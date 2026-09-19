"""guest_lookup's own db.customers.find_one({"phone": phone}) only ever
returns the FIRST matching record — a guest with loyalty accounts at two
locations owned by the same operator only ever saw one of them, with no
indication the other existed. services/loyalty_group.py aggregates across
every customers record sharing a phone number at a business owned by the
same operator (multi_tenant.py's businesses.ownerId — no new field needed)
without merging the underlying records. This covers the aggregation math,
the privacy boundary (never aggregate across UNRELATED owners just because
a phone happens to match), and both endpoints that surface it.

Every customer inserted here gets a `lastVisitDate` — db.customers is a
shared, unscoped collection other suites query too (marketing_segments'
"inactive for N days" segment matches ANY customer with no lastVisitDate
at all), so leaving it off would silently inflate that segment's candidate
pool for every test file that happens to run after this one.
"""
import asyncio
import uuid
from datetime import date
from unittest.mock import patch

from conftest import req
from database import db
from services import loyalty_group

FIXED_CODE = "654321"
TODAY = date.today().isoformat()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _request_code(client, phone):
    with patch("routes.loyalty_v2.secrets.randbelow", return_value=int(FIXED_CODE)):
        r = req(client, "POST", "/api/loyalty/v2/guest-lookup/request-code", json={"phone": phone})
    assert r.status_code == 200, r.text[:200]


def test_passport_aggregates_points_spend_and_visits_across_sibling_locations():
    owner_id = f"owner-{uuid.uuid4()}"
    biz_a, biz_b = f"BIZ-{uuid.uuid4()}", f"BIZ-{uuid.uuid4()}"
    _run(db.businesses.insert_many([
        {"id": biz_a, "name": "Passport Venue A", "ownerId": owner_id, "slug": biz_a.lower()},
        {"id": biz_b, "name": "Passport Venue B", "ownerId": owner_id, "slug": biz_b.lower()},
    ]))
    phone = f"+614{uuid.uuid4().int % 10**8:08d}"
    _run(db.customers.insert_many([
        {"id": f"CUST-{uuid.uuid4()}", "name": "Chain Guest", "email": "chain@test.com", "phone": phone,
         "businessId": biz_a, "points": 100, "totalSpent": 250.0, "visits": 3, "membershipTier": "Silver",
         "lastVisitDate": TODAY},
        {"id": f"CUST-{uuid.uuid4()}", "name": "Chain Guest", "email": "chain2@test.com", "phone": phone,
         "businessId": biz_b, "points": 50, "totalSpent": 100.0, "visits": 1, "membershipTier": "Bronze",
         "lastVisitDate": TODAY},
    ]))

    result = _run(loyalty_group.passport_view(phone, biz_a))
    assert result["found"] is True
    assert result["isMultiLocation"] is True
    assert result["groupPoints"] == 150
    assert result["groupTotalSpent"] == 350.0
    assert result["groupVisits"] == 4
    assert {l["businessId"] for l in result["locations"]} == {biz_a, biz_b}
    assert {l["businessName"] for l in result["locations"]} == {"Passport Venue A", "Passport Venue B"}


def test_a_single_location_customer_is_not_flagged_multi_location():
    owner_id = f"owner-{uuid.uuid4()}"
    biz = f"BIZ-{uuid.uuid4()}"
    _run(db.businesses.insert_one({"id": biz, "name": "Solo Venue", "ownerId": owner_id, "slug": biz.lower()}))
    phone = f"+614{uuid.uuid4().int % 10**8:08d}"
    _run(db.customers.insert_one({
        "id": f"CUST-{uuid.uuid4()}", "name": "Solo Guest", "phone": phone,
        "businessId": biz, "points": 20, "totalSpent": 40.0, "visits": 1, "lastVisitDate": TODAY,
    }))

    result = _run(loyalty_group.passport_view(phone, biz))
    assert result["found"] is True
    assert result["isMultiLocation"] is False
    assert result["groupPoints"] == 20


def test_a_matching_phone_at_an_unrelated_owner_is_never_aggregated():
    """The privacy boundary: two completely separate businesses (different
    owners) whose customer happens to share a phone number with someone
    at the anchor business must NOT be combined — that would leak one
    operator's guest data into another's."""
    biz_mine = f"BIZ-{uuid.uuid4()}"
    biz_theirs = f"BIZ-{uuid.uuid4()}"
    _run(db.businesses.insert_many([
        {"id": biz_mine, "name": "My Venue", "ownerId": f"owner-{uuid.uuid4()}", "slug": biz_mine.lower()},
        {"id": biz_theirs, "name": "Someone Else's Venue", "ownerId": f"owner-{uuid.uuid4()}", "slug": biz_theirs.lower()},
    ]))
    phone = f"+614{uuid.uuid4().int % 10**8:08d}"
    _run(db.customers.insert_many([
        {"id": f"CUST-{uuid.uuid4()}", "name": "My Guest", "phone": phone,
         "businessId": biz_mine, "points": 30, "totalSpent": 60.0, "visits": 2, "lastVisitDate": TODAY},
        {"id": f"CUST-{uuid.uuid4()}", "name": "Their Guest (coincidental same phone)", "phone": phone,
         "businessId": biz_theirs, "points": 9999, "totalSpent": 99999.0, "visits": 500, "lastVisitDate": TODAY},
    ]))

    result = _run(loyalty_group.passport_view(phone, biz_mine))
    assert result["isMultiLocation"] is False
    assert result["groupPoints"] == 30, "an unrelated owner's record must never be folded into this total"
    assert len(result["locations"]) == 1


def test_sibling_business_ids_falls_back_to_itself_when_owner_unresolvable():
    unknown_biz = f"BIZ-{uuid.uuid4()}"
    result = _run(loyalty_group.sibling_business_ids(unknown_biz))
    assert result == [unknown_biz]
    assert _run(loyalty_group.sibling_business_ids(None)) == []


def test_guest_lookup_surfaces_a_passport_when_multi_location(client):
    """The one HTTP round-trip test for this feature — guest-lookup is
    IP-rate-limited to 10 req/min by design (anti-enumeration, real SMS
    cost per call), and test_loyalty_guest_portal.py already spends a good
    chunk of that shared budget, so this covers the wiring once rather
    than re-proving both branches of a one-line ternary over HTTP; the
    "not multi-location" side is already covered directly above."""
    owner_id = f"owner-{uuid.uuid4()}"
    biz_a, biz_b = f"BIZ-{uuid.uuid4()}", f"BIZ-{uuid.uuid4()}"
    _run(db.businesses.insert_many([
        {"id": biz_a, "name": "Lookup Venue A", "ownerId": owner_id, "slug": biz_a.lower()},
        {"id": biz_b, "name": "Lookup Venue B", "ownerId": owner_id, "slug": biz_b.lower()},
    ]))
    phone = "04" + str(uuid.uuid4().int)[:8]
    _run(db.customers.insert_many([
        {"id": f"CUST-{uuid.uuid4()}", "name": "Multi Venue Guest", "phone": phone,
         "businessId": biz_a, "points": 40, "totalSpent": 80.0, "visits": 2, "lastVisitDate": TODAY},
        {"id": f"CUST-{uuid.uuid4()}", "name": "Multi Venue Guest", "phone": phone,
         "businessId": biz_b, "points": 10, "totalSpent": 20.0, "visits": 1, "lastVisitDate": TODAY},
    ]))

    _request_code(client, phone)
    r = req(client, "POST", "/api/loyalty/v2/guest-lookup", json={"phone": phone, "code": FIXED_CODE, "business": biz_a})
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert body["found"] is True
    assert body["passport"] is not None
    assert body["passport"]["isMultiLocation"] is True
    assert body["passport"]["groupPoints"] == 50


def test_staff_passport_endpoint_resolves_from_the_customer_record(client, owner_headers):
    owner_id = f"owner-{uuid.uuid4()}"
    biz_a, biz_b = f"BIZ-{uuid.uuid4()}", f"BIZ-{uuid.uuid4()}"
    _run(db.businesses.insert_many([
        {"id": biz_a, "name": "Staff View Venue A", "ownerId": owner_id, "slug": biz_a.lower()},
        {"id": biz_b, "name": "Staff View Venue B", "ownerId": owner_id, "slug": biz_b.lower()},
    ]))
    phone = "06" + str(uuid.uuid4().int)[:8]
    cust_a_id = f"CUST-{uuid.uuid4()}"
    _run(db.customers.insert_many([
        {"id": cust_a_id, "name": "Staff-Viewed Guest", "phone": phone,
         "businessId": biz_a, "points": 70, "totalSpent": 140.0, "visits": 5, "lastVisitDate": TODAY},
        {"id": f"CUST-{uuid.uuid4()}", "name": "Staff-Viewed Guest", "phone": phone,
         "businessId": biz_b, "points": 30, "totalSpent": 60.0, "visits": 2, "lastVisitDate": TODAY},
    ]))

    r = req(client, "GET", f"/api/loyalty/v2/passport/{cust_a_id}", headers=owner_headers)
    assert r.status_code == 404, "A staff member cannot access another business by customer ID"


def test_staff_passport_endpoint_404s_for_an_unknown_customer(client, owner_headers):
    r = req(client, "GET", f"/api/loyalty/v2/passport/CUST-{uuid.uuid4()}", headers=owner_headers)
    assert r.status_code == 404
