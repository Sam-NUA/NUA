"""The floor plan's table-course live state used to have no notion of which
guest was seated, and an "overdue" course always overrode the fill colour
(losing which course a late table was actually in). Both were fixed:
customerId can now be attached when seating, isVip is resolved from it and
returned per state, and `colour` always reflects the pure course colour
while `overdue` is reported separately — plus a maxMinutes=0 threshold
("overdue the instant this course starts") now actually works, instead of
being silently unreachable because of a `0 and ...` truthiness bug."""
import uuid
from datetime import datetime, timedelta, timezone

from conftest import req


def _insert_customer(is_vip):
    from database import db
    import asyncio

    cid = str(uuid.uuid4())

    async def run():
        await db.customers.insert_one({
            "id": cid, "businessId": "default", "name": "ZZZ Table Course Guest", "email": f"{cid}@example.com",
            "phone": "0400000000", "isVip": is_vip,
        })
    asyncio.get_event_loop().run_until_complete(run())
    return cid


def test_seating_with_a_vip_guest_flags_the_live_state_isvip(client, owner_headers):
    vip_id = _insert_customer(True)
    r = req(client, "POST", "/api/table-courses/states", headers=owner_headers, json={
        "tableId": "ZZZ-TBL-VIP", "course": "seated", "customerId": vip_id, "guestName": "VIP Guest",
    })
    assert r.status_code == 200, r.text

    r2 = req(client, "GET", "/api/table-courses/states", headers=owner_headers)
    state = next(s for s in r2.json()["states"] if s["tableId"] == "ZZZ-TBL-VIP")
    assert state["isVip"] is True


def test_seating_with_a_non_vip_guest_does_not_flag_isvip(client, owner_headers):
    reg_id = _insert_customer(False)
    req(client, "POST", "/api/table-courses/states", headers=owner_headers, json={
        "tableId": "ZZZ-TBL-REG", "course": "seated", "customerId": reg_id, "guestName": "Regular Guest",
    })
    r = req(client, "GET", "/api/table-courses/states", headers=owner_headers)
    state = next(s for s in r.json()["states"] if s["tableId"] == "ZZZ-TBL-REG")
    assert state["isVip"] is False


def test_seating_with_no_guest_attached_is_not_vip(client, owner_headers):
    req(client, "POST", "/api/table-courses/states", headers=owner_headers, json={
        "tableId": "ZZZ-TBL-WALKIN", "course": "seated",
    })
    r = req(client, "GET", "/api/table-courses/states", headers=owner_headers)
    state = next(s for s in r.json()["states"] if s["tableId"] == "ZZZ-TBL-WALKIN")
    assert state["isVip"] is False


def test_overdue_table_keeps_its_course_colour_instead_of_being_overridden(client, owner_headers):
    """Regression: `colour` used to be swapped for the overdue colour once a
    table went overdue, which lost the "which course is it stuck in"
    information the floor plan is built around. It should now always be the
    course's own colour, with `overdue` reported as its own boolean."""
    settings = req(client, "GET", "/api/table-courses/settings", headers=owner_headers).json()
    for c in settings["courses"]:
        if c["key"] == "seated":
            c["maxMinutes"] = 0
    req(client, "PUT", "/api/table-courses/settings", headers=owner_headers, json=settings)

    req(client, "POST", "/api/table-courses/states", headers=owner_headers, json={
        "tableId": "ZZZ-TBL-OVERDUE", "course": "seated",
    })

    from database import db
    import asyncio

    async def backdate():
        past = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        await db.table_states.update_one(
            {"tableId": "ZZZ-TBL-OVERDUE"},
            {"$set": {"seatedAt": past, "courseStartedAt": past}},
        )
    asyncio.get_event_loop().run_until_complete(backdate())

    r = req(client, "GET", "/api/table-courses/states", headers=owner_headers)
    body = r.json()
    state = next(s for s in body["states"] if s["tableId"] == "ZZZ-TBL-OVERDUE")
    seated_course = next(c for c in body["courses"] if c["key"] == "seated")
    assert state["overdue"] is True
    assert state["colour"] == seated_course["colour"]
    assert state["colour"] != body["overdueColour"]
