"""ai_discount_slow_movers (routes/channel_menus.py) matched transactions on
a `createdAt` field. The real POS checkout path (routes/transactions.py's
create_transaction) never writes `createdAt` on a transaction -- it only
ever writes `timestamp`. So every POS-originated sale was silently excluded
from the "did this sell in the last N days" aggregation, making products
that genuinely sold via POS look unsold and eligible for the slow-mover
discount.
"""
import asyncio
import uuid
from datetime import datetime, timezone

from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_a_product_sold_via_real_pos_checkout_is_not_treated_as_a_slow_mover(client, owner_headers):
    from database import db

    product_id = str(uuid.uuid4())
    txn_id = str(uuid.uuid4())
    _run(db.products.insert_one({
        "businessId": "default", "id": product_id, "name": "Freshly Sold Widget",
        "price": 20.0, "category": "Test", "stock": 5,
    }))
    # Mirrors the shape create_transaction actually inserts for a real POS
    # sale: a `timestamp` datetime, no `createdAt` at all.
    _run(db.transactions.insert_one({
        "businessId": "default", "id": txn_id, "status": "completed",
        "timestamp": datetime.now(timezone.utc),
        "items": [{"productId": product_id, "productName": "Freshly Sold Widget", "quantity": 3}],
    }))
    try:
        # ai_discount_slow_movers always ranks every *unsold* product ahead
        # of every *sold* one (weakest = unsold + rows, truncated to
        # bottomN), regardless of qty -- so with a small bottomN, other
        # tests' leftover unsold "default"-business products (this suite
        # shares one in-memory Mongo across the whole run; nothing here
        # cleans those up) can push a genuinely sold product out of the
        # response before this test's own assertion ever runs. bottomN this
        # large guarantees our product is included no matter what the rest
        # of the suite left behind.
        r = req(client, "POST", "/api/channel-menus/online/ai-discount-slow", headers=owner_headers,
                json={"discountPercent": 10, "bottomN": 1000000, "daysWindow": 7})
        assert r.status_code == 200, r.text[:200]
        applied = r.json()["applied"]
        row = next((a for a in applied if a["productId"] == product_id), None)
        assert row is not None, "expected this product to appear in the bottom-N ranking"
        # Buggy behavior: matching on createdAt (which POS transactions never
        # set) finds no sale at all, so this reports soldQty=0 for a product
        # that really sold 3 units via a genuine POS transaction.
        assert row["soldQty"] == 3, (
            f"expected the real POS sale (qty=3) to be counted, got soldQty={row['soldQty']} "
            "-- the date-field match excluded the real transaction"
        )
    finally:
        _run(db.products.delete_many({"id": product_id}))
        _run(db.transactions.delete_many({"id": txn_id}))
