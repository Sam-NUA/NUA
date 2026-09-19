"""NUA v25 — Enterprise Suite.

Consolidates the v25-v30 roadmap into one cohesive module:

MUST HAVE
- Offline sync queue          POST/GET   /api/v25/sync-queue
- Loss-control exceptions     GET/POST   /api/v25/exceptions
- Multi-site command          GET/POST   /api/v25/sites + /publish + /rollback
- Hardware health             GET/POST   /api/v25/hardware
- Chargebacks/disputes        GET/POST   /api/v25/disputes
- Supplier marketplace        GET/POST   /api/v25/suppliers/compare

SHOULD HAVE
- Kiosk session               POST/GET   /api/v25/kiosk/*
- Customer-facing display     GET        /api/v25/cfd/current
- Smart substitution / 86      POST       /api/v25/substitute
- Guest recovery automation   POST/GET   /api/v25/recovery/*
- Station readiness score     GET        /api/v25/station-readiness
- Menu margin guardrails      GET        /api/v25/margin-guardrails

TIER 1-5 EXTRAS
- NUA Pro (AI GM) approval     POST       /api/v25/ash-pro/plan + /approve
- Profit Guardian nightly      GET        /api/v25/profit-guardian
- Digital twin forecast        GET        /api/v25/digital-twin
- AI Shift Manager alerts      GET        /api/v25/shift-manager
- Autonomous marketing         POST/GET   /api/v25/marketing/auto
- Dynamic pricing rules        GET/POST   /api/v25/dynamic-pricing
- Subscription memberships    GET/POST   /api/v25/subscriptions
- Smart gift cards            GET/POST   /api/v25/gift-cards
- Recipe costing engine       GET/POST   /api/v25/recipes/*
- Predictive ordering         POST       /api/v25/predictive-orders
- Waste tracking              GET/POST   /api/v25/waste
- Universal guest profile     GET        /api/v25/guest/{id}
- AI concierge                POST       /api/v25/concierge
- Reputation command center   GET/POST   /api/v25/reputation/*
- Smart recovery (review)     POST       /api/v25/recovery-action
- Franchise command           GET/POST   /api/v25/franchise/*
- Multi-store benchmark       GET        /api/v25/benchmark
- Data warehouse export       GET        /api/v25/warehouse/export
- AI fraud detection          GET        /api/v25/fraud-detection
"""
from fastapi import APIRouter, HTTPException, Request, Depends
from deps import get_user, optional_user, require_owner, require_owner_or_manager
from database import db
from routes.products import GUEST_HIDDEN_PRODUCT_FIELDS
from middleware.actor_context import tenant_scope_filter, tenant_owns, tenant_owns_strict
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict
from typing import Optional, Any, cast
import uuid
import os
import json
import re
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v25")


def _now(): return datetime.now(timezone.utc).isoformat()
def _uid(prefix: str) -> str: return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


async def _llm_json(session_id: str, system: str, user_text: str, model: str = "gpt-5.2"):
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=os.environ.get("EMERGENT_LLM_KEY"),
            session_id=session_id, system_message=system,
        ).with_model("openai", model)
        resp = await chat.send_message(UserMessage(text=user_text))
        text = (resp or "").strip().strip("`")
        try: return json.loads(text)
        except Exception:
            m = re.search(r"\{.*\}|\[.*\]", text, re.DOTALL)
            return json.loads(m.group(0)) if m else {}
    except Exception as e:
        logger.warning("LLM [%s]: %s", session_id, str(e)[:200])
        return {"_error": str(e)[:200]}


# ============================================================================
# v25 MUST-HAVE — Offline Sync Queue
# ============================================================================
@router.post("/sync-queue")
async def push_sync(data: dict, user: dict = Depends(get_user)):
    """Receive a batch of pending offline operations from a client."""
    ops = data.get("ops") or []
    accepted, conflicts = [], []
    business_id = user.get("businessId")
    for op in ops:
        op_id = op.get("clientOpId") or _uid("OP")
        existing = await db.sync_ops.find_one(
            {"$and": [tenant_scope_filter(business_id), {"clientOpId": op_id}]}, {"_id": 0})
        if existing:
            conflicts.append({"clientOpId": op_id, "reason": "duplicate"})
            continue
        rec = {**op, "clientOpId": op_id, "id": _uid("SYNC"), "userId": user["id"],
               "status": "applied", "receivedAt": _now(), "businessId": business_id}
        await db.sync_ops.insert_one(rec)
        accepted.append(op_id)
    return {"accepted": accepted, "conflicts": conflicts}


@router.get("/sync-queue")
async def list_sync(limit: int = 100, user: dict = Depends(get_user)):
    rows = await db.sync_ops.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}) \
        .sort("receivedAt", -1).to_list(limit)
    return rows


@router.post("/sync-queue/process")
async def process_sync_queue(user: dict = Depends(require_owner_or_manager)):
    """Replay queued offline operations into their target collections. Handles
    the most common op types written by the POS while offline: create
    transaction, create kitchen order, adjust stock, append to held tab.
    Idempotent — already-applied clientOpIds are skipped."""
    business_id = user.get("businessId")
    query = {"$and": [tenant_scope_filter(business_id),
                       {"status": "applied", "replayedAt": {"$exists": False}}]}
    pending = await db.sync_ops.find(query, {"_id": 0}).to_list(500)
    applied, errors = 0, []
    for op in pending:
        kind = op.get("kind") or op.get("type")
        payload = op.get("payload") or op.get("data") or {}
        try:
            if kind == "transaction.create":
                payload.setdefault("id", _uid("TX"))
                payload.setdefault("createdAt", _now())
                payload["offlineReplayed"] = True
                payload["businessId"] = business_id
                await db.transactions.insert_one(payload)
            elif kind == "kitchen.order":
                payload.setdefault("id", _uid("KO"))
                payload.setdefault("status", "pending")
                payload["businessId"] = business_id
                await db.kitchen_orders.insert_one(payload)
            elif kind == "stock.adjust":
                guard = await db.products.find_one(
                    {"$and": [{"id": payload.get("productId")}, tenant_scope_filter(business_id)]}, {"_id": 0, "id": 1, "businessId": 1})
                if guard is None or not tenant_owns_strict(guard.get("businessId"), business_id):
                    errors.append({"clientOpId": op.get("clientOpId"), "reason": "product not found"})
                    continue
                await db.products.update_one(
                    {"$and": [{"id": payload.get("productId")}, tenant_scope_filter(business_id)]},
                    {"$inc": {"stock": int(payload.get("delta", 0))}},
                )
            elif kind == "tab.append":
                guard = await db.pos_tabs.find_one(
                    {"$and": [{"id": payload.get("tabId")}, tenant_scope_filter(business_id)]}, {"_id": 0, "id": 1, "businessId": 1})
                if guard is None or not tenant_owns_strict(guard.get("businessId"), business_id):
                    errors.append({"clientOpId": op.get("clientOpId"), "reason": "tab not found"})
                    continue
                await db.pos_tabs.update_one(
                    {"$and": [{"id": payload.get("tabId")}, tenant_scope_filter(business_id)]},
                    {"$push": {"cart": payload.get("item")}},
                )
            else:
                errors.append({"clientOpId": op.get("clientOpId"), "reason": f"unknown kind {kind}"})
                continue
            await db.sync_ops.update_one(
                {"clientOpId": op.get("clientOpId")},
                {"$set": {"replayedAt": _now(), "replayedBy": user["id"]}},
            )
            applied += 1
        except Exception as e:
            errors.append({"clientOpId": op.get("clientOpId"), "reason": str(e)[:120]})
    return {"applied": applied, "errors": errors, "pendingBefore": len(pending)}


# ============================================================================
# v25 MUST-HAVE — Loss-Control / Exception Center
# ============================================================================
@router.get("/exceptions")
async def list_exceptions(user: dict = Depends(require_owner_or_manager)):
    days = 14
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    query = {"$and": [tenant_scope_filter(user.get("businessId")), {"createdAt": {"$gte": cutoff}}]}
    tx = await db.transactions.find(query, {"_id": 0}).to_list(5000)
    voids, comps, discounts, refunds = 0, 0, 0, 0
    by_user = defaultdict(lambda: {"voids": 0, "comps": 0, "discounts": 0.0, "refunds": 0.0})
    exceptions = []
    for t in tx:
        uid = t.get("cashier") or t.get("createdBy") or "unknown"
        if t.get("voided"):
            voids += 1; by_user[uid]["voids"] += 1
            exceptions.append({"id": _uid("EX"), "type": "void", "txId": t.get("id"), "user": uid, "amount": t.get("total", 0), "createdAt": t.get("createdAt")})
        if t.get("compTotal", 0) > 0:
            comps += 1; by_user[uid]["comps"] += 1
        d = float(t.get("discount", 0) or 0)
        if d > 0:
            discounts += d; by_user[uid]["discounts"] += d
        if t.get("refunded"):
            refunds += 1; by_user[uid]["refunds"] += float(t.get("total", 0) or 0)
    # Suspicious if any single user has > 3 voids in window
    suspicious = [{"user": u, **v} for u, v in by_user.items() if v["voids"] >= 3]
    return {
        "window_days": days,
        "totals": {"voids": voids, "comps": comps, "discounts": round(discounts, 2), "refunds": refunds},
        "byUser": [{"user": u, **v} for u, v in by_user.items()],
        "suspicious": suspicious,
        "recentExceptions": exceptions[:50],
    }


# ============================================================================
# v25 MUST-HAVE — Multi-Site Command Center
# ============================================================================
@router.get("/sites")
async def list_sites(user: dict = Depends(get_user)):
    business_id = user.get("businessId")
    sites = await db.sites.find(tenant_scope_filter(business_id), {"_id": 0}).to_list(100)
    if not sites:
        # Seed default
        s = {"id": _uid("SITE"), "name": "Headquarters", "city": "Sydney", "active": True,
             "createdAt": _now(), "businessId": business_id}
        await db.sites.insert_one(s)
        s.pop("_id", None)
        sites = [s]
    return sites


@router.post("/sites")
async def create_site(data: dict, user: dict = Depends(get_user)):
    if user["role"] != "owner": raise HTTPException(status_code=403, detail="Owner only")
    site = {"id": _uid("SITE"), "name": data.get("name", "New Site"), "city": data.get("city", ""),
            "active": True, "createdAt": _now(), "businessId": user.get("businessId")}
    await db.sites.insert_one(site); site.pop("_id", None)
    return site


@router.post("/sites/publish")
async def publish_to_sites(data: dict, user: dict = Depends(get_user)):
    """Push a menu/pricing/promo bundle to selected sites with rollback support."""
    if user["role"] != "owner": raise HTTPException(status_code=403, detail="Owner only")
    publish = {
        "id": _uid("PUB"), "siteIds": data.get("siteIds", []),
        "bundle": data.get("bundle", {}), "publishedBy": user["id"],
        "publishedAt": _now(), "rolledBack": False, "businessId": user.get("businessId"),
    }
    await db.publications.insert_one(publish); publish.pop("_id", None)
    return publish


@router.post("/sites/rollback/{pub_id}")
async def rollback_publish(pub_id: str, user: dict = Depends(get_user)):
    if user["role"] != "owner": raise HTTPException(status_code=403, detail="Owner only")
    guard = await db.publications.find_one({"$and": [{"id": pub_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "id": 1, "businessId": 1})
    if guard is None or not tenant_owns_strict(guard.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Publication not found")
    r = await db.publications.update_one({"$and": [{"id": pub_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": {"rolledBack": True, "rolledBackAt": _now()}})
    if r.matched_count == 0: raise HTTPException(status_code=404, detail="Publication not found")
    return {"rolledBack": True, "id": pub_id}


# ============================================================================
# v25 MUST-HAVE — Hardware Health
# ============================================================================
@router.get("/hardware")
async def hardware_status(user: dict = Depends(get_user)):
    business_id = user.get("businessId")
    devices = await db.hardware.find(tenant_scope_filter(business_id), {"_id": 0}).to_list(200)
    if not devices:
        # Seed a baseline fleet so the UI has something to show
        seed = [
            {"id": _uid("PRN"), "kind": "printer", "name": "Kitchen printer", "status": "online", "lastSeen": _now(), "businessId": business_id},
            {"id": _uid("PRN"), "kind": "printer", "name": "Receipt printer", "status": "online", "lastSeen": _now(), "businessId": business_id},
            {"id": _uid("TERM"), "kind": "terminal", "name": "Front counter", "status": "online", "lastSeen": _now(), "businessId": business_id},
            {"id": _uid("SCN"), "kind": "scanner", "name": "Barcode scanner", "status": "online", "lastSeen": _now(), "businessId": business_id},
        ]
        for d in seed: await db.hardware.insert_one(d)
        for d in seed: d.pop("_id", None)
        devices = seed
    return devices


@router.post("/hardware/heartbeat")
async def hardware_heartbeat(data: dict, request: Request):
    """Devices ping in with a shared secret header `X-Device-Secret`.

    KNOWN GAP (documented, not fixed here): this secret is one single value
    shared by every device on the whole deployment (env
    DEVICE_HEARTBEAT_SECRET, default "nua-device-2026"), not a per-device
    credential like temperature.py's real sensors use. Any device that
    knows it can heartbeat any hardware id, including another business's.
    Closing that needs a real per-device provisioning/secret scheme, not a
    mechanical scoping fix — out of scope for this pass. As a partial
    mitigation: an existing device's businessId is never overwritten by a
    heartbeat, so once a device is correctly tagged (e.g. by site
    provisioning) a heartbeat can't reassign it to a different business.
    """
    secret = request.headers.get("X-Device-Secret")
    expected = os.environ.get("DEVICE_HEARTBEAT_SECRET", "nua-device-2026")
    if secret != expected:
        raise HTTPException(status_code=401, detail="Invalid device secret")
    dev_id = data.get("id")
    if not dev_id: raise HTTPException(status_code=400, detail="id required")
    update = {"status": data.get("status", "online"), "lastSeen": _now(),
              "errors": data.get("errors", [])}
    existing = await db.hardware.find_one({"id": dev_id}, {"_id": 0, "id": 1})
    if existing is None and data.get("businessId"):
        update["businessId"] = data.get("businessId")
    await db.hardware.update_one({"id": dev_id}, {"$set": update}, upsert=True)
    return {"recorded": True}


# ============================================================================
# v25 MUST-HAVE — Chargebacks/Disputes Console
# ============================================================================
@router.get("/disputes")
async def list_disputes(user: dict = Depends(get_user)):
    if user["role"] not in ("owner", "manager"): raise HTTPException(status_code=403, detail="Owner/Manager only")
    rows = await db.disputes.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}) \
        .sort("openedAt", -1).to_list(200)
    return rows


@router.post("/disputes")
async def open_dispute(data: dict, user: dict = Depends(get_user)):
    if user["role"] not in ("owner", "manager"): raise HTTPException(status_code=403, detail="Owner/Manager only")
    business_id = user.get("businessId")
    tx_id = data.get("txId")
    if tx_id:
        tx_guard = await db.transactions.find_one({"$and": [{"id": tx_id}, tenant_scope_filter(business_id)]}, {"_id": 0, "id": 1, "businessId": 1})
        if tx_guard is None or not tenant_owns_strict(tx_guard.get("businessId"), business_id):
            raise HTTPException(status_code=404, detail="Transaction not found")
    d = {
        "id": _uid("DSP"), "txId": tx_id, "amount": float(data.get("amount", 0) or 0),
        "reason": data.get("reason", "fraud"), "status": "open",
        "evidence": data.get("evidence", []), "openedAt": _now(), "openedBy": user["id"],
        "businessId": business_id,
    }
    await db.disputes.insert_one(d); d.pop("_id", None)
    return d


@router.post("/disputes/{dispute_id}/evidence")
async def attach_evidence(dispute_id: str, data: dict, user: dict = Depends(get_user)):
    """Auto-assemble an evidence pack: transaction details + items + signature + IP."""
    if user["role"] not in ("owner", "manager"): raise HTTPException(status_code=403, detail="Owner/Manager only")
    business_id = user.get("businessId")
    d = await db.disputes.find_one({"$and": [{"id": dispute_id}, tenant_scope_filter(business_id)]}, {"_id": 0})
    if d is None or not tenant_owns_strict(d.get("businessId"), business_id):
        raise HTTPException(status_code=404, detail="Not found")
    tx = await db.transactions.find_one({"$and": [{"id": d.get("txId")}, tenant_scope_filter(business_id)]}, {"_id": 0})
    if tx is not None and not tenant_owns_strict(tx.get("businessId"), business_id):
        tx = None
    evidence = {
        "transactionSnapshot": tx or {},
        "addedNotes": data.get("notes", ""),
        "assembledAt": _now(),
        "assembledBy": user["id"],
    }
    await db.disputes.update_one({"$and": [{"id": dispute_id}, tenant_scope_filter(business_id)]}, {"$push": {"evidence": evidence}, "$set": {"status": "evidence_submitted"}})
    return {"updated": True, "evidence": evidence}


# ============================================================================
# v25 MUST-HAVE — Supplier Marketplace
# ============================================================================
@router.get("/suppliers/compare")
async def compare_suppliers(item: str = "", user: dict = Depends(require_owner_or_manager)):
    """Compare quotes per ingredient across suppliers."""
    scope = tenant_scope_filter(user.get("businessId"))
    q = scope if not item else {"$and": [scope, {"item": {"$regex": item, "$options": "i"}}]}
    quotes = await db.supplier_quotes.find(q, {"_id": 0}).to_list(500)
    # Group by item, sort by price
    by_item = defaultdict(list)
    for q in quotes: by_item[q.get("item", "?")].append(q)
    comparisons = []
    for it, qs in by_item.items():
        qs.sort(key=lambda x: float(x.get("pricePerUnit", 99999)))
        if len(qs) >= 2:
            cheapest, current = qs[0], qs[-1]
            savings = (float(current.get("pricePerUnit", 0)) - float(cheapest.get("pricePerUnit", 0))) * float(current.get("annualVolume", 1))
            comparisons.append({"item": it, "quotes": qs, "cheapest": cheapest["supplier"],
                                "annualSavings": round(savings, 2)})
        else:
            comparisons.append({"item": it, "quotes": qs, "annualSavings": 0})
    return comparisons


@router.post("/suppliers/quote")
async def add_quote(data: dict, user: dict = Depends(get_user)):
    if user["role"] not in ("owner", "manager"): raise HTTPException(status_code=403, detail="Owner/Manager only")
    q = {"id": _uid("QTE"), **data, "createdAt": _now(), "createdBy": user["id"],
         "businessId": user.get("businessId")}
    await db.supplier_quotes.insert_one(q); q.pop("_id", None)
    return q


# ============================================================================
# v27 SHOULD-HAVE — Kiosk session
# ============================================================================
@router.post("/kiosk/session")
async def kiosk_start(data: dict, user: Optional[dict] = Depends(optional_user)):
    from routes.online_orders import resolve_or_require_business_id
    business_id = user["businessId"] if user else await resolve_or_require_business_id(data.get("business"))
    from services.retention import kiosk_session_expiry
    s = {"id": "KSK-" + uuid.uuid4().hex, "businessId": business_id, "tableId": data.get("tableId"), "guests": int(data.get("guests", 1)),
         "cart": [], "status": "active", "startedAt": _now(),
         "expiresAt": kiosk_session_expiry()}
    await db.kiosk_sessions.insert_one(s); s.pop("_id", None)
    return s


@router.post("/kiosk/session/{sid}/add")
async def kiosk_add(sid: str, data: dict):
    # The kiosk client wraps the item as {"item": {...}}; accept a flat body
    # too so a direct API caller (or a future client) can't silently push an
    # empty line.
    item = data.get("item") if isinstance(data.get("item"), dict) else data
    item = {k: v for k, v in (item or {}).items() if k != "item"}
    if not item:
        raise HTTPException(status_code=400, detail="No item supplied")
    session = await db.kiosk_sessions.find_one({"id": sid, "status": "active", "_ownershipQuarantined": {"$ne": True}}, {"_id": 0})
    if not session or not session.get("businessId"):
        raise HTTPException(status_code=404, detail="Session not found")
    product = await db.products.find_one({"id": item.get("productId") or item.get("id"),
                                          **tenant_scope_filter(session["businessId"])}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    try:
        quantity = int(item.get("quantity", 1))
        if quantity < 1 or quantity > 100:
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Quantity must be between 1 and 100")
    item.update({"productId": product["id"], "productName": product["name"],
                 "price": product["price"], "quantity": quantity, "category": product.get("category")})
    await db.kiosk_sessions.update_one({"id": sid, "_ownershipQuarantined": {"$ne": True}}, {"$push": {"cart": item}})
    return {"added": True, "item": item}


@router.post("/kiosk/session/{sid}/course")
async def kiosk_set_course(sid: str, data: dict):
    """Move one kiosk cart line to a different course.

    The ticket is built from the stored cart, so a guest's choice has to land
    here — changing it only on their screen would be a lie the kitchen never
    hears about.
    """
    line_id = data.get("lineId")
    try:
        course = int(data.get("course"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="A numeric course is required")
    s = await db.kiosk_sessions.find_one({"id": sid, "_ownershipQuarantined": {"$ne": True}}, {"_id": 0})
    if not s or not s.get("businessId"):
        raise HTTPException(status_code=404, detail="Session not found")
    cart = list(s.get("cart") or [])
    hit = False
    for i, line in enumerate(cart):
        if line.get("lineId") == line_id or (not line_id and i == data.get("index")):
            cart[i] = {**line, "course": course}
            hit = True
            break
    if not hit:
        raise HTTPException(status_code=404, detail="Cart line not found")
    await db.kiosk_sessions.update_one({"id": sid, "_ownershipQuarantined": {"$ne": True}}, {"$set": {"cart": cart}})
    return {"ok": True, "cart": cart}


@router.post("/kiosk/session/{sid}/checkout")
async def kiosk_checkout(sid: str):
    s = await db.kiosk_sessions.find_one({"id": sid, "_ownershipQuarantined": {"$ne": True}}, {"_id": 0})
    if not s or not s.get("businessId"): raise HTTPException(status_code=404, detail="Session not found")
    cart = s.get("cart") or []
    # No loyalty-tier discount here either — same structural reason as
    # routes/online_orders.py's place_order: a kiosk session only ever
    # carries guestName (freeform), never a resolved customerId, so there is
    # no membershipTier to discount against. See
    # tests/inprocess/test_loyalty_tier_discount_channel_consistency.py.
    total = sum(float(i.get("price", 0) or 0) * int(i.get("quantity", 1) or 1) for i in cart)

    # Checkout used to write a total and stop, so kiosk food never reached the
    # kitchen at all. It's a real order — it goes to the pass like any other.
    ticket = None
    try:
        from services import channel_orders
        ticket = await channel_orders.create_ticket(
            cart,
            order_type="dine_in" if s.get("tableId") else "takeaway",
            table_number=s.get("tableNumber"),
            source="kiosk", external_id=sid, actor="Kiosk",
            guest_name=s.get("guestName"), business_id=s.get("businessId"),
        )
    except Exception as e:
        logging.getLogger(__name__).warning("kiosk checkout: kitchen ticket failed — %s", e)

    await db.kiosk_sessions.update_one({"id": sid, "_ownershipQuarantined": {"$ne": True}}, {"$set": {
        "status": "checkout", "total": round(total, 2), "checkoutAt": _now(),
        "kitchenOrderId": (ticket or {}).get("id"),
    }})
    return {"sessionId": sid, "total": round(total, 2), "items": len(cart),
            "kitchenOrderId": (ticket or {}).get("id"),
            "courses": (ticket or {}).get("courses") or {}}


@router.get("/kiosk/sessions")
async def kiosk_list(user: dict = Depends(get_user)):
    """KNOWN GAP (documented, not fully fixed here): kiosk sessions are
    created by an unattended, unauthenticated kiosk device (kiosk_start
    above) that has no reliable signal to resolve which business a table
    belongs to — same architectural gap as table_ordering.py and
    public.py's booking portal (see TENANT_ISOLATION_REMAINING_WORK.md).
    Scoped here for defense-in-depth so a session that IS tagged (once a
    real tableId->business resolution exists) is correctly isolated, but
    today's untagged sessions remain visible to every business's staff via
    tenant_scope_filter's safe default."""
    rows = await db.kiosk_sessions.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}) \
        .sort("startedAt", -1).to_list(50)
    return rows


@router.post("/kiosk/session/{sid}/upsell")
async def kiosk_upsell(sid: str):
    """Pure-data upsell suggestions for a kiosk session — picks complementary
    items the cart is missing (drink if only food, side if only main, etc.)."""
    s = await db.kiosk_sessions.find_one({"id": sid, "_ownershipQuarantined": {"$ne": True}}, {"_id": 0})
    if not s or not s.get("businessId"): raise HTTPException(status_code=404, detail="Session not found")
    cart = s.get("cart", [])
    cats_in_cart = {(i.get("category") or "").lower() for i in cart}
    suggestions = []
    targets = []
    if not any(c in cats_in_cart for c in ("beverages", "coffee", "drink", "drinks")):
        targets.append(("Coffee", "Add a drink to round out the meal"))
        targets.append(("Beverages", "Pair with a refreshing beverage"))
    if any(c in cats_in_cart for c in ("burgers", "mains")) and not any(c in cats_in_cart for c in ("cakes & slices", "desserts")):
        targets.append(("Cakes & Slices", "Save room for something sweet"))
    if any(c in cats_in_cart for c in ("coffee", "beverages")) and not any(c in cats_in_cart for c in ("bakery", "muffins and pastry", "cakes & slices")):
        targets.append(("Bakery", "Goes great with coffee"))
        targets.append(("Muffins and Pastry", "Treat yourself"))
    for cat, reason in targets:
        prod = await db.products.find_one(
            {"category": cat, "stock": {"$gt": 0}}, {"_id": 0}, sort=[("price", 1)])
        if prod and not any(i.get("id") == prod["id"] for i in cart):
            suggestions.append({
                "productId": prod["id"], "name": prod["name"], "price": prod["price"],
                "image": prod.get("image"), "reason": reason,
            })
        if len(suggestions) >= 3: break
    return {"sessionId": sid, "suggestions": suggestions}


# ============================================================================
# v27 SHOULD-HAVE — Customer-Facing Display
# ============================================================================
@router.get("/cfd/current")
async def cfd_current():
    """Returns the latest open POS tab/cart so a CFD screen can mirror it."""
    tab = await db.pos_tabs.find_one({"status": {"$in": ["open", "active", None]}}, {"_id": 0}, sort=[("createdAt", -1)])
    return {"cart": (tab or {}).get("cart", []), "customer": (tab or {}).get("selectedCustomer"), "updatedAt": _now()}


# ============================================================================
# v27 SHOULD-HAVE — Smart Substitution / 86 fallback
# ============================================================================
@router.post("/substitute")
async def substitute(data: dict):
    """Given an 86'd product, suggest the best substitute with a human-readable
    reason per pick. Ranked by (1) modifier overlap, (2) price proximity, (3) stock.

    Public/no-auth — same as the kiosk's other endpoints (kiosk_start,
    kiosk_add, kiosk_upsell above), because the kiosk itself is unattended
    and never carries a staff credential. This never had a frontend caller
    at all before (kiosk or otherwise), which is why it still required
    Depends(get_user): nothing had ever tried to call it as a guest and hit
    the 401. Trade fields (cost/stock/sku) are stripped from every returned
    product the same way the public storefront strips them — a guest-facing
    caller must never see what a dish costs the business."""
    pid = data.get("productId")
    if not pid: raise HTTPException(status_code=400, detail="productId required")
    target = await db.products.find_one({"id": pid}, {"_id": 0})
    if not target: raise HTTPException(status_code=404, detail="Product not found")
    same_cat = await db.products.find(
        {"category": target.get("category"), "active": {"$ne": False},
         "stock": {"$gt": 0}, "id": {"$ne": pid}},
        {"_id": 0}
    ).to_list(50)
    base = float(target.get("price", 0))
    def _score(p):
        # Lower = better
        price_gap = abs(float(p.get("price", 0)) - base)
        stock_bonus = 0 if p.get("stock", 0) > 10 else 2
        return price_gap + stock_bonus
    same_cat.sort(key=_score)
    top = []
    for p in same_cat[:3]:
        diff = float(p.get("price", 0)) - base
        if abs(diff) < 0.5:
            reason = "Same price · same category"
        elif diff < 0:
            reason = f"${abs(diff):.2f} cheaper · in stock"
        else:
            reason = f"${diff:.2f} upgrade · plenty in stock"
        top.append({**p, "substitutionReason": reason})
    for f in GUEST_HIDDEN_PRODUCT_FIELDS:
        target.pop(f, None)
        for p in top:
            p.pop(f, None)
    return {"original": target, "substitutes": top}


@router.post("/products/{product_id}/86")
async def toggle_86(product_id: str, data: dict, user: dict = Depends(get_user)):
    """Toggle 86 (out-of-stock flag) for a product. Sets stock=0 and active=False
    when 86'd; restores active=True (preserves stock as-is) when un-86'd. Returns
    one recommended substitute so the cashier can offer it on the spot."""
    if user["role"] not in ("owner", "manager", "kitchen"):
        raise HTTPException(status_code=403, detail="Owner/Manager/Kitchen only")
    guard = await db.products.find_one({"$and": [{"id": product_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "id": 1, "businessId": 1})
    if guard is None or not tenant_owns_strict(guard.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Product not found")
    flag = bool(data.get("eightySixed", True))
    update = {"eightySixed": flag, "eightySixedAt": _now() if flag else None,
              "eightySixedBy": user["id"] if flag else None}
    if flag:
        update["stock"] = 0
    r = await db.products.update_one({"$and": [{"id": product_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": update})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")
    sub = None
    if flag:
        try:
            # substitute() takes a single `data` dict — it was previously
            # called with a second (Request) argument it doesn't accept,
            # which raised a TypeError on every call, silently swallowed
            # by this try/except, so suggestedSubstitute was always None.
            res = await substitute({"productId": product_id})
            sub = (res.get("substitutes") or [None])[0]
        except Exception:
            sub = None
    return {"eightySixed": flag, "productId": product_id, "suggestedSubstitute": sub}


# ============================================================================
# v27 SHOULD-HAVE — Guest Recovery automation
# ============================================================================
@router.get("/recovery/churn-risk")
async def churn_risk(user: dict = Depends(get_user)):
    if user["role"] not in ("owner", "manager"): raise HTTPException(status_code=403, detail="Owner/Manager only")
    # Customer hasn't visited in 30+ days but visited 3+ times historically
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    customers = await db.customers.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}).to_list(2000)
    at_risk = []
    for c in customers:
        last = c.get("lastVisit") or c.get("lastSeen")
        visits = int(c.get("visits", 0) or c.get("totalVisits", 0) or 0)
        if visits >= 3 and last and last < cutoff:
            at_risk.append({"id": c["id"], "name": c.get("name"), "visits": visits, "lastSeen": last, "tier": c.get("membershipTier")})
    return {"atRisk": at_risk[:100]}


@router.post("/recovery/win-back")
async def trigger_win_back(data: dict, user: dict = Depends(get_user)):
    if user["role"] not in ("owner", "manager"): raise HTTPException(status_code=403, detail="Owner/Manager only")
    business_id = user.get("businessId")
    cids = data.get("customerIds", [])
    voucher_value = float(data.get("voucherValue", 15))
    # Only ever issue vouchers to the caller's own customers — a raw
    # customerIds list from the client must not be trusted to belong to
    # this business.
    owned_cids = []
    for cid in cids:
        c_guard = await cast(Any, db.customers).find_one({**tenant_scope_filter(user.get("businessId")), "id": cid}, {"_id": 0, "id": 1, "businessId": 1})
        if c_guard is not None and tenant_owns(c_guard.get("businessId"), business_id):
            owned_cids.append(cid)
    campaign = {"id": _uid("RCV"), "customerIds": owned_cids, "voucherValue": voucher_value,
                "status": "queued", "createdAt": _now(), "createdBy": user["id"],
                "businessId": business_id}
    await db.recovery_campaigns.insert_one(campaign)
    for cid in owned_cids:
        await db.vouchers.insert_one({"id": _uid("VCH"), "customerId": cid, "amount": voucher_value,
                                       "reason": "win_back", "status": "active", "createdAt": _now(),
                                       "businessId": business_id})
    campaign.pop("_id", None)
    return {"queued": len(owned_cids), "campaign": campaign}


# ============================================================================
# v28 SHOULD-HAVE — Station Readiness Score
# ============================================================================
@router.get("/station-readiness")
async def station_readiness(user: dict = Depends(get_user)):
    # Combine: open prep tickets (lower=better), staff rostered, stock OK, printer status
    scope = tenant_scope_filter(user.get("businessId"))
    pending = await db.kitchen_orders.count_documents({**scope, "status": {"$in": ["pending", "in_progress"]}})
    today = datetime.now(timezone.utc).date().isoformat()
    shifts_today = await db.roster_shifts.count_documents({**scope, "date": today})
    low_stock = await db.products.count_documents({**scope, "stock": {"$lte": 5}, "active": {"$ne": False}})
    printers_online = await db.hardware.count_documents({**scope, "kind": "printer", "status": "online"})
    printers_total = await db.hardware.count_documents({**scope, "kind": "printer"})
    # Score 0-100
    score = 100
    score -= min(pending * 2, 30)
    if shifts_today == 0: score -= 25
    score -= min(low_stock * 2, 20)
    if printers_total > 0 and printers_online < printers_total: score -= 20
    score = max(0, score)
    return {
        "score": score,
        "factors": {
            "pendingTickets": pending, "shiftsToday": shifts_today,
            "lowStockItems": low_stock,
            "printers": f"{printers_online}/{printers_total}" if printers_total else "n/a",
        },
        "status": "ready" if score >= 80 else "watch" if score >= 50 else "at_risk",
    }


# ============================================================================
# v28 SHOULD-HAVE — Menu Margin Guardrails
# ============================================================================
@router.get("/margin-guardrails")
async def margin_guardrails(user: dict = Depends(get_user)):
    if user["role"] not in ("owner", "manager"): raise HTTPException(status_code=403, detail="Owner/Manager only")
    scope = tenant_scope_filter(user.get("businessId"))
    products = await db.products.find({**scope, "active": {"$ne": False}}, {"_id": 0}).to_list(500)
    warnings = []
    for p in products:
        price = float(p.get("price", 0) or 0)
        cost = float(p.get("cost", 0) or 0)
        if price <= 0: continue
        margin_pct = (price - cost) / price * 100
        if margin_pct < 50:
            warnings.append({"productId": p["id"], "name": p["name"], "marginPct": round(margin_pct, 1),
                             "price": price, "cost": cost,
                             "severity": "critical" if margin_pct < 30 else "warning"})
    warnings.sort(key=lambda x: x["marginPct"])
    return {"warnings": warnings[:50]}


# ============================================================================
# TIER 1 — NUA Pro: AI General Manager (executes plans on approval)
# ============================================================================
@router.get("/ash-pro/plan")
async def ash_plan(user: dict = Depends(get_user)):
    """Aggregate today's signals into a single approval plan."""
    if user["role"] not in ("owner", "manager"): raise HTTPException(status_code=403, detail="Owner/Manager only")
    business_id = user.get("businessId")
    scope = tenant_scope_filter(business_id)
    # Gather signals
    now = datetime.now(timezone.utc)
    yesterday = (now - timedelta(days=1)).isoformat()
    today_tx = await db.transactions.count_documents({**scope, "createdAt": {"$gte": yesterday}})
    bookings_today = await db.reservations.count_documents({**scope, "date": now.date().isoformat()})
    bookings_yest = await db.reservations.count_documents({**scope, "date": (now.date() - timedelta(days=7)).isoformat()})
    booking_delta = ((bookings_today - bookings_yest) / max(bookings_yest, 1)) * 100
    low_stock = await db.products.count_documents({**scope, "stock": {"$lte": 5}, "active": {"$ne": False}})
    # Build plan
    actions = []
    if booking_delta < -20:
        actions.append({"id": _uid("ACT"), "type": "send_sms_vips", "summary": f"Send win-back SMS to VIPs (bookings ↓ {abs(booking_delta):.0f}%)",
                        "impact": "+8-12 bookings", "params": {"audience": "VIP", "template": "comeback"}})
        actions.append({"id": _uid("ACT"), "type": "activate_promo", "summary": "Activate 10% lunch offer",
                        "impact": "+$420 revenue", "params": {"discountPct": 10, "window": "lunch"}})
    if low_stock >= 3:
        actions.append({"id": _uid("ACT"), "type": "generate_pos", "summary": f"Generate POs for {low_stock} low-stock items",
                        "impact": "Avoid stock-outs", "params": {}})
    plan = {
        "id": _uid("ASHP"),
        "createdAt": _now(),
        "planDate": datetime.now(timezone.utc).date().isoformat(),
        "signals": {"todaysTransactions": today_tx, "bookingsToday": bookings_today, "bookingDeltaPct": round(booking_delta, 1), "lowStockItems": low_stock},
        "actions": actions,
        "status": "pending_approval",
        "businessId": business_id,
    }
    # Replace today's existing plan (idempotent — don't grow the collection).
    # Keyed by (planDate, status, businessId): businessId was missing here,
    # so two different businesses' daily plans silently overwrote each other.
    await db.ash_plans.update_one(
        {"planDate": plan["planDate"], "status": "pending_approval", "businessId": business_id},
        {"$set": plan}, upsert=True,
    )
    return plan


@router.post("/ash-pro/approve")
async def ash_approve(data: dict, user: dict = Depends(require_owner)):
    plan_id = data.get("planId")
    approved_action_ids = data.get("actionIds", [])  # empty = approve all
    business_id = user.get("businessId")
    plan = await db.ash_plans.find_one({"$and": [{"id": plan_id}, tenant_scope_filter(business_id)]}, {"_id": 0})
    if plan is None or not tenant_owns_strict(plan.get("businessId"), business_id):
        raise HTTPException(status_code=404, detail="Plan not found")
    executed = []
    for act in plan.get("actions", []):
        if approved_action_ids and act["id"] not in approved_action_ids: continue
        # Execute (stubbed where external services would be involved)
        if act["type"] == "generate_pos":
            try:
                # generate_po expects the real authenticated user dict (it
                # reads user["businessId"]/user["id"] internally) — this
                # previously passed the raw Request object instead, which
                # generate_po was never written to accept.
                from routes.phase_ef import generate_po
                r = await generate_po(user)
                executed.append({**act, "result": r})
            except Exception as e:
                executed.append({**act, "error": str(e)[:120]})
        else:
            await db.agent_decisions.insert_one({
                "id": _uid("AGT"), "actionType": act["type"], "summary": act["summary"],
                "payload": act.get("params", {}), "status": "executed", "createdAt": _now(),
                "businessId": business_id,
            })
            executed.append({**act, "result": {"ok": True}})
    await db.ash_plans.update_one({"$and": [{"id": plan_id}, tenant_scope_filter(business_id)]}, {"$set": {"status": "approved", "executedAt": _now(), "executed": executed}})
    return {"executed": len(executed), "actions": executed}


# ============================================================================
# TIER 1 — Profit Guardian (nightly margin check)
# ============================================================================
@router.get("/profit-guardian")
async def profit_guardian(user: dict = Depends(get_user)):
    if user["role"] not in ("owner", "manager"): raise HTTPException(status_code=403, detail="Owner/Manager only")
    scope = tenant_scope_filter(user.get("businessId"))
    # Compare last-7d cost % vs prior 7-day window for each product
    now = datetime.now(timezone.utc)
    cur_start = (now - timedelta(days=7)).isoformat()
    prev_start = (now - timedelta(days=14)).isoformat()
    cur = await db.transactions.find({**scope, "createdAt": {"$gte": cur_start}}, {"_id": 0, "items": 1}).to_list(5000)
    prev = await db.transactions.find({**scope, "createdAt": {"$gte": prev_start, "$lt": cur_start}}, {"_id": 0, "items": 1}).to_list(5000)
    def aggregate(rows):
        rev, cost, units = defaultdict(float), defaultdict(float), defaultdict(int)
        for t in rows:
            for it in (t.get("items") or []):
                pid = it.get("productId")
                if not pid: continue
                q = int(it.get("quantity", 1) or 1)
                rev[pid] += float(it.get("price", 0) or 0) * q
                units[pid] += q
        return rev, cost, units
    cur_rev, _, cur_units = aggregate(cur)
    prev_rev, _, prev_units = aggregate(prev)
    products = {p["id"]: p for p in await db.products.find(scope, {"_id": 0}).to_list(2000)}
    alerts = []
    for pid in cur_rev:
        p = products.get(pid)
        if not p: continue
        price = float(p.get("price", 0) or 0); cost = float(p.get("cost", 0) or 0)
        if price <= 0: continue
        margin = (price - cost) / price * 100
        cu, pu = cur_units[pid], prev_units.get(pid, 0)
        if margin < 60 and cu >= 5:
            suggested = round(price * 1.05, 2)
            reason = f"Margin {margin:.1f}% sold {cu} last week — bump 5% to lift gross"
            # Heuristic: previously sold N+, now selling much less — surface
            # the decline alongside the margin call, since a thin-margin item
            # that's also losing volume is a worse price-bump candidate (it
            # may need a menu/promo look instead) than one holding steady.
            declining = pu >= 5 and cu < pu * 0.5
            if declining:
                reason += f" (down from {pu} the week before — losing volume, not just margin)"
            alerts.append({"productId": pid, "name": p["name"], "marginPct": round(margin, 1),
                           "price": price, "cost": cost, "suggestedPrice": suggested,
                           "unitsLastWeek": cu, "unitsPriorWeek": pu, "declining": declining,
                           "reason": reason})
    alerts.sort(key=lambda x: x["marginPct"])
    return {"alerts": alerts[:30]}


# ============================================================================
# TIER 1 — Digital Twin Forecast
# ============================================================================
@router.get("/digital-twin")
async def digital_twin(user: dict = Depends(get_user)):
    scope = tenant_scope_filter(user.get("businessId"))
    now = datetime.now(timezone.utc)
    # 8-week average revenue per weekday
    cutoff = (now - timedelta(days=56)).isoformat()
    tx = await db.transactions.find({**scope, "createdAt": {"$gte": cutoff}}, {"_id": 0, "createdAt": 1, "total": 1}).to_list(20000)
    by_dow = defaultdict(list)
    for t in tx:
        try:
            dt = datetime.fromisoformat(t["createdAt"].replace("Z", "+00:00"))
            by_dow[dt.weekday()].append(float(t.get("total", 0) or 0))
        except Exception:
            continue
    today_dow = now.weekday()
    today_avg = sum(by_dow.get(today_dow, [])) / max(len(by_dow.get(today_dow, [])) / 8, 1) if by_dow.get(today_dow) else 0
    bookings = await db.reservations.count_documents({**scope, "date": now.date().isoformat()})
    avg_party = 2.5
    expected_covers = bookings * avg_party
    # Confidence band ±8%
    return {
        "date": now.date().isoformat(),
        "expectedRevenue": round(today_avg, 2),
        "revenueLow": round(today_avg * 0.92, 2),
        "revenueHigh": round(today_avg * 1.08, 2),
        "expectedCovers": int(expected_covers),
        "bookings": bookings,
        "expectedWaitMin": min(45, max(5, int(bookings / 4))),
    }


# ============================================================================
# TIER 1 — AI Shift Manager (real-time alerts)
# ============================================================================
@router.get("/shift-manager")
async def shift_manager(user: dict = Depends(get_user)):
    scope = tenant_scope_filter(user.get("businessId"))
    alerts = []
    # Check kitchen station overload
    pending = await db.kitchen_orders.count_documents({**scope, "status": "pending"})
    if pending > 8:
        alerts.append({"type": "kitchen_overload", "severity": "high",
                       "message": f"Kitchen has {pending} pending tickets — pull a hand from bar/front to expo."})
    # Check oldest ticket
    oldest = await db.kitchen_orders.find_one({**scope, "status": "pending"}, {"_id": 0}, sort=[("createdAt", 1)])
    if oldest:
        try:
            dt = datetime.fromisoformat(oldest["createdAt"].replace("Z", "+00:00"))
            wait = (datetime.now(timezone.utc) - dt).total_seconds() / 60
            if wait > 18:
                alerts.append({"type": "ticket_aging", "severity": "high",
                               "message": f"Oldest ticket {wait:.0f} min old — flag manager."})
        except Exception: pass
    return {"alerts": alerts, "timestamp": _now()}


# ============================================================================
# TIER 1 — Autonomous Marketing Engine
# ============================================================================
@router.post("/marketing/auto")
async def auto_marketing(data: dict, user: dict = Depends(get_user)):
    if user["role"] not in ("owner", "manager"): raise HTTPException(status_code=403, detail="Owner/Manager only")
    scope = tenant_scope_filter(user.get("businessId"))
    audience = data.get("audience", "all")
    target = await db.customers.find(scope if audience == "all" else {**scope, "membershipTier": audience}, {"_id": 0}).to_list(2000)
    sys_msg = ("You are a restaurant CMO. Generate a short 1-line SMS + 50-word email "
               "for a midweek slowdown offer. Return STRICT JSON: "
               '{"sms":"...","emailSubject":"...","emailBody":"..."}')
    out = await _llm_json(f"mkt-{uuid.uuid4().hex[:6]}", sys_msg,
                          f"Audience: {audience}, {len(target)} customers. Day: {datetime.now().strftime('%A')}.")
    campaign = {
        "id": _uid("MKT"), "audience": audience, "recipients": len(target),
        "sms": out.get("sms", "Come back for 15% off this week!") if isinstance(out, dict) else None,
        "emailSubject": out.get("emailSubject", "We miss you") if isinstance(out, dict) else "We miss you",
        "emailBody": out.get("emailBody", "") if isinstance(out, dict) else "",
        # The redeemable side of the offer. Without this a campaign is just
        # ad copy — nothing for the guest to present and nothing the venue
        # can attribute a sale back to.
        "offer": data.get("offer") or {"valueType": "percentage", "value": 15,
                                       "label": "Midweek offer"},
        "status": "draft", "createdAt": _now(), "createdBy": user["id"],
        "sent": 0, "vouchersIssued": 0, "businessId": user.get("businessId"),
    }
    await db.marketing_campaigns.insert_one(campaign); campaign.pop("_id", None)
    return campaign


@router.post("/marketing/auto/{campaign_id}/send")
async def send_marketing(campaign_id: str, data: dict = None, user: dict = Depends(get_user)):
    """Actually send the campaign: issue each targeted customer their own
    voucher (code + scannable QR, saved to their wallet) and email it out.

    Idempotent per customer — re-sending won't mint a second voucher for
    someone who already has one for this campaign, so a retry after a
    partial failure is safe.

    `data` may carry owner edits (emailSubject/emailBody/sms) made in the
    review step before sending — the campaign is updated with them first,
    so Edit-then-Send never needs a separate save endpoint.
    """
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(status_code=403, detail="Owner/Manager only")
    campaign = await db.marketing_campaigns.find_one({"$and": [{"id": campaign_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if campaign is None or not tenant_owns_strict(campaign.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.get("status") == "held":
        raise HTTPException(status_code=400, detail="Campaign is on hold — take it off hold before sending")

    edits = {k: v for k, v in (data or {}).items() if k in ("emailSubject", "emailBody", "sms") and v}
    if edits:
        await db.marketing_campaigns.update_one({"$and": [{"id": campaign_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": edits})
        campaign.update(edits)

    return await _execute_campaign_send(campaign)


async def _execute_campaign_send(campaign: dict) -> dict:
    """The actual send: issue each targeted customer their own voucher and
    email it out. Shared by the review-and-send route above and by the
    Ash-drafted marketing-campaign approval path (routes/approvals.py),
    which used to reference this action type without anything to execute it.

    Idempotent per customer — re-sending won't mint a second voucher for
    someone who already has one for this campaign, so a retry after a
    partial failure is safe.
    """
    campaign_id = campaign["id"]
    from services.campaign_offers import issue_campaign_voucher, render_offer_email
    from utils.notifications import send_email

    audience = campaign.get("audience", "all")
    scope = tenant_scope_filter(campaign.get("businessId"))
    targets = await db.customers.find(
        scope if audience == "all" else {**scope, "membershipTier": audience}, {"_id": 0}
    ).to_list(2000)

    issued, sent, skipped = 0, 0, 0
    recipients = []
    for c in targets:
        if not (c.get("email") or "").strip():
            skipped += 1
            continue
        existing = await db.vouchers.find_one(
            {"customerId": c["id"], "sourceType": "campaign", "sourceRef": campaign_id},
            {"_id": 0},
        )
        voucher = existing or await issue_campaign_voucher(c, campaign)
        if not voucher:
            skipped += 1
            continue
        if not existing:
            issued += 1
        receipt = await send_email(
            c["email"], campaign.get("emailSubject") or "An offer for you",
            render_offer_email(c, campaign, voucher),
        )
        if receipt.get("delivered"):
            sent += 1
        recipients.append({
            "customerId": c["id"], "email": c["email"],
            "voucherId": voucher["id"], "code": voucher["code"],
            "delivered": bool(receipt.get("delivered")),
        })

    await db.marketing_campaigns.update_one({"id": campaign_id}, {"$set": {
        "status": "sent", "sentAt": _now(),
        "vouchersIssued": issued, "sent": sent, "skipped": skipped,
        "recipientLog": recipients[:2000],
    }})
    return {"campaignId": campaign_id, "vouchersIssued": issued,
            "emailsDelivered": sent, "skipped": skipped,
            "recipients": len(recipients)}


async def create_and_send_campaign_from_approval(params: dict, created_by: str = "ash",
                                                   business_id: Optional[str] = None) -> dict:
    """Turn an Ash-drafted marketing-campaign approval into a real, sendable
    v25 campaign and send it immediately — this is what fires when an owner
    clicks Approve on a "marketing.launch_campaign" approval.

    Ash's draft describes its target as a free-text segment expression
    (e.g. "visits>=3 AND lapsed_30d"), which this simpler audience-tier
    system can't evaluate, so it lands as an "all customers" campaign —
    still real and sent, just not narrowed to the exact cohort Ash reasoned
    about. Narrowing that requires the segment engine other parts of this
    codebase already use, which is out of scope for making this action
    execute instead of silently failing.
    """
    copy = params.get("copy") or {}
    campaign = {
        "id": _uid("MKT"), "audience": "all",
        "sms": copy.get("sms"),
        "emailSubject": copy.get("subject") or params.get("name") or "An offer for you",
        "emailBody": copy.get("email") or copy.get("sms") or "",
        "offer": params.get("offer") or {"valueType": "percentage", "value": 10, "label": "Thanks for being a regular"},
        "status": "draft", "createdAt": _now(), "createdBy": created_by,
        "sent": 0, "vouchersIssued": 0, "businessId": business_id,
        "ashDraft": {"segment": params.get("segment"), "reasoning": params.get("reasoning")},
    }
    await db.marketing_campaigns.insert_one(dict(campaign))
    return await _execute_campaign_send(campaign)


@router.post("/marketing/auto/{campaign_id}/hold")
async def hold_marketing(campaign_id: str, data: dict = None, user: dict = Depends(get_user)):
    """Owner intervention: put a drafted campaign on hold (or take it off
    hold) instead of it just sitting there ambiguously as an untouched
    draft. A held campaign can't be sent until it's taken off hold again."""
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(status_code=403, detail="Owner/Manager only")
    campaign = await db.marketing_campaigns.find_one({"$and": [{"id": campaign_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if campaign is None or not tenant_owns_strict(campaign.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.get("status") == "sent":
        raise HTTPException(status_code=400, detail="Campaign already sent")
    hold = (data or {}).get("hold", True)
    new_status = "held" if hold else "draft"
    await db.marketing_campaigns.update_one({"$and": [{"id": campaign_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": {"status": new_status}})
    return {"campaignId": campaign_id, "status": new_status}


@router.get("/marketing/auto/{campaign_id}/performance")
async def marketing_performance(campaign_id: str, user: dict = Depends(get_user)):
    """Redemption attribution — which issued vouchers actually came back."""
    campaign = await db.marketing_campaigns.find_one({"$and": [{"id": campaign_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "id": 1, "businessId": 1})
    if campaign is None or not tenant_owns_strict(campaign.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Campaign not found")
    vouchers = await db.vouchers.find(
        {"sourceType": "campaign", "sourceRef": campaign_id}, {"_id": 0}
    ).to_list(5000)
    redeemed = [v for v in vouchers if v.get("status") == "redeemed"
                or int(v.get("redemptionCount") or 0) > 0]
    issued = len(vouchers)
    return {
        "campaignId": campaign_id,
        "issued": issued,
        "redeemed": len(redeemed),
        "redemptionRate": round(len(redeemed) / issued * 100, 1) if issued else 0.0,
    }


@router.get("/marketing/auto")
async def list_marketing(user: dict = Depends(get_user)):
    rows = await db.marketing_campaigns.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}) \
        .sort("createdAt", -1).to_list(50)
    return rows


# ============================================================================
# TIER 2 — Dynamic Pricing rules
# ============================================================================
@router.get("/dynamic-pricing")
async def list_dynamic_rules(user: dict = Depends(get_user)):
    rules = await db.dynamic_pricing.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}).to_list(200)
    return rules


@router.post("/dynamic-pricing")
async def add_dynamic_rule(data: dict, user: dict = Depends(get_user)):
    if user["role"] != "owner": raise HTTPException(status_code=403, detail="Owner only")
    rule = {
        "id": _uid("DPR"),
        "productId": data.get("productId"),  # null = applies to all in category
        "category": data.get("category"),
        "dow": data.get("dow"),                # 0-6, null = any
        "hourStart": int(data.get("hourStart", 0)),
        "hourEnd": int(data.get("hourEnd", 24)),
        "multiplier": float(data.get("multiplier", 1.0)),
        "active": True, "createdAt": _now(), "businessId": user.get("businessId"),
    }
    await db.dynamic_pricing.insert_one(rule); rule.pop("_id", None)
    return rule


# ============================================================================
# TIER 2 — Subscription Memberships
# ============================================================================
@router.get("/subscriptions/plans")
async def list_sub_plans(user: dict = Depends(get_user)):
    business_id = user.get("businessId")
    plans = await db.subscription_plans.find(tenant_scope_filter(business_id), {"_id": 0}).to_list(50)
    if not plans:
        seed = [{"id": _uid("SUB"), "name": "Coffee Club", "priceMonthly": 29,
                 "perks": ["1 free coffee daily", "10% off food", "Priority booking"],
                 "businessId": business_id}]
        for s in seed: await db.subscription_plans.insert_one(s)
        for s in seed: s.pop("_id", None)
        plans = seed
    return plans


@router.post("/subscriptions/plans")
async def add_sub_plan(data: dict, user: dict = Depends(get_user)):
    if user["role"] != "owner": raise HTTPException(status_code=403, detail="Owner only")
    # Mint scannable barcode + manual code so the membership can be scanned at POS.
    import secrets as _secrets
    raw = _secrets.token_hex(4).upper()
    manual = f"SUB-{raw[:4]}-{raw[4:]}"
    plan = {
        "id": _uid("SUB"),
        "name": data.get("name", "Membership"),
        "priceMonthly": float(data.get("priceMonthly", 0)),
        "priceAnnual": float(data.get("priceAnnual", 0)),
        "perks": data.get("perks", []),
        "inclusions": data.get("inclusions", []),               # [{item, quantity, period}]
        "termsAndConditions": data.get("termsAndConditions", ""),
        "trialDays": int(data.get("trialDays", 0)),
        "manualCode": manual, "barcode": manual,
        "active": bool(data.get("active", True)),
        "createdAt": _now(), "businessId": user.get("businessId"),
    }
    await db.subscription_plans.insert_one(plan); plan.pop("_id", None)
    return plan


@router.post("/subscriptions/enroll")
async def enroll_sub(data: dict, user: dict = Depends(get_user)):
    business_id = user.get("businessId")
    plan_id = data.get("planId")
    plan_guard = await db.subscription_plans.find_one({"$and": [{"id": plan_id}, tenant_scope_filter(business_id)]}, {"_id": 0, "id": 1, "businessId": 1})
    if plan_guard is None or not tenant_owns_strict(plan_guard.get("businessId"), business_id):
        raise HTTPException(status_code=404, detail="planId does not exist")
    sub = {"id": _uid("SUBSC"), "customerId": data.get("customerId"), "planId": plan_id,
           "status": "active", "startedAt": _now(), "businessId": business_id}
    await db.subscriptions.insert_one(sub); sub.pop("_id", None)
    return sub


@router.get("/subscriptions/members")
async def list_sub_members(user: dict = Depends(get_user)):
    rows = await db.subscriptions.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}).to_list(500)
    return rows


@router.patch("/subscriptions/members/{sub_id}")
async def update_sub_member(sub_id: str, data: dict, user: dict = Depends(get_user)):
    """Owner can switch a member's plan, status (active|paused|cancelled) or
    notes. Validates the new planId actually exists when present."""
    if user["role"] != "owner":
        raise HTTPException(status_code=403, detail="Owner only")
    business_id = user.get("businessId")
    guard = await db.subscriptions.find_one({"$and": [{"id": sub_id}, tenant_scope_filter(business_id)]}, {"_id": 0, "id": 1, "businessId": 1})
    if guard is None or not tenant_owns_strict(guard.get("businessId"), business_id):
        raise HTTPException(status_code=404, detail="Membership not found")
    allowed = {"planId", "status", "notes", "customerId"}
    update = {k: v for k, v in data.items() if k in allowed}
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    if "status" in update and update["status"] not in ("active", "paused", "cancelled"):
        raise HTTPException(status_code=400, detail="status must be active | paused | cancelled")
    if "planId" in update:
        plan_guard = await db.subscription_plans.find_one(
            {"$and": [{"id": update["planId"]}, tenant_scope_filter(business_id)]}, {"_id": 0, "id": 1, "businessId": 1})
        if plan_guard is None or not tenant_owns_strict(plan_guard.get("businessId"), business_id):
            raise HTTPException(status_code=404, detail="planId does not exist")
    update["updatedAt"] = _now()
    r = await db.subscriptions.update_one({"$and": [{"id": sub_id}, tenant_scope_filter(business_id)]}, {"$set": update})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Membership not found")
    row = await db.subscriptions.find_one({"$and": [{"id": sub_id}, tenant_scope_filter(business_id)]}, {"_id": 0})
    return row


@router.delete("/subscriptions/members/{sub_id}")
async def cancel_sub_member(sub_id: str, user: dict = Depends(get_user)):
    """Soft-cancel — flips status to 'cancelled' and stamps cancelledAt.
    Keeps the row for audit so the next renewal/billing run can ignore it."""
    if user["role"] != "owner":
        raise HTTPException(status_code=403, detail="Owner only")
    guard = await db.subscriptions.find_one({"$and": [{"id": sub_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "id": 1, "businessId": 1})
    if guard is None or not tenant_owns_strict(guard.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Membership not found")
    r = await db.subscriptions.update_one(
        {"$and": [{"id": sub_id}, tenant_scope_filter(user.get("businessId"))]},
        {"$set": {"status": "cancelled", "cancelledAt": _now()}},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Membership not found")
    return {"cancelled": True}


# Gift cards live under /v26/gift-cards (routes/v26_commerce.py) — that's the
# schema the POS register and the owner's gift-card management page actually
# use. This tier used to duplicate it with a second, incompatible schema
# (decrementing `amount` instead of `currentBalance`) against the *same*
# `gift_cards` collection, which silently desynced balances between the two.
# Removed rather than fixed, since nothing calls it anymore.


# ============================================================================
# TIER 3 — Recipe Costing Engine
# ============================================================================
@router.get("/recipes/list")
async def list_recipes_costed(user: dict = Depends(get_user)):
    recipes = await db.product_recipes.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}).to_list(500)
    return recipes


@router.post("/recipes/upsert")
async def upsert_recipe(data: dict, user: dict = Depends(get_user)):
    """Attach a recipe of ingredients (productId + qty + costPerUnit) to a product."""
    if user["role"] not in ("owner", "manager"): raise HTTPException(status_code=403, detail="Owner/Manager only")
    business_id = user.get("businessId")
    pid = data.get("productId")
    if not pid: raise HTTPException(status_code=400, detail="productId required")
    prod_guard = await db.products.find_one({"$and": [{"id": pid}, tenant_scope_filter(business_id)]}, {"_id": 0, "id": 1, "businessId": 1})
    if prod_guard is None or not tenant_owns_strict(prod_guard.get("businessId"), business_id):
        raise HTTPException(status_code=404, detail="Product not found")
    ingredients = data.get("ingredients", [])  # [{item, quantity, unit, costPerUnit}]
    total_cost = sum(float(i.get("quantity", 0) or 0) * float(i.get("costPerUnit", 0) or 0) for i in ingredients)
    rec = {"productId": pid, "ingredients": ingredients, "computedCost": round(total_cost, 2),
           "updatedAt": _now(), "updatedBy": user["id"], "businessId": business_id}
    await db.product_recipes.update_one({"productId": pid}, {"$set": rec}, upsert=True)
    # Also push the computed cost back to product.cost so margin engines update
    await db.products.update_one({"$and": [{"id": pid}, tenant_scope_filter(business_id)]}, {"$set": {"cost": round(total_cost, 2), "recipeLinked": True}})
    return rec


@router.get("/recipes/{product_id}")
async def get_recipe(product_id: str, user: dict = Depends(get_user)):
    prod_guard = await db.products.find_one({"$and": [{"id": product_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "id": 1, "businessId": 1})
    if prod_guard is None or not tenant_owns_strict(prod_guard.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Product not found")
    r = await db.product_recipes.find_one({"productId": product_id}, {"_id": 0})
    return r or {"productId": product_id, "ingredients": [], "computedCost": 0}


# ============================================================================
# TIER 3 — Predictive Ordering
# ============================================================================
@router.post("/predictive-orders")
async def predictive_orders(user: dict = Depends(get_user)):
    """Generate next-week supplier orders based on velocity + bookings + weather hints."""
    if user["role"] not in ("owner", "manager"): raise HTTPException(status_code=403, detail="Owner/Manager only")
    scope = tenant_scope_filter(user.get("businessId"))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    tx = await db.transactions.find({**scope, "createdAt": {"$gte": cutoff}}, {"_id": 0, "items": 1}).to_list(5000)
    units_per_week = Counter()
    for t in tx:
        for it in t.get("items", []) or []:
            pid = it.get("productId")
            if pid: units_per_week[pid] += int(it.get("quantity", 1) or 1)
    # next week target = 7-day average rounded up
    products = await db.products.find({**scope, "active": {"$ne": False}}, {"_id": 0}).to_list(500)
    suggestions = []
    for p in products:
        weekly = units_per_week.get(p["id"], 0) / 2  # 14d -> 7d
        target = int(weekly * 1.1)  # +10% safety
        current = int(p.get("stock", 0) or 0)
        order_qty = max(target - current, 0)
        if order_qty > 0:
            suggestions.append({"productId": p["id"], "name": p["name"], "supplier": p.get("supplier", "Default"),
                                "currentStock": current, "orderQty": order_qty, "unitCost": p.get("cost", 0)})
    # Group by supplier
    by_supplier = defaultdict(list)
    for s in suggestions: by_supplier[s["supplier"]].append(s)
    return {"suggestions": suggestions, "bySupplier": [{"supplier": k, "items": v, "total": round(sum(i["orderQty"] * float(i["unitCost"]) for i in v), 2)} for k, v in by_supplier.items()]}


# ============================================================================
# TIER 3 — Waste Tracking
# ============================================================================
@router.get("/waste")
async def list_waste(user: dict = Depends(get_user)):
    rows = await db.waste_log.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}) \
        .sort("createdAt", -1).to_list(500)
    return rows


@router.post("/waste")
async def log_waste(data: dict, user: dict = Depends(get_user)):
    entry = {
        "id": _uid("WST"), "productId": data.get("productId"), "productName": data.get("productName", ""),
        "quantity": float(data.get("quantity", 0)), "reason": data.get("reason", "spoilage"),
        "estCost": float(data.get("estCost", 0)),
        "createdAt": _now(), "createdBy": user["id"], "businessId": user.get("businessId"),
    }
    await db.waste_log.insert_one(entry); entry.pop("_id", None)
    return entry


@router.get("/waste/insights")
async def waste_insights(user: dict = Depends(get_user)):
    if user["role"] not in ("owner", "manager"): raise HTTPException(status_code=403, detail="Owner/Manager only")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    query = {"$and": [tenant_scope_filter(user.get("businessId")), {"createdAt": {"$gte": cutoff}}]}
    rows = await db.waste_log.find(query, {"_id": 0}).to_list(2000)
    total_cost = sum(float(r.get("estCost", 0)) for r in rows)
    by_reason = Counter([r.get("reason", "?") for r in rows])
    by_product = Counter([r.get("productName", "?") for r in rows])
    return {"totalCost30d": round(total_cost, 2), "entries": len(rows),
            "byReason": dict(by_reason), "topOffenders": by_product.most_common(10)}


# ============================================================================
# TIER 4 — Universal Guest Profile
# ============================================================================
@router.get("/guest/{customer_id}")
async def universal_guest(customer_id: str, user: dict = Depends(get_user)):
    c = await db.customers.find_one({**tenant_scope_filter(user.get("businessId")), "id": customer_id}, {"_id": 0})
    if c is None or not tenant_owns(c.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Customer not found")
    visits = await db.transactions.count_documents({"customerId": customer_id})
    spend_agg = await db.transactions.aggregate([
        {"$match": {"customerId": customer_id}},
        {"$group": {"_id": None, "total": {"$sum": "$total"}}}
    ]).to_list(1)
    total_spend = float(spend_agg[0]["total"]) if spend_agg else 0
    reservations = await db.reservations.count_documents({"customerId": customer_id})
    points = await db.loyalty_ledger.aggregate([
        {"$match": {"customerId": customer_id}},
        {"$group": {"_id": None, "balance": {"$sum": "$delta"}}}
    ]).to_list(1)
    return {
        "profile": c,
        "stats": {"totalSpend": round(total_spend, 2), "visits": visits, "reservations": reservations,
                  "points": int(points[0]["balance"]) if points else 0},
        "sites": ["Default"],  # placeholder until per-site data exists
    }


# ============================================================================
# TIER 4 — AI Concierge
# ============================================================================
@router.post("/concierge")
async def concierge(data: dict, user: dict = Depends(get_user)):
    msg = (data.get("message") or "").strip()
    if not msg: raise HTTPException(status_code=400, detail="message required")
    sys_msg = (
        "You are a restaurant concierge at NUA. Given a guest request, classify and extract details. "
        "Return STRICT JSON: "
        '{"intent":"reservation|dietary|menu|other","date":"YYYY-MM-DD","time":"HH:MM",'
        '"partySize":6,"name":"...","phone":"... or null","email":"... or null",'
        '"notes":"...","reply":"a friendly 1-2 sentence reply"}'
    )
    out = await _llm_json(f"concierge-{uuid.uuid4().hex[:6]}", sys_msg,
                          f"Today: {datetime.now().date().isoformat()}. Guest: {msg}")
    if isinstance(out, dict) and out.get("intent") == "reservation" and out.get("date"):
        from services.customer_match import find_matching_customer, guest_context
        customer = await find_matching_customer(
            name=out.get("name"), phone=out.get("phone"), email=out.get("email"))
        notes = out.get("notes", msg)
        reply = out.get("reply", "Booking confirmed.")
        if customer:
            # A returning guest was found — carry their history into the
            # reservation instead of booking them as a stranger, and fold
            # anything the profile knows (allergies, VIP status, seating)
            # into the notes so front-of-house sees it without digging.
            notes = f"{notes} [Returning guest — {guest_context(customer)}]".strip()
            if customer.get("isVip"):
                reply = f"Welcome back — {reply}"
        r = {
            "id": _uid("RES"), "guestName": out.get("name") or (customer or {}).get("name") or "Concierge guest",
            "guestPhone": out.get("phone") or (customer or {}).get("phone"),
            "guestEmail": out.get("email") or (customer or {}).get("email"),
            "customerId": (customer or {}).get("id"),
            "partySize": int(out.get("partySize", 2) or 2),
            "date": out["date"], "time": out.get("time", "19:00"),
            "notes": notes, "status": "confirmed", "source": "ai_concierge",
            "createdAt": _now(), "businessId": user.get("businessId"),
        }
        await db.reservations.insert_one(r)
        return {"created": True, "reservationId": r["id"], "reply": reply, "intent": "reservation",
                "matchedCustomer": {"id": customer["id"], "name": customer.get("name"),
                                     "isVip": customer.get("isVip", False)} if customer else None}
    return {"created": False, "intent": (out or {}).get("intent", "other") if isinstance(out, dict) else "other",
            "reply": (out or {}).get("reply", "I'll pass that to a manager.") if isinstance(out, dict) else "Sorry, I couldn't process that."}


# ============================================================================
# TIER 4 — Reputation Command Center
# ============================================================================
@router.get("/reputation")
async def reputation(user: dict = Depends(get_user)):
    if user["role"] not in ("owner", "manager"): raise HTTPException(status_code=403, detail="Owner/Manager only")
    business_id = user.get("businessId")
    reviews = await db.reviews.find(tenant_scope_filter(business_id), {"_id": 0}).sort("createdAt", -1).to_list(500)
    if not reviews:
        # Seed a few samples so the dashboard isn't empty
        seed = [
            {"id": _uid("RV"), "source": "Google", "rating": 5, "author": "Mei L.", "text": "Best espresso in town.", "responded": False, "createdAt": _now(), "businessId": business_id},
            {"id": _uid("RV"), "source": "TripAdvisor", "rating": 2, "author": "Tom", "text": "Service was slow at lunch.", "responded": False, "createdAt": _now(), "businessId": business_id},
        ]
        for r in seed: await db.reviews.insert_one(r)
        for r in seed: r.pop("_id", None)
        reviews = seed
    by_source = defaultdict(list)
    for r in reviews: by_source[r.get("source", "?")].append(r.get("rating", 0))
    avg = sum(r.get("rating", 0) for r in reviews) / max(len(reviews), 1)
    return {
        "avgRating": round(avg, 2), "count": len(reviews),
        "bySource": [{"source": s, "avg": round(sum(rs)/len(rs), 2), "count": len(rs)} for s, rs in by_source.items()],
        "reviews": reviews[:50],
    }


@router.post("/reputation/respond")
async def respond_review(data: dict, user: dict = Depends(get_user)):
    if user["role"] not in ("owner", "manager"): raise HTTPException(status_code=403, detail="Owner/Manager only")
    rid = data.get("reviewId"); response = (data.get("response") or "").strip()
    rev_guard = await db.reviews.find_one({"$and": [{"id": rid}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "id": 1, "businessId": 1})
    if rev_guard is None or not tenant_owns_strict(rev_guard.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Review not found")
    if not response:
        # Ask LLM to draft
        rev = await db.reviews.find_one({"$and": [{"id": rid}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
        if not rev: raise HTTPException(status_code=404, detail="Review not found")
        out = await _llm_json(f"rep-{uuid.uuid4().hex[:6]}",
            "You write warm, professional restaurant review responses (2-3 sentences). Return STRICT JSON: {\"response\":\"...\"}",
            f"Source: {rev.get('source')} · Rating: {rev.get('rating')}/5 · Review: {rev.get('text')}")
        response = out.get("response") if isinstance(out, dict) else "Thank you for your feedback."
    await db.reviews.update_one({"$and": [{"id": rid}, tenant_scope_filter(user.get("businessId"))]}, {"$set": {"responded": True, "response": response, "respondedAt": _now()}})
    return {"updated": True, "response": response}


# ============================================================================
# TIER 4 — Smart Recovery (negative review intercept)
# ============================================================================
@router.post("/recovery-action")
async def recovery_action(data: dict, user: dict = Depends(get_user)):
    if user["role"] not in ("owner", "manager"): raise HTTPException(status_code=403, detail="Owner/Manager only")
    business_id = user.get("businessId")
    customer_id = data.get("customerId")
    c_guard = await cast(Any, db.customers).find_one({**tenant_scope_filter(user.get("businessId")), "id": customer_id}, {"_id": 0, "id": 1, "businessId": 1})
    if c_guard is None or not tenant_owns(c_guard.get("businessId"), business_id):
        raise HTTPException(status_code=404, detail="Customer not found")
    voucher = float(data.get("voucherAmount", 20))
    apology = data.get("apologyMessage", "We're sorry — please come back, on us.")
    rec = {
        "id": _uid("REC"), "customerId": customer_id, "voucher": voucher,
        "apology": apology, "managerFlagged": True, "status": "queued", "createdAt": _now(),
        "businessId": business_id,
    }
    await db.recovery_actions.insert_one(rec)
    await db.vouchers.insert_one({"id": _uid("VCH"), "customerId": customer_id, "amount": voucher,
                                  "reason": "service_recovery", "status": "active", "createdAt": _now(),
                                  "businessId": business_id})
    rec.pop("_id", None)
    return rec


# ============================================================================
# TIER 5 — Franchise Command Center
# ============================================================================
@router.get("/franchise/dashboard")
async def franchise_dashboard(user: dict = Depends(get_user)):
    if user["role"] != "owner": raise HTTPException(status_code=403, detail="Owner only")
    scope = tenant_scope_filter(user.get("businessId"))
    sites = await db.sites.find(scope, {"_id": 0}).to_list(100)
    publications = await db.publications.find(scope, {"_id": 0}).sort("publishedAt", -1).to_list(20)
    return {"sites": sites, "recentPublications": publications}


# ============================================================================
# TIER 5 — Multi-Store Benchmarking
# ============================================================================
@router.get("/benchmark")
async def benchmark(user: dict = Depends(get_user)):
    if user["role"] != "owner": raise HTTPException(status_code=403, detail="Owner only")
    scope = tenant_scope_filter(user.get("businessId"))
    sites = await db.sites.find(scope, {"_id": 0}).to_list(100)
    # Without per-site data we still return a single-site summary so the UI works
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    tx = await db.transactions.find({**scope, "createdAt": {"$gte": cutoff}}, {"_id": 0}).to_list(5000)
    revenue = sum(float(t.get("total", 0) or 0) for t in tx)
    food_cost = 0.0
    products = {p["id"]: p for p in await db.products.find(scope, {"_id": 0}).to_list(2000)}
    for t in tx:
        for it in t.get("items", []) or []:
            food_cost += float(products.get(it.get("productId"), {}).get("cost", 0) or 0) * int(it.get("quantity", 1) or 1)
    rows = []
    for s in sites:
        rows.append({
            "siteId": s["id"], "siteName": s["name"],
            "revenue": round(revenue, 2),
            "foodCostPct": round((food_cost / revenue * 100) if revenue else 0, 1),
            "labourPct": 28,  # placeholder until roster cost rollup is per-site
            "guestSat": 4.5,
        })
    return rows


# ============================================================================
# TIER 5 — Data Warehouse Export
# ============================================================================
@router.get("/warehouse/export")
async def warehouse_export(collection: str = "transactions", limit: int = 1000,
                           user: dict = Depends(require_owner)):
    """SEVERE finding, fixed here: this export had zero business filter —
    an owner of any single business could pull every business's raw
    transactions, customers, reservations, products or agent_decisions off
    the whole deployment through a legitimate 'data warehouse export'
    feature. Same class of bug as the /ops/backup whole-DB exfiltration
    fixed earlier in this audit."""
    allowed = {"transactions", "customers", "reservations", "products", "agent_decisions"}
    if collection not in allowed: raise HTTPException(status_code=400, detail=f"Allowed: {allowed}")
    rows = await db[collection].find(tenant_scope_filter(user.get("businessId")), {"_id": 0}).to_list(limit)
    return {"collection": collection, "rows": rows, "exportedAt": _now()}


# ============================================================================
# TIER 5 — AI Fraud Detection
# ============================================================================
@router.get("/fraud-detection")
async def fraud_detection(user: dict = Depends(get_user)):
    if user["role"] not in ("owner", "manager"): raise HTTPException(status_code=403, detail="Owner/Manager only")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    query = {"$and": [tenant_scope_filter(user.get("businessId")), {"createdAt": {"$gte": cutoff}}]}
    tx = await db.transactions.find(query, {"_id": 0}).to_list(5000)
    per_user = defaultdict(lambda: {"voids": 0, "comps": 0, "discounts": 0.0, "refunds": 0, "tx": 0})
    for t in tx:
        u = t.get("cashier") or t.get("createdBy") or "unknown"
        per_user[u]["tx"] += 1
        if t.get("voided"): per_user[u]["voids"] += 1
        if t.get("compTotal", 0) > 0: per_user[u]["comps"] += 1
        per_user[u]["discounts"] += float(t.get("discount", 0) or 0)
        if t.get("refunded"): per_user[u]["refunds"] += 1
    risk_rows = []
    for u, v in per_user.items():
        # Risk score: weighted
        score = 0
        if v["tx"] >= 5:
            score += min(v["voids"] / max(v["tx"], 1) * 100, 35)
            score += min(v["comps"] / max(v["tx"], 1) * 100, 20)
            score += min(v["refunds"] / max(v["tx"], 1) * 100, 20)
            score += min(v["discounts"] / max(v["tx"], 1) / 10, 25)
        risk_rows.append({"user": u, **v, "riskScore": round(score, 1)})
    risk_rows.sort(key=lambda x: x["riskScore"], reverse=True)
    return {"users": risk_rows, "windowDays": 30}
