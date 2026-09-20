"""Online-order payment must stay bound to the storefront venue."""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_online_checkout_requires_the_orders_business(client, monkeypatch):
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    businesses = [
        {"id": "CHECKOUT-BIZ-A", "slug": "checkout-biz-a", "name": "Checkout A", "status": "active"},
        {"id": "CHECKOUT-BIZ-B", "slug": "checkout-biz-b", "name": "Checkout B", "status": "active"},
    ]
    order = {
        "id": "CHECKOUT-ORDER-A", "businessId": "CHECKOUT-BIZ-A", "total": 19.0,
        "paymentStatus": "unpaid", "status": "pending",
    }
    _run(db.businesses.insert_many(businesses))
    _run(db.online_orders.insert_one(order))
    try:
        wrong_venue = req(client, "POST", "/api/online/orders/checkout", json={
            "orderId": order["id"], "originUrl": "http://testserver", "business": "checkout-biz-b",
        })
        assert wrong_venue.status_code == 404

        correct_venue = req(client, "POST", "/api/online/orders/checkout", json={
            "orderId": order["id"], "originUrl": "http://testserver", "business": "checkout-biz-a",
        })
        assert correct_venue.status_code == 200, correct_venue.text[:200]
        assert correct_venue.json() == {"configured": False, "url": None}

        tracking = req(client, "GET", f"/api/online/orders/track/{order['id']}")
        assert tracking.status_code == 200
        assert tracking.json()["paymentStatus"] == "unpaid"
    finally:
        _run(db.online_orders.delete_one({"id": order["id"]}))
        _run(db.businesses.delete_many({"id": {"$in": [b["id"] for b in businesses]}}))
