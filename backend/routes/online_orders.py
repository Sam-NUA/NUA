"""Online ordering + AI ETA engine.

Endpoints:
- POST   /api/online/orders                  — customer places an order (public)
- GET    /api/online/orders                  — owner inbox (auth)
- GET    /api/online/orders/{id}             — single order (auth)
- PATCH  /api/online/orders/{id}/status      — owner moves to next stage (auth)
- POST   /api/online/orders/{id}/eta         — AI-recomputed ETA (auth)
- GET    /api/online/orders/track/{code}     — public order tracking
- GET    /api/online/orders/track/stream/{code} — public order tracking, SSE
- GET    /api/online/kitchen/load            — current pending + preparing counts
"""
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from deps import get_user
import asyncio
import logging
from database import db
from datetime import datetime
from typing import Optional
import os
import json
import uuid
from urllib.parse import urlencode

from utils.notifications import notify_order
from routes.commerce_v29 import _resolve_voucher, _validate_voucher_rules, _compute_voucher_discount
from middleware.actor_context import tenant_scope_filter, tenant_owns_strict

router = APIRouter()

# Same env-tunable pattern as coursing.py's SSE stream — short poll interval,
# bounded connection lifetime so a guest who wanders off without closing the
# tab doesn't leak a connection + Mongo poll loop forever (EventSource
# reconnects on its own once the bound is hit).
TRACK_SSE_INTERVAL_SECONDS = float(os.environ.get('TRACK_SSE_INTERVAL', '4'))
TRACK_SSE_MAX_SECONDS = float(os.environ.get('TRACK_SSE_MAX_SECONDS', '600'))


from utils.ids import now_utc as _now, to_iso as _iso, gen_uid as _uid


# Allowed lifecycle transitions per channel.
_STATUS_ORDER = ["pending", "accepted", "preparing", "ready", "out_for_delivery", "completed", "cancelled"]


async def _kitchen_load(business_id: str) -> dict:
    """Snapshot of currently-active orders feeding the ETA buffer."""
    scope = tenant_scope_filter(business_id)
    pending = await db.online_orders.count_documents({"status": "pending", **scope})
    preparing = await db.online_orders.count_documents({"status": "preparing", **scope})
    accepted = await db.online_orders.count_documents({"status": "accepted", **scope})
    # Per active order add a small queue penalty (1 min). 2x penalty for orders
    # >5min stale to keep ETA honest in busy periods.
    now = _now()
    queue_penalty = 0.0
    rows = await db.online_orders.find(
        {"status": {"$in": ["accepted", "preparing"]}, **scope},
        {"_id": 0, "createdAt": 1}).to_list(50)
    for r in rows:
        try:
            created = datetime.fromisoformat(r.get("createdAt").replace("Z", "+00:00")) if isinstance(r.get("createdAt"), str) else r.get("createdAt")
            age_min = (now - created).total_seconds() / 60.0 if created else 0
            queue_penalty += 2.0 if age_min > 5 else 1.0
        except Exception:
            queue_penalty += 1.0
    return {"pending": pending, "accepted": accepted, "preparing": preparing,
            "queuePenaltyMins": round(queue_penalty, 1)}


async def _compute_eta(items: list, channel: str, kitchen_load: dict, business_id: str) -> dict:
    """Deterministic ETA = max category prep time × surge factor + delivery offset
    + kitchen load buffer. AI then drafts a natural-language explanation."""
    cats = await db.categories.find(tenant_scope_filter(business_id), {"_id": 0}).to_list(200)
    cat_prep = {c["name"].lower(): int(c.get("prepTime", 8)) for c in cats}
    item_prep_mins = []
    cat_breakdown = {}
    for it in items or []:
        c = (it.get("category") or "").lower()
        qty = int(it.get("quantity", 1))
        base = cat_prep.get(c, 8)
        # First unit is the base; each additional unit of the same category adds ~30%.
        total = base + max(0, qty - 1) * (base * 0.3)
        item_prep_mins.append(total)
        cat_breakdown[c] = max(cat_breakdown.get(c, 0), total)
    base_prep = max(item_prep_mins) if item_prep_mins else 8
    # Surge based on kitchen load: 0 → 1.0x, 5+ pending → 1.4x
    pending = kitchen_load.get("pending", 0) + kitchen_load.get("accepted", 0)
    surge = min(1.0 + (pending * 0.05), 1.6)
    queue_penalty = float(kitchen_load.get("queuePenaltyMins", 0))
    delivery_offset = {"delivery": 12, "pickup": 0, "dine-in": 0}.get(channel, 0)
    eta_mins = round(base_prep * surge + queue_penalty + delivery_offset)
    return {
        "etaMinutes": int(eta_mins),
        "baseMinutes": round(base_prep, 1),
        "surge": round(surge, 2),
        "queuePenaltyMins": queue_penalty,
        "deliveryOffsetMins": delivery_offset,
        "categoryBreakdown": cat_breakdown,
        "kitchenLoad": kitchen_load,
    }


async def _ai_eta_explanation(order: dict, eta: dict) -> str:
    """Optional natural-language ETA reason for the customer. Falls back to a
    deterministic string if the LLM is unavailable (key missing / network)."""
    fallback = (
        f"Your {order.get('channel','order')} is being prepared. "
        f"Estimated ready in ~{eta['etaMinutes']} minutes."
    )
    if not os.environ.get("EMERGENT_LLM_KEY"): return fallback
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=os.environ["EMERGENT_LLM_KEY"],
            session_id=f"eta-{uuid.uuid4().hex[:6]}",
            system_message=(
                "You are a friendly restaurant assistant writing a single-sentence "
                "ETA message for a customer. Mention the ETA in minutes and a brief "
                "reason (busy kitchen, large order, or simply 'fresh prep time'). "
                "Plain text — no emoji, no JSON."
            ),
        ).with_model("openai", "gpt-5.2")
        info = json.dumps({
            "channel": order.get("channel"),
            "items": [{"name": i.get("name"), "qty": i.get("quantity")} for i in order.get("items", [])],
            "etaMinutes": eta["etaMinutes"],
            "surge": eta["surge"],
            "pendingInKitchen": eta["kitchenLoad"].get("pending", 0) + eta["kitchenLoad"].get("accepted", 0),
        })
        reply = await chat.send_message(UserMessage(text=info))
        return (reply or fallback).strip()[:240]
    except Exception:
        return fallback


async def _adjust_stock_for_items(items: list, sign: int, business_id: str):
    """+1 to restock, -1 to deduct. Online orders never touched db.products
    stock at all before this — an accepted online order didn't reduce
    on-hand count the way a POS sale does, so this is what accepting one
    now does (mirroring routes/transactions.py's create_transaction), and
    cancelling a previously-accepted paid order reverses it — the same
    deduct-on-sale/restore-on-refund pairing the POS already has."""
    touched = []
    for item in items or []:
        pid = item.get("productId") or item.get("id")
        qty = int(item.get("quantity", 1))
        if not pid or qty <= 0:
            continue
        await db.products.update_one(
            {"id": pid, **tenant_scope_filter(business_id)}, {"$inc": {"stock": sign * qty}})
        touched.append(pid)
    if sign < 0 and touched:
        from utils.stock_ops import clamp_negative_stock
        await clamp_negative_stock(touched)


def _append_event(order: dict, kind: str, message: str, actor: Optional[str] = None) -> dict:
    event = {"kind": kind, "message": message, "actor": actor, "at": _iso(_now())}
    order.setdefault("events", []).append(event)
    return event


def _notification(order: dict, message: str) -> dict:
    """Persisted notification — would be hooked to SendGrid/Twilio in prod. For
    now we just append to the order so the customer sees it on the tracking page."""
    n = {"id": _uid("NOT"), "message": message, "at": _iso(_now())}
    order.setdefault("notifications", []).append(n)
    return n


# =============================================================================
# CATEGORY PREP TIMES (helper used by the storefront)
# =============================================================================
async def _resolve_business_id(business: Optional[str]) -> str:
    """Resolve a public venue; never pool tenants or ignore an invalid selector."""
    if business:
        biz = await db.businesses.find_one(
            {"$or": [{"id": business}, {"slug": business}]}, {"_id": 0, "id": 1})
        if not biz:
            raise HTTPException(status_code=404, detail="Business not found")
        return biz["id"]
    candidates = await db.businesses.find({}, {"_id": 0, "id": 1}).to_list(2)
    if len(candidates) != 1:
        raise HTTPException(status_code=400, detail="Specify a valid business (?business=<slug-or-id>)")
    return candidates[0]["id"]


async def resolve_or_require_business_id(business: Optional[str]) -> str:
    return await _resolve_business_id(business)



@router.get("/online/business")
async def public_business_info(business: Optional[str] = None):
    """Lets the storefront tell "no ?business= param, unscoped menu" (normal
    on a single-business deployment) apart from "?business= was set but
    didn't match anything" (a stale/mistyped link) — the products/categories
    endpoints alone can't distinguish these since both resolve to the same
    unscoped fallback. Only exposes what a guest already sees on the page."""
    if not business:
        return {"found": None}
    biz = await db.businesses.find_one({"$or": [{"id": business}, {"slug": business}]}, {"_id": 0, "id": 1, "name": 1})
    if not biz:
        return {"found": False}
    return {"found": True, "id": biz["id"], "name": biz.get("name", "")}


@router.get("/online/categories")
async def public_categories(business: Optional[str] = None):
    """Public — only returns active categories that are enabled for online
    channels (pickup OR delivery)."""
    business_id = await _resolve_business_id(business)
    query = {"active": True, **tenant_scope_filter(business_id)}
    cats = await db.categories.find(query, {"_id": 0}).to_list(200)
    rows = []
    for c in cats:
        channels = c.get("channels") or ["dine-in", "pickup", "delivery"]
        if any(ch in channels for ch in ("pickup", "delivery", "online")):
            rows.append({k: c.get(k) for k in ("id", "name", "icon", "color", "prepTime", "sortOrder")})
    rows.sort(key=lambda x: x.get("sortOrder", 99))
    return rows


@router.get("/online/products")
async def public_products(business: Optional[str] = None):
    """Public storefront catalog: in-stock, not 86'd, with online-enabled category."""
    business_id = await _resolve_business_id(business)
    cats = await public_categories(business)
    allowed = {c["name"] for c in cats}
    query = {
        "category": {"$in": list(allowed)}, "stock": {"$gt": 0}, "eightySixed": {"$ne": True},
        **tenant_scope_filter(business_id),
    }
    products = await db.products.find(
        query,
        # This is a storefront anyone on the internet can hit, so it hands back
        # the menu and nothing behind it — no unit cost, no on-hand count, no
        # SKU. Those are the same fields /products strips for guests.
        {"_id": 0, "cost": 0, "stock": 0, "sku": 0},
    ).to_list(500)
    return products


# =============================================================================
# PLACE ORDER (public)
# =============================================================================
@router.post("/online/orders")
async def place_order(data: dict, business: Optional[str] = None):
    """Customer places a new order. No auth required (storefront)."""
    items = data.get("items") or []
    if not items:
        raise HTTPException(status_code=400, detail="Order must contain at least one item")
    channel = data.get("channel", "pickup")  # pickup | delivery | dine-in
    if channel not in ("pickup", "delivery", "dine-in"):
        raise HTTPException(status_code=400, detail="Invalid channel")
    business_id = await _resolve_business_id(business or data.get("business"))
    customer = {
        "name": (data.get("customerName") or "").strip(),
        "phone": (data.get("customerPhone") or "").strip(),
        "email": (data.get("customerEmail") or "").strip(),
        "address": (data.get("address") or "").strip(),
        "notes": (data.get("notes") or "").strip(),
    }
    if not customer["name"]:
        raise HTTPException(status_code=400, detail="Customer name required")
    if channel == "delivery" and not customer["address"]:
        raise HTTPException(status_code=400, detail="Delivery requires an address")
    # Menu prices are GST-inclusive — the listed price is what the customer
    # pays, GST is disclosed as the component within it, not added on top.
    subtotal = sum(float(i.get("price", 0)) * int(i.get("quantity", 1)) for i in items)
    # No loyalty-tier discount is applied here, unlike routes/transactions.py's
    # POS checkout (which reads db.loyalty_tiers off transaction.customerId).
    # This is a deliberate, structural limitation, not an oversight: `customer`
    # above is freeform guest contact info (name/phone/email typed into the
    # storefront form), never resolved to an actual db.customers record —
    # there is no customerId here to look a tier up against. Giving online
    # ordering the same tier-discount behavior POS has would mean building
    # real guest-to-customer identification at checkout (matching/creating a
    # db.customers row, then trusting its membershipTier) — a new feature,
    # not a bug fix, and out of scope here. See
    # tests/inprocess/test_loyalty_tier_discount_channel_consistency.py for
    # the contract this currently holds to.
    #
    # Voucher discount is re-validated server-side here, not trusted from the
    # client — same voucher document commerce_v29's staff-facing apply uses.
    voucher_code = (data.get("voucherCode") or "").strip()
    voucher_discount = 0.0
    voucher_label = None
    if voucher_code:
        try:
            v = await _resolve_voucher(voucher_code, None, business_id=business_id)
            if not _validate_voucher_rules(v, cart=items):
                voucher_discount = _compute_voucher_discount(v, subtotal)
                voucher_label = v.get("label")
        except HTTPException:
            voucher_code = ""
    total = round(max(0.0, subtotal - voucher_discount), 2)
    gst = round(total / 11, 2)
    code = _uid("ORD")
    load = await _kitchen_load(business_id)
    eta = await _compute_eta(items, channel, load, business_id)
    order = {
        "id": code, "trackingCode": code,
        "businessId": business_id,
        "channel": channel,
        "customer": customer,
        "items": items,
        "subtotal": round(subtotal, 2),
        "voucherCode": voucher_code or None,
        "voucherDiscount": voucher_discount,
        "voucherLabel": voucher_label,
        "gst": gst,
        "total": total,
        "status": "pending",
        # "unpaid" until a Stripe checkout for this order actually confirms —
        # set by /online/orders/{id}/checkout + the shared Stripe status/webhook
        # handlers in routes/integrations.py. Orders placed with Stripe not
        # configured (or where the guest abandons checkout) simply stay
        # "unpaid" forever, same as the "pay at pickup/delivery" model this
        # replaces for anyone who does complete payment.
        "paymentStatus": "unpaid",
        "eta": eta,
        "etaMessage": await _ai_eta_explanation({"channel": channel, "items": items}, eta),
        "events": [], "notifications": [],
        "createdAt": _iso(_now()),
    }
    _append_event(order, "created", f"Order placed via {channel}")
    _notification(order, f"Hi {customer['name']}, we received your order {code}. Estimated ready in ~{eta['etaMinutes']} min.")
    receipts = await notify_order(order, f"Hi {customer['name']}, we received your order {code}. Estimated ready in ~{eta['etaMinutes']} min.",
                                  subject=f"NUA order {code} received")
    order["deliveryReceipts"] = receipts
    await db.online_orders.insert_one(order); order.pop("_id", None)
    return order


# =============================================================================
# PAYMENT — Stripe Checkout for an already-placed online order
# =============================================================================
# Online orders previously never got paid through this system at all — the
# order was created, a tracking code handed back, and actual payment
# happened entirely out of band (staff took payment at pickup/delivery,
# with nothing here recording it). This endpoint is the missing prerequisite
# for online ordering to be a sellable, complete product on its own: it
# reuses the exact Stripe Checkout flow the in-store POS already uses
# (routes/integrations.py), just pointed at an online order's total instead
# of a POS cart, and tagged so the shared status-poll/webhook handlers know
# to flip the ORDER's paymentStatus too, not just the generic payment ledger.
@router.post("/online/orders/checkout")
async def create_online_order_checkout(data: dict, http_request: Request):
    """Public — a guest who just placed an order has no session to attach.
    Takes orderId in the body rather than the URL (POST /online/orders/{id}/checkout
    would need a path-param-aware entry in server.py's public-path matcher,
    which only does prefix matching — a body field keeps this an exact,
    easily-audited allowlist entry instead)."""
    order_id = data.get("orderId")
    if not order_id:
        raise HTTPException(status_code=400, detail="orderId is required")
    business_id = await _resolve_business_id(data.get("business"))
    scope = tenant_scope_filter(business_id)
    order = await db.online_orders.find_one({"id": order_id, **scope}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.get("paymentStatus") == "paid":
        raise HTTPException(status_code=400, detail="Order is already paid")

    api_key = os.environ.get("STRIPE_API_KEY")
    if not api_key:
        # Not a hard failure — the guest just falls back to paying at
        # pickup/delivery like every online order before this endpoint existed.
        return {"configured": False, "url": None}

    # Deliberately imported only after the config check above, not before:
    # this endpoint must degrade to the pickup/delivery fallback whenever
    # Stripe isn't configured, even in an environment where this optional
    # SDK isn't installed at all — importing it unconditionally at the top
    # turned every checkout attempt into an unhandled 500 in exactly that
    # case (found running this endpoint end to end via Playwright). Matches
    # routes/integrations.py's _create_stripe_session, which already does
    # this the right way round.
    from emergentintegrations.payments.stripe.checkout import StripeCheckout, CheckoutSessionRequest

    # A double-click or a client retry must not create two live Stripe
    # sessions for the same order — order_id is already a stable resource
    # identity (unlike a freshly-generated one), so this needs no new
    # client-supplied key at all. See services/payment_idempotency.py.
    from services.payment_idempotency import claim_or_wait, record_result
    prior_result = await claim_or_wait("stripe_online_order", order_id)
    if prior_result is not None:
        return {"configured": True, **prior_result}

    origin_url = data.get("originUrl", str(http_request.base_url).rstrip("/"))
    host_url = str(http_request.base_url).rstrip("/")
    webhook_url = f"{host_url}/api/webhook/stripe"
    stripe_checkout = StripeCheckout(api_key=api_key, webhook_url=webhook_url)

    business_selector = data.get("business")
    business_query = urlencode({"business": business_selector}) if business_selector else ""
    success_query = f"{business_query}&" if business_query else ""
    success_url = f"{origin_url}/track/{order_id}?{success_query}session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{origin_url}/track/{order_id}" + (f"?{business_query}" if business_query else "")

    checkout_request = CheckoutSessionRequest(
        amount=float(order["total"]),
        currency="aud",
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"orderId": order_id, "source": "nua_pos", "kind": "online_order"},
    )
    session = await stripe_checkout.create_checkout_session(checkout_request)

    payment_doc = {
        "id": f"SPAY-{uuid.uuid4().hex[:8].upper()}",
        "sessionId": session.session_id,
        "orderId": order_id,
        "amount": float(order["total"]),
        "currency": "aud",
        "status": "initiated",
        "paymentStatus": "pending",
        "provider": "stripe",
        "kind": "online_order",
        "createdAt": _iso(_now()),
        "businessId": business_id,
    }
    await db.payment_transactions.insert_one(payment_doc)
    await db.online_orders.update_one(
        {"id": order_id, **scope}, {"$set": {"paymentSessionId": session.session_id}})
    result = {"url": session.url, "sessionId": session.session_id}
    await record_result("stripe_online_order", order_id, result)
    return {"configured": True, **result}


# =============================================================================
# OWNER INBOX + MANAGEMENT
# =============================================================================
@router.get("/online/orders")
async def list_orders( status: Optional[str] = None, limit: int = 100, user: dict = Depends(get_user)):
    if user["role"] not in ("owner", "manager", "cashier", "kitchen"):
        raise HTTPException(status_code=403, detail="Staff only")
    q = tenant_scope_filter(user.get("businessId"))
    if status: q["status"] = status
    rows = await db.online_orders.find(q, {"_id": 0}).sort("createdAt", -1).to_list(limit)
    return rows


@router.get("/online/orders/{order_id}")
async def get_order(order_id: str, user: dict = Depends(get_user)):
    row = await db.online_orders.find_one({"$and": [{"id": order_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not row or not tenant_owns_strict(row.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Order not found")
    return row


@router.patch("/online/orders/{order_id}/status")
async def update_status(order_id: str, data: dict, user: dict = Depends(get_user)):
    if user["role"] not in ("owner", "manager", "cashier", "kitchen"):
        raise HTTPException(status_code=403, detail="Staff only")
    new_status = data.get("status")
    if new_status not in _STATUS_ORDER:
        raise HTTPException(status_code=400, detail=f"Invalid status. Allowed: {_STATUS_ORDER}")
    business_id = user.get("businessId")
    scope = tenant_scope_filter(business_id)
    order = await db.online_orders.find_one({"id": order_id, **scope}, {"_id": 0})
    if not order: raise HTTPException(status_code=404, detail="Order not found")

    # Atomically claim this exact transition before doing any side effects.
    # This used to be read order -> mutate a Python dict -> blind $set at
    # the very end, which let two near-simultaneous requests (two staff
    # both hitting Accept, or an accept racing a cancel) both read the same
    # pre-transition order, both pass every guard below (stockDeducted was
    # checked against each request's own stale in-memory copy, not the
    # database), and both apply side effects — double stock deduction being
    # the sharpest edge — with whichever request's final update_one landed
    # last silently overwriting the other's status/event/refund outcome.
    # The filter re-verifies the order is still at the exact status this
    # request read; a request that loses the race gets a clean 409 instead
    # of proceeding to recompute and clobber. Tradeoff: status flips here,
    # before the derived side effects (stock, kitchen ticket, notifications)
    # are computed and persisted a few lines down — a crash in that narrow
    # window would leave the order's status updated without those side
    # effects applied. Accepted as strictly safer than the prior
    # no-protection-at-all state; see FINANCIAL_OFFLINE_INTEGRITY_REMAINING_WORK.md.
    claimed = await db.online_orders.find_one_and_update(
        {"id": order_id, "status": order["status"], **scope},
        {"$set": {"status": new_status}},
        projection={"_id": 0},
    )
    if not claimed:
        raise HTTPException(status_code=409,
                             detail="Order status was just changed by another request — reload and try again")
    order = claimed
    # Append event + notification with a status-specific message
    cust_name = (order.get("customer") or {}).get("name", "")
    ch = order.get("channel")
    msgs = {
        "accepted": f"Hi {cust_name}, your order {order['id']} has been accepted and is queued for the kitchen.",
        "preparing": f"{cust_name}, the kitchen has started preparing your order.",
        "ready": (f"{cust_name}, your order is ready for pickup!"
                  if ch == "pickup"
                  else (f"{cust_name}, your order is ready and the table is set." if ch == "dine-in"
                        else f"{cust_name}, your order is packed and waiting for the driver.")),
        "out_for_delivery": f"{cust_name}, your order is out for delivery. Driver: {data.get('driver','assigned')}.",
        "completed": f"{cust_name}, your order is complete. Thanks for choosing us!",
        "cancelled": f"{cust_name}, your order has been cancelled. {data.get('reason','')}",
    }
    _append_event(order, f"status:{new_status}", msgs.get(new_status, f"Status → {new_status}"), user.get("name"))
    _notification(order, msgs.get(new_status, f"Status updated to {new_status}"))
    # Best-effort email + SMS to the customer (no-op if SendGrid/Twilio not set).
    receipts = await notify_order(order, msgs.get(new_status, f"Status updated to {new_status}"),
                                  subject=f"Order {order['id']} — {new_status.replace('_',' ').title()}")
    order.setdefault("deliveryReceipts", []).extend(receipts)
    order["status"] = new_status
    if new_status == "accepted":
        order["acceptedAt"] = _iso(_now())
        # Accepting used to update this order's own collection and nothing
        # else, so an accepted online order never appeared on any KDS. It is
        # a real order — it goes to the pass, coursed like any other.
        try:
            from services import channel_orders
            ticket = await channel_orders.create_ticket(
                order.get("items") or [],
                order_type=("dine_in" if ch == "dine-in"
                            else "delivery" if ch == "delivery" else "takeaway"),
                table_number=order.get("tableNumber"),
                source=f"online:{ch}", external_id=order["id"],
                guest_name=(order.get("customer") or {}).get("name"),
                notes=order.get("notes"),
                actor=user.get("name") or "Online",
                business_id=user.get("businessId"),
            )
            if ticket:
                order["kitchenOrderId"] = ticket["id"]
        except Exception as e:
            logging.getLogger(__name__).warning(
                "online order %s: kitchen ticket failed — %s", order_id, e)
        if not order.get("stockDeducted"):
            await _adjust_stock_for_items(order.get("items") or [], sign=-1, business_id=business_id)
            order["stockDeducted"] = True
        # Recompute ETA with fresh kitchen-load snapshot
        load = await _kitchen_load(business_id)
        order["eta"] = await _compute_eta(order.get("items", []), ch, load, business_id)
        order["etaMessage"] = await _ai_eta_explanation(order, order["eta"])
    if new_status == "out_for_delivery":
        order["driver"] = data.get("driver", "")
        order["dispatchedAt"] = _iso(_now())
    if new_status == "ready":
        order["readyAt"] = _iso(_now())
    if new_status == "completed":
        order["completedAt"] = _iso(_now())
    if new_status == "cancelled" and order.get("stockDeducted") and not order.get("stockRestored"):
        # Only accepted orders ever deducted stock (above) — an order
        # cancelled while still "pending" never touched inventory, so there's
        # nothing to give back.
        await _adjust_stock_for_items(order.get("items") or [], sign=1, business_id=business_id)
        order["stockRestored"] = True
    if new_status == "cancelled" and order.get("paymentStatus") in ("paid", "refund_failed"):
        # This order was actually charged (Stripe checkout added last round)
        # — cancelling it without reversing the charge would just take the
        # guest's money for food they're never getting. Doesn't block the
        # cancellation on a failed refund call (network/Stripe-side issues
        # shouldn't trap staff into being unable to cancel an order) — it
        # flags the order for manual follow-up instead. Re-cancelling an
        # order already flagged refund_failed retries it — refund_stripe_
        # payment() is itself safe to call again against an already-refunded
        # charge, so this can't produce a double refund.
        payment = await db.payment_transactions.find_one(
            {"orderId": order_id, "kind": "online_order", "paymentStatus": "paid", **scope}, {"_id": 0})
        if payment and payment.get("sessionId"):
            from routes.integrations import refund_stripe_payment
            refunded = await refund_stripe_payment(payment["sessionId"])
            if refunded:
                order["paymentStatus"] = "refunded"
                await db.payment_transactions.update_one(
                    {"sessionId": payment["sessionId"], **scope},
                    {"$set": {"paymentStatus": "refunded", "status": "refunded", "updatedAt": _iso(_now())}},
                )
                _append_event(order, "payment:refunded", "Payment refunded in full.")
            else:
                order["paymentStatus"] = "refund_failed"
                _append_event(order, "payment:refund_failed",
                               "Automatic refund failed — needs manual refund via the Stripe dashboard.")
                logging.getLogger(__name__).error(
                    "online order %s: cancelled but Stripe refund failed — needs manual reconciliation", order_id)
    update_fields = {k: v for k, v in order.items() if k != "id"}
    await db.online_orders.update_one({"id": order_id, **scope}, {"$set": update_fields})
    return order


@router.post("/online/orders/{order_id}/eta")
async def recompute_eta(order_id: str, user: dict = Depends(get_user)):
    business_id = user.get("businessId")
    scope = tenant_scope_filter(business_id)
    order = await db.online_orders.find_one({"id": order_id, **scope}, {"_id": 0})
    if not order: raise HTTPException(status_code=404, detail="Order not found")
    load = await _kitchen_load(business_id)
    eta = await _compute_eta(order.get("items", []), order.get("channel", "pickup"), load, business_id)
    msg = await _ai_eta_explanation(order, eta)
    _append_event(order, "eta:recomputed", f"New ETA: {eta['etaMinutes']} min")
    await db.online_orders.update_one(
        {"id": order_id, **scope}, {"$set": {"eta": eta, "etaMessage": msg, "events": order["events"]}})
    return {"eta": eta, "etaMessage": msg}


@router.get("/online/kitchen/load")
async def kitchen_load_endpoint(user: dict = Depends(get_user)):
    return await _kitchen_load(user.get("businessId"))


# =============================================================================
# PUBLIC TRACKING (no auth — by order code)
# =============================================================================
def _public_order_view(order: dict) -> dict:
    """Strip internal fields the customer doesn't need — shared by the
    polled REST endpoint and the SSE stream below so they can never drift
    into showing different shapes for the same order."""
    customer = order.get("customer") or {}
    return {
        "id": order["id"], "status": order["status"], "channel": order.get("channel"),
        "createdAt": order.get("createdAt"),
        "customerName": customer.get("name"),
        "items": order.get("items", []),
        "subtotal": order.get("subtotal"), "gst": order.get("gst"), "total": order.get("total"),
        "paymentStatus": order.get("paymentStatus"),
        "eta": order.get("eta"), "etaMessage": order.get("etaMessage"),
        "notifications": order.get("notifications", []),
        "events": [{"kind": e["kind"], "at": e["at"], "message": e.get("message", "")} for e in order.get("events", [])],
        "driver": order.get("driver"),
        "readyAt": order.get("readyAt"),
        "completedAt": order.get("completedAt"),
    }

@router.get("/online/orders/track/{code}")
async def track_order(code: str):
    order = await db.online_orders.find_one({"id": code.upper()}, {"_id": 0})
    if not order: raise HTTPException(status_code=404, detail="Order not found")
    return _public_order_view(order)

@router.get("/online/orders/track/stream/{code}")
async def track_order_stream(code: str, request: Request):
    """Server-sent events for one guest's own order — replaces every
    guest currently watching their order polling every ~12s with one
    long-lived connection each. Public, same access model as the REST
    endpoint above: the tracking code (emailed/texted to the guest, and
    already right there in the /track/{code} URL) is the only credential,
    same as it already was for the polled version — this just pushes
    instead of making the guest's browser ask again and again.
    """
    async def events():
        last = None
        started = asyncio.get_event_loop().time()
        while True:
            if asyncio.get_event_loop().time() - started > TRACK_SSE_MAX_SECONDS:
                return
            if await request.is_disconnected():
                return
            try:
                order = await db.online_orders.find_one({"id": code.upper()}, {"_id": 0})
                if not order:
                    yield "event: not_found\ndata: {}\n\n"
                    return
                payload = json.dumps(_public_order_view(order), default=str)
                if payload != last:
                    last = payload
                    yield f"event: order\ndata: {payload}\n\n"
                else:
                    yield ": keepalive\n\n"
            except Exception as e:
                logging.getLogger(__name__).warning("order tracking stream error for %s: %s", code, e)
                yield ": error\n\n"
            await asyncio.sleep(TRACK_SSE_INTERVAL_SECONDS)

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        # nginx buffers SSE by default, which would defeat the whole point.
        "X-Accel-Buffering": "no",
    })
