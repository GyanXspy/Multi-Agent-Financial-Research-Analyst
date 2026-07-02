"""Auth flow tests: register, login, me, RBAC, and token validation."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.rate_limit import limiter


def _email() -> str:
    return f"user-{uuid.uuid4().hex[:10]}@test.com"


@pytest.fixture(scope="session")
def admin(_prepare_db):
    """Claims the first-user-is-admin slot for the whole test session."""
    limiter.enabled = False
    with TestClient(app) as c:
        resp = c.post("/api/auth/register", json={"email": "admin@test.com", "password": "adminpass123"})
        assert resp.status_code == 201
        body = resp.json()
        assert body["user"]["role"] == "admin"
    limiter.enabled = True
    return {"token": body["access_token"], "user": body["user"]}


def test_subsequent_users_are_analysts(client, admin):
    resp = client.post("/api/auth/register", json={"email": _email(), "password": "password123"})
    assert resp.status_code == 201
    assert resp.json()["user"]["role"] == "analyst"


def test_duplicate_email_rejected(client, admin):
    email = _email()
    assert client.post("/api/auth/register", json={"email": email, "password": "password123"}).status_code == 201
    dup = client.post("/api/auth/register", json={"email": email, "password": "password123"})
    assert dup.status_code == 409


def test_weak_password_rejected(client):
    resp = client.post("/api/auth/register", json={"email": _email(), "password": "short"})
    assert resp.status_code == 422


def test_invalid_email_rejected(client):
    resp = client.post("/api/auth/register", json={"email": "not-an-email", "password": "password123"})
    assert resp.status_code == 422


def test_login_and_me(client, admin):
    email = _email()
    client.post("/api/auth/register", json={"email": email, "password": "password123"})

    login = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert login.status_code == 200
    token = login.json()["access_token"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == email


def test_login_wrong_password(client, admin):
    email = _email()
    client.post("/api/auth/register", json={"email": email, "password": "password123"})
    bad = client.post("/api/auth/login", json={"email": email, "password": "wrongpassword"})
    assert bad.status_code == 401


def test_login_unknown_email_same_response(client):
    resp = client.post("/api/auth/login", json={"email": _email(), "password": "password123"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid email or password"


def test_me_requires_auth(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_token_via_query_param(client, admin):
    """SSE/WS clients pass the JWT as ?token= — confirm it authenticates."""
    me = client.get(f"/api/auth/me?token={admin['token']}")
    assert me.status_code == 200
    assert me.json()["role"] == "admin"


def test_analyst_cannot_access_admin_endpoints(client, admin):
    reg = client.post("/api/auth/register", json={"email": _email(), "password": "password123"})
    analyst_token = reg.json()["access_token"]

    denied = client.get("/api/auth/users", headers={"Authorization": f"Bearer {analyst_token}"})
    assert denied.status_code == 403


def test_admin_lists_users_and_changes_roles(client, admin):
    target = client.post("/api/auth/register", json={"email": _email(), "password": "password123"}).json()
    headers = {"Authorization": f"Bearer {admin['token']}"}

    users = client.get("/api/auth/users", headers=headers)
    assert users.status_code == 200
    assert len(users.json()["users"]) >= 2

    changed = client.patch(f"/api/auth/users/{target['user']['id']}/role", json={"role": "admin"}, headers=headers)
    assert changed.status_code == 200
    assert changed.json()["role"] == "admin"

    invalid = client.patch(f"/api/auth/users/{target['user']['id']}/role", json={"role": "superuser"}, headers=headers)
    assert invalid.status_code == 422


def test_admin_cannot_demote_self(client, admin):
    headers = {"Authorization": f"Bearer {admin['token']}"}
    resp = client.patch(f"/api/auth/users/{admin['user']['id']}/role", json={"role": "analyst"}, headers=headers)
    assert resp.status_code == 400
