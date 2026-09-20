"""Staff PIN login now checks the roster: an unrostered staff member gets
needsApproval instead of a token, and a manager/owner can authorize them
on the spot with their own PIN (POST /auth/pin-login/approve). Owners and
managers are exempt — they're the ones who approve everyone else."""
from datetime import datetime, timedelta, timezone

from conftest import req


def _today_iso():
    return datetime.now(timezone.utc).date().isoformat()


def _add_staff(client, owner_headers, name, pin, role="cashier"):
    r = req(client, "POST", "/api/auth/staff/add", headers=owner_headers,
            json={"name": name, "role": role, "pin": pin})
    assert r.status_code == 200, r.text
    return r.json()


def test_unrostered_staff_gets_needs_approval_not_a_token(client, owner_headers):
    _add_staff(client, owner_headers, "ZZZ Unrostered Cashier", "7711")

    r = req(client, "POST", "/api/auth/pin-login", json={"pin": "7711"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["needsApproval"] is True
    assert "token" not in body


def test_rostered_staff_logs_in_normally(client, owner_headers):
    staff = _add_staff(client, owner_headers, "ZZZ Rostered Cashier", "7712")
    now = datetime.now(timezone.utc)
    # Clamped to today's calendar day: an uncapped now-1h/now+4h window can
    # cross midnight in either direction and land on the wrong side of the
    # "date" field below, which is a real scenario but a different one
    # (see test_is_rostered_now_handles_overnight_shifts_deterministically) —
    # not what this test is about, so it shouldn't be flaky because of it.
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = now.replace(hour=23, minute=59, second=0, microsecond=0)
    start = max(now - timedelta(hours=1), midnight)
    end = min(now + timedelta(hours=4), end_of_day)
    req(client, "POST", "/api/staff/roster", headers=owner_headers, json={
        "staffId": staff["id"], "staffName": staff["name"], "date": _today_iso(),
        "startTime": start.strftime("%H:%M"),
        "endTime": end.strftime("%H:%M"),
    })

    r = req(client, "POST", "/api/auth/pin-login", json={"pin": "7712"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "token" in body
    assert body["user"]["id"] == staff["id"]


def test_manager_and_owner_always_log_in_regardless_of_roster(client, owner_headers):
    _add_staff(client, owner_headers, "ZZZ Unrostered Manager", "7713", role="manager")
    r = req(client, "POST", "/api/auth/pin-login", json={"pin": "7713"})
    assert r.status_code == 200, r.text
    assert "token" in r.json()


def test_manager_approval_issues_a_token_and_records_an_override(client, owner_headers):
    staff = _add_staff(client, owner_headers, "ZZZ Approve Me Cashier", "7714")
    manager = _add_staff(client, owner_headers, "ZZZ Approving Manager", "7715", role="manager")

    r = req(client, "POST", "/api/auth/pin-login", json={"pin": "7714"})
    assert r.json()["needsApproval"] is True

    r = req(client, "POST", "/api/auth/pin-login/approve",
            json={"staffPin": "7714", "managerPin": "7715"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["id"] == staff["id"]
    assert "token" in body

    # Second login attempt the same day succeeds without needing approval again.
    r2 = req(client, "POST", "/api/auth/pin-login", json={"pin": "7714"})
    assert r2.status_code == 200
    assert "token" in r2.json()


def test_approve_rejects_wrong_manager_pin(client, owner_headers):
    _add_staff(client, owner_headers, "ZZZ Approve Bad Mgr Cashier", "7716")
    r = req(client, "POST", "/api/auth/pin-login/approve",
            json={"staffPin": "7716", "managerPin": "0000"})
    assert r.status_code == 401


def test_approve_rejects_a_non_manager_pin(client, owner_headers):
    """A second cashier's PIN can't be used to self-approve."""
    _add_staff(client, owner_headers, "ZZZ Approve Cashier A", "7717")
    _add_staff(client, owner_headers, "ZZZ Approve Cashier B", "7718")
    r = req(client, "POST", "/api/auth/pin-login/approve",
            json={"staffPin": "7717", "managerPin": "7718"})
    assert r.status_code == 401


def test_clock_in_blocked_for_unrostered_staff_without_override(client, owner_headers):
    """The only way a non-rostered staff member ever gets a token through the
    real UI is via /auth/pin-login/approve, which always grants today's
    override as a side effect — so this state is unreachable end-to-end.
    Still worth covering directly: clock-in enforces its own roster check
    rather than trusting that login already did, which matters if a token
    is replayed later in the day after the approval's own effects (e.g. a
    different day) or reused in a way login's gate didn't anticipate."""
    import jwt
    import os
    staff = _add_staff(client, owner_headers, "ZZZ Clockin Blocked", "7719")
    token = jwt.encode(
        {"sub": staff["id"], "email": staff["email"], "role": staff["role"],
         "businessId": staff.get("businessId"), "exp": datetime.now(timezone.utc) + timedelta(hours=8),
         "type": "access"},
        os.environ["JWT_SECRET"], algorithm="HS256",
    )
    headers = {"Authorization": f"Bearer {token}"}
    r = req(client, "POST", "/api/staff/clock-in", headers=headers)
    assert r.status_code == 403
    assert "roster" in r.json()["detail"].lower() or "rostered" in r.json()["detail"].lower()


def test_is_rostered_now_handles_overnight_shifts_deterministically():
    """A shift dated today running 20:00-02:00 covers both 23:30 the same
    night and 01:30 the following calendar day (the shift stays dated by
    its start day) — this is ordinary bar/restaurant closing-shift math,
    and broke without explicit midnight-wraparound handling."""
    import asyncio
    from routes.staff_management import _is_rostered_now
    from database import db

    async def run():
        staff_id = "overnight-test-staff"
        today = datetime.now(timezone.utc).date()
        await db.roster_shifts.delete_many({"staffId": staff_id})
        await db.roster_shifts.insert_one({
            "id": "SHIFT-OVERNIGHT-TEST", "staffId": staff_id, "staffName": "Overnight Tester",
            "date": today.isoformat(), "startTime": "20:00", "endTime": "02:00",
            "businessId": "biz-default",
        })

        late_night = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc).replace(hour=23, minute=30)
        assert await _is_rostered_now(staff_id, now=late_night, business_id="biz-default") is True

        after_midnight = datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc).replace(hour=1, minute=30)
        assert await _is_rostered_now(staff_id, now=after_midnight, business_id="biz-default") is True

        broad_daylight = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc).replace(hour=12, minute=0)
        assert await _is_rostered_now(staff_id, now=broad_daylight, business_id="biz-default") is False

    asyncio.get_event_loop().run_until_complete(run())


def test_pos_session_settings_default_and_owner_only_write(client, owner_headers, anon):
    r = req(client, "GET", "/api/settings/pos-session", headers=owner_headers)
    assert r.status_code == 200
    assert r.json()["timeoutMinutes"] in (0, 2, 5, 10)

    r = req(client, "POST", "/api/settings/pos-session", headers=owner_headers, json={"timeoutMinutes": 5})
    assert r.status_code == 200
    assert r.json()["timeoutMinutes"] == 5

    r2 = req(client, "GET", "/api/settings/pos-session", headers=owner_headers)
    assert r2.json()["timeoutMinutes"] == 5

    bad = req(client, "POST", "/api/settings/pos-session", headers=owner_headers, json={"timeoutMinutes": 3})
    assert bad.status_code == 400

    assert req(anon, "POST", "/api/settings/pos-session", json={"timeoutMinutes": 2}).status_code == 401
