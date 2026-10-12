"""A reservation's client-supplied customerId/tableId used to be accepted
at face value: a foreign or nonexistent reference was either silently
no-opped (the bookkeeping $push/table-status write) or, for tableId on
PUT, never checked at all — either way, the raw id still landed on the
stored reservation (and, for waitlist, the stored waitlist entry) with no
404 ever raised. Launch audit docs/launch-audit-2026-10-11/REPORT.md
flagged this as a review-required gap under routes/reservations.py.
"""
import asyncio
import uuid

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Foreign Ref Test Owner", "email": email, "password": "ForeignRefTenant2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "ForeignRefTenant2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def _reservation_payload(**extra):
    payload = {
        "guestName": "Foreign Ref Guest", "guestPhone": f"+6140{uuid.uuid4().int % 10000000:07d}",
        "partySize": 2, "date": "2027-06-15", "time": "19:00",
    }
    payload.update(extra)
    return payload


def test_create_reservation_rejects_another_businesss_customer_id(client, owner_headers):
    biz_b = "foreign-ref-biz-b"
    headers_b = _login_as(client, owner_headers, email="foreignref-b@nua.com", business_id=biz_b)
    foreign_customer_id = str(uuid.uuid4())
    _run(db.customers.insert_one({"id": foreign_customer_id, "businessId": biz_b, "name": "B's customer"}))
    try:
        r = req(client, "POST", "/api/reservations", headers=owner_headers,
                json=_reservation_payload(customerId=foreign_customer_id))
        assert r.status_code == 404, r.text[:200]
        assert db.reservations is not None
        leaked = _run(db.reservations.find_one({"customerId": foreign_customer_id}))
        assert leaked is None, "no reservation should have been stored with the foreign customerId"
    finally:
        _run(db.customers.delete_many({"id": foreign_customer_id}))
        _run(db.reservations.delete_many({"customerId": foreign_customer_id}))


def test_create_reservation_rejects_nonexistent_customer_id(client, owner_headers):
    r = req(client, "POST", "/api/reservations", headers=owner_headers,
            json=_reservation_payload(customerId=str(uuid.uuid4())))
    assert r.status_code == 404, r.text[:200]


def test_create_reservation_rejects_another_businesss_table_id(client, owner_headers):
    biz_b = "foreign-ref-biz-table-b"
    headers_b = _login_as(client, owner_headers, email="foreignref-table-b@nua.com", business_id=biz_b)
    plan_id = str(uuid.uuid4())
    table_id = str(uuid.uuid4())
    _run(db.floor_plans.insert_one({
        "id": plan_id, "businessId": biz_b, "name": "B Plan", "isActive": True,
        "tables": [{"id": table_id, "number": "7", "isActive": True, "status": "available"}],
    }))
    try:
        r = req(client, "POST", "/api/reservations", headers=owner_headers,
                json=_reservation_payload(tableId=table_id))
        assert r.status_code == 404, r.text[:200]
    finally:
        _run(db.floor_plans.delete_many({"id": plan_id}))


def test_create_reservation_accepts_own_table_id(client, owner_headers):
    plan_id = str(uuid.uuid4())
    table_id = str(uuid.uuid4())
    _run(db.floor_plans.insert_one({
        "id": plan_id, "businessId": "default", "name": "Own Plan", "isActive": True,
        "tables": [{"id": table_id, "number": "9", "isActive": True, "status": "available"}],
    }))
    try:
        r = req(client, "POST", "/api/reservations", headers=owner_headers,
                json=_reservation_payload(tableId=table_id))
        assert r.status_code == 200, r.text[:200]
        assert r.json()["tableId"] == table_id
    finally:
        _run(db.floor_plans.delete_many({"id": plan_id}))
        _run(db.reservations.delete_many({"tableId": table_id}))


def test_update_reservation_rejects_another_businesss_table_id(client, owner_headers):
    created = req(client, "POST", "/api/reservations", headers=owner_headers, json=_reservation_payload())
    assert created.status_code == 200, created.text[:200]
    reservation_id = created.json()["id"]

    biz_b = "foreign-ref-biz-update-b"
    headers_b = _login_as(client, owner_headers, email="foreignref-update-b@nua.com", business_id=biz_b)
    plan_id = str(uuid.uuid4())
    table_id = str(uuid.uuid4())
    _run(db.floor_plans.insert_one({
        "id": plan_id, "businessId": biz_b, "name": "B Plan 2", "isActive": True,
        "tables": [{"id": table_id, "number": "11", "isActive": True, "status": "available"}],
    }))
    try:
        r = req(client, "PUT", f"/api/reservations/{reservation_id}", headers=owner_headers,
                json={"tableId": table_id})
        assert r.status_code == 404, r.text[:200]
        unchanged = _run(db.reservations.find_one({"id": reservation_id}, {"_id": 0, "tableId": 1}))
        assert unchanged.get("tableId") != table_id
    finally:
        _run(db.floor_plans.delete_many({"id": plan_id}))
        _run(db.reservations.delete_many({"id": reservation_id}))


def test_update_waitlist_entry_rejects_another_businesss_table_id(client, owner_headers):
    entry = req(client, "POST", "/api/waitlist", headers=owner_headers, json={
        "guestName": "Waitlist Guest", "partySize": 2,
    })
    assert entry.status_code == 200, entry.text[:200]
    entry_id = entry.json()["id"]

    biz_b = "foreign-ref-waitlist-biz-b"
    headers_b = _login_as(client, owner_headers, email="foreignref-waitlist-b@nua.com", business_id=biz_b)
    plan_id = str(uuid.uuid4())
    table_id = str(uuid.uuid4())
    _run(db.floor_plans.insert_one({
        "id": plan_id, "businessId": biz_b, "name": "B Plan 3", "isActive": True,
        "tables": [{"id": table_id, "number": "13", "isActive": True, "status": "available"}],
    }))
    try:
        r = req(client, "PUT", f"/api/waitlist/{entry_id}", headers=owner_headers, json={"tableId": table_id})
        assert r.status_code == 404, r.text[:200]
    finally:
        _run(db.floor_plans.delete_many({"id": plan_id}))
        _run(db.waitlist.delete_many({"id": entry_id}))
