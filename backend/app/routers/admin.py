"""
Admin router — the Admin Console backend. Every endpoint is gated by
`require_admin`, so only the designated admin account can reach them.

Capabilities:
- User management     — create, delete, reset password (list/role live in auth.py)
- Oversight           — audit log, activity stats
- System configuration — runtime-enforced settings (registration, session timeout)

Data records (reports) are exposed read-only via the research router's history
endpoints, which already grant admins visibility into every user's reports.
"""

import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, settings_store
from app.db import (
    ROLE_ADMIN,
    ROLE_ANALYST,
    AuditLog,
    Report,
    User,
    get_db,
    is_admin_email,
    normalize_email,
    utcnow,
)
from app.schemas import (
    AdminStats,
    AdminUserCreate,
    AuditLogEntry,
    AuditLogResponse,
    PasswordResetRequest,
    SystemSettingsOut,
    SystemSettingsUpdate,
    UserOut,
)
from app.security import hash_password, require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ─── User management ─────────────────────────────────────────────────────────

@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: AdminUserCreate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new account directly (admin-provisioned, no self-registration)."""
    email = normalize_email(body.email)

    # The admin role is reserved for the configured address.
    if body.role == ROLE_ADMIN and not is_admin_email(email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the designated admin address may hold the admin role.",
        )
    # Force the configured admin address to admin, everyone else to analyst
    # unless an explicit (valid) role was given.
    role = ROLE_ADMIN if is_admin_email(email) else (body.role if body.role == ROLE_ANALYST else ROLE_ANALYST)

    existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(email=email, hashed_password=hash_password(body.password), role=role)
    db.add(user)
    await db.commit()
    await db.refresh(user)

    logger.info("Admin: %s created user %s (role=%s)", admin.email, email, role)
    await audit.record(db, audit.USER_CREATE, actor=admin, target=email, detail=f"role={role}", request=request)
    return UserOut.model_validate(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete an account. The admin cannot delete itself or the designated admin."""
    if user_id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete your own account")

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if is_admin_email(user.email):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="The designated admin cannot be deleted.")

    # Reports reference the user; remove them first to satisfy the FK.
    await db.execute(Report.__table__.delete().where(Report.user_id == user_id))
    await db.delete(user)
    await db.commit()

    logger.info("Admin: %s deleted user %s", admin.email, user.email)
    await audit.record(db, audit.USER_DELETE, actor=admin, target=user.email, request=request)
    return None


@router.post("/users/{user_id}/reset-password", response_model=UserOut)
async def reset_password(
    user_id: int,
    body: PasswordResetRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Set a new password for any account."""
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.hashed_password = hash_password(body.new_password)
    await db.commit()
    await db.refresh(user)

    logger.info("Admin: %s reset password for %s", admin.email, user.email)
    await audit.record(db, audit.PASSWORD_RESET, actor=admin, target=user.email, request=request)
    return UserOut.model_validate(user)


# ─── Oversight ───────────────────────────────────────────────────────────────

@router.get("/audit", response_model=AuditLogResponse)
async def get_audit_log(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    action: str | None = Query(default=None, max_length=64),
):
    """Paginated audit trail, newest first, optionally filtered by action."""
    base = select(AuditLog)
    count_stmt = select(func.count(AuditLog.id))
    if action:
        base = base.where(AuditLog.action == action)
        count_stmt = count_stmt.where(AuditLog.action == action)

    total = (await db.execute(count_stmt)).scalar() or 0
    stmt = base.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return AuditLogResponse(entries=[AuditLogEntry.model_validate(r) for r in rows], total=total)


@router.get("/stats", response_model=AdminStats)
async def get_stats(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate activity metrics for the Admin Console overview."""
    total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0
    admin_count = (await db.execute(select(func.count(User.id)).where(User.role == ROLE_ADMIN))).scalar() or 0
    total_reports = (await db.execute(select(func.count(Report.id)))).scalar() or 0

    since = utcnow() - timedelta(days=7)
    reports_7d = (await db.execute(select(func.count(Report.id)).where(Report.created_at >= since))).scalar() or 0

    recent = (
        await db.execute(select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(10))
    ).scalars().all()

    return AdminStats(
        total_users=total_users,
        admin_count=admin_count,
        analyst_count=total_users - admin_count,
        total_reports=total_reports,
        reports_last_7d=reports_7d,
        recent_events=[AuditLogEntry.model_validate(r) for r in recent],
    )


# ─── System configuration ────────────────────────────────────────────────────

@router.get("/settings", response_model=SystemSettingsOut)
async def get_settings(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return SystemSettingsOut(**await settings_store.get_all(db))


@router.patch("/settings", response_model=SystemSettingsOut)
async def update_settings(
    body: SystemSettingsUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        return SystemSettingsOut(**await settings_store.get_all(db))

    merged = await settings_store.set_many(db, updates)
    logger.info("Admin: %s updated settings %s", admin.email, list(updates.keys()))
    await audit.record(
        db, audit.SETTINGS_CHANGE, actor=admin,
        detail=", ".join(f"{k}={v}" for k, v in updates.items()), request=request,
    )
    return SystemSettingsOut(**merged)
