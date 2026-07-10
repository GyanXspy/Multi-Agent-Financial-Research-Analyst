"""
Budget & cost estimation helpers for Gemini API usage.

Tracks estimated costs per analysis and provides alerting when
approaching the configured monthly budget cap.
"""

import logging
import time
from typing import Dict

from app.config import settings

logger = logging.getLogger(__name__)

# Rough cost estimates per Gemini 2.5 Flash call (USD)
# Input: ~$0.15 per 1M tokens, Output: ~$0.60 per 1M tokens
# Average analysis uses ~5 LLM calls with ~5K input + ~2K output tokens each
ESTIMATED_COST_PER_ANALYSIS = 0.012  # USD (conservative estimate)
ESTIMATED_COST_PER_CACHED_HIT = 0.0  # free from cache

# In-memory tracking (reset on restart — for real prod use Prometheus/Redis)
_usage: Dict[str, float] = {
    "total_analyses": 0,
    "cached_analyses": 0,
    "estimated_spend_usd": 0.0,
    "period_start": time.time(),
}


def record_analysis(cached: bool = False) -> None:
    """Record an analysis execution for cost tracking."""
    _usage["total_analyses"] += 1
    if cached:
        _usage["cached_analyses"] += 1
    else:
        _usage["estimated_spend_usd"] += ESTIMATED_COST_PER_ANALYSIS

    # Check budget threshold
    if _usage["estimated_spend_usd"] > settings.MONTHLY_BUDGET_CAP * 0.8:
        logger.warning(
            "BUDGET ALERT: Estimated spend $%.2f approaching cap $%.2f (%.0f%%)",
            _usage["estimated_spend_usd"],
            settings.MONTHLY_BUDGET_CAP,
            (_usage["estimated_spend_usd"] / settings.MONTHLY_BUDGET_CAP) * 100,
        )


def get_usage_stats() -> Dict[str, float]:
    """Get current usage statistics."""
    total = _usage["total_analyses"]
    cached = _usage["cached_analyses"]
    cache_rate = (cached / total * 100) if total > 0 else 0

    return {
        "total_analyses": total,
        "cached_analyses": cached,
        "cache_hit_rate_pct": round(cache_rate, 1),
        "estimated_spend_usd": round(_usage["estimated_spend_usd"], 4),
        "monthly_budget_cap_usd": settings.MONTHLY_BUDGET_CAP,
        "budget_remaining_usd": round(settings.MONTHLY_BUDGET_CAP - _usage["estimated_spend_usd"], 4),
        "uptime_hours": round((time.time() - _usage["period_start"]) / 3600, 1),
    }


def is_budget_exceeded() -> bool:
    """Check if the monthly budget has been exceeded."""
    return _usage["estimated_spend_usd"] >= settings.MONTHLY_BUDGET_CAP
