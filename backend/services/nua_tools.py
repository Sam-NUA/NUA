"""
Ash Tool Registry — the MCP-inspired capability catalog.

Design
──────
Every business capability Ash can invoke is defined ONCE here as a
`Tool` with:
  • name (snake_case) — LLM function name
  • label, description — human-readable
  • module — POS / Inventory / Customers / Reservations / Staff / Marketing / Finance / Ash
  • risk — low | medium | high | critical
  • defaultPermission — auto | approval | disabled
  • schema — JSON schema for arguments (used by GPT-5.2 function calling)
  • execute(args) → awaited outcome dict
  • rollback(outcome) → optional undo fn

Permissions
───────────
Owner-configurable in `db.ash_tool_config` — falls back to defaultPermission.
`Auto` runs immediately, `Approval` enqueues via approval_service,
`Disabled` blocks with a friendly explanation.
"""
from __future__ import annotations
from typing import Any, Awaitable, Callable, Dict, List, Optional
from datetime import datetime, timezone
from dataclasses import dataclass
from database import db
from middleware.actor_context import tenant_scope_filter, get_actor_context
from services import audit_service, approval_service
from pymongo import ReturnDocument
import asyncio
import uuid
import logging

logger = logging.getLogger(__name__)

HIGH_RISK_TIERS = {"high", "critical"}  # never allowed to auto-execute, regardless of config


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═════════════════════════════════════════════════════════════════════════
# Global kill switch — halts every mutating/auto tool execution regardless
# of entry point (chat agent, planner, direct API, approval execution).
# Stored in db.settings (same singleton-doc pattern as trust settings)
# rather than per-tool config, since it's meant to be one lever, not 23.
# ═════════════════════════════════════════════════════════════════════════
async def get_kill_switch() -> dict:
    s = await db.settings.find_one({"key": "ash_kill_switch"}, {"_id": 0})
    value = (s or {}).get("value") or {}
    return {
        "enabled": bool(value.get("enabled")),
        "reason": value.get("reason"),
        "setBy": value.get("setBy"),
        "setAt": value.get("setAt"),
    }


async def set_kill_switch(enabled: bool, actor: str, reason: Optional[str] = None) -> dict:
    """Owner-only at the route layer (see routes/nua.py) — this function
    itself doesn't re-check role, callers must gate it. Every toggle is
    audited so 'who paused Ash and when' is always answerable."""
    value = {"enabled": bool(enabled), "reason": reason, "setBy": actor, "setAt": _now()}
    await db.settings.update_one(
        {"key": "ash_kill_switch"}, {"$set": {"key": "ash_kill_switch", "value": value}}, upsert=True
    )
    await audit_service.log_event(
        entity_type="ash_kill_switch", entity_id="global", action="updated",
        after=value, memo=f"Ash global kill switch {'ENGAGED' if enabled else 'released'} by {actor}",
        severity="high" if enabled else "notice", tags=["ash_agent", "kill_switch"],
    )
    return value


@dataclass
class Tool:
    name: str
    label: str
    description: str
    module: str
    risk: str                                    # low | medium | high | critical
    default_permission: str                      # auto | approval | disabled
    parameters: Dict[str, Any]                   # JSON schema for LLM
    execute: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]
    rollback: Optional[Callable[[Dict[str, Any]], Awaitable[Any]]] = None
    expected_impact: str = "informational"       # informational | revenue | cost | csat | compliance


TOOLS: Dict[str, Tool] = {}


def register(tool: Tool) -> None:
    TOOLS[tool.name] = tool


# ═════════════════════════════════════════════════════════════════════════
# Individual tool implementations
# ═════════════════════════════════════════════════════════════════════════
async def _tx_dismiss_insight(a):
    r = await db.ash_insights.update_one({"id": a["insightId"], **tenant_scope_filter()},
                                          {"$set": {"resolvedAt": _now(), "resolvedBy": "ash-agent"}})
    if r.matched_count == 0:
        return {"error": "insight not found"}
    return {"insightId": a["insightId"], "resolved": True}


async def _tx_approve_pending_approval(a):
    """Ash approves a pending approval on the owner's behalf.
    We never bypass the queue — this only works when caller has permission.

    Tenant check added: approval_service.approve() itself has no
    businessId check (it trusts the caller to have already verified
    ownership — routes/approvals.py's HTTP endpoint does this before
    calling it), and this tool previously looked the approval up purely
    by the model-supplied approvalId with no check at all. Without this,
    a manager at business A (or a prompt-injected Ash agent acting on
    their behalf) could execute business B's pending approval — voucher
    issuance, refund, campaign send, whatever the underlying action is —
    just by supplying business B's approvalId."""
    from services.rules_engine import ACTION_LIBRARY
    from middleware.actor_context import get_actor_context, tenant_owns_strict
    doc = await db.approvals.find_one({"$and": [{"id": a["approvalId"]}, tenant_scope_filter(get_actor_context().get("businessId"))]}, {"_id": 0})
    if not doc:
        return {"error": "approval not found"}
    if not tenant_owns_strict(doc.get("businessId"), get_actor_context().get("businessId")):
        return {"error": "approval not found"}
    if doc["status"] != "pending":
        return {"error": f"already {doc['status']}"}
    action_meta = ACTION_LIBRARY.get(doc["actionType"])
    if not action_meta:
        return {"error": f"unknown underlying action {doc['actionType']}"}
    fake_rule = {"id": doc.get("sourceRef") or "ash", "name": "ash-agent approval"}
    fake_event = {"id": "ash", "type": "approval.executed", "payload": doc["params"]}
    async def _run(params): return await action_meta["fn"](fake_rule, fake_event, params)
    return await approval_service.approve(a["approvalId"], actor="ash-agent", execute_fn=_run)


async def _tx_reject_pending_approval(a):
    from middleware.actor_context import get_actor_context, tenant_owns_strict
    doc = await db.approvals.find_one({"$and": [{"id": a["approvalId"]}, tenant_scope_filter(get_actor_context().get("businessId"))]}, {"_id": 0})
    if not doc or not tenant_owns_strict(doc.get("businessId"), get_actor_context().get("businessId")):
        return {"error": "approval not found"}
    try:
        return await approval_service.reject(a["approvalId"], actor="ash-agent", reason=a.get("reason"))
    except ValueError as e:
        return {"error": str(e)}


async def _tx_adjust_menu_price(a):
    pid = a["productId"]; new_price = float(a["newPrice"])
    before = await db.products.find_one({"id": pid, **tenant_scope_filter()}, {"_id": 0})
    if not before:
        return {"error": "product not found"}
    await db.products.update_one(
        {"id": pid, **tenant_scope_filter()},
        {"$set": {"price": new_price, "updatedAt": _now(), "updatedBy": "ash-agent"}},
    )
    return {"productId": pid, "oldPrice": before.get("price"), "newPrice": new_price}


async def _rollback_menu_price(outcome):
    await db.products.update_one({"id": outcome["productId"], **tenant_scope_filter()},
                                  {"$set": {"price": outcome["oldPrice"]}})


async def _tx_issue_voucher(a):
    try:
        from routes.commerce_v29 import _issue_voucher
        v = await _issue_voucher({
            "sourceType": "ash_agent",
            "sourceRef": "chat",
            "label": a.get("label", "Ash-issued voucher"),
            "valueType": a.get("valueType", "amount"),
            "value": float(a.get("value") or 10),
            "customerId": a.get("customerId"),
        }, user=None)
        return {"voucherId": v["id"], "code": v["code"]}
    except Exception as e:
        return {"error": str(e), "mocked": True}


async def _tx_create_purchase_order(a):
    pid = a["productId"]; qty = int(a.get("quantity") or 10)
    est = float(a.get("estimatedCost") or (qty * float(a.get("unitCost") or 25)))
    product = await db.products.find_one({"id": pid, **tenant_scope_filter()}, {"_id": 0})
    if not product:
        return {"error": "product not found"}
    po = {
        "id": str(uuid.uuid4()),
        "productId": pid,
        "productName": (product or {}).get("name"),
        "quantity": qty,
        "supplierId": a.get("supplierId"),
        "estimatedCost": est,
        "status": "draft",
        "createdBy": "ash-agent",
        "createdAt": _now(),
        "businessId": get_actor_context().get("businessId"),
    }
    await db.purchase_orders.insert_one(dict(po))
    return {"purchaseOrderId": po["id"], "quantity": qty, "estimatedCost": est}


async def _rollback_purchase_order(outcome):
    """Soft-cancel, not delete — a PO already sent to a supplier shouldn't
    vanish from the record just because it was undone after the fact."""
    await db.purchase_orders.update_one(
        {"id": outcome["purchaseOrderId"], **tenant_scope_filter()},
        {"$set": {"status": "cancelled", "cancelledBy": "ash-agent-rollback", "cancelledAt": _now()}},
    )


async def _tx_add_customer_note(a):
    """customers.notes is a plain free-text string everywhere else in this
    codebase (seed data, the CRM UI, guest_intel.py), not an array — append
    to it rather than $push, which fails outright against a string field."""
    cid = a["customerId"]; note = a["note"]
    customer = await db.customers.find_one({**tenant_scope_filter(), "id": cid}, {"_id": 0, "notes": 1})
    if not customer:
        return {"error": "customer not found"}
    existing = (customer.get("notes") or "").strip()
    entry = f"[{_now()[:10]} · ash-agent] {note}"
    updated = f"{existing}\n{entry}" if existing else entry
    await db.customers.update_one({**tenant_scope_filter(), "id": cid}, {"$set": {"notes": updated}})
    return {"customerId": cid, "added": True}


async def _tx_add_wallet_credit(a):
    cid = a["customerId"]; amount = float(a["amount"])
    r = await db.customers.update_one({**tenant_scope_filter(), "id": cid}, {"$inc": {"storeCredit": amount}})
    ledger_id = None
    if r.matched_count:
        ledger_id = str(uuid.uuid4())
        await db.wallet_ledger.insert_one({
            "id": ledger_id, "customerId": cid, "type": "credit_grant",
            "amount": amount, "sourceType": "ash_agent", "createdAt": _now(),
            "description": a.get("reason", "Ash credit"),
            "businessId": get_actor_context().get("businessId"),
        })
    return {"customerId": cid, "credit": amount, "matched": r.matched_count, "ledgerId": ledger_id}


async def _rollback_wallet_credit(outcome):
    """Reverses the $inc with an equal-and-opposite one, and records a
    compensating ledger entry rather than deleting the original — deleting
    would leave storeCredit and wallet_ledger's own running total
    disagreeing with each other."""
    if not outcome.get("matched"):
        return
    cid = outcome["customerId"]; amount = float(outcome["credit"])
    await db.customers.update_one({**tenant_scope_filter(), "id": cid}, {"$inc": {"storeCredit": -amount}})
    await db.wallet_ledger.insert_one({
        "id": str(uuid.uuid4()), "customerId": cid, "type": "credit_reversal",
        "amount": -amount, "sourceType": "ash_agent_rollback", "createdAt": _now(),
        "description": f"Rollback of ledger entry {outcome.get('ledgerId')}",
        "reversalOf": outcome.get("ledgerId"),
        "businessId": get_actor_context().get("businessId"),
    })


async def _tx_upgrade_customer_tier(a):
    cid = a["customerId"]; tier = a["tier"]
    before = await db.customers.find_one({**tenant_scope_filter(), "id": cid}, {"_id": 0, "membershipTier": 1})
    if not before:
        return {"error": "customer not found"}
    r = await db.customers.update_one({**tenant_scope_filter(), "id": cid}, {"$set": {"membershipTier": tier, "vipUpgradedAt": _now()}})
    return {"customerId": cid, "oldTier": before.get("membershipTier"), "newTier": tier, "matched": r.matched_count}


async def _rollback_customer_tier(outcome):
    if not outcome.get("matched"):
        return
    await db.customers.update_one({**tenant_scope_filter(), "id": outcome["customerId"]},
                                   {"$set": {"membershipTier": outcome.get("oldTier")}})


async def _tx_mark_waste(a):
    pid = a["productId"]; qty = float(a.get("quantity") or 1); reason = a.get("reason", "spoilage")
    if not await db.products.find_one({"id": pid, **tenant_scope_filter()}, {"_id": 1}):
        return {"error": "product not found"}
    doc = {"id": str(uuid.uuid4()), "productId": pid, "quantity": qty, "reason": reason,
           "recordedBy": "ash-agent", "createdAt": _now(),
           "businessId": get_actor_context().get("businessId")}
    await db.waste_events.insert_one(dict(doc))
    await db.products.update_one({"id": pid, **tenant_scope_filter()}, {"$inc": {"stock": -qty}})
    from utils.stock_ops import clamp_negative_stock
    await clamp_negative_stock([pid])
    return {"wasteId": doc["id"], "productId": pid, "quantity": qty}


async def _rollback_waste(outcome):
    """Restores the deducted stock and marks the waste record reversed —
    kept, not deleted, so the audit trail still shows the original entry
    plus the fact it was undone."""
    await db.products.update_one(
        {"id": outcome["productId"], **tenant_scope_filter()}, {"$inc": {"stock": outcome["quantity"]}})
    await db.waste_events.update_one({"id": outcome["wasteId"], **tenant_scope_filter()},
                                      {"$set": {"reversed": True, "reversedAt": _now()}})


async def _tx_mark_dish_86(a):
    """Field names must match models/product.py (eightySixed/eightySixedAt/
    eightySixedBy) — an earlier version of this used is86ed/eightySixReason,
    fields nothing else in the codebase (POS, kitchen display, online
    ordering, low-stock/OOS endpoints) has ever read, so it silently 86'd
    nothing anywhere visible. services/rules_engine.py's identical action
    had the same bug, fixed alongside this one."""
    pid = a["productId"]
    before = await db.products.find_one({"id": pid, **tenant_scope_filter()})
    if before is None:
        return {"error": "product not found"}
    r = await db.products.update_one(
        {"id": pid, **tenant_scope_filter()},
        {"$set": {"eightySixed": True, "eightySixedAt": _now(), "eightySixedBy": "ash-agent",
                   "eightySixedReason": a.get("reason", "ash-agent")}},
    )
    return {"productId": pid, "matched": r.matched_count,
            "wasAlready86ed": bool(before.get("eightySixed")), "oldReason": before.get("eightySixedReason")}


async def _rollback_dish_86(outcome):
    if not outcome.get("matched"):
        return
    was_86ed = outcome.get("wasAlready86ed", False)
    await db.products.update_one(
        {"id": outcome["productId"], **tenant_scope_filter()},
        {"$set": {"eightySixed": was_86ed, "eightySixedReason": outcome.get("oldReason"),
                   "eightySixedAt": _now() if was_86ed else None}},
    )


async def _tx_cancel_reservation(a):
    r = await db.reservations.update_one({"id": a["reservationId"], **tenant_scope_filter()},
                                          {"$set": {"status": "cancelled", "cancelledBy": "ash-agent",
                                                    "cancellationReason": a.get("reason")}})
    return {"reservationId": a["reservationId"], "matched": r.matched_count}


async def _tx_send_customer_sms(a):
    to = a.get("phone") or "unknown"; text = a["text"]
    try:
        from utils.notifications import send_sms
        await send_sms(to, text)
        return {"sent": True, "to": to}
    except Exception:
        logger.info(f"[ash sms MOCKED] to={to} text={text}")
        return {"sent": False, "mocked": True, "to": to, "text": text}


async def _tx_call_customer(a):
    """Places a real outbound phone call via Twilio Voice — NUA speaks the
    opening line, gathers the guest's spoken reply, and hangs up once it
    has a confirm/decline (or after a few turns). Requires Twilio
    credentials; returns an error dict (never a fake 'call placed') when
    they're absent, same honesty contract as send_customer_sms."""
    import os
    from routes.voice_calls import initiate_call
    base_url = os.environ.get("TWILIO_WEBHOOK_BASE_URL") or os.environ.get("BACKEND_PUBLIC_URL")
    if not base_url:
        return {"error": "No public base URL configured for voice callbacks "
                          "(set TWILIO_WEBHOOK_BASE_URL or BACKEND_PUBLIC_URL)"}
    try:
        return await initiate_call(
            customer_id=a.get("customerId"), phone=a.get("phone"),
            purpose=a.get("purpose", "custom"), context=a.get("context"),
            base_url=base_url, actor={"name": "ash-agent"},
        )
    except Exception as e:
        return {"error": str(e)}


async def _tx_send_customer_email(a):
    to = a["email"]; subj = a["subject"]; body = a["body"]
    try:
        from utils.notifications import send_email
        await send_email(to, subj, body)
        return {"sent": True, "to": to}
    except Exception:
        logger.info(f"[ash email MOCKED] to={to} subj={subj}")
        return {"sent": False, "mocked": True, "to": to, "subject": subj}


async def _tx_create_task(a):
    doc = {"id": str(uuid.uuid4()), "title": a["title"], "assignee": a.get("assignee", "manager"),
           "priority": a.get("priority", "normal"), "dueAt": a.get("dueAt"),
           "createdBy": "ash-agent", "status": "open", "createdAt": _now(),
           "businessId": get_actor_context().get("businessId")}
    await db.tasks.insert_one(dict(doc))
    return {"taskId": doc["id"]}


async def _rollback_task(outcome):
    await db.tasks.update_one({"id": outcome["taskId"], **tenant_scope_filter()},
                               {"$set": {"status": "cancelled", "cancelledBy": "ash-agent-rollback"}})


async def _tx_check_promo_voucher(a):
    """Read-only: look up a venue promo/voucher code (e.g. one embedded in an
    email campaign) and report whether it's still redeemable. Staff can ask
    NUA to check a code a guest presents at the venue before it's applied
    through the normal POS voucher flow — NUA never redeems it directly, so
    the money-moving step always stays inside POS's own audit trail."""
    code = (a.get("code") or "").strip().upper()
    if not code:
        return {"error": "code required"}
    v = await db.commerce_vouchers.find_one(
        {"$or": [{"manualCode": code}, {"barcode": code}, {"id": code}],
         **tenant_scope_filter(get_actor_context().get("businessId"))}, {"_id": 0},
    )
    if not v:
        return {"valid": False, "code": code, "reason": "Code not found"}
    from routes.v26_commerce import _voucher_within_window
    valid = bool(v.get("active")) and _voucher_within_window(v)
    reason = None
    if not valid:
        reason = "Deactivated" if not v.get("active") else "Expired or fully redeemed"
    return {
        "valid": valid, "code": v.get("manualCode"), "name": v.get("name"),
        "discountType": v.get("discountType"), "value": v.get("value"),
        "minSpend": v.get("minSpend"), "usedCount": v.get("usedCount"),
        "maxUses": v.get("maxUses"), "validTo": v.get("validTo"), "reason": reason,
    }


async def _tx_create_promotion(a):
    doc = {"id": str(uuid.uuid4()), "name": a["name"], "type": a.get("type", "percent"),
           "discount": float(a.get("discount") or 10), "active": True, "createdBy": "ash-agent",
           "createdAt": _now(), "productId": a.get("productId"),
           "businessId": get_actor_context().get("businessId")}
    await db.promotions.insert_one(dict(doc))
    return {"promotionId": doc["id"]}


async def _rollback_promotion(outcome):
    await db.promotions.update_one({"id": outcome["promotionId"], **tenant_scope_filter()},
                                    {"$set": {"active": False, "deactivatedBy": "ash-agent-rollback"}})


async def _tx_run_ash_scan(a):
    from services.nua_intelligence import run_all_insights
    return await run_all_insights(include_summary=False)


async def _tx_generate_weekly_summary(a):
    from services.nua_intelligence import generate_weekly_summary
    doc = await generate_weekly_summary()
    if not doc:
        return {"error": "no summary generated"}
    await db.ash_insights.update_one(
        {"category": doc["category"], "key": doc["key"], **tenant_scope_filter()},
        {"$set": {**doc, "businessId": get_actor_context().get("businessId")},
         "$setOnInsert": {"firstSeenAt": doc["createdAt"]}},
        upsert=True,
    )
    return {"summary": doc["body"], "data": doc["data"]}


async def _tx_fetch_kpis(a):
    """Read-only tool — get finance KPIs."""
    from services.accounting_service import profit_and_loss, balance_sheet
    from datetime import date, timedelta
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=int(a.get("days", 7)))).isoformat()
    pnl = await profit_and_loss(start, end)
    bs = await balance_sheet(as_of=end)
    return {"revenue": pnl["totalRevenue"], "grossProfit": pnl["grossProfit"],
            "netProfit": pnl["netProfit"], "cash": bs["totalAssets"],
            "range": f"{start} → {end}"}


async def _tx_fetch_open_insights(a):
    rows = await db.ash_insights.find(
        {"resolvedAt": None, **tenant_scope_filter()}, {"_id": 0}
    ).sort("createdAt", -1).limit(50).to_list(50)
    return {"insights": [{"id": i["id"], "category": i["category"], "severity": i["severity"],
                            "title": i["title"], "body": i["body"]} for i in rows]}


async def _tx_lookup_customer(a):
    q = (a.get("query") or "").strip()
    if not q:
        return {"error": "query required"}
    row = await db.customers.find_one(
        {**tenant_scope_filter(), "$or": [{"email": {"$regex": q, "$options": "i"}},
                 {"name": {"$regex": q, "$options": "i"}},
                 {"phone": {"$regex": q, "$options": "i"}}]},
        {"_id": 0},
    )
    if not row:
        return {"error": "not found"}
    return {"customer": {k: row.get(k) for k in ("id", "name", "email", "phone", "membershipTier", "totalSpent", "visits", "lastVisit")}}


async def _tx_lookup_product(a):
    q = (a.get("query") or "").strip()
    row = await db.products.find_one(
        {"name": {"$regex": q, "$options": "i"}, **tenant_scope_filter()}, {"_id": 0})
    if not row:
        return {"error": "not found"}
    return {"product": {k: row.get(k) for k in ("id", "name", "price", "cost", "stock", "category")}}


async def _tx_generate_daily_briefing(a):
    """Delegate to briefing endpoint for consistency."""
    from services import nua_briefing
    return await nua_briefing.generate_briefing()


async def _tx_remember(a):
    from services import nua_memory
    doc = await nua_memory.remember(
        text=a["text"],
        scope=a.get("scope", "global"),
        kind=a.get("kind", "fact"),
        confidence=float(a.get("confidence") or 0.7),
        source="ash_agent",
        tags=a.get("tags") or [],
    )
    return {"memoryId": doc["id"], "reinforced": bool(doc.get("reinforced")),
            "confidence": doc.get("confidence"), "scope": doc.get("scope")}


async def _tx_recall(a):
    from services import nua_memory
    rows = await nua_memory.recall(scope=a.get("scope", "global"),
                                     limit=int(a.get("limit") or 10),
                                     kind=a.get("kind"))
    return {"memories": [{"id": r["id"], "kind": r["kind"], "text": r["text"],
                            "confidence": r["confidence"], "scope": r["scope"]}
                            for r in rows]}


# ═════════════════════════════════════════════════════════════════════════
# Registration
# ═════════════════════════════════════════════════════════════════════════
_TOOL_DEFS: List[Dict[str, Any]] = [
    # ── Ash / read-only ──
    {"n": "fetch_open_insights", "l": "Fetch open Ash insights", "m": "Ash", "r": "low", "p": "auto",
     "params": {"type": "object", "properties": {}}, "fn": _tx_fetch_open_insights, "impact": "informational"},
    {"n": "fetch_kpis", "l": "Fetch financial KPIs", "m": "Finance", "r": "low", "p": "auto",
     "params": {"type": "object", "properties": {"days": {"type": "integer", "default": 7}}}, "fn": _tx_fetch_kpis},
    {"n": "lookup_customer", "l": "Look up a customer", "m": "Customers", "r": "low", "p": "auto",
     "params": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
     "fn": _tx_lookup_customer},
    {"n": "lookup_product", "l": "Look up a product", "m": "Inventory", "r": "low", "p": "auto",
     "params": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
     "fn": _tx_lookup_product},
    {"n": "run_ash_scan", "l": "Run all Ash generators now", "m": "Ash", "r": "low", "p": "auto",
     "params": {"type": "object", "properties": {}}, "fn": _tx_run_ash_scan},
    {"n": "generate_weekly_summary", "l": "Generate the weekly business summary", "m": "Ash", "r": "low", "p": "auto",
     "params": {"type": "object", "properties": {}}, "fn": _tx_generate_weekly_summary},
    {"n": "generate_daily_briefing", "l": "Generate this morning's briefing", "m": "Ash", "r": "low", "p": "auto",
     "params": {"type": "object", "properties": {}}, "fn": _tx_generate_daily_briefing},
    {"n": "remember", "l": "Save a long-term memory / preference / pattern", "m": "Ash", "r": "low", "p": "auto",
     "params": {"type": "object",
                 "properties": {"text": {"type": "string"},
                                 "scope": {"type": "string",
                                             "description": "global | customer:<id> | staff:<id> | product:<id> | supplier:<id>"},
                                 "kind": {"type": "string", "enum": ["preference", "pattern", "fact", "note"]},
                                 "confidence": {"type": "number"},
                                 "tags": {"type": "array", "items": {"type": "string"}}},
                 "required": ["text"]},
     "fn": _tx_remember, "impact": "informational"},
    {"n": "recall", "l": "Retrieve long-term memories for a scope", "m": "Ash", "r": "low", "p": "auto",
     "params": {"type": "object",
                 "properties": {"scope": {"type": "string"},
                                 "kind": {"type": "string"},
                                 "limit": {"type": "integer", "default": 10}}},
     "fn": _tx_recall},

    # ── Ash / dismiss / approvals ──
    {"n": "dismiss_insight", "l": "Dismiss an Ash insight", "m": "Ash", "r": "low", "p": "auto",
     "params": {"type": "object", "properties": {"insightId": {"type": "string"}}, "required": ["insightId"]},
     "fn": _tx_dismiss_insight},
    {"n": "approve_pending_approval", "l": "Approve a pending approval", "m": "Ash", "r": "high", "p": "approval",
     "params": {"type": "object", "properties": {"approvalId": {"type": "string"}}, "required": ["approvalId"]},
     "fn": _tx_approve_pending_approval},
    {"n": "reject_pending_approval", "l": "Reject a pending approval", "m": "Ash", "r": "medium", "p": "approval",
     "params": {"type": "object", "properties": {"approvalId": {"type": "string"},
                                                    "reason": {"type": "string"}},
                "required": ["approvalId"]},
     "fn": _tx_reject_pending_approval},

    # ── Inventory / write ──
    {"n": "create_purchase_order", "l": "Create a purchase order", "m": "Inventory", "r": "high", "p": "approval",
     "params": {"type": "object",
                 "properties": {"productId": {"type": "string"}, "quantity": {"type": "integer"},
                                 "supplierId": {"type": "string"}, "unitCost": {"type": "number"},
                                 "estimatedCost": {"type": "number"}},
                 "required": ["productId", "quantity"]},
     "fn": _tx_create_purchase_order, "rollback": _rollback_purchase_order, "impact": "cost"},
    {"n": "mark_waste", "l": "Log a waste event & deduct stock", "m": "Inventory", "r": "medium", "p": "approval",
     "params": {"type": "object",
                 "properties": {"productId": {"type": "string"}, "quantity": {"type": "number"},
                                 "reason": {"type": "string"}}, "required": ["productId", "quantity"]},
     "fn": _tx_mark_waste, "rollback": _rollback_waste, "impact": "cost"},
    {"n": "mark_dish_86", "l": "Mark a dish as 86'd", "m": "Inventory", "r": "medium", "p": "approval",
     "params": {"type": "object",
                 "properties": {"productId": {"type": "string"}, "reason": {"type": "string"}},
                 "required": ["productId"]},
     "fn": _tx_mark_dish_86, "rollback": _rollback_dish_86, "impact": "revenue"},
    {"n": "adjust_menu_price", "l": "Change a product price", "m": "Inventory", "r": "high", "p": "approval",
     "params": {"type": "object",
                 "properties": {"productId": {"type": "string"}, "newPrice": {"type": "number"},
                                 "reason": {"type": "string"}},
                 "required": ["productId", "newPrice"]},
     "fn": _tx_adjust_menu_price, "rollback": _rollback_menu_price, "impact": "revenue"},

    # ── Customers / write ──
    {"n": "add_customer_note", "l": "Add a note to a customer", "m": "Customers", "r": "low", "p": "auto",
     "params": {"type": "object",
                 "properties": {"customerId": {"type": "string"}, "note": {"type": "string"}},
                 "required": ["customerId", "note"]},
     "fn": _tx_add_customer_note},
    {"n": "add_wallet_credit", "l": "Grant store credit", "m": "Customers", "r": "high", "p": "approval",
     "params": {"type": "object",
                 "properties": {"customerId": {"type": "string"}, "amount": {"type": "number"},
                                 "reason": {"type": "string"}},
                 "required": ["customerId", "amount"]},
     "fn": _tx_add_wallet_credit, "rollback": _rollback_wallet_credit, "impact": "cost"},
    {"n": "issue_voucher", "l": "Issue a voucher to a customer", "m": "Customers", "r": "medium", "p": "approval",
     "params": {"type": "object",
                 "properties": {"customerId": {"type": "string"}, "value": {"type": "number"},
                                 "label": {"type": "string"}, "valueType": {"type": "string"}},
                 "required": ["value"]},
     "fn": _tx_issue_voucher, "impact": "cost"},
    {"n": "upgrade_customer_tier", "l": "Change a customer's loyalty tier", "m": "Customers", "r": "medium", "p": "approval",
     "params": {"type": "object",
                 "properties": {"customerId": {"type": "string"}, "tier": {"type": "string"}},
                 "required": ["customerId", "tier"]},
     "fn": _tx_upgrade_customer_tier, "rollback": _rollback_customer_tier, "impact": "csat"},

    # ── Reservations ──
    {"n": "cancel_reservation", "l": "Cancel a reservation", "m": "Reservations", "r": "medium", "p": "approval",
     "params": {"type": "object",
                 "properties": {"reservationId": {"type": "string"}, "reason": {"type": "string"}},
                 "required": ["reservationId"]},
     "fn": _tx_cancel_reservation, "impact": "csat"},

    # ── Marketing ──
    {"n": "send_customer_sms", "l": "Send an SMS to a customer", "m": "Marketing", "r": "medium", "p": "approval",
     "params": {"type": "object",
                 "properties": {"phone": {"type": "string"}, "text": {"type": "string"}},
                 "required": ["text"]},
     "fn": _tx_send_customer_sms, "impact": "csat"},
    {"n": "call_customer", "l": "Call a customer to confirm or follow up by voice", "m": "Marketing",
     "r": "medium", "p": "approval",
     "params": {"type": "object",
                 "properties": {"customerId": {"type": "string"}, "phone": {"type": "string"},
                                 "purpose": {"type": "string", "enum": ["confirm_booking", "reminder", "custom"]},
                                 "context": {"type": "object",
                                             "description": "e.g. {date, time, partySize} for confirm_booking, or {message} for custom"}},
                 "required": ["purpose"]},
     "fn": _tx_call_customer, "impact": "csat"},
    {"n": "send_customer_email", "l": "Send an email to a customer", "m": "Marketing", "r": "medium", "p": "approval",
     "params": {"type": "object",
                 "properties": {"email": {"type": "string"}, "subject": {"type": "string"},
                                 "body": {"type": "string"}},
                 "required": ["email", "subject", "body"]},
     "fn": _tx_send_customer_email},
    {"n": "create_promotion", "l": "Create a promotion", "m": "Marketing", "r": "medium", "p": "approval",
     "params": {"type": "object",
                 "properties": {"name": {"type": "string"}, "discount": {"type": "number"},
                                 "type": {"type": "string"}, "productId": {"type": "string"}},
                 "required": ["name"]},
     "fn": _tx_create_promotion, "rollback": _rollback_promotion, "impact": "revenue"},
    {"n": "check_promo_voucher", "l": "Check whether a promo/voucher code is still redeemable", "m": "Marketing",
     "r": "low", "p": "auto",
     "params": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]},
     "fn": _tx_check_promo_voucher, "impact": "informational"},

    # ── Staff ──
    {"n": "create_staff_task", "l": "Create a task for a staff member", "m": "Staff", "r": "low", "p": "auto",
     "params": {"type": "object",
                 "properties": {"title": {"type": "string"}, "assignee": {"type": "string"},
                                 "priority": {"type": "string"}, "dueAt": {"type": "string"}},
                 "required": ["title"]},
     "fn": _tx_create_task, "rollback": _rollback_task},
]

for d in _TOOL_DEFS:
    register(Tool(
        name=d["n"], label=d["l"], description=d.get("desc", d["l"]),
        module=d["m"], risk=d["r"], default_permission=d["p"],
        parameters=d["params"], execute=d["fn"],
        rollback=d.get("rollback"), expected_impact=d.get("impact", "informational"),
    ))


# ═════════════════════════════════════════════════════════════════════════
# Permission resolution & execution
# ═════════════════════════════════════════════════════════════════════════
async def resolve_permission(tool_name: str, business_id: Optional[str] = None) -> str:
    """Look up owner override, else fall back to tool default.

    A hard floor: high/critical-risk tools can never resolve to "auto", no
    matter what's stored in db.ash_tool_config. This used to be enforced
    only by convention (every high-risk tool happened to default to
    "approval") — a manager could still flip one straight to auto via
    PUT /tools/{name}/permission with nothing to stop it. The write-side
    also rejects that now (routes/nua.py's set_tool_permission), but this
    read-side floor is the one that actually matters: it holds even if a
    bad value ever ends up in the database by some other path.

    The override lookup is scoped to the caller's own business (defaulting
    from the request's actor context, same pattern as
    notification_service.send()) — without this, one business's tool
    permission override (e.g. disabling issue_voucher, or promoting a
    low-risk tool to auto) silently applied to every other business on the
    deployment too.
    """
    tool = TOOLS.get(tool_name)
    if not tool:
        return "disabled"
    if business_id is None:
        business_id = get_actor_context().get("businessId")
    override = await db.ash_tool_config.find_one(
        {"toolName": tool_name, **tenant_scope_filter(business_id)}, {"_id": 0})
    perm = (override or {}).get("permission") or tool.default_permission
    if perm == "auto" and tool.risk in HIGH_RISK_TIERS:
        return "approval"
    return perm


async def execute_tool(tool_name: str, args: Dict[str, Any], *, actor: str = "ash-agent",
                        idempotency_key: Optional[str] = None) -> Dict[str, Any]:
    """Run a tool through the permission gate. Always returns a dict.

    idempotency_key, when supplied, dedups repeated calls (a retry, a
    replayed chat message, two near-simultaneous requests) so a mutating
    tool never runs twice for what is really the same request. Omitting it
    preserves the old at-most-once-per-call behavior — callers that don't
    have a natural key (nothing here forces one) just don't get dedup.
    """
    tool = TOOLS.get(tool_name)
    if not tool:
        await audit_service.log_event(
            entity_type="ash_tool:unknown", entity_id=tool_name, action="blocked",
            after={"reason": "unknown_tool", "args": args},
            memo=f"Blocked call to unknown Ash tool '{tool_name}'",
            severity="warning", tags=["ash_agent", "blocked"],
        )
        return {"status": "error", "error": f"Unknown tool: {tool_name}"}

    if idempotency_key:
        prior = await db.ash_tool_idempotency.find_one_and_update(
            {"toolName": tool_name, "idempotencyKey": idempotency_key},
            {"$setOnInsert": {"toolName": tool_name, "idempotencyKey": idempotency_key,
                               "createdAt": _now(), "result": None}},
            upsert=True, return_document=ReturnDocument.BEFORE,
        )
        if prior is not None:
            # A doc already existed before this call — this is a retry,
            # replay, or a concurrent duplicate racing the first caller.
            # Wait briefly for that first call to finish and reuse its
            # result instead of re-running a mutating action.
            existing = prior
            for _ in range(20):  # ~2s total
                if existing.get("result") is not None:
                    return existing["result"]
                await asyncio.sleep(0.1)
                existing = await db.ash_tool_idempotency.find_one(
                    {"toolName": tool_name, "idempotencyKey": idempotency_key}, {"_id": 0})
            return {"status": "duplicate_in_progress", "tool": tool_name,
                     "reason": "An identical request is already being processed"}

    async def _finish(result: Dict[str, Any]) -> Dict[str, Any]:
        if idempotency_key:
            await db.ash_tool_idempotency.update_one(
                {"toolName": tool_name, "idempotencyKey": idempotency_key},
                {"$set": {"result": result}},
            )
        return result

    kill_switch = await get_kill_switch()
    if kill_switch["enabled"]:
        await audit_service.log_event(
            entity_type=f"ash_tool:{tool.module}", entity_id=tool_name, action="blocked",
            after={"reason": "kill_switch_engaged", "args": args, "killSwitchReason": kill_switch.get("reason")},
            memo=f"Blocked '{tool_name}' — Ash is globally paused",
            severity="warning", tags=["ash_agent", "blocked", "kill_switch"],
        )
        return await _finish({"status": "blocked", "reason": f"Ash is globally paused: {kill_switch.get('reason') or 'no reason given'}",
                 "tool": tool_name, "killSwitch": True})

    perm = await resolve_permission(tool_name)
    if perm == "disabled":
        await audit_service.log_event(
            entity_type=f"ash_tool:{tool.module}", entity_id=tool_name, action="blocked",
            after={"reason": "disabled_by_policy", "args": args},
            memo=f"Blocked call to disabled tool '{tool_name}'",
            severity="notice", tags=["ash_agent", "blocked", f"risk_{tool.risk}"],
        )
        return await _finish({"status": "blocked", "reason": f"Tool '{tool_name}' is disabled by policy",
                 "tool": tool_name, "permission": perm})
    if perm == "approval":
        appr = await approval_service.enqueue_approval(
            action_type=tool_name, params=args, requested_by=actor,
            source="ash_agent",
            context={"toolName": tool_name, "label": tool.label, "risk": tool.risk},
        )
        return await _finish({"status": "pending_approval", "approvalId": appr["id"],
                 "tool": tool_name, "permission": perm, "expectedImpact": tool.expected_impact,
                 "risk": tool.risk})
    # auto
    try:
        outcome = await tool.execute(args)
    except Exception as e:
        logger.warning(f"[ash tool] {tool_name} failed: {e}")
        outcome = {"error": str(e)}
    await audit_service.log_event(
        entity_type=f"ash_tool:{tool.module}",
        entity_id=tool_name,
        action="executed",
        after={"args": args, "outcome": outcome},
        memo=f"Ash-agent executed {tool.label}",
        severity="notice",
        tags=["ash_agent", f"risk_{tool.risk}"],
    )
    return await _finish({"status": "executed", "tool": tool_name, "outcome": outcome,
             "risk": tool.risk, "expectedImpact": tool.expected_impact,
             "rollbackAvailable": tool.rollback is not None})


# ═════════════════════════════════════════════════════════════════════════
# Public catalog helpers
# ═════════════════════════════════════════════════════════════════════════
def catalog() -> List[Dict[str, Any]]:
    return [
        {
            "name": t.name, "label": t.label, "module": t.module,
            "risk": t.risk, "defaultPermission": t.default_permission,
            "parameters": t.parameters, "rollbackAvailable": t.rollback is not None,
            "expectedImpact": t.expected_impact,
        }
        for t in sorted(TOOLS.values(), key=lambda x: (x.module, x.name))
    ]


def openai_schema() -> List[Dict[str, Any]]:
    """Return the tool list in OpenAI function-calling shape."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": f"[{t.module}] {t.label} (risk={t.risk})",
                "parameters": t.parameters,
            },
        }
        for t in TOOLS.values()
    ]
