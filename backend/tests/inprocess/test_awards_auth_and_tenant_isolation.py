"""routes/awards.py had zero authentication on all 6 endpoints and zero
tenant scoping on db.awards (keyed only by "code", a shared national
identifier like "MA000119" — any business installing an award collided
with every other business's install/uninstall state on the same document).
Fair Work award data feeds directly into payroll super-contribution
calculations, so this is compliance-sensitive, not just leaky.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Awards Test Owner", "email": email, "password": "AwardsTenantTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "AwardsTenantTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def test_awards_endpoints_require_authentication(anon):
    assert req(anon, "GET", "/api/awards/catalogue").status_code == 401
    assert req(anon, "GET", "/api/awards/installed").status_code == 401
    assert req(anon, "POST", "/api/awards/install", json={"code": "MA000119"}).status_code == 401
    assert req(anon, "DELETE", "/api/awards/MA000119").status_code == 401
    assert req(anon, "POST", "/api/awards/sync-fairwork").status_code == 401
    assert req(anon, "POST", "/api/payruns/super-by-award", json={}).status_code == 401


def test_install_list_and_uninstall_still_works(client, owner_headers):
    install = req(client, "POST", "/api/awards/install", headers=owner_headers, json={"code": "MA000119"})
    assert install.status_code == 200, install.text[:200]
    try:
        listed = req(client, "GET", "/api/awards/installed", headers=owner_headers).json()
        assert any(a["code"] == "MA000119" for a in listed)

        catalogue = req(client, "GET", "/api/awards/catalogue", headers=owner_headers).json()
        entry = next(a for a in catalogue if a["code"] == "MA000119")
        assert entry["installed"] is True

        uninstall = req(client, "DELETE", "/api/awards/MA000119", headers=owner_headers)
        assert uninstall.status_code == 200, uninstall.text[:200]

        listed_after = req(client, "GET", "/api/awards/installed", headers=owner_headers).json()
        assert not any(a["code"] == "MA000119" for a in listed_after)
    finally:
        _run(db.awards.delete_many({"code": "MA000119"}))


def test_two_businesses_installing_the_same_award_code_do_not_collide(client, owner_headers):
    other = _login_as(client, owner_headers, email="awards.other.tenant@nua.com", business_id="awards-other-biz")
    try:
        req(client, "POST", "/api/awards/install", headers=owner_headers, json={"code": "MA000009"})
        req(client, "POST", "/api/awards/install", headers=other, json={"code": "MA000009"})

        # Business A uninstalling its own copy must not remove business B's.
        req(client, "DELETE", "/api/awards/MA000009", headers=owner_headers)

        other_listed = req(client, "GET", "/api/awards/installed", headers=other).json()
        assert any(a["code"] == "MA000009" for a in other_listed), (
            "one business uninstalling an award must not uninstall it for a different business"
        )

        owner_listed = req(client, "GET", "/api/awards/installed", headers=owner_headers).json()
        assert not any(a["code"] == "MA000009" for a in owner_listed)
    finally:
        _run(db.awards.delete_many({"code": "MA000009"}))


def test_super_by_award_uses_only_this_businesss_installed_award(client, owner_headers):
    other = _login_as(client, owner_headers, email="awards.super.other@nua.com", business_id="awards-super-other-biz")
    try:
        # Only the OTHER business installs MA000003 (superRate 11.5 in the
        # seed) — business A (owner_headers) never installed it.
        req(client, "POST", "/api/awards/install", headers=other, json={"code": "MA000003"})

        r = req(client, "POST", "/api/payruns/super-by-award", headers=owner_headers, json={
            "awardCode": "MA000003",
            "payrun": {"staffPayroll": [{"name": "Test Staff", "grossPay": 1000}]},
        })
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert "MA000003" in body["unresolvedAwards"], (
            "an award only installed by a different business must not resolve for this business's payrun"
        )
        assert body["staffSuper"][0]["awardName"] is None
    finally:
        _run(db.awards.delete_many({"code": "MA000003"}))


def test_uninstall_refuses_an_award_with_no_businessId(client, owner_headers):
    """uninstall_award's old inline fail-open filter (`$or businessId/None/
    $exists`) let ANY business delete an untagged award row — the same
    dangerous-for-a-delete shape as tenant_owns(). install_award always
    stamps a real businessId (no guest path creates one), so an untagged
    row is only ever genuine pre-fix legacy data; fixed to require an
    exact match, quarantining it instead."""
    _run(db.awards.insert_one({"code": "MA000099-UNTAGGED", "businessId": None, "name": "Untagged Legacy Award"}))
    try:
        r = req(client, "DELETE", "/api/awards/MA000099-UNTAGGED", headers=owner_headers)
        assert r.status_code == 404, (
            f"an untagged award must be refused for deletion (quarantined), not auto-owned, got {r.status_code}"
        )
        still_there = _run(db.awards.find_one({"code": "MA000099-UNTAGGED"}))
        assert still_there is not None, "quarantine must never delete the untagged document as a side effect"
    finally:
        _run(db.awards.delete_many({"code": "MA000099-UNTAGGED"}))
