"""Voucher lookup (_resolve_voucher and friends) had no tenant scoping at
all, and the unauthenticated /vouchers/public-check endpoint exposed that
lookup with no auth — letting anyone probe any business's voucher codes.
Percentage-discount vouchers also never respected rules.maxDiscount. Fixed:
lookups are now tenant-scoped (using the caller's real DB businessId, not
an X-Tenant-Id/X-Business-Id header, which a partner integration controls
but a staff member's own request shouldn't be overridden by), and discount
math (now shared between commerce_v29 and online_orders) applies the cap."""
from conftest import req


def _insert_voucher(code, business_id, value_type="amount", value=10.0, max_discount=None):
    from database import db
    import asyncio

    async def run():
        await db.vouchers.insert_one({
            "id": f"V-{code}", "code": code, "qrPayload": "x", "sourceType": "manual",
            "label": "ZZZ test voucher", "valueType": value_type, "value": value,
            "faceValue": value, "residualValue": 0.0, "usageType": "multi_use",
            "maxRedemptions": None, "redemptionCount": 0, "partialRedeemable": False,
            "assignable": True, "businessId": business_id,
            "rules": {"maxDiscount": max_discount} if max_discount is not None else {},
            "status": "active",
        })
    asyncio.get_event_loop().run_until_complete(run())


def test_owner_can_validate_a_voucher_belonging_to_their_own_business(client, owner_headers):
    _insert_voucher("ZZZOWN1", "default")
    r = req(client, "POST", "/api/vouchers/validate", headers=owner_headers, json={"code": "ZZZOWN1"})
    assert r.status_code == 200, r.text
    assert r.json()["valid"] is True


def test_owner_cannot_resolve_a_voucher_belonging_to_another_business(client, owner_headers):
    _insert_voucher("ZZZOTHER1", "BIZ-VOUCHER-OTHER")
    r = req(client, "GET", "/api/vouchers/lookup/ZZZOTHER1", headers=owner_headers)
    assert r.status_code == 404, r.text
    r2 = req(client, "POST", "/api/vouchers/validate", headers=owner_headers, json={"code": "ZZZOTHER1"})
    assert r2.status_code == 404, r2.text


def test_percentage_voucher_discount_is_capped_by_max_discount():
    from routes.commerce_v29 import _compute_voucher_discount
    v = {"valueType": "percentage", "value": 15.0, "rules": {"maxDiscount": 20.0}}
    assert _compute_voucher_discount(v, subtotal=500.0) == 20.0
    assert _compute_voucher_discount(v, subtotal=50.0) == 7.5


def test_public_check_applies_the_max_discount_cap(client):
    _insert_voucher("ZZZPUBCAP", "default", value_type="percentage", value=15.0, max_discount=20.0)
    r = req(client, "POST", "/api/vouchers/public-check?business=default", json={
        "code": "ZZZPUBCAP", "cart": [{"price": 500.0, "quantity": 1}],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["valid"] is True
    assert body["discount"] == 20.0


def test_revoke_voucher_rejects_a_voucher_belonging_to_another_business(client, owner_headers):
    """POST /vouchers/{id}/revoke had no tenant check at all — any
    owner/manager could revoke (permanently disable) any OTHER business's
    voucher just by knowing its id. Found during the Trust Release final
    readiness audit."""
    _insert_voucher("ZZZREVOKEOTHER", "BIZ-VOUCHER-REVOKE-OTHER")
    r = req(client, "POST", "/api/vouchers/V-ZZZREVOKEOTHER/revoke", headers=owner_headers, json={})
    assert r.status_code == 404, r.text

    from database import db
    import asyncio
    v = asyncio.get_event_loop().run_until_complete(
        db.vouchers.find_one({"id": "V-ZZZREVOKEOTHER"}, {"_id": 0, "status": 1}))
    assert v["status"] == "active", "a rejected cross-tenant revoke must not change the voucher's status"


def test_revoke_voucher_succeeds_for_your_own_business(client, owner_headers):
    _insert_voucher("ZZZREVOKEOWN", "default")
    r = req(client, "POST", "/api/vouchers/V-ZZZREVOKEOWN/revoke", headers=owner_headers, json={})
    assert r.status_code == 200, r.text
