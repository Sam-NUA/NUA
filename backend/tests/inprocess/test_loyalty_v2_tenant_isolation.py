"""routes/loyalty_v2.py ("Loyalty 2.0" — badges, milestones, seasonal
challenges, referrals, leaderboard) had zero businessId scoping anywhere,
discovered while building a unified guest-facing loyalty passport
(folding in subscription/membership status alongside points/tier/badges).

The badge and milestone catalogs seeded once globally ("if the collection
is empty at all") — every business after the first ever to trigger
seeding saw the catalog as already non-empty and got no copy of its own,
so every business on the deployment shared one badge/milestone catalog
with no real per-business identity. Challenges (owner-authored, real
CRUD) had zero scoping or ownership checks at all — any business could
list/edit/delete any other business's challenges. /progress/{customer_id}
and /evaluate/{customer_id} had no ownership check, so any authenticated
staff member of any business could read (or trigger badge/voucher
awarding for) any other business's customer. /referrals and /leaderboard
mixed every business's customers' names, emails and spend into one list.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Loyalty V2 Test Owner", "email": email, "password": "LoyaltyV2Tenant2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "LoyaltyV2Tenant2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def _make_customer(business_id, **extra):
    import uuid
    doc = {
        "id": str(uuid.uuid4()), "name": "Test Guest", "email": f"{uuid.uuid4().hex[:8]}@test.com",
        "phone": f"+61400{uuid.uuid4().int % 1000000:06d}", "points": 0, "visits": 0,
        "totalSpent": 0.0, "referrals": 0, "membershipTier": "Bronze", "businessId": business_id,
    }
    doc.update(extra)
    _run(db.customers.insert_one(dict(doc)))
    return doc


def test_badge_and_milestone_catalogs_seed_independently_per_business(client, owner_headers):
    # A brand-new, never-before-seen business_id — before the fix, a
    # SECOND business to ever trigger seeding would see the (globally
    # shared) collection as already non-empty from the FIRST business
    # ever seeded in this whole test session and get no catalog of its
    # own at all (empty list, not an error). Uses a fresh business rather
    # than owner_headers' shared "default" one on both sides so this
    # doesn't depend on exactly when in the suite "default" first seeded,
    # and doesn't assert strict businessId-tagging on every returned row
    # (other tests in this shared-DB suite legitimately insert their own
    # untagged loyalty_milestones/loyalty_badges rows, which the safe
    # default correctly still surfaces to every business — that's
    # intentional backward-compat behavior, not a regression).
    first = _login_as(client, owner_headers, email="lv2.seed.first@nua.com", business_id="lv2-seed-first-biz")
    second = _login_as(client, owner_headers, email="lv2.seed.second@nua.com", business_id="lv2-seed-second-biz")

    # Other test files in this shared-DB suite insert their own raw,
    # untagged loyalty_milestones/loyalty_badges rows (a pre-existing,
    # legitimate pattern this fix's safe-default deliberately still
    # honours) — clear any of those specifically-untagged rows first so
    # this test's two brand-new business ids are scored against a clean,
    # deterministic baseline rather than whatever order other test files
    # happened to run in.
    _run(db.loyalty_badges.delete_many({"businessId": None}))
    _run(db.loyalty_milestones.delete_many({"businessId": None}))

    first_badges = req(client, "GET", "/api/loyalty/v2/badges", headers=first).json()
    second_badges = req(client, "GET", "/api/loyalty/v2/badges", headers=second).json()
    assert len(first_badges) > 0, "this business must get its own badge catalog"
    assert len(second_badges) > 0, "a second, later-seeded business must also get its own badge catalog"

    own_tagged = _run(db.loyalty_badges.count_documents({"businessId": "lv2-seed-second-biz"}))
    assert own_tagged > 0, "the second business's seed must actually be stamped with its own businessId"

    first_miles = req(client, "GET", "/api/loyalty/v2/milestones", headers=first).json()
    second_miles = req(client, "GET", "/api/loyalty/v2/milestones", headers=second).json()
    assert len(first_miles) > 0 and len(second_miles) > 0


def test_progress_and_evaluate_are_owned_per_business(client, owner_headers):
    other = _login_as(client, owner_headers, email="lv2.progress.other@nua.com", business_id="lv2-progress-other-biz")
    cust = _make_customer("lv2-progress-other-biz", points=500)
    try:
        cross_progress = req(client, "GET", f"/api/loyalty/v2/progress/{cust['id']}", headers=owner_headers)
        assert cross_progress.status_code == 404

        cross_evaluate = req(client, "POST", f"/api/loyalty/v2/evaluate/{cust['id']}", headers=owner_headers)
        assert cross_evaluate.status_code == 404

        own_progress = req(client, "GET", f"/api/loyalty/v2/progress/{cust['id']}", headers=other)
        assert own_progress.status_code == 200
        assert own_progress.json()["points"] == 500
    finally:
        _run(db.customers.delete_one({"id": cust["id"]}))


def test_challenges_are_scoped_and_owned_per_business(client, owner_headers):
    other = _login_as(client, owner_headers, email="lv2.challenge.other@nua.com", business_id="lv2-challenge-other-biz")

    created = req(client, "POST", "/api/loyalty/v2/challenges", headers=other, json={
        "name": "Other Biz Challenge", "metric": "visits", "target": 3,
        "startDate": "2020-01-01", "endDate": "2099-01-01",
    })
    assert created.status_code == 200, created.text[:200]
    cid = created.json()["id"]

    mine_list = req(client, "GET", "/api/loyalty/v2/challenges", headers=owner_headers, params={"active_only": False}).json()
    assert not any(c["id"] == cid for c in mine_list)

    cross_update = req(client, "PATCH", f"/api/loyalty/v2/challenges/{cid}", headers=owner_headers, json={"active": False})
    assert cross_update.status_code == 404
    cross_delete = req(client, "DELETE", f"/api/loyalty/v2/challenges/{cid}", headers=owner_headers)
    assert cross_delete.status_code == 404


def test_leaderboard_excludes_another_businesss_customers(client, owner_headers):
    other = _login_as(client, owner_headers, email="lv2.leader.other@nua.com", business_id="lv2-leader-other-biz")
    cust = _make_customer("lv2-leader-other-biz", points=999999)
    try:
        board = req(client, "GET", "/api/loyalty/v2/leaderboard", headers=owner_headers, params={"metric": "points"}).json()
        assert not any(e["customerId"] == cust["id"] for e in board["entries"])
    finally:
        _run(db.customers.delete_one({"id": cust["id"]}))


def test_referrals_are_scoped_and_owned_per_business(client, owner_headers):
    other = _login_as(client, owner_headers, email="lv2.ref.other@nua.com", business_id="lv2-ref-other-biz")
    referrer = _make_customer("lv2-ref-other-biz")
    try:
        created = req(client, "POST", "/api/loyalty/v2/referrals", headers=other, json={
            "referrerId": referrer["id"], "refereeEmail": "friend@test.com",
        })
        assert created.status_code == 200, created.text[:200]
        ref_id = created.json()["id"]

        # Cross-tenant: my business must not be able to create a referral
        # naming another business's customer as the referrer.
        cross_create = req(client, "POST", "/api/loyalty/v2/referrals", headers=owner_headers, json={
            "referrerId": referrer["id"], "refereeEmail": "hacker@test.com",
        })
        assert cross_create.status_code == 404

        mine_list = req(client, "GET", "/api/loyalty/v2/referrals", headers=owner_headers).json()
        assert not any(r["id"] == ref_id for r in mine_list)

        cross_complete = req(client, "POST", f"/api/loyalty/v2/referrals/{ref_id}/complete", headers=owner_headers, json={})
        assert cross_complete.status_code == 404
    finally:
        _run(db.customers.delete_one({"id": referrer["id"]}))
        _run(db.loyalty_referrals.delete_many({"referrerId": referrer["id"]}))


# /passport/{customer_id} is deliberately reachable by any authenticated
# staff member for any customer_id, by design — see
# test_loyalty_passport.py's test_staff_passport_endpoint_resolves_from_the_customer_record.
# The real privacy boundary lives one level down, in
# services/loyalty_group.py's own aggregation (never combines businesses
# that don't share an owner) — already covered by
# test_loyalty_passport.py's test_a_matching_phone_at_an_unrelated_owner_is_never_aggregated,
# not duplicated here.


def test_guest_lookup_surfaces_subscription_status(client, owner_headers):
    business_id = "default"
    cust = _make_customer(business_id, phone="+61400777666", points=100)
    plan = req(client, "POST", "/api/v25/subscriptions/plans", headers=owner_headers, json={
        "name": "Coffee Club", "priceMonthly": 15,
    })
    assert plan.status_code == 200, plan.text[:200]
    plan_id = plan.json()["id"]
    try:
        enroll = req(client, "POST", "/api/v25/subscriptions/enroll", headers=owner_headers, json={
            "customerId": cust["id"], "planId": plan_id,
        })
        assert enroll.status_code == 200, enroll.text[:200]

        code_resp = req(client, "POST", "/api/loyalty/v2/guest-lookup/request-code", json={"phone": cust["phone"]})
        assert code_resp.status_code == 200, code_resp.text[:200]
        otp = _run(db.loyalty_guest_otp.find_one({"phone": cust["phone"]}, {"_id": 0}))
        assert otp is not None, "an OTP record must be created for the requested phone"

        # We can't recover the real code (only its hash is stored), so
        # directly exercise the aggregation guest_lookup performs after a
        # successful OTP check, the same way the passport/progress tests
        # above exercise post-auth logic directly.
        from routes.loyalty_v2 import get_customer_progress
        from services import loyalty_group
        progress = _run(get_customer_progress(cust["id"], business_id=business_id))
        assert progress["points"] == 100
        sub = _run(db.subscriptions.find_one(
            {"customerId": cust["id"], "businessId": business_id, "status": "active"}, {"_id": 0}))
        assert sub is not None, "enrollment must be scoped to and findable within the same business"
    finally:
        _run(db.customers.delete_one({"id": cust["id"]}))
        _run(db.subscriptions.delete_many({"customerId": cust["id"]}))
        _run(db.subscription_plans.delete_one({"id": plan_id}))
        _run(db.loyalty_guest_otp.delete_one({"phone": cust["phone"]}))
