"""HTTP rejection, rollback and ambiguous-commit regressions.

In-process transaction double covers route behavior; tests_real supplies the
real MongoDB rollback/concurrency proof. No unconditional refund is safe.
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
        self._raises.calls += 1
        raise self._raises

    async def find_one(self, query, *args, **kwargs):
        # Hide the pre-existing race winner until the attempted insert fails,
        # so neither the route nor transactional replay guard can short-circuit.
        if isinstance(self._raises, DuplicateKeyError) and not self._raises.calls:
            return None
        return await self._real.find_one(query, *args, **kwargs)

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
        exc.calls = 0
        monkeypatch.setattr(transactions_route, "db", _DBWithFailingTransactions(db, exc))
        return exc
    return _install


def test_a_sale_insert_that_fails_rolls_back_the_points_and_ledger(
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


def test_duplicate_insert_is_exercised_and_rolls_back_this_attempts_redemption(
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
    failure = failing_insert(DuplicateKeyError("E11000 Duplicate Key Error", 11000))

    try:
        r = req(client, "POST", "/api/transactions", headers=owner_headers,
                json=_sale_payload(customer_with_points, clientOpId=client_op_id))
        assert r.status_code == 200, r.text[:300]
        assert r.json()["id"] == "TXN-WINNER"
        assert failure.calls == 1, "must reach insert, not the early replay return"
        assert client.portal.call(db.loyalty_ledger.count_documents, {"transactionId": r.json()["id"], "type": "redeem"}) == 0

        balance = client.portal.call(db.customers.find_one,
                                      {"id": customer_with_points}, {"_id": 0, "points": 1})
        assert balance["points"] == 100, (
            "the loser of a concurrent duplicate-clientOpId race must have its own redemption "
            "refunded — only the winner's sale was actually kept, so only the winner's own "
            "redemption (already separately accounted for) should count against the balance"
        )
    finally:
        client.portal.call(db.transactions.delete_one, {"id": "TXN-WINNER"})


def test_lost_response_after_commit_never_refunds_or_redebits_on_replay(
        client, owner_headers, customer_with_points, monkeypatch):
    from services import pos_sale_store
    from pymongo.errors import AutoReconnect
    original = pos_sale_store._transaction

    async def commit_then_lose_response(operation):
        await original(operation)
        raise AutoReconnect("simulated response lost after durable commit")

    monkeypatch.setattr(pos_sale_store, "_transaction", commit_then_lose_response)
    payload = _sale_payload(customer_with_points, clientOpId=f"lost-response-{uuid.uuid4()}")
    response = req(client, "POST", "/api/transactions", headers=owner_headers, json=payload)
    assert response.status_code == 500
    saved = client.portal.call(db.transactions.find_one, {"clientOpId": payload["clientOpId"]})
    assert saved is not None
    assert client.portal.call(db.customers.find_one, {"id": customer_with_points})["points"] == 50
    assert client.portal.call(db.loyalty_ledger.count_documents, {"transactionId": saved["id"], "type": "redeem"}) == 1
    replay = req(client, "POST", "/api/transactions", headers=owner_headers, json=payload)
    assert replay.status_code == 200
    assert replay.json()["id"] == saved["id"]
    assert client.portal.call(db.customers.find_one, {"id": customer_with_points})["points"] == 50


def test_later_split_guest_failure_rolls_back_earlier_guest_debit(client, owner_headers, customer_with_points):
    response = req(client, "POST", "/api/transactions", headers=owner_headers,
                   json=_sale_payload(customer_with_points, splitDetails=[{
                       "payerName": "Missing account", "amount": 5, "method": "cash",
                       "customerId": "missing-or-foreign", "pointsRedeemed": 20,
                   }]))
    assert response.status_code == 400
    assert client.portal.call(db.customers.find_one, {"id": customer_with_points})["points"] == 100
    assert client.portal.call(db.transactions.count_documents, {"customerId": customer_with_points}) == 0
    assert client.portal.call(db.loyalty_ledger.count_documents, {"customerId": customer_with_points, "type": "redeem"}) == 0
