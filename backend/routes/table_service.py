"""Tenant-scoped, opt-in service-attention alerts for dining tables.

GET /alerts evaluates current service events and kitchen ticket states. Durable,
deterministic alert IDs make polls from multiple devices idempotent; manual
acknowledgements and snoozes survive refreshes. This service NEVER fires food.
"""
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from typing import Optional, Literal
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from database import db
from deps import get_user
from services import floor_tables

router = APIRouter(prefix="/table-service", tags=["table-service"])
log = logging.getLogger(__name__)
MANAGERS = {"owner", "manager"}
ALLOWED_EVENTS = {
    "drinks_served", "bill_requested", "bill_completed",
    "service_paused", "service_resumed", "food_order_taken",
}
RULES = {
    "seated_no_order": ("Order not taken", 5, 8, "floor"),
    "drinks_no_food": ("Check food order", 8, 12, "floor"),
    "mains_not_fired": ("Mains not fired", 10, 15, "floor"),
    "kitchen_delayed": ("Kitchen order delayed", 20, 30, "kitchen"),
    "food_waiting": ("Food ready for collection", 3, 5, "floor"),
    "post_mains_check": ("Check on table", 12, 18, "floor"),
    "bill_waiting": ("Bill request waiting", 5, 8, "floor"),
}
DEFAULT = {"enabled": False, "rules": {
    key: {"enabled": True, "minutes": minutes, "escalateMinutes": escalation}
    for key, (_, minutes, escalation, _) in RULES.items()
}}


def utcnow():
    return datetime.now(timezone.utc)


def stamp(dt=None):
    return (dt or utcnow()).isoformat()


def parse_time(value):
    if not value:
        return None
    if isinstance(value, datetime):
        d = value
    else:
        try:
            d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


def minute_age(anchor, now):
    parsed = parse_time(anchor)
    return (now - parsed).total_seconds() / 60 if parsed else -1


class RuleConfig(BaseModel):
    enabled: bool = True
    minutes: int = Field(ge=1, le=240)
    escalateMinutes: int = Field(ge=1, le=480)


class ServiceConfig(BaseModel):
    enabled: bool = False
    rules: dict[str, RuleConfig]


class EventIn(BaseModel):
    tableId: str = Field(min_length=1, max_length=128)
    event: Literal["drinks_served", "bill_requested", "bill_completed",
                   "service_paused", "service_resumed", "food_order_taken"]


class ActionIn(BaseModel):
    action: Literal["acknowledge", "snooze", "resolve"]
    minutes: int = Field(default=3, ge=1, le=30)


def _business(user):
    biz = user.get("businessId")
    if not biz:
        raise HTTPException(403, "Business context required")
    return biz


def _allowed(user, doc):
    if user.get("role") in MANAGERS:
        return True
    server = doc.get("serverId")
    if server and str(server) not in {str(user.get("id")), str(user.get("email"))}:
        return False
    return True


async def _config(biz):
    doc = await db.table_service_settings.find_one({"businessId": biz}, {"_id": 0})
    if not doc:
        return DEFAULT
    return {"enabled": bool(doc.get("enabled", False)),
            "rules": {**DEFAULT["rules"], **doc.get("rules", {})}}


@router.get("/settings")
async def get_settings(user: dict = Depends(get_user)):
    return await _config(_business(user))


@router.put("/settings")
async def save_settings(body: ServiceConfig, user: dict = Depends(get_user)):
    if user.get("role") not in MANAGERS:
        raise HTTPException(403, "Owner or manager only")
    if set(body.rules) != set(RULES):
        raise HTTPException(422, "Exactly the seven service rules are required")
    for rule in body.rules.values():
        if rule.escalateMinutes <= rule.minutes:
            raise HTTPException(422, "Escalation must be later than first alert")
    biz = _business(user)
    payload = body.dict()
    payload.update({"businessId": biz, "updatedAt": stamp(), "updatedBy": user.get("email")})
    await db.table_service_settings.update_one({"businessId": biz},
                                               {"$set": payload}, upsert=True)
    return {"enabled": payload["enabled"], "rules": payload["rules"]}


@router.post("/events")
async def record_event(body: EventIn, user: dict = Depends(get_user)):
    biz = _business(user)
    found = await floor_tables.get_table_by_id(body.tableId, business_id=biz)
    if not found:
        raise HTTPException(404, "Table not found in this business")
    state = await db.table_states.find_one({"businessId": biz, "tableId": body.tableId})
    if not state:
        raise HTTPException(409, "Seat the table before recording service events")
    await db.table_states.update_one({"businessId": biz, "tableId": body.tableId},
                                     {"$set": {"serviceEvents." + body.event: stamp(),
                                               "updatedAt": stamp()}})
    return {"recorded": body.event, "tableId": body.tableId}


def _candidate(rule, table, anchor, minutes, server, message, now, config, extra=None):
    cfg = config["rules"].get(rule, {})
    if not cfg.get("enabled", True) or minute_age(anchor, now) < cfg.get("minutes", 9999):
        return None
    return {
        "id": sha256(("%s|%s|%s|%s" % (table["businessId"], table["tableId"], rule, anchor)).encode()).hexdigest()[:36],
        "businessId": table["businessId"], "tableId": table["tableId"],
        "tableNumber": table["tableNumber"], "serverId": server,
        "rule": rule, "title": RULES[rule][0], "category": RULES[rule][3],
        "message": message, "startedAt": anchor,
        "elapsedMinutes": int(minute_age(anchor, now)),
        "priority": "urgent" if minute_age(anchor, now) >= cfg["escalateMinutes"] else "normal",
        **(extra or {}),
    }


def _candidates(state, orders, config, now, number):
    """Only use events we actually have. Never infer that food was served from
    a floor-plan colour or that a guest wants their mains automatically fired.
    """
    biz = state["businessId"]
    table = {"businessId": biz, "tableId": state["tableId"], "tableNumber": number}
    server = state.get("serverId") or state.get("createdBy")
    events = state.get("serviceEvents") or {}
    seated = state.get("seatedAt")
    if not seated:
        return []
    if events.get("service_paused") and (
        not events.get("service_resumed") or
        parse_time(events["service_paused"]) > parse_time(events["service_resumed"])
    ):
        return []

    def emit(rule, anchor, msg, extra=None):
        candidate = _candidate(rule, table, anchor, None, server, msg, now, config, extra)
        if candidate:
            found.append(candidate)

    found = []
    # Ticket creation, not just floor colour, proves an order was taken.
    recent = [o for o in orders if minute_age(o.get("createdAt"), now) >= 0 and
              parse_time(o.get("createdAt")) and parse_time(o["createdAt"]) >=
              parse_time(seated) - timedelta(seconds=90)]
    if not recent and not events.get("food_order_taken"):
        emit("seated_no_order", seated, "Guests seated; please greet and take their order.")
    # This only activates once staff explicitly record drinks as served.
    drinks_at = events.get("drinks_served")
    if drinks_at and not events.get("food_order_taken"):
        food_order = any(any(str(i.get("course", "")).isdigit() and int(i["course"]) >= 1
                             for i in (o.get("items") or [])) for o in recent)
        if not food_order:
            emit("drinks_no_food", drinks_at, "Drinks served; ask whether guests are ready for food.")

    for order in recent:
        courses = order.get("courses") or {}
        main = courses.get("2") or {}
        entree = courses.get("1") or {}
        # Held mains only become an alert after the preceding entrée is actually served.
        if main.get("status") in ("held", "queued") and entree.get("status") == "served":
            emit("mains_not_fired", entree.get("servedAt"),
                 "Entrée served but mains remain on hold. Check with the table; do not auto-fire.",
                 {"orderId": order.get("id"), "course": 2})
        for key, course in courses.items():
            if course.get("status") == "fired":
                emit("kitchen_delayed", course.get("firedAt"),
                     "Fired course has not been marked ready by the kitchen.",
                     {"orderId": order.get("id"), "course": key})
            if course.get("status") == "ready":
                emit("food_waiting", course.get("readyAt"),
                     "Food is ready at the pass; collect and serve.",
                     {"orderId": order.get("id"), "course": key})
        if main.get("status") == "served" and state.get("course") == "main":
            emit("post_mains_check", main.get("servedAt"),
                 "Mains served; check on guests and offer dessert or coffee.")
    bill = events.get("bill_requested")
    completed = events.get("bill_completed")
    if bill and (not completed or parse_time(completed) < parse_time(bill)):
        emit("bill_waiting", bill, "Bill requested; arrange payment for this table.")
    return found


@router.get("/alerts")
async def list_alerts(user: dict = Depends(get_user)):
    biz = _business(user)
    config = await _config(biz)
    if not config["enabled"]:
        return {"enabled": False, "alerts": [], "openCount": 0}
    now = utcnow()
    states = await db.table_states.find({"businessId": biz}, {"_id": 0}).to_list(500)
    tables = await floor_tables.list_tables(business_id=biz)
    by_id = {t["id"]: str(t.get("number") or t.get("name") or t["id"]) for t in tables}
    numbers = {floor_tables.normalize_table_number(v): k for k, v in by_id.items()}
    orders = await db.kitchen_orders.find(
        {"businessId": biz, "orderType": {"$in": ["dine_in", "dine-in", "dineIn"]}},
        {"_id": 0}).sort("createdAt", -1).to_list(600)
    grouped = {}
    for order in orders:
        key = numbers.get(floor_tables.normalize_table_number(order.get("tableNumber")))
        if key:
            grouped.setdefault(key, []).append(order)

    keep = set()
    for state in states:
        tid = state.get("tableId")
        if tid not in by_id:
            continue
        for alert in _candidates(state, grouped.get(tid, []), config, now, by_id[tid]):
            keep.add(alert["id"])
            # Unique index makes concurrent device polls safe.
            await db.table_service_alerts.create_index("id", unique=True)
            await db.table_service_alerts.update_one(
                {"id": alert["id"], "businessId": biz},
                {"$setOnInsert": {**alert, "createdAt": stamp(now), "status": "open"},
                 "$set": {"priority": alert["priority"], "elapsedMinutes": alert["elapsedMinutes"],
                          "message": alert["message"]}},
                upsert=True)
    active = await db.table_service_alerts.find(
        {"businessId": biz, "status": {"$in": ["open", "acknowledged", "snoozed"]}},
        {"_id": 0}).to_list(700)
    obsolete = [a["id"] for a in active if a["id"] not in keep]
    if obsolete:
        await db.table_service_alerts.update_many(
            {"businessId": biz, "id": {"$in": obsolete}},
            {"$set": {"status": "resolved", "resolvedAt": stamp(now), "resolvedBy": "auto"}})
    visible = []
    for alert in active:
        if alert["id"] not in keep or not _allowed(user, alert):
            continue
        if alert.get("status") == "snoozed" and minute_age(alert.get("snoozedUntil"), now) < 0:
            continue
        if alert.get("status") == "snoozed":
            await db.table_service_alerts.update_one(
                {"id": alert["id"], "businessId": biz}, {"$set": {"status": "open"}})
            alert["status"] = "open"
        visible.append(alert)
    visible.sort(key=lambda a: (a["priority"] != "urgent", -a["elapsedMinutes"]))
    return {"enabled": True, "alerts": visible, "openCount": sum(a["status"] == "open" for a in visible)}


@router.post("/alerts/{alert_id}/action")
async def action(alert_id: str, body: ActionIn, user: dict = Depends(get_user)):
    biz = _business(user)
    alert = await db.table_service_alerts.find_one({"id": alert_id, "businessId": biz}, {"_id": 0})
    if not alert or not _allowed(user, alert):
        raise HTTPException(404, "Alert not found")
    if alert.get("status") == "resolved":
        return {"id": alert_id, "status": "resolved"}
    values = {"status": {"acknowledge": "acknowledged", "snooze": "snoozed",
                          "resolve": "resolved"}[body.action],
              "updatedAt": stamp(), "updatedBy": user.get("email")}
    if body.action == "snooze":
        values["snoozedUntil"] = stamp(utcnow() + timedelta(minutes=body.minutes))
    if body.action == "resolve":
        values["resolvedAt"] = stamp()
    await db.table_service_alerts.update_one(
        {"id": alert_id, "businessId": biz}, {"$set": values})
    return {"id": alert_id, "status": values["status"]}
