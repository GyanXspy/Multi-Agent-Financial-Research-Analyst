"""
Admin Console tests: the single-admin (email-gated) invariant plus the
/api/admin/* management, oversight, and settings endpoints.

Relies on the shared `admin` fixture and helpers in test_auth.py.
"""

from tests.test_auth import _email  # shared email generator; `admin` comes from conftest


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ─── Single-admin invariant ──────────────────────────────────────────────────

def test_configured_email_becomes_admin(client, admin):
    """Sanity: the fixture proves the configured address is admin, nobody else is."""
    assert admin["user"]["role"] == "admin"


def test_non_configured_email_cannot_be_promoted(client, admin):
    """Only the configured address may hold admin — promotion of others is 403."""
    target = client.post("/api/auth/register", json={"email": _email(), "password": "password123"}).json()
    resp = client.patch(
        f"/api/auth/users/{target['user']['id']}/role",
        json={"role": "admin"},
        headers=_auth(admin["token"]),
    )
    assert resp.status_code == 403


def test_admin_create_via_admin_router_forbidden_for_other_email(client, admin):
    """POST /api/admin/users with role=admin for a non-configured email is rejected."""
    resp = client.post(
        "/api/admin/users",
        json={"email": _email(), "password": "password123", "role": "admin"},
        headers=_auth(admin["token"]),
    )
    assert resp.status_code == 403


# ─── User management ─────────────────────────────────────────────────────────

def test_admin_creates_and_deletes_user(client, admin):
    email = _email()
    created = client.post(
        "/api/admin/users",
        json={"email": email, "password": "password123", "role": "analyst"},
        headers=_auth(admin["token"]),
    )
    assert created.status_code == 201
    user_id = created.json()["id"]
    assert created.json()["role"] == "analyst"

    # The created account can log in.
    login = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert login.status_code == 200

    deleted = client.delete(f"/api/admin/users/{user_id}", headers=_auth(admin["token"]))
    assert deleted.status_code == 204

    # After deletion the account can no longer authenticate.
    gone = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert gone.status_code == 401


def test_admin_cannot_delete_self(client, admin):
    resp = client.delete(f"/api/admin/users/{admin['user']['id']}", headers=_auth(admin["token"]))
    assert resp.status_code == 400


def test_admin_resets_password(client, admin):
    email = _email()
    created = client.post(
        "/api/admin/users",
        json={"email": email, "password": "password123", "role": "analyst"},
        headers=_auth(admin["token"]),
    ).json()

    reset = client.post(
        f"/api/admin/users/{created['id']}/reset-password",
        json={"new_password": "brand-new-pass-456"},
        headers=_auth(admin["token"]),
    )
    assert reset.status_code == 200

    assert client.post("/api/auth/login", json={"email": email, "password": "password123"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": email, "password": "brand-new-pass-456"}).status_code == 200


def test_analyst_cannot_reach_admin_router(client, admin):
    analyst_token = client.post(
        "/api/auth/register", json={"email": _email(), "password": "password123"}
    ).json()["access_token"]

    assert client.get("/api/admin/stats", headers=_auth(analyst_token)).status_code == 403
    assert client.get("/api/admin/audit", headers=_auth(analyst_token)).status_code == 403
    assert client.get("/api/admin/settings", headers=_auth(analyst_token)).status_code == 403


# ─── Oversight ───────────────────────────────────────────────────────────────

def test_stats_shape(client, admin):
    resp = client.get("/api/admin/stats", headers=_auth(admin["token"]))
    assert resp.status_code == 200
    body = resp.json()
    for key in ("total_users", "admin_count", "analyst_count", "total_reports", "reports_last_7d", "recent_events"):
        assert key in body
    assert body["admin_count"] >= 1


def test_audit_log_records_events(client, admin):
    """Creating a user should surface a user_create entry in the audit trail."""
    email = _email()
    client.post(
        "/api/admin/users",
        json={"email": email, "password": "password123", "role": "analyst"},
        headers=_auth(admin["token"]),
    )
    resp = client.get("/api/admin/audit?action=user_create", headers=_auth(admin["token"]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert any(e["target"] == email for e in body["entries"])


# ─── System settings ─────────────────────────────────────────────────────────

def test_settings_roundtrip_and_registration_gate(client, admin):
    headers = _auth(admin["token"])

    # Close self-registration.
    patched = client.patch("/api/admin/settings", json={"registration_open": False}, headers=headers)
    assert patched.status_code == 200
    assert patched.json()["registration_open"] is False

    # A non-admin address is now refused registration.
    blocked = client.post("/api/auth/register", json={"email": _email(), "password": "password123"})
    assert blocked.status_code == 403

    # Re-open and confirm registration works again.
    reopened = client.patch("/api/admin/settings", json={"registration_open": True}, headers=headers)
    assert reopened.json()["registration_open"] is True
    assert client.post("/api/auth/register", json={"email": _email(), "password": "password123"}).status_code == 201
