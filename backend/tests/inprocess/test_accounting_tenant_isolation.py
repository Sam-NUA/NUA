"""services/accounting_service.py + routes/accounting.py — the entire
double-entry general-ledger system (chart of accounts, journal postings,
P&L/balance-sheet/cash-flow/trial-balance/general-ledger reports, AP bills,
AR invoices, customer deposits, bank reconciliation, budgets) had zero
businessId scoping anywhere. Every business's real financial data was
computed from every business's transactions on a shared deployment.

This was escalated during the wider tenant-isolation audit as the single
highest-priority follow-up (bigger in scope than any single file fixed in
that audit) and is fixed here as its own dedicated pass.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Accounting Test Owner", "email": email, "password": "AcctTenantTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "AcctTenantTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def test_chart_of_accounts_seeds_and_is_scoped_independently_per_business(client, owner_headers):
    other = _login_as(client, owner_headers, email="acct.coa.other@nua.com", business_id="acct-coa-other-biz")

    seed_mine = req(client, "POST", "/api/accounting/seed", headers=owner_headers)
    assert seed_mine.status_code == 200, seed_mine.text[:200]
    seed_other = req(client, "POST", "/api/accounting/seed", headers=other)
    assert seed_other.status_code == 200, seed_other.text[:200]
    # Both businesses must be able to seed the SAME code set independently —
    # before the fix, the second business's seed would see every code as
    # "already existing" (queried with no businessId filter) and seed nothing.
    assert seed_other.json()["seeded"] > 0, "second business must get its own full chart of accounts"

    my_accounts = req(client, "GET", "/api/accounting/accounts", headers=owner_headers).json()
    other_accounts = req(client, "GET", "/api/accounting/accounts", headers=other).json()
    my_codes = {a["code"] for a in my_accounts}
    other_codes = {a["code"] for a in other_accounts}
    assert "1000" in my_codes and "1000" in other_codes, "both businesses seed the same code space independently"

    # Renaming my "1000" account must never affect the other business's "1000".
    upd = req(client, "PUT", "/api/accounting/accounts/1000", headers=owner_headers, json={"name": "My Renamed Cash"})
    assert upd.status_code == 200, upd.text[:200]
    other_1000 = next(a for a in req(client, "GET", "/api/accounting/accounts", headers=other).json() if a["code"] == "1000")
    assert other_1000["name"] != "My Renamed Cash"


def test_journal_get_and_reverse_are_owned_per_business(client, owner_headers):
    other = _login_as(client, owner_headers, email="acct.je.other@nua.com", business_id="acct-je-other-biz")
    req(client, "POST", "/api/accounting/seed", headers=other)

    created = req(client, "POST", "/api/accounting/journals", headers=other, json={
        "lines": [
            {"accountCode": "1000", "debit": 500.0, "credit": 0.0, "description": "test"},
            {"accountCode": "4000", "debit": 0.0, "credit": 500.0, "description": "test"},
        ],
        "memo": "Other biz manual entry",
    })
    assert created.status_code == 200, created.text[:200]
    je_id = created.json()["id"]

    cross_get = req(client, "GET", f"/api/accounting/journals/{je_id}", headers=owner_headers)
    assert cross_get.status_code == 404

    cross_reverse = req(client, "POST", f"/api/accounting/journals/{je_id}/reverse", headers=owner_headers, json={})
    assert cross_reverse.status_code == 400, "cross-tenant journal reversal must be rejected"

    own_get = req(client, "GET", f"/api/accounting/journals/{je_id}", headers=other)
    assert own_get.status_code == 200
    assert own_get.json()["businessId"] == "acct-je-other-biz"


def test_a_journal_entry_with_no_businessId_is_quarantined_from_reads_by_anyone(client, owner_headers):
    """get_journal used tenant_owns(), which treats a document with no
    businessId at all as owned by whoever asks — a READ-path fail-open
    gap distinct from (and found after) the mutation-path fixes above:
    an untagged journal entry was readable by any authenticated user on
    any business, not just refused for mutation. Fixed to
    tenant_owns_strict() since journal_entries is tenant-owned financial
    data, not shared reference data, and every creation path
    (create_journal, and services/accounting_service.py's auto-posting)
    always stamps businessId — so a genuinely untagged row can only be
    a stale/legacy record, never a currently-valid shared one."""
    untagged_id = "ACCT-QUARANTINE-JE-1"
    _run(db.journal_entries.insert_one({
        "id": untagged_id, "date": "2099-01-01", "sourceType": "manual",
        "lines": [{"accountCode": "1000", "debit": 1.0, "credit": 0.0}],
        "businessId": None,
    }))
    try:
        cross_get = req(client, "GET", f"/api/accounting/journals/{untagged_id}", headers=owner_headers)
        assert cross_get.status_code == 404, (
            f"an untagged journal entry must be refused for reads by anyone, got {cross_get.status_code}"
        )
    finally:
        _run(db.journal_entries.delete_many({"id": untagged_id}))


def test_reports_exclude_another_businesss_journal_entries(client, owner_headers):
    other = _login_as(client, owner_headers, email="acct.reports.other@nua.com", business_id="acct-reports-other-biz")
    req(client, "POST", "/api/accounting/seed", headers=other)

    huge = req(client, "POST", "/api/accounting/journals", headers=other, json={
        "lines": [
            {"accountCode": "1000", "debit": 9_000_000.0, "credit": 0.0},
            {"accountCode": "4000", "debit": 0.0, "credit": 9_000_000.0},
        ],
        "memo": "Huge other-business revenue",
    })
    assert huge.status_code == 200, huge.text[:200]

    from datetime import date, timedelta
    today = date.today().isoformat()
    year_ago = (date.today() - timedelta(days=365)).isoformat()

    tb = req(client, "GET", "/api/accounting/reports/trial-balance", headers=owner_headers).json()
    assert tb["totalDebit"] < 9_000_000.0

    pnl = req(client, "GET", "/api/accounting/reports/profit-loss", headers=owner_headers,
              params={"from": year_ago, "to": today}).json()
    assert pnl["totalRevenue"] < 9_000_000.0

    bs = req(client, "GET", "/api/accounting/reports/balance-sheet", headers=owner_headers).json()
    assert bs["totalAssets"] < 9_000_000.0

    cf = req(client, "GET", "/api/accounting/reports/cash-flow", headers=owner_headers,
             params={"from": year_ago, "to": today}).json()
    assert abs(cf["netCash"]) < 9_000_000.0

    gl = req(client, "GET", "/api/accounting/reports/general-ledger/1000", headers=owner_headers).json()
    assert not any(r["debit"] == 9_000_000.0 for r in gl["rows"])


def test_ap_bills_are_owned_per_business(client, owner_headers):
    other = _login_as(client, owner_headers, email="acct.bills.other@nua.com", business_id="acct-bills-other-biz")
    req(client, "POST", "/api/accounting/seed", headers=other)

    bill = req(client, "POST", "/api/accounting/bills", headers=other, json={
        "supplierId": "SUP-1", "supplierName": "Acme", "issueDate": "2026-01-01",
        "dueDate": "2026-01-31", "total": 220.0, "gst": 20.0,
    })
    assert bill.status_code == 200, bill.text[:200]
    bid = bill.json()["id"]

    mine_list = req(client, "GET", "/api/accounting/bills", headers=owner_headers).json()
    assert not any(b["id"] == bid for b in mine_list)

    cross_pay = req(client, "POST", f"/api/accounting/bills/{bid}/pay", headers=owner_headers, json={"amount": 220.0})
    assert cross_pay.status_code == 404

    cross_delete = req(client, "DELETE", f"/api/accounting/bills/{bid}", headers=owner_headers)
    assert cross_delete.status_code == 404


def test_ar_invoices_and_customer_deposits_are_owned_per_business(client, owner_headers):
    other = _login_as(client, owner_headers, email="acct.ar.other@nua.com", business_id="acct-ar-other-biz")
    req(client, "POST", "/api/accounting/seed", headers=other)

    inv = req(client, "POST", "/api/accounting/invoices", headers=other, json={
        "customerId": "CUST-1", "customerName": "Big Co", "issueDate": "2026-01-01",
        "dueDate": "2026-01-31", "total": 550.0, "gst": 50.0,
    })
    assert inv.status_code == 200, inv.text[:200]
    iid = inv.json()["id"]

    mine_list = req(client, "GET", "/api/accounting/invoices", headers=owner_headers).json()
    assert not any(i["id"] == iid for i in mine_list)

    cross_receive = req(client, "POST", f"/api/accounting/invoices/{iid}/receive", headers=owner_headers, json={"amount": 550.0})
    assert cross_receive.status_code == 404
    cross_delete = req(client, "DELETE", f"/api/accounting/invoices/{iid}", headers=owner_headers)
    assert cross_delete.status_code == 404

    dep = req(client, "POST", "/api/accounting/deposits", headers=other, json={
        "customerId": "CUST-1", "customerName": "Big Co", "amount": 100.0, "receivedAt": "2026-01-01",
    })
    assert dep.status_code == 200, dep.text[:200]
    did = dep.json()["id"]

    mine_deposits = req(client, "GET", "/api/accounting/deposits", headers=owner_headers).json()
    assert not any(d["id"] == did for d in mine_deposits)

    cross_apply = req(client, "POST", f"/api/accounting/deposits/{did}/apply", headers=owner_headers,
                       json={"transactionId": "TX-1"})
    assert cross_apply.status_code == 404
    cross_refund = req(client, "POST", f"/api/accounting/deposits/{did}/refund", headers=owner_headers)
    assert cross_refund.status_code == 404


def test_budgets_are_owned_per_business(client, owner_headers):
    other = _login_as(client, owner_headers, email="acct.budget.other@nua.com", business_id="acct-budget-other-biz")

    budget = req(client, "POST", "/api/accounting/budgets", headers=other, json={
        "fyStart": "2026-07-01", "fyEnd": "2027-06-30", "name": "Other Biz Budget",
    })
    assert budget.status_code == 200, budget.text[:200]
    bid = budget.json()["id"]

    mine_list = req(client, "GET", "/api/accounting/budgets", headers=owner_headers).json()
    assert not any(b["id"] == bid for b in mine_list)

    cross_update = req(client, "PUT", f"/api/accounting/budgets/{bid}", headers=owner_headers, json={"name": "Hijacked"})
    assert cross_update.status_code == 404
    cross_delete = req(client, "DELETE", f"/api/accounting/budgets/{bid}", headers=owner_headers)
    assert cross_delete.status_code == 404


def test_pos_sale_auto_posts_a_journal_entry_scoped_to_the_selling_business(client, owner_headers):
    req(client, "POST", "/api/accounting/seed", headers=owner_headers)

    sale = req(client, "POST", "/api/transactions", headers=owner_headers, json={
        "items": [{"productId": "no-such-product", "productName": "Test item", "quantity": 1, "price": 25.0}],
        "paymentMethod": "cash", "location": "Test", "cashier": "Tester",
    })
    assert sale.status_code == 200, sale.text[:200]
    txn_id = sale.json()["id"]

    je = _run(db.journal_entries.find_one({"sourceType": "pos_sale", "sourceRef": txn_id}, {"_id": 0}))
    assert je is not None, "a POS sale must auto-post a journal entry"
    assert je["businessId"] == "default", "the auto-posted entry must be stamped with the selling business"


def test_a_bill_with_no_businessId_is_quarantined_from_mutation_by_anyone(client, owner_headers):
    """routes/accounting.py's mutation endpoints (pay_bill, delete_bill, and
    the sibling invoice/deposit/bank-match/budget ones) used tenant_owns(),
    which treats a document with no businessId at all as owned by whoever
    asks — dangerous for a WRITE given this codebase's own documented
    history of untagged rows created by many different businesses before
    tenant stamping existed. Fixed to tenant_owns_strict(): an untagged
    document is refused for a mutation by ANY caller (quarantined) rather
    than auto-assigned to whoever asks first or silently deleted. Found
    during a bounded release-closure pass explicitly enumerating every
    fail-open fallback path in the codebase."""
    tenant = dict(owner_headers, **{"X-Tenant-Id": "default"})
    untagged_bill_id = "ACCT-QUARANTINE-BILL-1"
    _run(db.bills.insert_one({
        "id": untagged_bill_id, "vendorName": "Untagged Legacy Vendor",
        "amount": 500.0, "amountPaid": 0.0, "status": "unpaid",
        "dueDate": "2099-01-01", "businessId": None,
    }))
    try:
        pay = req(client, "POST", f"/api/accounting/bills/{untagged_bill_id}/pay",
                   headers=tenant, json={"amount": 500.0, "accountCode": "1000"})
        assert pay.status_code == 404, (
            f"an untagged bill must be refused for payment (quarantined), not auto-owned, got {pay.status_code}"
        )
        delete = req(client, "DELETE", f"/api/accounting/bills/{untagged_bill_id}", headers=tenant)
        assert delete.status_code == 404, (
            f"an untagged bill must be refused for deletion (quarantined), not auto-owned, got {delete.status_code}"
        )
        still_there = _run(db.bills.find_one({"id": untagged_bill_id}))
        assert still_there is not None, "quarantine must never delete the untagged document as a side effect"
        assert still_there["status"] == "unpaid", "quarantine must never mutate the untagged document either"
    finally:
        _run(db.bills.delete_many({"id": untagged_bill_id}))
