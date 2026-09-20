"""
NUA Cross-Module Rules Engine ("Automation Brain")
────────────────────────────────────────────────────

The rules engine is a single point of authority for automations that span
multiple modules. Any module can `emit_event(...)` and any subscribed rule
whose conditions match will fire its actions — atomically, idempotently
and with a full audit trail.

Design
──────
• Events are lightweight dicts: `{type, entity_id, payload, ts}`.
• Rules live in `db.rules`. Each rule declares:
    trigger_event  — one of the entries in EVENT_CATALOG
    conditions[]   — list of `{path, op, value}` combined with `all|any`
    actions[]      — list of `{type, params, delay_seconds}`
    active, priority (higher runs first)
• Actions are looked up in ACTION_LIBRARY. New actions register by adding
  a function to that dict — no route changes required.
• Every rule firing is logged in `db.rule_executions` with the event
  snapshot, condition results and action outcomes.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Callable, Awaitable
from datetime import datetime, timezone
from database import db
import uuid
import logging
import asyncio
import operator as _op
from middleware.actor_context import tenant_scope_filter

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════
# Event catalog — the ONE list of events across every module
# ═════════════════════════════════════════════════════════════════════════
EVENT_CATALOG = {
    # POS / commerce
    "pos.sale.completed":       {"module": "pos",       "label": "Sale completed",              "fields": ["id", "total", "customerId", "items"]},
    "pos.refund.issued":        {"module": "pos",       "label": "Refund issued",               "fields": ["id", "amount", "reason", "customerId"]},
    "voucher.redeemed":         {"module": "commerce",  "label": "Voucher redeemed",            "fields": ["voucherId", "amount", "customerId"]},
    "gift_card.sold":           {"module": "commerce",  "label": "Gift card sold",              "fields": ["id", "amount", "customerId"]},
    # Inventory
    "inventory.low_stock":      {"module": "inventory", "label": "Product below threshold",     "fields": ["productId", "productName", "stock", "threshold"]},
    "inventory.stockout":       {"module": "inventory", "label": "Product hit zero",            "fields": ["productId", "productName"]},
    "inventory.received":       {"module": "inventory", "label": "Stock received",              "fields": ["productId", "quantity", "supplierId"]},
    "inventory.predicted_stockout": {"module": "inventory", "label": "Predicted to run out soon", "fields": ["productId", "productName", "currentStock", "avgDailyUsage", "daysRemaining"]},
    # CRM
    "customer.created":         {"module": "crm",       "label": "Customer created",            "fields": ["id", "name", "email"]},
    "customer.spend_milestone": {"module": "crm",       "label": "Customer spend milestone",    "fields": ["customerId", "totalSpent", "milestone"]},
    "customer.birthday":        {"module": "crm",       "label": "Customer birthday",           "fields": ["customerId", "name"]},
    "customer.no_show":         {"module": "crm",       "label": "Customer no-show",            "fields": ["customerId", "count"]},
    "customer.review":          {"module": "crm",       "label": "Customer review received",    "fields": ["customerId", "rating", "text"]},
    # Bookings
    "booking.created":          {"module": "bookings",  "label": "Booking created",             "fields": ["id", "partySize", "time", "customerId"]},
    "booking.confirmed":        {"module": "bookings",  "label": "Booking confirmed",           "fields": ["id"]},
    "booking.cancelled":        {"module": "bookings",  "label": "Booking cancelled",           "fields": ["id", "reason"]},
    "booking.no_show":          {"module": "bookings",  "label": "Booking no-show",             "fields": ["id", "customerId"]},
    # Labour
    "labour.staff_late":        {"module": "labour",    "label": "Staff clock-in late",         "fields": ["staffId", "shiftId", "minutesLate"]},
    "labour.overtime":          {"module": "labour",    "label": "Overtime threshold hit",      "fields": ["staffId", "hours"]},
    "labour.no_show":           {"module": "labour",    "label": "Staff no-show",               "fields": ["staffId", "shiftId"]},
    # Kitchen
    "kitchen.wait_time_high":   {"module": "kitchen",   "label": "Wait time > threshold",       "fields": ["averageMinutes"]},
    "kitchen.dish_86":          {"module": "kitchen",   "label": "Dish 86'd",                   "fields": ["productId", "productName"]},
    "kitchen.temp_abnormal":    {"module": "kitchen",   "label": "Temperature abnormal",        "fields": ["deviceId", "temperature", "unit"]},
    # Finance
    "finance.ap_due_soon":      {"module": "finance",   "label": "AP bill due soon",            "fields": ["billId", "amount", "supplierName"]},
    "finance.cash_low":         {"module": "finance",   "label": "Cash balance low",            "fields": ["accountCode", "balance"]},
    # Ops / observability
    "ops.error_spike":          {"module": "ops",       "label": "Error rate spike",            "fields": ["source", "count", "threshold", "windowMinutes"]},
}


# ═════════════════════════════════════════════════════════════════════════
# Condition evaluation
# ═════════════════════════════════════════════════════════════════════════
_OPS: Dict[str, Callable[[Any, Any], bool]] = {
    "eq": _op.eq, "ne": _op.ne, "gt": _op.gt, "gte": _op.ge, "lt": _op.lt, "lte": _op.le,
    "in": lambda a, b: a in (b or []),
    "not_in": lambda a, b: a not in (b or []),
    "contains": lambda a, b: b in (a or "") if isinstance(a, str) else b in (a or []),
    "starts_with": lambda a, b: isinstance(a, str) and a.startswith(b or ""),
    "exists": lambda a, b: (a is not None) if b else (a is None),
    "changed": lambda a, b: True,  # placeholder — resolved by caller when previous state known
}


def _path_value(payload: Dict[str, Any], path: str) -> Any:
    """Read dot-path from a payload — payload['a']['b'] via 'a.b'."""
    cur: Any = payload
    for part in (path or "").split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def evaluate_conditions(conditions: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Conditions may be:
      • empty                → always match
      • {mode:"all"|"any", clauses:[{path, op, value}, ...]}
      • flat list of clauses  → treated as "all"
      • legacy dict           → treated as {'path' >= value} (backwards compat)
    """
    if not conditions:
        return {"passed": True, "details": []}

    mode = "all"
    clauses: List[Dict[str, Any]] = []
    if isinstance(conditions, dict) and "clauses" in conditions:
        mode = (conditions.get("mode") or "all").lower()
        clauses = conditions.get("clauses") or []
    elif isinstance(conditions, list):
        clauses = conditions
    elif isinstance(conditions, dict):
        # Legacy shape: {"threshold": 5, "category":"Wine"}  →  equality per key
        clauses = [{"path": k, "op": "eq", "value": v} for k, v in conditions.items()]

    details = []
    passed_any = False
    passed_all = True
    for c in clauses:
        actual = _path_value(payload, c.get("path", ""))
        op = c.get("op", "eq")
        expected = c.get("value")
        try:
            ok = bool(_OPS.get(op, _op.eq)(actual, expected))
        except Exception:
            ok = False
        details.append({"path": c.get("path"), "op": op, "expected": expected, "actual": actual, "passed": ok})
        passed_any = passed_any or ok
        passed_all = passed_all and ok

    return {"passed": passed_any if mode == "any" else passed_all, "mode": mode, "details": details}


# ═════════════════════════════════════════════════════════════════════════
# Action library — each action is `async def(rule, event, params) -> dict`
# ═════════════════════════════════════════════════════════════════════════
async def _action_dock_notify(rule, event, params):
    msg = params.get("message") or f"Rule '{rule['name']}' fired"
    doc = {
        "id": str(uuid.uuid4()),
        "type": "automation",
        "message": msg,
        "severity": params.get("severity", "info"),
        "ruleId": rule["id"],
        "eventType": event["type"],
        "createdAt": _now_iso(),
        "read": False,
    }
    await db.notifications.insert_one(doc)
    return {"notificationId": doc["id"], "message": msg}


async def _action_send_email(rule, event, params):
    to = params.get("to") or _path_value(event["payload"], "email") or "guest@nua.example"
    subj = params.get("subject") or f"Automation: {rule['name']}"
    body = params.get("body") or f"Rule '{rule['name']}' fired for event {event['type']}."
    # Delegate to notifications util if available, else log
    try:
        from utils.notifications import send_email  # type: ignore
        await send_email(to, subj, body)
        return {"sent": True, "to": to}
    except Exception:
        logger.info(f"[email:MOCKED] to={to} subj={subj}")
        return {"sent": False, "mocked": True, "to": to, "subject": subj}


async def _action_send_sms(rule, event, params):
    to = params.get("to") or _path_value(event["payload"], "phone")
    text = params.get("text") or f"NUA: {rule['name']}"
    try:
        from utils.notifications import send_sms  # type: ignore
        await send_sms(to, text)
        return {"sent": True, "to": to}
    except Exception:
        logger.info(f"[sms:MOCKED] to={to} text={text}")
        return {"sent": False, "mocked": True, "to": to}


async def _action_create_po(rule, event, params):
    """Create a purchase order for the low-stock product from the event."""
    pid = params.get("productId") or _path_value(event["payload"], "productId")
    qty = params.get("quantity") or 10
    if not pid:
        return {"error": "no productId in event or params"}
    supplier_id = params.get("supplierId")
    product = await db.products.find_one({"id": pid}, {"_id": 0})
    po = {
        "id": str(uuid.uuid4()),
        "productId": pid,
        "productName": (product or {}).get("name"),
        "quantity": qty,
        "supplierId": supplier_id,
        "status": "draft",
        "createdBy": "rules_engine",
        "ruleId": rule["id"],
        "createdAt": _now_iso(),
    }
    await db.purchase_orders.insert_one(dict(po))
    return {"purchaseOrderId": po["id"], "productId": pid, "quantity": qty}


async def _action_upgrade_vip(rule, event, params):
    cid = params.get("customerId") or _path_value(event["payload"], "customerId")
    if not cid:
        return {"error": "no customerId"}
    tier = params.get("tier", "Gold")
    r = await db.customers.update_one({**tenant_scope_filter(), "id": cid}, {"$set": {"membershipTier": tier, "vipUpgradedAt": _now_iso()}})
    return {"customerId": cid, "newTier": tier, "matched": r.matched_count}


async def _action_apply_credit(rule, event, params):
    cid = params.get("customerId") or _path_value(event["payload"], "customerId")
    amount = float(params.get("amount") or 0)
    if not cid or amount <= 0:
        return {"error": "customerId and amount required"}
    r = await db.customers.update_one({**tenant_scope_filter(), "id": cid}, {"$inc": {"storeCredit": amount}})
    # Also log to wallet ledger if present
    try:
        await db.wallet_ledger.insert_one({
            "id": str(uuid.uuid4()), "customerId": cid, "type": "store_credit_grant",
            "amount": amount, "createdAt": _now_iso(), "sourceType": "rules_engine",
            "sourceRef": rule["id"], "description": f"Rule '{rule['name']}' credit"
        })
    except Exception:
        pass
    return {"customerId": cid, "credit": amount, "matched": r.matched_count}


async def _action_issue_voucher(rule, event, params):
    cid = params.get("customerId") or _path_value(event["payload"], "customerId")
    value = float(params.get("value") or 10)
    try:
        from routes.commerce_v29 import _issue_voucher
        v = await _issue_voucher({
            "sourceType": "rule_engine",
            "sourceRef": rule["id"],
            "label": params.get("label", f"Auto voucher — {rule['name']}"),
            "valueType": params.get("valueType", "amount"),
            "value": value,
            "customerId": cid,
        }, user=None)
        return {"voucherId": v["id"], "code": v["code"]}
    except Exception as e:
        return {"error": str(e), "mocked": True}


async def _action_dispatch_task(rule, event, params):
    doc = {
        "id": str(uuid.uuid4()),
        "title": params.get("title") or f"Task from rule '{rule['name']}'",
        "assignee": params.get("assignee") or "manager",
        "priority": params.get("priority", "normal"),
        "dueAt": params.get("dueAt"),
        "eventType": event["type"],
        "ruleId": rule["id"],
        "status": "open",
        "createdAt": _now_iso(),
    }
    await db.tasks.insert_one(dict(doc))
    return {"taskId": doc["id"]}


async def _action_post_journal(rule, event, params):
    """Post a journal entry as a rule outcome."""
    try:
        from services.accounting_service import post_entry
        je = await post_entry(
            params.get("lines") or [],
            memo=params.get("memo") or f"Rule '{rule['name']}'",
            source_type="rules_engine",
            source_ref=rule["id"],
        )
        return {"journalId": je["id"]}
    except Exception as e:
        return {"error": str(e)}


async def _action_mark_dish_86(rule, event, params):
    pid = params.get("productId") or _path_value(event["payload"], "productId")
    if not pid:
        return {"error": "no productId"}
    # Was writing is86ed/eightySixReason — fields the product schema (and
    # every reader of it: POS, kitchen display, online ordering, the
    # low-stock/oos endpoints) has never had. This silently 86'd nothing
    # anywhere visible; the real field is eightySixed (models/product.py).
    r = await db.products.update_one(
        {"id": pid},
        {"$set": {"eightySixed": True, "eightySixedAt": datetime.now(timezone.utc).isoformat(),
                   "eightySixedBy": "rules_engine", "eightySixedReason": params.get("reason", "auto")}},
    )
    return {"productId": pid, "matched": r.matched_count}


async def _action_webhook(rule, event, params):
    url = params.get("url")
    if not url:
        return {"error": "no url"}
    try:
        import httpx
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.post(url, json={"rule": rule["name"], "event": event["type"], "payload": event["payload"]})
        return {"status": r.status_code}
    except Exception as e:
        return {"error": str(e)}


async def _action_apply_discount(rule, event, params):
    """Attach a promotion object (idempotent by name)."""
    name = params.get("name") or f"AUTO {rule['name']}"
    existing = await db.promotions.find_one({"name": name}, {"_id": 0})
    if existing:
        return {"promotionId": existing["id"], "reused": True}
    promo = {
        "id": str(uuid.uuid4()), "name": name,
        "type": params.get("type", "percent"),
        "discount": float(params.get("discount") or 10),
        "active": True, "createdBy": "rules_engine", "ruleId": rule["id"],
        "createdAt": _now_iso(),
    }
    await db.promotions.insert_one(dict(promo))
    return {"promotionId": promo["id"]}


ACTION_LIBRARY: Dict[str, Dict[str, Any]] = {
    "dock_notify":       {"label": "Send dock notification", "fn": _action_dock_notify,   "params": ["message", "severity"]},
    "send_email":        {"label": "Send email",              "fn": _action_send_email,    "params": ["to", "subject", "body"]},
    "send_sms":          {"label": "Send SMS",                "fn": _action_send_sms,      "params": ["to", "text"]},
    "create_purchase_order": {"label": "Create Purchase Order", "fn": _action_create_po,   "params": ["productId", "quantity", "supplierId"]},
    "upgrade_vip_tier":  {"label": "Upgrade customer tier",   "fn": _action_upgrade_vip,   "params": ["customerId", "tier"]},
    "apply_customer_credit": {"label": "Apply store credit",  "fn": _action_apply_credit,  "params": ["customerId", "amount"]},
    "issue_voucher":     {"label": "Issue voucher",           "fn": _action_issue_voucher, "params": ["customerId", "value", "label"]},
    "dispatch_task":     {"label": "Create task",             "fn": _action_dispatch_task, "params": ["title", "assignee", "priority", "dueAt"]},
    "post_journal":      {"label": "Post accounting journal", "fn": _action_post_journal,  "params": ["memo", "lines"]},
    "mark_dish_86":      {"label": "Mark dish as 86'd",       "fn": _action_mark_dish_86,  "params": ["productId", "reason"]},
    "apply_discount":    {"label": "Auto-create promotion",   "fn": _action_apply_discount,"params": ["name", "type", "discount"]},
    "webhook":           {"label": "Outbound webhook",        "fn": _action_webhook,       "params": ["url"]},
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═════════════════════════════════════════════════════════════════════════
# Public API
# ═════════════════════════════════════════════════════════════════════════
async def emit_event(event_type: str, payload: Optional[Dict[str, Any]] = None,
                     entity_id: Optional[str] = None, business_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Fire an event through the rules engine. Every matching, active rule
    is evaluated + executed. Returns a summary { rulesEvaluated, ruleFirings }.

    business_id scopes which business's rules this event can trigger —
    without it, a POS sale (or any other event) in Business A evaluated
    and executed every business's active rules for that event type, not
    just Business A's own, so one business's automation ("VIP-upgrade on
    big spend", "auto-PO on low stock") fired against another business's
    customers/inventory. Defaults from the request's actor context, same
    pattern as notification_service.send() — safe_emit's fire-and-forget
    asyncio task still sees it, since asyncio.create_task captures the
    calling context at creation time. Background scanners with no request
    context (ops_signals.py, predictive_signals.py) fall through to None,
    which matches every business's rules same as before this fix — a
    known, separate, documented gap, not one this closes.
    """
    if business_id is None:
        from middleware.actor_context import get_actor_context
        business_id = get_actor_context().get("businessId")
    event = {
        "id": str(uuid.uuid4()),
        "type": event_type,
        "entityId": entity_id,
        "payload": payload or {},
        "ts": _now_iso(),
        "businessId": business_id,
    }
    try:
        await db.rule_events.insert_one(dict(event))
    except Exception:
        pass

    rules_cursor = db.rules.find(
        {"active": True, "triggerEvent": event_type, **tenant_scope_filter(business_id)}, {"_id": 0})
    rules = await rules_cursor.to_list(200)
    rules.sort(key=lambda r: -(r.get("priority", 0)))

    firings = []
    for rule in rules:
        cond = evaluate_conditions(rule.get("conditions"), event["payload"])
        if not cond["passed"]:
            firings.append({"ruleId": rule["id"], "name": rule["name"], "matched": False, "condition": cond})
            continue
        outcomes = []
        for a in rule.get("actions") or []:
            atype = a.get("type")
            fn_meta = ACTION_LIBRARY.get(atype)
            if not fn_meta:
                outcomes.append({"type": atype, "error": "unknown action"})
                continue
            try:
                params = a.get("params") or {}
                delay = int(a.get("delaySeconds") or 0)
                if delay > 0:
                    asyncio.create_task(_delayed_action(delay, fn_meta["fn"], rule, event, params))
                    outcomes.append({"type": atype, "scheduled_in": delay})
                    continue
                # Approval gate — enqueue or execute based on policy
                from services.approval_service import enqueue_or_execute
                gate = await enqueue_or_execute(
                    action_type=atype, params=params,
                    execute_fn=lambda p, _r=rule, _e=event, _fn=fn_meta["fn"]: _fn(_r, _e, p),
                    source="rules_engine", source_ref=rule["id"],
                    context={"eventType": event["type"], "ruleName": rule["name"]},
                    requested_by=f"rule:{rule['name']}",
                )
                outcomes.append({"type": atype, "result": gate})
            except Exception as e:
                outcomes.append({"type": atype, "error": str(e)})
        firings.append({"ruleId": rule["id"], "name": rule["name"], "matched": True,
                         "condition": cond, "outcomes": outcomes})
        # bump rule stats
        try:
            await db.rules.update_one(
                {"id": rule["id"]},
                {"$inc": {"triggerCount": 1}, "$set": {"lastTriggeredAt": _now_iso()}},
            )
        except Exception:
            pass

    execution = {
        "id": str(uuid.uuid4()),
        "eventId": event["id"],
        "eventType": event_type,
        "payload": event["payload"],
        "firings": firings,
        "ts": event["ts"],
        "businessId": business_id,
    }
    try:
        await db.rule_executions.insert_one(dict(execution))
    except Exception:
        pass
    return {"eventId": event["id"], "rulesEvaluated": len(rules),
            "ruleFirings": firings, "executionId": execution["id"]}


async def _delayed_action(delay: int, fn: Callable[..., Awaitable[Any]], rule, event, params):
    await asyncio.sleep(delay)
    try:
        await fn(rule, event, params)
    except Exception as e:
        logger.warning(f"Delayed action failed: {e}")


def action_library_meta() -> List[Dict[str, Any]]:
    return [{"type": k, "label": v["label"], "params": v.get("params", [])} for k, v in ACTION_LIBRARY.items()]


def event_catalog_meta() -> List[Dict[str, Any]]:
    return [{"type": k, **v} for k, v in EVENT_CATALOG.items()]


def safe_emit(event_type: str, payload: Optional[Dict[str, Any]] = None, entity_id: Optional[str] = None):
    """
    Fire-and-forget helper for producers that don't need to await
    (POS handlers, etc). Errors are logged, never raised.
    """
    async def _run():
        try:
            await emit_event(event_type, payload, entity_id)
        except Exception as e:
            logger.warning(f"Rules engine emit failed for {event_type}: {e}")

    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        # No running loop → just skip
        pass
