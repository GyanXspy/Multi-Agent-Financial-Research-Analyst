"""
Caching layer — Redis-backed with in-memory fallback for local dev.

Features:
- get_or_set(key, ttl, coro): Cache-aside pattern with async coroutine
- Request coalescing (single-flight): if N requests hit the same key on a
  cold cache simultaneously, only ONE coroutine executes; the rest await
- Automatic fallback to TTLCache when Redis is unavailable
- JSON serialization for complex data structures
"""

import asyncio
import json
import logging
import time
from typing import Any, Callable, Coroutine, Dict, Optional

from app.config import settings

logger = logging.getLogger(__name__)

# Redis client — lazily initialized
_redis_client = None
_redis_available: Optional[bool] = None

# In-memory fallback (TTL cache)
_memory_cache: Dict[str, tuple[Any, float]] = {}  # key -> (value, expiry_timestamp)
_MAX_MEMORY_CACHE = 500  # max entries to prevent unbounded growth

# Request coalescing: in-flight futures per cache key
_inflight: Dict[str, asyncio.Future] = {}
_inflight_lock = asyncio.Lock()


async def get_redis():
    """Get or create the Redis client. Returns None if Redis unavailable."""
    global _redis_client, _redis_available

    if _redis_available is False:
        return None

    if _redis_client is not None:
        return _redis_client

    if not settings.REDIS_URL:
        _redis_available = False
        logger.info("Cache: no REDIS_URL configured, using in-memory fallback")
        return None

    try:
        import redis.asyncio as aioredis
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=5,
        )
        # Test connectivity
        await _redis_client.ping()
        _redis_available = True
        logger.info("Cache: connected to Redis at %s", settings.REDIS_URL)
        return _redis_client
    except Exception as e:
        logger.warning("Cache: Redis unavailable (%s), falling back to in-memory", e)
        _redis_available = False
        _redis_client = None
        return None


async def close_redis():
    """Close the Redis connection (call on shutdown)."""
    global _redis_client, _redis_available
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
        _redis_available = None


# ─── In-memory fallback ──────────────────────────────────────────────────────

def _mem_get(key: str) -> Optional[Any]:
    entry = _memory_cache.get(key)
    if entry is None:
        return None
    value, expiry = entry
    if time.time() > expiry:
        _memory_cache.pop(key, None)
        return None
    return value


def _mem_set(key: str, value: Any, ttl: int) -> None:
    # Evict expired entries if we're at capacity
    if len(_memory_cache) >= _MAX_MEMORY_CACHE:
        now = time.time()
        expired = [k for k, (_, exp) in _memory_cache.items() if now > exp]
        for k in expired:
            _memory_cache.pop(k, None)
        # If still at capacity, evict oldest
        if len(_memory_cache) >= _MAX_MEMORY_CACHE:
            oldest = min(_memory_cache, key=lambda k: _memory_cache[k][1])
            _memory_cache.pop(oldest, None)

    _memory_cache[key] = (value, time.time() + ttl)


# ─── Core cache API ──────────────────────────────────────────────────────────

async def get_or_set(
    key: str,
    ttl: int,
    factory: Callable[[], Coroutine[Any, Any, Any]],
) -> Any:
    """
    Cache-aside with request coalescing.

    If the key exists in cache, return it.
    If not, check if another coroutine is already computing this key.
    If yes, await that result. If no, compute it, cache it, return it.

    Args:
        key: Cache key (e.g. "fin:AAPL")
        ttl: Time-to-live in seconds
        factory: An async callable that produces the value

    Returns:
        The cached or freshly computed value
    """
    # 1. Try cache hit
    cached = await _cache_get(key)
    if cached is not None:
        logger.debug("Cache HIT: %s", key)
        return cached

    # 2. Request coalescing — check if someone else is computing this key
    async with _inflight_lock:
        if key in _inflight:
            logger.debug("Cache COALESCE: %s (waiting for in-flight)", key)
            future = _inflight[key]
        else:
            future = asyncio.get_event_loop().create_future()
            _inflight[key] = future
            future = None  # signal that WE are the executor

    if future is not None:
        # Wait for the other coroutine to finish
        return await future

    # 3. We are the executor — compute and cache
    try:
        logger.debug("Cache MISS: %s (computing)", key)
        value = await factory()
        await _cache_set(key, value, ttl)

        # Resolve all waiters
        async with _inflight_lock:
            inflight_future = _inflight.pop(key, None)
        if inflight_future is not None and not inflight_future.done():
            inflight_future.set_result(value)

        return value
    except Exception as e:
        # Reject all waiters
        async with _inflight_lock:
            inflight_future = _inflight.pop(key, None)
        if inflight_future is not None and not inflight_future.done():
            inflight_future.set_exception(e)
        raise


async def invalidate(key: str) -> None:
    """Remove a key from cache."""
    redis = await get_redis()
    if redis:
        try:
            await redis.delete(key)
        except Exception:
            pass
    _memory_cache.pop(key, None)


async def invalidate_pattern(pattern: str) -> None:
    """Remove all keys matching a pattern (e.g. 'fin:*')."""
    redis = await get_redis()
    if redis:
        try:
            async for key in redis.scan_iter(match=pattern):
                await redis.delete(key)
        except Exception:
            pass
    # In-memory: prefix match
    prefix = pattern.rstrip("*")
    to_remove = [k for k in _memory_cache if k.startswith(prefix)]
    for k in to_remove:
        _memory_cache.pop(k, None)


# ─── Internal helpers ─────────────────────────────────────────────────────────

async def _cache_get(key: str) -> Optional[Any]:
    """Try Redis first, fall back to memory."""
    redis = await get_redis()
    if redis:
        try:
            raw = await redis.get(key)
            if raw is not None:
                return json.loads(raw)
        except Exception as e:
            logger.warning("Cache Redis GET failed for %s: %s", key, e)

    return _mem_get(key)


async def _cache_set(key: str, value: Any, ttl: int) -> None:
    """Write to Redis and memory."""
    serialized = json.dumps(value, default=str)

    redis = await get_redis()
    if redis:
        try:
            await redis.setex(key, ttl, serialized)
        except Exception as e:
            logger.warning("Cache Redis SET failed for %s: %s", key, e)

    _mem_set(key, value, ttl)
