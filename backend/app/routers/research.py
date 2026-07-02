"""
Research router — the multi-agent analysis endpoints.

1. POST /api/research/analyze      — Blocking REST endpoint (auth required)
2. GET  /api/research/stream       — SSE streaming (auth via ?token=)
3. GET  /api/research/history      — List past reports (own; admin sees all)
4. GET  /api/research/history/{id} — Fetch a stored report
Completed analyses are persisted to the reports table.
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
from app.rate_limit import limiter
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
# 1. Blocking REST Endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/analyze", response_model=ResearchResponse)
@limiter.limit("5/minute")
async def analyze_stock(
    request: Request,
    body: ResearchRequest,
    user: User = Depends(get_current_user),
):
    """Run the full multi-agent pipeline and return the complete research report."""
    logger.info("REST /analyze — user=%s query=%s", user.email, body.query)
    try:
        result = await coordinator.run(body.query)
    except ValueError as e:
        # Ticker resolution/validation failures are client errors
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
# 2. SSE Streaming Endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/stream")
@limiter.limit("5/minute")
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
                yield {"event": "status", "data": f"Warning: {len(errors)} agent(s) had errors: {list(errors.keys())}"}

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
