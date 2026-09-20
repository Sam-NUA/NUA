"""routes/loyalty_engine.py's reports (liability, locked-accounts,
fraud-flags, and the new ROI report) had zero businessId scoping — every
business's outstanding points liability, locked accounts, and fraud
signals were mixed into one report, and resolve_fraud_flag/unlock had no
ownership check at all. Also, loyalty_ledger entries themselves were
never stamped with businessId at any real write site (routes/
transactions.py's checkout-time earn/redeem, services/sale_recorder.py,
the Square connector) — fixed at the root by stamping businessId on every
insert, which is what makes scoping the reports actually effective rather
than a no-op against untagged data.

This file covers the tenant-isolation fixes plus the new GET
/loyalty/reports/roi (redemption cost vs incremental member spend).
"""
import asyncio
import uuid
from datetime import datetime, timezone

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Loyalty Engine Test Owner", "email": email, "password": "LoyaltyEngineTenant2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "LoyaltyEngineTenant2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def _make_customer(business_id, **extra):
    doc = {
        "id": str(uuid.uuid4()), "name": "Report Test Guest", "email": f"{uuid.uuid4().hex[:8]}@test.com",
        "phone": f"+61400{uuid.uuid4().int % 1000000:06d}", "points": 0, "totalSpent": 0.0,
        "visits": 0, "membershipTier": "Bronze", "businessId": business_id,
    }
    doc.update(extra)
    _run(db.customers.insert_one(dict(doc)))
    return doc


def test_liability_and_locked_reports_exclude_another_businesss_customers(client, owner_headers):
    other = _login_as(client, owner_headers, email="lengine.liability.other@nua.com", business_id="lengine-liability-biz")
    cust = _make_customer("lengine-liability-biz", points=777, loyaltyLocked=True)
    try:
        mine_liability = req(client, "GET", "/api/loyalty/reports/liability", headers=owner_headers).json()
        assert not any(h["customerId"] == cust["id"] for h in mine_liability["topHolders"])

        own_liability = req(client, "GET", "/api/loyalty/reports/liability", headers=other).json()
        assert any(h["customerId"] == cust["id"] for h in own_liability["topHolders"])

        mine_locked = req(client, "GET", "/api/loyalty/reports/locked-accounts", headers=owner_headers).json()
        assert not any(a["id"] == cust["id"] for a in mine_locked["accounts"])

        own_locked = req(client, "GET", "/api/loyalty/reports/locked-accounts", headers=other).json()
        assert any(a["id"] == cust["id"] for a in own_locked["accounts"])
    finally:
        _run(db.customers.delete_one({"id": cust["id"]}))


def test_unlock_requires_ownership(client, owner_headers):
    other = _login_as(client, owner_headers, email="lengine.unlock.other@nua.com", business_id="lengine-unlock-biz")
    cust = _make_customer("lengine-unlock-biz", loyaltyLocked=True)
    try:
        cross = req(client, "POST", f"/api/loyalty/customers/{cust['id']}/unlock", headers=owner_headers)
        assert cross.status_code == 404

        still_locked = _run(db.customers.find_one({"id": cust["id"]}, {"_id": 0, "loyaltyLocked": 1}))
        assert still_locked["loyaltyLocked"] is True

        own = req(client, "POST", f"/api/loyalty/customers/{cust['id']}/unlock", headers=other)
        assert own.status_code == 200, own.text[:200]
    finally:
        _run(db.customers.delete_one({"id": cust["id"]}))


def test_fraud_flags_are_scoped_and_owned_per_business(client, owner_headers):
    other = _login_as(client, owner_headers, email="lengine.fraud.other@nua.com", business_id="lengine-fraud-biz")
    cust = _make_customer("lengine-fraud-biz")
    now = datetime.now(timezone.utc).isoformat()
    entries = [{
        "id": f"LP-{uuid.uuid4().hex[:8].upper()}", "customerId": cust["id"], "transactionId": None,
        "type": "earn", "points": 10, "businessId": "lengine-fraud-biz", "createdAt": now,
    } for _ in range(5)]
    try:
        _run(db.loyalty_ledger.insert_many(entries))

        mine = req(client, "GET", "/api/loyalty/reports/fraud-flags", headers=owner_headers,
                   params={"status": "all"}).json()
        assert not any(f.get("customerId") == cust["id"] for f in mine["flags"])

        own = req(client, "GET", "/api/loyalty/reports/fraud-flags", headers=other,
                  params={"status": "all"}).json()
        matching = [f for f in own["flags"] if f.get("customerId") == cust["id"]]
        assert len(matching) == 1, f"expected exactly one point_farming flag, got {own['flags']}"
        flag_id = matching[0]["id"]

        cross_resolve = req(client, "PUT", f"/api/loyalty/reports/fraud-flags/{flag_id}", headers=owner_headers,
                             json={"status": "reviewed_ok"})
        assert cross_resolve.status_code == 404

        own_resolve = req(client, "PUT", f"/api/loyalty/reports/fraud-flags/{flag_id}", headers=other,
                          json={"status": "reviewed_ok"})
        assert own_resolve.status_code == 200, own_resolve.text[:200]
    finally:
        _run(db.customers.delete_one({"id": cust["id"]}))
        _run(db.loyalty_ledger.delete_many({"customerId": cust["id"]}))
        _run(db.loyalty_fraud_flags.delete_many({"customerId": cust["id"]}))


def test_roi_report_computes_cost_and_engagement_scoped_to_one_business(client, owner_headers):
    biz = "lengine-roi-biz"
    other_biz = "lengine-roi-other-biz"
    staff = _login_as(client, owner_headers, email="lengine.roi@nua.com", business_id=biz)
    other_staff = _login_as(client, owner_headers, email="lengine.roi.other@nua.com", business_id=other_biz)

    # Baseline first — the shared test DB may already carry some untagged
    # legacy loyalty_ledger/customers rows that tenant_scope_filter's safe
    # default correctly still surfaces to every business; asserting on a
    # DELTA rather than an absolute total keeps this test correct
    # regardless of that pre-existing, shared-DB noise level.
    base = req(client, "GET", "/api/loyalty/reports/roi", headers=staff).json()

    engaged = _make_customer(biz, totalSpent=100.0, visits=4)
    never_engaged = _make_customer(biz, totalSpent=20.0, visits=1)
    # A wildly distinctive value on a DIFFERENT business — if this leaks
    # into `biz`'s report the delta assertion below fails loudly instead
    # of silently passing.
    other_cust = _make_customer(other_biz, totalSpent=999999.0, visits=1)
    try:
        _run(db.loyalty_ledger.insert_one({
            "id": f"LP-{uuid.uuid4().hex[:8].upper()}", "customerId": engaged["id"], "transactionId": None,
            "type": "redeem", "points": -500, "value": 5.00, "businessId": biz,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }))
        _run(db.loyalty_ledger.insert_one({
            "id": f"LP-{uuid.uuid4().hex[:8].upper()}", "customerId": other_cust["id"], "transactionId": None,
            "type": "redeem", "points": -1, "value": 777777.77, "businessId": other_biz,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }))

        after = req(client, "GET", "/api/loyalty/reports/roi", headers=staff).json()

        assert round(after["programCost"] - base["programCost"], 2) == 5.00, (
            "must only count this business's own redemption, not the other business's 777777.77 entry")
        assert after["engagedCustomers"] - base["engagedCustomers"] == 1
        assert after["neverEngagedCustomers"] - base["neverEngagedCustomers"] == 1
        assert after["redemptionCount"] - base["redemptionCount"] == 1

        other_report = req(client, "GET", "/api/loyalty/reports/roi", headers=other_staff).json()
        assert other_report["programCost"] >= 777777.77
    finally:
        _run(db.customers.delete_many({"businessId": {"$in": [biz, other_biz]}}))
        _run(db.loyalty_ledger.delete_many({"businessId": {"$in": [biz, other_biz]}}))


def test_reports_require_owner_or_manager(client, owner_headers):
    req(client, "POST", "/api/auth/staff/add", headers=owner_headers, json={
        "name": "Loyalty Engine Cashier", "email": "lengine.cashier@nua.com",
        "password": "CashierPass1!", "role": "cashier"})
    tok = req(client, "POST", "/api/auth/login", json={
        "email": "lengine.cashier@nua.com", "password": "CashierPass1!"}).json()
    client.cookies.clear()
    cashier_headers = {"Authorization": f"Bearer {tok['token']}"}

    assert req(client, "GET", "/api/loyalty/reports/roi", headers=cashier_headers).status_code == 403
    assert req(client, "GET", "/api/loyalty/reports/liability", headers=cashier_headers).status_code == 403
