"""
FastAPI Main Application — Multi-Agent Financial Research Analyst

Production-ready wiring:
- Structured JSON logging with request IDs
- Prometheus metrics at /metrics
- Deep healthcheck at /api/health/ready (DB + Redis)
- Redis-backed rate limiting with Retry-After headers
- Security headers middleware
- WebSocket with shared price feed (Redis pub/sub when available)
- CORS, auth, admin, research routers
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
from starlette.requests import Request
from starlette.responses import JSONResponse

from sqlalchemy import select, text

from app.config import settings
from app.db import ROLE_ADMIN, ROLE_ANALYST, User, async_session_factory, init_db, normalize_email
from app.logging_config import setup_logging
from app.middleware import RequestIdMiddleware, SecurityHeadersMiddleware
from app.rate_limit import limiter
from app.routers import admin as admin_router
from app.routers import auth as auth_router
from app.routers import research as research_router
from app.security import authenticate_websocket
from app.settings_store import seed_defaults

# --- Structured logging setup ---
setup_logging(log_format=settings.LOG_FORMAT)
logger = logging.getLogger(__name__)

SYMBOL_RE = re.compile(r"^\^?[A-Z0-9.\-]{1,12}$")


async def reconcile_admin() -> None:
    """
    Enforce the single-admin invariant on every startup with targeted queries
    instead of loading the full user table:
    1. Promote the configured ADMIN_EMAIL to 'admin' if it exists but isn't admin.
    2. Demote any other accounts that are still marked 'admin'.
    Also seed default system settings.
    """
    admin_email = normalize_email(settings.ADMIN_EMAIL)
    async with async_session_factory() as db:
        changed = False

        # Promote the designated admin if they exist but lack the admin role
        result = await db.execute(
            select(User).where(User.email == admin_email, User.role != ROLE_ADMIN)
        )
        admin_user = result.scalar_one_or_none()
        if admin_user is not None:
            admin_user.role = ROLE_ADMIN
            changed = True
            logger.info("Startup: promoted configured admin %s", admin_user.email)

        # Demote any stray admins (accounts that shouldn't be admin)
        result = await db.execute(
            select(User).where(User.email != admin_email, User.role == ROLE_ADMIN)
        )
        for user in result.scalars().all():
            user.role = ROLE_ANALYST
            changed = True
            logger.warning("Startup: demoted stray admin %s -> analyst", user.email)

        if changed:
            await db.commit()
        await seed_defaults(db)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    await init_db()
    await reconcile_admin()
    logger.info("Database initialized")

    # Initialize Redis connection (best-effort)
    try:
        from app.cache import get_redis
        redis = await get_redis()
        if redis:
            logger.info("Redis connected")
    except Exception as e:
        logger.warning("Redis connection failed (caching/queue will use in-memory fallback): %s", e)

    # Initialize Sentry if configured
    if settings.SENTRY_DSN:
        try:
            import sentry_sdk
            sentry_sdk.init(
                dsn=settings.SENTRY_DSN,
                traces_sample_rate=0.1,
                environment=settings.ENVIRONMENT,
            )
            logger.info("Sentry initialized")
        except Exception as e:
            logger.warning("Sentry initialization failed: %s", e)

    yield

    # --- Shutdown ---
    try:
        from app.cache import close_redis
        await close_redis()
    except Exception:
        pass
    logger.info("Application shutdown complete")


app = FastAPI(
    title="Real-Time Multi-Agent Financial Research Analyst API",
    description="Coordinates specialized AI agents to produce investment research reports with live data streaming.",
    version="3.0.0",
    lifespan=lifespan,
)

# --- Rate limiting ---
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Return 429 with Retry-After and X-RateLimit-* headers for intelligent backoff."""
    retry_after = getattr(exc, "retry_after", 60)
    headers = {
        "Retry-After": str(retry_after),
        "X-RateLimit-Limit": str(getattr(exc, "limit", "unknown")),
    }
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Rate limit exceeded. Please slow down.",
            "retry_after": retry_after,
        },
        headers=headers,
    )


app.add_middleware(SlowAPIMiddleware)

# --- Middleware stack (order matters: outermost first) ---
app.add_middleware(RequestIdMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

# --- CORS (restricted origins; wildcard + credentials is invalid & insecure) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# --- Prometheus metrics ---
try:
    from prometheus_fastapi_instrumentator import Instrumentator
    instrumentator = Instrumentator(
        should_group_status_codes=True,
        excluded_handlers=["/api/health", "/api/health/ready", "/metrics"],
    )
    instrumentator.instrument(app).expose(app, endpoint="/metrics")
    logger.info("Prometheus metrics enabled at /metrics")
except ImportError:
    logger.info("prometheus-fastapi-instrumentator not installed, /metrics disabled")

# --- Routers ---
app.include_router(auth_router.router)
app.include_router(admin_router.router)
app.include_router(research_router.router)


# ─────────────────────────────────────────────────────────────────────────────
# Health checks
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    """Lightweight liveness check — always responds if the process is up."""
    return {"status": "ok"}


@app.get("/api/health/ready")
async def health_ready():
    """
    Deep readiness check — verifies DB and Redis connectivity.
    Used by load balancers to determine if this replica should receive traffic.
    """
    checks = {}

    # Check database
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    # Check Redis
    try:
        from app.cache import get_redis
        redis = await get_redis()
        if redis:
            await redis.ping()
            checks["redis"] = "ok"
        else:
            checks["redis"] = "not configured"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    all_ok = all(v == "ok" or v == "not configured" for v in checks.values())

    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={"status": "ready" if all_ok else "degraded", "checks": checks},
    )


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket Live Price Feed — shared subscription manager
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


class PriceSubscriptionManager:
    """
    Shares a single polling loop per symbol across all connected WebSocket
    clients.  When the first client subscribes to a symbol a background task
    is created; when the last client unsubscribes, the task is cancelled.

    Supports Redis pub/sub for cross-replica price feed when Redis is available.
    """

    def __init__(self, poll_interval: float = None):
        self._poll_interval = poll_interval or settings.WS_POLL_INTERVAL
        # symbol -> set of WebSocket objects
        self._subscribers: dict[str, set[WebSocket]] = {}
        # symbol -> background polling Task
        self._tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()
        # Per-user connection tracking
        self._user_connections: dict[str, int] = {}  # user_email -> count

    async def subscribe(self, symbol: str, ws: WebSocket, user_email: str = "") -> bool:
        """Subscribe a WebSocket to a symbol's price feed. Returns False if connection limit exceeded."""
        # Check per-user connection limit
        if user_email:
            current = self._user_connections.get(user_email, 0)
            if current >= settings.WS_MAX_CONNECTIONS_PER_USER:
                return False
            self._user_connections[user_email] = current + 1

        async with self._lock:
            if symbol not in self._subscribers:
                self._subscribers[symbol] = set()
            self._subscribers[symbol].add(ws)
            if symbol not in self._tasks or self._tasks[symbol].done():
                self._tasks[symbol] = asyncio.create_task(self._poll_loop(symbol))

        return True

    async def unsubscribe(self, symbol: str, ws: WebSocket, user_email: str = "") -> None:
        if user_email:
            current = self._user_connections.get(user_email, 0)
            if current > 0:
                self._user_connections[user_email] = current - 1

        async with self._lock:
            subs = self._subscribers.get(symbol)
            if subs:
                subs.discard(ws)
                if not subs:
                    del self._subscribers[symbol]
                    task = self._tasks.pop(symbol, None)
                    if task and not task.done():
                        task.cancel()

    async def _poll_loop(self, symbol: str) -> None:
        """Fetch price data on a schedule and broadcast to all subscribers."""
        while True:
            try:
                price_data = await asyncio.wait_for(
                    asyncio.to_thread(_fetch_latest_bar, symbol),
                    timeout=settings.YFINANCE_TIMEOUT,
                )
                payload = price_data or {
                    "symbol": symbol,
                    "error": "Market may be closed — no intraday data available.",
                }
            except asyncio.TimeoutError:
                logger.warning("Price fetch timeout for %s", symbol)
                payload = {"symbol": symbol, "error": "Price fetch timed out"}
            except Exception as e:
                logger.warning("Price fetch error for %s: %s", symbol, e)
                payload = {"symbol": symbol, "error": "Price fetch failed"}

            # Publish to Redis pub/sub for cross-replica fanout
            try:
                from app.cache import get_redis
                import json
                redis = await get_redis()
                if redis:
                    await redis.publish(f"price:{symbol}", json.dumps(payload))
            except Exception:
                pass

            # Broadcast to all local subscribers; collect stale connections for cleanup
            async with self._lock:
                subs = self._subscribers.get(symbol, set()).copy()
            stale: list[WebSocket] = []
            for ws in subs:
                try:
                    await ws.send_json(payload)
                except Exception:
                    stale.append(ws)
            if stale:
                async with self._lock:
                    current = self._subscribers.get(symbol)
                    if current:
                        for ws in stale:
                            current.discard(ws)
                        if not current:
                            del self._subscribers[symbol]
                            task = self._tasks.pop(symbol, None)
                            if task and not task.done():
                                task.cancel()
                            return

            await asyncio.sleep(self._poll_interval)


# Singleton manager
price_manager = PriceSubscriptionManager()


@app.websocket("/api/ws/stock/{symbol}")
async def websocket_stock_price(websocket: WebSocket, symbol: str):
    """
    Streams live price data for a symbol.  Requires ?token=<JWT>.
    Authentication is validated BEFORE accepting the connection to prevent
    unauthenticated connection floods (F5 fix).
    """
    # ── Validate symbol format before any connection work ──
    symbol = symbol.upper().strip()
    if not SYMBOL_RE.match(symbol):
        await websocket.close(code=4400, reason="Invalid symbol format")
        return

    # ── Authenticate BEFORE accepting (F5) ──
    async with async_session_factory() as db:
        user = await authenticate_websocket(websocket, db)
    if user is None:
        return  # authenticate_websocket already sent close(4401)

    # ── Accept only after successful auth ──
    await websocket.accept()
    logger.info("WebSocket connected for %s (user=%s)", symbol, user.email)

    # ── Subscribe to the shared price feed with connection limit check ──
    subscribed = await price_manager.subscribe(symbol, websocket, user.email)
    if not subscribed:
        await websocket.send_json({
            "error": f"Connection limit exceeded ({settings.WS_MAX_CONNECTIONS_PER_USER} max per user)"
        })
        await websocket.close(code=4429, reason="Too many connections")
        return

    try:
        # Keep the connection alive; the subscription manager handles sending.
        while True:
            # Wait for client messages (pong/close); ignore content.
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for %s (user=%s)", symbol, user.email)
    except Exception as e:
        logger.error("WebSocket error for %s: %s", symbol, e)
    finally:
        await price_manager.unsubscribe(symbol, websocket, user.email)


# ─────────────────────────────────────────────────────────────────────────────
# Entrypoint (development only)
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.RELOAD,
    )
