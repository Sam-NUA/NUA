"""A "default" business (or any business) created before the
onboardingComplete field existed has it missing entirely -- falsy -- which
traps its owner behind the first-run OnboardingWizard on every login
(App.js's ProtectedRoutes renders *only* the wizard, nothing else, while
`!business.onboardingComplete`). Both the automatic startup seeder and the
manual backfill endpoint must grandfather a genuinely-missing field to
True without touching a business that explicitly has it set False (still
mid-wizard, must keep seeing it).
"""
from database import db
from routes.multi_tenant import seed_default_business
from tests.inprocess.conftest import req


def _run(coro):
    import asyncio
    return asyncio.get_event_loop().run_until_complete(coro)


def test_seed_default_business_backfills_a_legacy_default_business_missing_the_field(client):
    # Simulate a "default" business that predates the onboardingComplete
    # field -- field absent entirely, not set to False.
    _run(db.businesses.update_one({"id": "default"}, {"$unset": {"onboardingComplete": ""}}))
    biz = _run(db.businesses.find_one({"id": "default"}))
    assert "onboardingComplete" not in biz

    _run(seed_default_business())

    biz_after = _run(db.businesses.find_one({"id": "default"}))
    assert biz_after["onboardingComplete"] is True


def test_seed_default_business_does_not_touch_other_fields_during_backfill(client):
    _run(db.businesses.update_one({"id": "default"}, {"$unset": {"onboardingComplete": ""}}))
    before = _run(db.businesses.find_one({"id": "default"}, {"_id": 0}))

    _run(seed_default_business())

    after = _run(db.businesses.find_one({"id": "default"}, {"_id": 0}))
    before["onboardingComplete"] = True
    assert after == before


def test_seed_default_business_never_overrides_an_explicit_false(client):
    # A business genuinely mid-wizard (explicitly False, not missing) must
    # keep seeing it -- this is not the legacy-data bug the backfill exists
    # to fix.
    _run(db.businesses.update_one({"id": "default"}, {"$set": {"onboardingComplete": False}}))

    _run(seed_default_business())

    biz = _run(db.businesses.find_one({"id": "default"}))
    assert biz["onboardingComplete"] is False
    # Restore, so later tests in the suite that rely on a ready-to-use
    # "default" business (most of them) aren't affected by this one.
    _run(db.businesses.update_one({"id": "default"}, {"$set": {"onboardingComplete": True}}))


def test_backfill_tenant_endpoint_is_retired_without_mutating_businesses(client, owner_headers):
    before = _run(db.businesses.find_one({"id": "default"}))
    r = req(client, "POST", "/api/business/backfill-tenant", headers=owner_headers)
    assert r.status_code == 410, r.text
    assert _run(db.businesses.find_one({"id": "default"})) == before
