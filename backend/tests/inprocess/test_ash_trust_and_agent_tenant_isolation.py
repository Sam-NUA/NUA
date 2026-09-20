"""Final pre-merge assurance pass: an independent security review found two
Critical cross-tenant bugs and one High-severity one, none caught by the
existing test suite because none of it exercised a second business against
these specific surfaces.

1. services/nua_trust.py's db.ash_tool_config reads/writes had no
   businessId at all — a promotion earned by one business's clean-approval
   streak could silently flip a tool to "auto" execution for every other
   business on the deployment (or vice-versa for a demotion).
2. routes/loyalty_engine.py's POST /agent/tick and its six helper functions
   ran against every business's customers/tiers/products/reservations
   regardless of who triggered it — a routine automation run could zero
   points, change membership tiers, and issue real wallet vouchers for
   another business's customers.
3. services/nua_tools.py's _tx_approve_pending_approval/
   _tx_reject_pending_approval (the Ash-tool-callable versions of
   approve/reject an approval) looked an approval up by client-supplied
   approvalId with no tenant check at all, unlike the HTTP endpoints in
   routes/approvals.py which already checked ownership.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Trust Isolation Test Owner", "email": email, "password": "TrustIsoTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "TrustIsoTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


# ─────────────────────────────────────────────────────────────────────────
# nua_trust.py — ash_tool_config trust ladder
# ─────────────────────────────────────────────────────────────────────────
def test_a_tools_trust_streak_is_scoped_per_business(client, owner_headers):
    """Business A builds a clean-approval streak on a tool via
    record_decision (simulated directly — driving the real approval queue
    end to end isn't needed to prove the isolation). Business B, which has
    never made a single decision about this tool, must see a completely
    fresh trust state, not A's streak."""
    other = _login_as(client, owner_headers, email="trust.iso.a@nua.com", business_id="trust-iso-biz-a")
    tool_name = "add_customer_note"  # a real, low-risk, trust-eligible tool
    _run(db.ash_tool_config.delete_many({"toolName": tool_name}))
    try:
        from services import nua_trust
        for i in range(8):
            _run(nua_trust.record_decision(tool_name, "approved", f"fake-approval-{i}",
                                            business_id="trust-iso-biz-a"))

        trust_a = req(client, "GET", f"/api/nua/tools/{tool_name}/trust", headers=other).json()
        assert trust_a["trust"]["consecutiveApproved"] == 8

        trust_b = req(client, "GET", f"/api/nua/tools/{tool_name}/trust", headers=owner_headers).json()
        assert trust_b["trust"]["consecutiveApproved"] == 0, (
            "business B must not see business A's approval streak on a shared tool"
        )
    finally:
        _run(db.ash_tool_config.delete_many({"toolName": tool_name}))
        _run(db.ash_trust_events.delete_many({"toolName": tool_name}))


def test_promoting_a_tool_to_auto_does_not_affect_other_businesses(client, owner_headers):
    """The actual exploit: business A promotes a tool to "auto" — business
    B's own resolve_permission() for that same tool must be unaffected.
    mark_dish_86 (medium risk, defaultPermission="approval") — unlike
    add_customer_note above, this tool's own baseline is NOT already
    "auto" for everyone, so a false pass here can't hide behind the tool's
    own default."""
    other = _login_as(client, owner_headers, email="trust.iso.b@nua.com", business_id="trust-iso-biz-b")
    tool_name = "mark_dish_86"
    _run(db.ash_tool_config.delete_many({"toolName": tool_name}))
    try:
        from services import nua_trust
        # Build eligibility directly rather than driving 6 real approvals —
        # promote() itself re-validates eligibility server-side, so this
        # only proves the isolation, not that eligibility math is skipped.
        settings = _run(nua_trust.get_settings("trust-iso-biz-b"))
        for i in range(settings["minStreak"]):
            _run(nua_trust.record_decision(tool_name, "approved", f"fake-{i}", business_id="trust-iso-biz-b"))
        _run(db.ash_tool_config.update_one(
            {"toolName": tool_name, "businessId": "trust-iso-biz-b"},
            {"$set": {"trust.streakStartedAt": "2020-01-01T00:00:00+00:00"}},
        ))

        promoted = req(client, "POST", f"/api/nua/tools/{tool_name}/promote", headers=other)
        assert promoted.status_code == 200, promoted.text[:200]
        assert promoted.json()["permission"] == "auto"

        from services.nua_tools import resolve_permission
        perm_b = _run(resolve_permission(tool_name, "trust-iso-biz-b"))
        assert perm_b == "auto"
        perm_a = _run(resolve_permission(tool_name, "default"))
        assert perm_a != "auto", (
            "promoting a tool to auto for business B must not auto-execute it for business A too"
        )
    finally:
        _run(db.ash_tool_config.delete_many({"toolName": tool_name}))
        _run(db.ash_trust_events.delete_many({"toolName": tool_name}))


# ─────────────────────────────────────────────────────────────────────────
# loyalty_engine.py — POST /agent/tick and its helpers
# ─────────────────────────────────────────────────────────────────────────
def test_agent_tick_does_not_touch_another_businesss_customer_points(client, owner_headers):
    other = _login_as(client, owner_headers, email="agent.tick.a@nua.com", business_id="agent-tick-biz-a")
    _run(db.customers.insert_one({
        "id": "ATICK-CUST-OTHER", "name": "Other Biz Customer", "points": 500,
        "businessId": "agent-tick-biz-b",  # a DIFFERENT business than the caller
    }))
    _run(db.loyalty_config.update_one(
        {"id": "default", "businessId": "agent-tick-biz-a"},
        {"$set": {"id": "default", "businessId": "agent-tick-biz-a", "pointsExpiryDays": 1}},
        upsert=True,
    ))
    try:
        r = req(client, "POST", "/api/agent/tick", headers=other)
        assert r.status_code == 200, r.text[:300]

        untouched = _run(db.customers.find_one({"id": "ATICK-CUST-OTHER"}, {"_id": 0}))
        assert untouched["points"] == 500, (
            "business A's agent tick must never zero out business B's customer's points"
        )
    finally:
        _run(db.customers.delete_many({"id": "ATICK-CUST-OTHER"}))
        _run(db.loyalty_config.delete_many({"businessId": "agent-tick-biz-a"}))
        _run(db.agent_decisions.delete_many({"businessId": "agent-tick-biz-a"}))


def test_agent_segments_and_decisions_are_scoped_per_business(client, owner_headers):
    other = _login_as(client, owner_headers, email="agent.seg.a@nua.com", business_id="agent-seg-biz-a")
    _run(db.customers.insert_one({
        "id": "ASEG-CUST-OTHER", "name": "Other Biz VIP", "points": 10,
        "visits": 20, "totalSpent": 1000, "businessId": "agent-seg-biz-b",
    }))
    try:
        segs = req(client, "GET", "/api/agent/segments", headers=other).json()
        assert "ASEG-CUST-OTHER" not in segs["ids"]["vip"], (
            "business A's segment view must not include business B's customers"
        )
    finally:
        _run(db.customers.delete_many({"id": "ASEG-CUST-OTHER"}))


# ─────────────────────────────────────────────────────────────────────────
# nua_tools.py — Ash-tool approve/reject tenant check
# ─────────────────────────────────────────────────────────────────────────
def test_ash_tool_cannot_approve_another_businesss_pending_approval(client, owner_headers):
    """approve_pending_approval is risk="high", so resolve_permission's hard
    floor (services/nua_tools.py: "high/critical-risk tools can never
    resolve to auto") means it can NEVER be called directly through
    POST /nua/tools/approve_pending_approval/execute — that endpoint would
    only ever enqueue a fresh approval for it, never actually run
    _tx_approve_pending_approval. The real path the underlying finding
    describes is one level up: the Ash agent enqueues a *meta-approval*
    whose actionType is itself "approve_pending_approval" (source=
    ash_agent) with a client/agent-supplied params.approvalId. A manager
    approves that meta-approval for their OWN business via the ordinary
    POST /approvals/{id}/approve endpoint (routes/approvals.py, which does
    check the meta-approval's own tenant, correctly) — that handler then
    calls tool.execute(params) directly with no check on which business
    the target approvalId actually belongs to. Without the tenant_owns
    check inside _tx_approve_pending_approval itself, this lets business
    A's manager unknowingly rubber-stamp business B's pending approval."""
    other = _login_as(client, owner_headers, email="approve.bypass.a@nua.com", business_id="approve-bypass-biz-a")
    target_id = "APR-BYPASS-TARGET-1"
    meta_id = "APR-BYPASS-META-1"
    _run(db.approvals.insert_one({
        "id": target_id, "actionType": "issue_voucher", "status": "pending",
        "params": {}, "businessId": "approve-bypass-biz-b",  # belongs to a DIFFERENT business
        "requestedBy": "system", "source": "ash_agent", "createdAt": "2026-01-01T00:00:00+00:00",
    }))
    _run(db.approvals.insert_one({
        "id": meta_id, "actionType": "approve_pending_approval", "status": "pending",
        "params": {"approvalId": target_id}, "businessId": "approve-bypass-biz-a",  # the caller's OWN business
        "requestedBy": "ash-agent", "source": "ash_agent", "createdAt": "2026-01-01T00:00:00+00:00",
    }))
    try:
        r = req(client, "POST", f"/api/approvals/{meta_id}/approve", headers=other)
        assert r.status_code == 200, r.text[:300]
        outcome = (r.json() or {}).get("outcome") or {}
        assert outcome.get("error"), (
            f"business A must not be able to approve business B's pending approval — got {outcome}"
        )

        still_pending = _run(db.approvals.find_one({"id": target_id}, {"_id": 0}))
        assert still_pending["status"] == "pending", "the other business's approval must be untouched"
    finally:
        _run(db.approvals.delete_many({"id": {"$in": [target_id, meta_id]}}))
