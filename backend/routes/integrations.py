from fastapi import APIRouter, Depends, Header, HTTPException, Request
from typing import Optional
from datetime import datetime, timedelta
from database import db
from deps import get_user, require_owner_or_manager
import logging
import os
import uuid

router = APIRouter()


def _stripe_key_mode() -> Optional[str]:
    """Stripe secret keys are self-describing: sk_test_/rk_test_ vs
    sk_live_/rk_live_. None when Stripe isn't configured at all."""
    key = os.environ.get("STRIPE_API_KEY", "")
    if not key:
        return None
    return "live" if "_live_" in key else "test"


async def _mark_online_order_paid_if_applicable(session_id: str):
    """A payment_transactions doc tagged kind='online_order' (set by
    routes/online_orders.py's checkout endpoint) means this Stripe session
    is paying for an online order, not a POS sale — flip that order's
    paymentStatus too, not just the generic payment ledger, so staff and the
    guest's tracking page both see it as paid."""
    payment = await db.payment_transactions.find_one({"sessionId": session_id}, {"_id": 0})
    if not payment or payment.get("kind") != "online_order" or not payment.get("orderId"):
        return
    await db.online_orders.update_one(
        {"id": payment["orderId"]},
        {"$set": {"paymentStatus": "paid", "paidAt": datetime.utcnow().isoformat()}},
    )


async def _mark_reservation_deposit_paid_if_applicable(session_id: str):
    """A payment_transactions doc tagged kind='booking_deposit' (set by
    routes/reservations.py's request_deposit) means this Stripe session paid
    a booking's deposit — flip depositPaid on the reservation itself so it's
    genuinely collected money, not a staff-ticked checkbox, and something
    mark_no_show can actually forfeit."""
    payment = await db.payment_transactions.find_one({"sessionId": session_id}, {"_id": 0})
    if not payment or payment.get("kind") != "booking_deposit" or not payment.get("reservationId"):
        return
    await db.reservations.update_one(
        {"id": payment["reservationId"]},
        {"$set": {"depositPaid": True, "updatedAt": datetime.utcnow().isoformat()}},
    )


async def refund_stripe_payment(session_id: str) -> bool:
    """Refund, in full, the Stripe payment behind a Checkout Session.

    Uses the official `stripe` SDK directly (already a pinned dependency in
    requirements.txt) rather than the emergentintegrations wrapper used
    elsewhere in this file — that wrapper only exposes checkout-session
    creation/status/webhook, no refund call. The SDK is synchronous, so the
    actual network calls run in a thread so they don't block the event loop.
    Returns False (never raises) on any failure — callers decide what a
    failed refund means for the action that triggered it.
    """
    import stripe
    import asyncio

    api_key = os.environ.get("STRIPE_API_KEY")
    if not api_key:
        return False

    def _do_refund():
        stripe.api_key = api_key
        session = stripe.checkout.Session.retrieve(session_id)
        payment_intent = session.get("payment_intent")
        if not payment_intent:
            return False
        # Guards a double-refund attempt (e.g. staff double-clicking cancel
        # before the first request's response comes back) at the source of
        # truth — Stripe's own charge record — rather than trusting only our
        # own payment_transactions doc, which could itself be out of sync.
        intent = stripe.PaymentIntent.retrieve(payment_intent)
        charges = (intent.get("charges") or {}).get("data") or []
        if any(c.get("refunded") for c in charges):
            return True  # already refunded — the desired end state already holds
        stripe.Refund.create(payment_intent=payment_intent)
        return True

    try:
        return await asyncio.to_thread(_do_refund)
    except Exception as e:
        # Stripe itself rejects a second refund on an already-fully-refunded
        # charge with an InvalidRequestError — that's not a failure, it's
        # confirmation the money is already back with the guest.
        if "already been refunded" in str(e).lower() or "has already been refunded" in str(e).lower():
            return True
        logging.getLogger(__name__).error(f"Stripe refund failed for session {session_id}: {e}")
        return False


async def _finalize_pos_sale_if_applicable(session_id: str):
    """A payment_transactions doc tagged kind='pos_sale' carries the exact
    cart/discount/loyalty payload the POS had built at the moment the
    cashier sent the guest to Stripe — Stripe Checkout redirects the whole
    browser away and back, so nothing survives in POSTerminal's React state
    to finalize the sale once the guest returns. The Stripe redirect used to
    be the entire flow: pay, then land back on a page that only confirmed
    *money moved*, never actually rang anything up — no transaction, no
    stock deduction, no receipt, no loyalty earn.

    Runs the exact same POST /transactions code path a cash/card sale uses
    (imported and called directly, not re-implemented), so this gets
    everything that endpoint already does — server-side pricing, loyalty,
    gift cards — for free. Claims the payment doc atomically first so the
    status-poll and the webhook, which can both observe "paid" for the same
    session, can't both create the sale.

    The claim carries a timestamp and is reclaimable after 2 minutes — if
    the process crashes between claiming and finishing (not an exception,
    an actual process death), the except-block's un-claim never runs, and
    without a staleness window that would strand the sale at "pending"
    forever with no automatic retry. Stripe retries its webhook for days on
    failure, so a stale claim gets picked up by the next delivery attempt.
    """
    stale_cutoff = (datetime.utcnow() - timedelta(minutes=2)).isoformat()
    claimed = await db.payment_transactions.find_one_and_update(
        {"sessionId": session_id, "kind": "pos_sale", "$or": [
            {"transactionId": {"$exists": False}},
            {"transactionId": "pending", "transactionClaimedAt": {"$lt": stale_cutoff}},
        ]},
        {"$set": {"transactionId": "pending", "transactionClaimedAt": datetime.utcnow().isoformat()}},
    )
    if not claimed:
        return
    try:
        from models.transaction import TransactionCreate
        from routes.transactions import create_transaction
        txn = await create_transaction(TransactionCreate(**claimed["salePayload"]), user=claimed["cashierUser"])
        await db.payment_transactions.update_one(
            {"sessionId": session_id}, {"$set": {"transactionId": txn.id}}
        )
        if claimed.get("splitSessionId"):
            # Bookkeeping only — the sale itself already landed above. A
            # failure here must never look like the payment failed, so it's
            # logged and swallowed, not raised into this try block's except.
            try:
                from services import bill_split
                await bill_split.mark_lines_paid(
                    claimed["splitSessionId"], claimed.get("splitLineIds"),
                    claimed.get("splitSlotIndex"), txn.id,
                    guest_email=claimed.get("guestEmail"),
                )
            except Exception as split_e:
                logging.getLogger(__name__).error(
                    f"Split-bill bookkeeping failed for {session_id} (sale itself succeeded, txn {txn.id}): {split_e}"
                )
        if claimed.get("heldTabId"):
            # The auto-hold created right before the redirect to Stripe/
            # Coinbase has done its job — the sale is rung up for real now,
            # so the parked cart is no longer needed. Same "bookkeeping
            # only, never fail the sale over it" rule as the split-bill
            # branch above.
            try:
                await db.pos_tabs.delete_one({"id": claimed["heldTabId"]})
            except Exception as hold_e:
                logging.getLogger(__name__).error(
                    f"Held-tab cleanup failed for {session_id} (sale itself succeeded, txn {txn.id}): {hold_e}"
                )
    except Exception as e:
        logging.getLogger(__name__).error(
            f"Stripe payment {session_id} confirmed paid but sale creation failed — needs manual reconciliation: {e}"
        )
        # Un-claim so a retried poll/webhook can try again immediately
        # rather than waiting out the staleness window above.
        await db.payment_transactions.update_one(
            {"sessionId": session_id}, {"$unset": {"transactionId": "", "transactionClaimedAt": ""}}
        )


# ============ STRIPE CHECKOUT API ============
async def _create_stripe_session(data: dict, http_request: Request, cashier: dict) -> dict:
    """The actual session-creation logic, factored out so a non-staff
    caller (routes/bill_split.py's guest checkout) can create a session
    too without going through the staff-only route below — `cashier` is
    whatever identity should be attributed on the resulting sale (the
    logged-in staff member for a normal POS checkout, or a synthetic
    "guest:<phone>" identity for a guest self-checkout), stored as-is on
    the payment doc the same way either caller would want."""
    api_key = os.environ.get("STRIPE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Stripe not configured")

    # Deliberately imported after the config check above, not before: an
    # unconfigured venue (or a deploy where this optional SDK genuinely
    # isn't installed) should see "Stripe not configured", not a raw
    # ModuleNotFoundError surfacing as an unexplained 500.
    from emergentintegrations.payments.stripe.checkout import StripeCheckout, CheckoutSessionRequest

    origin_url = data.get("originUrl", str(http_request.base_url).rstrip("/"))
    client_order_id = data.get("orderId")
    order_id = client_order_id or f"ORD-{str(uuid.uuid4())[:8].upper()}"
    amount = data.get("amount", 0)
    sale_payload = data.get("sale")

    if amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid amount")

    # A double-click or a client retry after a dropped response must not
    # create two live Stripe sessions for the same cart. `idempotencyKey`
    # (explicit, e.g. the POS's per-attempt UUID) takes priority; falling
    # back to order_id means callers whose orderId is already a stable
    # resource identity — routes/bill_split.py's split_id,
    # routes/online_orders.py's placed-order id — get real protection with
    # no caller change at all. See services/payment_idempotency.py.
    #
    # Namespaced by the cashier's own businessId: order_id/idempotencyKey
    # is client-supplied on this generic endpoint (unlike bill_split's
    # server-derived split_id), so without this a staff member at business
    # A using the same orderId as business B within the claim window would
    # have gotten back business B's live Stripe session instead of their
    # own. A guest checkout (routes/bill_split.py's synthetic cashier, no
    # businessId) still gets real per-split protection from split_id's own
    # uniqueness — "guest" here is just this endpoint's shared fallback
    # bucket for callers with no business of their own, not a weakening of
    # bill_split's actual guarantee.
    from services.payment_idempotency import claim_or_wait, record_result, fingerprint, IdempotencyConflict
    idempotency_key = f"{cashier.get('businessId') or 'guest'}:{data.get('idempotencyKey') or order_id}"
    # Pinned to amount + the CLIENT-supplied orderId (client_order_id, not
    # order_id — order_id falls back to a fresh random value every call
    # when the client omits it, which would make every retry look like a
    # "different request" and 409 on its own legitimate retry). originUrl/
    # sale legitimately vary across a genuine retry (different tab, cart
    # snapshot re-serialized) without meaning a different transaction. A
    # DIFFERENT amount or client-supplied orderId under the same key is
    # exactly the "client reused a stale idempotency key across two
    # different carts" bug this guards against.
    try:
        prior_result = await claim_or_wait("stripe", idempotency_key,
                                            payload_fingerprint=fingerprint(amount, client_order_id))
    except IdempotencyConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    if prior_result is not None:
        return prior_result

    host_url = str(http_request.base_url).rstrip("/")
    webhook_url = f"{host_url}/api/webhook/stripe"
    stripe_checkout = StripeCheckout(api_key=api_key, webhook_url=webhook_url)

    success_url = f"{origin_url}/payment-success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{origin_url}/pos"

    checkout_request = CheckoutSessionRequest(
        amount=float(amount),
        currency="aud",
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"orderId": order_id, "source": "nua_pos"},
    )

    session = await stripe_checkout.create_checkout_session(checkout_request)

    # Save payment transaction
    payment_doc = {
        "id": f"SPAY-{str(uuid.uuid4())[:8].upper()}",
        "sessionId": session.session_id,
        "orderId": order_id,
        "amount": float(amount),
        "currency": "aud",
        "status": "initiated",
        "paymentStatus": "pending",
        "provider": "stripe",
        "createdAt": datetime.utcnow().isoformat(),
    }
    if sale_payload:
        payment_doc["kind"] = "pos_sale"
        payment_doc["salePayload"] = sale_payload
        payment_doc["cashierUser"] = cashier
        # Split-bill metadata rides alongside salePayload rather than inside
        # it — TransactionCreate doesn't (and shouldn't) know about split
        # sessions, so these live as sibling fields _finalize_pos_sale_
        # if_applicable reads directly off the payment doc. heldTabId is the
        # same idea for the POS's auto-hold-before-redirect tab (see
        # POSTerminal.jsx handleStripeCheckout) — lets finalize clean up the
        # hold once the sale actually lands, instead of it sitting there
        # looking unresolved after a successful payment.
        for k in ("splitSessionId", "splitLineIds", "splitSlotIndex", "guestEmail", "heldTabId"):
            if k in data:
                payment_doc[k] = data[k]
    await db.payment_transactions.insert_one(payment_doc)
    payment_doc.pop("_id", None)

    result = {"url": session.url, "sessionId": session.session_id}
    await record_result("stripe", idempotency_key, result)
    return result


@router.post("/stripe/checkout")
async def create_stripe_checkout(data: dict, http_request: Request, user: dict = Depends(get_user)):
    """Create a Stripe checkout session for a POS transaction.

    An optional "sale" object — the same shape POST /transactions takes
    (items, paymentMethod, customerId, location, cashier, orderType,
    tableNumber, discounts, points…) — gets stashed against this session so
    the sale can actually be rung up once Stripe confirms payment. Without
    it (or for any other caller of this generic endpoint) this behaves
    exactly as before: a payment session with nothing else attached.
    """
    return await _create_stripe_session(data, http_request, cashier=user)

@router.get("/stripe/checkout/status/{session_id}")
async def get_stripe_checkout_status(session_id: str, http_request: Request):
    """Poll Stripe checkout session status.

    Returns {"configured": False, ...} rather than a 500 when Stripe isn't
    configured — matches create_online_order_checkout's style, and means a
    caller polling with a stale/bookmarked session_id from before Stripe was
    ever set up (or after a key gets removed) gets a normal response to
    branch on instead of having to catch an exception.
    """
    from emergentintegrations.payments.stripe.checkout import StripeCheckout

    api_key = os.environ.get("STRIPE_API_KEY")
    if not api_key:
        return {"configured": False, "status": None, "paymentStatus": None, "amountTotal": None, "currency": None}

    host_url = str(http_request.base_url).rstrip("/")
    webhook_url = f"{host_url}/api/webhook/stripe"
    stripe_checkout = StripeCheckout(api_key=api_key, webhook_url=webhook_url)

    try:
        status = await stripe_checkout.get_checkout_status(session_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Checkout session not found")

    # Update payment transaction
    existing = await db.payment_transactions.find_one({"sessionId": session_id})
    if existing:
        new_status = "completed" if status.payment_status == "paid" else (
            "expired" if status.status == "expired" else "pending"
        )
        # Only update if not already completed (prevent double processing)
        if existing.get("paymentStatus") != "paid":
            await db.payment_transactions.update_one(
                {"sessionId": session_id},
                {"$set": {"status": new_status, "paymentStatus": status.payment_status, "updatedAt": datetime.utcnow().isoformat()}}
            )
            if status.payment_status == "paid":
                await _mark_online_order_paid_if_applicable(session_id)
                await _finalize_pos_sale_if_applicable(session_id)
                await _mark_reservation_deposit_paid_if_applicable(session_id)

    # Split-bill payments carry a splitSessionId on the payment doc — a
    # guest's own PaymentSuccess screen uses this to route back to their
    # table's bill instead of a staff-only "Back to POS" button, which
    # would otherwise dead-end a guest with no login.
    payment = existing or await db.payment_transactions.find_one({"sessionId": session_id}, {"_id": 0})
    split_session_id = (payment or {}).get("splitSessionId")

    return {
        "configured": True,
        "status": status.status,
        "paymentStatus": status.payment_status,
        "amountTotal": status.amount_total,
        "currency": status.currency,
        "splitSessionId": split_session_id,
    }

@router.post("/webhook/stripe")
async def stripe_webhook(request: Request, stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature")):
    """Handle Stripe webhook events for POS/online-order checkout sessions.

    Previously delegated verification to emergentintegrations.payments.stripe
    .checkout.StripeCheckout.handle_webhook — an opaque third-party wrapper
    that isn't installed in this environment (not in requirements.txt) and
    whose verification internals can't be inspected or trusted. Worse, the
    bare `except Exception` around it turned ANY failure — including a
    rejected/invalid signature — into an HTTP 200 {"received": True}, which
    is exactly the "silently return success" failure mode this endpoint must
    not have: it marks online orders and POS sales as paid. Now verified
    directly with the official `stripe` SDK (the same package and pattern
    already used by refund_stripe_payment in this file and by
    routes/licensing.py's webhook), and fails closed — 503 when no secret is
    configured, 400 on a bad/missing signature — instead of ever reporting
    received:true for something that wasn't verified.
    """
    import stripe

    api_key = os.environ.get("STRIPE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Stripe not configured")
    stripe.api_key = api_key

    # Reuses STRIPE_WEBHOOK_SECRET rather than a dedicated var: today only
    # one Stripe webhook secret is documented/configured for this deployment
    # (README.md). If this checkout endpoint and routes/licensing.py's
    # billing endpoint are ever registered with Stripe as two separate
    # webhook endpoints in production, Stripe issues a distinct signing
    # secret per endpoint URL and this should split into its own
    # STRIPE_CHECKOUT_WEBHOOK_SECRET rather than sharing one.
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if not secret:
        logging.getLogger(__name__).error("STRIPE_WEBHOOK_SECRET not set; rejecting checkout webhook instead of skipping signature verification")
        raise HTTPException(status_code=503, detail="Webhook signature verification is not configured")

    body = await request.body()
    try:
        # .to_dict() converts the stripe.Event (a StripeObject) to a plain
        # dict — StripeObject supports [] and attribute access but not
        # .get(), which the checks below rely on.
        event = stripe.Webhook.construct_event(body, stripe_signature, secret).to_dict()
    except (ValueError, stripe.error.SignatureVerificationError) as e:
        raise HTTPException(status_code=400, detail=f"Webhook verification failed: {e}")

    obj = (event.get("data") or {}).get("object") or {}
    if event.get("type") == "checkout.session.completed" and obj.get("payment_status") == "paid":
        session_id = obj.get("id")
        await db.payment_transactions.update_one(
            {"sessionId": session_id},
            {"$set": {"status": "completed", "paymentStatus": "paid", "updatedAt": datetime.utcnow().isoformat()}}
        )
        await _mark_online_order_paid_if_applicable(session_id)
        await _finalize_pos_sale_if_applicable(session_id)
        await _mark_reservation_deposit_paid_if_applicable(session_id)
    return {"received": True}

# ============ NUA CONNECT — INTEGRATIONS HUB API ============
# Real registry-driven integration hub. Status is never faked: a provider is
# "connected" only once its connector's test_connection has actually
# succeeded against that provider's real API, "pending_accreditation" for
# the 11 CDR banks always (regardless of credentials), and
# "not_implemented" for every provider that doesn't have connector code yet
# — never silently presented as available. See services/connect/.
from services.connect.registry import all_providers, get_provider
from services.connect import manager
from services.connect.base import ConnectorError


@router.get("/integrations")
async def get_integrations(user: dict = Depends(get_user)):
    """Every provider NUA Connect knows about, with this business's real,
    live status for each — not a hardcoded flag."""
    business_id = user.get("businessId")
    result = [await manager.describe_provider(business_id, meta) for meta in all_providers()]
    # Stripe secret keys are self-describing (sk_test_... vs sk_live_...) —
    # surfacing which one is active matters because there was previously no
    # way to tell from the UI whether a deployment was still taking
    # play-money test charges or real guest card payments, short of reading
    # the key value out of the environment directly.
    for p in result:
        if p["slug"] == "stripe":
            p["mode"] = _stripe_key_mode()
    return result


@router.get("/integrations/{slug}")
async def get_integration_detail(slug: str, user: dict = Depends(get_user)):
    meta = get_provider(slug)
    if not meta:
        raise HTTPException(status_code=404, detail="Unknown provider")
    return await manager.describe_provider(user.get("businessId"), meta)


@router.post("/integrations/{slug}/connect")
async def connect_integration(slug: str, data: dict, user: dict = Depends(require_owner_or_manager)):
    """Store credentials and (for providers with a real connector) actually
    test them against the provider before ever reporting 'connected'."""
    meta = get_provider(slug)
    if not meta:
        raise HTTPException(status_code=404, detail="Unknown provider")
    if not data:
        raise HTTPException(status_code=400, detail="Credentials required")
    try:
        result = await manager.connect_provider(user.get("businessId"), slug, data)
    except manager.NotImplementedProvider:
        raise HTTPException(status_code=501, detail=f"{meta.name} does not have a working connector yet")
    if result.get("status") == "error":
        raise HTTPException(status_code=502, detail=f"Could not verify {meta.name} credentials: {result.get('error')}")
    return result


@router.post("/integrations/{slug}/disconnect")
async def disconnect_integration(slug: str, user: dict = Depends(require_owner_or_manager)):
    meta = get_provider(slug)
    if not meta:
        raise HTTPException(status_code=404, detail="Unknown provider")
    await manager.disconnect_provider(user.get("businessId"), slug)
    return {"status": "disconnected"}


@router.post("/integrations/{slug}/sync")
async def sync_integration(slug: str, sync_type: str = "sales", user: dict = Depends(require_owner_or_manager)):
    """Trigger a real inbound sync. sync_type is one of catalog | sales | customers
    (whichever the provider's connector supports — see its `capabilities`)."""
    meta = get_provider(slug)
    if not meta:
        raise HTTPException(status_code=404, detail="Unknown provider")
    try:
        result = await manager.run_sync(user.get("businessId"), slug, sync_type)
    except manager.NotImplementedProvider:
        raise HTTPException(status_code=501, detail=f"{meta.name} does not have a working connector yet")
    except ConnectorError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return result


@router.get("/integrations/{slug}/credentials")
async def get_integration_credentials(slug: str, user: dict = Depends(require_owner_or_manager)):
    """Masked (last-4-only) view of stored credential field values — never
    the raw secret, which is only ever decrypted in-process for a call."""
    from services.connect.credentials import get_credentials_masked
    masked = await get_credentials_masked(user.get("businessId"), slug)
    if masked is None:
        raise HTTPException(status_code=404, detail="No credentials on file")
    return masked


# ---- Reporting / audit surface — the raw sync-run data end to end ----

@router.get("/integrations/sync-runs/history")
async def get_sync_history(provider: Optional[str] = None, limit: int = 50, user: dict = Depends(get_user)):
    return await manager.sync_history(user.get("businessId"), provider, limit)


@router.get("/integrations/sync-runs/{run_id}")
async def get_sync_run_detail(run_id: str, user: dict = Depends(get_user)):
    from services.connect.sync_log import get_sync_run
    run = await get_sync_run(user.get("businessId"), run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Sync run not found")
    return run


# ---- Inbound webhook — real-time push instead of waiting for the next poll ----

@router.post("/webhooks/square")
async def square_webhook(request: Request):
    """Square pushes order/customer/catalog change events here in real time.
    Square doesn't include NUA's businessId in the payload, so the owning
    business is identified the same way the signature itself is verified:
    by finding whose stored webhook signing key actually validates this
    request. That also means an unrecognized/forged request never touches
    any business's data — it's rejected before a business is even resolved.
    """
    from services.connect.connectors.square import SquareConnector
    from services.connect.credentials import get_credentials
    from services.connect.sync_log import SyncRun

    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    connector = SquareConnector()

    candidates = await db.integration_credentials.find(
        {"provider": "square"}, {"_id": 0, "businessId": 1}
    ).to_list(1000)

    for cand in candidates:
        business_id = cand["businessId"]
        creds = await get_credentials(business_id, "square")
        if creds and connector.verify_webhook(body, headers, creds):
            import json
            event = json.loads(body)
            async with SyncRun(business_id, "square", "webhook", direction="inbound") as run:
                await connector.handle_webhook_event(event, business_id, run)
            return {"received": True}

    raise HTTPException(status_code=401, detail="Signature verification failed")
