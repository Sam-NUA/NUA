"""Remediation of the final readiness audit's finding on routes/public.py's
legacy "QR PAYMENT API" (generate-qr / split / confirm): db.payments and
db.split_payments carried no businessId at all, and confirm_payment looked
up a payment purely by its id (an 8-hex, ~32-bit value) with no ownership
check — a staff member logged into ANY business could confirm (or, with
the id guessed/enumerated) read another business's QR-UPI payment or
split-payment record. Fixed with businessId stamped at creation, required
on every lookup/mutation, and a wider (full uuid4 hex) id.
"""
import asyncio

from database import db


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "QR Payment Test Owner", "email": email, "password": "QrPaymentTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "QrPaymentTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _make_business(biz_id):
    _run(db.businesses.insert_one({"id": biz_id, "slug": biz_id, "name": f"Biz {biz_id}", "status": "active"}))


def _cleanup(*, biz_ids=(), payment_ids=()):
    if biz_ids:
        _run(db.businesses.delete_many({"id": {"$in": list(biz_ids)}}))
        _run(db.auth_users.delete_many({"businessId": {"$in": list(biz_ids)}}))
    if payment_ids:
        _run(db.payments.delete_many({"id": {"$in": list(payment_ids)}}))
        _run(db.split_payments.delete_many({"id": {"$in": list(payment_ids)}}))


def test_generate_qr_rejects_an_unauthenticated_caller(anon):
    r = anon.post("/api/payments/generate-qr", json={"amount": 10})
    assert r.status_code in (401, 403), r.text


def test_confirm_payment_rejects_an_unauthenticated_caller(anon):
    r = anon.post("/api/payments/some-id/confirm")
    assert r.status_code in (401, 403), r.text


def test_generate_qr_stamps_the_callers_business(client, owner_headers):
    payment_id = None
    try:
        r = client.post("/api/payments/generate-qr", headers=owner_headers, json={"amount": 25})
        assert r.status_code == 200, r.text
        payment_id = r.json()["paymentId"]
        doc = _run(db.payments.find_one({"id": payment_id}, {"_id": 0}))
        assert doc["businessId"] == "default"
    finally:
        _cleanup(payment_ids=[payment_id] if payment_id else [])


def test_another_business_cannot_confirm_this_businesss_payment(client, owner_headers):
    biz_b = "qrpay-biz-b"
    payment_id = None
    try:
        _make_business(biz_b)
        biz_b_headers = _login_as(client, owner_headers, email="qrpay-b-owner@nua.com", business_id=biz_b)

        r = client.post("/api/payments/generate-qr", headers=owner_headers, json={"amount": 40})
        payment_id = r.json()["paymentId"]

        r = client.post(f"/api/payments/{payment_id}/confirm", headers=biz_b_headers)
        assert r.status_code == 404, "a different business must not be able to confirm this payment"

        r = client.post(f"/api/payments/{payment_id}/confirm", headers=owner_headers)
        assert r.status_code == 200
        assert r.json()["status"] == "confirmed"
    finally:
        _cleanup(biz_ids=[biz_b], payment_ids=[payment_id] if payment_id else [])


def test_split_payment_records_are_stamped_and_tenant_scoped(client, owner_headers):
    biz_b = "qrpay-biz-b2"
    split_ids = []
    try:
        _make_business(biz_b)
        biz_b_headers = _login_as(client, owner_headers, email="qrpay-b2-owner@nua.com", business_id=biz_b)

        r = client.post("/api/payments/split", headers=owner_headers, json={
            "totalAmount": 30, "splits": [{"amount": 15}, {"amount": 15}],
        })
        assert r.status_code == 200, r.text
        splits = r.json()["splits"]
        split_ids = [s["id"] for s in splits]
        assert all(s["businessId"] == "default" for s in
                   _run(db.split_payments.find({"id": {"$in": split_ids}}, {"_id": 0}).to_list(10)))

        r = client.post(f"/api/payments/{split_ids[0]}/confirm", headers=biz_b_headers)
        assert r.status_code == 404, "a different business must not be able to confirm this split payment"
    finally:
        _cleanup(biz_ids=[biz_b], payment_ids=split_ids)
