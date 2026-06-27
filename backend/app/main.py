"""
FastAPI Main Application — Multi-Agent Financial Research Analyst

Exposes three endpoint types:
1. POST /api/research/analyze  — Blocking REST endpoint
2. GET  /api/research/stream   — SSE streaming (agent status + report tokens)
3. WS   /api/ws/stock/{symbol} — WebSocket live price feed
"""

import asyncio
import json
import logging

import uvicorn
import yfinance as yf
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from app.agents.coordinator import CoordinatorAgent
from app.schemas import ResearchRequest, ResearchResponse

# --- Logging setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# --- FastAPI app ---
app = FastAPI(
    title="Real-Time Multi-Agent Financial Research Analyst API",
    description="Coordinates specialized AI agents to produce investment research reports with live data streaming.",
    version="1.0.0",
)

# --- CORS middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to specific domains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Shared coordinator instance ---
coordinator = CoordinatorAgent()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Blocking REST Endpoint
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/research/analyze", response_model=ResearchResponse)
async def analyze_stock(request: ResearchRequest):
    """
    Run the full multi-agent pipeline and return the complete research report.
    This is a blocking request — waits for all agents to complete.
    """
    logger.info("REST /analyze — query: %s", request.query)
    try:
        result = await coordinator.run(request.query)
        return ResearchResponse(
            symbol=result["symbol"],
            data=result["data"],
            report=result["report"],
            errors=result.get("errors"),
        )
    except Exception as e:
        logger.exception("REST /analyze failed")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# 2. SSE Streaming Endpoint (Agent Status + Report Token Stream)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/research/stream")
async def stream_analysis(query: str):
    """
    Server-Sent Events (SSE) endpoint that streams:
    - 'status'       — pipeline stage updates
    - 'data'         — aggregated financial data (JSON)
    - 'report_chunk' — streaming report text tokens
    - 'done'         — completion signal
    - 'error'        — error messages
    """
    logger.info("SSE /stream — query: %s", query)

    async def event_generator():
        try:
            # ── Step 1: Resolve ticker ──
            yield {"event": "status", "data": "Coordinator identifying stock ticker..."}
            symbol = await coordinator._identify_ticker(query)
            yield {"event": "status", "data": f"Ticker identified: {symbol}. Launching agent pipeline..."}

            # ── Step 2: Launch worker agents in parallel ──
            yield {"event": "status", "data": "Starting Financial Data, News, Filings, and Peer Comparison agents..."}

            financials_task = asyncio.create_task(coordinator.financial_agent.collect(symbol))
            news_task = asyncio.create_task(coordinator.news_agent.collect(symbol))
            filings_task = asyncio.create_task(coordinator.filings_agent.collect(symbol))
            peers_task = asyncio.create_task(coordinator.peer_agent.collect(symbol))

            all_tasks = [financials_task, news_task, filings_task, peers_task]
            agent_names = ["Financial Data", "News", "Filings", "Peer Comparison"]

            # Poll until all tasks complete, sending heartbeat status updates
            while not all(t.done() for t in all_tasks):
                await asyncio.sleep(1.0)
                completed = [name for name, t in zip(agent_names, all_tasks) if t.done()]
                pending = [name for name, t in zip(agent_names, all_tasks) if not t.done()]
                status_msg = f"Completed: [{', '.join(completed) or 'none'}] | Running: [{', '.join(pending)}]"
                yield {"event": "status", "data": status_msg}

            # ── Step 3: Aggregate results ──
            yield {"event": "status", "data": "All worker agents completed. Aggregating data..."}

            errors = {}

            def safe_result(task, name):
                try:
                    return task.result()
                except Exception as e:
                    errors[name] = str(e)
                    return {}

            aggregated_data = {
                "symbol": symbol,
                "financials": safe_result(financials_task, "financial_data"),
                "news": safe_result(news_task, "news"),
                "filings": safe_result(filings_task, "filings"),
                "peers": safe_result(peers_task, "peer_comparison"),
            }

            # Send the aggregated data to the frontend (populates metrics cards)
            yield {"event": "data", "data": json.dumps(aggregated_data, default=str)}

            if errors:
                yield {"event": "status", "data": f"Warning: {len(errors)} agent(s) had errors: {list(errors.keys())}"}

            # ── Step 4: Stream the report ──
            yield {"event": "status", "data": "Thesis Writer Agent generating investment report..."}

            async for chunk in coordinator.thesis_agent.stream_report(aggregated_data):
                yield {"event": "report_chunk", "data": chunk}

            yield {"event": "status", "data": "Analysis complete."}
            yield {"event": "done", "data": "true"}

        except Exception as e:
            logger.exception("SSE /stream failed")
            yield {"event": "error", "data": str(e)}

    return EventSourceResponse(event_generator())


# ─────────────────────────────────────────────────────────────────────────────
# 3. WebSocket Live Price Feed
# ─────────────────────────────────────────────────────────────────────────────

@app.websocket("/api/ws/stock/{symbol}")
async def websocket_stock_price(websocket: WebSocket, symbol: str):
    """
    WebSocket endpoint that streams live stock price data every second.
    Uses yfinance 1-minute interval bars for the current trading day.
    """
    await websocket.accept()
    logger.info("WebSocket connected for %s", symbol)

    try:
        ticker = yf.Ticker(symbol)

        while True:
            try:
                history = ticker.history(period="1d", interval="1m")
                if not history.empty:
                    latest_bar = history.tail(1)
                    price_data = {
                        "symbol": symbol,
                        "price": round(float(latest_bar["Close"].iloc[0]), 2),
                        "open": round(float(latest_bar["Open"].iloc[0]), 2),
                        "high": round(float(latest_bar["High"].iloc[0]), 2),
                        "low": round(float(latest_bar["Low"].iloc[0]), 2),
                        "volume": int(latest_bar["Volume"].iloc[0]),
                        "timestamp": str(latest_bar.index[0]),
                    }
                    await websocket.send_json(price_data)
                else:
                    await websocket.send_json({
                        "symbol": symbol,
                        "error": "Market may be closed — no intraday data available.",
                    })
            except WebSocketDisconnect:
                break
            except RuntimeError as e:
                if "Cannot call" in str(e) or "close message has been sent" in str(e):
                    break
                await websocket.send_json({"symbol": symbol, "error": str(e)})
            except Exception as e:
                await websocket.send_json({"symbol": symbol, "error": str(e)})

            await asyncio.sleep(1.0)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for %s", symbol)
    except Exception as e:
        logger.error("WebSocket error for %s: %s", symbol, e)


# ─────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from app.config import settings

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.RELOAD,
    )
