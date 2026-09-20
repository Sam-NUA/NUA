"""routes/loyalty.py had several endpoints with no auth dependency at all
(update_loyalty_reward, and the whole events CRUD) plus zero businessId
scoping across loyalty_rewards, loyalty_tiers, and events — any business's
staff could modify another business's rewards/tiers/events, and every
business's rows were mixed together on read.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Loyalty Test Owner", "email": email, "password": "LoyaltyTenantTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "LoyaltyTenantTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def test_loyalty_endpoints_require_authentication(anon):
    assert req(anon, "GET", "/api/loyalty/rewards").status_code == 401
    assert req(anon, "PUT", "/api/loyalty/rewards/some-id", json={"name": "x"}).status_code == 401
    assert req(anon, "GET", "/api/events").status_code == 401
    assert req(anon, "POST", "/api/events", json={}).status_code == 401
    assert req(anon, "PUT", "/api/events/some-id", json={}).status_code == 401


def test_a_different_businesss_reward_is_not_visible_or_editable(client, owner_headers):
    other = _login_as(client, owner_headers, email="loyalty.reward.other@nua.com", business_id="loyalty-reward-biz")

    created = req(client, "POST", "/api/loyalty/rewards", headers=other, json={
        "name": "Other Biz Reward", "pointsCost": 100})
    assert created.status_code == 200, created.text[:200]
    reward_id = created.json()["id"]
    try:
        listed = req(client, "GET", "/api/loyalty/rewards", headers=owner_headers).json()
        assert reward_id not in {r["id"] for r in listed}

        edit = req(client, "PUT", f"/api/loyalty/rewards/{reward_id}", headers=owner_headers,
                   json={"pointsCost": 1})
        assert edit.status_code == 404, edit.text[:200]

        delete = req(client, "DELETE", f"/api/loyalty/rewards/{reward_id}", headers=owner_headers)
        assert delete.status_code == 200
        still_there = req(client, "GET", "/api/loyalty/rewards", headers=other).json()
        assert reward_id in {r["id"] for r in still_there}, "a different business must not be able to delete this reward"
    finally:
        _run(db.loyalty_rewards.delete_one({"id": reward_id}))


def test_a_different_businesss_event_is_not_visible_or_editable(client, owner_headers):
    other = _login_as(client, owner_headers, email="loyalty.event.other@nua.com", business_id="loyalty-event-biz")

    created = req(client, "POST", "/api/events", headers=other, json={
        "name": "Other Biz Event", "description": "test", "date": "2026-12-01", "time": "18:00", "capacity": 50})
    assert created.status_code == 200, created.text[:200]
    event_id = created.json()["id"]
    try:
        listed = req(client, "GET", "/api/events", headers=owner_headers, params={"active_only": False}).json()
        assert event_id not in {e["id"] for e in listed}

        edit = req(client, "PUT", f"/api/events/{event_id}", headers=owner_headers, json={"capacity": 999})
        assert edit.status_code == 404, edit.text[:200]

        book = req(client, "POST", f"/api/events/{event_id}/book", headers=owner_headers, params={"quantity": 1})
        assert book.status_code == 404, book.text[:200]
    finally:
        _run(db.events.delete_one({"id": event_id}))


def test_two_businesses_get_independent_seeded_loyalty_tiers(client, owner_headers):
    # Mutates only the freshly-created `other` business's tier, never
    # owner_headers' ("default") — that business's Bronze-tier discount
    # feeds real checkout pricing math in many other tests across this
    # shared-DB suite (routes/transactions.py applies it to every sale for
    # a Bronze customer), so changing it here without ever reverting would
    # silently corrupt every other test's expected totals for the rest of
    # the suite run.
    other = _login_as(client, owner_headers, email="loyalty.tiers.other@nua.com", business_id="loyalty-tiers-biz")

    tiers_a = req(client, "GET", "/api/loyalty/tiers", headers=owner_headers).json()
    tiers_b = req(client, "GET", "/api/loyalty/tiers", headers=other).json()
    bronze_a_before = next(t for t in tiers_a if t["id"] == "tier-bronze")

    edit = req(client, "PUT", "/api/loyalty/tiers/tier-bronze", headers=other, json={"discountPercent": 42})
    assert edit.status_code == 200, edit.text[:200]
    assert edit.json()["discountPercent"] == 42

    tiers_a_after = req(client, "GET", "/api/loyalty/tiers", headers=owner_headers).json()
    bronze_a_after = next(t for t in tiers_a_after if t["id"] == "tier-bronze")
    assert bronze_a_after["discountPercent"] == bronze_a_before["discountPercent"], (
        "one business editing its Bronze tier must not change a different business's Bronze tier"
    )
    assert tiers_b is not None and bronze_a_after is not None
