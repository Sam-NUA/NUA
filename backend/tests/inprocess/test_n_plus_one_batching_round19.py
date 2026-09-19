"""Round 19 N+1 batching — same pattern as round 18's batching fixes:
functional behavior unchanged, correctness locked in independent of how
the queries are batched.
"""
import asyncio
import uuid

from conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_promo_analytics_sums_redemption_revenue_via_batched_lookup(client, owner_headers):
    from database import db
    from datetime import datetime, timezone

    txn_id = str(uuid.uuid4())
    voucher_id = str(uuid.uuid4())
    _run(db.transactions.delete_many({"id": txn_id}))
    _run(db.transactions.insert_one({"businessId": "default", "id": txn_id, "total": 42.5, "status": "completed"}))
    _run(db.vouchers.delete_many({"id": voucher_id}))
    _run(db.vouchers.insert_one({"businessId": "default",
        "id": voucher_id, "code": "PROMO-N1-TEST", "sourceType": "promotion",
        "faceValue": 10.0, "status": "redeemed", "redemptionCount": 1,
        "issuedAt": datetime.now(timezone.utc).isoformat(),
        "redemptions": [{"transactionId": txn_id, "amount": 10.0}],
    }))

    r = req(client, "GET", "/api/promo-analytics/summary", headers=owner_headers, params={"days": 30})
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert body["revenueGenerated"] >= 42.5


def test_ai_discount_slow_movers_prices_unsold_products_without_a_second_lookup(client, owner_headers):
    from database import db

    product_id = str(uuid.uuid4())
    _run(db.products.delete_many({"id": product_id}))
    _run(db.products.insert_one({"businessId": "default", "id": product_id, "name": "Slow Mover Widget", "price": 20.0, "category": "Test", "stock": 5}))

    r = req(client, "POST", "/api/channel-menus/online/ai-discount-slow", headers=owner_headers,
            json={"discountPercent": 10, "bottomN": 50, "daysWindow": 7})
    assert r.status_code == 200, r.text[:200]
    applied = r.json()["applied"]
    row = next((a for a in applied if a["productId"] == product_id), None)
    assert row is not None, "unsold product was not priced"
    assert row["basePrice"] == 20.0
    assert row["newPrice"] == 18.0
