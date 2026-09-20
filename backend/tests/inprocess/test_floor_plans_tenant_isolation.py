"""routes/reservations.py's floor-plans CRUD section (GET/POST/PUT/DELETE
/floor-plans, /floor-plans/tables/{id}/status, /floor-plans/sections/
{id}/assign) had no auth dependency at all on most of these endpoints, and
no businessId scoping anywhere. A floor plan is a real operational asset
(table layout, sections, server assignments) — this router isn't behind
server.py's public-prefix allowlist, so the global middleware already
required a valid token, but nothing beyond that: any staff member of any
role or business could create, view, modify, or delete any other
business's entire floor plan.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Floor Plans Test Owner", "email": email, "password": "FloorPlansTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "FloorPlansTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def test_floor_plan_crud_requires_a_role_appropriate_credential(client, owner_headers):
    cashier_email = "floorplans.cashier@nua.com"
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Floor Plans Cashier", "email": cashier_email, "password": "FloorPlansCashier2026!"})
    r = client.post("/api/auth/login", json={"email": cashier_email, "password": "FloorPlansCashier2026!"})
    cashier = {"Authorization": f"Bearer {r.json()['token']}"}
    client.cookies.clear()

    denied = req(client, "POST", "/api/floor-plans", headers=cashier, json={"name": "Cashier Attempt"})
    assert denied.status_code == 403, denied.text[:200]


def test_a_different_businesss_floor_plan_is_not_visible_or_editable(client, owner_headers):
    other = _login_as(client, owner_headers, email="floorplans.other@nua.com", business_id="floorplans-other-biz")

    created = req(client, "POST", "/api/floor-plans", headers=other, json={
        "name": "Other Business Floor",
        "tables": [{"number": "1", "capacity": 4}],
        "sections": [{"name": "Main"}],
    })
    assert created.status_code == 200, created.text[:200]
    plan_id = created.json()["id"]
    try:
        listed = req(client, "GET", "/api/floor-plans", headers=owner_headers).json()
        assert plan_id not in {p["id"] for p in listed}

        direct = req(client, "GET", f"/api/floor-plans/{plan_id}", headers=owner_headers)
        assert direct.status_code == 404, direct.text[:200]

        edit = req(client, "PUT", f"/api/floor-plans/{plan_id}", headers=owner_headers, json={"name": "Hijacked"})
        assert edit.status_code == 404, edit.text[:200]

        delete = req(client, "DELETE", f"/api/floor-plans/{plan_id}", headers=owner_headers)
        assert delete.status_code == 404, delete.text[:200]

        # The plan must still exist, untouched, for its real owner.
        still_there = req(client, "GET", f"/api/floor-plans/{plan_id}", headers=other)
        assert still_there.status_code == 200
        assert still_there.json()["name"] == "Other Business Floor"
    finally:
        _run(db.floor_plans.delete_one({"id": plan_id}))
