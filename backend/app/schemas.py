"""
Pydantic schemas for API request/response validation.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


# ─── Research ───────────────────────────────────────────────────────────────

class ResearchRequest(BaseModel):
    """Incoming research analysis request."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Natural language query containing a company name or ticker symbol.",
        examples=["Analyze AAPL", "What is the valuation of Tesla?", "RELIANCE.NS research report"],
    )

    @field_validator("query")
    @classmethod
    def strip_and_check(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Query must not be empty")
        return v


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


class ReportSummary(BaseModel):
    """Lightweight report listing item for history views."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    query: str
    created_at: datetime


class ReportDetail(ReportSummary):
    """Full stored report."""

    report_md: str
    data_json: str


# ─── Auth ───────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    role: str
    created_at: datetime


class RoleUpdateRequest(BaseModel):
    role: str = Field(..., pattern="^(admin|analyst)$")


class UserListResponse(BaseModel):
    users: List[UserOut]


# ─── Admin ──────────────────────────────────────────────────────────────────

class AdminUserCreate(BaseModel):
    """Admin-initiated account creation."""

    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    role: str = Field(default="analyst", pattern="^(admin|analyst)$")


class PasswordResetRequest(BaseModel):
    new_password: str = Field(..., min_length=8, max_length=128)


class AuditLogEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_email: str
    action: str
    target: str
    detail: str
    ip: str
    created_at: datetime


class AuditLogResponse(BaseModel):
    entries: List[AuditLogEntry]
    total: int


class AdminStats(BaseModel):
    total_users: int
    admin_count: int
    analyst_count: int
    total_reports: int
    reports_last_7d: int
    recent_events: List[AuditLogEntry]


class SystemSettingsOut(BaseModel):
    registration_open: bool
    default_role: str
    session_timeout_minutes: int


class SystemSettingsUpdate(BaseModel):
    """All fields optional — only provided keys are updated."""

    registration_open: Optional[bool] = None
    default_role: Optional[str] = Field(default=None, pattern="^(admin|analyst)$")
    session_timeout_minutes: Optional[int] = Field(default=None, ge=0, le=10080)
