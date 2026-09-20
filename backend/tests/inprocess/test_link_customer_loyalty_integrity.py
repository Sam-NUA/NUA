"""Remediation of the final readiness audit's Critical finding:
POST /api/orders/link-customer had no auth dependency at all, accepted a
client-supplied pointsEarned with no validation, no tenant check on either
the transaction or the customer, no idempotency, and no audit trail — any
bearer token from any business could grant an arbitrary number of points to
any customer of any business.

Fixed in routes/analytics.py's link_order_to_customer: requires
Depends(get_user), verifies both the transaction and the customer belong to
the caller's own business, computes points itself from the transaction's own
stored items/total via services.sale_recorder's canonical
compute_points_earned/credit_loyalty_points (the same function POS checkout
uses), is idempotent per transactionId via the loyalty_ledger, and writes an
audit_service log_event.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Link Customer Test Owner", "email": email, "password": "LinkCustTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "LinkCustTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _make_txn(txn_id, business_id, *, subtotal=100.0, total=100.0, customer_id=None):
    _run(db.transactions.insert_one({
        "id": txn_id, "businessId": business_id, "customerId": customer_id,
        "items": [{"productId": "LC-PROD-1", "productName": "Test Item", "quantity": 1, "price": subtotal}],
        "subtotal": subtotal, "total": total, "gst": total / 11, "paymentMethod": "cash",
        "location": "main", "cashier": "tester", "status": "completed",
    }))


def _make_customer(cust_id, business_id, *, points=0):
    _run(db.customers.insert_one({
        "id": cust_id, "businessId": business_id, "name": "Link Cust Test Customer",
        "points": points, "membershipTier": "Bronze",
    }))


def _cleanup(*, txn_ids=(), cust_ids=()):
    if txn_ids:
        _run(db.transactions.delete_many({"id": {"$in": list(txn_ids)}}))
    if cust_ids:
        _run(db.customers.delete_many({"id": {"$in": list(cust_ids)}}))
    _run(db.loyalty_ledger.delete_many({"transactionId": {"$in": list(txn_ids)}}))


def test_anonymous_caller_is_refused(anon):
    r = req(anon, "POST", "/api/orders/link-customer",
            json={}, headers={})
    # bare query-param style call with no auth at all must 401 before ever
    # touching the DB
    assert req(anon, "POST", "/api/orders/link-customer?transaction_id=x&customer_id=y").status_code == 401


def test_client_cannot_choose_points_earned_or_cross_tenant_link(client, owner_headers):
    """The actual exploit: business A's staff tries to link business B's
    customer to business A's transaction, and separately tries to smuggle a
    huge points_earned value in (which the route no longer even accepts as
    a parameter — any extra query param is simply ignored by FastAPI, not
    honored)."""
    other = _login_as(client, owner_headers, email="link.cust.a@nua.com", business_id="link-cust-biz-a")
    txn_id, cust_id = "LC-TXN-CROSS-1", "LC-CUST-CROSS-1"
    _make_txn(txn_id, "link-cust-biz-a")
    _make_customer(cust_id, "link-cust-biz-b", points=0)  # a DIFFERENT business's customer
    try:
        r = req(client, "POST",
                f"/api/orders/link-customer?transaction_id={txn_id}&customer_id={cust_id}&points_earned=999999",
                headers=other)
        assert r.status_code == 404, (
            f"business A must not be able to link business B's customer to its own transaction — got {r.text[:200]}"
        )
        untouched = _run(db.customers.find_one({"id": cust_id}, {"_id": 0}))
        assert untouched["points"] == 0, "the other business's customer must be untouched"
        txn = _run(db.transactions.find_one({"id": txn_id}, {"_id": 0}))
        assert txn.get("customerId") is None
    finally:
        _cleanup(txn_ids=[txn_id], cust_ids=[cust_id])


def test_cannot_link_another_businesss_transaction(client, owner_headers):
    other = _login_as(client, owner_headers, email="link.cust.b@nua.com", business_id="link-cust-biz-c")
    txn_id, cust_id = "LC-TXN-CROSS-2", "LC-CUST-CROSS-2"
    _make_txn(txn_id, "link-cust-biz-d")  # a DIFFERENT business's transaction
    _make_customer(cust_id, "link-cust-biz-c", points=0)
    try:
        r = req(client, "POST",
                f"/api/orders/link-customer?transaction_id={txn_id}&customer_id={cust_id}",
                headers=other)
        assert r.status_code == 404
        txn = _run(db.transactions.find_one({"id": txn_id}, {"_id": 0}))
        assert txn.get("customerId") is None, "another business's transaction must be untouched"
    finally:
        _cleanup(txn_ids=[txn_id], cust_ids=[cust_id])


def test_points_are_computed_from_the_transactions_own_total_not_client_supplied(client, owner_headers):
    other = _login_as(client, owner_headers, email="link.cust.c@nua.com", business_id="link-cust-biz-e")
    txn_id, cust_id = "LC-TXN-COMPUTE-1", "LC-CUST-COMPUTE-1"
    _make_txn(txn_id, "link-cust-biz-e", subtotal=100.0, total=100.0)
    _make_customer(cust_id, "link-cust-biz-e", points=0)
    # Default loyalty config has earnRate=1.0 with no active flag set, so a
    # $100 sale should earn ~100 points (int(total * 1.0 * 1.0 * 1.0)) — the
    # exact figure doesn't matter as much as proving it is NOT 999999.
    try:
        r = req(client, "POST",
                f"/api/orders/link-customer?transaction_id={txn_id}&customer_id={cust_id}&points_earned=999999",
                headers=other)
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert body["pointsEarned"] != 999999, "client-supplied points_earned must never be honored"
        assert 0 <= body["pointsEarned"] <= 200, f"computed points look wrong: {body}"

        cust = _run(db.customers.find_one({"id": cust_id}, {"_id": 0}))
        assert cust["points"] == body["pointsEarned"]

        ledger = _run(db.loyalty_ledger.find_one(
            {"transactionId": txn_id, "type": "earn"}, {"_id": 0}))
        assert ledger is not None, "must write through the canonical loyalty ledger"
        assert ledger["points"] == body["pointsEarned"]
        assert ledger["businessId"] == "link-cust-biz-e"

        txn = _run(db.transactions.find_one({"id": txn_id}, {"_id": 0}))
        assert txn["customerId"] == cust_id
    finally:
        _cleanup(txn_ids=[txn_id], cust_ids=[cust_id])


def test_linking_the_same_transaction_twice_does_not_double_credit(client, owner_headers):
    other = _login_as(client, owner_headers, email="link.cust.d@nua.com", business_id="link-cust-biz-f")
    txn_id, cust_id = "LC-TXN-IDEMPOTENT-1", "LC-CUST-IDEMPOTENT-1"
    _make_txn(txn_id, "link-cust-biz-f", subtotal=50.0, total=50.0)
    _make_customer(cust_id, "link-cust-biz-f", points=0)
    try:
        first = req(client, "POST",
                    f"/api/orders/link-customer?transaction_id={txn_id}&customer_id={cust_id}",
                    headers=other)
        assert first.status_code == 200, first.text[:200]
        first_points = first.json()["pointsEarned"]

        second = req(client, "POST",
                     f"/api/orders/link-customer?transaction_id={txn_id}&customer_id={cust_id}",
                     headers=other)
        assert second.status_code == 200, second.text[:200]
        assert second.json().get("skipped") is True

        cust = _run(db.customers.find_one({"id": cust_id}, {"_id": 0}))
        assert cust["points"] == first_points, (
            f"a repeated link-customer call for the same transaction must not double-credit points, "
            f"got {cust['points']} after crediting {first_points} once"
        )
        ledger_entries = _run(db.loyalty_ledger.find(
            {"transactionId": txn_id, "type": "earn"}, {"_id": 0}).to_list(10))
        assert len(ledger_entries) == 1, "must not write a second ledger entry for the same sale"
    finally:
        _cleanup(txn_ids=[txn_id], cust_ids=[cust_id])


def test_relinking_to_a_different_customer_is_rejected(client, owner_headers):
    other = _login_as(client, owner_headers, email="link.cust.e@nua.com", business_id="link-cust-biz-g")
    txn_id = "LC-TXN-RELINK-1"
    cust_a, cust_b = "LC-CUST-RELINK-A", "LC-CUST-RELINK-B"
    _make_txn(txn_id, "link-cust-biz-g")
    _make_customer(cust_a, "link-cust-biz-g")
    _make_customer(cust_b, "link-cust-biz-g")
    try:
        first = req(client, "POST",
                    f"/api/orders/link-customer?transaction_id={txn_id}&customer_id={cust_a}",
                    headers=other)
        assert first.status_code == 200, first.text[:200]

        second = req(client, "POST",
                     f"/api/orders/link-customer?transaction_id={txn_id}&customer_id={cust_b}",
                     headers=other)
        assert second.status_code == 409, (
            "relinking an already-linked order to a different customer must be rejected"
        )
    finally:
        _cleanup(txn_ids=[txn_id], cust_ids=[cust_a, cust_b])
