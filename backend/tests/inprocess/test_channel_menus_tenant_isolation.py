"""routes/channel_menus.py had zero businessId scoping across products,
channel_menus, and transactions queries — any business's channel-pricing
overrides, AI prep-time sync, and AI slow-mover discounts could read and
write against every other business's product catalogue.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Channel Menus Test Owner", "email": email, "password": "ChannelMenusTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "ChannelMenusTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def test_a_different_businesss_product_is_not_in_the_channel_menu_or_bulk_priced(client, owner_headers):
    other = _login_as(client, owner_headers, email="channelmenus.other@nua.com", business_id="channelmenus-other-biz")

    created = req(client, "POST", "/api/products", headers=other, json={
        "name": "Other Biz Channel Product", "price": 10.0, "cost": 4.0, "category": "Test",
        "stock": 5, "sku": "CHMENU-OTHER-1"})
    assert created.status_code == 200, created.text[:200]
    product_id = created.json()["id"]
    try:
        listing = req(client, "GET", "/api/channel-menus/website", headers=owner_headers).json()
        assert product_id not in {row["productId"] for row in listing}

        bulk = req(client, "POST", "/api/channel-menus/website/bulk-price", headers=owner_headers,
                   json={"deltaPercent": -50})
        assert bulk.status_code == 200, bulk.text[:200]

        override = _run(db.channel_menus.find_one({"channel": "website", "productId": product_id}, {"_id": 0}))
        assert override is None, "a bulk price change from one business must not touch another business's product"
    finally:
        _run(db.products.delete_one({"id": product_id}))
        _run(db.channel_menus.delete_many({"productId": product_id}))


def test_patch_row_rejects_another_businesss_product_id(client, owner_headers):
    """The write itself was already tenant-scoped and couldn't leak data,
    but without an ownership/existence check it would silently create a
    channel-menu row pointing at a product that doesn't exist, or that
    belongs to a different business."""
    other = _login_as(client, owner_headers, email="channelmenus.patch-other@nua.com",
                       business_id="channelmenus-patch-other-biz")
    created = req(client, "POST", "/api/products", headers=other, json={
        "name": "Other Biz Patch Product", "price": 8.0, "cost": 3.0, "category": "Test",
        "stock": 5, "sku": "CHMENU-PATCH-OTHER-1"})
    assert created.status_code == 200, created.text[:200]
    product_id = created.json()["id"]
    try:
        r = req(client, "POST", "/api/channel-menus/website/patch", headers=owner_headers,
                json={"productId": product_id, "available": False})
        assert r.status_code == 404, r.text[:200]
        override = _run(db.channel_menus.find_one({"channel": "website", "productId": product_id}, {"_id": 0}))
        assert override is None, "no override should have been created for a foreign/unowned productId"
    finally:
        _run(db.products.delete_one({"id": product_id}))
        _run(db.channel_menus.delete_many({"productId": product_id}))


def test_patch_row_rejects_nonexistent_product_id(client, owner_headers):
    r = req(client, "POST", "/api/channel-menus/website/patch", headers=owner_headers,
            json={"productId": "no-such-product-id", "available": False})
    assert r.status_code == 404, r.text[:200]


def test_ai_prep_times_reads_kitchen_heat_from_the_live_ticket_collection(client, owner_headers):
    """ai_prep_times used to count db.kds_orders — a collection nothing in
    this codebase ever writes to — so kitchen heat was always reported
    "cool" and the prep-time multiplier applied to every channel-menu
    product was always a no-op 1.0x, regardless of real kitchen load.
    Live tickets are written to kitchen_orders (routes/kitchen.py)."""
    # Product has no prepTimeMin field of its own — ai_prep_times falls back
    # to a 12-minute base (p.get("prepTimeMin", 12)) for every product.
    created = req(client, "POST", "/api/products", headers=owner_headers, json={
        "name": "Heat Test Product", "price": 10.0, "cost": 4.0, "category": "Test",
        "stock": 5, "sku": "CHMENU-HEAT-1"})
    assert created.status_code == 200, created.text[:200]
    product_id = created.json()["id"]
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    ticket_ids = [f"heat-test-{i}" for i in range(11)]
    try:
        _run(db.kitchen_orders.insert_many([
            {"id": tid, "businessId": "default", "status": "preparing", "createdAt": now_iso, "items": []}
            for tid in ticket_ids
        ]))
        r = req(client, "POST", "/api/channel-menus/website/ai-prep-times", headers=owner_headers)
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        # >= not ==: other tests in the full suite can leave their own
        # active "default"-business tickets lying around at this point;
        # what matters is that these 11 alone are enough to register, not
        # the exact count.
        assert body["activeTickets"] >= 11
        assert body["heat"] == "very_high"
        assert body["multiplier"] == 1.5
        override = _run(db.channel_menus.find_one(
            {"channel": "website", "productId": product_id}, {"_id": 0}))
        assert override["prepTimeMin"] == 18  # 12 (default base) * 1.5
    finally:
        _run(db.products.delete_one({"id": product_id}))
        _run(db.channel_menus.delete_many({"productId": product_id}))
        _run(db.kitchen_orders.delete_many({"id": {"$in": ticket_ids}}))
