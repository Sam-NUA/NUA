"""The rules engine's event catalog was entirely reactive — inventory.low_stock
and inventory.stockout only fire once a product has already crossed a
threshold or hit zero, which can be almost no lead time for a fast-selling
item. predictive_signals.py projects days-remaining from real sales velocity
and emits inventory.predicted_stockout through the same emit_event() pipeline
before that happens. This exercises the projection math and the dedupe that
keeps the hourly scheduler from re-emitting for the same product every hour.
"""
import asyncio
from conftest import req
from services import predictive_signals
from database import db


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _sale(client, headers, *, product_id, quantity):
    return req(client, "POST", "/api/transactions", headers=headers, json={
        "items": [{"productId": product_id, "productName": "Predictive Test Item",
                   "quantity": quantity, "price": 10}],
        "paymentMethod": "cash", "location": "Main", "cashier": "Test Cashier",
    })


def test_a_fast_selling_low_stock_product_is_predicted_to_run_out(client, owner_headers):
    # Transactions really deduct stock, so the starting count has to survive
    # the sales below with something left — this isn't "stock=4, sell a lot"
    # (that just hits inventory.stockout's territory, stock<=0, which this
    # function deliberately excludes), it's "sell fast enough that the stock
    # remaining after the dust settles still won't last 2 more days."
    product = req(client, "POST", "/api/products", headers=owner_headers, json={
        "name": "Predictive Fast Seller", "price": 10, "cost": 4, "category": "Test",
        "stock": 100, "sku": "PRED-FAST-1"})
    assert product.status_code == 200, product.text[:200]
    pid = product.json()["id"]

    # 90 units sold today → ~12.9/day averaged over the 7-day lookback
    # window, 10 left → well under a day of runway, inside the 2-day horizon.
    for _ in range(3):
        r = _sale(client, owner_headers, product_id=pid, quantity=30)
        assert r.status_code == 200, r.text[:200]

    predictions = _run(predictive_signals.compute_predicted_stockouts(business_id="default"))
    match = next((p for p in predictions if p["productId"] == pid), None)
    assert match is not None, "a product selling ~13/day with 10 left must be projected to run out"
    assert match["daysRemaining"] < 2.0
    assert match["currentStock"] == 10


def test_a_slow_selling_well_stocked_product_is_not_predicted(client, owner_headers):
    product = req(client, "POST", "/api/products", headers=owner_headers, json={
        "name": "Predictive Slow Seller", "price": 10, "cost": 4, "category": "Test",
        "stock": 500, "sku": "PRED-SLOW-1"})
    pid = product.json()["id"]
    _sale(client, owner_headers, product_id=pid, quantity=1)

    predictions = _run(predictive_signals.compute_predicted_stockouts(business_id="default"))
    assert all(p["productId"] != pid for p in predictions), \
        "500 units at ~1/day is nowhere near the 2-day horizon and must not be flagged"


def test_preview_endpoint_does_not_write_rule_events(client, owner_headers):
    before = _run(db.rule_events.count_documents({}))
    r = req(client, "GET", "/api/rules/predictive/stockouts", headers=owner_headers)
    assert r.status_code == 200, r.text[:200]
    assert "predictions" in r.json()
    after = _run(db.rule_events.count_documents({}))
    assert after == before


def test_scan_emits_once_then_dedupes_within_the_window(client, owner_headers):
    product = req(client, "POST", "/api/products", headers=owner_headers, json={
        "name": "Predictive Dedupe Item", "price": 10, "cost": 4, "category": "Test",
        "stock": 100, "sku": "PRED-DEDUPE-1"})
    pid = product.json()["id"]
    for _ in range(2):
        _sale(client, owner_headers, product_id=pid, quantity=40)

    first = req(client, "POST", "/api/rules/predictive/scan", headers=owner_headers)
    assert first.status_code == 200, first.text[:200]
    assert any(p["productId"] == pid for p in first.json()["predictions"])
    first_emitted = _run(db.rule_events.count_documents(
        {"type": "inventory.predicted_stockout", "entityId": pid}))
    assert first_emitted == 1

    # Same product, same window — must not emit a second event.
    second = req(client, "POST", "/api/rules/predictive/scan", headers=owner_headers)
    assert second.status_code == 200, second.text[:200]
    second_emitted = _run(db.rule_events.count_documents(
        {"type": "inventory.predicted_stockout", "entityId": pid}))
    assert second_emitted == 1, "a product already flagged inside the dedupe window must not fire twice"
