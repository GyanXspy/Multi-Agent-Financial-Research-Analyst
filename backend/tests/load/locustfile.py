"""
Load test — Locust scenarios for the Multi-Agent Financial Research Analyst.

Install: pip install locust
Run:     locust -f locustfile.py --headless -u 100 -r 10 --run-time 2m --host http://localhost:8000

Scenarios:
1. Light endpoints: /health, /me, /history (should handle 10k+ concurrent)
2. Heavy endpoints: /analyze (bound by worker pool + Gemini quota)
3. WebSocket: price feed connections
"""

import json
import random

from locust import HttpUser, between, task


# Test credentials — create this user beforehand
TEST_EMAIL = "loadtest@example.com"
TEST_PASSWORD = "loadtest123!"

# Tickers to test with
TICKERS = ["AAPL", "TSLA", "MSFT", "GOOGL", "AMZN", "NVDA", "META"]


class StockAnalystUser(HttpUser):
    """Simulates a typical user flow: login → browse history → run analysis."""

    wait_time = between(1, 5)
    token: str = ""

    def on_start(self):
        """Login or register on start."""
        # Try login first
        resp = self.client.post(
            "/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        if resp.status_code == 200:
            self.token = resp.json()["access_token"]
        elif resp.status_code == 401:
            # Try to register
            resp = self.client.post(
                "/api/auth/register",
                json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
            )
            if resp.status_code == 201:
                self.token = resp.json()["access_token"]

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    # ── Light endpoints (high frequency) ──

    @task(10)
    def health_check(self):
        self.client.get("/api/health")

    @task(5)
    def health_ready(self):
        self.client.get("/api/health/ready")

    @task(5)
    def get_me(self):
        self.client.get("/api/auth/me", headers=self._headers())

    @task(8)
    def get_history(self):
        self.client.get("/api/research/history", headers=self._headers())

    # ── Heavy endpoints (low frequency, bounded by rate limit) ──

    @task(1)
    def analyze_stock(self):
        ticker = random.choice(TICKERS)
        resp = self.client.post(
            "/api/research/analyze",
            json={"query": f"Analyze {ticker}"},
            headers=self._headers(),
            name="/api/research/analyze",
        )
        # If we get a 202 (queued), poll for result
        if resp.status_code == 202:
            job_id = resp.json().get("job_id")
            if job_id:
                # Poll a few times
                for _ in range(5):
                    import time
                    time.sleep(3)
                    status_resp = self.client.get(
                        f"/api/research/analyze/{job_id}",
                        headers=self._headers(),
                        name="/api/research/analyze/[job_id]",
                    )
                    if status_resp.status_code == 200:
                        data = status_resp.json()
                        if data.get("status") in ("complete", "failed"):
                            break
