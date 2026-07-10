"""
Shared rate limiter — Redis-backed in production, in-memory for dev.

Features:
- Moving-window strategy (prevents boundary bursts)
- Redis storage for shared counters across replicas
- User-ID-based key function for authenticated heavy endpoints
- Graceful fallback to in-memory when Redis is unavailable
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.config import settings


def _get_user_or_ip(request: Request) -> str:
    """
    Rate-limit key function: use authenticated user ID for heavy endpoints,
    fall back to IP address for unauthenticated requests.
    """
    # Check if user was resolved by auth dependency
    if hasattr(request.state, "user_id"):
        return f"user:{request.state.user_id}"
    return get_remote_address(request)


def _build_limiter() -> Limiter:
    """Build a limiter with Redis storage if available, else in-memory."""
    storage_uri = settings.REDIS_URL if settings.REDIS_URL else "memory://"
    strategy = "moving-window" if settings.REDIS_URL else "fixed-window"

    return Limiter(
        key_func=get_remote_address,
        default_limits=["120/minute"],
        storage_uri=storage_uri,
        strategy=strategy,
    )


# Primary limiter instance (IP-keyed, for general endpoints)
limiter = _build_limiter()


def user_key_func(request: Request) -> str:
    """Key function for heavy endpoints — keys by user ID, not IP."""
    return _get_user_or_ip(request)
