"""P0.6/P0.7/P0.8 Trust Release: financial & offline integrity.

Covers gaps a read-only exploration found: the cumulative-refund cap was a
read-then-write race, online-order status transitions were read-then-write
(no protection against two near-simultaneous requests both applying side
effects), stock decrements had no floor, and the offline queue's replayed
sale had no dedup — a retried POST after a dropped response would ring up
a duplicate transaction.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ─────────────────────────────────────────────────────────────────────────
# Atomic cumulative refund cap
# ─────────────────────────────────────────────────────────────────────────
def test_a_refund_that_would_exceed_the_remaining_balance_is_rejected(client, owner_headers):
    txn = {"id": "FIN-REFUND-TXN-1", "total": 100.0, "items": [], "subtotal": 100.0, "gst": 9.09,
           "paymentMethod": "card", "location": "Main", "cashier": "Test", "businessId": "default"}
    _run(db.transactions.insert_one(dict(txn)))
    try:
        first = req(client, "POST", "/api/refunds", headers=owner_headers, json={
            "originalTransactionId": "FIN-REFUND-TXN-1", "amount": 60, "reason": "partial refund", "refundMethod": "original_payment", "processedBy": "owner@nua.com"})
        assert first.status_code == 200, first.text[:200]

        second = req(client, "POST", "/api/refunds", headers=owner_headers, json={
            "originalTransactionId": "FIN-REFUND-TXN-1", "amount": 60, "reason": "second refund, over the cap", "refundMethod": "original_payment", "processedBy": "owner@nua.com"})
        assert second.status_code == 400, second.text[:200]
        assert "exceeds" in second.json()["detail"].lower()

        # Exactly at the remaining balance must still succeed.
        third = req(client, "POST", "/api/refunds", headers=owner_headers, json={
            "originalTransactionId": "FIN-REFUND-TXN-1", "amount": 40, "reason": "exact remainder", "refundMethod": "original_payment", "processedBy": "owner@nua.com"})
        assert third.status_code == 200, third.text[:200]

        refunded = _run(db.refunds.find({"originalTransactionId": "FIN-REFUND-TXN-1"}, {"_id": 0}).to_list(10))
        assert sum(r["amount"] for r in refunded) == 100
    finally:
        _run(db.transactions.delete_one({"id": "FIN-REFUND-TXN-1"}))
        _run(db.refunds.delete_many({"originalTransactionId": "FIN-REFUND-TXN-1"}))


def test_concurrent_refunds_for_the_same_transaction_cannot_both_exceed_the_cap(client, owner_headers):
    """The actual race the old read-then-write code was vulnerable to: two
    requests that both read 'nothing refunded yet' before either writes."""
    txn = {"id": "FIN-REFUND-TXN-RACE", "total": 100.0, "items": [], "subtotal": 100.0, "gst": 9.09,
           "paymentMethod": "card", "location": "Main", "cashier": "Test", "businessId": "default"}
    _run(db.transactions.insert_one(dict(txn)))
    try:
        def _do_refund(amount):
            return req(client, "POST", "/api/refunds", headers=owner_headers, json={
                "originalTransactionId": "FIN-REFUND-TXN-RACE", "amount": amount, "reason": "race test", "refundMethod": "original_payment", "processedBy": "owner@nua.com"})

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(_do_refund, 70)
            f2 = pool.submit(_do_refund, 70)
            r1, r2 = f1.result(), f2.result()

        statuses = sorted([r1.status_code, r2.status_code])
        assert statuses == [200, 400], (
            f"two concurrent refunds totalling 140 against a $100 transaction must not both succeed: "
            f"got {r1.status_code}, {r2.status_code}"
        )

        refunded = _run(db.refunds.find({"originalTransactionId": "FIN-REFUND-TXN-RACE"}, {"_id": 0}).to_list(10))
        assert sum(r["amount"] for r in refunded) <= 100, "cumulative refunds must never exceed the transaction total"
    finally:
        _run(db.transactions.delete_one({"id": "FIN-REFUND-TXN-RACE"}))
        _run(db.refunds.delete_many({"originalTransactionId": "FIN-REFUND-TXN-RACE"}))


# ─────────────────────────────────────────────────────────────────────────
# Race-safe online-order status transitions
# ─────────────────────────────────────────────────────────────────────────
def test_retrying_accept_on_an_already_accepted_order_does_not_double_deduct_stock(client, owner_headers):
    _run(db.products.insert_one({"id": "FIN-ORDER-PROD-1", "name": "Retry Burger", "category": "Mains",
                                   "stock": 10, "price": 15.0, "active": True, "businessId": "default"}))
    try:
        placed = req(client, "POST", "/api/online/orders?business=default", json={
            "channel": "pickup", "customerName": "Retry Test",
            "items": [{"productId": "FIN-ORDER-PROD-1", "name": "Retry Burger", "price": 15.0,
                       "quantity": 3, "category": "Mains"}],
        })
        order_id = placed.json()["id"]

        first = req(client, "PATCH", f"/api/online/orders/{order_id}/status", headers=owner_headers,
                    json={"status": "accepted"})
        assert first.status_code == 200, first.text[:200]

        # A client retry of the same accept (e.g. the staff app didn't see
        # the first response) — the transition is now a no-op (already
        # accepted), and stock must not be deducted a second time.
        second = req(client, "PATCH", f"/api/online/orders/{order_id}/status", headers=owner_headers,
                     json={"status": "accepted"})
        assert second.status_code == 200, second.text[:200]

        prod = _run(db.products.find_one({"id": "FIN-ORDER-PROD-1"}, {"_id": 0}))
        assert prod["stock"] == 7, "stock must be deducted exactly once, not once per accept call"
    finally:
        _run(db.products.delete_one({"id": "FIN-ORDER-PROD-1"}))


def test_concurrent_accept_requests_for_the_same_order_only_one_wins(client, owner_headers):
    _run(db.products.insert_one({"id": "FIN-ORDER-PROD-RACE", "name": "Race Burger", "category": "Mains",
                                   "stock": 10, "price": 15.0, "active": True, "businessId": "default"}))
    try:
        placed = req(client, "POST", "/api/online/orders?business=default", json={
            "channel": "pickup", "customerName": "Race Test",
            "items": [{"productId": "FIN-ORDER-PROD-RACE", "name": "Race Burger", "price": 15.0,
                       "quantity": 2, "category": "Mains"}],
        })
        order_id = placed.json()["id"]

        def _accept():
            return req(client, "PATCH", f"/api/online/orders/{order_id}/status", headers=owner_headers,
                       json={"status": "accepted"})

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(_accept)
            f2 = pool.submit(_accept)
            r1, r2 = f1.result(), f2.result()

        # asyncio + mongomock's fake I/O means these two requests rarely
        # interleave mid-flight (each runs close to atomically on the single
        # event loop) — so this doesn't reliably force the true race, and
        # both landing 200 is a legitimate outcome (the second is a
        # same-status no-op transition, not a lost update). What the atomic
        # claim actually guarantees, and what this asserts, is the
        # invariant that must hold either way: whichever interleaving
        # happens, the stockDeducted side effect runs at most once — a
        # concurrent duplicate accept must never double-deduct stock.
        assert r1.status_code in (200, 409) and r2.status_code in (200, 409)
        assert 200 in (r1.status_code, r2.status_code), "at least one of the two accepts must succeed"

        prod = _run(db.products.find_one({"id": "FIN-ORDER-PROD-RACE"}, {"_id": 0}))
        assert prod["stock"] == 8, "stock must be deducted exactly once no matter how the two requests interleaved"
    finally:
        _run(db.products.delete_one({"id": "FIN-ORDER-PROD-RACE"}))


# ─────────────────────────────────────────────────────────────────────────
# Stock floor
# ─────────────────────────────────────────────────────────────────────────
def test_stock_is_clamped_at_zero_after_overselling_the_last_units(client, owner_headers):
    _run(db.products.insert_one({"id": "FIN-STOCK-FLOOR-1", "name": "Last Units", "category": "Mains",
                                   "stock": 2, "price": 10.0, "active": True, "sku": "FIN-FLOOR-1",
                                   "businessId": "default"}))
    try:
        # Two POS sales for 2 units each against only 2 in stock — both
        # sales must still succeed (oversell isn't blocked), but stock must
        # land at exactly 0, not -2.
        for _ in range(2):
            r = req(client, "POST", "/api/transactions", headers=owner_headers, json={
                "items": [{"productId": "FIN-STOCK-FLOOR-1", "productName": "Last Units", "price": 10.0,
                           "quantity": 2, "modifiers": []}],
                "paymentMethod": "cash", "location": "Main", "cashier": "Test",
            })
            assert r.status_code == 200, r.text[:200]

        prod = _run(db.products.find_one({"id": "FIN-STOCK-FLOOR-1"}, {"_id": 0}))
        assert prod["stock"] == 0, f"stock must be clamped at 0, not left negative: got {prod['stock']}"
    finally:
        _run(db.products.delete_one({"id": "FIN-STOCK-FLOOR-1"}))


# ─────────────────────────────────────────────────────────────────────────
# Offline-replay dedup (clientOpId)
# ─────────────────────────────────────────────────────────────────────────
def test_a_repeated_clientopid_does_not_create_a_second_transaction(client, owner_headers):
    _run(db.products.insert_one({"id": "FIN-DEDUP-PROD-1", "name": "Dedup Widget", "category": "Mains",
                                   "stock": 50, "price": 20.0, "active": True, "sku": "FIN-DEDUP-1",
                                   "businessId": "default"}))
    try:
        payload = {
            "items": [{"productId": "FIN-DEDUP-PROD-1", "productName": "Dedup Widget", "price": 20.0,
                       "quantity": 1, "modifiers": []}],
            "paymentMethod": "cash", "location": "Main", "cashier": "Test",
            "clientOpId": "test-client-op-id-dedup-1",
        }
        first = req(client, "POST", "/api/transactions", headers=owner_headers, json=payload)
        assert first.status_code == 200, first.text[:200]
        first_id = first.json()["id"]

        # Simulates the offline queue retrying the identical POST because
        # the first response never reached the client.
        second = req(client, "POST", "/api/transactions", headers=owner_headers, json=payload)
        assert second.status_code == 200, second.text[:200]
        assert second.json()["id"] == first_id, "a replayed clientOpId must return the original transaction, not create a new one"

        count = _run(db.transactions.count_documents({"clientOpId": "test-client-op-id-dedup-1"}))
        assert count == 1

        prod = _run(db.products.find_one({"id": "FIN-DEDUP-PROD-1"}, {"_id": 0}))
        assert prod["stock"] == 49, "stock must be deducted exactly once, not once per replayed POST"
    finally:
        _run(db.products.delete_one({"id": "FIN-DEDUP-PROD-1"}))
        _run(db.transactions.delete_many({"clientOpId": "test-client-op-id-dedup-1"}))


def test_concurrent_posts_with_the_same_clientopid_only_create_one_transaction(client, owner_headers):
    _run(db.products.insert_one({"id": "FIN-DEDUP-PROD-RACE", "name": "Dedup Race Widget", "category": "Mains",
                                   "stock": 50, "price": 20.0, "active": True, "sku": "FIN-DEDUP-RACE",
                                   "businessId": "default"}))
    try:
        payload = {
            "items": [{"productId": "FIN-DEDUP-PROD-RACE", "productName": "Dedup Race Widget", "price": 20.0,
                       "quantity": 1, "modifiers": []}],
            "paymentMethod": "cash", "location": "Main", "cashier": "Test",
            "clientOpId": "test-client-op-id-dedup-race-1",
        }

        def _post():
            return req(client, "POST", "/api/transactions", headers=owner_headers, json=payload)

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(_post)
            f2 = pool.submit(_post)
            r1, r2 = f1.result(), f2.result()

        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json()["id"] == r2.json()["id"], "both concurrent calls must resolve to the same transaction"

        count = _run(db.transactions.count_documents({"clientOpId": "test-client-op-id-dedup-race-1"}))
        assert count == 1, "the unique sparse index must prevent two transactions from ever being inserted"
    finally:
        _run(db.products.delete_one({"id": "FIN-DEDUP-PROD-RACE"}))
        _run(db.transactions.delete_many({"clientOpId": "test-client-op-id-dedup-race-1"}))
