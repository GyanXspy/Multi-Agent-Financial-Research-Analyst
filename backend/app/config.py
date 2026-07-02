"""
Application configuration — loads environment variables from .env file
using Pydantic Settings for type-safe, validated config access.
"""

from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for the Multi-Agent Financial Research Analyst."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- API Keys ---
    GEMINI_API_KEY: str = ""
    NEWS_API_KEY: str = ""

    # --- Auth / Security ---
    JWT_SECRET: str = ""  # REQUIRED — generate with: python -c "import secrets; print(secrets.token_urlsafe(48))"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # --- Database ---
    DATABASE_URL: str = "mysql+aiomysql://root:sql24@localhost/stockanalyst"

    # --- LLM Configuration ---
    COORDINATOR_MODEL: str = "gemini-2.5-flash"
    FINANCIAL_MODEL: str = "gemini-2.5-flash"
    NEWS_MODEL: str = "gemini-2.5-flash"
    FILINGS_MODEL: str = "gemini-2.5-flash"
    THESIS_MODEL: str = "gemini-2.5-flash"

    # --- Server Configuration ---
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    RELOAD: bool = True

    # --- CORS ---
    CORS_ORIGINS: List[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # --- Timeouts ---
    NEWS_API_TIMEOUT: int = 10
    EDGAR_TIMEOUT: int = 15


# Singleton instance — import this everywhere
settings = Settings()
