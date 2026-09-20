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
