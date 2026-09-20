"""routes/advanced_features.py had zero businessId scoping across tips,
the end-of-day report, marketing segments, and marketing campaigns —
plus POST /tips/add had no auth dependency at all. Any staff member of
any business could see and manipulate another business's tip ledger,
revenue/refund/customer figures in the End-of-Day report, saved audience
segments (and the customer PII they resolve to), and marketing campaigns.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Advanced Features Test Owner", "email": email, "password": "AdvFeaturesTenantTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "AdvFeaturesTenantTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def test_tips_are_isolated_per_business_and_add_tip_requires_auth(client, owner_headers):
    other = _login_as(client, owner_headers, email="advfeat.tips.other@nua.com", business_id="advfeat-tips-other-biz")

    anon_add = req(client, "POST", "/api/tips/add", json={"amount": 999, "staffName": "Ghost"})
    assert anon_add.status_code in (401, 403), "adding a tip must require a staff credential"

    added = req(client, "POST", "/api/tips/add", headers=other, json={"amount": 50, "staffName": "Other Biz Staff"})
    assert added.status_code == 200, added.text[:200]
    tip_id = added.json()["id"]
    try:
        mine = req(client, "GET", "/api/tips", headers=owner_headers).json()
        assert not any(t["id"] == tip_id for t in mine), "another business's tip must not appear in this business's ledger"

        summary_mine = req(client, "GET", "/api/tips/summary", headers=owner_headers).json()
        assert not any(s["name"] == "Other Biz Staff" for s in summary_mine["byStaff"])

        theirs = req(client, "GET", "/api/tips", headers=other).json()
        assert any(t["id"] == tip_id for t in theirs)
    finally:
        _run(db.tips.delete_one({"id": tip_id}))


def test_end_of_day_report_only_reflects_this_businesss_own_data(client, owner_headers):
    other = _login_as(client, owner_headers, email="advfeat.eod.other@nua.com", business_id="advfeat-eod-other-biz")

    sale = req(client, "POST", "/api/transactions", headers=other, json={
        "items": [{"productId": "no-such-product", "productName": "Other biz item", "quantity": 1, "price": 12345}],
        "paymentMethod": "cash", "location": "Main", "cashier": "Other Cashier"})
    assert sale.status_code == 200, sale.text[:200]

    mine = req(client, "GET", "/api/reports/end-of-day?period=today", headers=owner_headers).json()
    assert mine["summary"]["totalSales"] < 12345, "another business's huge sale must not leak into this business's EOD totals"


def test_a_different_businesss_segment_is_not_visible_editable_or_deletable(client, owner_headers):
    other = _login_as(client, owner_headers, email="advfeat.seg.other@nua.com", business_id="advfeat-seg-other-biz")

    created = req(client, "POST", "/api/marketing/segments", headers=other, json={
        "name": "Other biz VIPs", "rules": {"tier": "Gold"}})
    assert created.status_code == 200, created.text[:200]
    seg_id = created.json()["id"]
    try:
        mine = req(client, "GET", "/api/marketing/segments", headers=owner_headers).json()
        assert not any(s["id"] == seg_id for s in mine)

        get_customers_mine = req(client, "GET", f"/api/marketing/segments/{seg_id}/customers", headers=owner_headers)
        assert get_customers_mine.status_code == 404

        update_mine = req(client, "PUT", f"/api/marketing/segments/{seg_id}", headers=owner_headers,
                           json={"name": "Hijacked"})
        assert update_mine.status_code == 404

        delete_mine = req(client, "DELETE", f"/api/marketing/segments/{seg_id}", headers=owner_headers)
        assert delete_mine.status_code == 404

        still_there = req(client, "GET", f"/api/marketing/segments/{seg_id}/customers", headers=other)
        assert still_there.status_code == 200
        assert still_there.json()["segment"]["name"] == "Other biz VIPs", "cross-tenant attempts must not have mutated it"
    finally:
        _run(db.customer_segments.delete_one({"id": seg_id}))


def test_a_different_businesss_campaign_is_not_visible_or_actionable(client, owner_headers):
    other = _login_as(client, owner_headers, email="advfeat.camp.other@nua.com", business_id="advfeat-camp-other-biz")

    created = req(client, "POST", "/api/marketing/campaigns", headers=other, json={
        "name": "Other biz campaign", "subject": "Hi", "body": "Hi {first_name}"})
    assert created.status_code == 200, created.text[:200]
    camp_id = created.json()["id"]
    try:
        mine = req(client, "GET", "/api/marketing/campaigns", headers=owner_headers).json()
        assert not any(c["id"] == camp_id for c in mine)

        send_mine = req(client, "POST", f"/api/marketing/campaigns/{camp_id}/send", headers=owner_headers)
        assert send_mine.status_code == 404

        delete_mine = req(client, "DELETE", f"/api/marketing/campaigns/{camp_id}", headers=owner_headers)
        assert delete_mine.status_code == 404

        still_there = req(client, "GET", "/api/marketing/campaigns", headers=other).json()
        assert any(c["id"] == camp_id for c in still_there), "cross-tenant delete attempt must not have removed it"
    finally:
        _run(db.campaigns.delete_one({"id": camp_id}))
