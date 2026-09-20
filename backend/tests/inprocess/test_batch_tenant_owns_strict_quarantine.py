"""Tenant-ownership release-closure pass, task #66: a representative
sample of the ~30 files whose write/delete tenant_owns() checks were
converted to tenant_owns_strict() in one batch, each after confirming
(individually, per file — see this commit's own message for the specific
reasoning per collection, and the ones deliberately left fail-open:
routes/coursing.py + services/ticket_lifecycle.py for kitchen_orders,
routes/phase_ef.py for purchase_orders, and every "customers"-collection
site across 9 files) that the collection has no currently-active
untagged-creation path.

This file is not exhaustive — the full existing tenant-isolation suite
for every converted file already re-ran clean (772/772) after the batch,
which is the primary evidence the conversion didn't break real
workflows. These tests add the one case that suite didn't already cover:
an untagged (businessId=None) document must be quarantined — refused on
every mutation, never auto-owned by whichever business asks first, never
deleted as a side effect of the refusal.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_rules_engine_mutations_refuse_a_doc_with_no_businessId(client, owner_headers):
    untagged_id = "RULE-QUARANTINE-1"
    _run(db.rules.insert_one({"id": untagged_id, "name": "Untagged Rule", "active": True, "businessId": None}))
    try:
        upd = req(client, "PATCH", f"/api/rules/{untagged_id}", headers=owner_headers, json={"name": "Hijacked"})
        assert upd.status_code == 404, upd.text[:200]
        toggle = req(client, "POST", f"/api/rules/{untagged_id}/toggle", headers=owner_headers)
        assert toggle.status_code == 404, toggle.text[:200]
        deL = req(client, "DELETE", f"/api/rules/{untagged_id}", headers=owner_headers)
        assert deL.status_code == 404, deL.text[:200]
        still_there = _run(db.rules.find_one({"id": untagged_id}))
        assert still_there is not None and still_there["name"] == "Untagged Rule"
    finally:
        _run(db.rules.delete_many({"id": untagged_id}))


def test_temperature_device_mutations_refuse_a_doc_with_no_businessId(client, owner_headers):
    untagged_id = "TEMPDEV-QUARANTINE-1"
    _run(db.temperature_devices.insert_one({
        "id": untagged_id, "name": "Untagged Fridge", "unitType": "fridge",
        "minC": 0, "maxC": 5, "active": True, "businessId": None,
    }))
    try:
        upd = req(client, "PATCH", f"/api/temperature/devices/{untagged_id}", headers=owner_headers,
                   json={"name": "Hijacked"})
        assert upd.status_code == 404, upd.text[:200]
        deL = req(client, "DELETE", f"/api/temperature/devices/{untagged_id}", headers=owner_headers)
        assert deL.status_code == 404, deL.text[:200]
        still_there = _run(db.temperature_devices.find_one({"id": untagged_id}))
        assert still_there is not None and still_there["name"] == "Untagged Fridge"
    finally:
        _run(db.temperature_devices.delete_many({"id": untagged_id}))


def test_stock_transfer_mutations_refuse_a_doc_with_no_businessId(client, owner_headers):
    untagged_id = "XFER-QUARANTINE-1"
    _run(db.stock_transfers.insert_one({
        "id": untagged_id, "fromLocation": "Main", "toLocation": "Kiosk",
        "status": "pending", "items": [], "businessId": None,
    }))
    try:
        receive = req(client, "POST", f"/api/stock-transfers/{untagged_id}/receive", headers=owner_headers)
        assert receive.status_code == 404, receive.text[:200]
        cancel = req(client, "POST", f"/api/stock-transfers/{untagged_id}/cancel", headers=owner_headers)
        assert cancel.status_code == 404, cancel.text[:200]
        still_there = _run(db.stock_transfers.find_one({"id": untagged_id}))
        assert still_there is not None and still_there["status"] == "pending"
    finally:
        _run(db.stock_transfers.delete_many({"id": untagged_id}))


def test_approval_actions_refuse_a_doc_with_no_businessId(client, owner_headers):
    untagged_id = "APPR-QUARANTINE-1"
    _run(db.approvals.insert_one({
        "id": untagged_id, "actionType": "test_action", "status": "pending", "businessId": None,
    }))
    try:
        appr = req(client, "POST", f"/api/approvals/{untagged_id}/approve", headers=owner_headers)
        assert appr.status_code == 404, appr.text[:200]
        rej = req(client, "POST", f"/api/approvals/{untagged_id}/reject", headers=owner_headers, json={})
        assert rej.status_code == 404, rej.text[:200]
        still_there = _run(db.approvals.find_one({"id": untagged_id}))
        assert still_there is not None and still_there["status"] == "pending"
    finally:
        _run(db.approvals.delete_many({"id": untagged_id}))


def test_customer_segment_mutations_refuse_a_doc_with_no_businessId(client, owner_headers):
    untagged_id = "SEG-QUARANTINE-1"
    _run(db.customer_segments.insert_one({
        "id": untagged_id, "name": "Untagged Segment", "rules": {}, "businessId": None,
    }))
    try:
        upd = req(client, "PUT", f"/api/marketing/segments/{untagged_id}", headers=owner_headers,
                   json={"name": "Hijacked"})
        assert upd.status_code == 404, upd.text[:200]
        still_there = _run(db.customer_segments.find_one({"id": untagged_id}))
        assert still_there is not None and still_there["name"] == "Untagged Segment"
    finally:
        _run(db.customer_segments.delete_many({"id": untagged_id}))


def test_appointment_mutations_refuse_a_doc_with_no_businessId(client, owner_headers):
    untagged_id = "APPT-QUARANTINE-1"
    _run(db.appointments.insert_one({
        "id": untagged_id, "customerName": "Untagged Guest", "serviceId": "svc-1",
        "date": "2027-06-15", "time": "10:00", "status": "confirmed", "businessId": None,
    }))
    try:
        upd = req(client, "PUT", f"/api/appointments/{untagged_id}", headers=owner_headers,
                   json={"status": "cancelled"})
        assert upd.status_code == 404, upd.text[:200]
        complete = req(client, "POST", f"/api/appointments/{untagged_id}/complete", headers=owner_headers)
        assert complete.status_code == 404, complete.text[:200]
        still_there = _run(db.appointments.find_one({"id": untagged_id}))
        assert still_there is not None and still_there["status"] == "confirmed"
    finally:
        _run(db.appointments.delete_many({"id": untagged_id}))
