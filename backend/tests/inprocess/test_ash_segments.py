"""_segment_customers() (backing GET /agent/segments and the autonomous
agent_tick's at-risk flagging) read totalVisits/totalSpend/lastVisit —
none of which exist on the Customer model (models/customer.py has
visits/totalSpent/lastVisitDate). Every customer silently evaluated as
visits=0/spend=0/lastVisit="" and fell into "first_timer" regardless of
their actual history, since visits<=1 is always true when the field never
existed. This pinned the fix: a real VIP customer must land in "vip", not
"first_timer".
"""
import asyncio

from conftest import req


def _seed_customer(name, email, *, spend=0, visits=0, last_visit=None):
    loop = asyncio.get_event_loop()
    from database import db
    from routes.customers import Customer
    doc = Customer(businessId="default", name=name, email=email, phone="0400000000",
                    totalSpent=spend, visits=visits).dict()
    if last_visit is not None:
        doc["lastVisitDate"] = last_visit
    loop.run_until_complete(db.customers.insert_one(doc))
    return doc["id"]


def test_a_real_vip_customer_lands_in_the_vip_segment_not_first_timer(client, owner_headers):
    vip_id = _seed_customer("Loyal VIP", "loyalvip@nua.com", spend=800, visits=25, last_visit="2026-08-01")

    r = req(client, "GET", "/api/agent/segments", headers=owner_headers)
    assert r.status_code == 200, r.text[:200]
    ids = r.json()["ids"]
    assert vip_id in ids["vip"]
    assert vip_id not in ids["first_timer"]


def test_a_stale_regular_customer_lands_in_at_risk(client, owner_headers):
    stale_id = _seed_customer("Stale Regular", "staleregular@nua.com", spend=100, visits=5, last_visit="2020-01-01")

    r = req(client, "GET", "/api/agent/segments", headers=owner_headers)
    ids = r.json()["ids"]
    assert stale_id in ids["at_risk"]
    assert stale_id not in ids["first_timer"]
