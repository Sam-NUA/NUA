"""Crypto checkout — Bitcoin (on-chain or Lightning) and USDC via Coinbase
Commerce. Same "redirect away, redirect back, webhook confirms" shape as
Stripe Checkout (routes/integrations.py), and deliberately reuses that
file's sale-finalize helpers rather than re-implementing them — a crypto
sale gets everything a cash/card sale already does (server-side pricing,
loyalty, gift cards, stock deduction) for free, and there is exactly one
place that decides "money arrived, ring up the sale" instead of two
slightly-different copies drifting apart.
"""
from fastapi import APIRouter, HTTPException, Request, Depends
from datetime import datetime
from database import db
from deps import get_user
from services import coinbase_commerce
import json
import logging
import uuid

router = APIRouter()
logger = logging.getLogger(__name__)


async def _create_crypto_session(data: dict, http_request: Request, cashier: dict) -> dict:
    """The actual charge-creation logic, factored out so a non-staff caller
    (routes/bill_split.py's guest checkout) can create a charge too without
    going through the staff-only route below — see
    routes/integrations.py's _create_stripe_session for why."""
    if not coinbase_commerce.is_configured():
        raise HTTPException(status_code=500,
                             detail="Crypto payments aren't set up yet — ask the owner to add a "
                                    "Coinbase Commerce API key.")

    origin_url = data.get("originUrl", str(http_request.base_url).rstrip("/"))
    client_order_id = data.get("orderId")
    order_id = client_order_id or f"ORD-{str(uuid.uuid4())[:8].upper()}"
    amount = data.get("amount", 0)
    sale_payload = data.get("sale")

    if amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid amount")

    # Same double-click/retry protection as _create_stripe_session, and the
    # same businessId-namespacing to stop two different businesses' staff
    # colliding on a client-supplied orderId — see
    # services/payment_idempotency.py and _create_stripe_session's own
    # comment on why the namespace matters.
    from services.payment_idempotency import claim_or_wait, record_result, fingerprint, IdempotencyConflict
    idempotency_key = f"{cashier.get('businessId') or 'guest'}:{data.get('idempotencyKey') or order_id}"
    # Same amount + CLIENT-supplied-orderId fingerprint as
    # _create_stripe_session — see its comment on why client_order_id, not
    # order_id, and why those two fields and not the whole payload.
    try:
        prior_result = await claim_or_wait("crypto", idempotency_key,
                                            payload_fingerprint=fingerprint(amount, client_order_id))
    except IdempotencyConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    if prior_result is not None:
        return prior_result

    # Coinbase Commerce doesn't template a charge identifier into
    # redirect_url the way Stripe does {CHECKOUT_SESSION_ID} — it just
    # redirects to the bare URL with nothing appended. order_id is the one
    # identifier known before the charge exists, so it travels in the URL
    # instead; GET .../status-by-order/{order_id} resolves it to the charge
    # code Coinbase actually gave us.
    success_url = f"{origin_url}/payment-success?provider=crypto&order_id={order_id}"
    cancel_url = f"{origin_url}/pos"

    try:
        charge = await coinbase_commerce.create_charge(
            amount=float(amount), currency="AUD", name=f"NUA order {order_id}",
            description="NUA POS sale", redirect_url=success_url, cancel_url=cancel_url,
            metadata={"orderId": order_id, "source": "nua_pos"},
        )
    except coinbase_commerce.CoinbaseCommerceError as e:
        logger.error(f"Coinbase Commerce charge create failed: {e}")
        raise HTTPException(status_code=502, detail="Could not create crypto checkout")

    payment_doc = {
        "id": f"CPAY-{str(uuid.uuid4())[:8].upper()}",
        "sessionId": charge["code"],
        "orderId": order_id,
        "amount": float(amount),
        "currency": "aud",
        "status": "initiated",
        "paymentStatus": "pending",
        "provider": "crypto_coinbase",
        "createdAt": datetime.utcnow().isoformat(),
    }
    if sale_payload:
        payment_doc["kind"] = "pos_sale"
        payment_doc["salePayload"] = sale_payload
        payment_doc["cashierUser"] = cashier
        for k in ("splitSessionId", "splitLineIds", "splitSlotIndex", "guestEmail", "heldTabId"):
            if k in data:
                payment_doc[k] = data[k]
    await db.payment_transactions.insert_one(payment_doc)

    result = {"url": charge["hosted_url"], "sessionId": charge["code"]}
    await record_result("crypto", idempotency_key, result)
    return result


@router.post("/crypto/checkout")
async def create_crypto_checkout(data: dict, http_request: Request, user: dict = Depends(get_user)):
    """Create a Coinbase Commerce charge for a POS transaction. Same
    optional "sale" payload shape as POST /stripe/checkout."""
    return await _create_crypto_session(data, http_request, cashier=user)


async def _check_and_finalize(charge_code: str) -> dict:
    try:
        charge = await coinbase_commerce.get_charge(charge_code)
    except coinbase_commerce.CoinbaseCommerceError:
        raise HTTPException(status_code=404, detail="Charge not found")

    status = coinbase_commerce.charge_status(charge)
    payment_status = "paid" if status == "paid" else "unpaid"

    existing = await db.payment_transactions.find_one({"sessionId": charge_code})
    if existing and existing.get("paymentStatus") != "paid":
        await db.payment_transactions.update_one(
            {"sessionId": charge_code},
            {"$set": {"status": "completed" if status == "paid" else status,
                       "paymentStatus": payment_status, "updatedAt": datetime.utcnow().isoformat()}}
        )
        if status == "paid":
            from routes.integrations import _mark_online_order_paid_if_applicable, _finalize_pos_sale_if_applicable
            await _mark_online_order_paid_if_applicable(charge_code)
            await _finalize_pos_sale_if_applicable(charge_code)

    # Split-bill payments carry a splitSessionId on the payment doc — a
    # guest's own PaymentSuccess screen uses this to route back to their
    # table's bill instead of a staff-only "Back to POS" button, which
    # would otherwise dead-end a guest with no login.
    payment = existing or await db.payment_transactions.find_one({"sessionId": charge_code}, {"_id": 0})
    split_session_id = (payment or {}).get("splitSessionId")

    return {"configured": True, "status": status, "paymentStatus": payment_status,
            "splitSessionId": split_session_id}


@router.get("/crypto/checkout/status/{charge_code}")
async def get_crypto_checkout_status(charge_code: str):
    """Poll a Coinbase Commerce charge's status by the charge code Coinbase
    itself assigned. Returns {"configured": False, ...} rather than a 500
    when crypto isn't configured — matches the Stripe status endpoint's
    style, so a caller polling with a stale code from before it was ever
    set up (or after the key is removed) gets a normal response to branch
    on instead of an exception."""
    if not coinbase_commerce.is_configured():
        return {"configured": False, "status": None, "paymentStatus": None}
    return await _check_and_finalize(charge_code)


@router.get("/crypto/checkout/status-by-order/{order_id}")
async def get_crypto_checkout_status_by_order(order_id: str):
    """Same as above, but keyed by the order_id the browser actually has
    after Coinbase's redirect back (see create_crypto_checkout's comment on
    why order_id, not the charge code, travels in the URL)."""
    if not coinbase_commerce.is_configured():
        return {"configured": False, "status": None, "paymentStatus": None}
    payment = await db.payment_transactions.find_one(
        {"orderId": order_id, "provider": "crypto_coinbase"}, {"_id": 0})
    if not payment:
        raise HTTPException(status_code=404, detail="No crypto checkout found for this order")
    return await _check_and_finalize(payment["sessionId"])


@router.post("/webhook/coinbase")
async def coinbase_webhook(request: Request):
    """Coinbase Commerce webhook — HMAC-verified, not a user token, so this
    stays reachable with no session (see server.py's PUBLIC_API_PATHS)."""
    body = await request.body()
    signature = request.headers.get("X-CC-Webhook-Signature", "")
    if not coinbase_commerce.verify_webhook_signature(body, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    event = json.loads(body).get("event", {})
    charge = event.get("data", {})
    charge_code = charge.get("code")
    if event.get("type") != "charge:confirmed" or not charge_code:
        return {"received": True}

    existing = await db.payment_transactions.find_one({"sessionId": charge_code})
    if existing and existing.get("paymentStatus") != "paid":
        await db.payment_transactions.update_one(
            {"sessionId": charge_code},
            {"$set": {"status": "completed", "paymentStatus": "paid", "updatedAt": datetime.utcnow().isoformat()}}
        )
        from routes.integrations import _mark_online_order_paid_if_applicable, _finalize_pos_sale_if_applicable
        await _mark_online_order_paid_if_applicable(charge_code)
        await _finalize_pos_sale_if_applicable(charge_code)
    return {"received": True}
