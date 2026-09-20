"""table_states was keyed only by tableId, with no businessId at all — two
businesses on a shared deployment both seating "Table 5" collided on one
document, meaning one business's live floor-plan state (course progress,
guest name, VIP flag) could be silently overwritten by another business
seating a same-numbered table. dock_notifications (the "Send" nudge log)
had the same gap.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Table Courses Test Owner", "email": email, "password": "TableCoursesTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "TableCoursesTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def test_two_businesses_seating_the_same_table_number_do_not_collide(client, owner_headers):
    other = _login_as(client, owner_headers, email="tablecourses.other@nua.com", business_id="tablecourses-other-biz")
    try:
        seated_a = req(client, "POST", "/api/table-courses/states", headers=owner_headers, json={
            "tableId": "SHARED-TABLE-7", "course": "drinks", "guestName": "Business A Guest"})
        assert seated_a.status_code == 200, seated_a.text[:200]

        seated_b = req(client, "POST", "/api/table-courses/states", headers=other, json={
            "tableId": "SHARED-TABLE-7", "course": "main", "guestName": "Business B Guest"})
        assert seated_b.status_code == 200, seated_b.text[:200]

        states_a = req(client, "GET", "/api/table-courses/states", headers=owner_headers).json()
        row_a = next(s for s in states_a["states"] if s["tableId"] == "SHARED-TABLE-7")
        assert row_a["guestName"] == "Business A Guest", (
            "business B seating the same table number must not overwrite business A's live state"
        )

        states_b = req(client, "GET", "/api/table-courses/states", headers=other).json()
        row_b = next(s for s in states_b["states"] if s["tableId"] == "SHARED-TABLE-7")
        assert row_b["guestName"] == "Business B Guest"

        # Clearing business A's table must not clear business B's.
        req(client, "POST", "/api/table-courses/states", headers=owner_headers,
            json={"tableId": "SHARED-TABLE-7", "clearState": True})
        states_b_after = req(client, "GET", "/api/table-courses/states", headers=other).json()
        assert any(s["tableId"] == "SHARED-TABLE-7" for s in states_b_after["states"]), (
            "business A clearing its own table must not clear business B's same-numbered table"
        )
    finally:
        _run(db.table_states.delete_many({"tableId": "SHARED-TABLE-7"}))


def test_a_nudge_notification_is_not_visible_to_a_different_business(client, owner_headers):
    other = _login_as(client, owner_headers, email="tablecourses.nudge.other@nua.com", business_id="tablecourses-nudge-biz")

    sent = req(client, "POST", "/api/table-courses/send", headers=other, json={
        "tableId": "NUDGE-TABLE-1", "message": "Other business nudge"})
    assert sent.status_code == 200, sent.text[:200]
    notif_id = sent.json()["id"]
    try:
        owner_notifs = req(client, "GET", "/api/table-courses/notifications", headers=owner_headers).json()
        assert notif_id not in {n["id"] for n in owner_notifs}

        mark_read = req(client, "POST", f"/api/table-courses/notifications/{notif_id}/read", headers=owner_headers)
        assert mark_read.status_code == 404, mark_read.text[:200]
    finally:
        _run(db.dock_notifications.delete_one({"id": notif_id}))
