"""In-process tests: the whole app, no server, no database daemon.

The 50+ suites in the parent directory all talk to a live BASE_URL, which is
why none of them ever ran in CI — they need a booted backend and a real Mongo
before they can even be collected. The tests in here mount the real FastAPI app
through TestClient with an in-memory Mongo underneath, so they run anywhere in
seconds and can gate a pull request.

That matters most for the things that have no second chance: whether an
endpoint is reachable without a credential, and whether a second factor is
actually checked. Both were wrong in this codebase in ways no amount of
reading the diff would have caught.
"""
import os
import sys

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "inprocess_tests")
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")
os.environ.setdefault("ADMIN_EMAIL", "owner@nua.com")
# Matches the OWNER constant below — these used to be hardcoded defaults in
# routes/auth.py itself; moved here so production code has no built-in
# fallback password while this suite's fixtures keep working unchanged.
os.environ.setdefault("ADMIN_PASSWORD", "NuaOwner2026!")
os.environ.setdefault("DEMO_STAFF_PASSWORD", "Staff2026!")
os.environ.setdefault("SEED_DEMO_STAFF", "true")
os.environ.setdefault("SUPPORT_OVERRIDE_KEY", "test-only-support-override-key")
os.environ.setdefault("OWNER_RECOVERY_KEY", "test-only-owner-recovery-key")
os.environ.setdefault("CRON_SECRET", "test-only-cron-secret")

# Swap the Mongo driver for an in-memory one before anything imports database.py.
import mongomock_motor                     # noqa: E402
import motor.motor_asyncio as motor_asyncio  # noqa: E402
motor_asyncio.AsyncIOMotorClient = mongomock_motor.AsyncMongoMockClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.mongomock_compat import install as install_mongomock_compat  # noqa: E402
install_mongomock_compat()

OWNER = {"email": "owner@nua.com", "password": "NuaOwner2026!"}


@pytest.fixture(scope="session")
def app():
    import server
    return server.app


@pytest.fixture(scope="session")
def client(app):
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_rate_limit_buckets(client):
    """Each test starts with empty shared rate-limit windows.
    Within a test, all instances still enforce the same real limit.
    """
    from database import db
    client.portal.call(db.rate_limit_windows.delete_many, {})
    yield


@pytest.fixture
def anon(client):
    """A caller with no credential at all.

    The cookie jar is the trap here: TestClient keeps the Set-Cookie from any
    login that happened earlier in the session, and get_current_user prefers
    cookies over bearer headers — so an 'anonymous' request would quietly be
    authenticated and the test would pass while proving nothing.
    """
    client.cookies.clear()
    return client


_probe = [0]


def req(client, method, path, **kw):
    """Preserve legacy test tenant context on internal probes.

    X-Tenant-Id no longer affects rate-limit identity. Shared counters reset
    between tests; large auth sweeps explicitly reset them per case to keep
    exercising authentication. Public/table probes never inject tenant context.
    """
    if path.startswith("/api/public") or path.startswith("/api/table"):
        return client.request(method, path, **kw)
    _probe[0] += 1
    headers = dict(kw.pop("headers", {}))
    headers.setdefault("X-Tenant-Id", f"probe-{_probe[0]}")
    return client.request(method, path, headers=headers, **kw)


@pytest.fixture
def owner_headers(client):
    r = req(client, "POST", "/api/auth/login", json=OWNER)
    body = r.json()
    assert "token" in body, f"owner login failed: {r.status_code} {r.text[:200]}"
    client.cookies.clear()
    return {"Authorization": f"Bearer {body['token']}"}


@pytest.fixture(autouse=True)
def mock_reservation_transaction(monkeypatch):
    # mongomock has no transactions. The replica-set suite proves atomicity.
    from services import reservation_store
    async def execute(operation):
        return await operation(None)
    monkeypatch.setattr(reservation_store, '_transaction', execute)
