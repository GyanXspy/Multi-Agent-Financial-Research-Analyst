"""
Auth router — registration, login, current-user info, and admin user management.

RBAC model:
- Exactly one address (settings.ADMIN_EMAIL) may hold the 'admin' role.
  Registering with that address grants admin; everyone else is an 'analyst',
  and no other account can be promoted to admin.
- Admins can list users and change roles (see also routers/admin.py).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, settings_store
from app.db import ROLE_ADMIN, ROLE_ANALYST, User, get_db, is_admin_email, normalize_email
from app.rate_limit import limiter
from app.schemas import (
    LoginRequest,
    RegisterRequest,
    RoleUpdateRequest,
    TokenResponse,
    UserListResponse,
    UserOut,
)
from app.security import (
    create_access_token,
    get_current_user,
    hash_password,
    require_admin,
    verify_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


async def _token_for(db: AsyncSession, user: User) -> str:
    """Mint an access token honoring the admin-configured session timeout."""
    timeout = await settings_store.get(db, "session_timeout_minutes")
    return create_access_token(user.id, user.role, expires_minutes=timeout)


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def register(request: Request, body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    email = normalize_email(body.email)

    # Admin is decided solely by the configured address — never by signup order.
    is_admin = is_admin_email(email)

    # When self-registration is closed, only the designated admin may sign up.
    registration_open = await settings_store.get(db, "registration_open")
    if not registration_open and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is currently closed. Contact an administrator.",
        )

    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    role = ROLE_ADMIN if is_admin else ROLE_ANALYST

    user = User(email=email, hashed_password=hash_password(body.password), role=role)
    db.add(user)
    await db.commit()
    await db.refresh(user)

    logger.info("Auth: registered %s (role=%s)", email, role)
    await audit.record(db, audit.REGISTER, actor=user, target=email, detail=f"role={role}", request=request)
    token = await _token_for(db, user)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(request: Request, body: LoginRequest, db: AsyncSession = Depends(get_db)):
    email = normalize_email(body.email)

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    # Constant-shape response: never reveal whether email exists
    if user is None or not verify_password(body.password, user.hashed_password):
        await audit.record(db, audit.LOGIN_FAILED, actor_email=email, target=email, request=request)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    logger.info("Auth: login %s", email)
    await audit.record(db, audit.LOGIN, actor=user, request=request)
    token = await _token_for(db, user)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)


# ─── Admin endpoints ────────────────────────────────────────────────────────

@router.get("/users", response_model=UserListResponse)
async def list_users(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).order_by(User.created_at))
    users = result.scalars().all()
    return UserListResponse(users=[UserOut.model_validate(u) for u in users])


@router.patch("/users/{user_id}/role", response_model=UserOut)
async def update_role(
    user_id: int,
    body: RoleUpdateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if user_id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot change your own role")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # The admin role is reserved for the configured address. No other account
    # may be promoted to admin, and the admin account may not be demoted.
    if body.role == ROLE_ADMIN and not is_admin_email(user.email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the designated admin address may hold the admin role.",
        )
    if body.role != ROLE_ADMIN and is_admin_email(user.email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The designated admin account cannot be demoted.",
        )

    user.role = body.role
    await db.commit()
    await db.refresh(user)
    logger.info("Auth: role of %s changed to %s by %s", user.email, body.role, admin.email)
    await audit.record(db, audit.ROLE_CHANGE, actor=admin, target=user.email, detail=f"role={body.role}", request=request)
    return UserOut.model_validate(user)
