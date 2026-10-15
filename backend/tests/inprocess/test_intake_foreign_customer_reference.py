"""create_intake_note accepted a client-supplied customerId at face value
and stamped it straight onto the stored note alongside the staff member's
own businessId -- no check that the referenced customer actually belongs
to that business. A staff member at business A could link an intake note
to business B's customer by supplying B's customerId directly (same class
of bug reservations.py's create_reservation already guards against for
its own customerId field; see test_reservation_foreign_references.py).
"""
import asyncio
import uuid

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_create_intake_note_rejects_another_businesss_customer_id(client, owner_headers):
    foreign_business_id = f"intake-foreign-biz-{uuid.uuid4().hex[:8]}"
    foreign_customer_id = str(uuid.uuid4())
    _run(db.customers.insert_one(
        {"id": foreign_customer_id, "businessId": foreign_business_id, "name": "B's customer"}))
    try:
        r = req(client, "POST", "/api/client-intake", headers=owner_headers, json={
            "customerName": "Foreign Ref Guest", "customerId": foreign_customer_id,
        })
        assert r.status_code == 404, r.text[:200]
        leaked = _run(db.client_intake.find_one({"customerId": foreign_customer_id}))
        assert leaked is None, "no intake note should have been stored with the foreign customerId"
    finally:
        _run(db.customers.delete_many({"id": foreign_customer_id}))
        _run(db.client_intake.delete_many({"customerId": foreign_customer_id}))


def test_create_intake_note_rejects_nonexistent_customer_id(client, owner_headers):
    r = req(client, "POST", "/api/client-intake", headers=owner_headers, json={
        "customerName": "Foreign Ref Guest", "customerId": str(uuid.uuid4()),
    })
    assert r.status_code == 404, r.text[:200]


def test_create_intake_note_still_works_without_a_customer_id(client, owner_headers):
    r = req(client, "POST", "/api/client-intake", headers=owner_headers, json={
        "customerName": "Walk-in Guest",
    })
    assert r.status_code == 200, r.text[:200]
    note_id = r.json()["id"]
    _run(db.client_intake.delete_many({"id": note_id}))
