"""
ARQ worker — background job processor for heavy analysis pipelines.

Run with:
    arq app.worker.WorkerSettings

The worker executes analysis pipelines outside the web tier, bounded by
MAX_CONCURRENT_ANALYSES.  Progress is published to Redis pub/sub so SSE
subscribers on the web tier can stream updates to clients.
"""

import json
import logging
from typing import Any, Dict

from app.config import settings

logger = logging.getLogger(__name__)


async def run_analysis(
    ctx: Dict[str, Any],
    *,
    user_id: int,
    symbol: str,
    query: str,
    job_id: str,
) -> Dict[str, Any]:
    """
    Execute the full multi-agent analysis pipeline as a background job.
    Publishes progress events to Redis pub/sub channel `job:{job_id}`.
    """
    from app.agents.coordinator import CoordinatorAgent
    from app.job_queue import publish_progress

    logger.info("Worker: starting analysis job %s for user=%d symbol=%s", job_id, user_id, symbol)

    try:
        await publish_progress(job_id, "status", "Starting analysis pipeline...")

        coordinator = CoordinatorAgent()

        # Step 1: Identify ticker
        await publish_progress(job_id, "status", "Identifying stock ticker...")
        resolved_symbol = await coordinator.identify_ticker(query)
        await publish_progress(job_id, "status", f"Ticker identified: {resolved_symbol}")

        # Step 2: Run agents in parallel
        await publish_progress(job_id, "status", "Launching worker agents...")

        import asyncio
        tasks = [
            coordinator.financial_agent.collect(resolved_symbol),
            coordinator.news_agent.collect(resolved_symbol),
            coordinator.filings_agent.collect(resolved_symbol),
            coordinator.peer_agent.collect(resolved_symbol),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Step 3: Aggregate
        errors: Dict[str, str] = {}
        agent_names = ["financial_data", "news", "filings", "peer_comparison"]

        def _safe(idx, name):
            if isinstance(results[idx], Exception):
                logger.error("Worker: %s agent failed: %s", name, results[idx])
                errors[name] = str(results[idx])
                return {}
            return results[idx]

        aggregated = {
            "symbol": resolved_symbol,
            "financials": _safe(0, "financial_data"),
            "news": _safe(1, "news"),
            "filings": _safe(2, "filings"),
            "peers": _safe(3, "peer_comparison"),
        }

        await publish_progress(job_id, "data", json.dumps(aggregated, default=str))
        await publish_progress(job_id, "status", "Generating investment report...")

        # Step 4: Generate report
        report = await coordinator.thesis_agent.generate_report(aggregated)

        # Step 5: Save to database
        try:
            from app.db import async_session_factory, Report
            async with async_session_factory() as session:
                session.add(Report(
                    user_id=user_id,
                    symbol=resolved_symbol[:20],
                    query=query[:255],
                    report_md=report,
                    data_json=json.dumps(aggregated, default=str),
                ))
                await session.commit()
        except Exception:
            logger.exception("Worker: failed to persist report for job %s", job_id)

        result = {
            "symbol": resolved_symbol,
            "data": aggregated,
            "report": report,
            "errors": errors if errors else None,
        }

        await publish_progress(job_id, "done", json.dumps(result, default=str))
        logger.info("Worker: job %s completed successfully", job_id)
        return result

    except Exception as e:
        logger.exception("Worker: job %s failed", job_id)
        await publish_progress(job_id, "error", str(e))
        raise


async def startup(ctx: Dict[str, Any]) -> None:
    """Worker startup hook — initialize DB engine, logging."""
    from app.logging_config import setup_logging
    setup_logging(settings.LOG_FORMAT)
    logger.info("ARQ worker started (max_jobs=%d)", settings.MAX_CONCURRENT_ANALYSES)


async def shutdown(ctx: Dict[str, Any]) -> None:
    """Worker shutdown hook — cleanup."""
    from app.cache import close_redis
    await close_redis()
    logger.info("ARQ worker shut down")


class WorkerSettings:
    """ARQ worker configuration."""
    functions = [run_analysis]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = settings.MAX_CONCURRENT_ANALYSES
    job_timeout = 300  # 5 minute max per job
    redis_settings = None  # Set dynamically below


# Configure Redis settings if available
if settings.REDIS_URL:
    try:
        from arq.connections import RedisSettings
        WorkerSettings.redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    except Exception:
        pass
