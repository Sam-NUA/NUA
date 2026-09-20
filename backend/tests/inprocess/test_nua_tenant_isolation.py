"""routes/nua.py (the Ash/NUA autonomous operating layer) and the services
behind it had zero businessId scoping almost everywhere: Ash insights and
Ash plans were keyed with no tenant tag at all (so two businesses' same-
named insight silently collided/overwrote each other, and any business
could list, read, approve, or reject any other business's autonomous
plans — real tool-executing actions); the daily briefing collided the
same way (keyed only by date, so whichever business generated theirs
last that day overwrote every other business's revenue/bookings/margin
narrative); and per-tool permission overrides (auto/approval/disabled)
in db.ash_tool_config had no tenant tag either, so one business disabling
or promoting a tool silently applied the same change to every other
business on the deployment.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "NUA Test Owner", "email": email, "password": "NuaTenantTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "NuaTenantTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def test_ash_insights_do_not_collide_or_leak_across_businesses(client, owner_headers):
    other = _login_as(client, owner_headers, email="nua.insights.other@nua.com", business_id="nua-insights-other-biz")

    # Simulate what run_all_insights() would write for each business —
    # same category/key, different businessId, must be two separate docs.
    _run(db.ash_insights.insert_one({
        "id": "INS-MINE", "category": "theft", "key": "theft-signal-1", "severity": "high",
        "title": "Mine", "body": "x", "recommendedActions": [], "data": {},
        "createdAt": "2026-01-01T00:00:00", "resolvedAt": None, "businessId": "default",
    }))
    _run(db.ash_insights.insert_one({
        "id": "INS-OTHER", "category": "theft", "key": "theft-signal-1", "severity": "high",
        "title": "Other biz theft signal", "body": "x", "recommendedActions": [], "data": {},
        "createdAt": "2026-01-01T00:00:00", "resolvedAt": None, "businessId": "nua-insights-other-biz",
    }))
    try:
        mine = req(client, "GET", "/api/nua/insights", headers=owner_headers).json()
        assert not any(i["id"] == "INS-OTHER" for i in mine)
        assert any(i["id"] == "INS-MINE" for i in mine)

        dismiss_attack = req(client, "POST", "/api/nua/insights/INS-OTHER/dismiss", headers=owner_headers)
        assert dismiss_attack.status_code == 404

        still_open = _run(db.ash_insights.find_one({"id": "INS-OTHER"}, {"_id": 0}))
        assert still_open["resolvedAt"] is None
    finally:
        _run(db.ash_insights.delete_many({"id": {"$in": ["INS-MINE", "INS-OTHER"]}}))


def test_ash_plans_are_not_visible_or_actionable_across_businesses(client, owner_headers):
    other = _login_as(client, owner_headers, email="nua.plans.other@nua.com", business_id="nua-plans-other-biz")

    _run(db.ash_plans.insert_one({
        "id": "PLAN-OTHERBIZ", "goal": "secret plan", "rationale": "", "expectedOutcome": "",
        "risk": "low", "persona": "default", "personaLabel": "Default", "steps": [],
        "status": "proposed", "createdBy": "x", "createdAt": "2026-01-01T00:00:00",
        "updatedAt": "2026-01-01T00:00:00", "businessId": "nua-plans-other-biz",
    }))
    try:
        mine = req(client, "GET", "/api/nua/plans", headers=owner_headers).json()
        assert not any(p["id"] == "PLAN-OTHERBIZ" for p in mine)

        get_mine = req(client, "GET", "/api/nua/plans/PLAN-OTHERBIZ", headers=owner_headers)
        assert get_mine.status_code == 404

        approve_mine = req(client, "POST", "/api/nua/plans/PLAN-OTHERBIZ/approve", headers=owner_headers)
        assert approve_mine.status_code == 200
        assert approve_mine.json().get("error") == "plan not found"

        reject_mine = req(client, "POST", "/api/nua/plans/PLAN-OTHERBIZ/reject", headers=owner_headers, json={})
        assert reject_mine.json().get("error") == "plan not found"

        still_proposed = _run(db.ash_plans.find_one({"id": "PLAN-OTHERBIZ"}, {"_id": 0}))
        assert still_proposed["status"] == "proposed", "cross-tenant approve/reject attempts must not have mutated it"
    finally:
        _run(db.ash_plans.delete_one({"id": "PLAN-OTHERBIZ"}))


def test_daily_briefings_do_not_collide_across_businesses(client, owner_headers):
    other = _login_as(client, owner_headers, email="nua.briefing.other@nua.com", business_id="nua-briefing-other-biz")

    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()
    _run(db.ash_briefings.insert_one({
        "id": "BRIEF-OTHERBIZ", "date": today, "narrative": "Other business's real revenue is $999,999",
        "data": {}, "createdAt": "2026-01-01T00:00:00", "businessId": "nua-briefing-other-biz",
    }))
    try:
        mine = req(client, "GET", "/api/nua/briefing", headers=owner_headers)
        assert mine.status_code == 200
        assert "999,999" not in mine.json().get("narrative", "")
        assert mine.json().get("businessId") != "nua-briefing-other-biz"
    finally:
        _run(db.ash_briefings.delete_one({"id": "BRIEF-OTHERBIZ"}))


def test_tool_permission_override_does_not_leak_across_businesses(client, owner_headers):
    other = _login_as(client, owner_headers, email="nua.toolperm.other@nua.com", business_id="nua-toolperm-other-biz")

    # As "other", disable a low-risk tool.
    disabled = req(client, "PUT", "/api/nua/tools/fetch_open_insights/permission", headers=other,
                    json={"permission": "disabled"})
    assert disabled.status_code == 200, disabled.text[:200]
    try:
        mine = req(client, "GET", "/api/nua/tools", headers=owner_headers).json()
        mine_tool = next(t for t in mine if t["name"] == "fetch_open_insights")
        assert mine_tool["effectivePermission"] != "disabled", (
            "another business disabling a tool must not disable it for this business too"
        )

        theirs = req(client, "GET", "/api/nua/tools", headers=other).json()
        their_tool = next(t for t in theirs if t["name"] == "fetch_open_insights")
        assert their_tool["effectivePermission"] == "disabled"
    finally:
        _run(db.ash_tool_config.delete_many({"toolName": "fetch_open_insights", "businessId": "nua-toolperm-other-biz"}))
