"""
NUA Enterprise Accounting — double-entry ledger service.

Everything money-shaped funnels through `post_entry`. Reports are read-only
aggregations over `journal_lines` denormalised out of every posted entry.

Guarantees
──────────
• sum(debits) == sum(credits) on every entry (validated on insert)
• Immutable posted entries — corrections require reversing journals
• Idempotent auto-posting: sourceRef+sourceType duplicates are silently
  skipped so hooks are safe to re-fire.
"""
from __future__ import annotations
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from database import db
from models.accounting import JournalEntry, JournalLine
from middleware.actor_context import tenant_scope_filter, tenant_owns_strict, get_actor_context
import uuid
import logging

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════
# Chart of Accounts — hospitality seed (AU GST-ready)
# ═════════════════════════════════════════════════════════════════════════
SEED_COA: List[Dict[str, Any]] = [
    # Assets (1xxx)
    {"code": "1000", "name": "Cash at Bank",             "type": "asset",     "subType": "current_asset",   "isBank": True,  "isLocked": True},
    {"code": "1010", "name": "Cash on Hand (Till)",      "type": "asset",     "subType": "current_asset",   "isBank": True,  "isLocked": True},
    {"code": "1050", "name": "Undeposited Funds",        "type": "asset",     "subType": "current_asset",   "isLocked": True},
    {"code": "1100", "name": "Accounts Receivable",      "type": "asset",     "subType": "current_asset",   "isLocked": True},
    {"code": "1200", "name": "Inventory",                "type": "asset",     "subType": "current_asset",   "isLocked": True},
    {"code": "1500", "name": "Fixed Assets",             "type": "asset",     "subType": "non_current_asset"},
    {"code": "1510", "name": "Accumulated Depreciation", "type": "asset",     "subType": "contra_asset"},

    # Liabilities (2xxx)
    {"code": "2000", "name": "Accounts Payable",         "type": "liability", "subType": "current_liability", "isLocked": True},
    {"code": "2100", "name": "GST Collected",            "type": "liability", "subType": "current_liability", "isLocked": True},
    {"code": "2110", "name": "GST Paid",                 "type": "liability", "subType": "current_liability", "isLocked": True},
    {"code": "2200", "name": "PAYG Withholding Payable", "type": "liability", "subType": "current_liability", "isLocked": True},
    {"code": "2210", "name": "Superannuation Payable",   "type": "liability", "subType": "current_liability", "isLocked": True},
    {"code": "2300", "name": "Gift Card Liability",      "type": "liability", "subType": "current_liability", "isLocked": True},
    {"code": "2310", "name": "Voucher Liability",        "type": "liability", "subType": "current_liability", "isLocked": True},
    {"code": "2320", "name": "Customer Deposits Held",   "type": "liability", "subType": "current_liability", "isLocked": True},
    {"code": "2400", "name": "Wages Payable",            "type": "liability", "subType": "current_liability", "isLocked": True},
    {"code": "2410", "name": "Gratuities Payable",       "type": "liability", "subType": "current_liability", "isLocked": True},

    # Equity (3xxx)
    {"code": "3000", "name": "Owner's Equity",           "type": "equity",    "isLocked": True},
    {"code": "3900", "name": "Retained Earnings",        "type": "equity",    "isLocked": True},

    # Revenue (4xxx)
    {"code": "4000", "name": "Food Sales",               "type": "revenue",   "subType": "operating_revenue"},
    {"code": "4010", "name": "Beverage Sales",           "type": "revenue",   "subType": "operating_revenue"},
    {"code": "4020", "name": "Retail Sales",             "type": "revenue",   "subType": "operating_revenue"},
    {"code": "4030", "name": "Function / Catering",      "type": "revenue",   "subType": "operating_revenue"},
    {"code": "4040", "name": "Surcharge Revenue",        "type": "revenue",   "subType": "operating_revenue"},
    {"code": "4090", "name": "Sales Discounts",          "type": "revenue",   "subType": "contra_revenue"},
    {"code": "4100", "name": "Gift Card Breakage",       "type": "revenue",   "subType": "other_revenue"},

    # Expenses (5xxx-6xxx)
    {"code": "5000", "name": "Cost of Goods Sold — Food",     "type": "expense", "subType": "cogs"},
    {"code": "5010", "name": "Cost of Goods Sold — Beverage", "type": "expense", "subType": "cogs"},
    {"code": "5020", "name": "Cost of Goods Sold — Retail",   "type": "expense", "subType": "cogs"},
    {"code": "6000", "name": "Wages & Salaries",              "type": "expense", "subType": "operating_expense"},
    {"code": "6010", "name": "Superannuation Expense",        "type": "expense", "subType": "operating_expense"},
    {"code": "6020", "name": "PAYG Expense",                  "type": "expense", "subType": "operating_expense"},
    {"code": "6100", "name": "Rent",                          "type": "expense", "subType": "operating_expense"},
    {"code": "6110", "name": "Utilities",                     "type": "expense", "subType": "operating_expense"},
    {"code": "6120", "name": "Marketing & Advertising",       "type": "expense", "subType": "operating_expense"},
    {"code": "6130", "name": "Insurance",                     "type": "expense", "subType": "operating_expense"},
    {"code": "6140", "name": "Repairs & Maintenance",         "type": "expense", "subType": "operating_expense"},
    {"code": "6150", "name": "Merchant Fees",                 "type": "expense", "subType": "operating_expense"},
    {"code": "6160", "name": "Software & Subscriptions",      "type": "expense", "subType": "operating_expense"},
    {"code": "6200", "name": "Depreciation Expense",          "type": "expense", "subType": "non_cash_expense"},
    {"code": "6900", "name": "Miscellaneous Expense",         "type": "expense", "subType": "operating_expense"},
]


async def seed_chart_of_accounts(business_id: Optional[str] = None) -> Dict[str, int]:
    """Idempotent — insert any missing seed accounts without touching customised ones.

    Accounts are keyed by (code, businessId): each business gets its own
    chart of accounts, seeded independently. Without businessId on `code`
    uniqueness, the first business to seed would "claim" every code and no
    other business could ever seed its own copy.
    """
    if business_id is None:
        business_id = get_actor_context().get("businessId")
    existing = {a["code"] async for a in db.accounts.find(tenant_scope_filter(business_id), {"code": 1})}
    to_insert = []
    for acc in SEED_COA:
        if acc["code"] in existing:
            continue
        doc = {
            "id": str(uuid.uuid4()),
            "currency": "AUD",
            "active": True,
            "isLocked": acc.get("isLocked", False),
            "isBank": acc.get("isBank", False),
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "businessId": business_id,
            **acc,
        }
        to_insert.append(doc)
    if to_insert:
        await db.accounts.insert_many(to_insert)
    return {"seeded": len(to_insert), "total": len(existing) + len(to_insert)}


# ═════════════════════════════════════════════════════════════════════════
# Journal posting
# ═════════════════════════════════════════════════════════════════════════
def _validate_balanced(lines: List[Dict[str, Any]]) -> None:
    if not lines:
        raise ValueError("Journal entry needs at least one line")
    debits = round(sum(float(l.get("debit") or 0) for l in lines), 2)
    credits = round(sum(float(l.get("credit") or 0) for l in lines), 2)
    if abs(debits - credits) > 0.005:
        raise ValueError(f"Entry unbalanced: debits={debits} credits={credits}")
    if debits == 0:
        raise ValueError("Zero-value entry — nothing to post")
    for l in lines:
        if float(l.get("debit") or 0) > 0 and float(l.get("credit") or 0) > 0:
            raise ValueError(f"Line {l.get('accountCode')} has both debit and credit — split into two lines")


async def _next_journal_number(business_id: Optional[str]) -> str:
    query = {"$and": [tenant_scope_filter(business_id), {"journalNumber": {"$exists": True}}]}
    last = await db.journal_entries.find_one(
        query,
        {"journalNumber": 1},
        sort=[("journalNumber", -1)],
    )
    n = 1
    if last and last.get("journalNumber"):
        try:
            n = int(str(last["journalNumber"]).split("-")[-1]) + 1
        except Exception:
            n = 1
    return f"JE-{n:06d}"


async def _enrich_account_names(lines: List[Dict[str, Any]], business_id: Optional[str]) -> List[Dict[str, Any]]:
    codes = list({l["accountCode"] for l in lines if l.get("accountCode")})
    if not codes:
        return lines
    query = {"$and": [tenant_scope_filter(business_id), {"code": {"$in": codes}}]}
    accs = {
        a["code"]: a
        async for a in db.accounts.find(query, {"_id": 0, "code": 1, "name": 1})
    }
    for l in lines:
        if not l.get("accountName") and l.get("accountCode") in accs:
            l["accountName"] = accs[l["accountCode"]]["name"]
    return lines


async def post_entry(
    lines: List[Dict[str, Any]],
    *,
    entry_date: Optional[str] = None,
    memo: Optional[str] = None,
    reference: Optional[str] = None,
    source_type: str = "manual",
    source_ref: Optional[str] = None,
    created_by: Optional[str] = None,
    idempotent: bool = True,
    business_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Post a balanced double-entry journal. Raises ValueError on imbalance."""
    if business_id is None:
        business_id = get_actor_context().get("businessId")

    if idempotent and source_ref and source_type != "manual":
        query = {"$and": [tenant_scope_filter(business_id),
                           {"sourceType": source_type, "sourceRef": source_ref}]}
        existing = await db.journal_entries.find_one(query, {"_id": 0})
        if existing:
            return existing

    _validate_balanced(lines)
    lines = await _enrich_account_names(lines, business_id)

    entry = JournalEntry(
        journalNumber=await _next_journal_number(business_id),
        date=entry_date or datetime.now(timezone.utc).date().isoformat(),
        memo=memo,
        reference=reference,
        sourceType=source_type,
        sourceRef=source_ref,
        lines=[JournalLine(**l) for l in lines],
        posted=True,
        createdBy=created_by,
    )
    doc = entry.dict()
    doc["businessId"] = business_id
    await db.journal_entries.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


async def reverse_entry(entry_id: str, *, memo: Optional[str] = None, created_by: Optional[str] = None,
                         business_id: Optional[str] = None) -> Dict[str, Any]:
    """Create an opposite journal that cancels `entry_id`."""
    if business_id is None:
        business_id = get_actor_context().get("businessId")
    orig = await db.journal_entries.find_one({"$and": [{"id": entry_id}, tenant_scope_filter(business_id)]}, {"_id": 0})
    if orig is None or not tenant_owns_strict(orig.get("businessId"), business_id):
        raise ValueError("Journal entry not found")
    reversed_lines = [
        {"accountCode": l["accountCode"], "accountName": l.get("accountName"),
         "debit": float(l.get("credit") or 0), "credit": float(l.get("debit") or 0),
         "description": f"Reversal: {l.get('description') or ''}".strip(": "),
         "contactId": l.get("contactId")}
        for l in orig["lines"]
    ]
    rev = await post_entry(
        reversed_lines,
        entry_date=datetime.now(timezone.utc).date().isoformat(),
        memo=memo or f"Reversal of {orig.get('journalNumber')}",
        source_type="reversal",
        source_ref=entry_id,
        created_by=created_by,
        idempotent=False,
        business_id=business_id,
    )
    await db.journal_entries.update_one({"$and": [{"id": entry_id}, tenant_scope_filter(business_id)]}, {"$set": {"reversedBy": rev["id"]}})
    return rev


# ═════════════════════════════════════════════════════════════════════════
# Aggregations — reports read from journal_lines only
# ═════════════════════════════════════════════════════════════════════════
async def _account_map(business_id: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    return {
        a["code"]: a async for a in db.accounts.find(tenant_scope_filter(business_id), {"_id": 0})
    }


async def trial_balance(as_of: Optional[str] = None, business_id: Optional[str] = None) -> Dict[str, Any]:
    if business_id is None:
        business_id = get_actor_context().get("businessId")
    match: Dict[str, Any] = {"posted": True}
    if as_of:
        match["date"] = {"$lte": as_of}
    match = {"$and": [match, tenant_scope_filter(business_id)]}
    pipeline = [
        {"$match": match},
        {"$unwind": "$lines"},
        {"$group": {
            "_id": "$lines.accountCode",
            "debit": {"$sum": "$lines.debit"},
            "credit": {"$sum": "$lines.credit"},
        }},
        {"$sort": {"_id": 1}},
    ]
    rows = await db.journal_entries.aggregate(pipeline).to_list(1000)
    accounts = await _account_map(business_id)
    out = []
    total_debit = total_credit = 0.0
    for r in rows:
        code = r["_id"]
        acc = accounts.get(code, {"name": code, "type": "unknown"})
        d = round(float(r["debit"] or 0), 2)
        c = round(float(r["credit"] or 0), 2)
        # Present net side per accounting convention
        net_debit = max(0.0, d - c) if acc["type"] in ("asset", "expense") else 0.0
        net_credit = max(0.0, c - d) if acc["type"] in ("liability", "equity", "revenue") else 0.0
        if acc["type"] in ("asset", "expense"):
            if c > d:
                net_credit = c - d
        else:
            if d > c:
                net_debit = d - c
        total_debit += net_debit
        total_credit += net_credit
        out.append({
            "code": code, "name": acc.get("name", code), "type": acc.get("type"),
            "debit": round(net_debit, 2), "credit": round(net_credit, 2),
            "raw_debit": d, "raw_credit": c,
        })
    return {
        "asOf": as_of or datetime.now(timezone.utc).date().isoformat(),
        "rows": out,
        "totalDebit": round(total_debit, 2),
        "totalCredit": round(total_credit, 2),
        "balanced": abs(total_debit - total_credit) < 0.01,
    }


async def _account_totals_between(from_date: Optional[str], to_date: Optional[str],
                                    business_id: Optional[str] = None) -> Dict[str, float]:
    """Net movement per account (debit - credit) between dates."""
    if business_id is None:
        business_id = get_actor_context().get("businessId")
    match: Dict[str, Any] = {"posted": True}
    if from_date or to_date:
        match["date"] = {}
        if from_date: match["date"]["$gte"] = from_date
        if to_date:   match["date"]["$lte"] = to_date
        if not match["date"]:
            match.pop("date")
    match = {"$and": [match, tenant_scope_filter(business_id)]}
    pipeline = [
        {"$match": match},
        {"$unwind": "$lines"},
        {"$group": {
            "_id": "$lines.accountCode",
            "debit": {"$sum": "$lines.debit"},
            "credit": {"$sum": "$lines.credit"},
        }},
    ]
    rows = await db.journal_entries.aggregate(pipeline).to_list(2000)
    return {r["_id"]: round(float(r["debit"] or 0) - float(r["credit"] or 0), 2) for r in rows}


async def profit_and_loss(from_date: str, to_date: str, business_id: Optional[str] = None) -> Dict[str, Any]:
    if business_id is None:
        business_id = get_actor_context().get("businessId")
    totals = await _account_totals_between(from_date, to_date, business_id)
    accounts = await _account_map(business_id)
    revenue: List[Dict[str, Any]] = []
    cogs: List[Dict[str, Any]] = []
    expenses: List[Dict[str, Any]] = []
    other_revenue: List[Dict[str, Any]] = []
    for code, net in totals.items():
        acc = accounts.get(code)
        if not acc:
            continue
        t = acc["type"]
        sub = acc.get("subType") or ""
        # Revenue: credit balance → represent as positive
        if t == "revenue":
            amt = round(-net, 2)  # credits are negative net
            row = {"code": code, "name": acc["name"], "amount": amt}
            if sub == "other_revenue":
                other_revenue.append(row)
            else:
                revenue.append(row)
        elif t == "expense":
            amt = round(net, 2)
            row = {"code": code, "name": acc["name"], "amount": amt}
            if sub == "cogs":
                cogs.append(row)
            else:
                expenses.append(row)

    total_revenue = round(sum(r["amount"] for r in revenue), 2)
    total_cogs = round(sum(r["amount"] for r in cogs), 2)
    total_expenses = round(sum(r["amount"] for r in expenses), 2)
    total_other_rev = round(sum(r["amount"] for r in other_revenue), 2)
    gross_profit = round(total_revenue - total_cogs, 2)
    operating_profit = round(gross_profit - total_expenses, 2)
    net_profit = round(operating_profit + total_other_rev, 2)

    return {
        "from": from_date, "to": to_date,
        "revenue": sorted(revenue, key=lambda r: r["code"]),
        "cogs": sorted(cogs, key=lambda r: r["code"]),
        "expenses": sorted(expenses, key=lambda r: r["code"]),
        "otherRevenue": sorted(other_revenue, key=lambda r: r["code"]),
        "totalRevenue": total_revenue,
        "totalCOGS": total_cogs,
        "grossProfit": gross_profit,
        "totalExpenses": total_expenses,
        "operatingProfit": operating_profit,
        "totalOtherRevenue": total_other_rev,
        "netProfit": net_profit,
        "grossMarginPct": round((gross_profit / total_revenue) * 100, 2) if total_revenue else 0.0,
        "netMarginPct": round((net_profit / total_revenue) * 100, 2) if total_revenue else 0.0,
    }


async def balance_sheet(as_of: Optional[str] = None, business_id: Optional[str] = None) -> Dict[str, Any]:
    if business_id is None:
        business_id = get_actor_context().get("businessId")
    totals = await _account_totals_between(None, as_of, business_id)
    accounts = await _account_map(business_id)
    assets: List[Dict[str, Any]] = []
    liabilities: List[Dict[str, Any]] = []
    equity: List[Dict[str, Any]] = []
    # For equity we also need retained earnings up to as_of = revenues - expenses lifetime
    lifetime_income = 0.0
    for code, net in totals.items():
        acc = accounts.get(code)
        if not acc:
            continue
        t = acc["type"]
        if t == "asset":
            amt = round(net, 2)  # debit balance = +
            assets.append({"code": code, "name": acc["name"], "amount": amt, "subType": acc.get("subType")})
        elif t == "liability":
            amt = round(-net, 2)  # credit balance = +
            liabilities.append({"code": code, "name": acc["name"], "amount": amt, "subType": acc.get("subType")})
        elif t == "equity":
            amt = round(-net, 2)
            equity.append({"code": code, "name": acc["name"], "amount": amt, "subType": acc.get("subType")})
        elif t == "revenue":
            lifetime_income += -net
        elif t == "expense":
            lifetime_income -= net

    retained_earnings = round(lifetime_income, 2)
    equity.append({"code": "3999", "name": "Current Period Earnings (calculated)", "amount": retained_earnings, "subType": "calculated"})

    total_assets = round(sum(a["amount"] for a in assets), 2)
    total_liabilities = round(sum(l["amount"] for l in liabilities), 2)
    total_equity = round(sum(e["amount"] for e in equity), 2)

    return {
        "asOf": as_of or datetime.now(timezone.utc).date().isoformat(),
        "assets": sorted(assets, key=lambda r: r["code"]),
        "liabilities": sorted(liabilities, key=lambda r: r["code"]),
        "equity": sorted(equity, key=lambda r: r["code"]),
        "totalAssets": total_assets,
        "totalLiabilities": total_liabilities,
        "totalEquity": total_equity,
        "totalLiabilitiesAndEquity": round(total_liabilities + total_equity, 2),
        "balanced": abs(total_assets - (total_liabilities + total_equity)) < 0.05,
    }


async def cash_flow(from_date: str, to_date: str, business_id: Optional[str] = None) -> Dict[str, Any]:
    """Direct method — sum debits/credits against bank accounts in the period."""
    if business_id is None:
        business_id = get_actor_context().get("businessId")
    bank_query = {"$and": [tenant_scope_filter(business_id), {"isBank": True}]}
    bank_codes = [a["code"] async for a in db.accounts.find(bank_query, {"code": 1})]
    if not bank_codes:
        return {"from": from_date, "to": to_date, "inflows": [], "outflows": [],
                "netCash": 0.0, "openingBalance": 0.0, "closingBalance": 0.0}

    pipeline = [
        {"$match": {"$and": [{"posted": True, "date": {"$gte": from_date, "$lte": to_date}},
                              tenant_scope_filter(business_id)]}},
        {"$unwind": "$lines"},
        {"$match": {"lines.accountCode": {"$in": bank_codes}}},
        {"$project": {
            "sourceType": 1,
            "memo": 1,
            "accountCode": "$lines.accountCode",
            "amount": {"$subtract": ["$lines.debit", "$lines.credit"]},
        }},
        {"$group": {
            "_id": "$sourceType",
            "amount": {"$sum": "$amount"},
        }},
        {"$sort": {"_id": 1}},
    ]
    rows = await db.journal_entries.aggregate(pipeline).to_list(200)
    inflows = [{"category": r["_id"] or "manual", "amount": round(float(r["amount"]), 2)} for r in rows if float(r["amount"]) > 0]
    outflows = [{"category": r["_id"] or "manual", "amount": round(-float(r["amount"]), 2)} for r in rows if float(r["amount"]) < 0]
    net = round(sum(i["amount"] for i in inflows) - sum(o["amount"] for o in outflows), 2)

    # Opening balance = bank totals before from_date
    opening_totals = await _account_totals_between(None, from_date, business_id)
    opening = round(sum(opening_totals.get(c, 0) for c in bank_codes), 2)
    closing = round(opening + net, 2)
    return {
        "from": from_date, "to": to_date,
        "inflows": inflows,
        "outflows": outflows,
        "netCash": net,
        "openingBalance": opening,
        "closingBalance": closing,
    }


async def general_ledger(account_code: str, from_date: Optional[str] = None, to_date: Optional[str] = None,
                          business_id: Optional[str] = None) -> Dict[str, Any]:
    if business_id is None:
        business_id = get_actor_context().get("businessId")
    match: Dict[str, Any] = {"posted": True, "lines.accountCode": account_code}
    if from_date or to_date:
        match["date"] = {}
        if from_date: match["date"]["$gte"] = from_date
        if to_date:   match["date"]["$lte"] = to_date
        if not match["date"]:
            match.pop("date")
    match = {"$and": [match, tenant_scope_filter(business_id)]}
    pipeline = [
        {"$match": match},
        {"$sort": {"date": 1, "journalNumber": 1}},
    ]
    entries = await db.journal_entries.aggregate(pipeline).to_list(2000)
    rows = []
    running = 0.0
    for e in entries:
        for l in e["lines"]:
            if l.get("accountCode") != account_code:
                continue
            d = float(l.get("debit") or 0)
            c = float(l.get("credit") or 0)
            running += (d - c)
            rows.append({
                "date": e["date"],
                "journalNumber": e.get("journalNumber"),
                "journalId": e["id"],
                "sourceType": e.get("sourceType"),
                "sourceRef": e.get("sourceRef"),
                "memo": e.get("memo") or l.get("description") or "",
                "debit": round(d, 2),
                "credit": round(c, 2),
                "balance": round(running, 2),
            })
    acc_query = {"$and": [tenant_scope_filter(business_id), {"code": account_code}]}
    acc = await db.accounts.find_one(acc_query, {"_id": 0}) or {"code": account_code}
    return {"account": acc, "rows": rows, "closingBalance": round(running, 2)}


# ═════════════════════════════════════════════════════════════════════════
# Auto-posting hooks — called from other modules
# ═════════════════════════════════════════════════════════════════════════
async def auto_post_pos_sale(txn: Dict[str, Any], business_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """POS transaction (cash/card) → Bank DR, Sales CR, Surcharge CR, Gratuity CR, GST CR.

    `total` is GST-inclusive (menu prices already include GST) and already
    contains any auto-surcharge and auto-gratuity. `gst` is the 1/11th
    component within `total`, not an amount added on top of it — so the
    non-GST portion of `total` (`total - gst`) is split between Sales,
    Surcharge revenue, and Gratuities Payable in proportion to each one's
    share of the pre-GST net, and the discount is grossed back onto Sales at
    its GST-exclusive value. Gratuity is a liability, not revenue — it's
    money owed out to staff, not money the business earned.
    """
    if business_id is None:
        # The Square/Connect sync path calls this with no request/actor
        # context at all (a background sync job, not a staff request), but
        # already stamps businessId onto the transaction it built — prefer
        # that over the (empty) actor-context default in that case.
        business_id = txn.get("businessId") or get_actor_context().get("businessId")
    total = float(txn.get("total") or 0)
    if total <= 0:
        return None
    gst = float(txn.get("gst") or 0)
    discount = float(txn.get("discountAmount") or 0)
    surcharge = float(txn.get("surchargeAmount") or 0)
    gratuity = float(txn.get("gratuityAmount") or 0)

    net_of_gst_total = round(total - gst, 2)
    surcharge_share = (surcharge / total) if total > 0 else 0
    gratuity_share = (gratuity / total) if total > 0 else 0
    surcharge_net = round(net_of_gst_total * surcharge_share, 2)
    gratuity_net = round(net_of_gst_total * gratuity_share, 2)
    sales_net = round(net_of_gst_total - surcharge_net - gratuity_net, 2)  # remainder — keeps the entry exactly balanced
    gross_sales = round(sales_net + discount, 2)

    method = (txn.get("paymentMethod") or "").lower()
    bank_code = "1010" if "cash" in method else "1000"

    lines = [
        {"accountCode": bank_code, "debit": total, "credit": 0.0, "description": f"POS sale #{txn.get('id')}"},
    ]
    if discount > 0:
        lines.append({"accountCode": "4090", "debit": discount, "credit": 0.0, "description": "Sales discounts (vouchers/loyalty)"})
    lines.append({"accountCode": "4000", "debit": 0.0, "credit": gross_sales, "description": "Sales revenue"})
    if surcharge_net > 0:
        lines.append({"accountCode": "4040", "debit": 0.0, "credit": surcharge_net, "description": txn.get("surchargeReason") or "Surcharge revenue"})
    if gratuity_net > 0:
        lines.append({"accountCode": "2410", "debit": 0.0, "credit": gratuity_net, "description": txn.get("gratuityLabel") or "Auto-gratuity"})
    if gst > 0:
        lines.append({"accountCode": "2100", "debit": 0.0, "credit": gst, "description": "GST on sales (incl.)"})
    return await post_entry(
        lines,
        entry_date=(txn.get("timestamp") or datetime.now(timezone.utc).isoformat())[:10],
        memo=f"POS sale — {txn.get('paymentMethod')}",
        reference=txn.get("receiptNumber") or txn.get("id"),
        source_type="pos_sale",
        source_ref=txn.get("id"),
        business_id=business_id,
    )


async def auto_post_refund(refund: Dict[str, Any], business_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Refund → reverse sale side."""
    amount = float(refund.get("amount") or 0)
    if amount <= 0:
        return None
    # crude GST unwind: 1/11th portion (AU standard)
    gst = round(amount / 11.0, 2)
    net = round(amount - gst, 2)
    method = (refund.get("refundMethod") or "").lower()
    bank_code = "1010" if "cash" in method else "1000"
    lines = [
        {"accountCode": "4000",    "debit": net, "credit": 0.0, "description": "Refund — reverse sale"},
        {"accountCode": "2100",    "debit": gst, "credit": 0.0, "description": "Refund — reverse GST"},
        {"accountCode": bank_code, "debit": 0.0, "credit": amount, "description": f"Refund #{refund.get('id')}"},
    ]
    return await post_entry(
        lines,
        entry_date=(refund.get("timestamp") or datetime.now(timezone.utc).isoformat())[:10],
        memo=f"Refund — {refund.get('reason', '')}",
        source_type="refund",
        source_ref=refund.get("id"),
        business_id=business_id,
    )


async def auto_post_gift_card_sale(sale: Dict[str, Any], business_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Gift card sold → Bank DR, Gift Card Liability CR."""
    amount = float(sale.get("amount") or 0)
    if amount <= 0:
        return None
    lines = [
        {"accountCode": "1000", "debit": amount, "credit": 0.0, "description": f"Gift card sold #{sale.get('id')}"},
        {"accountCode": "2300", "debit": 0.0, "credit": amount, "description": "Gift card liability"},
    ]
    return await post_entry(
        lines,
        entry_date=(sale.get("issuedAt") or datetime.now(timezone.utc).isoformat())[:10],
        memo="Gift card issued",
        source_type="gift_card_sale",
        source_ref=sale.get("id"),
        business_id=business_id,
    )


async def auto_post_voucher_redeem(redeem: Dict[str, Any], business_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Voucher redeemed against a sale → Voucher Liability DR, Sales CR."""
    amount = float(redeem.get("amount") or 0)
    if amount <= 0:
        return None
    lines = [
        {"accountCode": "2310", "debit": amount, "credit": 0.0, "description": "Voucher redeemed"},
        {"accountCode": "4000", "debit": 0.0, "credit": amount, "description": "Sales via voucher"},
    ]
    return await post_entry(
        lines,
        entry_date=(redeem.get("timestamp") or datetime.now(timezone.utc).isoformat())[:10],
        memo="Voucher redeem",
        source_type="voucher_redeem",
        source_ref=redeem.get("id"),
        business_id=business_id,
    )


async def auto_post_bill(bill: Dict[str, Any], business_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """AP bill received → Expense/GST Paid DR, Accounts Payable CR."""
    total = float(bill.get("total") or 0)
    if total <= 0:
        return None
    gst = float(bill.get("gst") or 0)
    net = round(total - gst, 2)
    lines = []
    # If bill has line-level accountCode splits, use them; else fall back to Misc.
    line_items = bill.get("lines") or []
    if line_items and all(li.get("accountCode") for li in line_items):
        for li in line_items:
            lines.append({"accountCode": li["accountCode"], "debit": float(li.get("amount") or 0),
                          "credit": 0.0, "description": li.get("description", "")})
    else:
        lines.append({"accountCode": "6900", "debit": net, "credit": 0.0, "description": bill.get("description") or "Bill expense"})
    if gst > 0:
        lines.append({"accountCode": "2110", "debit": gst, "credit": 0.0, "description": "GST paid"})
    lines.append({"accountCode": "2000", "debit": 0.0, "credit": total,
                  "description": f"Bill {bill.get('billNumber') or bill.get('id')}",
                  "contactId": bill.get("supplierId")})
    return await post_entry(
        lines,
        entry_date=bill.get("issueDate") or datetime.now(timezone.utc).date().isoformat(),
        memo=f"Bill {bill.get('billNumber') or ''} — {bill.get('supplierName') or ''}".strip(),
        source_type="ap_bill",
        source_ref=bill.get("id"),
        business_id=business_id,
    )


async def auto_post_bill_payment(payment: Dict[str, Any], business_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """AP payment → Accounts Payable DR, Bank CR."""
    amount = float(payment.get("amount") or 0)
    if amount <= 0:
        return None
    lines = [
        {"accountCode": "2000", "debit": amount, "credit": 0.0, "description": f"Payment for bill {payment.get('billId')}",
         "contactId": payment.get("supplierId")},
        {"accountCode": "1000", "debit": 0.0, "credit": amount, "description": f"Bill payment #{payment.get('id')}"},
    ]
    return await post_entry(
        lines,
        entry_date=payment.get("paidAt") or datetime.now(timezone.utc).date().isoformat(),
        memo=f"AP payment — bill {payment.get('billId')}",
        source_type="ap_payment",
        source_ref=payment.get("id"),
        business_id=business_id,
    )


async def auto_post_invoice(invoice: Dict[str, Any], business_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """AR invoice → AR DR, Sales CR, GST Collected CR."""
    total = float(invoice.get("total") or 0)
    if total <= 0:
        return None
    gst = float(invoice.get("gst") or 0)
    net = round(total - gst, 2)
    lines = [
        {"accountCode": "1100", "debit": total, "credit": 0.0, "description": f"Invoice {invoice.get('invoiceNumber') or invoice.get('id')}",
         "contactId": invoice.get("customerId")},
        {"accountCode": "4030", "debit": 0.0, "credit": net, "description": "AR revenue"},
    ]
    if gst > 0:
        lines.append({"accountCode": "2100", "debit": 0.0, "credit": gst, "description": "GST on invoice"})
    return await post_entry(
        lines,
        entry_date=invoice.get("issueDate") or datetime.now(timezone.utc).date().isoformat(),
        memo=f"Invoice {invoice.get('invoiceNumber') or ''} — {invoice.get('customerName') or ''}".strip(),
        source_type="ar_invoice",
        source_ref=invoice.get("id"),
        business_id=business_id,
    )


async def auto_post_invoice_receipt(receipt: Dict[str, Any], business_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    amount = float(receipt.get("amount") or 0)
    if amount <= 0:
        return None
    lines = [
        {"accountCode": "1000", "debit": amount, "credit": 0.0, "description": f"Receipt for {receipt.get('invoiceId')}"},
        {"accountCode": "1100", "debit": 0.0, "credit": amount, "description": "AR settled",
         "contactId": receipt.get("customerId")},
    ]
    return await post_entry(
        lines,
        entry_date=receipt.get("receivedAt") or datetime.now(timezone.utc).date().isoformat(),
        memo=f"AR receipt — invoice {receipt.get('invoiceId')}",
        source_type="ar_receipt",
        source_ref=receipt.get("id"),
        business_id=business_id,
    )


async def auto_post_payroll_run(run: Dict[str, Any], business_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Payroll run summary → Wages Expense DR, PAYG CR, Super CR, Bank CR (net)."""
    gross = float(run.get("gross") or 0)
    payg = float(run.get("payg") or 0)
    super_amt = float(run.get("super") or 0)
    net = round(gross - payg, 2)
    if gross <= 0:
        return None
    lines = [
        {"accountCode": "6000", "debit": gross,     "credit": 0.0, "description": f"Wages — pay run {run.get('id')}"},
        {"accountCode": "6010", "debit": super_amt, "credit": 0.0, "description": "Super expense"},
        {"accountCode": "2200", "debit": 0.0, "credit": payg,     "description": "PAYG withholding"},
        {"accountCode": "2210", "debit": 0.0, "credit": super_amt, "description": "Super payable"},
        {"accountCode": "1000", "debit": 0.0, "credit": net,      "description": "Wages paid"},
    ]
    return await post_entry(
        lines,
        entry_date=run.get("payDate") or datetime.now(timezone.utc).date().isoformat(),
        memo=f"Payroll run {run.get('id')}",
        source_type="payroll_run",
        source_ref=run.get("id"),
        business_id=business_id,
    )


async def auto_post_customer_deposit(deposit: Dict[str, Any], business_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Customer deposit received → Bank DR, Customer Deposits Held CR."""
    amount = float(deposit.get("amount") or 0)
    if amount <= 0:
        return None
    lines = [
        {"accountCode": "1000", "debit": amount, "credit": 0.0, "description": f"Deposit from {deposit.get('customerName')}"},
        {"accountCode": "2320", "debit": 0.0, "credit": amount, "description": "Held deposit",
         "contactId": deposit.get("customerId")},
    ]
    return await post_entry(
        lines,
        entry_date=deposit.get("receivedAt") or datetime.now(timezone.utc).date().isoformat(),
        memo=f"Customer deposit — {deposit.get('bookingId') or ''}",
        source_type="deposit",
        source_ref=deposit.get("id"),
        business_id=business_id,
    )


async def auto_post_deposit_applied(deposit: Dict[str, Any], transaction: Dict[str, Any],
                                     business_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    amount = float(deposit.get("amount") or 0)
    if amount <= 0:
        return None
    lines = [
        {"accountCode": "2320", "debit": amount, "credit": 0.0, "description": "Deposit applied",
         "contactId": deposit.get("customerId")},
        {"accountCode": "4030", "debit": 0.0, "credit": amount, "description": "Deposit realised as revenue"},
    ]
    return await post_entry(
        lines,
        entry_date=datetime.now(timezone.utc).date().isoformat(),
        memo=f"Deposit applied to txn {transaction.get('id')}",
        source_type="deposit_applied",
        source_ref=deposit.get("id"),
        business_id=business_id,
    )


async def auto_post_deposit_refunded(deposit: Dict[str, Any], business_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Held deposit paid back to the customer (booking fell through) → Held
    deposit liability DR, Bank CR. Mirrors auto_post_deposit_applied's
    liability release but the money leaves the business instead of
    becoming revenue."""
    amount = float(deposit.get("amount") or 0)
    if amount <= 0:
        return None
    lines = [
        {"accountCode": "2320", "debit": amount, "credit": 0.0, "description": "Deposit refunded",
         "contactId": deposit.get("customerId")},
        {"accountCode": "1000", "debit": 0.0, "credit": amount, "description": f"Refund to {deposit.get('customerName')}"},
    ]
    return await post_entry(
        lines,
        entry_date=datetime.now(timezone.utc).date().isoformat(),
        memo=f"Deposit refunded — {deposit.get('bookingId') or ''}",
        source_type="deposit_refunded",
        source_ref=deposit.get("id"),
        business_id=business_id,
    )
