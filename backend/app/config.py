"""
Application configuration — loads environment variables from .env file
using Pydantic Settings for type-safe, validated config access.
"""

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

    # --- LLM Configuration ---
    COORDINATOR_MODEL: str = "gemini-2.5-flash"
    FINANCIAL_MODEL: str = "gemini-2.5-flash"
    NEWS_MODEL: str = "gemini-2.5-flash"
    FILINGS_MODEL: str = "gemini-2.5-flash"
    THESIS_MODEL: str = "gemini-2.5-flash"

    # --- Server Configuration ---
    HOST: str = "[IP_ADDRESS]"
    PORT: int = 8000
    RELOAD: bool = True

    # --- Timeouts ---
    NEWS_API_TIMEOUT: int = 10
    EDGAR_TIMEOUT: int = 10


# Singleton instance — import this everywhere
settings = Settings()
