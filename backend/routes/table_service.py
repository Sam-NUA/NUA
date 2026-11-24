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
    role = user.get("role")
    if role in MANAGERS:
        return True
    if role == "kitchen":
        return doc.get("category") == "kitchen"
    if doc.get("category") == "kitchen":
        return False
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
    changes = {"serviceEvents." + body.event: stamp(), "updatedAt": stamp()}
    update = {"$set": changes}
    if body.event == "service_resumed":
        events = state.get("serviceEvents") or {}
        paused = parse_time(events.get("service_paused"))
        last_resume = parse_time(events.get("service_resumed"))
        if paused and (not last_resume or paused > last_resume):
            update["$push"] = {"servicePauseIntervals": {"start": stamp(paused), "end": stamp()}}
    await db.table_states.update_one({"businessId": biz, "tableId": body.tableId}, update)
    return {"recorded": body.event, "tableId": body.tableId}


def _candidate(rule, table, anchor, minutes, server, message, now, config, extra=None,
               include_pending=False):
    cfg = config["rules"].get(rule, {})
    age = minute_age(anchor, now)
    if not cfg.get("enabled", True) or age < 0:
        return None
    pending = age < cfg.get("minutes", 9999)
    if pending and not include_pending:
        return None
    # Tell the terminal when the next rule boundary occurs. The terminal can
    # refresh at that exact time instead of only waiting for its safety poll.
    next_minutes = (cfg["minutes"] if pending else
                    cfg["escalateMinutes"] if age < cfg["escalateMinutes"] else None)
    next_check = (stamp(parse_time(anchor) + timedelta(minutes=next_minutes))
                  if next_minutes is not None else None)
    return {
        "id": sha256(("%s|%s|%s|%s" % (table["businessId"], table["tableId"], rule, anchor)).encode()).hexdigest()[:36],
        "businessId": table["businessId"], "tableId": table["tableId"],
        "tableNumber": table["tableNumber"], "serverId": server,
        "rule": rule, "title": RULES[rule][0], "category": RULES[rule][3],
        "message": message, "startedAt": anchor,
        "elapsedMinutes": int(age), "pending": pending, "nextCheckAt": next_check,
        "priority": "urgent" if age >= cfg["escalateMinutes"] else "normal",
        **(extra or {}),
    }


def _candidates(state, orders, config, now, number, *, main_course="2", starter_course="1",
                include_pending=False):
    """Only use events we actually have. Never infer that food was served from
    a floor-plan colour or that a guest wants their mains automatically fired.
    """
    biz = state["businessId"]
    table = {"businessId": biz, "tableId": state["tableId"], "tableNumber": number}
    server = state.get("serverId")
    events = state.get("serviceEvents") or {}
    seated = state.get("seatedAt")
    if not seated or not parse_time(seated):
        return []
    if events.get("service_paused") and (
        not events.get("service_resumed") or
        parse_time(events["service_paused"]) > parse_time(events["service_resumed"])
    ):
        return []

    def effective_anchor(anchor):
        parsed = parse_time(anchor)
        if not parsed:
            return anchor
        paused_seconds = 0
        for interval in state.get("servicePauseIntervals") or []:
            start = parse_time(interval.get("start"))
            end = parse_time(interval.get("end"))
            if start and end and end > start:
                paused_seconds += max(0, (end - max(start, parsed)).total_seconds())
        return stamp(parsed + timedelta(seconds=paused_seconds))

    def emit(rule, anchor, msg, extra=None):
        candidate = _candidate(rule, table, effective_anchor(anchor), None, server, msg, now,
                               config, extra, include_pending=include_pending)
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
        food_order = any(any(
            (str(i.get("course", "")).isdigit() and int(i["course"]) >= 2) or
            any(word in str(i.get("category") or i.get("courseLabel") or "").lower()
                for word in ("entree", "entrée", "starter", "main", "food", "pizza", "pasta"))
            for i in (o.get("items") or [])) for o in recent)
        if not food_order:
            emit("drinks_no_food", drinks_at, "Drinks served; ask whether guests are ready for food.")

    for order in recent:
        courses = order.get("courses") or {}
        main = courses.get(str(main_course)) or {}
        entree = courses.get(str(starter_course)) or {}
        # Held mains deserve a check even for tables that skip entrée.
        # The action remains manual: never auto-fire from a service alert.
        if main.get("status") in ("held", "queued"):
            anchor = entree.get("servedAt") if entree.get("status") == "served" else (
                events.get("drinks_served") or main.get("heldAt") or order.get("createdAt"))
            emit("mains_not_fired", anchor,
                 "Mains are still on hold. Check the table before firing.",
                 {"orderId": order.get("id"), "course": int(main_course)})
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


@router.get("/staff")
async def floor_staff(user: dict = Depends(get_user)):
    """Minimal role-filtered directory for assigning tables; never expose PINs."""
    if user.get("role") not in MANAGERS:
        raise HTTPException(403, "Manager or owner only")
    biz = _business(user)
    rows = await db.auth_users.find(
        {"businessId": biz, "role": {"$in": ["owner", "manager", "cashier", "server", "waiter"]}},
        {"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1},
    ).to_list(200)
    return [{"id": x.get("id"), "name": x.get("name") or x.get("email"),
             "email": x.get("email"), "role": x.get("role")} for x in rows if x.get("email")]


def _kitchen_course_key(definitions, names, default):
    for course in definitions or []:
        label = str(course.get("label") or "").casefold()
        if any(token in label for token in names):
            try:
                return str(int(course["key"]))
            except (ValueError, TypeError, KeyError):
                continue
    return str(default)


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

    from services import coursing as kitchen_coursing
    coursing_config = await kitchen_coursing.get_config(business_id=biz)
    kitchen_courses = coursing_config.get("courses") or []
    main_course = _kitchen_course_key(kitchen_courses, ("main",), 2)
    starter_course = _kitchen_course_key(kitchen_courses, ("starter", "entrée", "entree"), 1)

    keep = set()
    next_check_at = None
    for state in states:
        tid = state.get("tableId")
        if tid not in by_id:
            continue
        for alert in _candidates(state, grouped.get(tid, []), config, now, by_id[tid],
                                 main_course=main_course, starter_course=starter_course,
                                 include_pending=True):
            due = parse_time(alert.get("nextCheckAt"))
            if due and due > now and (next_check_at is None or due < next_check_at):
                next_check_at = due
            if alert.get("pending"):
                continue
            keep.add(alert["id"])
            # Escalate an acknowledged normal reminder only once, when it crosses
            # the higher owner-configured threshold.
            if alert["priority"] == "urgent":
                await db.table_service_alerts.update_one(
                    {"id": alert["id"], "businessId": biz, "status": "acknowledged",
                     "priority": "normal"},
                    {"$set": {"status": "open", "escalatedAt": stamp(now)}})
            stable = {k: v for k, v in alert.items() if k not in
                      ("priority", "elapsedMinutes", "message", "tableNumber", "serverId",
                        "pending", "nextCheckAt")}
            await db.table_service_alerts.update_one(
                {"id": alert["id"], "businessId": biz},
                {"$setOnInsert": {**stable, "createdAt": stamp(now), "status": "open"},
                 "$set": {"priority": alert["priority"], "elapsedMinutes": alert["elapsedMinutes"],
                          "message": alert["message"], "tableNumber": alert["tableNumber"],
                          "serverId": alert["serverId"]}},
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
    return {"enabled": True, "alerts": visible,
            "openCount": sum(a["status"] == "open" for a in visible),
            "nextCheckAt": stamp(next_check_at) if next_check_at else None}


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
