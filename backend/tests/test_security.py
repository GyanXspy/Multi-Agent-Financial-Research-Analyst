"""Security tests: endpoint protection, validation, headers, and ticker guard."""

import pytest

from app.agents.coordinator import TICKER_RE


def test_research_endpoints_require_auth(client):
    assert client.post("/api/research/analyze", json={"query": "AAPL"}).status_code == 401
    assert client.get("/api/research/stream?query=AAPL").status_code == 401
    assert client.get("/api/research/history").status_code == 401


def test_query_validation(client):
    reg = client.post("/api/auth/register", json={"email": "sec-test@test.com", "password": "password123"})
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Empty query
    assert client.post("/api/research/analyze", json={"query": "   "}, headers=headers).status_code == 422
    # Oversized query
    assert client.post("/api/research/analyze", json={"query": "x" * 500}, headers=headers).status_code == 422
    # Missing query
    assert client.post("/api/research/analyze", json={}, headers=headers).status_code == 422


def test_security_headers_present(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in resp.headers
    assert resp.headers["Referrer-Policy"] == "no-referrer"


@pytest.mark.parametrize("symbol", ["AAPL", "RELIANCE.NS", "^GSPC", "BRK-B", "^NSEI"])
def test_ticker_regex_accepts_valid(symbol):
    assert TICKER_RE.match(symbol)


@pytest.mark.parametrize(
    "symbol",
    [
        "",
        "aapl",                      # lowercase — LLM output is uppercased first, raw lowercase rejected
        "DROP TABLE users",          # spaces / injection
        "AAPL; rm -rf /",
        "<script>alert(1)</script>",
        "A" * 20,                    # too long
        "I AM UNABLE TO",            # LLM refusal fragment
    ],
)
def test_ticker_regex_rejects_invalid(symbol):
    assert not TICKER_RE.match(symbol)


def test_websocket_rejects_missing_token(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/api/ws/stock/AAPL") as ws:
            ws.receive_text()  # server closes with 4401 right after accept
    assert exc_info.value.code == 4401
