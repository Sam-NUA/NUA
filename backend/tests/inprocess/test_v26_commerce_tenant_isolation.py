"""Regression coverage for v26 stored-value and coupon tenant boundaries."""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _other_owner(client, owner_headers, *, email: str, business_id: str) -> dict:
    req(client, "POST", "/api/auth/register", headers=owner_headers, json={
        "name": "Other Owner", "email": email, "password": "OtherOwner2026!",
    })
    _run(db.auth_users.update_one(
        {"email": email}, {"$set": {"role": "owner", "businessId": business_id}}
    ))
    token = req(client, "POST", "/api/auth/login", json={
        "email": email, "password": "OtherOwner2026!",
    }).json()["token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def test_v26_gift_cards_are_scoped_and_redemption_is_idempotent(client, owner_headers):
    other = _other_owner(
        client, owner_headers, email="v26.gift.other@nua.com", business_id="v26-gift-other"
    )
    sold = req(client, "POST", "/api/v26/gift-cards/sell", headers=other, json={
        "amount": 80, "bonus": 0, "channel": "counter", "transactionId": "SALE-OTHER-1",
    })
    assert sold.status_code == 200, sold.text[:300]
    card = sold.json()
    assert card["businessId"] == "v26-gift-other"

    mine = req(client, "GET", "/api/v26/gift-cards", headers=owner_headers)
    assert mine.status_code == 200
    assert not any(row["id"] == card["id"] for row in mine.json())
    assert req(
        client, "GET", f"/api/v26/gift-cards/lookup/{card['code']}", headers=owner_headers
    ).status_code == 404
    assert req(
        client, "POST", f"/api/v26/gift-cards/{card['code']}/reload",
        headers=owner_headers, json={"amount": 10},
    ).status_code == 404

    first = req(
        client, "POST", f"/api/v26/gift-cards/{card['code']}/redeem", headers=other,
        json={"amount": 15, "transactionId": "ORDER-OTHER-1"},
    )
    assert first.status_code == 200, first.text[:300]
    assert first.json()["newBalance"] == 65
    duplicate = req(
        client, "POST", f"/api/v26/gift-cards/{card['code']}/redeem", headers=other,
        json={"amount": 15, "transactionId": "ORDER-OTHER-1"},
    )
    assert duplicate.status_code == 200, duplicate.text[:300]
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["newBalance"] == 65


def test_v26_coupon_redemption_is_tenant_scoped_and_idempotent(client, owner_headers):
    other = _other_owner(
        client, owner_headers, email="v26.coupon.other@nua.com", business_id="v26-coupon-other"
    )
    created = req(client, "POST", "/api/v26/vouchers", headers=other, json={
        "name": "Other only", "discountType": "fixed", "value": 10, "maxUses": 2,
    })
    assert created.status_code == 200, created.text[:300]
    voucher = created.json()

    assert not any(
        row["id"] == voucher["id"]
        for row in req(client, "GET", "/api/v26/vouchers", headers=owner_headers).json()
    )
    cross = req(
        client, "POST", f"/api/v26/vouchers/{voucher['id']}/redeem",
        headers=owner_headers, json={"txId": "MINE-1", "amount": 10},
    )
    assert cross.status_code == 404

    first = req(
        client, "POST", f"/api/v26/vouchers/{voucher['id']}/redeem",
        headers=other, json={"txId": "OTHER-1", "amount": 10},
    )
    assert first.status_code == 200, first.text[:300]
    retry = req(
        client, "POST", f"/api/v26/vouchers/{voucher['id']}/redeem",
        headers=other, json={"txId": "OTHER-1", "amount": 10},
    )
    assert retry.status_code == 200, retry.text[:300]
    assert retry.json()["duplicate"] is True

