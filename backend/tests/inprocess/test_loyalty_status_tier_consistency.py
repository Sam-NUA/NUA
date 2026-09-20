"""GET /loyalty/status/{customer_id} (the Customer Wallet panel's tier badge)
used to run its own hardcoded, spend-based tier ladder (Bronze/Silver/Gold/
Platinum/VIP at $0/$500/$1500/$5000/$10000) — completely separate from
db.loyalty_tiers, the real, owner-editable, points-based ladder checkout
itself uses to apply tier discounts. A customer could show as one tier on
the wallet panel and a different tier everywhere else in the app. Now both
read the same ladder.
"""
import asyncio

from conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_wallet_tier_matches_the_real_loyalty_tiers_ladder(client, owner_headers):
    from database import db

    # Seed a known, non-default tier ladder so this can't coincidentally pass
    # against whatever the seed defaults happen to be. Scoped to owner_headers'
    # own businessId ("default") and cleaned up afterward — loyalty_tiers is
    # now businessId-scoped (routes/loyalty.py), so a global wipe/insert here
    # would both destroy every other business's tiers in this shared test-suite
    # DB and leave stray untagged rows other tests could pick up.
    _run(db.loyalty_tiers.delete_many({"businessId": "default"}))
    _run(db.loyalty_tiers.insert_many([
        {"id": "t-bronze", "name": "Bronze", "minPoints": 0, "multiplier": 1.0, "discountPercent": 0,
         "perks": [], "businessId": "default"},
        {"id": "t-gold", "name": "Gold", "minPoints": 300, "multiplier": 1.5, "discountPercent": 5,
         "perks": [], "businessId": "default"},
    ]))
    try:
        created = req(client, "POST", "/api/customers", headers=owner_headers, json={
            "name": "Tier Test Customer", "email": "tiertest@nua.com", "phone": "0400111222"})
        assert created.status_code == 200, created.text[:200]
        cid = created.json()["id"]
        _run(db.customers.update_one({"id": cid}, {"$set": {"points": 350}}))

        r = req(client, "GET", f"/api/loyalty/status/{cid}", headers=owner_headers)
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert body["tier"] == "Gold"
        assert body["points"] == 350
    finally:
        _run(db.loyalty_tiers.delete_many({"id": {"$in": ["t-bronze", "t-gold"]}, "businessId": "default"}))


def test_wallet_tier_below_any_threshold_is_the_lowest_tier(client, owner_headers):
    from database import db

    _run(db.loyalty_tiers.delete_many({"businessId": "default"}))
    _run(db.loyalty_tiers.insert_many([
        {"id": "t-bronze", "name": "Bronze", "minPoints": 0, "multiplier": 1.0, "discountPercent": 0,
         "perks": [], "businessId": "default"},
        {"id": "t-gold", "name": "Gold", "minPoints": 300, "multiplier": 1.5, "discountPercent": 5,
         "perks": [], "businessId": "default"},
    ]))
    try:
        created = req(client, "POST", "/api/customers", headers=owner_headers, json={
            "name": "Low Points Customer", "email": "lowpoints@nua.com", "phone": "0400333444"})
        cid = created.json()["id"]
        _run(db.customers.update_one({"id": cid}, {"$set": {"points": 10}}))

        r = req(client, "GET", f"/api/loyalty/status/{cid}", headers=owner_headers)
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert body["tier"] == "Bronze"
        assert body["nextTier"] == "Gold"
        assert body["nextTierAt"] == 300
    finally:
        _run(db.loyalty_tiers.delete_many({"id": {"$in": ["t-bronze", "t-gold"]}, "businessId": "default"}))
