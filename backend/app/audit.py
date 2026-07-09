"""
Audit logging — a thin helper for appending oversight events to the audit_logs
table. Used by auth and admin routers to record who did what.

Writing an audit entry must never break the request it describes, so `record`
swallows and logs its own failures rather than raising.
"""

import logging
from typing import Optional

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import AuditLog, User

logger = logging.getLogger(__name__)

# --- Action constants (keep in sync with the frontend Audit Log filter) ---
LOGIN = "login"
LOGIN_FAILED = "login_failed"
REGISTER = "register"
USER_CREATE = "user_create"
USER_DELETE = "user_delete"
ROLE_CHANGE = "role_change"
PASSWORD_RESET = "password_reset"
SETTINGS_CHANGE = "settings_change"


def client_ip(request: Optional[Request]) -> str:
    """Best-effort client IP for an audit entry."""
    if request is None or request.client is None:
        return ""
    return request.client.host or ""


async def record(
    db: AsyncSession,
    action: str,
    *,
    actor: Optional[User] = None,
    actor_email: str = "",
    target: str = "",
    detail: str = "",
    request: Optional[Request] = None,
    commit: bool = True,
) -> None:
    """Append an audit entry. Never raises — failures are logged and dropped."""
    try:
        entry = AuditLog(
            actor_id=actor.id if actor is not None else None,
            actor_email=(actor.email if actor is not None else actor_email)[:255],
            action=action[:64],
            target=target[:255],
            detail=detail[:512],
            ip=client_ip(request),
        )
        db.add(entry)
        if commit:
            await db.commit()
    except Exception:
        logger.exception("Failed to write audit log for action=%s", action)
        # Roll back only the audit failure so the caller's own commit isn't poisoned.
        try:
            await db.rollback()
        except Exception:
            pass
