"""Smart Table Service contract: event sources, owner rules, dedup, escalation and isolation."""
import asyncio
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from database import db
from conftest import req


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def stamp(minutes_ago):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def api(client, headers, method, path, **kwargs):
    return req(client, method, "/api/table-service" + path, headers=headers, **kwargs)


def owner_rules(client, headers, **changes):
    r = api(client, headers, "GET", "/settings")
    assert r.status_code == 200, r.text
    cfg = r.json()
    cfg.update(changes)
    saved = api(client, headers, "PUT", "/settings", json=cfg)
    assert saved.status_code == 200, saved.text
    return cfg


def seed(business="default", number="601", age=16, course="seated", events=None, with_order=None):
    """Real owned floor plan + seating state, not a bare table-state shortcut."""
    suffix = uuid4().hex[:8]
    tid = "SERVICE_TABLE_" + suffix
    plan_id = "SERVICE_PLAN_" + suffix
    state_id = "SERVICE_SESSION_" + suffix
    doc = {
        "id": plan_id, "businessId": business, "name": "Service Test Plan", "isActive": True,
        "tables": [{"id": tid, "number": number, "name": "Service test table",
                    "status": "occupied", "capacity": 4, "isActive": True}],
    }
    state = {"id": state_id, "businessId": business, "tableId": tid,
             "course": course, "seatedAt": stamp(age),
             "courseStartedAt": stamp(age), "serviceEvents": events or {},
             "serverId": None}
    run(db.floor_plans.insert_one(doc))
    run(db.table_states.insert_one(state))
    if with_order:
        order = {
            "id": "SERVICE_ORDER_" + suffix, "businessId": business,
            "tableNumber": number, "status": "preparing", "createdAt": stamp(age - 1),
            "courses": with_order, "items": [{"productName": "Steak",
                "category": "Mains", "quantity": 1, "course": 2}],
        }
        run(db.kitchen_orders.insert_one(order))
    return {"tableId": tid, "planId": plan_id, "stateId": state_id,
            "orderId": "SERVICE_ORDER_" + suffix, "business": business}


def cleanup(*seeds):
    for s in seeds:
        run(db.floor_plans.delete_one({"id": s["planId"]}))
        run(db.table_states.delete_one({"id": s["stateId"]}))
        run(db.kitchen_orders.delete_one({"id": s["orderId"]}))
        run(db.table_service_alerts.delete_many({"sessionId": s["stateId"]}))


def list_alerts(client, headers):
    r = api(client, headers, "GET", "/alerts")
    assert r.status_code == 200, r.text
    return r.json()["alerts"]


def test_owner_opt_in_limits_and_missing_login(client, owner_headers, anon):
    unauth = anon.get("/api/table-service/alerts")
    assert unauth.status_code in (401, 403)
    cfg = api(client, owner_headers, "GET", "/settings").json()
    assert cfg["enabled"] is False
    assert cfg["rules"]["no_order"]["warningMinutes"] == 5
    invalid = {**cfg, "enabled": True}
    invalid["rules"] = {**cfg["rules"]}
    invalid["rules"]["mains_held"] = {
        "enabled": True, "warningMinutes": 40, "escalateMinutes": 30,
    }
    rejected = api(client, owner_headers, "PUT", "/settings", json=invalid)
    assert rejected.status_code == 422
    invalid["rules"]["mains_held"] = cfg["rules"]["mains_held"]


def test_one_alert_per_session_ack_and_event_clears_it(client, owner_headers):
    owner_rules(client, owner_headers, enabled=True)
    s = seed(number="901", age=13)
    try:
        first = [a for a in list_alerts(client, owner_headers) if a["tableId"] == s["tableId"]]
        assert len(first) == 1, first
        alert = first[0]
        assert alert["rule"] == "no_order" and alert["level"] == "urgent"
        repeat = [a for a in list_alerts(client, owner_headers) if a["tableId"] == s["tableId"]]
        assert [x["id"] for x in repeat] == [alert["id"]], "Polling tablets must not duplicate alerts"
        ack = api(client, owner_headers, "POST", f"/alerts/{alert['id']}/acknowledge")
        assert ack.status_code == 200
        assert next(a for a in list_alerts(client, owner_headers) if a["id"] == alert["id"])["status"] == "acknowledged"
        marked = api(client, owner_headers, "POST", f"/tables/{s['tableId']}/events", json={"event": "order_taken"})
        assert marked.status_code == 200, marked.text
        assert not any(a["id"] == alert["id"] for a in list_alerts(client, owner_headers))
        stored = run(db.table_service_alerts.find_one({"id": alert["id"]}))
        assert stored["status"] == "resolved"
    finally:
        cleanup(s)
        owner_rules(client, owner_headers, enabled=False)


def test_drinks_and_food_events_prevent_false_alerts(client, owner_headers):
    owner_rules(client, owner_headers, enabled=True)
    s = seed(number="902", age=14, course="drinks",
             events={"order_taken": stamp(13), "drinks_served": stamp(10)})
    try:
        alerts = [a for a in list_alerts(client, owner_headers) if a["tableId"] == s["tableId"]]
        assert {x["rule"] for x in alerts} == {"after_drinks"}
        r = api(client, owner_headers, "POST", f"/tables/{s['tableId']}/events",
                json={"event": "food_order_taken"})
        assert r.status_code == 200, r.text
        assert not any(a["tableId"] == s["tableId"] for a in list_alerts(client, owner_headers))
    finally:
        cleanup(s)
        owner_rules(client, owner_headers, enabled=False)


def test_mains_held_vs_fired_and_food_at_pass(client, owner_headers):
    owner_rules(client, owner_headers, enabled=True)
    s = seed(number="903", age=35, course="entree",
             with_order={"1": {"status": "served", "servedAt": stamp(12)},
                         "2": {"status": "held", "heldAt": stamp(18)}})
    try:
        first = [a for a in list_alerts(client, owner_headers) if a["tableId"] == s["tableId"]]
        assert "mains_held" in {a["rule"] for a in first}, first
        assert "mains_delayed" not in {a["rule"] for a in first}
        run(db.kitchen_orders.update_one({"id": s["orderId"]}, {"$set": {
            "courses.2.status": "fired", "courses.2.firedAt": stamp(25)}}))
        next_alerts = [a for a in list_alerts(client, owner_headers) if a["tableId"] == s["tableId"]]
        assert "mains_held" not in {a["rule"] for a in next_alerts}
        assert "mains_delayed" in {a["rule"] for a in next_alerts}
        run(db.kitchen_orders.update_one({"id": s["orderId"]}, {"$set": {
            "courses.2.status": "ready", "courses.2.readyAt": stamp(8)}}))
        latest = [a for a in list_alerts(client, owner_headers) if a["tableId"] == s["tableId"]]
        assert "mains_delayed" not in {a["rule"] for a in latest}
        assert any(a["rule"] == "ready_waiting" for a in latest)
    finally:
        cleanup(s)
        owner_rules(client, owner_headers, enabled=False)


def test_snooze_then_reopen_and_explicit_resolve(client, owner_headers):
    owner_rules(client, owner_headers, enabled=True)
    s = seed(number="904", age=6)
    try:
        alert = next(x for x in list_alerts(client, owner_headers) if x["tableId"] == s["tableId"])
        assert alert["level"] == "warning"
        snooze = api(client, owner_headers, "POST", f"/alerts/{alert['id']}/snooze", json={"minutes": 3})
        assert snooze.status_code == 200
        assert next(x for x in list_alerts(client, owner_headers) if x["id"] == alert["id"])["status"] == "snoozed"
        run(db.table_service_alerts.update_one({"id": alert["id"]}, {
            "$set": {"snoozedUntil": stamp(1)}}))
        assert next(x for x in list_alerts(client, owner_headers) if x["id"] == alert["id"])["status"] == "open"
        resolve = api(client, owner_headers, "POST", f"/alerts/{alert['id']}/resolve")
        assert resolve.status_code == 200
        assert all(x["id"] != alert["id"] for x in list_alerts(client, owner_headers))
        assert api(client, owner_headers, "POST", f"/alerts/{alert['id']}/resolve").status_code == 404
    finally:
        cleanup(s)
        owner_rules(client, owner_headers, enabled=False)


def _other_login(client, owner_headers):
    email = f"table.service.{uuid4().hex[:8]}@example.com"
    created = client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Different Owner", "email": email, "password": "TestService2026!"})
    assert created.status_code in (200, 201), created.text
    run(db.auth_users.update_one({"email": email}, {"$set": {
        "role": "owner", "businessId": "other-table-service"}}))
    login = client.post("/api/auth/login", json={"email": email, "password": "TestService2026!"})
    assert login.status_code == 200, login.text
    client.cookies.clear()
    return {"Authorization": "Bearer " + login.json()["token"]}, email


def test_tenant_isolation_on_alerts_actions_and_service_events(client, owner_headers):
    owner_rules(client, owner_headers, enabled=True)
    s = seed(number="905", age=13)
    other, email = _other_login(client, owner_headers)
    owner_rules(client, other, enabled=True)
    try:
        mine = next(x for x in list_alerts(client, owner_headers) if x["tableId"] == s["tableId"])
        assert all(x["id"] != mine["id"] for x in list_alerts(client, other))
        assert api(client, other, "POST", f"/alerts/{mine['id']}/acknowledge").status_code == 404
        assert api(client, other, "POST", f"/tables/{s['tableId']}/events",
                   json={"event": "order_taken"}).status_code == 404
        own = run(db.table_service_alerts.find_one({"id": mine["id"]}))
        assert own["status"] == "open"
    finally:
        cleanup(s)
        owner_rules(client, owner_headers, enabled=False)
        owner_rules(client, other, enabled=False)
        run(db.auth_users.delete_one({"email": email}))


def test_table_pacing_requires_tenant_for_kitchen_bridge(client, owner_headers):
    from services import table_pacing
    from services import coursing
    a = seed(number="906", age=2)
    b = seed(business="a-different-table-service-venue", number="906", age=2)
    try:
        cfg = dict(coursing.DEFAULT_COURSING_CONFIG)
        cfg["enabled"] = True
        cfg["syncTablePacing"] = True
        # A ticket for business B cannot advance A's identically numbered table.
        result = run(table_pacing.advance_for_course(
            {"businessId": b["business"], "tableNumber": "906", "id": "ORDER-B"},
            2, cfg))
        assert result == "main"
        mine = run(db.table_states.find_one({"id": a["stateId"]}))
        theirs = run(db.table_states.find_one({"id": b["stateId"]}))
        assert mine["course"] == "seated"
        assert theirs["course"] == "main"
    finally:
        cleanup(a, b)
