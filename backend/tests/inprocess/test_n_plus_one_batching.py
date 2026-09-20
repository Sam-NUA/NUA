"""Round 18 N+1 batching — these endpoints used to issue one Mongo query
per row in a loop instead of a single batched lookup. Functional behavior
is unchanged; these tests lock that in so the batched rewrite can't
silently drop a match.
"""
import asyncio
import uuid

from conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_identity_segment_preview_batches_loyalty_tier_and_guest_tag_lookups(client, owner_headers):
    from database import db

    cid_gold = str(uuid.uuid4())
    cid_bronze = str(uuid.uuid4())
    _run(db.identity_customers.delete_many({"id": {"$in": [cid_gold, cid_bronze]}}))
    _run(db.identity_customers.insert_many([
        {"id": cid_gold, "venue_id": "main", "name": "Gold Guest", "phone": "0400000001",
         "email": None, "source": "pos_checkout", "visit_count": 3, "last_seen_at": "2026-08-01T00:00:00+00:00"},
        {"id": cid_bronze, "venue_id": "main", "name": "Bronze Guest", "phone": "0400000002",
         "email": None, "source": "pos_checkout", "visit_count": 1, "last_seen_at": "2026-08-01T00:00:00+00:00"},
    ]))
    _run(db.loyalty_accounts.delete_many({"customer_id": {"$in": [cid_gold, cid_bronze]}}))
    _run(db.loyalty_accounts.insert_many([
        {"customer_id": cid_gold, "points_balance": 500, "tier": "Gold", "enrolled_at": "2026-08-01T00:00:00+00:00"},
        {"customer_id": cid_bronze, "points_balance": 10, "tier": "Bronze", "enrolled_at": "2026-08-01T00:00:00+00:00"},
    ]))
    _run(db.guest_profiles.delete_many({"customer_id": {"$in": [cid_gold, cid_bronze]}}))
    _run(db.guest_profiles.insert_one(
        {"customer_id": cid_gold, "notes": "", "tags": ["regular"], "created_at": "2026-08-01T00:00:00+00:00"}))

    r = req(client, "POST", "/api/identity/segments/preview", headers=owner_headers,
            json={"min_loyalty_tier": "Gold"})
    assert r.status_code == 200, r.text[:200]
    ids = {c["id"] for c in r.json()["customers"]}
    assert cid_gold in ids
    assert cid_bronze not in ids

    r2 = req(client, "POST", "/api/identity/segments/preview", headers=owner_headers,
             json={"guest_tag": "regular"})
    assert r2.status_code == 200, r2.text[:200]
    ids2 = {c["id"] for c in r2.json()["customers"]}
    assert cid_gold in ids2
    assert cid_bronze not in ids2


def test_pre_shift_today_batches_customer_lookups_for_vip_and_dietary(client, owner_headers):
    from database import db
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    cust_vip = str(uuid.uuid4())
    cust_allergy = str(uuid.uuid4())
    _run(db.customers.delete_many({"id": {"$in": [cust_vip, cust_allergy]}}))
    _run(db.customers.insert_many([
        {"id": cust_vip, "businessId": "default", "name": "VIP Guest", "email": "vip@test.com", "phone": "1", "isVip": True},
        {"id": cust_allergy, "businessId": "default", "name": "Allergy Guest", "email": "allergy@test.com", "phone": "2",
         "allergies": ["Peanuts"]},
    ]))
    res_vip = str(uuid.uuid4())
    res_allergy = str(uuid.uuid4())
    _run(db.reservations.delete_many({"id": {"$in": [res_vip, res_allergy]}}))
    _run(db.reservations.insert_many([
        {"id": res_vip, "businessId": "default", "date": today, "time": "18:00", "guestName": "VIP Guest",
         "customerId": cust_vip, "partySize": 2, "status": "confirmed"},
        {"id": res_allergy, "businessId": "default", "date": today, "time": "19:00", "guestName": "Allergy Guest",
         "customerId": cust_allergy, "partySize": 4, "status": "confirmed"},
    ]))

    r = req(client, "GET", "/api/pre-shift/today", headers=owner_headers)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert any(g.get("id") == res_vip for g in body["vipGuests"] if "id" in g) or \
        any(g.get("customerProfile", {}).get("id") == cust_vip for g in body["vipGuests"])
    assert any(a["reservation"] == res_allergy and "ALLERGY: Peanuts" in a["alerts"] for a in body["dietaryAlerts"])


def test_cleanup_legacy_categories_batches_product_counts(client, owner_headers):
    from database import db

    empty_cat_id = str(uuid.uuid4())
    used_cat_id = str(uuid.uuid4())
    empty_name = f"Empty Legacy {uuid.uuid4().hex[:8]}"
    used_name = f"Used Legacy {uuid.uuid4().hex[:8]}"
    _run(db.categories.delete_many({"id": {"$in": [empty_cat_id, used_cat_id]}}))
    _run(db.categories.insert_many([
        {"id": empty_cat_id, "name": empty_name, "businessId": "default"},
        {"id": used_cat_id, "name": used_name, "businessId": "default"},
    ]))
    prod_id = str(uuid.uuid4())
    _run(db.products.delete_many({"id": prod_id}))
    _run(db.products.insert_one({"id": prod_id, "name": "Widget", "category": used_name,
                                 "price": 5, "businessId": "default"}))

    r = req(client, "POST", "/api/categories/cleanup-legacy", headers=owner_headers)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert empty_name in body["removed"]
    assert any(k["name"] == used_name and k["productCount"] == 1 for k in body["keptWithProducts"])
