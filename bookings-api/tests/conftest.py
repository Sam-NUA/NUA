"""In-process tests for the bookings-api service — mounts the real FastAPI
app through TestClient with an in-memory Mongo underneath, same technique
as the main NUA backend's tests/inprocess/conftest.py, so this runs
anywhere in seconds with no real Mongo or a booted service.
"""
import os
import sys

import pytest

os.environ.setdefault("BOOKINGS_MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("BOOKINGS_DB_NAME", "bookings_inprocess_tests")
os.environ.setdefault("BOOKINGS_ADMIN_KEY", "test-admin-key-not-for-production")

import mongomock_motor                       # noqa: E402
import motor.motor_asyncio as motor_asyncio  # noqa: E402
motor_asyncio.AsyncIOMotorClient = mongomock_motor.AsyncMongoMockClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ADMIN_KEY = os.environ["BOOKINGS_ADMIN_KEY"]


@pytest.fixture(scope="session")
def app():
    import server
    return server.app


@pytest.fixture(scope="session")
def client(app):
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_headers():
    return {"X-Admin-Key": ADMIN_KEY}


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """auth.rate_limiter is a process-wide in-memory singleton keyed by
    caller identity — every TestClient request shares the same fake IP, so
    without this, tests would trip each other's rate-limit buckets instead
    of each starting from a clean slate."""
    from auth import rate_limiter
    rate_limiter.buckets.clear()
    yield
    rate_limiter.buckets.clear()


@pytest.fixture(autouse=True)
def mock_transaction_runner(monkeypatch):
    """Unit tests use mongomock, which cannot prove transaction isolation.

    Real commit/rollback/concurrency tests live in tests_real and have a
    mandatory replica-set CI job. There is no production nontransactional
    fallback.
    """
    import routes_v1

    async def execute(venue_id, partner, operation):
        venue = await routes_v1._own_venue(venue_id, partner)
        return await operation(venue, None)
    monkeypatch.setattr(routes_v1, 'run_for_venue', execute)
