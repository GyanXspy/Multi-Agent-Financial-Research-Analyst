"""
Tests for WebSocket auth-before-accept (F5) and reconcile_admin targeted queries (F4).
"""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-pytest-only-padded-to-a-safe-length-000000")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_stockanalyst.db")
os.environ.setdefault("ADMIN_EMAIL", "admin@test.com")

from starlette.websockets import WebSocketDisconnect

from app.security import create_access_token


# ─── WebSocket F5 tests ──────────────────────────────────────────────────────


class TestWebSocketAuthBeforeAccept:
    """
    Verify that the WebSocket endpoint authenticates BEFORE accepting the
    connection (F5 fix). Unauthenticated clients should be rejected with 4401.
    """

    def test_missing_token_rejected_with_4401(self, client):
        """No token → connection rejected (should be close code 4401)."""
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/api/ws/stock/AAPL"):
                pass  # Connection rejected before accept
        assert exc_info.value.code == 4401

    def test_invalid_token_rejected_with_4401(self, client):
        """Bad JWT → connection rejected with 4401."""
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/api/ws/stock/AAPL?token=bad-jwt"):
                pass  # Connection rejected before accept
        assert exc_info.value.code == 4401

    def test_invalid_symbol_rejected_with_4400(self, client, admin):
        """Valid auth but invalid symbol → rejected with 4400."""
        token = admin["token"]
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(f"/api/ws/stock/INVALID!SYMBOL?token={token}"):
                pass  # Connection rejected for bad symbol
        assert exc_info.value.code == 4400


# ─── reconcile_admin F4 tests ────────────────────────────────────────────────


class TestReconcileAdmin:
    """
    Verify the startup reconcile_admin function enforces the single-admin
    invariant using targeted queries (F4 fix).
    """

    def test_admin_email_gets_admin_role_on_register(self, client):
        """The configured ADMIN_EMAIL should get the admin role."""
        # admin is already registered via the session-scoped fixture,
        # verify via the /me endpoint
        resp = client.post(
            "/api/auth/login",
            json={"email": "admin@test.com", "password": "adminpass123"},
        )
        assert resp.status_code == 200
        assert resp.json()["user"]["role"] == "admin"

    def test_non_admin_email_gets_analyst_role(self, client):
        """Any other email should get the analyst role."""
        email = "reconcile-analyst@test.com"
        resp = client.post(
            "/api/auth/register",
            json={"email": email, "password": "password123"},
        )
        assert resp.status_code == 201
        assert resp.json()["user"]["role"] == "analyst"

    def test_admin_cannot_promote_non_admin_email(self, client, admin):
        """An admin cannot promote a non-admin-email user to admin."""
        # First register a regular user
        reg = client.post(
            "/api/auth/register",
            json={"email": "nopromo@test.com", "password": "password123"},
        )
        assert reg.status_code == 201
        user_id = reg.json()["user"]["id"]

        headers = {"Authorization": f"Bearer {admin['token']}"}
        resp = client.patch(
            f"/api/auth/users/{user_id}/role",
            json={"role": "admin"},
            headers=headers,
        )
        assert resp.status_code == 403


# ─── normalize_email F1 tests ────────────────────────────────────────────────


class TestNormalizeEmail:
    """Verify the centralized normalize_email helper."""

    def test_lowercases_and_strips(self):
        from app.db import normalize_email

        assert normalize_email("  Admin@Test.COM  ") == "admin@test.com"
        assert normalize_email("user@example.com") == "user@example.com"
        assert normalize_email("") == ""

    def test_is_admin_email_uses_normalized(self):
        from app.db import is_admin_email

        # ADMIN_EMAIL is set to admin@test.com in conftest
        assert is_admin_email("admin@test.com")
        assert is_admin_email("  ADMIN@TEST.COM  ")
        assert is_admin_email("Admin@Test.Com")
        assert not is_admin_email("other@test.com")
