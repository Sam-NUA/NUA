"""P0.5 Trust Release: Ash tool-execution safety controls.

Covers the gaps a read-only audit found in services/nua_tools.py before this
pass: no global kill switch, no server-side floor stopping a manager from
setting a high-risk tool to auto-execute, blocked/rejected tool calls never
audited, no idempotency protection against a retried/replayed/racing call,
and the approval-execute path bypassing the permission gate entirely (so a
tool disabled after an approval was queued could still run once approved).
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, role):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": f"Ash Safety Test {role}", "email": email, "password": "AshSafetyTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": role}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "AshSafetyTest2026!"})
    assert r.status_code == 200, f"login as {role} failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    assert body["user"]["role"] == role
    return {"Authorization": f"Bearer {body['token']}"}


def _reset_kill_switch(client, owner_headers):
    req(client, "POST", "/api/nua/kill-switch", headers=owner_headers, json={"enabled": False})


# ─────────────────────────────────────────────────────────────────────────
# Risk-tier floor: high/critical-risk tools can never auto-execute
# ─────────────────────────────────────────────────────────────────────────
def test_setting_a_high_risk_tool_to_auto_is_rejected_at_the_api(client, owner_headers):
    r = req(client, "PUT", "/api/nua/tools/add_wallet_credit/permission", headers=owner_headers,
            json={"permission": "auto"})
    assert r.status_code == 400, r.text[:200]
    assert "high" in r.json()["detail"].lower()


def test_a_high_risk_tool_forced_to_auto_in_the_database_still_does_not_auto_execute(client, owner_headers):
    # Simulates the config-only gap the audit found: some other write path,
    # a bad migration, a manual DB edit — anything that lands "auto" on a
    # high-risk tool's db.ash_tool_config doc without going through the
    # (now-guarded) API. resolve_permission()'s floor must still catch it.
    _run(db.ash_tool_config.update_one(
        {"toolName": "add_wallet_credit"},
        {"$set": {"toolName": "add_wallet_credit", "permission": "auto"}},
        upsert=True,
    ))
    try:
        created = req(client, "POST", "/api/customers", headers=owner_headers, json={
            "name": "Risk Floor Customer", "email": "risk.floor@example.com", "phone": "0400000010"})
        customer_id = created.json()["id"]

        r = req(client, "POST", "/api/nua/tools/add_wallet_credit/execute", headers=owner_headers,
                json={"args": {"customerId": customer_id, "amount": 500, "reason": "should not auto-run"}})
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert body["status"] == "pending_approval", (
            "a high-risk tool must never resolve to auto, even with 'auto' sitting in the database"
        )

        customer = _run(db.customers.find_one({"id": customer_id}, {"_id": 0, "storeCredit": 1}))
        assert not (customer or {}).get("storeCredit"), "wallet must not be credited before an approval"
    finally:
        _run(db.ash_tool_config.delete_one({"toolName": "add_wallet_credit"}))


# ─────────────────────────────────────────────────────────────────────────
# Global kill switch
# ─────────────────────────────────────────────────────────────────────────
def test_kill_switch_is_owner_only(client, owner_headers):
    manager = _login_as(client, owner_headers, email="ash.safety.manager@nua.com", role="manager")
    r = req(client, "POST", "/api/nua/kill-switch", headers=manager, json={"enabled": True})
    assert r.status_code == 403, r.text[:200]


def test_engaging_the_kill_switch_blocks_direct_api_execution_and_is_audited(client, owner_headers):
    on = req(client, "POST", "/api/nua/kill-switch", headers=owner_headers,
             json={"enabled": True, "reason": "test: freezing Ash"})
    assert on.status_code == 200, on.text[:200]
    assert on.json()["enabled"] is True
    try:
        # create_staff_task is risk=low/permission=auto — would normally run
        # immediately. The kill switch must stop it regardless of the
        # tool's own risk tier or permission.
        r = req(client, "POST", "/api/nua/tools/create_staff_task/execute", headers=owner_headers,
                json={"args": {"title": "must not be created while paused"}})
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert body["status"] == "blocked"
        assert body.get("killSwitch") is True

        task = _run(db.tasks.find_one({"title": "must not be created while paused"}))
        assert task is None, "kill switch must prevent the tool from running at all, not just report blocked"

        blocked_event = _run(db.audit_events.find_one(
            {"entityType": "ash_tool:Staff", "entityId": "create_staff_task", "action": "blocked"},
            sort=[("_id", -1)],
        ))
        assert blocked_event is not None, "a kill-switch block must leave an audit trail"
        assert blocked_event["after"]["reason"] == "kill_switch_engaged"
    finally:
        _reset_kill_switch(client, owner_headers)

    status = req(client, "GET", "/api/nua/kill-switch", headers=owner_headers).json()
    assert status["enabled"] is False


def test_kill_switch_also_blocks_execution_of_an_already_approved_action(client, owner_headers):
    """Closes the approval-execute bypass the audit found: routes/approvals.py
    called tool.execute() directly, skipping every check in execute_tool()
    (including the kill switch) — an approval queued before the switch was
    engaged could still run after. It must not."""
    created = req(client, "POST", "/api/customers", headers=owner_headers, json={
        "name": "Kill Switch Approval Customer", "email": "killswitch.approval@example.com",
        "phone": "0400000011"})
    customer_id = created.json()["id"]

    queued = req(client, "POST", "/api/nua/tools/add_wallet_credit/execute", headers=owner_headers,
                 json={"args": {"customerId": customer_id, "amount": 250, "reason": "queued before pause"}})
    assert queued.status_code == 200, queued.text[:200]
    approval_id = queued.json()["approvalId"]

    on = req(client, "POST", "/api/nua/kill-switch", headers=owner_headers, json={"enabled": True})
    assert on.status_code == 200
    try:
        approve_r = req(client, "POST", f"/api/approvals/{approval_id}/approve", headers=owner_headers)
        assert approve_r.status_code == 200, approve_r.text[:200]
        result = approve_r.json()
        assert result["outcome"].get("blocked") is True

        customer = _run(db.customers.find_one({"id": customer_id}, {"_id": 0, "storeCredit": 1}))
        assert not (customer or {}).get("storeCredit"), "the kill switch must block execution even for an already-approved action"
    finally:
        _reset_kill_switch(client, owner_headers)


# ─────────────────────────────────────────────────────────────────────────
# Blocked/rejected attempts are audited
# ─────────────────────────────────────────────────────────────────────────
def test_an_unknown_tool_call_is_audited_as_blocked(client, owner_headers):
    r = req(client, "POST", "/api/nua/tools/not_a_real_tool/execute", headers=owner_headers,
            json={"args": {}})
    assert r.status_code == 200, r.text[:200]
    assert r.json()["status"] == "error"

    event = _run(db.audit_events.find_one(
        {"entityType": "ash_tool:unknown", "entityId": "not_a_real_tool", "action": "blocked"},
        sort=[("_id", -1)],
    ))
    assert event is not None, "an unknown-tool call must still leave an audit trail, not vanish silently"


def test_a_disabled_tool_call_is_audited_as_blocked(client, owner_headers):
    disable = req(client, "PUT", "/api/nua/tools/add_customer_note/permission", headers=owner_headers,
                   json={"permission": "disabled"})
    assert disable.status_code == 200
    try:
        r = req(client, "POST", "/api/nua/tools/add_customer_note/execute", headers=owner_headers,
                json={"args": {"customerId": "does-not-matter", "note": "should be blocked"}})
        assert r.status_code == 200
        assert r.json()["status"] == "blocked"

        event = _run(db.audit_events.find_one(
            {"entityType": "ash_tool:Customers", "entityId": "add_customer_note", "action": "blocked"},
            sort=[("_id", -1)],
        ))
        assert event is not None
        assert event["after"]["reason"] == "disabled_by_policy"
    finally:
        req(client, "PUT", "/api/nua/tools/add_customer_note/permission", headers=owner_headers,
            json={"permission": "auto"})


def test_approving_a_since_disabled_tool_is_blocked_not_executed(client, owner_headers):
    """The other half of the approval-execute bypass: a tool disabled after
    its approval was queued must not run just because someone clicks
    approve — resolve_permission() is re-checked at execution time now."""
    created = req(client, "POST", "/api/customers", headers=owner_headers, json={
        "name": "Disabled After Queue Customer", "email": "disabled.after.queue@example.com",
        "phone": "0400000012"})
    customer_id = created.json()["id"]

    queued = req(client, "POST", "/api/nua/tools/add_wallet_credit/execute", headers=owner_headers,
                 json={"args": {"customerId": customer_id, "amount": 300, "reason": "queued then disabled"}})
    approval_id = queued.json()["approvalId"]

    disable = req(client, "PUT", "/api/nua/tools/add_wallet_credit/permission", headers=owner_headers,
                   json={"permission": "disabled"})
    assert disable.status_code == 200
    try:
        approve_r = req(client, "POST", f"/api/approvals/{approval_id}/approve", headers=owner_headers)
        assert approve_r.status_code == 200, approve_r.text[:200]
        assert approve_r.json()["outcome"].get("blocked") is True

        customer = _run(db.customers.find_one({"id": customer_id}, {"_id": 0, "storeCredit": 1}))
        assert not (customer or {}).get("storeCredit")
    finally:
        req(client, "PUT", "/api/nua/tools/add_wallet_credit/permission", headers=owner_headers,
            json={"permission": "approval"})


# ─────────────────────────────────────────────────────────────────────────
# Idempotency
# ─────────────────────────────────────────────────────────────────────────
def test_a_repeated_idempotency_key_executes_the_mutating_tool_only_once(client, owner_headers):
    key = "test-idem-key-ash-safety-1"
    payload = {"args": {"title": "Idempotent task"}, "idempotencyKey": key}

    first = req(client, "POST", "/api/nua/tools/create_staff_task/execute", headers=owner_headers, json=payload)
    second = req(client, "POST", "/api/nua/tools/create_staff_task/execute", headers=owner_headers, json=payload)
    assert first.status_code == 200 and second.status_code == 200

    first_body, second_body = first.json(), second.json()
    assert first_body["status"] == "executed"
    assert second_body == first_body, "a replayed call with the same idempotency key must return the exact same result"

    count = _run(db.tasks.count_documents({"title": "Idempotent task"}))
    assert count == 1, "the tool must have executed exactly once, not once per call"


def test_a_different_idempotency_key_executes_again(client, owner_headers):
    r1 = req(client, "POST", "/api/nua/tools/create_staff_task/execute", headers=owner_headers,
             json={"args": {"title": "Distinct task A"}, "idempotencyKey": "test-idem-key-ash-safety-2a"})
    r2 = req(client, "POST", "/api/nua/tools/create_staff_task/execute", headers=owner_headers,
             json={"args": {"title": "Distinct task B"}, "idempotencyKey": "test-idem-key-ash-safety-2b"})
    assert r1.json()["outcome"]["taskId"] != r2.json()["outcome"]["taskId"]


# ─────────────────────────────────────────────────────────────────────────
# Rollback for the highest-blast-radius tools
# ─────────────────────────────────────────────────────────────────────────
def test_wallet_credit_rollback_reverses_the_credit(client, owner_headers):
    from middleware.actor_context import _actor_ctx
    token = _actor_ctx.set({"businessId": "default", "email": "owner@nua.com"})
    created = req(client, "POST", "/api/customers", headers=owner_headers, json={
        "name": "Wallet Rollback Customer", "email": "wallet.rollback@example.com", "phone": "0400000013"})
    customer_id = created.json()["id"]

    # Force auto just for this one call via a direct DB override so the
    # credit executes immediately instead of queuing — the flag/undo
    # endpoint only operates on already-executed (auto-tier) actions.
    _run(db.ash_tool_config.update_one(
        {"toolName": "add_wallet_credit"}, {"$set": {"permission": "approval"}}, upsert=True))
    try:
        from services import nua_tools
        outcome = _run(nua_tools._tx_add_wallet_credit({"customerId": customer_id, "amount": 100, "reason": "test"}))
        assert outcome["matched"] == 1
        before = _run(db.customers.find_one({"id": customer_id}, {"_id": 0, "storeCredit": 1}))
        assert before["storeCredit"] == 100

        _run(nua_tools._rollback_wallet_credit(outcome))
        after = _run(db.customers.find_one({"id": customer_id}, {"_id": 0, "storeCredit": 1}))
        assert after["storeCredit"] == 0

        ledger = _run(db.wallet_ledger.find({"customerId": customer_id}, {"_id": 0}).to_list(10))
        assert any(e["type"] == "credit_reversal" and e["amount"] == -100 for e in ledger)
    finally:
        _actor_ctx.reset(token)
        _run(db.ash_tool_config.delete_one({"toolName": "add_wallet_credit"}))


def test_mark_dish_86_rollback_restores_the_prior_state(client, owner_headers):
    product = req(client, "POST", "/api/products", headers=owner_headers, json={
        "name": "86 Rollback Widget", "price": 15, "cost": 5, "category": "Test",
        "stock": 3, "sku": "86-ROLLBACK-1"})
    product_id = product.json()["id"]

    from services import nua_tools
    outcome = _run(nua_tools._tx_mark_dish_86({"productId": product_id, "reason": "test 86"}))
    assert outcome["matched"] == 1
    row = _run(db.products.find_one({"id": product_id}, {"_id": 0, "eightySixed": 1}))
    assert row["eightySixed"] is True

    _run(nua_tools._rollback_dish_86(outcome))
    row_after = _run(db.products.find_one({"id": product_id}, {"_id": 0, "eightySixed": 1}))
    assert row_after["eightySixed"] is False
