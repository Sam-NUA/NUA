"""error_log and client_error_log (observability.py) captured real server and
browser errors but nothing ever looked at them again until a human went
looking — a system of record, not a system of alerting. services/ops_signals.py
checks both on the same hourly cadence as predictive_signals.py and emits
ops.error_spike through the rules engine when a rolling window crosses a
threshold, so a subscribed rule can notify or page instead of an owner
finding out from a complaint.
"""
import asyncio
import uuid
import pytest
from datetime import datetime, timezone

from conftest import req
from database import db
from services import ops_signals

FIXED_WINDOW = 30
TEST_BIZ = "ops-signals-test"

@pytest.fixture(autouse=True)
def isolate_signals():
    for collection in ("error_log", "client_error_log", "rule_events"):
        _run(db[collection].delete_many({"businessId": TEST_BIZ}))
    yield
    for collection in ("error_log", "client_error_log", "rule_events"):
        _run(db[collection].delete_many({"businessId": TEST_BIZ}))



def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _insert_server_errors(n, path="/api/checkout"):
    now = datetime.now(timezone.utc)
    docs = [{"requestId": str(uuid.uuid4()), "method": "POST", "path": path,
             "actor": None, "businessId": TEST_BIZ, "error": "ValueError: boom", "traceback": "…", "at": now} for _ in range(n)]
    if docs:
        _run(db.error_log.insert_many(docs))


def _insert_client_errors(n, message="TypeError: cannot read property"):
    now = datetime.now(timezone.utc)
    docs = [{"message": message, "stack": "…", "url": "/pos", "userAgent": "test",
             "actor": None, "businessId": TEST_BIZ, "at": now} for _ in range(n)]
    if docs:
        _run(db.client_error_log.insert_many(docs))


def test_server_error_check_does_not_trigger_below_threshold():
    _insert_server_errors(2, path="/api/quiet-endpoint-below-threshold")
    result = _run(ops_signals.check_server_errors(business_id=TEST_BIZ, threshold=5))
    assert result["triggered"] is False


def test_server_error_check_triggers_at_threshold_with_top_path():
    # error_log is a shared, unscoped collection other tests in this file
    # write to too (each on its own unique path) — 40 clearly outweighs any
    # other single path any sibling test inserts in the same window, so
    # "most common path" can't tie-break onto someone else's data.
    path = f"/api/hot-endpoint-{uuid.uuid4()}"
    _insert_server_errors(40, path=path)
    result = _run(ops_signals.check_server_errors(business_id=TEST_BIZ, threshold=5))
    assert result["triggered"] is True
    assert result["count"] >= 40
    assert result["topPath"] == path
    assert "ValueError" in result["sampleError"]


def test_client_error_check_triggers_at_threshold():
    _insert_client_errors(11)
    result = _run(ops_signals.check_client_errors(business_id=TEST_BIZ, threshold=10))
    assert result["triggered"] is True
    assert result["count"] >= 11
    assert "TypeError" in result["sampleMessage"]


def test_scan_and_emit_fires_once_then_dedupes_within_the_window():
    path = f"/api/dedupe-test-{uuid.uuid4()}"
    _insert_server_errors(6, path=path)

    first = _run(ops_signals.scan_and_emit(business_id=TEST_BIZ))
    assert first["server"]["triggered"] is True
    assert first["server"]["emitted"] is True

    server_events = _run(db.rule_events.count_documents(
        {"type": "ops.error_spike", "entityId": "server", "businessId": TEST_BIZ}))
    assert server_events == 1

    # Same still-triggering window, called again — must not fire a second event.
    second = _run(ops_signals.scan_and_emit(business_id=TEST_BIZ))
    assert second["server"]["triggered"] is True
    assert second["server"]["emitted"] is False
    server_events_after = _run(db.rule_events.count_documents(
        {"type": "ops.error_spike", "entityId": "server", "businessId": TEST_BIZ}))
    assert server_events_after == 1, "an ongoing spike inside the dedupe window must not re-fire every scan"


def test_preview_endpoint_does_not_write_rule_events(client, owner_headers):
    before = _run(db.rule_events.count_documents({}))
    r = req(client, "GET", "/api/rules/ops/error-status", headers=owner_headers)
    assert r.status_code == 200, r.text[:200]
    assert "server" in r.json() and "client" in r.json()
    after = _run(db.rule_events.count_documents({}))
    assert after == before


def test_ops_scan_endpoint_requires_owner_or_manager(client, owner_headers):
    email = f"ops-cashier-{uuid.uuid4()}@nua.com"
    req(client, "POST", "/api/auth/staff/add", headers=owner_headers, json={
        "name": "Ops Cashier", "email": email, "password": "CashierPass1!", "role": "cashier"})
    tok = req(client, "POST", "/api/auth/login", json={"email": email, "password": "CashierPass1!"}).json()
    client.cookies.clear()
    r = req(client, "POST", "/api/rules/ops/scan", headers={"Authorization": f"Bearer {tok['token']}"})
    assert r.status_code == 403
