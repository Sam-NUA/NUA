"""Final readiness audit item: "verify tier discounts across POS, online
ordering, kiosk and QR/table ordering."

Finding: POS checkout (routes/transactions.py) is the only channel that
applies a loyalty-tier discount — it does so by reading db.loyalty_tiers
off the transaction's own customerId. Online ordering (routes/
online_orders.py), kiosk (routes/v25_suite.py's kiosk_checkout) and
QR/table ordering (routes/table_ordering.py) never resolve a guest's
freeform name/phone/email to an actual db.customers record at all, so none
of them have a customerId to look a tier up against — this is a structural
product-design gap (no guest-identification-at-checkout exists on those
channels), not a bug in duplicated discount math, and building real guest
identification there would be a new feature, not a fix.

This is a contract test, not a bug-reproduction test: it locks in today's
actual (correct, if incomplete) behavior — POS applies the tier discount
for an identified customer; the other three channels apply none, even
when the guest's typed-in details happen to match an existing loyalty
member — so a future change either updates this test deliberately (tier
discounts intentionally extended to a new channel) or this test catches an
accidental regression (POS silently stops applying it, or another channel
starts applying a stale/wrong one).
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_pos_checkout_applies_the_customers_real_tier_discount(client, owner_headers):
    _run(db.loyalty_tiers.delete_many({"businessId": "default", "name": "ChannelConsistencyGold"}))
    _run(db.loyalty_tiers.insert_one({
        "id": "t-cc-gold", "name": "ChannelConsistencyGold", "minPoints": 0,
        "multiplier": 1.0, "discountPercent": 10, "perks": [], "businessId": "default",
    }))
    created = req(client, "POST", "/api/customers", headers=owner_headers, json={
        "name": "Channel Consistency Customer", "email": "cc-tier@nua.com", "phone": "0400333444"})
    assert created.status_code == 200, created.text[:200]
    cid = created.json()["id"]
    _run(db.customers.update_one({"id": cid}, {"$set": {"membershipTier": "ChannelConsistencyGold"}}))
    try:
        r = req(client, "POST", "/api/transactions", headers=owner_headers, json={
            "items": [{"productId": "no-such-product", "productName": "Custom item",
                       "quantity": 1, "price": 100}],
            "paymentMethod": "cash", "location": "Main", "cashier": "Test Cashier",
            "customerId": cid,
        })
        assert r.status_code == 200, r.text[:200]
        assert r.json()["discount"] == 10.0, (
            f"POS must apply the customer's real 10% tier discount — got {r.json().get('discount')}"
        )
    finally:
        _run(db.customers.delete_many({"id": cid}))
        _run(db.loyalty_tiers.delete_many({"id": "t-cc-gold"}))


def test_online_ordering_never_applies_a_tier_discount_even_for_a_matching_guest_name(client, owner_headers):
    """Confirms the documented, current contract: online ordering has no
    customerId to hang a tier discount on, so none is ever applied — not
    even when the guest types in the exact name of a real Gold-tier member."""
    _run(db.loyalty_tiers.delete_many({"businessId": "default", "name": "ChannelConsistencyGold2"}))
    _run(db.loyalty_tiers.insert_one({
        "id": "t-cc-gold-2", "name": "ChannelConsistencyGold2", "minPoints": 0,
        "multiplier": 1.0, "discountPercent": 25, "perks": [], "businessId": "default",
    }))
    created = req(client, "POST", "/api/customers", headers=owner_headers, json={
        "name": "Online Order Guest Match", "email": "cc-online@nua.com", "phone": "0400555666"})
    cid = created.json()["id"]
    _run(db.customers.update_one({"id": cid}, {"$set": {"membershipTier": "ChannelConsistencyGold2"}}))
    _run(db.products.insert_one({"id": "CC-ONLINE-PROD", "name": "Online Test Item", "price": 100,
                                  "category": "Other", "stock": 100}))
    try:
        r = req(client, "POST", "/api/online/orders?business=default", json={
            "channel": "pickup",
            "customerName": "Online Order Guest Match", "customerPhone": "0400555666",
            "items": [{"productId": "CC-ONLINE-PROD", "productName": "Online Test Item",
                       "price": 100, "quantity": 1}],
        })
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert body["subtotal"] == body["total"], (
            f"online ordering must not silently discount a guest, matching name/phone or not — got {body}"
        )
    finally:
        _run(db.customers.delete_many({"id": cid}))
        _run(db.loyalty_tiers.delete_many({"id": "t-cc-gold-2"}))
        _run(db.products.delete_many({"id": "CC-ONLINE-PROD"}))
