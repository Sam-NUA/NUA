"""Campaign targeting only ever supported "all customers" or a single
loyalty tier — no way to build a segment like "spent over $X" or "hasn't
visited in 30 days".

Worse, campaign creation/send queried db.members for recipients — a
collection nothing in this codebase has written to since the member-portal
router was removed (see routes/multi_tenant.py's comment on the same
collection). On any deployment created after that removal, every campaign
silently had zero real recipients. Segments are built against
db.customers, the actual live guest record, and campaign send now goes
through the same resolver.
"""
import asyncio
from datetime import date, timedelta

from conftest import req


def _seed_customer(name, email, *, spend=0, visits=0, tier="Bronze", last_visit=None):
    loop = asyncio.get_event_loop()
    from database import db
    from routes.customers import Customer
    doc = Customer(businessId="default", name=name, email=email, phone="0400000000", membershipTier=tier,
                    totalSpent=spend, visits=visits).dict()
    if last_visit is not None:
        doc["lastVisitDate"] = last_visit
    loop.run_until_complete(db.customers.insert_one(doc))
    return doc["id"]


def test_segment_preview_filters_by_spend_and_tier(client, owner_headers):
    _seed_customer("Big Spender", "big@nua.com", spend=500, visits=20, tier="Gold")
    _seed_customer("Small Spender", "small@nua.com", spend=10, visits=1, tier="Bronze")

    r = req(client, "POST", "/api/marketing/segments/preview", headers=owner_headers,
            json={"rules": {"minSpend": 100}})
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert any(c["email"] == "big@nua.com" for c in body["sample"])
    assert not any(c["email"] == "small@nua.com" for c in body["sample"])

    r2 = req(client, "POST", "/api/marketing/segments/preview", headers=owner_headers,
            json={"rules": {"tier": "Gold"}})
    assert all(c["membershipTier"] == "Gold" for c in r2.json()["sample"])


def test_segment_inactive_for_days_catches_never_visited_and_stale(client, owner_headers):
    # Dates relative to "today" rather than hardcoded — a fixed absolute date
    # for the "recent" visitor ages past the 30-day inactive threshold as real
    # time passes, which is exactly what made this test a calendar time-bomb
    # (it silently started failing ~30 days after whichever day it was
    # written on, with no code change involved).
    recent_date = (date.today() - timedelta(days=5)).isoformat()
    stale_date = (date.today() - timedelta(days=365 * 5)).isoformat()
    _seed_customer("Never Visited", "never@nua.com", spend=0, visits=0)
    _seed_customer("Recent Visitor", "recent@nua.com", spend=50, visits=3, last_visit=recent_date)
    _seed_customer("Stale Visitor", "stale@nua.com", spend=50, visits=3, last_visit=stale_date)

    r = req(client, "POST", "/api/marketing/segments/preview", headers=owner_headers,
            json={"rules": {"inactiveForDays": 30}})
    assert r.status_code == 200, r.text[:200]

    # The endpoint's `sample` is deliberately capped to the first 20 matches
    # (it's a preview, not a full export) — this suite runs 400+ tests against
    # one shared in-memory DB, so by the time this test runs there can already
    # be 20+ other "inactive" customers seeded by earlier tests, pushing our
    # own seeded row out of the visible sample even though it genuinely
    # matched. Query with the exact same matcher the endpoint itself uses,
    # rather than asserting against the truncated preview, so this test's
    # correctness doesn't depend on how much state ran before it.
    from database import db
    from routes.advanced_features import _build_segment_query
    query = _build_segment_query({"inactiveForDays": 30})
    loop = asyncio.get_event_loop()
    matched = loop.run_until_complete(db.customers.find(query, {"_id": 0, "email": 1}).to_list(100000))
    # .get(), not c["email"] — other tests' seed data can leave customer-shaped
    # docs with no email field at all, and this test only cares about the
    # three it seeded above, not the shape of everything else in the shared DB.
    matched_emails = {c.get("email") for c in matched if c.get("email")}
    assert "never@nua.com" in matched_emails
    assert "stale@nua.com" in matched_emails
    assert "recent@nua.com" not in matched_emails


def test_saved_segment_can_be_used_as_campaign_target_and_actually_gets_emailed(client, owner_headers, monkeypatch):
    _seed_customer("VIP Guest", "vip@nua.com", spend=1000, visits=50, tier="Gold")
    _seed_customer("Regular Guest", "regular@nua.com", spend=20, visits=2, tier="Bronze")

    seg = req(client, "POST", "/api/marketing/segments", headers=owner_headers,
              json={"name": "Big spenders", "rules": {"minSpend": 500}})
    assert seg.status_code == 200, seg.text[:200]
    segment_id = seg.json()["id"]

    listed = req(client, "GET", "/api/marketing/segments", headers=owner_headers).json()
    assert any(s["id"] == segment_id for s in listed)

    campaign = req(client, "POST", "/api/marketing/campaigns", headers=owner_headers, json={
        "name": "VIP thank you", "subject": "Thanks!", "body": "Hi {first_name}", "segmentId": segment_id})
    assert campaign.status_code == 200, campaign.text[:200]
    # Demo/seed data and other tests in this session may also have
    # customers with totalSpent >= 500 — assert this one's in the segment,
    # not an exact count that'd be fragile to whatever else is in the db.
    assert campaign.json()["recipientCount"] >= 1

    sent_to = []

    async def fake_send_email(to, subject, body):
        sent_to.append(to)
        return {"channel": "email", "delivered": True, "to": to}

    import utils.notifications
    monkeypatch.setattr(utils.notifications, "send_email", fake_send_email)

    result = req(client, "POST", f"/api/marketing/campaigns/{campaign.json()['id']}/send", headers=owner_headers)
    assert result.status_code == 200, result.text[:200]
    # The segment's actual point: a high-spend customer gets emailed here,
    # a low-spend one filtered out by the same query never does.
    assert "vip@nua.com" in sent_to
    assert "regular@nua.com" not in sent_to

    deleted = req(client, "DELETE", f"/api/marketing/segments/{segment_id}", headers=owner_headers)
    assert deleted.status_code == 200


def test_segment_endpoints_require_owner_or_manager(client, owner_headers):
    req(client, "POST", "/api/auth/staff/add", headers=owner_headers, json={
        "name": "Marketing Cashier", "email": "marketing.cashier@nua.com",
        "password": "CashierPass1!", "role": "cashier"})
    tok = req(client, "POST", "/api/auth/login", json={
        "email": "marketing.cashier@nua.com", "password": "CashierPass1!"}).json()
    client.cookies.clear()
    cashier_headers = {"Authorization": f"Bearer {tok['token']}"}

    assert req(client, "POST", "/api/marketing/segments/preview", headers=cashier_headers,
               json={"rules": {}}).status_code == 403
    assert req(client, "GET", "/api/marketing/segments", headers=cashier_headers).status_code == 403
    assert req(client, "POST", "/api/marketing/segments", headers=cashier_headers,
               json={"name": "x", "rules": {}}).status_code == 403
