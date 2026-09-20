"""Two things fixed together:

1. routes/phase_ef.py's AI Phone Agent (/phone-agent/simulate) only ever
   logged a {"action": "order_drafted", "items": [...]} entry for a
   caller's "order" intent — it never created a real order, regardless of
   PhoneAgent.jsx's own copy implying it drafts real orders from calls.
   Fixed to match spoken item names against the caller's own product
   catalogue and, for real matches, actually send the order to the
   kitchen via services/channel_orders.create_ticket — same mechanism a
   kiosk or an accepted online order uses. _match_product_by_name is a
   pure function, tested directly here (no LLM call needed).

2. services/channel_orders.py (the shared "turn a channel order into a
   real kitchen ticket" service, used by online-order acceptance, kiosk
   checkout, and now the phone agent) had zero businessId scoping: the
   external_id idempotency lookup and the category-enrichment product
   lookup could both silently cross business lines on a shared
   deployment. Fixed with the same optional business_id, actor-context-
   default pattern used throughout this codebase. The LLM classification
   step itself can't be exercised in this sandbox (emergentintegrations
   isn't installed / no outbound network), so this tests create_ticket
   directly — the piece that actually needed the tenant-isolation fix.
"""
import asyncio

from database import db
from routes.phase_ef import _match_product_by_name
from services import channel_orders


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_match_product_by_name_exact_and_substring():
    catalogue = [
        {"id": "P1", "name": "Flat White", "price": 4.5},
        {"id": "P2", "name": "Large Pepperoni Pizza", "price": 22.0},
        {"id": "P3", "name": "Coke", "price": 3.5},
    ]
    assert _match_product_by_name(catalogue, "Flat White")["id"] == "P1"
    assert _match_product_by_name(catalogue, "flat white")["id"] == "P1"
    assert _match_product_by_name(catalogue, "pepperoni pizza")["id"] == "P2"
    assert _match_product_by_name(catalogue, "large coke")["id"] == "P3"
    assert _match_product_by_name(catalogue, "a quantum computer") is None
    assert _match_product_by_name(catalogue, "") is None


def test_create_ticket_external_id_idempotency_is_scoped_per_business():
    items = [{"productId": "PROD-X", "productName": "Test Item", "quantity": 1, "price": 5.0, "category": "Mains"}]
    try:
        first = _run(channel_orders.create_ticket(
            items, order_type="takeaway", source="test", external_id="EXT-SHARED-1",
            actor="tester", business_id="phone-agent-biz-a",
        ))
        assert first is not None
        assert first["businessId"] == "phone-agent-biz-a"

        # Same external_id, different business — before the fix this
        # would have returned business A's ticket (or, worse, silently
        # been treated as "already exists" and skipped entirely).
        second = _run(channel_orders.create_ticket(
            items, order_type="takeaway", source="test", external_id="EXT-SHARED-1",
            actor="tester", business_id="phone-agent-biz-b",
        ))
        assert second is not None
        assert second["id"] != first["id"], "a different business's external_id must not collide with another's"
        assert second["businessId"] == "phone-agent-biz-b"

        # Replaying the SAME business's external_id must still be idempotent.
        replay = _run(channel_orders.create_ticket(
            items, order_type="takeaway", source="test", external_id="EXT-SHARED-1",
            actor="tester", business_id="phone-agent-biz-a",
        ))
        assert replay["id"] == first["id"]
    finally:
        _run(db.kitchen_orders.delete_many({"externalId": "EXT-SHARED-1"}))


def test_create_ticket_category_enrichment_does_not_leak_across_businesses():
    _run(db.products.insert_one({
        "id": "PROD-CROSSBIZ", "name": "Other Biz Special", "category": "Secret Category",
        "businessId": "channel-orders-other-biz",
    }))
    try:
        ticket = _run(channel_orders.create_ticket(
            [{"productId": "PROD-CROSSBIZ", "productName": "Other Biz Special", "quantity": 1, "price": 9.0}],
            order_type="takeaway", source="test", external_id="EXT-CATEGORY-1",
            actor="tester", business_id="channel-orders-my-biz",
        ))
        assert ticket is not None
        item = ticket["items"][0]
        assert item.get("category") != "Secret Category", (
            "must not enrich a line item's category from another business's product"
        )
    finally:
        _run(db.products.delete_one({"id": "PROD-CROSSBIZ"}))
        _run(db.kitchen_orders.delete_many({"externalId": "EXT-CATEGORY-1"}))
