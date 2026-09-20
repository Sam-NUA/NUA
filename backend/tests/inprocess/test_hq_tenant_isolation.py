"""routes/hq.py's whole purpose is cross-LOCATION rollups within one
franchise/brand group, but none of its 4 endpoints ever checked which
brand a location belonged to — /kpi-roll-up and /leaderboard aggregated
db.transactions across literally every business on the deployment, so any
logged-in staff member could see every other (unrelated) tenant's
revenue, covers, and GST, not just sibling locations under their own
brand.
"""
import asyncio
import uuid

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "HQ Test Owner", "email": email, "password": "HqTenantTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "HqTenantTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def test_an_unrelated_businesss_revenue_does_not_leak_into_the_kpi_rollup(client, owner_headers):
    other = _login_as(client, owner_headers, email="hq.unrelated@nua.com", business_id="hq-unrelated-biz")

    txn_id = f"TXN-HQ-{uuid.uuid4().hex[:8]}"
    _run(db.transactions.insert_one({
        "id": txn_id, "businessId": "hq-unrelated-biz", "locationId": "hq-unrelated-biz",
        "total": 999999.0, "gst": 90909.0, "timestamp": "2026-09-14T00:00:00+00:00",
        "items": [], "subtotal": 999999.0, "paymentMethod": "cash", "location": "Main", "cashier": "Test",
    }))
    try:
        rollup = req(client, "GET", "/api/hq/kpi-roll-up", headers=owner_headers, params={"days": 3650}).json()
        assert not any(loc["location"] == "hq-unrelated-biz" for loc in rollup["locations"]), (
            "an unrelated business's revenue must not appear in this business's HQ rollup"
        )
        assert rollup["totalRevenue"] < 999999.0

        leaderboard = req(client, "GET", "/api/hq/leaderboard", headers=owner_headers).json()
        assert not any(row["location"] == "hq-unrelated-biz" for row in leaderboard)

        # And the unrelated business's own view must actually see its revenue.
        other_rollup = req(client, "GET", "/api/hq/kpi-roll-up", headers=other, params={"days": 3650}).json()
        assert any(loc["location"] == "hq-unrelated-biz" for loc in other_rollup["locations"])
    finally:
        _run(db.transactions.delete_one({"id": txn_id}))


def test_sibling_locations_under_the_same_brand_are_visible_to_each_other(client, owner_headers):
    brand_id = f"BRAND-{uuid.uuid4().hex[:8]}"
    loc_a_id = f"LOC-A-{uuid.uuid4().hex[:8]}"
    loc_b_id = f"LOC-B-{uuid.uuid4().hex[:8]}"
    _run(db.businesses.insert_many([
        {"id": brand_id, "name": "Test Brand HQ", "parentBrandId": None},
        {"id": loc_a_id, "name": "Location A", "parentBrandId": brand_id},
        {"id": loc_b_id, "name": "Location B", "parentBrandId": brand_id},
    ]))
    loc_a_owner = _login_as(client, owner_headers, email="hq.loc.a@nua.com", business_id=loc_a_id)

    txn_id = f"TXN-HQ-SIB-{uuid.uuid4().hex[:8]}"
    _run(db.transactions.insert_one({
        "id": txn_id, "businessId": loc_b_id, "locationId": loc_b_id,
        "total": 500.0, "gst": 45.45, "timestamp": "2026-09-14T00:00:00+00:00",
        "items": [], "subtotal": 500.0, "paymentMethod": "cash", "location": "Main", "cashier": "Test",
    }))
    try:
        rollup = req(client, "GET", "/api/hq/kpi-roll-up", headers=loc_a_owner, params={"days": 3650}).json()
        assert any(loc["location"] == loc_b_id for loc in rollup["locations"]), (
            "a sibling location's revenue under the same brand must be visible in the HQ rollup"
        )

        locations = req(client, "GET", "/api/hq/locations", headers=loc_a_owner).json()
        assert loc_b_id in {loc["id"] for loc in locations}
    finally:
        _run(db.transactions.delete_one({"id": txn_id}))
        _run(db.businesses.delete_many({"id": {"$in": [brand_id, loc_a_id, loc_b_id]}}))
