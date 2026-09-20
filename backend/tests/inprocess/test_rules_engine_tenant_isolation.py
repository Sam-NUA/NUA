"""services/rules_engine.py's emit_event() evaluated and executed EVERY
business's active automation rules matching an event type, not just the
triggering business's own — so Business A's automation rule ("on
pos.sale.completed, upgrade VIP if spend > $X") fired against Business
B's own sale events too, not just Business A's. routes/rules_engine.py
had the same unscoped-CRUD pattern on top: any business could list, read,
edit, delete, or toggle any other business's automation rules.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Rules Engine Test Owner", "email": email, "password": "RulesEngineTenantTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "RulesEngineTenantTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def test_emitting_an_event_only_fires_this_businesss_own_rules(client, owner_headers):
    other = _login_as(client, owner_headers, email="rules.emit.other@nua.com", business_id="rules-emit-other-biz")

    created = req(client, "POST", "/api/rules", headers=other, json={
        "name": "Other biz dock-notify rule", "triggerEvent": "pos.sale.completed",
        "conditions": {"mode": "all", "clauses": []},
        "actions": [{"type": "dock_notify", "params": {"message": "should not fire for another business"}}],
        "active": True,
    })
    assert created.status_code == 200, created.text[:200]
    rule_id = created.json()["id"]
    try:
        # My business emits the same event type — the other business's rule
        # must not be among the ones evaluated.
        emitted = req(client, "POST", "/api/rules/emit", headers=owner_headers,
                      json={"type": "pos.sale.completed", "payload": {"total": 999999}})
        assert emitted.status_code == 200, emitted.text[:200]
        fired_rule_ids = {f["ruleId"] for f in emitted.json()["ruleFirings"]}
        assert rule_id not in fired_rule_ids, (
            "another business's rule must not be evaluated or fired by this business's event"
        )

        unchanged = _run(db.rules.find_one({"id": rule_id}, {"_id": 0}))
        assert unchanged["triggerCount"] == 0, "another business's rule must not have its trigger count bumped"
    finally:
        _run(db.rules.delete_one({"id": rule_id}))


def test_rules_crud_is_scoped_and_owned_per_business(client, owner_headers):
    other = _login_as(client, owner_headers, email="rules.crud.other@nua.com", business_id="rules-crud-other-biz")

    created = req(client, "POST", "/api/rules", headers=other, json={
        "name": "Other biz secret rule", "triggerEvent": "customer.birthday",
        "conditions": {"mode": "all", "clauses": []},
        "actions": [{"type": "dock_notify", "params": {"message": "x"}}],
        "active": True,
    })
    assert created.status_code == 200, created.text[:200]
    rule_id = created.json()["id"]
    try:
        mine = req(client, "GET", "/api/rules", headers=owner_headers).json()
        assert not any(r["id"] == rule_id for r in mine)

        get_mine = req(client, "GET", f"/api/rules/{rule_id}", headers=owner_headers)
        assert get_mine.status_code == 404

        update_mine = req(client, "PATCH", f"/api/rules/{rule_id}", headers=owner_headers, json={"name": "hijacked"})
        assert update_mine.status_code == 404

        toggle_mine = req(client, "POST", f"/api/rules/{rule_id}/toggle", headers=owner_headers)
        assert toggle_mine.status_code == 404

        delete_mine = req(client, "DELETE", f"/api/rules/{rule_id}", headers=owner_headers)
        assert delete_mine.status_code == 404

        still_there = req(client, "GET", f"/api/rules/{rule_id}", headers=other)
        assert still_there.status_code == 200
        assert still_there.json()["name"] == "Other biz secret rule", "cross-tenant attempts must not have mutated it"
    finally:
        _run(db.rules.delete_one({"id": rule_id}))
