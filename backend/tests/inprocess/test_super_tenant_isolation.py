"""routes/super.py's Superannuation Guarantee ledger (db.super_weekly_runs
— real staff wages, OTE, and super contribution amounts) had zero
businessId scoping: any business could list another business's committed
super runs, mark them paid/reversed (corrupting statutory compliance
records), and the BAS-line / yearly-summary aggregates mixed every
business's superannuation totals into one figure.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Super Test Owner", "email": email, "password": "SuperTenantTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "SuperTenantTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def _run_payload():
    return {
        "payPeriodStart": "2026-01-01", "payPeriodEnd": "2026-01-07", "payDate": "2026-01-08",
        "staff": [{"name": "Secret Staffer", "grossPay": 5000000.0}],
    }


def test_super_weekly_runs_are_scoped_and_owned_per_business(client, owner_headers):
    other = _login_as(client, owner_headers, email="super.runs.other@nua.com", business_id="super-runs-other-biz")

    created = req(client, "POST", "/api/super/weekly-runs", headers=other, json=_run_payload())
    assert created.status_code == 200, created.text[:200]
    run_id = created.json()["id"]
    try:
        mine = req(client, "GET", "/api/super/weekly-runs", headers=owner_headers).json()
        assert not any(r["id"] == run_id for r in mine)

        mark_mine = req(client, "PATCH", f"/api/super/weekly-runs/{run_id}", headers=owner_headers,
                         json={"status": "paid"})
        assert mark_mine.status_code == 404

        theirs = req(client, "GET", "/api/super/weekly-runs", headers=other).json()
        found = next(r for r in theirs if r["id"] == run_id)
        assert found["status"] == "unpaid", "a cross-tenant mark-paid attempt must not have mutated it"
    finally:
        _run(db.super_weekly_runs.delete_one({"id": run_id}))


def test_bas_line_and_yearly_summary_exclude_another_businesss_super_runs(client, owner_headers):
    other = _login_as(client, owner_headers, email="super.bas.other@nua.com", business_id="super-bas-other-biz")

    created = req(client, "POST", "/api/super/weekly-runs", headers=other, json=_run_payload())
    assert created.status_code == 200, created.text[:200]
    run_id = created.json()["id"]
    huge_total = created.json()["totalSuper"]
    try:
        bas = req(client, "GET", "/api/super/bas-line", headers=owner_headers,
                  params={"quarterStart": "2026-01-01", "quarterEnd": "2026-03-31"}).json()
        assert bas["totalSuper"] < huge_total, "another business's huge super run must not inflate this business's BAS line"

        summary = req(client, "GET", "/api/super/summary", headers=owner_headers, params={"fy": "2025-2026"}).json()
        assert summary["totalSuper"] < huge_total
    finally:
        _run(db.super_weekly_runs.delete_one({"id": run_id}))
