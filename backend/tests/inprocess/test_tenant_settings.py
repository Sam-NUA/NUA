"""Pre-merge P0 risk closure: ~19 distinct `db.settings`-style singleton
documents (loyalty_config, business_theme, print_routing, pos_layout,
training_mode, surcharge/gratuity/auto-report config, receipt config, POS
session timeout, wallet offers, 2FA policy, Ash trust-ladder settings,
venue subscription/entitlements, agent autonomy, table-course settings,
business_settings, custom roles, email config, booking rules) were all
read/written with a bare `{"key": "..."}` (or equivalent) filter — no
businessId anywhere — so every business on a shared deployment read and
wrote the exact same document. Fixed at the root via
services/tenant_settings.py's get_setting/set_setting (for the plain
`db.settings` collection) and get_scoped_singleton/set_scoped_singleton
(for the handful of other single-conceptual-document collections:
loyalty_config, agent_autonomy, table_course_settings, business_settings).

This file covers the shared helper directly, plus a representative
sample of the ~25 fixed call sites across route files — not exhaustively
every one (that would just re-test the same three-line pattern
repeatedly), chosen to cover: a plain db.settings key, a get_scoped_singleton
collection, the optional_user/public-endpoint case (business/theme), and
the actor-context-default case (a function with many existing callers,
none of which pass business_id explicitly).
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Tenant Settings Test Owner", "email": email, "password": "TenantSettingsTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "TenantSettingsTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def test_get_setting_and_set_setting_are_scoped_per_business():
    from services.tenant_settings import get_setting, set_setting
    biz_a, biz_b = "tsettings-unit-biz-a", "tsettings-unit-biz-b"
    key = "tsettings_unit_test_key"
    _run(db.settings.delete_many({"key": key}))

    assert _run(get_setting(key, biz_a)) is None
    _run(set_setting(key, {"value": "A"}, biz_a))
    assert _run(get_setting(key, biz_a)) == {"value": "A"}
    assert _run(get_setting(key, biz_b)) is None, "business B must not see business A's own copy"

    _run(set_setting(key, {"value": "B"}, biz_b))
    assert _run(get_setting(key, biz_a)) == {"value": "A"}, "business B writing its own copy must not affect A's"
    assert _run(get_setting(key, biz_b)) == {"value": "B"}


def test_get_setting_hides_legacy_untagged_document():
    from services.tenant_settings import get_setting, set_setting
    key = "tsettings_unit_legacy_key"
    biz = "tsettings-unit-legacy-biz"
    _run(db.settings.delete_many({"key": key}))
    _run(db.settings.insert_one({"key": key, "value": {"legacy": True}}))
    try:
        assert _run(get_setting(key, biz)) is None
        _run(set_setting(key, {"legacy": False, "own": True}, biz))
        assert _run(get_setting(key, biz)) == {"legacy": False, "own": True}
        legacy_still_there = _run(db.settings.find_one({"key": key, "businessId": {"$exists": False}}, {"_id": 0}))
        assert legacy_still_there == {"key": key, "value": {"legacy": True}}, (
            "writing this business's own copy must never mutate the shared legacy document")
    finally:
        _run(db.settings.delete_many({"key": key}))


def test_loyalty_config_is_scoped_per_business(client, owner_headers):
    other = _login_as(client, owner_headers, email="tsettings.loyalty@nua.com", business_id="tsettings-loyalty-biz")
    try:
        updated = req(client, "PUT", "/api/loyalty/config", headers=other, json={"earnRate": 3.5})
        assert updated.status_code == 200, updated.text[:200]
        assert updated.json()["earnRate"] == 3.5

        mine = req(client, "GET", "/api/loyalty/config", headers=owner_headers).json()
        assert mine.get("earnRate") != 3.5, "a different business's loyalty config edit must not leak"

        theirs = req(client, "GET", "/api/loyalty/config", headers=other).json()
        assert theirs["earnRate"] == 3.5
    finally:
        _run(db.loyalty_config.delete_many({"businessId": "tsettings-loyalty-biz"}))


def test_agent_autonomy_is_scoped_per_business(client, owner_headers):
    other = _login_as(client, owner_headers, email="tsettings.autonomy@nua.com", business_id="tsettings-autonomy-biz")
    try:
        updated = req(client, "PUT", "/api/agent/autonomy", headers=other, json={"autoReorderThreshold": 77})
        assert updated.status_code == 200, updated.text[:200]

        mine = req(client, "GET", "/api/agent/autonomy", headers=owner_headers).json()
        assert mine.get("autoReorderThreshold") != 77

        theirs = req(client, "GET", "/api/agent/autonomy", headers=other).json()
        assert theirs["autoReorderThreshold"] == 77
    finally:
        _run(db.agent_autonomy.delete_many({"businessId": "tsettings-autonomy-biz"}))


def test_table_course_settings_are_scoped_per_business(client, owner_headers):
    other = _login_as(client, owner_headers, email="tsettings.tablecourses@nua.com", business_id="tsettings-tablecourses-biz")
    try:
        payload = {"courses": [{"key": "starter", "label": "Starter", "colour": "#111111", "maxMinutes": 20, "next": None}],
                   "overdueColour": "#ABCDEF", "autoAdvance": True}
        updated = req(client, "PUT", "/api/table-courses/settings", headers=other, json=payload)
        assert updated.status_code == 200, updated.text[:200]

        mine = req(client, "GET", "/api/table-courses/settings", headers=owner_headers).json()
        assert mine.get("overdueColour") != "#ABCDEF"

        theirs = req(client, "GET", "/api/table-courses/settings", headers=other).json()
        assert theirs["overdueColour"] == "#ABCDEF"
        assert theirs["autoAdvance"] is True
    finally:
        _run(db.table_course_settings.delete_many({"businessId": "tsettings-tablecourses-biz"}))


def test_pos_layout_is_scoped_per_business(client, owner_headers):
    other = _login_as(client, owner_headers, email="tsettings.poslayout@nua.com", business_id="tsettings-poslayout-biz")
    try:
        updated = req(client, "POST", "/api/pos/layout", headers=other, json={"cartPosition": "left", "tileSize": "large"})
        assert updated.status_code == 200, updated.text[:200]

        mine = req(client, "GET", "/api/pos/layout", headers=owner_headers).json()
        assert mine.get("cartPosition") != "left" or mine.get("tileSize") != "large"

        theirs = req(client, "GET", "/api/pos/layout", headers=other).json()
        assert theirs["cartPosition"] == "left"
        assert theirs["tileSize"] == "large"
    finally:
        _run(db.settings.delete_many({"key": "pos_layout", "businessId": "tsettings-poslayout-biz"}))


def test_business_theme_is_public_but_scoped_when_authenticated(client, owner_headers):
    # No auth at all — must not 401 (ThemeProvider mounts this at the app
    # root, above every guest-facing page).
    anon = req(client, "GET", "/api/business/theme")
    assert anon.status_code == 200, anon.text[:200]

    other = _login_as(client, owner_headers, email="tsettings.theme@nua.com", business_id="tsettings-theme-biz")
    try:
        updated = req(client, "POST", "/api/business/theme", headers=other, json={"primary": "#123456"})
        assert updated.status_code == 200, updated.text[:200]

        mine = req(client, "GET", "/api/business/theme", headers=owner_headers)
        mine_body = mine.json() or {}
        assert mine_body.get("primary") != "#123456"

        theirs = req(client, "GET", "/api/business/theme", headers=other).json()
        assert theirs["primary"] == "#123456"
    finally:
        _run(db.settings.delete_many({"key": "business_theme", "businessId": "tsettings-theme-biz"}))


def test_print_routing_requires_auth_and_is_scoped(client, owner_headers):
    assert req(client, "GET", "/api/print-routing/config").status_code in (401, 403)

    other = _login_as(client, owner_headers, email="tsettings.printrouting@nua.com", business_id="tsettings-printrouting-biz")
    try:
        payload = {"enabled": True, "routes": [{"category": "Wine", "printer": "Bar B", "priority": 1}],
                   "defaultPrinter": "Custom Printer", "defaultPriority": 3}
        updated = req(client, "POST", "/api/print-routing/config", headers=other, json=payload)
        assert updated.status_code == 200, updated.text[:200]

        mine = req(client, "GET", "/api/print-routing/config", headers=owner_headers).json()
        assert mine.get("defaultPrinter") != "Custom Printer"

        theirs = req(client, "GET", "/api/print-routing/config", headers=other).json()
        assert theirs["defaultPrinter"] == "Custom Printer"
    finally:
        _run(db.settings.delete_many({"key": "print_routing", "businessId": "tsettings-printrouting-biz"}))
