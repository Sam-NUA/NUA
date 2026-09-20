"""Reliability pass: routes/reservations.py's status-changing endpoints
(no-show, cancel, approve, reject, restore, plus create_reservation's
override/large-booking audit calls) write an audit-log entry AFTER the
real state change already succeeded. Before this, that write was
unguarded — a transient Mongo hiccup on the audit_log insert would 500
the whole request even though the reservation's status had already
changed for real, misleading the caller into thinking the action failed.
Now wrapped with utils.errors.log_and_continue, the same "best-effort,
never block the real mutation" pattern already used elsewhere in this
codebase for audit/notification writes.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _create_reservation(client, headers, **extra):
    payload = {
        "guestName": "Audit Resilience Guest", "guestPhone": "+61400555666",
        "partySize": 2, "date": "2027-06-15", "time": "19:00",
    }
    payload.update(extra)
    r = req(client, "POST", "/api/reservations", headers=headers, json=payload)
    assert r.status_code == 200, r.text[:200]
    return r.json()


def test_a_failing_audit_log_write_does_not_undo_or_fail_the_cancellation(client, owner_headers, monkeypatch):
    async def broken_log_event(*args, **kwargs):
        raise RuntimeError("simulated audit_log write failure")

    from services import audit_service
    monkeypatch.setattr(audit_service, "log_event", broken_log_event)

    res = _create_reservation(client, owner_headers)
    try:
        r = req(client, "POST", f"/api/reservations/{res['id']}/cancel", headers=owner_headers, json={})
        assert r.status_code == 200, (
            "a broken audit-log write must never fail a cancellation that already succeeded: " + r.text[:200])
        assert r.json()["status"] == "cancelled"
        stored = _run(db.reservations.find_one({"id": res["id"]}, {"_id": 0}))
        assert stored["status"] == "cancelled"
    finally:
        _run(db.reservations.delete_one({"id": res["id"]}))


def test_a_failing_audit_log_write_does_not_undo_or_fail_a_no_show(client, owner_headers, monkeypatch):
    async def broken_log_event(*args, **kwargs):
        raise RuntimeError("simulated audit_log write failure")

    from services import audit_service
    monkeypatch.setattr(audit_service, "log_event", broken_log_event)

    res = _create_reservation(client, owner_headers)
    try:
        r = req(client, "POST", f"/api/reservations/{res['id']}/no-show", headers=owner_headers, json={})
        assert r.status_code == 200, (
            "a broken audit-log write must never fail a no-show mark that already succeeded: " + r.text[:200])
        stored = _run(db.reservations.find_one({"id": res["id"]}, {"_id": 0}))
        assert stored["status"] == "no_show"
    finally:
        _run(db.reservations.delete_one({"id": res["id"]}))
