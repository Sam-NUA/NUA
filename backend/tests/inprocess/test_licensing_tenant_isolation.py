"""routes/licensing.py derived every "which tenant's license is this
action for" decision from `user.get("tenantId")` — a field that has never
existed anywhere on the auth_users/JWT model (the real field is
businessId) — so every caller silently fell through to tenant_id =
"default", meaning every business on the deployment shared ONE license
record: one ABN, one Stripe customer/subscription, one device list, one
audit log. Several endpoints additionally accepted a client-supplied
tenantId in the request body with no check that it belonged to the
caller at all, so any owner could onboard, revoke devices on, or request
an ABN change for another business's license by simply naming its
tenantId in the payload — and /billing/recovery-link would hand back a
live Stripe Billing Portal session for whichever business happened to
own the "default" record, regardless of who asked.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Licensing Test Owner", "email": email, "password": "LicensingTenantTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "LicensingTenantTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def test_me_and_audit_are_scoped_to_the_callers_own_business_not_a_shared_default(client, owner_headers):
    other = _login_as(client, owner_headers, email="licensing.me.other@nua.com", business_id="licensing-me-other-biz")

    _run(db.tenant_licenses.insert_one({
        "id": "LIC-OTHERBIZ", "tenantId": "licensing-me-other-biz", "abn": "12345678901",
        "abnVerified": True, "abnEntityName": "Other Biz Pty Ltd", "abnGstRegistered": True,
        "state": "active", "ownerEmail": "licensing.me.other@nua.com", "maxDevices": 3, "devices": [],
        "stripeCustomerId": "cus_other_biz_secret", "stripeSubscriptionId": None,
        "currentPeriodEnd": None, "lastValidationAt": None, "graceEndAt": None,
        "suspensionReason": None, "createdAt": "2026-01-01T00:00:00",
    }))
    try:
        mine = req(client, "GET", "/api/license/me", headers=owner_headers).json()
        assert mine.get("abnEntityName") != "Other Biz Pty Ltd", (
            "an unrelated business's license (ABN, Stripe customer) must never surface as 'my' license"
        )

        theirs = req(client, "GET", "/api/license/me", headers=other).json()
        assert theirs.get("abnEntityName") == "Other Biz Pty Ltd"

        audit_mine = req(client, "GET", "/api/license/audit", headers=owner_headers).json()
        assert not any(a.get("tenantId") == "licensing-me-other-biz" for a in audit_mine)
    finally:
        _run(db.tenant_licenses.delete_one({"id": "LIC-OTHERBIZ"}))


def test_a_client_supplied_tenant_id_cannot_target_another_businesss_license(client, owner_headers):
    other = _login_as(client, owner_headers, email="licensing.spoof.other@nua.com", business_id="licensing-spoof-other-biz")

    _run(db.tenant_licenses.insert_one({
        "id": "LIC-SPOOFTARGET", "tenantId": "licensing-spoof-other-biz", "abn": "98765432109",
        "abnVerified": True, "abnEntityName": "Spoof Target Biz", "abnGstRegistered": True,
        "state": "active", "ownerEmail": "licensing.spoof.other@nua.com", "maxDevices": 3,
        "devices": [{"deviceId": "victim-device-1", "name": "Victim POS", "activatedAt": "2026-01-01T00:00:00",
                     "activatedBy": "x", "status": "active"}],
        "stripeCustomerId": None, "stripeSubscriptionId": None,
        "currentPeriodEnd": None, "lastValidationAt": None, "graceEndAt": None,
        "suspensionReason": None, "createdAt": "2026-01-01T00:00:00",
    }))
    try:
        # owner_headers (a different, real business) tries to revoke the
        # other business's device by naming its tenantId directly.
        attack = req(client, "POST", "/api/license/device/revoke", headers=owner_headers,
                      json={"tenantId": "licensing-spoof-other-biz", "deviceId": "victim-device-1"})
        assert attack.status_code == 403, attack.text[:200]

        still_there = _run(db.tenant_licenses.find_one({"id": "LIC-SPOOFTARGET"}, {"_id": 0}))
        assert any(d["deviceId"] == "victim-device-1" for d in still_there["devices"]), (
            "a spoofed tenantId in the request body must never let a different business revoke another's device"
        )

        # Same attack against onboarding a license "for" someone else's tenantId.
        onboard_attack = req(client, "POST", "/api/license/onboard", headers=owner_headers,
                              json={"tenantId": "licensing-spoof-other-biz", "abn": "11111111111"})
        assert onboard_attack.status_code == 403
    finally:
        _run(db.tenant_licenses.delete_one({"id": "LIC-SPOOFTARGET"}))
