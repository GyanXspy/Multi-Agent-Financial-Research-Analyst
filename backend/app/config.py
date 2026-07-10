"""
Application configuration — loads environment variables from .env file
using Pydantic Settings for type-safe, validated config access.

Production-ready: all secrets are REQUIRED (no defaults) so the app fails
fast on startup if misconfigured.  Development defaults are provided for
non-secret operational settings only.
"""

from typing import List, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for the Multi-Agent Financial Research Analyst."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Environment ---
    ENVIRONMENT: str = "development"  # development | staging | production

    # --- API Keys (REQUIRED — no defaults) ---
    GEMINI_API_KEY: str = ""
    NEWS_API_KEY: str = ""

    # --- Auth / Security (REQUIRED — no defaults) ---
    JWT_SECRET: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # The single email address permitted to hold the 'admin' role.
    ADMIN_EMAIL: str = ""

    # Google OAuth Client ID
    GOOGLE_CLIENT_ID: Optional[str] = None

    # --- Database ---
    DATABASE_URL: str = ""

    # Connection pool tuning
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_RECYCLE: int = 1800

    # --- Redis (optional for dev; required for production) ---
    REDIS_URL: Optional[str] = None

    # --- LLM Configuration ---
    COORDINATOR_MODEL: str = "gemini-2.5-flash"
    FINANCIAL_MODEL: str = "gemini-2.5-flash"
    NEWS_MODEL: str = "gemini-2.5-flash"
    FILINGS_MODEL: str = "gemini-2.5-flash"
    THESIS_MODEL: str = "gemini-2.5-flash"

    # LLM call timeouts (seconds)
    LLM_TIMEOUT: int = 120
    LLM_MAX_RETRIES: int = 3

    # --- Gemini quota / cost controls ---
    GEMINI_RPM_LIMIT: int = 60  # requests per minute cap
    GEMINI_TPM_LIMIT: int = 1000000  # tokens per minute cap
    MONTHLY_BUDGET_CAP: float = 500.0  # USD

    # --- Worker / Queue ---
    MAX_CONCURRENT_ANALYSES: int = 10  # worker pool concurrency cap
    MAX_USER_CONCURRENT: int = 2  # per-user in-flight analyses

    # --- Server Configuration ---
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    RELOAD: bool = True
    WORKERS: int = 4  # Gunicorn workers

    # --- CORS ---
    CORS_ORIGINS: List[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # --- Timeouts ---
    NEWS_API_TIMEOUT: int = 10
    EDGAR_TIMEOUT: int = 15
    YFINANCE_TIMEOUT: int = 30

    # --- Observability ---
    SENTRY_DSN: Optional[str] = None
    LOG_FORMAT: str = "json"  # json | text (text for local dev)

    # --- Cache TTLs (seconds) ---
    CACHE_TTL_FINANCIAL: int = 900  # 15 min
    CACHE_TTL_NEWS: int = 900  # 15 min
    CACHE_TTL_FILINGS: int = 3600  # 60 min
    CACHE_TTL_PEERS: int = 3600  # 60 min
    CACHE_TTL_REPORT: int = 3600  # 60 min

    # --- WebSocket ---
    WS_MAX_CONNECTIONS_PER_USER: int = 5
    WS_POLL_INTERVAL: float = 5.0

    @field_validator("GEMINI_API_KEY")
    @classmethod
    def gemini_key_required(cls, v: str) -> str:
        if not v:
            raise ValueError(
                "GEMINI_API_KEY is required. Get one at https://aistudio.google.com/app/apikey"
            )
        return v

    @field_validator("JWT_SECRET")
    @classmethod
    def jwt_secret_required(cls, v: str) -> str:
        if not v:
            raise ValueError(
                'JWT_SECRET is required. Generate with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        return v

    @field_validator("DATABASE_URL")
    @classmethod
    def database_url_required(cls, v: str) -> str:
        if not v:
            raise ValueError(
                "DATABASE_URL is required. Example: mysql+aiomysql://user:pass@localhost/stockanalyst"
            )
        return v

    @field_validator("ADMIN_EMAIL")
    @classmethod
    def admin_email_required(cls, v: str) -> str:
        if not v:
            raise ValueError(
                "ADMIN_EMAIL is required — this is the single address granted admin privileges."
            )
        return v

    @field_validator("RELOAD")
    @classmethod
    def no_reload_in_prod(cls, v: bool, info) -> bool:
        env = info.data.get("ENVIRONMENT", "development")
        if env != "development" and v:
            return False
        return v

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == "development"


# Singleton instance — import this everywhere
settings = Settings()
