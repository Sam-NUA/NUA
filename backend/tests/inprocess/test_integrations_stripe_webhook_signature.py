"""routes/integrations.py's /api/webhook/stripe used to delegate signature
verification to emergentintegrations.payments.stripe.checkout.StripeCheckout
— a package that isn't installed in this environment at all — wrapped in a
bare `except Exception` that turned ANY failure, including a rejected
signature, into HTTP 200 {"received": True}. That's the same "silently
return success" failure mode the licensing webhook had, on an endpoint that
marks real online orders and POS sales as paid. It's now verified directly
with the official `stripe` SDK and fails closed instead.
"""
import asyncio
import hashlib
import hmac
import json
import time

from conftest import req

WEBHOOK_SECRET = "whsec_test_secret_for_checkout_webhook"


def _sign(payload_bytes: bytes, secret: str = WEBHOOK_SECRET) -> str:
    timestamp = int(time.time())
    signed_payload = f"{timestamp}.{payload_bytes.decode()}"
    signature = hmac.new(secret.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


def test_an_unconfigured_webhook_secret_fails_closed(client, monkeypatch):
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_dummy")
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)

    body = json.dumps({
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_test_nosecret", "payment_status": "paid"}},
    }).encode()

    r = req(client, "POST", "/api/webhook/stripe", content=body,
                     headers={"Stripe-Signature": "t=1,v1=doesnotmatter", "Content-Type": "application/json"})
    assert r.status_code == 503, r.text[:200]


def test_a_tampered_signature_is_rejected_and_never_marks_payment_paid(client, monkeypatch):
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_dummy")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)

    loop = asyncio.get_event_loop()
    from database import db
    loop.run_until_complete(db.payment_transactions.insert_one({
        "sessionId": "cs_test_tamper", "status": "pending", "paymentStatus": "unpaid",
    }))
    try:
        body = json.dumps({
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_test_tamper", "payment_status": "paid"}},
        }).encode()
        # Sign a different payload than the one sent — a forged/corrupted
        # delivery claiming a session is paid without the real secret.
        signature = _sign(b'{"type": "checkout.session.completed", "data": {"object": {"id": "someone-else"}}}')

        r = req(client, "POST", "/api/webhook/stripe", content=body,
                         headers={"Stripe-Signature": signature, "Content-Type": "application/json"})
        assert r.status_code == 400, r.text[:200]

        payment = loop.run_until_complete(db.payment_transactions.find_one({"sessionId": "cs_test_tamper"}, {"_id": 0}))
        assert payment["paymentStatus"] == "unpaid", "an unverified event must never mark a payment as paid"
    finally:
        loop.run_until_complete(db.payment_transactions.delete_one({"sessionId": "cs_test_tamper"}))


def test_a_correctly_signed_checkout_completed_event_marks_the_payment_paid(client, monkeypatch):
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_dummy")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)

    loop = asyncio.get_event_loop()
    from database import db
    loop.run_until_complete(db.payment_transactions.insert_one({
        "sessionId": "cs_test_valid", "status": "pending", "paymentStatus": "unpaid",
    }))
    try:
        body = json.dumps({
            "id": "evt_test", "object": "event", "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_test_valid", "payment_status": "paid"}},
        }).encode()
        signature = _sign(body)

        r = req(client, "POST", "/api/webhook/stripe", content=body,
                         headers={"Stripe-Signature": signature, "Content-Type": "application/json"})
        assert r.status_code == 200, r.text[:200]
        assert r.json() == {"received": True}

        payment = loop.run_until_complete(db.payment_transactions.find_one({"sessionId": "cs_test_valid"}, {"_id": 0}))
        assert payment["paymentStatus"] == "paid"
        assert payment["status"] == "completed"
    finally:
        loop.run_until_complete(db.payment_transactions.delete_one({"sessionId": "cs_test_valid"}))
