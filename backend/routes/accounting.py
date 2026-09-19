"""
NUA Enterprise Accounting — REST endpoints.

Routes
──────
Chart of Accounts
  GET    /accounting/accounts
  POST   /accounting/accounts
  PUT    /accounting/accounts/{code}
  DELETE /accounting/accounts/{code}          (locked accounts guarded)
  POST   /accounting/seed                     (idempotent COA seed)

Journals
  GET    /accounting/journals                  (with filters)
  GET    /accounting/journals/{id}
  POST   /accounting/journals                  (manual entry)
  POST   /accounting/journals/{id}/reverse

Reports
  GET    /accounting/reports/trial-balance
  GET    /accounting/reports/profit-loss
  GET    /accounting/reports/balance-sheet
  GET    /accounting/reports/cash-flow
  GET    /accounting/reports/general-ledger/{code}
  GET    /accounting/reports/budget-vs-actual

AP (Bills)
  GET/POST   /accounting/bills
  POST       /accounting/bills/{id}/pay
  DELETE     /accounting/bills/{id}

AR (Invoices)
  GET/POST   /accounting/invoices
  POST       /accounting/invoices/parse-upload  (AI OCR draft from a photo/text)
  POST       /accounting/invoices/{id}/receive
  DELETE     /accounting/invoices/{id}

Customer Deposits
  GET/POST   /accounting/deposits
  POST       /accounting/deposits/{id}/apply
  POST       /accounting/deposits/{id}/refund

Bank Reconciliation
  GET   /accounting/bank/statement/{account_code}
  POST  /accounting/bank/import                (bulk statement upload)
  POST  /accounting/bank/{line_id}/match/{journal_id}
  POST  /accounting/bank/{line_id}/ignore

Budgets
  GET/POST      /accounting/budgets
  PUT/DELETE    /accounting/budgets/{id}

Dashboard / KPIs
  GET   /accounting/kpis
"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from database import db
from deps import get_user, require_owner_or_manager
from models.accounting import (
    Account, JournalEntry, Bill, Invoice, CustomerDeposit,
    Budget, BankStatementLine,
)
from utils.mongo_safe import safe_parse_list
from services import accounting_service as svc
from middleware.actor_context import tenant_scope_filter, tenant_owns_strict
import uuid
import logging
import os

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/accounting")


# ═════════════════════════════════════════════════════════════════════════
# Chart of Accounts
# ═════════════════════════════════════════════════════════════════════════
@router.get("/accounts")
async def list_accounts(user: dict = Depends(get_user)):
    rows = await db.accounts.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}).sort("code", 1).to_list(500)
    return safe_parse_list(rows, Account, where="accounts")


@router.post("/accounts")
async def create_account(body: dict, user: dict = Depends(require_owner_or_manager)):
    code = str(body.get("code") or "").strip()
    if not code:
        raise HTTPException(400, "code is required")
    business_id = user.get("businessId")
    # Accounts are keyed by (code, businessId) — a code existing for another
    # business must never block this business from using it.
    dup_query = {"$and": [tenant_scope_filter(business_id), {"code": code}]}
    if await db.accounts.find_one(dup_query):
        raise HTTPException(400, f"Account {code} already exists")
    acc = Account(**{**body, "code": code, "businessId": business_id}).dict()
    await db.accounts.insert_one(dict(acc))
    return acc


@router.put("/accounts/{code}")
async def update_account(code: str, body: dict, user: dict = Depends(require_owner_or_manager)):
    business_id = user.get("businessId")
    query = {"$and": [tenant_scope_filter(business_id), {"code": code}]}
    existing = await db.accounts.find_one(query, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Account not found")
    if existing.get("isLocked") and body.get("type") and body["type"] != existing.get("type"):
        raise HTTPException(400, "Cannot change type of a locked (system) account")
    upd = {k: v for k, v in body.items() if k not in ("code", "id", "businessId")}
    await db.accounts.update_one(query, {"$set": upd})
    return await db.accounts.find_one(query, {"_id": 0})


@router.delete("/accounts/{code}")
async def delete_account(code: str, user: dict = Depends(require_owner_or_manager)):
    business_id = user.get("businessId")
    query = {"$and": [tenant_scope_filter(business_id), {"code": code}]}
    acc = await db.accounts.find_one(query, {"_id": 0})
    if not acc:
        raise HTTPException(404, "Account not found")
    if acc.get("isLocked"):
        raise HTTPException(400, "Locked system account cannot be deleted")
    used_query = {"$and": [tenant_scope_filter(business_id),
                            {"lines.accountCode": code, "posted": True}]}
    used = await db.journal_entries.count_documents(used_query)
    if used:
        raise HTTPException(400, f"Account is used in {used} journal entries — deactivate instead")
    await db.accounts.delete_one(query)
    return {"deleted": True}


@router.post("/seed")
async def seed(user: dict = Depends(require_owner_or_manager)):
    return await svc.seed_chart_of_accounts(business_id=user.get("businessId"))


# ═════════════════════════════════════════════════════════════════════════
# Journals
# ═════════════════════════════════════════════════════════════════════════
@router.get("/journals")
async def list_journals(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    source_type: Optional[str] = None,
    account_code: Optional[str] = None,
    limit: int = 200,
    user: dict = Depends(get_user),
):
    q: Dict[str, Any] = {}
    if from_date or to_date:
        q["date"] = {}
        if from_date: q["date"]["$gte"] = from_date
        if to_date:   q["date"]["$lte"] = to_date
        if not q["date"]:
            q.pop("date")
    if source_type:
        q["sourceType"] = source_type
    if account_code:
        q["lines.accountCode"] = account_code
    # journal_entries had no tenant filter at all — any authenticated user
    # could list every business's ledger entries, not just their own.
    q.update(tenant_scope_filter(user.get("businessId")))
    rows = await db.journal_entries.find(q, {"_id": 0}).sort("date", -1).limit(limit).to_list(limit)
    return safe_parse_list(rows, JournalEntry, where="journal_entries")


@router.get("/journals/{jid}")
async def get_journal(jid: str, user: dict = Depends(get_user)):
    doc = await db.journal_entries.find_one({"$and": [{"id": jid}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if doc is None or not tenant_owns_strict(doc.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "Journal entry not found")
    return doc


@router.post("/journals")
async def create_journal(body: dict, user: dict = Depends(require_owner_or_manager)):
    try:
        je = await svc.post_entry(
            body.get("lines") or [],
            entry_date=body.get("date"),
            memo=body.get("memo"),
            reference=body.get("reference"),
            source_type="manual",
            created_by=user.get("email"),
            business_id=user.get("businessId"),
        )
        # Audit
        try:
            from services.audit_service import log_event
            await log_event(entity_type="journal_entry", entity_id=je.get("id"),
                            action="created", after=je, memo=f"Manual journal {je.get('journalNumber')}")
        except Exception as e:
            from utils.errors import log_and_continue
            log_and_continue(logger, f"Journal entry audit log write failed for {je.get('id')}", e)
        return je
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/journals/{jid}/reverse")
async def reverse_journal(jid: str, body: dict, user: dict = Depends(require_owner_or_manager)):
    try:
        return await svc.reverse_entry(jid, memo=body.get("memo"), created_by=user.get("email"),
                                        business_id=user.get("businessId"))
    except ValueError as e:
        raise HTTPException(400, str(e))


# ═════════════════════════════════════════════════════════════════════════
# Reports
# ═════════════════════════════════════════════════════════════════════════
def _default_period() -> Dict[str, str]:
    """Financial year default: current AU FY (Jul 1 → Jun 30)."""
    today = datetime.now(timezone.utc).date()
    fy_start_year = today.year if today.month >= 7 else today.year - 1
    return {
        "from": f"{fy_start_year}-07-01",
        "to": f"{fy_start_year + 1}-06-30",
    }


@router.get("/reports/trial-balance")
async def report_trial_balance(as_of: Optional[str] = None, user: dict = Depends(get_user)):
    return await svc.trial_balance(as_of=as_of, business_id=user.get("businessId"))


@router.get("/reports/profit-loss")
async def report_profit_loss(
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    user: dict = Depends(get_user),
):
    d = _default_period()
    return await svc.profit_and_loss(from_date or d["from"], to_date or d["to"], business_id=user.get("businessId"))


@router.get("/reports/balance-sheet")
async def report_balance_sheet(as_of: Optional[str] = None, user: dict = Depends(get_user)):
    return await svc.balance_sheet(as_of=as_of, business_id=user.get("businessId"))


@router.get("/reports/cash-flow")
async def report_cash_flow(
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    user: dict = Depends(get_user),
):
    d = _default_period()
    return await svc.cash_flow(from_date or d["from"], to_date or d["to"], business_id=user.get("businessId"))


@router.get("/reports/general-ledger/{code}")
async def report_general_ledger(
    code: str,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    user: dict = Depends(get_user),
):
    return await svc.general_ledger(code, from_date=from_date, to_date=to_date, business_id=user.get("businessId"))


@router.get("/reports/budget-vs-actual")
async def report_budget_vs_actual(
    budget_id: Optional[str] = None,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    user: dict = Depends(get_user),
):
    d = _default_period()
    from_d = from_date or d["from"]
    to_d = to_date or d["to"]
    business_id = user.get("businessId")
    budget_query = tenant_scope_filter(business_id)
    budget = None
    if budget_id:
        budget = await db.budgets.find_one({"$and": [budget_query, {"id": budget_id}]}, {"_id": 0})
    else:
        budget = await db.budgets.find_one(budget_query, {"_id": 0}, sort=[("createdAt", -1)])
    actuals = await svc._account_totals_between(from_d, to_d, business_id)
    accounts = await svc._account_map(business_id)

    def months_in_range(a: str, b: str) -> int:
        ay, am, _ = a.split("-"); by, bm, _ = b.split("-")
        return max(1, (int(by) - int(ay)) * 12 + (int(bm) - int(am)) + 1)

    months = months_in_range(from_d, to_d) if budget else 1
    rows = []
    if budget:
        for line in budget.get("lines", []):
            code = line["accountCode"]
            acc = accounts.get(code, {"name": code, "type": "unknown"})
            budget_total = float(line.get("monthlyAmount") or 0) * months
            actual = abs(round(actuals.get(code, 0.0), 2))
            variance = round(actual - budget_total, 2)
            rows.append({
                "code": code, "name": acc.get("name"), "type": acc.get("type"),
                "budget": round(budget_total, 2), "actual": actual, "variance": variance,
                "variancePct": round((variance / budget_total) * 100, 1) if budget_total else 0.0,
            })
    return {
        "from": from_d, "to": to_d,
        "budgetId": budget["id"] if budget else None,
        "budgetName": budget["name"] if budget else None,
        "rows": rows,
    }


# ═════════════════════════════════════════════════════════════════════════
# AP — Bills
# ═════════════════════════════════════════════════════════════════════════
@router.get("/bills")
async def list_bills(status: Optional[str] = None, supplier_id: Optional[str] = None, user: dict = Depends(get_user)):
    q: Dict[str, Any] = {}
    if status: q["status"] = status
    if supplier_id: q["supplierId"] = supplier_id
    # Accounts-payable bills, same missing-filter gap as journal_entries above.
    q.update(tenant_scope_filter(user.get("businessId")))
    rows = await db.bills.find(q, {"_id": 0}).sort("dueDate", 1).to_list(500)
    return safe_parse_list(rows, Bill, where="bills")


@router.post("/bills")
async def create_bill(body: dict, user: dict = Depends(require_owner_or_manager)):
    business_id = user.get("businessId")
    try:
        bill = Bill(**{**body, "businessId": business_id}).dict()
    except Exception as e:
        raise HTTPException(422, f"Invalid bill payload: {e}")
    # attempt auto-post
    try:
        je = await svc.auto_post_bill(bill, business_id=business_id)
        if je:
            bill["journalEntryId"] = je["id"]
    except ValueError as e:
        raise HTTPException(400, f"Bill posting failed: {e}")
    await db.bills.insert_one(dict(bill))
    return bill


@router.post("/bills/{bid}/pay")
async def pay_bill(bid: str, body: dict, user: dict = Depends(require_owner_or_manager)):
    business_id = user.get("businessId")
    bill = await db.bills.find_one({"$and": [{"id": bid}, tenant_scope_filter(business_id)]}, {"_id": 0})
    if bill is None or not tenant_owns_strict(bill.get("businessId"), business_id):
        raise HTTPException(404, "Bill not found")
    amount = float(body.get("amount") or 0)
    if amount <= 0:
        raise HTTPException(400, "amount must be > 0")
    remaining = float(bill["total"]) - float(bill.get("paidAmount") or 0)
    if amount > remaining + 0.01:
        raise HTTPException(400, f"Payment exceeds remaining balance {remaining}")
    payment = {
        "id": str(uuid.uuid4()),
        "billId": bid,
        "supplierId": bill.get("supplierId"),
        "amount": amount,
        "method": body.get("method", "bank"),
        "paidAt": body.get("paidAt") or datetime.now(timezone.utc).date().isoformat(),
        "reference": body.get("reference"),
        "createdBy": user.get("email"),
        "businessId": business_id,
    }
    try:
        je = await svc.auto_post_bill_payment(payment, business_id=business_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    payment["journalEntryId"] = je["id"] if je else None
    await db.bill_payments.insert_one(dict(payment))

    new_paid = float(bill.get("paidAmount") or 0) + amount
    new_status = "paid" if new_paid + 0.01 >= float(bill["total"]) else "partial"
    await db.bills.update_one({"$and": [{"id": bid}, tenant_scope_filter(business_id)]}, {"$set": {"paidAmount": round(new_paid, 2), "status": new_status}})
    return {"payment": payment, "newStatus": new_status, "paidAmount": round(new_paid, 2)}


@router.delete("/bills/{bid}")
async def delete_bill(bid: str, user: dict = Depends(require_owner_or_manager)):
    business_id = user.get("businessId")
    bill = await db.bills.find_one({"$and": [{"id": bid}, tenant_scope_filter(business_id)]}, {"_id": 0})
    if bill is None or not tenant_owns_strict(bill.get("businessId"), business_id):
        raise HTTPException(404, "Bill not found")
    if bill.get("paidAmount", 0) > 0:
        raise HTTPException(400, "Bill has payments — reverse those first")
    if bill.get("journalEntryId"):
        try:
            await svc.reverse_entry(bill["journalEntryId"], memo="Bill deleted", business_id=business_id)
        except ValueError:
            pass
    await db.bills.delete_one({"$and": [{"id": bid}, tenant_scope_filter(business_id)]})
    return {"deleted": True}


# ═════════════════════════════════════════════════════════════════════════
# AR — Invoices
# ═════════════════════════════════════════════════════════════════════════
@router.get("/invoices")
async def list_invoices(status: Optional[str] = None, customer_id: Optional[str] = None, user: dict = Depends(get_user)):
    q: Dict[str, Any] = {}
    if status: q["status"] = status
    if customer_id: q["customerId"] = customer_id
    q = {"$and": [q, tenant_scope_filter(user.get("businessId"))]}
    rows = await db.ar_invoices.find(q, {"_id": 0}).sort("dueDate", 1).to_list(500)
    return safe_parse_list(rows, Invoice, where="ar_invoices")


@router.post("/invoices")
async def create_invoice(body: dict, user: dict = Depends(require_owner_or_manager)):
    business_id = user.get("businessId")
    try:
        inv = Invoice(**{**body, "businessId": business_id}).dict()
    except Exception as e:
        raise HTTPException(422, f"Invalid invoice payload: {e}")
    try:
        je = await svc.auto_post_invoice(inv, business_id=business_id)
        if je: inv["journalEntryId"] = je["id"]
    except ValueError as e:
        raise HTTPException(400, str(e))
    await db.ar_invoices.insert_one(dict(inv))
    return inv


@router.post("/invoices/{iid}/receive")
async def receive_invoice(iid: str, body: dict, user: dict = Depends(require_owner_or_manager)):
    business_id = user.get("businessId")
    inv = await db.ar_invoices.find_one({"$and": [{"id": iid}, tenant_scope_filter(business_id)]}, {"_id": 0})
    if inv is None or not tenant_owns_strict(inv.get("businessId"), business_id):
        raise HTTPException(404, "Invoice not found")
    amount = float(body.get("amount") or 0)
    if amount <= 0:
        raise HTTPException(400, "amount must be > 0")
    remaining = float(inv["total"]) - float(inv.get("paidAmount") or 0)
    if amount > remaining + 0.01:
        raise HTTPException(400, f"Receipt exceeds outstanding {remaining}")
    receipt = {
        "id": str(uuid.uuid4()),
        "invoiceId": iid,
        "customerId": inv.get("customerId"),
        "amount": amount,
        "method": body.get("method", "bank"),
        "receivedAt": body.get("receivedAt") or datetime.now(timezone.utc).date().isoformat(),
        "createdBy": user.get("email"),
        "businessId": business_id,
    }
    try:
        je = await svc.auto_post_invoice_receipt(receipt, business_id=business_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    receipt["journalEntryId"] = je["id"] if je else None
    await db.ar_receipts.insert_one(dict(receipt))
    new_paid = float(inv.get("paidAmount") or 0) + amount
    new_status = "paid" if new_paid + 0.01 >= float(inv["total"]) else "partial"
    await db.ar_invoices.update_one({"$and": [{"id": iid}, tenant_scope_filter(business_id)]}, {"$set": {"paidAmount": round(new_paid, 2), "status": new_status}})
    return {"receipt": receipt, "newStatus": new_status, "paidAmount": round(new_paid, 2)}


@router.delete("/invoices/{iid}")
async def delete_invoice(iid: str, user: dict = Depends(require_owner_or_manager)):
    business_id = user.get("businessId")
    inv = await db.ar_invoices.find_one({"$and": [{"id": iid}, tenant_scope_filter(business_id)]}, {"_id": 0})
    if inv is None or not tenant_owns_strict(inv.get("businessId"), business_id):
        raise HTTPException(404, "Invoice not found")
    if inv.get("paidAmount", 0) > 0:
        raise HTTPException(400, "Invoice has receipts — reverse those first")
    if inv.get("journalEntryId"):
        try:
            await svc.reverse_entry(inv["journalEntryId"], memo="Invoice deleted", business_id=business_id)
        except ValueError:
            pass
    await db.ar_invoices.delete_one({"$and": [{"id": iid}, tenant_scope_filter(business_id)]})
    return {"deleted": True}


@router.post("/invoices/parse-upload")
async def parse_invoice_upload(data: dict, user: dict = Depends(require_owner_or_manager)):
    """Upload an invoice the business is sending to ITS customer (a photo or
    pasted text) and let the LLM extract a draft — the same OCR pattern
    ai_pantry.py's parse-invoice uses for supplier bills, pointed at accounts
    receivable instead. Returns a draft only; nothing is saved until the
    caller reviews it and POSTs the result to /accounting/invoices."""
    invoice_text = (data.get("text") or "").strip()
    image_b64 = data.get("imageBase64")
    if not invoice_text and not image_b64:
        raise HTTPException(status_code=400, detail="Provide either invoice 'text' or 'imageBase64'")

    sys_msg = (
        "You parse invoices a business is sending to ITS customer (accounts "
        "receivable — money owed TO the business, not a supplier bill). "
        "Extract and return STRICT JSON with this shape: {"
        '"customerName":"...", "invoiceNumber":"...", "issueDate":"YYYY-MM-DD", '
        '"dueDate":"YYYY-MM-DD", "lines":[{"description":"...", "quantity":0, '
        '"unitPrice":0.00, "amount":0.00}], "gst":0, "total":0}. '
        "Use lower-case keys. If a value is missing use null. "
        "Best-guess parsing — do not invent line items."
    )

    from emergentintegrations.llm.chat import LlmChat, UserMessage
    chat = LlmChat(
        api_key=os.environ.get("EMERGENT_LLM_KEY"),
        session_id=f"ar-invoice-{uuid.uuid4().hex[:6]}",
        system_message=sys_msg,
    ).with_model("openai", "gpt-5.2")

    msg_args = {"text": invoice_text or "Parse the attached invoice image."}
    if image_b64:
        try:
            from emergentintegrations.llm.chat import ImageContent
            msg_args["file_contents"] = [ImageContent(image_base64=image_b64)]
        except Exception:
            pass
    reply = await chat.send_message(UserMessage(**msg_args))

    import json as _json
    parsed = None
    try:
        parsed = _json.loads(reply)
    except Exception:
        s, e = reply.find("{"), reply.rfind("}") + 1
        if s >= 0 and e > s:
            try: parsed = _json.loads(reply[s:e])
            except Exception: parsed = None
    if not parsed:
        raise HTTPException(status_code=422, detail=f"Could not parse invoice. AI returned: {reply[:300]}")

    # Best-guess match against existing customers by name — same fuzzy
    # token-overlap approach the supplier-invoice OCR uses for products.
    customers = await db.customers.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}).to_list(5000)
    matched_customer = None
    name = (parsed.get("customerName") or "").strip().lower()
    if name:
        for c in customers:
            if (c.get("name") or "").strip().lower() == name:
                matched_customer = c
                break
        if not matched_customer:
            tokens = set(t for t in name.split() if len(t) > 2)
            best, best_score = None, 0
            for c in customers:
                c_tokens = set(t for t in (c.get("name") or "").lower().split() if len(t) > 2)
                score = len(tokens & c_tokens)
                if score > best_score:
                    best, best_score = c, score
            if best_score > 0:
                matched_customer = best

    today_iso = datetime.now(timezone.utc).date().isoformat()
    lines = parsed.get("lines") or []
    return {
        "customerId": matched_customer["id"] if matched_customer else None,
        "customerName": parsed.get("customerName") or (matched_customer["name"] if matched_customer else None),
        "customerMatched": matched_customer is not None,
        "invoiceNumber": parsed.get("invoiceNumber"),
        "issueDate": parsed.get("issueDate") or today_iso,
        "dueDate": parsed.get("dueDate") or today_iso,
        "total": parsed.get("total") or round(sum((l.get("amount") or 0) for l in lines), 2),
        "gst": parsed.get("gst") or 0,
        "lines": lines,
    }


# ═════════════════════════════════════════════════════════════════════════
# Customer Deposits
# ═════════════════════════════════════════════════════════════════════════
@router.get("/deposits")
async def list_deposits(status: Optional[str] = None, user: dict = Depends(get_user)):
    q: Dict[str, Any] = {}
    if status: q["status"] = status
    q = {"$and": [q, tenant_scope_filter(user.get("businessId"))]}
    rows = await db.customer_deposits.find(q, {"_id": 0}).sort("receivedAt", -1).to_list(500)
    return safe_parse_list(rows, CustomerDeposit, where="customer_deposits")


@router.post("/deposits")
async def create_deposit(body: dict, user: dict = Depends(require_owner_or_manager)):
    business_id = user.get("businessId")
    dep = CustomerDeposit(**{**body, "businessId": business_id}).dict()
    try:
        je = await svc.auto_post_customer_deposit(dep, business_id=business_id)
        if je: dep["journalEntryId"] = je["id"]
    except ValueError as e:
        raise HTTPException(400, str(e))
    await db.customer_deposits.insert_one(dict(dep))
    return dep


@router.post("/deposits/{did}/apply")
async def apply_deposit(did: str, body: dict, user: dict = Depends(require_owner_or_manager)):
    business_id = user.get("businessId")
    dep = await db.customer_deposits.find_one({"$and": [{"id": did}, tenant_scope_filter(business_id)]}, {"_id": 0})
    if dep is None or not tenant_owns_strict(dep.get("businessId"), business_id):
        raise HTTPException(404, "Deposit not found")
    if dep.get("status") != "held":
        raise HTTPException(400, f"Deposit already {dep.get('status')}")
    txn_id = body.get("transactionId")
    if not txn_id:
        raise HTTPException(400, "transactionId required")
    try:
        je = await svc.auto_post_deposit_applied(dep, {"id": txn_id}, business_id=business_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await db.customer_deposits.update_one(
        {"$and": [{"id": did}, tenant_scope_filter(business_id)]}, {"$set": {"status": "applied", "appliedTransactionId": txn_id,
                                "appliedJournalEntryId": je["id"] if je else None}}
    )
    return {"applied": True, "journalEntryId": je["id"] if je else None}


@router.post("/deposits/{did}/refund")
async def refund_deposit(did: str, user: dict = Depends(require_owner_or_manager)):
    business_id = user.get("businessId")
    dep = await db.customer_deposits.find_one({"$and": [{"id": did}, tenant_scope_filter(business_id)]}, {"_id": 0})
    if dep is None or not tenant_owns_strict(dep.get("businessId"), business_id):
        raise HTTPException(404, "Deposit not found")
    if dep.get("status") != "held":
        raise HTTPException(400, f"Deposit already {dep.get('status')}")
    try:
        je = await svc.auto_post_deposit_refunded(dep, business_id=business_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await db.customer_deposits.update_one(
        {"$and": [{"id": did}, tenant_scope_filter(business_id)]}, {"$set": {"status": "refunded",
                                "refundedJournalEntryId": je["id"] if je else None}}
    )
    return {"refunded": True, "journalEntryId": je["id"] if je else None}


# ═════════════════════════════════════════════════════════════════════════
# Bank reconciliation
# ═════════════════════════════════════════════════════════════════════════
@router.get("/bank/statement/{code}")
async def bank_statement(code: str, unmatched_only: bool = False, user: dict = Depends(get_user)):
    business_id = user.get("businessId")
    q: Dict[str, Any] = {"accountCode": code}
    if unmatched_only:
        q["matchedJournalLineId"] = None
        q["ignored"] = False
    q = {"$and": [q, tenant_scope_filter(business_id)]}
    rows = await db.bank_statement_lines.find(q, {"_id": 0}).sort("statementDate", -1).to_list(1000)
    # Suggest possible journal matches within 3 days & same amount for unmatched lines
    for r in rows:
        if r.get("matchedJournalLineId") or r.get("ignored"):
            continue
        target = float(r["amount"])
        try:
            sd = datetime.fromisoformat(r["statementDate"]).date()
        except Exception:
            sd = None
        near = []
        if sd:
            lo = (sd - timedelta(days=3)).isoformat()
            hi = (sd + timedelta(days=3)).isoformat()
            cand_query = {"$and": [{"date": {"$gte": lo, "$lte": hi}, "lines.accountCode": code},
                                    tenant_scope_filter(business_id)]}
            cand = await db.journal_entries.find(cand_query, {"_id": 0}).to_list(50)
            for je in cand:
                for l in je["lines"]:
                    if l.get("accountCode") != code:
                        continue
                    line_amt = float(l.get("debit") or 0) - float(l.get("credit") or 0)
                    if abs(line_amt - target) < 0.01:
                        near.append({"journalId": je["id"], "journalNumber": je.get("journalNumber"),
                                     "memo": je.get("memo"), "amount": round(line_amt, 2)})
        r["suggestedMatches"] = near[:5]
    return safe_parse_list(rows, BankStatementLine, where="bank_statement_lines")


@router.post("/bank/import")
async def bank_import(body: dict, user: dict = Depends(require_owner_or_manager)):
    business_id = user.get("businessId")
    account_code = body.get("accountCode")
    if not account_code:
        raise HTTPException(400, "accountCode required")
    lines_in = body.get("lines") or []
    inserted = 0
    for l in lines_in:
        doc = BankStatementLine(**{**l, "accountCode": account_code, "businessId": business_id}).dict()
        if doc.get("externalId"):
            exists_query = {"$and": [tenant_scope_filter(business_id),
                                      {"externalId": doc["externalId"], "accountCode": account_code}]}
            exists = await db.bank_statement_lines.find_one(exists_query)
            if exists:
                continue
        await db.bank_statement_lines.insert_one(dict(doc))
        inserted += 1
    return {"inserted": inserted, "skipped": len(lines_in) - inserted}


@router.post("/bank/{line_id}/match/{journal_id}")
async def bank_match(line_id: str, journal_id: str, user: dict = Depends(require_owner_or_manager)):
    business_id = user.get("businessId")
    line = await db.bank_statement_lines.find_one({"$and": [{"id": line_id}, tenant_scope_filter(business_id)]}, {"_id": 0})
    if line is None or not tenant_owns_strict(line.get("businessId"), business_id):
        raise HTTPException(404, "Statement line not found")
    je = await db.journal_entries.find_one({"$and": [{"id": journal_id}, tenant_scope_filter(business_id)]}, {"_id": 0})
    if je is None or not tenant_owns_strict(je.get("businessId"), business_id):
        raise HTTPException(404, "Journal not found")
    await db.bank_statement_lines.update_one(
        {"$and": [{"id": line_id}, tenant_scope_filter(business_id)]},
        {"$set": {"matchedJournalLineId": journal_id, "matchedAt": datetime.now(timezone.utc).isoformat()}},
    )
    return {"matched": True}


@router.post("/bank/{line_id}/ignore")
async def bank_ignore(line_id: str, user: dict = Depends(require_owner_or_manager)):
    guard = await db.bank_statement_lines.find_one({"$and": [{"id": line_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "id": 1, "businessId": 1})
    if guard is None or not tenant_owns_strict(guard.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "Statement line not found")
    r = await db.bank_statement_lines.update_one({"$and": [{"id": line_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": {"ignored": True}})
    if r.matched_count == 0:
        raise HTTPException(404, "Statement line not found")
    return {"ignored": True}


# ═════════════════════════════════════════════════════════════════════════
# Budgets
# ═════════════════════════════════════════════════════════════════════════
@router.get("/budgets")
async def list_budgets(user: dict = Depends(get_user)):
    rows = await db.budgets.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}).sort("createdAt", -1).to_list(50)
    return safe_parse_list(rows, Budget, where="budgets")


@router.post("/budgets")
async def create_budget(body: dict, user: dict = Depends(require_owner_or_manager)):
    b = Budget(**{**body, "businessId": user.get("businessId")}).dict()
    await db.budgets.insert_one(dict(b))
    return b


@router.put("/budgets/{bid}")
async def update_budget(bid: str, body: dict, user: dict = Depends(require_owner_or_manager)):
    business_id = user.get("businessId")
    existing = await db.budgets.find_one({"$and": [{"id": bid}, tenant_scope_filter(business_id)]}, {"_id": 0})
    if existing is None or not tenant_owns_strict(existing.get("businessId"), business_id):
        raise HTTPException(404, "Budget not found")
    updated = Budget(**{**existing, **body, "id": bid, "businessId": business_id}).dict()
    await db.budgets.replace_one({"id": bid}, updated)
    return updated


@router.delete("/budgets/{bid}")
async def delete_budget(bid: str, user: dict = Depends(require_owner_or_manager)):
    guard = await db.budgets.find_one({"$and": [{"id": bid}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "id": 1, "businessId": 1})
    if guard is None or not tenant_owns_strict(guard.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "Budget not found")
    result = await db.budgets.delete_one({"$and": [{"id": bid}, tenant_scope_filter(user.get("businessId"))]})
    if result.deleted_count == 0:
        raise HTTPException(404, "Budget not found")
    return {"deleted": True}


# ═════════════════════════════════════════════════════════════════════════
# Dashboard KPIs
# ═════════════════════════════════════════════════════════════════════════
@router.get("/kpis")
async def kpis(user: dict = Depends(get_user)):
    business_id = user.get("businessId")
    today = datetime.now(timezone.utc).date()
    fy_start = f"{today.year if today.month >= 7 else today.year - 1}-07-01"
    to_d = today.isoformat()

    pnl = await svc.profit_and_loss(fy_start, to_d, business_id=business_id)
    bs = await svc.balance_sheet(as_of=to_d, business_id=business_id)
    cash = await svc.cash_flow(fy_start, to_d, business_id=business_id)

    # AR/AP outstanding
    scope = tenant_scope_filter(business_id)
    ar_open = await db.ar_invoices.find(
        {"$and": [{"status": {"$in": ["unpaid", "partial", "overdue"]}}, scope]}, {"_id": 0}).to_list(1000)
    ap_open = await db.bills.find(
        {"$and": [{"status": {"$in": ["unpaid", "partial", "overdue"]}}, scope]}, {"_id": 0}).to_list(1000)
    ar_outstanding = round(sum(float(i["total"]) - float(i.get("paidAmount") or 0) for i in ar_open), 2)
    ap_outstanding = round(sum(float(b["total"]) - float(b.get("paidAmount") or 0) for b in ap_open), 2)

    return {
        "fyStart": fy_start,
        "asOf": to_d,
        "revenue": pnl["totalRevenue"],
        "grossProfit": pnl["grossProfit"],
        "netProfit": pnl["netProfit"],
        "grossMarginPct": pnl["grossMarginPct"],
        "netMarginPct": pnl["netMarginPct"],
        "cashOnHand": bs["totalAssets"] and cash["closingBalance"],
        "totalAssets": bs["totalAssets"],
        "totalLiabilities": bs["totalLiabilities"],
        "arOutstanding": ar_outstanding,
        "apOutstanding": ap_outstanding,
        "openInvoices": len(ar_open),
        "openBills": len(ap_open),
    }
