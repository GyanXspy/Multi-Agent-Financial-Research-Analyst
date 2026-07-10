"""
Structured logging configuration — JSON in production, human-readable in dev.

Sets up:
- JSON formatter (python-json-logger) for machine-parseable prod logs
- Colorized text formatter for local development
- Request ID propagation via contextvars
- Filters to suppress noisy library loggers
"""

import contextvars
import logging
import sys
import uuid
from typing import Optional

from pythonjsonlogger import jsonlogger

# Context variable for request-scoped trace IDs
request_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "request_id", default=None
)


def get_request_id() -> Optional[str]:
    return request_id_var.get()


def set_request_id(rid: Optional[str] = None) -> str:
    """Set (or generate) a request ID for the current async context."""
    rid = rid or uuid.uuid4().hex[:12]
    request_id_var.set(rid)
    return rid


class RequestIdFilter(logging.Filter):
    """Inject the current request ID into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"  # type: ignore[attr-defined]
        return True


class JsonFormatter(jsonlogger.JsonFormatter):
    """Custom JSON formatter that adds standard fields."""

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record["level"] = record.levelname
        log_record["logger"] = record.name
        log_record["request_id"] = getattr(record, "request_id", "-")
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)


def setup_logging(log_format: str = "json", level: int = logging.INFO) -> None:
    """
    Configure root logger.

    Args:
        log_format: "json" for production, "text" for development
        level: logging level (default INFO)
    """
    root = logging.getLogger()
    root.setLevel(level)

    # Clear existing handlers
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIdFilter())

    if log_format == "json":
        formatter = JsonFormatter(
            fmt="%(asctime)s %(level)s %(logger)s %(request_id)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-7s | %(name)s | [%(request_id)s] %(message)s",
            datefmt="%H:%M:%S",
        )

    handler.setFormatter(formatter)
    root.addHandler(handler)

    # Suppress noisy library loggers
    for noisy in ("httpx", "httpcore", "urllib3", "yfinance", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
