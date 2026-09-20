"""loyalty_v2.py's badge/milestone/challenge reward code wrote points to
customers.loyaltyPoints — a field that doesn't exist on the Customer
model (models/customer.py has `points`), and that checkout's own
earn/redeem never reads. Awarded points were invisible everywhere else:
POS redemption, the wallet, the liability report, and loyalty_v2's own
tier-progress calculation, which read the same wrong field back. The
exact same bug was already found and fixed once in loyalty_engine.py
(see its comment on award_points) — this is the sibling occurrence in
loyalty_v2.py.
"""
import asyncio

from conftest import req


def _seed_customer(name, email):
    loop = asyncio.get_event_loop()
    from database import db
    from routes.customers import Customer
    doc = Customer(businessId="default", name=name, email=email, phone="0400000000").dict()
    loop.run_until_complete(db.customers.insert_one(doc))
    return doc["id"]


def test_a_milestone_points_reward_lands_on_the_real_points_field(client, owner_headers):
    customer_id = _seed_customer("Milestone Customer", "milestone@nua.com")

    loop = asyncio.get_event_loop()
    from database import db
    # A milestone with a points reward and a trivially-met threshold (0
    # visits) so awarding it doesn't depend on unrelated seed/fixture data.
    loop.run_until_complete(db.loyalty_milestones.insert_one({"businessId": "default",
        "id": "MS-TEST-1", "name": "Test milestone", "metric": "visits", "threshold": 0,
        "reward": {"type": "points", "value": 50}, "order": 999,
    }))

    r = req(client, "POST", f"/api/loyalty/v2/evaluate/{customer_id}", headers=owner_headers)
    assert r.status_code == 200, r.text[:200]

    doc = loop.run_until_complete(db.customers.find_one({"id": customer_id}, {"_id": 0}))
    assert doc.get("points", 0) >= 50, "the reward must land on the real 'points' field, not 'loyaltyPoints'"
    assert "loyaltyPoints" not in doc, "must not write a phantom field alongside the real one"


def test_leaderboard_visits_metric_finds_a_real_customer_with_visits(client, owner_headers):
    tenant = dict(owner_headers, **{"X-Tenant-Id": "leaderboard-test"})
    customer_id = _seed_customer("Frequent Visitor", "frequentvisitor@nua.com")
    from database import db
    asyncio.get_event_loop().run_until_complete(
        db.customers.update_one({"id": customer_id}, {"$set": {"visits": 12}}))

    r = req(client, "GET", "/api/loyalty/v2/leaderboard", headers=tenant, params={"metric": "visits"})
    assert r.status_code == 200, r.text[:200]
    entries = r.json()["entries"]
    assert any(e["customerId"] == customer_id for e in entries), \
        "leaderboard must find customers by the real 'visits' field, not the nonexistent 'totalVisits'"
