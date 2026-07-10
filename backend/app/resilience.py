"""
Resilience utilities — timeouts, retries, and circuit breakers for LLM and
upstream API calls.

Wraps langchain ainvoke/astream with tenacity retry + asyncio timeout so
a single hung Gemini call can never stall the entire pipeline.
"""

import asyncio
import logging
from typing import Any, AsyncIterator

from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings

logger = logging.getLogger(__name__)

# Exceptions that are worth retrying (transient)
RETRYABLE_EXCEPTIONS = (
    asyncio.TimeoutError,
    ConnectionError,
    OSError,
)


async def resilient_ainvoke(
    llm,
    prompt: str,
    *,
    timeout: int | None = None,
    max_retries: int | None = None,
    label: str = "LLM",
) -> Any:
    """
    Call llm.ainvoke(prompt) with a timeout and retry policy.

    Args:
        llm: A langchain LLM instance
        prompt: The prompt string
        timeout: Seconds before timing out (default: settings.LLM_TIMEOUT)
        max_retries: Max retry attempts (default: settings.LLM_MAX_RETRIES)
        label: Human-readable name for logging

    Returns:
        The LLM response object

    Raises:
        asyncio.TimeoutError: If all retries are exhausted and still timing out
        Exception: The last exception if retries are exhausted
    """
    _timeout = timeout or settings.LLM_TIMEOUT
    _retries = max_retries or settings.LLM_MAX_RETRIES

    @retry(
        retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
        stop=stop_after_attempt(_retries),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def _call():
        try:
            return await asyncio.wait_for(llm.ainvoke(prompt), timeout=_timeout)
        except asyncio.TimeoutError:
            logger.warning("%s call timed out after %ds", label, _timeout)
            raise

    try:
        return await _call()
    except RetryError as e:
        logger.error("%s call failed after %d retries: %s", label, _retries, e.last_attempt.exception())
        raise e.last_attempt.exception() from e


async def resilient_astream(
    llm,
    prompt: str,
    *,
    timeout: int | None = None,
    chunk_timeout: int = 30,
    label: str = "LLM",
) -> AsyncIterator[Any]:
    """
    Stream from llm.astream(prompt) with an overall timeout and per-chunk timeout.

    Yields:
        LLM response chunks

    Raises:
        asyncio.TimeoutError: If the stream takes too long overall or between chunks
    """
    _timeout = timeout or settings.LLM_TIMEOUT

    async def _stream():
        async for chunk in llm.astream(prompt):
            yield chunk

    try:
        stream = _stream()
        deadline = asyncio.get_event_loop().time() + _timeout

        async for chunk in stream:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                logger.warning("%s stream exceeded overall timeout of %ds", label, _timeout)
                break
            if chunk.content:
                yield chunk
    except asyncio.TimeoutError:
        logger.warning("%s stream timed out", label)
        raise
    except Exception as e:
        logger.error("%s stream error: %s", label, e)
        raise


async def with_timeout(coro, timeout: int, label: str = "operation"):
    """Run a coroutine with a timeout. Logs a warning on timeout."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("%s timed out after %ds", label, timeout)
        raise
