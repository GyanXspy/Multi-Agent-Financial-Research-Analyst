"""
Auth router — registration, login, current-user info, and admin user management.

RBAC model:
- The FIRST registered user becomes 'admin'; everyone after is 'analyst'.
- Admins can list users and change roles.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import ROLE_ADMIN, ROLE_ANALYST, User, get_db
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


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def register(request: Request, body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    email = body.email.lower().strip()

    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user_count = (await db.execute(select(func.count(User.id)))).scalar() or 0
    role = ROLE_ADMIN if user_count == 0 else ROLE_ANALYST

    user = User(email=email, hashed_password=hash_password(body.password), role=role)
    db.add(user)
    await db.commit()
    await db.refresh(user)

    logger.info("Auth: registered %s (role=%s)", email, role)
    token = create_access_token(user.id, user.role)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(request: Request, body: LoginRequest, db: AsyncSession = Depends(get_db)):
    email = body.email.lower().strip()

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    # Constant-shape response: never reveal whether email exists
    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    logger.info("Auth: login %s", email)
    token = create_access_token(user.id, user.role)
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
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if user_id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot change your own role")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.role = body.role
    await db.commit()
    await db.refresh(user)
    logger.info("Auth: role of %s changed to %s by %s", user.email, body.role, admin.email)
    return UserOut.model_validate(user)
