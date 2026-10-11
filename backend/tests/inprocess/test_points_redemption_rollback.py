"""routes/transactions.py's create_transaction atomically decrements a
customer's loyalty points BEFORE the sale itself is ever inserted — a real
launch-risk flagged in docs/launch-audit-2026-10-11/REPORT.md ("point
redemption occurs before insert"). If the insert then fails for any
reason, the customer had already been charged points for a sale that was
never recorded — a silently lost balance with nothing to show for it.

This isn't a real multi-document ACID transaction (mongomock can't prove
that either way — see TRUST_RELEASE_FINAL_REPORT.md and the real-replica-
set suite for what would). It's a narrower, independently useful fix: a
compensating refund whenever the insert doesn't end up being THIS
request's own recorded sale, covering both a genuine insert failure and
the concurrent-duplicate-clientOpId race (where the loser's redemption was
previously never refunded even though only the winner's sale was kept).
"""
import uuid

import pytest
from conftest import req
from database import db
from pymongo.errors import DuplicateKeyError
import routes.transactions as transactions_route


@pytest.fixture
def customer_with_points(client, owner_headers):
    customer_id = str(uuid.uuid4())
    client.portal.call(db.customers.insert_one, {
        "id": customer_id, "businessId": "default", "name": "Points Rollback Guest",
        "points": 100, "membershipTier": "Bronze",
    })
    yield customer_id
    client.portal.call(db.customers.delete_one, {"id": customer_id})
    client.portal.call(db.transactions.delete_many, {"customerId": customer_id})


def _sale_payload(customer_id, **extra):
    payload = {
        "items": [{"productId": "no-such-product", "productName": "Custom item",
                   "quantity": 1, "price": 100}],
        "paymentMethod": "cash", "location": "Main", "cashier": "Test Cashier",
        "customerId": customer_id, "pointsRedeemed": 50,
    }
    payload.update(extra)
    return payload


class _FailingTransactions:
    """Proxies the real db.transactions collection, except insert_one
    raises whatever this test needs it to — mongomock-motor returns a new
    wrapper object on every `db.transactions` access, so patching an
    attribute directly on one access's object is a no-op; swapping the
    whole `routes.transactions` module-level `db` reference (as this test
    does) is what actually takes effect."""

    def __init__(self, real_transactions, raises):
        self._real = real_transactions
        self._raises = raises

    async def insert_one(self, *args, **kwargs):
        raise self._raises

    def __getattr__(self, name):
        return getattr(self._real, name)


class _DBWithFailingTransactions:
    def __init__(self, real_db, raises):
        self._real_db = real_db
        self._raises = raises

    @property
    def transactions(self):
        return _FailingTransactions(self._real_db.transactions, self._raises)

    def __getattr__(self, name):
        return getattr(self._real_db, name)


@pytest.fixture
def failing_insert(monkeypatch):
    def _install(exc):
        monkeypatch.setattr(transactions_route, "db", _DBWithFailingTransactions(db, exc))
    return _install


def test_a_sale_insert_that_fails_outright_refunds_the_redeemed_points(
        client, owner_headers, customer_with_points, failing_insert):
    failing_insert(RuntimeError("simulated dropped connection"))

    r = req(client, "POST", "/api/transactions", headers=owner_headers,
            json=_sale_payload(customer_with_points))
    assert r.status_code == 500

    balance = client.portal.call(db.customers.find_one, {"id": customer_with_points}, {"_id": 0, "points": 1})
    assert balance["points"] == 100, (
        "a sale that was never actually recorded must never leave the customer's points "
        "balance permanently decremented"
    )


def test_losing_a_concurrent_duplicate_clientopid_race_refunds_this_attempts_own_redemption(
        client, owner_headers, customer_with_points, failing_insert):
    """Simulates the race deterministically rather than with real
    concurrency (mongomock-motor has no genuine suspend point to force an
    interleave — see test_wallet_voucher_redemption_concurrency.py's
    docstring for the same limitation): another request's sale is already
    sitting in the database under this clientOpId, and the insert raises
    DuplicateKeyError exactly as it would for a true race loser."""
    client_op_id = f"rollback-race-{uuid.uuid4()}"
    winner_txn = {
        "id": "TXN-WINNER", "businessId": "default", "clientOpId": client_op_id,
        "items": [], "subtotal": 50, "discount": 0, "discountAmount": 0, "appliedDiscounts": [],
        "pointsRedeemed": 20, "pointsDiscount": 0.2, "splitDetails": [],
        "surchargeAmount": 0, "surchargePercent": 0, "surchargeReason": None,
        "gratuityAmount": 0, "gratuityPercent": 0, "gratuityLabel": None, "covers": None,
        "gst": 50 / 11, "total": 50, "customerId": customer_with_points,
        "paymentMethod": "cash", "location": "Main", "cashier": "Winner Cashier",
    }
    client.portal.call(db.transactions.insert_one, dict(winner_txn))
    failing_insert(DuplicateKeyError("E11000 Duplicate Key Error", 11000))

    try:
        r = req(client, "POST", "/api/transactions", headers=owner_headers,
                json=_sale_payload(customer_with_points, clientOpId=client_op_id))
        assert r.status_code == 200, r.text[:300]
        assert r.json()["id"] == "TXN-WINNER"

        balance = client.portal.call(db.customers.find_one,
                                      {"id": customer_with_points}, {"_id": 0, "points": 1})
        assert balance["points"] == 100, (
            "the loser of a concurrent duplicate-clientOpId race must have its own redemption "
            "refunded — only the winner's sale was actually kept, so only the winner's own "
            "redemption (already separately accounted for) should count against the balance"
        )
    finally:
        client.portal.call(db.transactions.delete_one, {"id": "TXN-WINNER"})
