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
os.environ.setdefault("SUPPORT_OVERRIDE_KEY", "test-only-support-override-key")

# Swap the Mongo driver for an in-memory one before anything imports database.py.
import mongomock_motor                     # noqa: E402
import motor.motor_asyncio as motor_asyncio  # noqa: E402
motor_asyncio.AsyncIOMotorClient = mongomock_motor.AsyncMongoMockClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

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
    """RateLimitMiddleware's request buckets live on one middleware instance
    for the app's whole lifetime, and `app`/`client` are session-scoped — so
    without a reset, guest-facing traffic (now rate-limited, see
    server.py's RateLimitMiddleware) from an earlier test would carry over
    and produce spurious 429s in a later, unrelated test. Clearing between
    tests isolates them without weakening the limits within any single test.
    """
    mw = client.app.middleware_stack
    while mw is not None:
        if type(mw).__name__ == "RateLimitMiddleware":
            mw.buckets.clear()
            break
        mw = getattr(mw, "app", None)
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
    """Send one request in its own rate-limit bucket.

    The app allows 120 requests a minute per (tenant, identity). A suite that
    sweeps a few hundred routes blows through that and every answer comes back
    429, which is not an authorisation result. A distinct tenant header per
    probe keeps what we read as the auth decision.

    Skipped for /api/public/* and /api/table/* — these are bucketed by IP
    plus table/business token, not by tenant header (see server.py's
    RateLimitMiddleware.GUEST_DEFAULT_LIMIT and PREFIX_OVERRIDES), so the
    header serves no rate-limit purpose there. Worse, ActorContextMiddleware
    reads the same X-Tenant-Id header as a genuine (if low-priority,
    JWT-beats-it) business identity — for a partner/integration caller with
    no bearer token, which is a real, intentional feature. Injecting a
    synthetic "probe-N" value on every call made these two
    genuinely-anonymous-by-design path prefixes look, to any code that reads
    the actor context for tenant scoping, like a rapid string of different
    "businesses" instead of no business at all — surfaced by
    services/booking_rules_engine.py's guest-booking path once it started
    actually consulting tenant scope on these routes.

    Guest-surface rate-limit buckets are cleared between tests by the
    autouse `_reset_rate_limit_buckets` fixture above, so a test that needs
    to exceed the real limit on purpose (to prove a 429 fires) still can.
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
