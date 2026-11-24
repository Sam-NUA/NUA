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
        assert req(client, "GET", "/api/table-service/alerts",
                   headers=owner_headers).json()["openCount"] == 0

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
