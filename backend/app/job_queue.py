"""
Job queue helpers — enqueue analysis jobs and query their status.

When Redis/ARQ is available, jobs run asynchronously in the worker pool.
When unavailable (local dev without Redis), falls back to inline execution.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.config import settings

logger = logging.getLogger(__name__)

# In-memory job store for fallback mode
_jobs: Dict[str, Dict[str, Any]] = {}

# Job status constants
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_COMPLETE = "complete"
STATUS_FAILED = "failed"


async def _get_arq_pool():
    """Get or create the ARQ Redis pool. Returns None if unavailable."""
    if not settings.REDIS_URL:
        return None
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        # Parse redis URL
        return await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
    except Exception as e:
        logger.warning("ARQ pool creation failed: %s", e)
        return None


async def enqueue_analysis(
    user_id: int,
    symbol: str,
    query: str,
) -> Dict[str, Any]:
    """
    Enqueue an analysis job.

    Returns:
        Dict with 'job_id' and 'status'
    """
    job_id = uuid.uuid4().hex[:16]

    # Try ARQ first
    pool = await _get_arq_pool()
    if pool is not None:
        try:
            # Check per-user concurrency
            user_jobs = await _count_user_jobs(pool, user_id)
            if user_jobs >= settings.MAX_USER_CONCURRENT:
                return {
                    "job_id": None,
                    "status": "rejected",
                    "message": f"You already have {user_jobs} analyses in progress. "
                               f"Maximum is {settings.MAX_USER_CONCURRENT}.",
                }

            await pool.enqueue_job(
                "run_analysis",
                user_id=user_id,
                symbol=symbol,
                query=query,
                job_id=job_id,
                _job_id=job_id,
            )
            logger.info("Job %s enqueued for user=%d symbol=%s", job_id, user_id, symbol)
            return {"job_id": job_id, "status": STATUS_QUEUED}
        except Exception as e:
            logger.warning("ARQ enqueue failed: %s, falling back to inline", e)
        finally:
            await pool.aclose()

    # Fallback: store job metadata for inline execution
    _jobs[job_id] = {
        "status": STATUS_QUEUED,
        "user_id": user_id,
        "symbol": symbol,
        "query": query,
        "result": None,
        "error": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    logger.info("Job %s stored in-memory (no ARQ) for user=%d symbol=%s", job_id, user_id, symbol)
    return {"job_id": job_id, "status": STATUS_QUEUED}


async def get_job_status(job_id: str) -> Dict[str, Any]:
    """
    Get the status of a job.

    Returns:
        Dict with 'status', and optionally 'result' or 'error'
    """
    # Try ARQ first
    pool = await _get_arq_pool()
    if pool is not None:
        try:
            from arq.jobs import Job
            job = Job(job_id, pool)
            info = await job.info()
            if info is None:
                await pool.aclose()
                return {"status": "not_found"}

            status_map = {
                "deferred": STATUS_QUEUED,
                "queued": STATUS_QUEUED,
                "in_progress": STATUS_RUNNING,
                "complete": STATUS_COMPLETE,
            }

            result = {
                "status": status_map.get(str(info.status), STATUS_FAILED),
            }

            if info.result is not None:
                result["result"] = info.result
            if info.status == "complete" and info.success is False:
                result["status"] = STATUS_FAILED
                result["error"] = str(info.result) if info.result else "Unknown error"

            await pool.aclose()
            return result
        except Exception as e:
            logger.warning("ARQ job status check failed: %s", e)
            if pool:
                await pool.aclose()

    # Fallback: check in-memory store
    job = _jobs.get(job_id)
    if job is None:
        return {"status": "not_found"}

    result = {"status": job["status"]}
    if job["result"] is not None:
        result["result"] = job["result"]
    if job["error"] is not None:
        result["error"] = job["error"]
    return result


async def run_inline(job_id: str, user_id: int, symbol: str, query: str) -> Dict[str, Any]:
    """
    Run an analysis inline (fallback when ARQ unavailable).
    Updates the in-memory job store with progress.
    """
    from app.agents.coordinator import CoordinatorAgent

    job = _jobs.get(job_id)
    if job:
        job["status"] = STATUS_RUNNING

    try:
        coordinator = CoordinatorAgent()
        result = await coordinator.run(query)

        if job:
            job["status"] = STATUS_COMPLETE
            job["result"] = result

        return result
    except Exception as e:
        if job:
            job["status"] = STATUS_FAILED
            job["error"] = str(e)
        raise


async def publish_progress(job_id: str, event: str, data: str) -> None:
    """Publish job progress to Redis pub/sub (for SSE subscribers)."""
    from app.cache import get_redis

    redis = await get_redis()
    if redis:
        try:
            msg = json.dumps({"event": event, "data": data})
            await redis.publish(f"job:{job_id}", msg)
        except Exception as e:
            logger.warning("Progress publish failed for job %s: %s", job_id, e)


async def subscribe_progress(job_id: str):
    """
    Async generator that yields progress events for a job.
    Uses Redis pub/sub if available, otherwise polls in-memory status.
    """
    from app.cache import get_redis

    redis = await get_redis()
    if redis:
        try:
            pubsub = redis.pubsub()
            await pubsub.subscribe(f"job:{job_id}")
            try:
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        data = json.loads(message["data"])
                        yield data
                        if data.get("event") in ("done", "error"):
                            break
            finally:
                await pubsub.unsubscribe(f"job:{job_id}")
                await pubsub.aclose()
            return
        except Exception as e:
            logger.warning("Redis pub/sub failed for job %s: %s, falling back to polling", job_id, e)

    # Fallback: poll in-memory job status
    while True:
        job = _jobs.get(job_id)
        if job is None:
            yield {"event": "error", "data": "Job not found"}
            break
        if job["status"] == STATUS_COMPLETE:
            yield {"event": "done", "data": json.dumps(job.get("result", {}), default=str)}
            break
        if job["status"] == STATUS_FAILED:
            yield {"event": "error", "data": job.get("error", "Unknown error")}
            break
        yield {"event": "status", "data": f"Job status: {job['status']}"}
        await asyncio.sleep(2)


async def _count_user_jobs(pool, user_id: int) -> int:
    """Count in-flight jobs for a user (ARQ mode)."""
    try:
        from arq.jobs import Job
        # Check queued jobs
        jobs = await pool.queued_jobs()
        count = 0
        for job_info in jobs:
            if hasattr(job_info, 'kwargs') and job_info.kwargs.get('user_id') == user_id:
                count += 1
        return count
    except Exception:
        return 0
