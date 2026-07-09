"""
Security utilities — password hashing (bcrypt), JWT creation/validation,
and FastAPI auth dependencies (current user, admin gate).

Tokens are accepted from either:
- The `Authorization: Bearer <token>` header (normal API calls), or
- A `?token=<token>` query parameter (SSE EventSource / WebSocket clients
  that cannot set custom headers).
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Query, Request, WebSocket, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import ROLE_ADMIN, User, get_db

logger = logging.getLogger(__name__)

CREDENTIALS_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


# ─── Password hashing ───────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


# ─── JWT ────────────────────────────────────────────────────────────────────

def create_access_token(user_id: int, role: str, expires_minutes: Optional[int] = None) -> str:
    if not settings.JWT_SECRET:
        raise RuntimeError("JWT_SECRET is not configured — set it in backend/.env")
    # A positive override (from the session_timeout_minutes system setting) wins;
    # otherwise fall back to the static config default.
    minutes = expires_minutes if expires_minutes and expires_minutes > 0 else settings.ACCESS_TOKEN_EXPIRE_MINUTES
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT. Raises HTTPException(401) on any failure."""
    if not settings.JWT_SECRET:
        raise CREDENTIALS_EXC
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise CREDENTIALS_EXC


# ─── FastAPI dependencies ───────────────────────────────────────────────────

def _extract_token(request: Request, token_qp: Optional[str]) -> str:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:].strip()
    if token_qp:
        return token_qp
    raise CREDENTIALS_EXC


async def _load_user(token: str, db: AsyncSession) -> User:
    payload = decode_token(token)
    try:
        user_id = int(payload.get("sub", ""))
    except (TypeError, ValueError):
        raise CREDENTIALS_EXC

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise CREDENTIALS_EXC
    return user


async def get_current_user(
    request: Request,
    token: Optional[str] = Query(default=None, description="JWT for SSE clients that cannot set headers"),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the authenticated user from Bearer header or ?token= query param."""
    return await _load_user(_extract_token(request, token), db)


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != ROLE_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
    return user


async def authenticate_websocket(websocket: WebSocket, db: AsyncSession) -> Optional[User]:
    """
    Validate the JWT passed as ?token= on a WebSocket connection.
    Returns the User, or None (after closing the socket with 4401) on failure.
    """
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4401, reason="Missing auth token")
        return None
    try:
        return await _load_user(token, db)
    except HTTPException:
        await websocket.close(code=4401, reason="Invalid auth token")
        return None
