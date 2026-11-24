"""Smart Table Service: tenant-scoped, evidence-led reminders (never auto-fire food).

One alert per (tenant, seating session, rule). Mongo's unique _id deduplicates
simultaneous polling tablets. Acknowledged, snoozed and resolved alerts do not
reappear until escalation or a different seating session.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from hashlib import sha256
from typing import Any, Dict, Optional
from database import db
from middleware.actor_context import tenant_scope_filter
from services import floor_tables
from services.tenant_settings import get_scoped_singleton, set_scoped_singleton

DEFAULT_RULES = {
    "no_order": (5, 8, "No order taken", "Check whether guests are ready to order"),
    "after_drinks": (8, 12, "Food order follow-up", "Drinks were served; check on food order"),
    "mains_held": (10, 15, "Mains not fired", "Entrées were served; check table before firing mains"),
    "mains_delayed": (20, 30, "Mains delayed", "Mains fired but not ready; check with kitchen"),
    "ready_waiting": (3, 5, "Food at the pass", "Food is ready; arrange collection"),
    "post_mains": (12, 18, "Table follow-up", "Check guests after mains; offer dessert or coffee"),
    "bill_waiting": (5, 8, "Bill request pending", "A guest requested the bill"),
}
EVENT_TYPES = (
    "order_taken", "drinks_served", "food_order_taken", "entree_served",
    "follow_up_done", "bill_requested", "bill_delivered",
)
RULE_ORDER = list(DEFAULT_RULES)
_MGMT = {"owner", "manager"}
_FLOOR = {"owner", "manager", "cashier", "server"}
_MAX_STATES = 200
_MAX_ORDERS = 1200


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def parse_at(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def elapsed_minutes(since, now):
    stamp = parse_at(since)
    return max(0, (now - stamp).total_seconds() / 60) if stamp and stamp <= now else None


def default_settings():
    return {
        "enabled": False,  # Opt-in only; no unexpected prompts for existing venues
        "rules": {key: {"enabled": True, "warningMinutes": warn, "escalateMinutes": urgent}
                  for key, (warn, urgent, _, _) in DEFAULT_RULES.items()},
        "popupEnabled": True,
    }


async def settings_for(business_id):
    data = default_settings()
    if not business_id:
        return data
    saved = await get_scoped_singleton(
        db.table_service_settings, {"scope": "smart-table-service"}, business_id
    )
    if saved:
        data["enabled"] = saved.get("enabled") is True
        data["popupEnabled"] = saved.get("popupEnabled", True) is not False
        for key, overrides in (saved.get("rules") or {}).items():
            if key in data["rules"] and isinstance(overrides, dict):
                data["rules"][key].update({
                    field: overrides[field] for field in ("enabled", "warningMinutes", "escalateMinutes")
                    if field in overrides
                })
    return data


async def write_settings(business_id, settings, by):
    doc = {"scope": "smart-table-service", "enabled": settings["enabled"],
           "rules": settings["rules"], "popupEnabled": settings["popupEnabled"],
           "updatedAt": iso(now_utc()), "updatedBy": by}
    await set_scoped_singleton(
        db.table_service_settings, {"scope": "smart-table-service"}, doc, business_id
    )
    return doc


def active_for_user(alert, user):
    if alert.get("businessId") != user.get("businessId"):
        return False
    role = user.get("role")
    if role in _MGMT:
        return True
    if role == "kitchen":
        return alert.get("rule") in {"mains_delayed", "ready_waiting"}
    if role not in _FLOOR:
        return False
    server = alert.get("serverId")
    return not server or server in {user.get("id"), user.get("email")}


def _order_after_seating(order, seated_at):
    a, b = parse_at(order.get("createdAt")), parse_at(seated_at)
    return bool(a and b and a >= b)


def _food_present(orders, events):
    if events.get("food_order_taken"):
        return True
    # Never misclassify a menu item with no category as a drink and send a
    # false "food not ordered" alert. Unknown items count as potential food.
    drink_tags = {"drinks", "drink", "beverage", "beverages", "cocktail", "cocktails",
                  "beer", "wine", "spirits", "soft drinks", "coffee", "tea"}
    for order in orders:
        for item in order.get("items") or []:
            cat = str(item.get("category") or "").strip().lower()
            if not cat or cat not in drink_tags:
                return True
    return False


def _rule_sources(state, orders, main_keys, starter_keys):
    events = state.get("serviceEvents") or {}
    stage = state.get("course")
    candidates = {}
    if not orders and not events.get("order_taken"):
        candidates["no_order"] = state.get("seatedAt")

    if (stage == "drinks" or events.get("drinks_served")) and not _food_present(orders, events):
        candidates["after_drinks"] = events.get("drinks_served") or state.get("courseStartedAt")

    main_served = None
    has_main = False
    has_ready_or_order = False
    for order in orders:
        courses = order.get("courses") or {}
        previous_served = events.get("entree_served")
        for key in starter_keys:
            previous_served = max_time(previous_served, (courses.get(key) or {}).get("servedAt"))
        for key in main_keys:
            main = courses.get(key) or {}
            status = main.get("status")
            if not status:
                continue
            has_main = True
            if status in ("held", "queued") and previous_served:
                candidates["mains_held"] = min_time(candidates.get("mains_held"), previous_served)
            if status == "fired" and main.get("firedAt"):
                candidates["mains_delayed"] = min_time(candidates.get("mains_delayed"), main["firedAt"])
            if status == "served":
                main_served = max_time(main_served, main.get("servedAt"))
        for course in courses.values():
            if (course or {}).get("status") == "ready" and (course or {}).get("readyAt"):
                candidates["ready_waiting"] = min_time(candidates.get("ready_waiting"), course["readyAt"])
                has_ready_or_order = True
    if main_served and not events.get("follow_up_done") and stage not in {"dessert", "coffee", "check"}:
        candidates["post_mains"] = main_served
    if events.get("bill_requested") and not events.get("bill_delivered"):
        candidates["bill_waiting"] = events["bill_requested"]
    return candidates


def min_time(a, b):
    if not a:
        return b
    if not b:
        return a
    da, db = parse_at(a), parse_at(b)
    return b if db and (not da or db < da) else a


def max_time(a, b):
    if not a:
        return b
    if not b:
        return a
    da, db = parse_at(a), parse_at(b)
    return b if db and (not da or db > da) else a


def alert_key(business_id, state, rule):
    # Mongo's globally-unique primary key prevents duplicate writes from
    # two devices polling the same table at the same time.
    session = state.get("id") or f"{state.get('tableId')}:{state.get('seatedAt')}"
    seed = f"{business_id}:{session}:{rule}".encode("utf-8")
    return "tsa_" + sha256(seed).hexdigest()[:36]


async def evaluate(business_id, *, clock=None):
    """Generate current service reminders for this tenant, idempotently.

    Called from authenticated polling (works in Vercel's serverless runtime).
    No background process or cross-tenant scan is required. Max work per
    evaluation is bounded to protect shared venues.
    """
    if not business_id:
        return 0
    config = await settings_for(business_id)
    if not config["enabled"]:
        return 0
    now = clock or now_utc()
    scope = tenant_scope_filter(business_id)
    states = await db.table_states.find(scope, {"_id": 0}).to_list(_MAX_STATES)
    if not states:
        await db.table_service_alerts.update_many(
            {**scope, "status": {"$in": ["open", "snoozed", "acknowledged"]}},
            {"$set": {"status": "resolved", "resolvedReason": "table_closed", "resolvedAt": iso(now)}})
        return 0
    seated_times = [parse_at(s.get("seatedAt")) for s in states]
    seated_times = [t for t in seated_times if t]
    if not seated_times:
        return 0
    oldest = max(min(seated_times), now - timedelta(days=2))
    orders = await db.kitchen_orders.find(
        {**scope, "createdAt": {"$gte": iso(oldest)}, "status": {"$ne": "cancelled"}},
        {"_id": 0},
    ).sort("createdAt", -1).to_list(_MAX_ORDERS)

    # Never join kitchen tickets by a table number that is duplicated on
    # two floor plans. There is no unambiguous table -> ticket relationship.
    tables = await floor_tables.list_tables(business_id=business_id)
    number_to_id = {}
    for t in tables:
        number = floor_tables.normalize_table_number(t.get("number"))
        if number:
            if number in number_to_id:
                number_to_id[number] = None
            else:
                number_to_id[number] = t.get("id")
    orders_by_table = {}
    for order in orders:
        num = floor_tables.normalize_table_number(order.get("tableNumber"))
        tid = number_to_id.get(num)
        if tid:
            orders_by_table.setdefault(tid, []).append(order)

    from services import coursing
    course_config = await coursing.get_config(business_id=business_id)
    mapping = course_config.get("tablePacingMap") or {"1": "entree", "2": "main"}
    main_keys = {str(k) for k, v in mapping.items() if v == "main"} or {"2"}
    starter_keys = {str(k) for k, v in mapping.items() if v == "entree"} or {"1"}

    matched = set()
    created = 0
    for state in states:
        table_id = state.get("tableId")
        if not table_id:
            continue
        ticket_orders = [o for o in orders_by_table.get(table_id, [])
                         if _order_after_seating(o, state.get("seatedAt"))]
        sources = _rule_sources(state, ticket_orders, main_keys, starter_keys)
        for rule, since in sources.items():
            cfg = config["rules"].get(rule) or {}
            if not cfg.get("enabled", False):
                continue
            elapsed = elapsed_minutes(since, now)
            if elapsed is None or elapsed < cfg["warningMinutes"]:
                continue
            key = alert_key(business_id, state, rule)
            matched.add(key)
            urgent = elapsed >= cfg["escalateMinutes"]
            warning, escalation, title, message = DEFAULT_RULES[rule]
            doc = {
                "_id": key, "id": key, "businessId": business_id,
                "tableId": table_id, "tableNumber": next(
                    (t.get("number") for t in tables if t.get("id") == table_id), str(table_id)),
                "sessionId": state.get("id") or state.get("seatedAt"),
                "serverId": state.get("serverId"),
                "rule": rule, "title": title, "message": message,
                "eventAt": iso(parse_at(since)),
                "level": "urgent" if urgent else "warning",
                "status": "open", "createdAt": iso(now),
                "acknowledgedBy": None, "snoozedUntil": None,
            }
            # Idempotent insert; a previously resolved/acknowledged alert
            # is never recreated during the same seating session.
            result = await db.table_service_alerts.update_one(
                {"_id": key}, {"$setOnInsert": doc}, upsert=True)
            created += int(result.upserted_id is not None)
            if urgent:
                # Acknowledgement/snooze suppresses the first warning, but an
                # unaddressed issue can still escalate to the floor manager.
                await db.table_service_alerts.update_one(
                    {"_id": key, "businessId": business_id,
                     "level": "warning", "status": {"$ne": "resolved"}},
                    {"$set": {"level": "urgent", "status": "open",
                              "snoozedUntil": None, "escalatedAt": iso(now)}})
    # Advancing the table or completing a ticket clears stale warnings.
    if matched:
        await db.table_service_alerts.update_many(
            {**scope, "_id": {"$nin": list(matched)},
             "status": {"$in": ["open", "acknowledged", "snoozed"]}},
            {"$set": {"status": "resolved", "resolvedAt": iso(now),
                      "resolvedReason": "condition_cleared"}})
    else:
        await db.table_service_alerts.update_many(
            {**scope, "status": {"$in": ["open", "acknowledged", "snoozed"]}},
            {"$set": {"status": "resolved", "resolvedAt": iso(now),
                      "resolvedReason": "condition_cleared"}})
    await db.table_service_alerts.update_many(
        {**scope, "status": "snoozed", "snoozedUntil": {"$lte": iso(now)}},
        {"$set": {"status": "open", "snoozedUntil": None}})
    return created


async def alerts_for(user, *, include_resolved=False):
    biz = user.get("businessId")
    if not biz:
        return []
    await evaluate(biz)
    query = tenant_scope_filter(biz)
    if not include_resolved:
        query["status"] = {"$in": ["open", "acknowledged", "snoozed"]}
    alerts = await db.table_service_alerts.find(query, {"_id": 0}).sort(
        "createdAt", -1).to_list(300)
    visible = [a for a in alerts if active_for_user(a, user)]
    return sorted(visible, key=lambda x: (
        0 if x.get("level") == "urgent" else 1,
        x.get("eventAt") or ""))


async def update_alert(user, alert_id, action, *, minutes=None):
    biz = user.get("businessId")
    scope = tenant_scope_filter(biz)
    alert = await db.table_service_alerts.find_one({"id": alert_id, **scope}, {"_id": 0})
    if not alert or not active_for_user(alert, user):
        return None
    if alert.get("status") == "resolved":
        return None
    now = now_utc()
    if action == "acknowledge":
        update = {"status": "acknowledged", "acknowledgedBy": user.get("email"),
                  "acknowledgedAt": iso(now), "snoozedUntil": None}
    elif action == "snooze":
        if minutes not in {1, 3, 5, 10, 15}:
            raise ValueError("Unsupported snooze duration")
        update = {"status": "snoozed", "snoozedUntil": iso(now + timedelta(minutes=minutes)),
                  "snoozedBy": user.get("email")}
    elif action == "resolve":
        update = {"status": "resolved", "resolvedAt": iso(now),
                  "resolvedBy": user.get("email"), "resolvedReason": "staff_action"}
    else:
        raise ValueError("Unknown action")
    changed = await db.table_service_alerts.update_one(
        {"id": alert_id, **scope, "status": {"$ne": "resolved"}}, {"$set": update})
    return bool(changed.matched_count)
