"""
FastAPI Main Application — Multi-Agent Financial Research Analyst

Wires together:
- Auth router      (/api/auth/*)      — register, login, me, list users, role changes
- Admin router     (/api/admin/*)     — user management, audit log, stats, settings
- Research router  (/api/research/*)  — analyze (REST), stream (SSE), history
- WebSocket        (/api/ws/stock/*)  — live price feed (JWT via ?token=)
Plus: CORS, security headers, rate limiting, and DB initialization.
"""

import asyncio
import contextlib
import logging
import re

import uvicorn
import yfinance as yf
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from sqlalchemy import select

from app.config import settings
from app.db import ROLE_ADMIN, ROLE_ANALYST, User, async_session_factory, init_db, is_admin_email
from app.rate_limit import limiter
from app.routers import admin as admin_router
from app.routers import auth as auth_router
from app.routers import research as research_router
from app.security import authenticate_websocket
from app.settings_store import seed_defaults

# --- Logging setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

SYMBOL_RE = re.compile(r"^\^?[A-Z0-9.\-]{1,12}$")


async def reconcile_admin() -> None:
    """
    Enforce the single-admin invariant on every startup:
    - the configured ADMIN_EMAIL, if it exists, is set to 'admin';
    - any other account left as 'admin' (e.g. from the old first-user rule) is
      demoted to 'analyst'.
    Also seed default system settings.
    """
    async with async_session_factory() as db:
        users = (await db.execute(select(User))).scalars().all()
        changed = False
        for user in users:
            if is_admin_email(user.email):
                if user.role != ROLE_ADMIN:
                    user.role = ROLE_ADMIN
                    changed = True
                    logger.info("Startup: promoted configured admin %s", user.email)
            elif user.role == ROLE_ADMIN:
                user.role = ROLE_ANALYST
                changed = True
                logger.warning("Startup: demoted stray admin %s -> analyst", user.email)
        if changed:
            await db.commit()
        await seed_defaults(db)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await reconcile_admin()
    logger.info("Database initialized")
    yield


app = FastAPI(
    title="Real-Time Multi-Agent Financial Research Analyst API",
    description="Coordinates specialized AI agents to produce investment research reports with live data streaming.",
    version="2.0.0",
    lifespan=lifespan,
)

# --- Rate limiting ---
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded. Please slow down."})


app.add_middleware(SlowAPIMiddleware)


# --- Security headers ---
# Docs/OpenAPI paths are excluded from strict CSP so Swagger UI can load its
# external CDN assets. All API responses still get the hardened policy.
DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if not request.url.path.startswith(DOCS_PATHS):
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        return response


app.add_middleware(SecurityHeadersMiddleware)

# --- CORS (restricted origins; wildcard + credentials is invalid & insecure) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# --- Routers ---
app.include_router(auth_router.router)
app.include_router(admin_router.router)
app.include_router(research_router.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket Live Price Feed
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_latest_bar(symbol: str) -> dict | None:
    """Blocking yfinance fetch — always call via asyncio.to_thread."""
    history = yf.Ticker(symbol).history(period="1d", interval="1m")
    if history.empty:
        return None
    latest = history.tail(1)
    return {
        "symbol": symbol,
        "price": round(float(latest["Close"].iloc[0]), 2),
        "open": round(float(latest["Open"].iloc[0]), 2),
        "high": round(float(latest["High"].iloc[0]), 2),
        "low": round(float(latest["Low"].iloc[0]), 2),
        "volume": int(latest["Volume"].iloc[0]),
        "timestamp": str(latest.index[0]),
    }


@app.websocket("/api/ws/stock/{symbol}")
async def websocket_stock_price(websocket: WebSocket, symbol: str):
    """
    Streams live price data for a symbol. Requires ?token=<JWT>.
    Fetches fresh 1-minute bars every 5 seconds without blocking the event loop.
    """
    await websocket.accept()

    async with async_session_factory() as db:
        user = await authenticate_websocket(websocket, db)
    if user is None:
        return

    symbol = symbol.upper().strip()
    if not SYMBOL_RE.match(symbol):
        await websocket.close(code=4400, reason="Invalid symbol format")
        return

    logger.info("WebSocket connected for %s (user=%s)", symbol, user.email)

    try:
        while True:
            try:
                price_data = await asyncio.to_thread(_fetch_latest_bar, symbol)
                if price_data:
                    await websocket.send_json(price_data)
                else:
                    await websocket.send_json({
                        "symbol": symbol,
                        "error": "Market may be closed — no intraday data available.",
                    })
            except WebSocketDisconnect:
                raise
            except RuntimeError:
                # Socket already closing/closed — stop the loop quietly
                break
            except Exception as e:
                logger.warning("WebSocket fetch error for %s: %s", symbol, e)
                await websocket.send_json({"symbol": symbol, "error": "Price fetch failed"})

            await asyncio.sleep(5.0)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for %s", symbol)
    except Exception as e:
        logger.error("WebSocket error for %s: %s", symbol, e)


# ─────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.RELOAD,
    )
