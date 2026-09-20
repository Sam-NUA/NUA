"""routes/approvals.py had zero businessId scoping anywhere: list, get,
approve and reject all operated on `db.approvals` with no tenant filter at
all, and `services/approval_service.enqueue_approval` never stamped a
businessId on the document in the first place. Every pending high-risk
approval on the whole deployment — refunds over threshold, purchase
orders, marketing campaigns, VIP tier downgrades, Ash agent tool calls
awaiting sign-off — was visible to, and actionable by, any owner/manager
of ANY business, not just their own. An owner of Business A could approve
or reject Business B's pending refund or voucher issuance.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Approvals Test Owner", "email": email, "password": "ApprovalsTenantTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "ApprovalsTenantTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def test_a_different_businesss_pending_approval_is_not_visible_or_actionable(client, owner_headers):
    other = _login_as(client, owner_headers, email="approvals.other.owner@nua.com", business_id="approvals-other-biz")

    import uuid
    from datetime import datetime, timezone
    aid = str(uuid.uuid4())
    _run(db.approvals.insert_one({
        "id": aid, "actionType": "issue_refund", "params": {"amount": 250},
        "requestedBy": "system", "source": "rules_engine", "sourceRef": None,
        "context": {}, "status": "pending", "createdAt": datetime.now(timezone.utc).isoformat(),
        "resolvedAt": None, "resolvedBy": None, "resolution": None, "outcome": None,
        "businessId": "approvals-other-biz",
    }))
    try:
        mine = req(client, "GET", "/api/approvals", headers=owner_headers).json()
        assert not any(a["id"] == aid for a in mine), (
            "a different business's pending approval must not appear in this business's list"
        )

        get_mine = req(client, "GET", f"/api/approvals/{aid}", headers=owner_headers)
        assert get_mine.status_code == 404

        approve_mine = req(client, "POST", f"/api/approvals/{aid}/approve", headers=owner_headers)
        assert approve_mine.status_code == 404, "must not be able to approve another business's pending action"

        reject_mine = req(client, "POST", f"/api/approvals/{aid}/reject", headers=owner_headers, json={"reason": "nope"})
        assert reject_mine.status_code == 404, "must not be able to reject another business's pending action"

        theirs = req(client, "GET", "/api/approvals", headers=other).json()
        assert any(a["id"] == aid for a in theirs)

        get_theirs = req(client, "GET", f"/api/approvals/{aid}", headers=other)
        assert get_theirs.status_code == 200

        still_pending = _run(db.approvals.find_one({"id": aid}, {"_id": 0}))
        assert still_pending["status"] == "pending", "the cross-tenant approve/reject attempts must not have mutated it"
    finally:
        _run(db.approvals.delete_one({"id": aid}))


def test_enqueue_approval_stamps_business_id_from_the_current_request_context():
    from middleware.actor_context import set_actor_context
    from services import approval_service

    set_actor_context({"businessId": "approvals-ctx-biz"})
    try:
        doc = _run(approval_service.enqueue_approval(
            action_type="apply_discount", params={"discount": 40}, requested_by="rule:test",
        ))
        assert doc["businessId"] == "approvals-ctx-biz"
    finally:
        _run(db.approvals.delete_one({"id": doc["id"]}))
        set_actor_context({})
