"""
Research router — the multi-agent analysis endpoints.

Production features:
- Async job queue (ARQ): POST /analyze returns 202 with job_id
- GET /analyze/{job_id}: poll job status/result
- SSE streaming: subscribes to worker progress via Redis pub/sub
- Inline fallback when Redis/ARQ unavailable (dev mode)
- All results cached in Redis

Endpoints:
1. POST /api/research/analyze      — Enqueue analysis job (auth required)
2. GET  /api/research/analyze/{id} — Poll job status/result
3. GET  /api/research/stream       — SSE streaming (auth via ?token=)
4. GET  /api/research/history      — List past reports (own; admin sees all)
5. GET  /api/research/history/{id} — Fetch a stored report
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.agents.coordinator import CoordinatorAgent
from app.db import ROLE_ADMIN, Report, User, async_session_factory, get_db
from app.rate_limit import limiter, user_key_func
from app.schemas import (
    ReportDetail,
    ReportSummary,
    ResearchRequest,
    ResearchResponse,
)
from app.security import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/research", tags=["research"])

# Shared coordinator instance (agents are stateless between runs)
coordinator = CoordinatorAgent()


async def _save_report(user_id: int, symbol: str, query: str, report_md: str, data: dict) -> None:
    """Persist a completed analysis. Failures are logged, never raised to the client."""
    try:
        async with async_session_factory() as session:
            session.add(
                Report(
                    user_id=user_id,
                    symbol=symbol[:20],
                    query=query[:255],
                    report_md=report_md,
                    data_json=json.dumps(data, default=str),
                )
            )
            await session.commit()
    except Exception:
        logger.exception("Failed to persist report for user %s / %s", user_id, symbol)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Async Analysis Endpoint (Job Queue)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/analyze", response_model=ResearchResponse, status_code=200)
@limiter.limit("5/minute", key_func=user_key_func)
async def analyze_stock(
    request: Request,
    body: ResearchRequest,
    user: User = Depends(get_current_user),
):
    """
    Run the full multi-agent pipeline.

    When ARQ/Redis is available: enqueues the job and returns 202 with job_id.
    When unavailable (dev): runs inline and returns the complete result.
    """
    logger.info("REST /analyze — user=%s query=%s", user.email, body.query)

    # Try job queue first
    try:
        from app.job_queue import enqueue_analysis, run_inline, get_job_status
        from app.config import settings

        if settings.REDIS_URL:
            # Production mode: enqueue and return immediately
            result = await enqueue_analysis(user.id, body.query, body.query)

            if result.get("status") == "rejected":
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=result.get("message", "Too many concurrent analyses"),
                )

            # Return 202 Accepted with job_id for polling
            from starlette.responses import JSONResponse
            return JSONResponse(
                status_code=202,
                content={
                    "job_id": result["job_id"],
                    "status": result["status"],
                    "message": "Analysis queued. Poll GET /api/research/analyze/{job_id} for results.",
                },
            )
    except ImportError:
        pass
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Job queue unavailable (%s), falling back to inline execution", e)

    # Fallback: inline execution (dev mode / no Redis)
    try:
        result = await coordinator.run(body.query)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception:
        logger.exception("REST /analyze failed")
        raise HTTPException(status_code=500, detail="Internal server error")

    await _save_report(user.id, result["symbol"], body.query, result["report"], result["data"])

    return ResearchResponse(
        symbol=result["symbol"],
        data=result["data"],
        report=result["report"],
        errors=result.get("errors"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1b. Job Status Polling
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/analyze/{job_id}")
async def get_analysis_status(
    job_id: str,
    user: User = Depends(get_current_user),
):
    """Poll the status of an enqueued analysis job."""
    try:
        from app.job_queue import get_job_status
        result = await get_job_status(job_id)
        return result
    except Exception as e:
        logger.warning("Job status check failed for %s: %s", job_id, e)
        return {"status": "unknown", "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# 2. SSE Streaming Endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/stream")
@limiter.limit("5/minute", key_func=user_key_func)
async def stream_analysis(
    request: Request,
    query: str = Query(..., min_length=1, max_length=200),
    user: User = Depends(get_current_user),
):
    """
    Server-Sent Events endpoint streaming:
    'status' | 'data' | 'report_chunk' | 'done' | 'error' events.
    Auth: pass the JWT as ?token= (EventSource cannot set headers) or Bearer header.
    """
    logger.info("SSE /stream — user=%s query=%s", user.email, query)
    clean_query = query.strip()

    async def event_generator():
        try:
            # ── Step 1: Resolve ticker ──
            yield {"event": "status", "data": "Coordinator identifying stock ticker..."}
            try:
                symbol = await coordinator.identify_ticker(clean_query)
            except ValueError as e:
                yield {"event": "error", "data": str(e)}
                return
            yield {"event": "status", "data": f"Ticker identified: {symbol}. Launching agent pipeline..."}

            # ── Step 2: Launch worker agents in parallel ──
            yield {"event": "status", "data": "Starting Financial Data, News, Filings, and Peer Comparison agents..."}

            financials_task = asyncio.create_task(coordinator.financial_agent.collect(symbol))
            news_task = asyncio.create_task(coordinator.news_agent.collect(symbol))
            filings_task = asyncio.create_task(coordinator.filings_agent.collect(symbol))
            peers_task = asyncio.create_task(coordinator.peer_agent.collect(symbol))

            all_tasks = [financials_task, news_task, filings_task, peers_task]
            agent_names = ["Financial Data", "News", "Filings", "Peer Comparison"]

            reported_done: set[str] = set()
            while not all(t.done() for t in all_tasks):
                await asyncio.sleep(1.0)
                completed = {name for name, t in zip(agent_names, all_tasks) if t.done()}
                newly_done = completed - reported_done
                for name in sorted(newly_done):
                    yield {"event": "status", "data": f"{name} agent completed."}
                reported_done = completed
                pending = [name for name, t in zip(agent_names, all_tasks) if not t.done()]
                if pending:
                    yield {"event": "status", "data": f"Running: [{', '.join(pending)}]"}

            # ── Step 3: Aggregate results ──
            yield {"event": "status", "data": "All worker agents completed. Aggregating data..."}

            errors = {}

            def safe_result(task, name):
                try:
                    return task.result()
                except Exception as e:
                    logger.error("SSE agent %s failed: %s", name, e)
                    errors[name] = str(e)
                    return {}

            aggregated_data = {
                "symbol": symbol,
                "financials": safe_result(financials_task, "financial_data"),
                "news": safe_result(news_task, "news"),
                "filings": safe_result(filings_task, "filings"),
                "peers": safe_result(peers_task, "peer_comparison"),
            }

            yield {"event": "data", "data": json.dumps(aggregated_data, default=str)}

            if errors:
                for agent_name, error_msg in errors.items():
                    yield {"event": "status", "data": f"\u26a0 {agent_name} agent error: {error_msg}"}

            # ── Step 4: Stream the report ──
            yield {"event": "status", "data": "Thesis Writer Agent generating investment report..."}

            report_parts: list[str] = []
            async for chunk in coordinator.thesis_agent.stream_report(aggregated_data):
                report_parts.append(chunk)
                yield {"event": "report_chunk", "data": chunk}

            await _save_report(user.id, symbol, clean_query, "".join(report_parts), aggregated_data)

            yield {"event": "status", "data": "Analysis complete."}
            yield {"event": "done", "data": "true"}

        except Exception:
            logger.exception("SSE /stream failed")
            yield {"event": "error", "data": "Analysis pipeline failed. Please try again."}

    return EventSourceResponse(event_generator())


# ─────────────────────────────────────────────────────────────────────────────
# 3. Report history
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/history", response_model=list[ReportSummary])
async def report_history(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=25, ge=1, le=100),
):
    """List past reports — analysts see their own; admins see everyone's."""
    stmt = select(Report).order_by(Report.created_at.desc()).limit(limit)
    if user.role != ROLE_ADMIN:
        stmt = stmt.where(Report.user_id == user.id)
    result = await db.execute(stmt)
    return [ReportSummary.model_validate(r) for r in result.scalars().all()]


@router.get("/history/{report_id}", response_model=ReportDetail)
async def report_detail(
    report_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if user.role != ROLE_ADMIN and report.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this report")
    return ReportDetail.model_validate(report)
