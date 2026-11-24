"""Smart Table Service: opt-in, deduplicated alerts, owner rules and cross-tenant safety."""
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from database import db
from tests.inprocess.conftest import req


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def new_table(biz="default"):
    table_id = "STS-" + uuid4().hex[:12]
    number = "STS-" + uuid4().hex[:9]
    plan_id = "PLAN-" + uuid4().hex[:9]
    run(db.floor_plans.insert_one({
        "id": plan_id, "businessId": biz, "name": "STS isolated test floor",
        "isActive": True, "tables": [{"id": table_id, "number": number,
                                      "isActive": True, "status": "occupied"}],
        "sections": [],
    }))
    return table_id, number, plan_id


def cleanup(table_id, plan_id, biz="default"):
    run(db.table_service_alerts.delete_many({"businessId": biz, "tableId": table_id}))
    run(db.table_states.delete_many({"businessId": biz, "tableId": table_id}))
    run(db.floor_plans.delete_one({"businessId": biz, "id": plan_id}))


def test_disabled_by_default_no_alerts(client, owner_headers):
    result = req(client, "GET", "/api/table-service/settings", headers=owner_headers)
    assert result.status_code == 200
    assert result.json()["enabled"] is False
    alerts = req(client, "GET", "/api/table-service/alerts", headers=owner_headers)
    assert alerts.status_code == 200
    assert alerts.json()["alerts"] == []


def test_owner_controls_alerts_and_staff_acknowledges(client, owner_headers):
    tid, number, plan = new_table()
    original = req(client, "GET", "/api/table-service/settings", headers=owner_headers).json()
    try:
        settings = {**original, "enabled": True}
        assert req(client, "PUT", "/api/table-service/settings",
                   headers=owner_headers, json=settings).status_code == 200

        seated = req(client, "POST", "/api/table-courses/states",
                     headers=owner_headers, json={"tableId": tid, "course": "seated"})
        assert seated.status_code == 200
        past = (datetime.now(timezone.utc) - timedelta(minutes=12)).isoformat()
        run(db.table_states.update_one({"tableId": tid, "businessId": "default"},
                                       {"$set": {"seatedAt": past, "courseStartedAt": past}}))
        first = req(client, "GET", "/api/table-service/alerts", headers=owner_headers)
        assert first.status_code == 200, first.text
        item = next(x for x in first.json()["alerts"] if x["tableId"] == tid and x["rule"] == "seated_no_order")
        assert item["priority"] == "urgent"
        second = req(client, "GET", "/api/table-service/alerts", headers=owner_headers)
        assert len([x for x in second.json()["alerts"] if x["id"] == item["id"]]) == 1
        assert run(db.table_service_alerts.count_documents({"id": item["id"]})) == 1

        ack = req(client, "POST", "/api/table-service/alerts/" + item["id"] + "/action",
                  headers=owner_headers, json={"action": "acknowledge"})
        assert ack.status_code == 200, ack.text
        assert ack.json()["status"] == "acknowledged"
        after_ack = req(client, "GET", "/api/table-service/alerts",
                        headers=owner_headers).json()["alerts"]
        assert next(x for x in after_ack if x["id"] == item["id"])["status"] == "acknowledged"

        record = req(client, "POST", "/api/table-service/events", headers=owner_headers,
                     json={"tableId": tid, "event": "food_order_taken"})
        assert record.status_code == 200, record.text
        resolved = req(client, "GET", "/api/table-service/alerts", headers=owner_headers)
        assert not any(x["id"] == item["id"] for x in resolved.json()["alerts"])
    finally:
        req(client, "PUT", "/api/table-service/settings", headers=owner_headers, json=original)
        cleanup(tid, plan)


def test_foreign_business_cannot_record_service_event(client, owner_headers):
    tid, _, plan = new_table(biz="other-tenant")
    try:
        response = req(client, "POST", "/api/table-service/events", headers=owner_headers,
                       json={"tableId": tid, "event": "drinks_served"})
        assert response.status_code == 404
    finally:
        cleanup(tid, plan, biz="other-tenant")


def test_rules_validate_escalation_after_first_warning(client, owner_headers):
    settings = req(client, "GET", "/api/table-service/settings", headers=owner_headers).json()
    settings["rules"]["seated_no_order"]["minutes"] = 20
    settings["rules"]["seated_no_order"]["escalateMinutes"] = 10
    result = req(client, "PUT", "/api/table-service/settings",
                 headers=owner_headers, json=settings)
    assert result.status_code == 422


def _fixtures(minutes=30):
    from routes.table_service import utcnow, stamp
    now = utcnow()
    seated = stamp(now - timedelta(minutes=minutes))
    return now, {"businessId": "default", "tableId": "T-SMART-UNIT",
                 "seatedAt": seated, "course": "entree",
                 "serviceEvents": {}}


def test_held_mains_and_kitchen_ready_alert_rules():
    from routes.table_service import _candidates, DEFAULT, stamp
    now, state = _fixtures()
    earlier = stamp(now - timedelta(minutes=25))
    order = {
        "id": "TEST-KO-SMART", "createdAt": earlier,
        "items": [{"course": 1}, {"course": 2}],
        "courses": {"1": {"status": "served", "servedAt": earlier},
                    "2": {"status": "held", "heldAt": earlier}},
    }
    found = _candidates(state, [order], DEFAULT, now, "52")
    assert any(a["rule"] == "mains_not_fired" and a["course"] == 2 for a in found)
    assert not any(a["rule"] == "kitchen_delayed" for a in found)

    order["courses"]["2"] = {"status": "fired", "firedAt": earlier}
    found = _candidates(state, [order], DEFAULT, now, "52")
    assert any(a["rule"] == "kitchen_delayed" for a in found)
    assert not any(a["rule"] == "mains_not_fired" for a in found)

    order["courses"]["2"] = {"status": "ready", "readyAt": earlier}
    found = _candidates(state, [order], DEFAULT, now, "52")
    assert any(a["rule"] == "food_waiting" for a in found)
    assert not any(a["rule"] == "kitchen_delayed" for a in found)


def test_drinks_without_food_and_unfulfilled_bill_alert():
    from routes.table_service import _candidates, DEFAULT, stamp
    now, state = _fixtures()
    state["serviceEvents"] = {
        "drinks_served": stamp(now - timedelta(minutes=17)),
        "bill_requested": stamp(now - timedelta(minutes=11)),
    }
    # Drinks-only tickets can legitimately have course 1; that must not be
    # misinterpreted as a food order.
    order = {"id": "DRINKS", "createdAt": stamp(now - timedelta(minutes=20)),
             "items": [{"course": 1, "category": "Beverages"}], "courses": {}}
    found = _candidates(state, [order], DEFAULT, now, "53")
    assert {a["rule"] for a in found} >= {"drinks_no_food", "bill_waiting"}
    state["serviceEvents"]["bill_completed"] = stamp(now - timedelta(minutes=2))
    found = _candidates(state, [order], DEFAULT, now, "53")
    assert not any(a["rule"] == "bill_waiting" for a in found)


def test_paused_service_excludes_paused_minutes_from_alert_clock():
    from routes.table_service import _candidates, DEFAULT, stamp
    now, state = _fixtures(minutes=13)
    state["serviceEvents"] = {"service_paused": stamp(now - timedelta(minutes=12)),
                              "service_resumed": stamp(now - timedelta(minutes=3))}
    state["servicePauseIntervals"] = [{
        "start": stamp(now - timedelta(minutes=12)),
        "end": stamp(now - timedelta(minutes=3)),
    }]
    assert not _candidates(state, [], DEFAULT, now, "54"), (
        "13 minutes seated with 9 paused = only 4 active minutes, below the 5-minute warning"
    )


def test_custom_kitchen_course_keys_drive_mains_alerts():
    from routes.table_service import _candidates, _kitchen_course_key, DEFAULT, stamp
    definitions = [
        {"key": 10, "label": "Drinks"},
        {"key": 20, "label": "Entrées"},
        {"key": 30, "label": "Mains"},
        {"key": 40, "label": "Desserts"},
    ]
    main_key = _kitchen_course_key(definitions, ("main",), 2)
    starter_key = _kitchen_course_key(definitions, ("starter", "entrée", "entree"), 1)
    assert main_key == "30"
    assert starter_key == "20"
    now, state = _fixtures()
    past = stamp(now - timedelta(minutes=22))
    ticket = {
        "id": "CUSTOM-KEYS", "createdAt": past,
        "items": [{"course": 20}, {"course": 30}],
        "courses": {"20": {"status": "served", "servedAt": past},
                    "30": {"status": "held", "heldAt": past}},
    }
    alerts = _candidates(state, [ticket], DEFAULT, now, "22",
                          main_course=main_key, starter_course=starter_key)
    assert any(a["rule"] == "mains_not_fired" and a["course"] == 30 for a in alerts)

def test_pending_service_warning_exposes_exact_upcoming_threshold():
    """The POS refreshes at the owner's first-warning deadline, not just on a poll."""
    from routes.table_service import _candidates, DEFAULT
    now, state = _fixtures(minutes=3)
    pending = _candidates(state, [], DEFAULT, now, "55", include_pending=True)
    arrival = next(a for a in pending if a["rule"] == "seated_no_order")
    assert arrival["pending"] is True
    due = datetime.fromisoformat(arrival["nextCheckAt"])
    assert 100 < (due - now).total_seconds() < 140
    assert not _candidates(state, [], DEFAULT, now, "55")


def test_escalation_deadline_is_reported_after_first_warning():
    from routes.table_service import _candidates, DEFAULT
    now, state = _fixtures(minutes=6)
    reminders = _candidates(state, [], DEFAULT, now, "56", include_pending=True)
    arrival = next(a for a in reminders if a["rule"] == "seated_no_order")
    assert arrival["pending"] is False
    assert arrival["priority"] == "normal"
    escalation = datetime.fromisoformat(arrival["nextCheckAt"])
    assert 100 < (escalation - now).total_seconds() < 140
