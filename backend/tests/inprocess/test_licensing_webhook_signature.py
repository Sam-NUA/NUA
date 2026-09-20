"""The public-allowlist fix (a prior round) proved /api/license/stripe/webhook
is reachable — this proves the whole path actually works end to end with a
REAL Stripe-format signature, not just a bare unauthenticated POST. Stripe
signs every webhook delivery with an HMAC-SHA256 over "{timestamp}.{body}"
using the endpoint's signing secret (STRIPE_WEBHOOK_SECRET); the route
rejects anything that doesn't verify. A test that only confirms "not 401"
would miss a broken signature-verification path entirely.
"""
import asyncio
import hashlib
import hmac
import json
import time

from conftest import req

WEBHOOK_SECRET = "whsec_test_secret_for_licensing_webhook"


def _sign(payload_bytes: bytes, secret: str = WEBHOOK_SECRET) -> str:
    timestamp = int(time.time())
    signed_payload = f"{timestamp}.{payload_bytes.decode()}"
    signature = hmac.new(secret.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


def test_a_correctly_signed_invoice_paid_event_reactivates_the_tenant(client, monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)

    loop = asyncio.get_event_loop()
    from database import db
    loop.run_until_complete(db.tenant_licenses.insert_one({
        "tenantId": "TEN-WEBHOOK-TEST", "stripeCustomerId": "cus_webhook_test",
        "stripeSubscriptionId": None, "state": "past_due",
    }))
    try:
        body = json.dumps({
            "id": "evt_test", "object": "event", "type": "invoice.paid",
            "data": {"object": {"customer": "cus_webhook_test", "id": "in_test", "period_end": int(time.time())}},
        }).encode()
        signature = _sign(body)

        r = req(client, "POST", "/api/license/stripe/webhook", content=body,
                         headers={"Stripe-Signature": signature, "Content-Type": "application/json"})
        assert r.status_code == 200, r.text[:200]
        assert r.json().get("type") == "invoice.paid"

        lic = loop.run_until_complete(db.tenant_licenses.find_one({"tenantId": "TEN-WEBHOOK-TEST"}, {"_id": 0}))
        assert lic["state"] == "active", "a paid invoice must reactivate a past-due tenant"
    finally:
        loop.run_until_complete(db.tenant_licenses.delete_one({"tenantId": "TEN-WEBHOOK-TEST"}))


def test_a_tampered_signature_is_rejected_and_never_touches_license_state(client, monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)

    loop = asyncio.get_event_loop()
    from database import db
    loop.run_until_complete(db.tenant_licenses.insert_one({
        "tenantId": "TEN-WEBHOOK-TAMPER", "stripeCustomerId": "cus_webhook_tamper",
        "stripeSubscriptionId": None, "state": "past_due",
    }))
    try:
        body = json.dumps({
            "type": "invoice.paid",
            "data": {"object": {"customer": "cus_webhook_tamper", "id": "in_test"}},
        }).encode()
        # Sign one payload, send a different one — exactly what an attacker
        # (or a corrupted delivery) forging a "your subscription is paid"
        # event without the real Stripe secret would produce.
        signature = _sign(b'{"type": "invoice.paid", "data": {"object": {"customer": "someone-else"}}}')

        r = req(client, "POST", "/api/license/stripe/webhook", content=body,
                         headers={"Stripe-Signature": signature, "Content-Type": "application/json"})
        assert r.status_code == 400, r.text[:200]

        lic = loop.run_until_complete(db.tenant_licenses.find_one({"tenantId": "TEN-WEBHOOK-TAMPER"}, {"_id": 0}))
        assert lic["state"] == "past_due", "an unverified event must never change license state"
    finally:
        loop.run_until_complete(db.tenant_licenses.delete_one({"tenantId": "TEN-WEBHOOK-TAMPER"}))


def test_an_unconfigured_webhook_secret_fails_closed_instead_of_skipping_verification(client, monkeypatch):
    # Regression test for a prior insecure dev-fallback: when
    # STRIPE_WEBHOOK_SECRET wasn't set, the route used to accept the raw
    # payload with zero signature verification. It must now refuse to
    # process anything at all rather than silently degrade to "unsigned
    # accepted" — a missing secret is a deployment misconfiguration, not a
    # reason to trust unverified input.
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)

    loop = asyncio.get_event_loop()
    from database import db
    loop.run_until_complete(db.tenant_licenses.insert_one({
        "tenantId": "TEN-WEBHOOK-NOSECRET", "stripeCustomerId": "cus_webhook_nosecret",
        "stripeSubscriptionId": None, "state": "past_due",
    }))
    try:
        body = json.dumps({
            "type": "invoice.paid",
            "data": {"object": {"customer": "cus_webhook_nosecret", "id": "in_test"}},
        }).encode()

        r = req(client, "POST", "/api/license/stripe/webhook", content=body,
                         headers={"Stripe-Signature": "t=1,v1=doesnotmatter", "Content-Type": "application/json"})
        assert r.status_code == 503, r.text[:200]

        lic = loop.run_until_complete(db.tenant_licenses.find_one({"tenantId": "TEN-WEBHOOK-NOSECRET"}, {"_id": 0}))
        assert lic["state"] == "past_due", "an unsigned event must never change license state, even with no secret configured"
    finally:
        loop.run_until_complete(db.tenant_licenses.delete_one({"tenantId": "TEN-WEBHOOK-NOSECRET"}))
