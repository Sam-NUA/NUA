"""Structured request logging, error capture, and a deep health check.

There was previously no way to answer "is the backend actually healthy" beyond
a bare 200 from the root endpoint, and an unhandled exception vanished into
whatever terminal happened to be tailing stdout. These tests exercise the
replacement: a health check that actually pings the database, and an error
captured from a real unhandled exception that an owner can read back through
the API rather than needing shell access to a log file.
"""
from conftest import req


def test_health_reports_the_database_is_reachable(anon):
    r = req(anon, "GET", "/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"]["ok"] is True
    assert "latencyMs" in body["checks"]["database"]


def test_healthz_is_the_same_check_under_a_different_name(anon):
    assert req(anon, "GET", "/api/healthz").json()["status"] == "ok"


def test_health_check_is_reachable_with_no_login(anon):
    # Already covered by test_auth_gate's allow-list sweep, but pinned here
    # too since a health check that requires auth is useless to a load
    # balancer that has no credential to offer.
    assert req(anon, "GET", "/api/health").status_code == 200


def test_every_request_gets_a_request_id_header(client, owner_headers):
    r = req(client, "GET", "/api/customers", headers=owner_headers)
    assert r.status_code == 200
    assert r.headers.get("x-request-id")


def test_ops_errors_endpoint_requires_owner_or_manager(anon):
    r = req(anon, "GET", "/api/ops/errors")
    assert r.status_code == 401


def test_a_genuinely_unhandled_exception_is_captured_and_readable(app, client, owner_headers):
    """Register a throwaway route that always raises, and confirm the failure
    shows up in the owner-facing error list rather than only in stdout.

    A route added at test time, rather than monkeypatching a database
    internal, is what actually exercises the real middleware: FastAPI
    resolves route callables at registration time, and mongomock's collection
    accessors aren't guaranteed to return the same object twice, so patching
    "the" db.customers.find would silently patch nothing.
    """
    async def _boom():
        raise RuntimeError("synthetic failure for test_observability")

    app.router.add_api_route("/api/__test_boom", _boom, methods=["GET"])

    r = req(client, "GET", "/api/__test_boom", headers=owner_headers)
    assert r.status_code == 500
    assert r.json().get("requestId")
    # And never a raw traceback leaked to the client.
    assert "Traceback" not in r.text

    errs = req(client, "GET", "/api/ops/errors", headers=owner_headers).json()["errors"]
    matching = [e for e in errs if e["requestId"] == r.json()["requestId"]]
    assert matching, "the captured error should be readable back through /api/ops/errors"
    assert "synthetic failure for test_observability" in matching[0]["error"]
    assert matching[0]["actor"]["role"] == "owner"


def test_client_error_report_requires_no_authentication(anon):
    # Has to work from a guest ordering page and the login screen, neither
    # of which carries a token.
    r = req(anon, "POST", "/api/ops/client-errors", json={
        "message": "TypeError: cannot read property of undefined",
        "stack": "at TrackOrder.jsx:42",
        "url": "https://example.com/order/track/ABC123",
    })
    assert r.status_code == 200
    assert r.json() == {"recorded": True}


def test_client_error_report_is_readable_back_by_an_owner(client, owner_headers):
    unique_message = "synthetic client crash for test_observability"
    r = req(client, "POST", "/api/ops/client-errors", headers=owner_headers, json={
        "message": unique_message, "stack": "at Kitchen.jsx:100", "url": "/kitchen",
    })
    assert r.status_code == 200

    errs = req(client, "GET", "/api/ops/client-errors", headers=owner_headers).json()["errors"]
    matching = [e for e in errs if e["message"] == unique_message]
    assert matching, "the captured client error should be readable back through /api/ops/client-errors"
    assert matching[0]["url"] == "/kitchen"


def test_client_errors_endpoint_requires_owner_or_manager(anon):
    r = req(anon, "GET", "/api/ops/client-errors")
    assert r.status_code == 401


def test_client_error_report_tolerates_a_missing_body(anon):
    r = req(anon, "POST", "/api/ops/client-errors", json={})
    assert r.status_code == 200
    assert r.json() == {"recorded": True}
