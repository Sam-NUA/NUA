"""routes/phase_ef.py and routes/phase_ef_wave2.py (Ash autonomy Phase E/F
features — VIP tagging, SMS queue, voice price commands, purchase orders,
A/B tests, AI price-tune, surge pricing) had zero businessId scoping
across almost every endpoint. The sharpest findings: voice-command price
changes and AI price-tune apply could reprice another business's product
by name/id, and surge/apply wiped (delete_many({})) and replaced every
business's surge pricing rules on the deployment in one call.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Phase EF Test Owner", "email": email, "password": "PhaseEfTenantTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "PhaseEfTenantTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def test_voice_price_command_cannot_reprice_another_businesss_product(client, owner_headers):
    other = _login_as(client, owner_headers, email="phaseef.voice.other@nua.com", business_id="phaseef-voice-other-biz")

    victim_id = "PHASEEF-VOICE-VICTIM"
    _run(db.products.insert_one({
        "id": victim_id, "name": "Voice Target Latte", "price": 5.0, "cost": 1.5,
        "businessId": "phaseef-voice-other-biz",
    }))
    try:
        r = req(client, "POST", "/api/agent/voice-extended", headers=owner_headers,
                json={"text": "raise voice target latte by 50 cents"})
        assert r.status_code == 200, r.text[:200]
        assert r.json().get("error"), "must not resolve to another business's product at all"

        untouched = _run(db.products.find_one({"id": victim_id}, {"_id": 0}))
        assert untouched["price"] == 5.0
    finally:
        _run(db.products.delete_one({"id": victim_id}))


def test_ai_price_tune_apply_cannot_reprice_another_businesss_product(client, owner_headers):
    other = _login_as(client, owner_headers, email="phaseef.pricetune.other@nua.com", business_id="phaseef-pricetune-other-biz")

    victim_id = "PHASEEF-PRICETUNE-VICTIM"
    _run(db.products.insert_one({
        "id": victim_id, "name": "Price Tune Victim", "price": 8.0, "cost": 2.0,
        "businessId": "phaseef-pricetune-other-biz",
    }))
    try:
        r = req(client, "POST", "/api/ai/price-tune/apply", headers=owner_headers,
                json={"productId": victim_id, "newPrice": 999})
        assert r.status_code == 404, r.text[:200]

        untouched = _run(db.products.find_one({"id": victim_id}, {"_id": 0}))
        assert untouched["price"] == 8.0
    finally:
        _run(db.products.delete_one({"id": victim_id}))


def test_surge_apply_does_not_wipe_or_leak_another_businesss_rules(client, owner_headers):
    other = _login_as(client, owner_headers, email="phaseef.surge.other@nua.com", business_id="phaseef-surge-other-biz")

    theirs = req(client, "POST", "/api/ai/surge/apply", headers=other,
                 json={"rules": [{"dow": 4, "hour": 19, "multiplier": 1.2}]})
    assert theirs.status_code == 200, theirs.text[:200]
    try:
        # My own apply must not wipe the other business's rules.
        mine = req(client, "POST", "/api/ai/surge/apply", headers=owner_headers,
                   json={"rules": [{"dow": 5, "hour": 20, "multiplier": 1.1}]})
        assert mine.status_code == 200, mine.text[:200]

        their_rules_after = _run(db.surge_rules.find({"businessId": "phaseef-surge-other-biz"}, {"_id": 0}).to_list(10))
        assert len(their_rules_after) == 1, "another business's surge rules must survive this business's apply call"

        mine_active = req(client, "GET", "/api/ai/surge/active", headers=owner_headers).json()
        assert not any(r.get("businessId") == "phaseef-surge-other-biz" for r in mine_active["all"])
    finally:
        _run(db.surge_rules.delete_many({"businessId": {"$in": ["phaseef-surge-other-biz", "default"]}}))


def test_purchase_orders_and_ab_tests_are_scoped_per_business(client, owner_headers):
    other = _login_as(client, owner_headers, email="phaseef.po.other@nua.com", business_id="phaseef-po-other-biz")

    po_created = _run(db.purchase_orders.insert_one({
        "id": "PHASEEF-PO-OTHERBIZ", "supplier": "X", "items": [], "totalCost": 0,
        "status": "draft", "createdAt": "2026-01-01T00:00:00", "businessId": "phaseef-po-other-biz",
    }))
    ab_created = _run(db.ab_tests.insert_one({
        "id": "PHASEEF-AB-OTHERBIZ", "productId": "x", "variantA": {}, "variantB": {},
        "metric": "conversions", "status": "running", "exposures": {"A": 0, "B": 0},
        "conversions": {"A": 0, "B": 0}, "revenue": {"A": 0.0, "B": 0.0},
        "createdAt": "2026-01-01T00:00:00", "businessId": "phaseef-po-other-biz",
    }))
    try:
        my_pos = req(client, "GET", "/api/purchase-orders", headers=owner_headers).json()
        assert not any(p["id"] == "PHASEEF-PO-OTHERBIZ" for p in my_pos)

        my_ab = req(client, "GET", "/api/ab-tests", headers=owner_headers).json()
        assert not any(t["id"] == "PHASEEF-AB-OTHERBIZ" for t in my_ab)

        conclude_mine = req(client, "POST", "/api/ab-tests/PHASEEF-AB-OTHERBIZ/conclude", headers=owner_headers)
        assert conclude_mine.status_code == 404

        approve_mine = req(client, "POST", "/api/purchase-orders/PHASEEF-PO-OTHERBIZ/approve", headers=owner_headers)
        assert approve_mine.status_code == 404
    finally:
        _run(db.purchase_orders.delete_one({"id": "PHASEEF-PO-OTHERBIZ"}))
        _run(db.ab_tests.delete_one({"id": "PHASEEF-AB-OTHERBIZ"}))
