"""
System settings store — typed access to admin-configurable, runtime-enforced
settings persisted in the system_settings table.

Only settings that the application actually enforces live here. Billing,
external integrations, and dynamic rate limits are intentionally omitted:
there is nothing in this app to enforce them, so exposing them would be
misleading. Add a key here only once code reads and acts on it.
"""

from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SystemSetting

# key -> (default_value, type). Types are 'bool' or 'int'.
DEFAULTS: Dict[str, tuple] = {
    # When false, only the configured ADMIN_EMAIL may register.
    "registration_open": (True, "bool"),
    # Default role assigned to newly self-registered users (informational —
    # the admin email always overrides to admin).
    "default_role": ("analyst", "str"),
    # Overrides JWT expiry when > 0; falls back to ACCESS_TOKEN_EXPIRE_MINUTES otherwise.
    "session_timeout_minutes": (0, "int"),
}


def _coerce(raw: str, kind: str) -> Any:
    if kind == "bool":
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    if kind == "int":
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0
    return raw


def _serialize(value: Any, kind: str) -> str:
    if kind == "bool":
        return "true" if value else "false"
    return str(value)


async def get_all(db: AsyncSession) -> Dict[str, Any]:
    """Return every known setting, merging stored rows over the defaults."""
    rows = (await db.execute(select(SystemSetting))).scalars().all()
    stored = {r.key: r.value for r in rows}
    result: Dict[str, Any] = {}
    for key, (default, kind) in DEFAULTS.items():
        result[key] = _coerce(stored[key], kind) if key in stored else default
    return result


async def get(db: AsyncSession, key: str) -> Any:
    default, kind = DEFAULTS[key]
    row = (await db.execute(select(SystemSetting).where(SystemSetting.key == key))).scalar_one_or_none()
    return _coerce(row.value, kind) if row is not None else default


async def set_many(db: AsyncSession, updates: Dict[str, Any]) -> Dict[str, Any]:
    """Upsert the given settings (ignoring unknown keys) and return the full set."""
    for key, value in updates.items():
        if key not in DEFAULTS:
            continue
        _, kind = DEFAULTS[key]
        raw = _serialize(value, kind)
        row = (await db.execute(select(SystemSetting).where(SystemSetting.key == key))).scalar_one_or_none()
        if row is None:
            db.add(SystemSetting(key=key, value=raw))
        else:
            row.value = raw
    await db.commit()
    return await get_all(db)


async def seed_defaults(db: AsyncSession) -> None:
    """Insert any missing default rows. Called on startup."""
    existing = {r.key for r in (await db.execute(select(SystemSetting.key))).all()}
    # `.all()` on a single column yields Row objects; normalize to plain keys.
    existing_keys = {k if isinstance(k, str) else k[0] for k in existing}
    added = False
    for key, (default, kind) in DEFAULTS.items():
        if key not in existing_keys:
            db.add(SystemSetting(key=key, value=_serialize(default, kind)))
            added = True
    if added:
        await db.commit()
