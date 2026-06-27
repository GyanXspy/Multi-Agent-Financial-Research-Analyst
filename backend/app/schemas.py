"""
Pydantic schemas for API request/response validation.
"""

from pydantic import BaseModel, Field
from typing import Any, Dict, Optional


class ResearchRequest(BaseModel):
    """Incoming research analysis request."""

    query: str = Field(
        ...,
        description="Natural language query containing a company name or ticker symbol.",
        examples=["Analyze AAPL", "What is the valuation of Tesla?", "RELIANCE.NS research report"],
    )


class ResearchResponse(BaseModel):
    """Structured response from the research pipeline."""

    symbol: str = Field(..., description="Resolved stock ticker symbol.")
    data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Aggregated raw data from all worker agents (financials, news, filings, peers).",
    )
    report: str = Field(
        default="",
        description="Final markdown-formatted investment research report.",
    )
    errors: Optional[Dict[str, str]] = Field(
        default=None,
        description="Per-agent error messages if any worker failed.",
    )
