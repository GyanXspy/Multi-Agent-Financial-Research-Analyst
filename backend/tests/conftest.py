"""
Test fixtures — spin up the FastAPI app against a temporary SQLite database
with rate limiting relaxed so auth tests don't trip the limiter.
"""

import asyncio
import os
import sys

import pytest

# Ensure `app` package is importable when running from backend/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-pytest-only-padded-to-a-safe-length-000000")
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_stockanalyst.db"

from fastapi.testclient import TestClient  # noqa: E402

from app.db import engine, Base  # noqa: E402
from app.main import app  # noqa: E402
from app.rate_limit import limiter  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _prepare_db():
    """Create a fresh test database for the session, drop it afterwards."""

    async def create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(create())
    yield
    asyncio.run(engine.dispose())
    try:
        os.remove("test_stockanalyst.db")
    except OSError:
        pass


@pytest.fixture()
def client():
    # Disable rate limiting for functional tests; re-enable per-test when needed
    limiter.enabled = False
    with TestClient(app) as c:
        yield c
    limiter.enabled = True
