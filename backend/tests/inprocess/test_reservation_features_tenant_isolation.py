"""routes/reservation_features.py had zero businessId scoping across
table_combinations, booking_shifts, booking_experiences, club_offers,
social_accounts, and email_log. social_accounts is the sharpest edge —
it stores real OAuth accessTokens, so this was a credential leak across
tenants, not just a data leak.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Reservation Features Test Owner", "email": email, "password": "ResFeaturesTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "ResFeaturesTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def test_a_different_businesss_social_account_token_is_not_visible(client, owner_headers):
    other = _login_as(client, owner_headers, email="resfeatures.social.other@nua.com", business_id="resfeatures-social-biz")

    created = req(client, "POST", "/api/clubmember/social-accounts", headers=other, json={
        "platform": "instagram", "accountName": "other_biz_insta", "accessToken": "secret-oauth-token-xyz"})
    assert created.status_code == 200, created.text[:200]
    account_id = created.json()["id"]
    try:
        listed = req(client, "GET", "/api/clubmember/social-accounts", headers=owner_headers).json()
        assert account_id not in {a["id"] for a in listed}
        assert not any(a.get("accessToken") == "secret-oauth-token-xyz" for a in listed), (
            "a different business's OAuth access token must never be readable"
        )

        # Business A must not be able to delete business B's account either.
        req(client, "DELETE", f"/api/clubmember/social-accounts/{account_id}", headers=owner_headers)
        still_there = req(client, "GET", "/api/clubmember/social-accounts", headers=other).json()
        assert account_id in {a["id"] for a in still_there}, "a different business must not be able to delete this account"
    finally:
        _run(db.social_accounts.delete_one({"id": account_id}))


def test_a_different_businesss_table_combination_is_not_visible(client, owner_headers):
    other = _login_as(client, owner_headers, email="resfeatures.combo.other@nua.com", business_id="resfeatures-combo-biz")

    created = req(client, "POST", "/api/tables/combinations", headers=other, json={
        "name": "Other Biz Combo", "tableIds": ["T1", "T2"], "maxCovers": 8})
    assert created.status_code == 200, created.text[:200]
    combo_id = created.json()["id"]
    try:
        listed = req(client, "GET", "/api/tables/combinations", headers=owner_headers).json()
        assert combo_id not in {c["id"] for c in listed}
    finally:
        _run(db.table_combinations.delete_one({"id": combo_id}))


def test_a_different_businesss_club_offer_is_not_visible_or_editable(client, owner_headers):
    other = _login_as(client, owner_headers, email="resfeatures.club.other@nua.com", business_id="resfeatures-club-biz")

    created = req(client, "POST", "/api/clubmember/offers", headers=other, json={
        "title": "Other Biz Offer", "discount": 25})
    assert created.status_code == 200, created.text[:200]
    offer_id = created.json()["id"]
    try:
        listed = req(client, "GET", "/api/clubmember/offers", headers=owner_headers).json()
        assert offer_id not in {o["id"] for o in listed}

        edit = req(client, "PUT", f"/api/clubmember/offers/{offer_id}", headers=owner_headers,
                   json={"discount": 50})
        assert edit.status_code == 404, edit.text[:200]
    finally:
        _run(db.club_offers.delete_one({"id": offer_id}))


def test_booking_shifts_are_scoped_per_business(client, owner_headers):
    other = _login_as(client, owner_headers, email="resfeatures.shifts.other@nua.com", business_id="resfeatures-shifts-biz")

    saved = req(client, "POST", "/api/booking/schedule", headers=other, json={
        "shifts": [{"name": "OtherBizShift", "startTime": "06:00", "endTime": "09:00", "interval": 15, "tables": [], "enabled": True}]})
    assert saved.status_code == 200, saved.text[:200]
    try:
        owner_shifts = req(client, "GET", "/api/booking/schedule", headers=owner_headers).json()
        assert not any(s.get("name") == "OtherBizShift" for s in owner_shifts), (
            "one business saving its schedule must not leak into or overwrite a different business's schedule"
        )
    finally:
        _run(db.booking_shifts.delete_many({"businessId": "resfeatures-shifts-biz"}))
