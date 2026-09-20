"""Payment-integrity paths added across the Stripe/online-order rounds had no
test coverage at all — every one of these was previously verified only by
reading the diff. Three real failure modes, each with a fix already in
production code, get pinned here:

1. An online order's stock must go back on the shelf when a paid,
   already-accepted order is cancelled — and NOT when a still-pending
   order (never deducted) is cancelled, which would over-restock.
2. refund_stripe_payment must not call Stripe's refund API a second time
   against a charge that's already fully refunded (Stripe itself would
   reject it, but the guard exists so a flaky retry doesn't even try).
3. The Stripe-session -> POS-transaction finalizer's claim must be
   reclaimable after a crash (stale claim) but left alone while another
   request is still actively working it (fresh claim) — otherwise either
   a crashed process strands a paid sale forever, or two concurrent
   pollers ring up the same sale twice.
"""
import asyncio
from datetime import datetime, timedelta

import httpx

from conftest import req

_RealAsyncClient = httpx.AsyncClient


def _mock_client_factory(handler):
    def factory(*args, **kwargs):
        return _RealAsyncClient(transport=httpx.MockTransport(handler), timeout=kwargs.get("timeout", 10))
    return factory


def test_online_order_stock_deducts_on_accept_and_restores_on_cancel(client, owner_headers):
    loop = asyncio.get_event_loop()
    from database import db

    loop.run_until_complete(db.products.insert_one(
        {"id": "PAYINT-PROD-1", "name": "Test Burger", "category": "Mains",
         "stock": 10, "price": 15.0, "active": True, "businessId": "default"}
    ))
    try:
        r = req(client, "POST", "/api/online/orders?business=default", json={
            "channel": "pickup", "customerName": "Stock Test",
            "items": [{"productId": "PAYINT-PROD-1", "name": "Test Burger", "price": 15.0, "quantity": 3,
                       "category": "Mains"}],
        })
        assert r.status_code == 200, r.text[:200]
        order_id = r.json()["id"]

        # Still pending — accepting hasn't happened yet, stock is untouched.
        prod = loop.run_until_complete(db.products.find_one({"id": "PAYINT-PROD-1"}, {"_id": 0}))
        assert prod["stock"] == 10

        r = req(client, "PATCH", f"/api/online/orders/{order_id}/status", headers=owner_headers,
                json={"status": "accepted"})
        assert r.status_code == 200, r.text[:200]
        prod = loop.run_until_complete(db.products.find_one({"id": "PAYINT-PROD-1"}, {"_id": 0}))
        assert prod["stock"] == 7, "accepting an online order should deduct stock like a POS sale"

        r = req(client, "PATCH", f"/api/online/orders/{order_id}/status", headers=owner_headers,
                json={"status": "cancelled"})
        assert r.status_code == 200, r.text[:200]
        prod = loop.run_until_complete(db.products.find_one({"id": "PAYINT-PROD-1"}, {"_id": 0}))
        assert prod["stock"] == 10, "cancelling an accepted order should restore the deducted stock"
    finally:
        loop.run_until_complete(db.products.delete_one({"id": "PAYINT-PROD-1"}))


def test_cancelling_a_never_accepted_order_does_not_over_restock(client, owner_headers):
    loop = asyncio.get_event_loop()
    from database import db

    loop.run_until_complete(db.products.insert_one(
        {"id": "PAYINT-PROD-2", "name": "Test Fries", "category": "Sides",
         "stock": 5, "price": 6.0, "active": True, "businessId": "default"}
    ))
    try:
        r = req(client, "POST", "/api/online/orders?business=default", json={
            "channel": "pickup", "customerName": "Never Accepted",
            "items": [{"productId": "PAYINT-PROD-2", "name": "Test Fries", "price": 6.0, "quantity": 2,
                       "category": "Sides"}],
        })
        order_id = r.json()["id"]

        # Cancel directly from "pending" — stock was never deducted, so
        # cancelling must not add stock back (that would inflate on-hand
        # count above the true total).
        r = req(client, "PATCH", f"/api/online/orders/{order_id}/status", headers=owner_headers,
                json={"status": "cancelled"})
        assert r.status_code == 200, r.text[:200]
        prod = loop.run_until_complete(db.products.find_one({"id": "PAYINT-PROD-2"}, {"_id": 0}))
        assert prod["stock"] == 5
    finally:
        loop.run_until_complete(db.products.delete_one({"id": "PAYINT-PROD-2"}))


def test_refund_stripe_payment_skips_an_already_refunded_charge(monkeypatch):
    import stripe
    from routes.integrations import refund_stripe_payment

    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_fake")
    create_calls = []
    monkeypatch.setattr(stripe.checkout.Session, "retrieve", lambda session_id: {"payment_intent": "pi_already_refunded"})
    monkeypatch.setattr(stripe.PaymentIntent, "retrieve",
                         lambda pi: {"charges": {"data": [{"refunded": True}]}})
    monkeypatch.setattr(stripe.Refund, "create", lambda **kw: create_calls.append(kw))

    loop = asyncio.get_event_loop()
    result = loop.run_until_complete(refund_stripe_payment("cs_test_already_refunded"))

    assert result is True
    assert create_calls == [], "must not call Stripe's refund API against an already-refunded charge"


def test_refund_stripe_payment_refunds_an_unrefunded_charge(monkeypatch):
    import stripe
    from routes.integrations import refund_stripe_payment

    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_fake")
    create_calls = []
    monkeypatch.setattr(stripe.checkout.Session, "retrieve", lambda session_id: {"payment_intent": "pi_needs_refund"})
    monkeypatch.setattr(stripe.PaymentIntent, "retrieve",
                         lambda pi: {"charges": {"data": [{"refunded": False}]}})
    monkeypatch.setattr(stripe.Refund, "create", lambda **kw: create_calls.append(kw))

    loop = asyncio.get_event_loop()
    result = loop.run_until_complete(refund_stripe_payment("cs_test_needs_refund"))

    assert result is True
    assert create_calls == [{"payment_intent": "pi_needs_refund"}]


def test_crypto_checkout_stores_the_held_tab_id_for_later_cleanup(client, owner_headers, monkeypatch):
    """POSTerminal's handleCryptoCheckout auto-holds the cart (db.pos_tabs)
    and passes the resulting tab id as heldTabId — this proves it actually
    rides onto the payment_transactions doc, which is what lets finalize
    find and clean it up later. Crypto is the fully-testable checkout path
    in this sandbox (Stripe's SDK isn't installed here); Stripe shares the
    exact same `for k in (...)` sibling-field line in integrations.py."""
    import services.coinbase_commerce as cc
    from database import db

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {
            "id": "charge-uuid-held", "code": "HELDCODE1",
            "hosted_url": "https://commerce.coinbase.com/charges/HELDCODE1",
            "timeline": [{"status": "NEW"}],
        }})
    monkeypatch.setenv("COINBASE_COMMERCE_API_KEY", "cc-test-key")
    monkeypatch.setattr(cc.httpx, "AsyncClient", _mock_client_factory(handler))

    try:
        r = req(client, "POST", "/api/crypto/checkout", headers=owner_headers, json={
            "amount": 42.0, "heldTabId": "TAB-FROM-POS-1",
            "sale": {
                "items": [{"productId": "P1", "productName": "Item", "quantity": 1, "price": 42.0}],
                "paymentMethod": "Crypto", "location": "front", "cashier": "Test Cashier",
                "orderType": "dine_in",
            },
        })
        assert r.status_code == 200, r.text[:200]

        loop = asyncio.get_event_loop()
        payment = loop.run_until_complete(
            db.payment_transactions.find_one({"sessionId": "HELDCODE1"}, {"_id": 0}))
        assert payment["heldTabId"] == "TAB-FROM-POS-1"
    finally:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(db.payment_transactions.delete_many({"sessionId": "HELDCODE1"}))


def test_finalize_pos_sale_recovers_a_stale_claim(monkeypatch):
    """A claim left in 'pending' for over 2 minutes means the process that
    claimed it died before finishing — the next poll/webhook must be able
    to pick it back up rather than leaving the sale stranded forever."""
    import routes.transactions
    from routes.integrations import _finalize_pos_sale_if_applicable
    from database import db

    finalize_calls = []

    class FakeTxn:
        id = "TXN-RECOVERED"

    async def fake_create_transaction(payload, user):
        finalize_calls.append((payload, user))
        return FakeTxn()

    monkeypatch.setattr(routes.transactions, "create_transaction", fake_create_transaction)

    loop = asyncio.get_event_loop()
    stale_claim_time = (datetime.utcnow() - timedelta(minutes=5)).isoformat()
    loop.run_until_complete(db.payment_transactions.insert_one({
        "id": "SPAY-STALE", "sessionId": "cs_stale_claim", "kind": "pos_sale",
        "transactionId": "pending", "transactionClaimedAt": stale_claim_time,
        "salePayload": {"items": [], "paymentMethod": "card", "location": "front", "cashier": "Test Cashier"},
        "cashierUser": {"id": "U1", "name": "Test Cashier", "role": "cashier"},
    }))
    try:
        loop.run_until_complete(_finalize_pos_sale_if_applicable("cs_stale_claim"))
        assert len(finalize_calls) == 1, "a stale (crashed) claim should be reclaimed and finalized"
        doc = loop.run_until_complete(db.payment_transactions.find_one({"sessionId": "cs_stale_claim"}, {"_id": 0}))
        assert doc["transactionId"] == "TXN-RECOVERED"
    finally:
        loop.run_until_complete(db.payment_transactions.delete_one({"sessionId": "cs_stale_claim"}))


def test_pos_tabs_stores_auto_hold_metadata(client, owner_headers):
    """POST /pos/tabs must persist the autoHold/checkoutProvider fields
    POSTerminal sets when it parks a cart before redirecting to a hosted
    checkout — without these, GET /pos/tabs can't distinguish a deliberate
    manual Hold from an in-flight payment redirect, and the POS screen
    can't tell staff which is which."""
    r = req(client, "POST", "/api/pos/tabs", headers=owner_headers, json={
        "name": "Card (Stripe) — auto", "cart": [{"id": "P1", "quantity": 1, "price": 10}],
        "autoHold": True, "checkoutProvider": "stripe", "checkoutSessionId": "cs_test_123",
    })
    assert r.status_code == 200, r.text[:200]
    tab = r.json()
    try:
        assert tab["autoHold"] is True
        assert tab["checkoutProvider"] == "stripe"
        assert tab["checkoutSessionId"] == "cs_test_123"

        listed = req(client, "GET", "/api/pos/tabs", headers=owner_headers).json()
        found = next(t for t in listed if t["id"] == tab["id"])
        assert found["autoHold"] is True
    finally:
        req(client, "DELETE", f"/api/pos/tabs/{tab['id']}", headers=owner_headers)


def test_pos_tabs_defaults_auto_hold_to_false_for_manual_holds(client, owner_headers):
    """The existing manual "Hold" button doesn't send autoHold at all —
    must default to False, not error or default to True (which would make
    every ordinary held tab show up in the abandoned-checkout banner)."""
    r = req(client, "POST", "/api/pos/tabs", headers=owner_headers, json={
        "name": "Manual hold", "cart": [],
    })
    assert r.status_code == 200, r.text[:200]
    tab = r.json()
    try:
        assert tab["autoHold"] is False
    finally:
        req(client, "DELETE", f"/api/pos/tabs/{tab['id']}", headers=owner_headers)


def test_finalize_pos_sale_cleans_up_its_held_tab_after_success(monkeypatch):
    """POSTerminal auto-holds the cart (db.pos_tabs) right before redirecting
    to Stripe/Crypto so an abandoned checkout doesn't just vanish (see
    handleStripeCheckout/handleCryptoCheckout). Once the sale actually
    lands, that hold has done its job and must be cleared — otherwise a
    *successful* payment would still show up as "held sale pending
    payment" on the POS screen."""
    import routes.transactions
    from routes.integrations import _finalize_pos_sale_if_applicable
    from database import db

    async def fake_create_transaction(payload, user):
        class FakeTxn: id = "TXN-HELD-CLEANUP"
        return FakeTxn()
    monkeypatch.setattr(routes.transactions, "create_transaction", fake_create_transaction)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(db.pos_tabs.insert_one({
        "id": "TAB-HELD-1", "name": "Card (Stripe) — held", "cart": [], "status": "open",
        "autoHold": True, "checkoutProvider": "stripe",
    }))
    loop.run_until_complete(db.payment_transactions.insert_one({
        "id": "SPAY-HELD-1", "sessionId": "cs_held_success", "kind": "pos_sale", "heldTabId": "TAB-HELD-1",
        "salePayload": {"items": [], "paymentMethod": "card", "location": "front", "cashier": "Test Cashier"},
        "cashierUser": {"id": "U1", "name": "Test Cashier", "role": "cashier"},
    }))
    try:
        loop.run_until_complete(_finalize_pos_sale_if_applicable("cs_held_success"))
        tab = loop.run_until_complete(db.pos_tabs.find_one({"id": "TAB-HELD-1"}, {"_id": 0}))
        assert tab is None, "the auto-hold tab must be deleted once its sale is actually rung up"
        doc = loop.run_until_complete(db.payment_transactions.find_one({"sessionId": "cs_held_success"}, {"_id": 0}))
        assert doc["transactionId"] == "TXN-HELD-CLEANUP", "held-tab cleanup must not block the sale itself finalizing"
    finally:
        loop.run_until_complete(db.payment_transactions.delete_one({"sessionId": "cs_held_success"}))
        loop.run_until_complete(db.pos_tabs.delete_one({"id": "TAB-HELD-1"}))


def test_finalize_pos_sale_without_a_held_tab_does_not_touch_pos_tabs(monkeypatch):
    """A normal Stripe/Crypto payment with no heldTabId (e.g. the guest
    bill-split checkout, which never creates a POS hold) must finalize
    exactly as before — no accidental db.pos_tabs writes."""
    import routes.transactions
    from routes.integrations import _finalize_pos_sale_if_applicable
    from database import db

    async def fake_create_transaction(payload, user):
        class FakeTxn: id = "TXN-NO-HOLD"
        return FakeTxn()
    monkeypatch.setattr(routes.transactions, "create_transaction", fake_create_transaction)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(db.payment_transactions.insert_one({
        "id": "SPAY-NOHOLD-1", "sessionId": "cs_no_hold", "kind": "pos_sale",
        "salePayload": {"items": [], "paymentMethod": "card", "location": "front", "cashier": "Test Cashier"},
        "cashierUser": {"id": "U1", "name": "Test Cashier", "role": "cashier"},
    }))
    try:
        loop.run_until_complete(_finalize_pos_sale_if_applicable("cs_no_hold"))
        doc = loop.run_until_complete(db.payment_transactions.find_one({"sessionId": "cs_no_hold"}, {"_id": 0}))
        assert doc["transactionId"] == "TXN-NO-HOLD"
    finally:
        loop.run_until_complete(db.payment_transactions.delete_one({"sessionId": "cs_no_hold"}))


def test_finalize_pos_sale_leaves_a_fresh_claim_alone(monkeypatch):
    """A claim made moments ago is presumably still being worked by another
    in-flight request — a concurrent poll/webhook for the same session must
    not re-finalize it, or the same sale would be rung up twice."""
    import routes.transactions
    from routes.integrations import _finalize_pos_sale_if_applicable
    from database import db

    finalize_calls = []

    async def fake_create_transaction(payload, user):
        finalize_calls.append((payload, user))
        class FakeTxn: id = "TXN-SHOULD-NOT-HAPPEN"
        return FakeTxn()

    monkeypatch.setattr(routes.transactions, "create_transaction", fake_create_transaction)

    loop = asyncio.get_event_loop()
    fresh_claim_time = datetime.utcnow().isoformat()
    loop.run_until_complete(db.payment_transactions.insert_one({
        "id": "SPAY-FRESH", "sessionId": "cs_fresh_claim", "kind": "pos_sale",
        "transactionId": "pending", "transactionClaimedAt": fresh_claim_time,
        "salePayload": {"items": [], "paymentMethod": "card", "location": "front", "cashier": "Test Cashier"},
        "cashierUser": {"id": "U1", "name": "Test Cashier", "role": "cashier"},
    }))
    try:
        loop.run_until_complete(_finalize_pos_sale_if_applicable("cs_fresh_claim"))
        assert finalize_calls == [], "a fresh, still-in-flight claim must not be reclaimed"
        doc = loop.run_until_complete(db.payment_transactions.find_one({"sessionId": "cs_fresh_claim"}, {"_id": 0}))
        assert doc["transactionId"] == "pending"
    finally:
        loop.run_until_complete(db.payment_transactions.delete_one({"sessionId": "cs_fresh_claim"}))
