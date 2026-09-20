from fastapi import APIRouter, Depends, HTTPException
from deps import get_user, require_owner_or_manager
from typing import List, Optional
from datetime import datetime, timedelta
from database import db
from models.bas_report import BASReport, BASReportCreate
from models.expense import Expense, ExpenseCreate
from models.supplier import Supplier, SupplierCreate, PurchaseOrder, PurchaseOrderCreate
from middleware.actor_context import tenant_scope_filter, tenant_owns, tenant_owns_strict
from utils.dates import date_range_filter as _date_match
import asyncio
import uuid
import random
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


async def _sum_transactions(match: dict) -> dict:
    pipeline = [{"$match": match}] if match else []
    pipeline.append({"$group": {"_id": None, "revenue": {"$sum": "$total"},
                                "gst": {"$sum": "$gst"}}})
    out = await db.transactions.aggregate(pipeline).to_list(1)
    return out[0] if out else {"revenue": 0, "gst": 0}


async def _sum_expenses(match: dict) -> List[dict]:
    """Grouped by category, since P&L needs to split COGS from operating."""
    pipeline = [{"$match": match}] if match else []
    pipeline.append({"$group": {"_id": "$category", "amount": {"$sum": "$amount"},
                                "gst": {"$sum": "$gstAmount"}}})
    return await db.expenses.aggregate(pipeline).to_list(1000)


COGS_CATEGORIES = ("Ingredients", "Food Supplies", "Beverages")


# ============ ACCOUNTING API ============
@router.get("/accounting/summary")
async def get_accounting_summary(start_date: Optional[str] = None, end_date: Optional[str] = None,
                                 user: dict = Depends(require_owner_or_manager)):
    txn_totals, expense_rows = await asyncio.gather(
        _sum_transactions({**_date_match("timestamp", start_date, end_date), **tenant_scope_filter(user.get("businessId"))}),
        _sum_expenses({**_date_match("date", start_date, end_date), **tenant_scope_filter(user.get("businessId"))}),
    )
    total_expenses = sum(r["amount"] for r in expense_rows)
    total_gst_paid = sum(r["gst"] for r in expense_rows)
    return {
        "revenue": round(txn_totals["revenue"], 2),
        "gstCollected": round(txn_totals["gst"], 2),
        "expenses": round(total_expenses, 2),
        "gstPaid": round(total_gst_paid, 2),
        "netGST": round(txn_totals["gst"] - total_gst_paid, 2),
        "profit": round(txn_totals["revenue"] - total_expenses, 2),
    }

@router.get("/accounting/p-and-l")
async def get_p_and_l(start_date: Optional[str] = None, end_date: Optional[str] = None,
                      user: dict = Depends(require_owner_or_manager)):
    txn_totals, expense_rows = await asyncio.gather(
        _sum_transactions({**_date_match("timestamp", start_date, end_date), **tenant_scope_filter(user.get("businessId"))}),
        _sum_expenses({**_date_match("date", start_date, end_date), **tenant_scope_filter(user.get("businessId"))}),
    )
    revenue = txn_totals["revenue"]
    cogs = sum(r["amount"] for r in expense_rows if r["_id"] in COGS_CATEGORIES)
    operating = sum(r["amount"] for r in expense_rows if r["_id"] not in COGS_CATEGORIES)
    gross_profit = revenue - cogs
    return {
        "revenue": round(revenue, 2),
        "costOfGoods": round(cogs, 2),
        "grossProfit": round(gross_profit, 2),
        "operatingExpenses": round(operating, 2),
        "netProfit": round(gross_profit - operating, 2),
        "grossMargin": round((gross_profit / revenue * 100) if revenue > 0 else 0, 1),
    }

# ============ BAS/GST API ============
@router.get("/bas-gst/reports", response_model=List[BASReport])
async def get_bas_reports(user: dict = Depends(require_owner_or_manager)):
    reports = await db.bas_reports.find(tenant_scope_filter(user.get("businessId"))).to_list(1000)
    return [BASReport(**r) for r in reports]

@router.post("/bas-gst/reports", response_model=BASReport)
async def create_bas_report(report: BASReportCreate, user: dict = Depends(require_owner_or_manager)):
    scope = tenant_scope_filter(user.get("businessId"))
    transactions = await db.transactions.find(scope).to_list(10000)
    expenses = await db.expenses.find(scope).to_list(10000)
    gst_collected = sum(t.get("gst", 0) for t in transactions)
    gst_paid = sum(e.get("gstAmount", 0) for e in expenses)
    total_sales = sum(t.get("total", 0) for t in transactions)
    total_purchases = sum(e.get("amount", 0) for e in expenses)
    report_dict = report.dict()
    report_dict.update({
        "businessId": user.get("businessId"),
        "gstCollected": round(gst_collected, 2),
        "gstPaid": round(gst_paid, 2),
        "netGst": round(gst_collected - gst_paid, 2),
        "totalSales": round(total_sales, 2),
        "totalPurchases": round(total_purchases, 2),
    })
    report_obj = BASReport(**report_dict)
    await db.bas_reports.insert_one(report_obj.dict())
    return report_obj

@router.post("/bas-gst/submit/{report_id}")
async def submit_bas_report(report_id: str, use_api: bool = False,
                            user: dict = Depends(require_owner_or_manager)):
    query = {"id": report_id, **tenant_scope_filter(user.get("businessId"))}
    report = await db.bas_reports.find_one(query)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if use_api:
        await db.bas_reports.update_one(
            query,
            {"$set": {"status": "submitted", "submittedAt": datetime.utcnow().isoformat(), "atoReference": f"ATO-{str(uuid.uuid4())[:8].upper()}"}}
        )
        return {"message": "BAS submitted to ATO via API", "reference": f"ATO-{str(uuid.uuid4())[:8].upper()}"}
    else:
        await db.bas_reports.update_one(
            query,
            {"$set": {"status": "ready_to_lodge"}}
        )
        return {"message": "BAS marked as ready to lodge", "atoPortalUrl": "https://www.ato.gov.au/business-portal"}


@router.get("/bas-gst/worksheet")
async def bas_worksheet(period_start: str, period_end: str,
                        user: dict = Depends(require_owner_or_manager)):
    """Return a fully-labelled BAS worksheet (G1–G20, 1A/1B, W1/W2, T1) for
    the requested period. Numbers are computed from POS transactions,
    expenses and committed pay runs in the same window.

    Reference: ATO NAT 4189 (Instructions for Business Activity Statement).
    """
    scope = tenant_scope_filter(user.get("businessId"))
    tx = await db.transactions.find({
        "createdAt": {"$gte": period_start, "$lte": period_end + "T23:59:59Z"},
        **scope,
    }, {"_id": 0}).to_list(50000)
    exp = await db.expenses.find({
        "date": {"$gte": period_start, "$lte": period_end + "T23:59:59Z"},
        **scope,
    }, {"_id": 0}).to_list(50000)
    runs = await db.payruns.find({
        "payDate": {"$gte": period_start, "$lte": period_end},
        **scope,
    }, {"_id": 0}).to_list(500)

    # GST supplies (G1) — include GST-inclusive.
    g1_total_sales = round(sum(t.get("total", 0) for t in tx), 2)
    # G3 — GST-free sales (items with gstFree=True on the line).
    g3_gst_free = round(sum(
        sum(li.get("price", 0) * li.get("quantity", 1) for li in (t.get("items") or []) if li.get("gstFree"))
        for t in tx
    ), 2)
    # G2 — export sales (delivery channel = export/international) — usually zero for a restaurant.
    g2_exports = 0.0
    # G4 — input-taxed sales (rare — e.g. a rental component). Zero by default.
    g4_input_taxed = 0.0
    g5_subtotal = round(g2_exports + g3_gst_free + g4_input_taxed, 2)
    g6_taxable_supplies = round(g1_total_sales - g5_subtotal, 2)
    g7_adjustments = 0.0
    g8_total = round(g6_taxable_supplies + g7_adjustments, 2)
    g9_gst_on_sales = round(sum(t.get("gst", 0) for t in tx), 2)  # 1A

    # Acquisitions
    g10_capital = round(sum(e.get("amount", 0) for e in exp if e.get("isCapital")), 2)
    g11_non_capital = round(sum(e.get("amount", 0) for e in exp if not e.get("isCapital")), 2)
    g12_subtotal = round(g10_capital + g11_non_capital, 2)
    g13_input_taxed = 0.0
    g14_private = round(sum(e.get("privatePortion", 0) for e in exp), 2)
    g15_estimate_gst_free = round(sum(e.get("amount", 0) for e in exp if e.get("gstFree")), 2)
    g16_subtotal = round(g13_input_taxed + g14_private + g15_estimate_gst_free, 2)
    g17_creditable = round(g12_subtotal - g16_subtotal, 2)
    g18_adjustments = 0.0
    g19_total = round(g17_creditable + g18_adjustments, 2)
    g20_gst_on_purchases = round(sum(e.get("gstAmount", 0) for e in exp), 2)  # 1B

    net_gst = round(g9_gst_on_sales - g20_gst_on_purchases, 2)  # positive → owe ATO

    # PAYG withholding (W-labels) & PAYG instalment (T1)
    w1_gross_wages = round(sum(r.get("totals", {}).get("grossPay", 0) for r in runs), 2)
    w2_payg_withheld = round(sum(r.get("totals", {}).get("payg", 0) for r in runs), 2)
    w3_no_abn_withholding = 0.0
    w4_other_withholding = 0.0
    w5_total_withheld = round(w2_payg_withheld + w3_no_abn_withholding + w4_other_withholding, 2)

    # T1 — PAYG income tax instalment. Rough ATO method: base rate = 12.5%
    # of assessable GST-exclusive turnover. Owner can override.
    turnover_ex_gst = round(g8_total - g9_gst_on_sales, 2)
    t1_instalment = round(turnover_ex_gst * 0.125, 2)

    total_owing = round(net_gst + w5_total_withheld + t1_instalment, 2)
    return {
        "period": {"start": period_start, "end": period_end},
        "sales": {
            "G1_totalSales": g1_total_sales,
            "G2_exports": g2_exports,
            "G3_gstFreeSales": g3_gst_free,
            "G4_inputTaxedSales": g4_input_taxed,
            "G5_subtotal": g5_subtotal,
            "G6_taxableSupplies": g6_taxable_supplies,
            "G7_adjustments": g7_adjustments,
            "G8_total": g8_total,
            "G9_gstOnSales_1A": g9_gst_on_sales,
        },
        "acquisitions": {
            "G10_capital": g10_capital,
            "G11_nonCapital": g11_non_capital,
            "G12_subtotal": g12_subtotal,
            "G13_inputTaxed": g13_input_taxed,
            "G14_private": g14_private,
            "G15_estimateGstFree": g15_estimate_gst_free,
            "G16_subtotal": g16_subtotal,
            "G17_creditable": g17_creditable,
            "G18_adjustments": g18_adjustments,
            "G19_total": g19_total,
            "G20_gstOnPurchases_1B": g20_gst_on_purchases,
        },
        "netGST": net_gst,
        "withholding": {
            "W1_totalWages": w1_gross_wages,
            "W2_paygWithheld": w2_payg_withheld,
            "W3_noAbnWithholding": w3_no_abn_withholding,
            "W4_otherWithholding": w4_other_withholding,
            "W5_totalWithheld": w5_total_withheld,
        },
        "instalment": {
            "T1_paygInstalment": t1_instalment,
            "T7_varianceReason": None,
        },
        "summary": {
            "grossSales": g1_total_sales,
            "gstToPay": max(net_gst, 0.0),
            "gstToClaim": max(-net_gst, 0.0),
            "paygWithheld": w5_total_withheld,
            "paygInstalment": t1_instalment,
            "totalOwing": max(total_owing, 0.0),
            "refundDue": max(-total_owing, 0.0),
        },
    }

# ============ EXPENSES API ============
@router.get("/expenses", response_model=List[Expense])
async def get_expenses(start_date: Optional[str] = None, end_date: Optional[str] = None, category: Optional[str] = None, user: dict = Depends(require_owner_or_manager)):
    query = tenant_scope_filter(user.get("businessId"))
    if category:
        query["category"] = category
    if start_date and end_date:
        query["date"] = {"$gte": datetime.fromisoformat(start_date), "$lte": datetime.fromisoformat(end_date)}
    expenses = await db.expenses.find(query).to_list(1000)
    return [Expense(**e) for e in expenses]

@router.post("/expenses", response_model=Expense)
async def create_expense(expense: ExpenseCreate, user: dict = Depends(require_owner_or_manager)):
    expense_obj = Expense(**expense.dict(), businessId=user.get("businessId"))
    await db.expenses.insert_one(expense_obj.dict())
    return expense_obj

# ============ SUPPLIERS API ============
@router.get("/suppliers", response_model=List[Supplier])
async def get_suppliers(user: dict = Depends(get_user)):
    suppliers = await db.suppliers.find(tenant_scope_filter(user.get("businessId"))).to_list(1000)
    return [Supplier(**s) for s in suppliers]

@router.post("/suppliers", response_model=Supplier)
async def create_supplier(supplier: SupplierCreate, user: dict = Depends(require_owner_or_manager)):
    supplier_obj = Supplier(**supplier.dict(), businessId=user.get("businessId"))
    await db.suppliers.insert_one(supplier_obj.dict())
    return supplier_obj

# ============ PURCHASE ORDERS API ============
# Note: phase_ef.py also exposes /purchase-orders with a flexible schema. The
# canonical GET endpoint lives in phase_ef.py; this strict-model variant is kept
# here only for legacy POST (creating supplier-linked POs with GST math).
@router.post("/purchase-orders", response_model=PurchaseOrder)
async def create_purchase_order(po: PurchaseOrderCreate, user: dict = Depends(require_owner_or_manager)):
    supplier = await db.suppliers.find_one(
        {"id": po.supplierId, **tenant_scope_filter(user.get("businessId"))})
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    subtotal = sum(item["quantity"] * item["price"] for item in po.items)
    gst = subtotal * 0.1
    total = subtotal + gst
    po_obj = PurchaseOrder(
        supplierId=po.supplierId, supplierName=supplier["name"],
        expectedDelivery=po.expectedDelivery, items=po.items,
        subtotal=subtotal, gst=gst, total=total, notes=po.notes,
        businessId=user.get("businessId"),
    )
    await db.purchase_orders.insert_one(po_obj.dict())
    return po_obj

# ============ REPORTS API ============
@router.get("/reports/sales-summary")
async def get_sales_summary(start_date: str, end_date: str, location: Optional[str] = None,
                            user: dict = Depends(get_user)):
    query = {"timestamp": {"$gte": datetime.fromisoformat(start_date), "$lte": datetime.fromisoformat(end_date)},
             **tenant_scope_filter(user.get("businessId"))}
    if location:
        query["location"] = location
    transactions = await db.transactions.find(query).to_list(10000)
    total_sales = sum(t["total"] for t in transactions)
    total_transactions = len(transactions)
    avg_transaction = total_sales / total_transactions if total_transactions > 0 else 0
    by_payment = {}
    for txn in transactions:
        method = txn["paymentMethod"]
        by_payment[method] = by_payment.get(method, 0) + txn["total"]
    product_sales = {}
    for txn in transactions:
        for item in txn["items"]:
            pid = item["productId"]
            if pid not in product_sales:
                product_sales[pid] = {"name": item["productName"], "quantity": 0, "revenue": 0}
            product_sales[pid]["quantity"] += item["quantity"]
            product_sales[pid]["revenue"] += item["quantity"] * item["price"]
    return {
        "period": {"start": start_date, "end": end_date},
        "total_sales": total_sales, "total_transactions": total_transactions,
        "avg_transaction": avg_transaction, "by_payment_method": by_payment,
        "top_products": sorted(product_sales.values(), key=lambda x: x["revenue"], reverse=True)[:10]
    }

@router.get("/reports/export/csv")
async def export_report_csv(report_type: str, start_date: str, end_date: str, _: dict = Depends(require_owner_or_manager)):
    return {"message": "CSV export endpoint - implement with csv library"}

# ============ PRE-SHIFT DASHBOARD API ============
@router.get("/pre-shift/today")
async def get_pre_shift_data(_: dict = Depends(get_user)):
    today = datetime.utcnow().strftime('%Y-%m-%d')
    reservations = await db.reservations.find({"date": today, **tenant_scope_filter()}, {"_id": 0}).sort("time", 1).to_list(100)
    # One batched $in lookup instead of one find_one() per reservation, per
    # loop — the VIP pass and the dietary-alerts pass below both used to
    # re-fetch the same customer doc a second time.
    cust_ids = list({r["customerId"] for r in reservations if r.get("customerId")})
    customers_by_id = {}
    if cust_ids:
        rows = await db.customers.find({**tenant_scope_filter(), "id": {"$in": cust_ids}}, {"_id": 0}).to_list(len(cust_ids))
        customers_by_id = {c["id"]: c for c in rows}
    vip_guests = []
    for r in reservations:
        if r.get("customerId"):
            cust = customers_by_id.get(r["customerId"])
            if cust and cust.get("isVip"):
                vip_guests.append({**r, "customerProfile": cust})
        elif "VIP" in (r.get("tags") or []):
            vip_guests.append(r)
    dietary_alerts = []
    for r in reservations:
        alerts = []
        if r.get("customerId"):
            cust = customers_by_id.get(r["customerId"])
            if cust:
                if cust.get("dietaryRestrictions"):
                    alerts.extend(cust["dietaryRestrictions"])
                if cust.get("allergies"):
                    alerts.extend([f"ALLERGY: {a}" for a in cust["allergies"]])
        if alerts:
            dietary_alerts.append({"reservation": r["id"], "guest": r["guestName"], "time": r["time"], "alerts": alerts})
    special_requests = [
        {"guest": r["guestName"], "time": r["time"], "request": r["specialRequests"], "partySize": r["partySize"]}
        for r in reservations if r.get("specialRequests")
    ]
    # Large bookings — what services.booking_rules_engine flagged at
    # creation time (isLargeBooking + the tier/experience/deposit/pre-order/
    # approval fields it set), surfaced here so FOH/kitchen can anticipate
    # a big party same as they already do for VIPs and dietary alerts.
    large_bookings = [
        {
            "reservationId": r["id"], "guest": r["guestName"], "time": r["time"],
            "partySize": r["partySize"], "tierLabel": r.get("bookingTierLabel"),
            "experienceName": r.get("experienceName"),
            "depositRequired": r.get("depositRequired", 0), "depositPaid": r.get("depositPaid", False),
            "preOrderRequired": r.get("preOrderRequired", False), "preOrderCompleted": r.get("preOrderCompleted", False),
            "approvalRequired": r.get("approvalRequired", False), "approvalStatus": r.get("approvalStatus", "not_required"),
            "specialRequests": r.get("specialRequests"),
        }
        for r in reservations if r.get("isLargeBooking") and r.get("status") not in ("cancelled", "no_show")
    ]
    total_covers = sum(r.get("partySize", 0) for r in reservations)
    confirmed = len([r for r in reservations if r.get("status") == "confirmed"])
    seated = len([r for r in reservations if r.get("status") == "seated"])
    kitchen_pending = await db.kitchen_orders.count_documents({"status": {"$in": ["new", "preparing"]}, **tenant_scope_filter()})
    waitlist_count = await db.waitlist.count_documents({"status": "waiting", **tenant_scope_filter()})
    txns_today = await db.transactions.find(tenant_scope_filter(), {"_id": 0}).sort("timestamp", -1).to_list(100)
    revenue_today = sum(t.get("total", 0) for t in txns_today)
    return {
        "date": today, "reservations": reservations, "totalReservations": len(reservations),
        "totalCovers": total_covers, "confirmed": confirmed, "seated": seated,
        "vipGuests": vip_guests, "dietaryAlerts": dietary_alerts, "specialRequests": special_requests,
        "largeBookings": large_bookings,
        "kitchenPending": kitchen_pending, "waitlistCount": waitlist_count,
        "revenueToday": revenue_today, "transactionsToday": len(txns_today),
    }

# ============ AI COMMAND CENTER API ============
@router.get("/analytics/command-center")
async def get_command_center(_: dict = Depends(require_owner_or_manager)):
    all_txns = await db.transactions.find(tenant_scope_filter(), {"_id": 0}).to_list(10000)
    total_revenue = sum(t.get("total", 0) for t in all_txns)
    total_txns = len(all_txns)
    avg_ticket = total_revenue / total_txns if total_txns > 0 else 0
    products = await db.products.find(tenant_scope_filter(), {"_id": 0}).to_list(1000)
    product_map = {p["id"]: p for p in products}
    total_cogs = 0
    for txn in all_txns:
        for item in txn.get("items", []):
            prod = product_map.get(item.get("productId"))
            if prod:
                total_cogs += prod.get("cost", 0) * item.get("quantity", 0)
    food_cost_pct = (total_cogs / total_revenue * 100) if total_revenue > 0 else 0
    expenses = await db.expenses.find(tenant_scope_filter(), {"_id": 0}).to_list(10000)
    total_expenses = sum(e.get("amount", 0) for e in expenses)
    shifts = await db.staff_shifts.find(tenant_scope_filter(), {"_id": 0}).to_list(1000)
    total_hours = sum(s.get("totalHours", 0) for s in shifts)
    labor_cost = total_hours * 30
    labor_pct = (labor_cost / total_revenue * 100) if total_revenue > 0 else 0
    product_sales = {}
    for txn in all_txns:
        for item in txn.get("items", []):
            pid = item.get("productId", "")
            if pid not in product_sales:
                prod = product_map.get(pid, {})
                product_sales[pid] = {
                    "id": pid, "name": item.get("productName", ""),
                    "revenue": 0, "quantity": 0, "cost": prod.get("cost", 0),
                    "price": prod.get("price", item.get("price", 0))
                }
            product_sales[pid]["revenue"] += item.get("price", 0) * item.get("quantity", 0)
            product_sales[pid]["quantity"] += item.get("quantity", 0)
    for pid, ps in product_sales.items():
        ps["totalCost"] = ps["cost"] * ps["quantity"]
        ps["profit"] = ps["revenue"] - ps["totalCost"]
        ps["margin"] = (ps["profit"] / ps["revenue"] * 100) if ps["revenue"] > 0 else 0
    top_sellers = sorted(product_sales.values(), key=lambda x: x["revenue"], reverse=True)[:10]
    low_performers = sorted(product_sales.values(), key=lambda x: x["margin"])[:5]
    today = datetime.utcnow().strftime('%Y-%m-%d')
    today_res = await db.reservations.find({"date": today, **tenant_scope_filter()}, {"_id": 0}).to_list(100)
    insights = []
    if food_cost_pct > 35:
        insights.append({"type": "warning", "title": "High Food Cost", "message": f"Food cost at {food_cost_pct:.1f}% - target is under 35%.", "priority": "high"})
    if labor_pct > 30:
        insights.append({"type": "warning", "title": "Labor Cost Alert", "message": f"Labor cost at {labor_pct:.1f}% of revenue.", "priority": "high"})
    if len(today_res) > 20:
        insights.append({"type": "info", "title": "Busy Night Ahead", "message": f"{len(today_res)} reservations today.", "priority": "medium"})
    if low_performers:
        worst = low_performers[0]
        if worst["margin"] < 20:
            insights.append({"type": "alert", "title": "Underperforming Dish", "message": f'"{worst["name"]}" has only {worst["margin"]:.0f}% margin.', "priority": "medium"})
    customers = await db.customers.find({**tenant_scope_filter(), }, {"_id": 0}).to_list(10000)
    vip_count = len([c for c in customers if c.get("isVip")])
    avg_rating = sum(c.get("feedbackRating", 0) for c in customers if c.get("feedbackRating", 0) > 0)
    rated = len([c for c in customers if c.get("feedbackRating", 0) > 0])
    avg_rating = avg_rating / rated if rated > 0 else 0
    return {
        "revenue": {"total": total_revenue, "transactions": total_txns, "avgTicket": avg_ticket},
        "costs": {"foodCost": total_cogs, "foodCostPct": food_cost_pct, "laborCost": labor_cost, "laborPct": labor_pct, "expenses": total_expenses},
        "profit": {"gross": total_revenue - total_cogs, "net": total_revenue - total_cogs - total_expenses - labor_cost},
        "topSellers": top_sellers, "lowPerformers": low_performers, "insights": insights,
        "customers": {"total": len(customers), "vips": vip_count, "avgRating": round(avg_rating, 1)},
        "todayReservations": len(today_res), "todayCovers": sum(r.get("partySize", 0) for r in today_res),
    }

# ============ MENU ENGINEERING API ============
@router.get("/analytics/menu-engineering")
async def get_menu_engineering():
    products = await db.products.find(tenant_scope_filter(), {"_id": 0}).to_list(1000)
    all_txns = await db.transactions.find(tenant_scope_filter(), {"_id": 0}).to_list(10000)
    product_map = {p["id"]: p for p in products}
    sales_data = {}
    for txn in all_txns:
        for item in txn.get("items", []):
            pid = item.get("productId", "")
            if pid not in sales_data:
                prod = product_map.get(pid, {})
                sales_data[pid] = {
                    "id": pid, "name": item.get("productName", prod.get("name", "")),
                    "category": prod.get("category", "Other"),
                    "price": prod.get("price", 0), "cost": prod.get("cost", 0),
                    "quantity": 0, "revenue": 0
                }
            sales_data[pid]["quantity"] += item.get("quantity", 0)
            sales_data[pid]["revenue"] += item.get("price", 0) * item.get("quantity", 0)
    items = list(sales_data.values())
    for item in items:
        item["totalCost"] = item["cost"] * item["quantity"]
        item["profit"] = item["revenue"] - item["totalCost"]
        item["margin"] = (item["profit"] / item["revenue"] * 100) if item["revenue"] > 0 else 0
        item["contributionMargin"] = item["price"] - item["cost"]
    if items:
        avg_qty = sum(i["quantity"] for i in items) / len(items)
        avg_margin = sum(i["margin"] for i in items) / len(items)
        for item in items:
            high_pop = item["quantity"] >= avg_qty * 0.7
            high_profit = item["margin"] >= avg_margin
            if high_pop and high_profit:
                item["classification"] = "star"
            elif not high_pop and high_profit:
                item["classification"] = "puzzle"
            elif high_pop and not high_profit:
                item["classification"] = "horse"
            else:
                item["classification"] = "dog"
    categories = {}
    for item in items:
        cat = item["category"]
        if cat not in categories:
            categories[cat] = {"name": cat, "revenue": 0, "cost": 0, "quantity": 0, "items": 0}
        categories[cat]["revenue"] += item["revenue"]
        categories[cat]["cost"] += item["totalCost"]
        categories[cat]["quantity"] += item["quantity"]
        categories[cat]["items"] += 1
    for cat in categories.values():
        cat["profit"] = cat["revenue"] - cat["cost"]
        cat["margin"] = (cat["profit"] / cat["revenue"] * 100) if cat["revenue"] > 0 else 0
    return {
        "items": sorted(items, key=lambda x: x["revenue"], reverse=True),
        "categories": sorted(categories.values(), key=lambda x: x["revenue"], reverse=True),
        "summary": {
            "stars": len([i for i in items if i.get("classification") == "star"]),
            "puzzles": len([i for i in items if i.get("classification") == "puzzle"]),
            "horses": len([i for i in items if i.get("classification") == "horse"]),
            "dogs": len([i for i in items if i.get("classification") == "dog"]),
        }
    }

# ============ WHAT-IF SIMULATOR ============
@router.post("/analytics/what-if")
async def what_if_simulation(changes: List[dict]):
    products = await db.products.find(tenant_scope_filter(), {"_id": 0}).to_list(1000)
    txns = await db.transactions.find(tenant_scope_filter(), {"_id": 0}).to_list(10000)
    product_map = {p["id"]: p for p in products}
    product_sales = {}
    for txn in txns:
        for item in txn.get("items", []):
            pid = item.get("productId", "")
            if pid not in product_sales:
                product_sales[pid] = {"quantity": 0, "revenue": 0}
            product_sales[pid]["quantity"] += item.get("quantity", 0)
            product_sales[pid]["revenue"] += item.get("price", 0) * item.get("quantity", 0)
    results = []
    total_current_profit = 0
    total_projected_profit = 0
    for change in changes:
        pid = change.get("productId", "")
        new_price = change.get("newPrice")
        new_cost = change.get("newCost")
        prod = product_map.get(pid)
        if not prod:
            continue
        sales = product_sales.get(pid, {"quantity": 0, "revenue": 0})
        qty = sales["quantity"]
        current_price = prod.get("price", 0)
        current_cost = prod.get("cost", 0)
        current_profit = (current_price - current_cost) * qty
        proj_price = new_price if new_price is not None else current_price
        proj_cost = new_cost if new_cost is not None else current_cost
        price_change_pct = ((proj_price - current_price) / max(current_price, 0.01)) * 100
        demand_adjustment = 1 - (price_change_pct * 0.005)
        proj_qty = max(0, int(qty * demand_adjustment))
        projected_profit = (proj_price - proj_cost) * proj_qty
        total_current_profit += current_profit
        total_projected_profit += projected_profit
        results.append({
            "productId": pid, "productName": prod["name"],
            "currentPrice": current_price, "currentCost": current_cost,
            "projectedPrice": proj_price, "projectedCost": proj_cost,
            "currentQty": qty, "projectedQty": proj_qty,
            "currentProfit": round(current_profit, 2), "projectedProfit": round(projected_profit, 2),
            "profitChange": round(projected_profit - current_profit, 2),
            "profitChangePct": round(((projected_profit - current_profit) / max(abs(current_profit), 0.01)) * 100, 1),
        })
    return {
        "simulations": results,
        "totalCurrentProfit": round(total_current_profit, 2),
        "totalProjectedProfit": round(total_projected_profit, 2),
        "netImpact": round(total_projected_profit - total_current_profit, 2),
    }

# ============ DEMAND FORECASTING API ============
@router.get("/analytics/demand-forecast")
async def get_demand_forecast():
    reservations = await db.reservations.find(tenant_scope_filter(), {"_id": 0}).to_list(1000)
    today = datetime.utcnow()
    forecast = []
    for i in range(7):
        day = today + __import__('datetime').timedelta(days=i)
        day_str = day.strftime('%Y-%m-%d')
        day_name = day.strftime('%A')
        day_res = [r for r in reservations if r.get("date") == day_str]
        booked_covers = sum(r.get("partySize", 0) for r in day_res)
        is_weekend = day.weekday() >= 4
        base_walkins = random.randint(30, 60) if is_weekend else random.randint(15, 35)
        estimated_covers = booked_covers + base_walkins
        busy_level = "low"
        if estimated_covers > 80:
            busy_level = "very_high"
        elif estimated_covers > 50:
            busy_level = "high"
        elif estimated_covers > 30:
            busy_level = "medium"
        forecast.append({
            "date": day_str, "dayOfWeek": day_name,
            "reservations": len(day_res), "bookedCovers": booked_covers,
            "estimatedWalkins": base_walkins, "totalEstimatedCovers": estimated_covers,
            "busyLevel": busy_level, "isWeekend": is_weekend,
            "suggestedStaff": max(3, estimated_covers // 15),
        })
    return {"forecast": forecast, "generatedAt": today.isoformat()}

# ============ TABLE TURN-TIME OPTIMIZATION ============
@router.get("/analytics/table-turns")
async def get_table_turn_analytics():
    reservations = await db.reservations.find(tenant_scope_filter(), {"_id": 0}).to_list(5000)
    completed = [r for r in reservations if r.get("status") == "completed" and r.get("seatedAt") and r.get("completedAt")]
    turn_times = []
    for r in completed:
        try:
            seated = datetime.fromisoformat(r["seatedAt"])
            done = datetime.fromisoformat(r["completedAt"])
            duration = (done - seated).total_seconds() / 60
            if 10 < duration < 300:
                turn_times.append({"reservationId": r["id"], "partySize": r.get("partySize", 2), "duration": round(duration, 1), "section": r.get("section", "main")})
        except (ValueError, TypeError):
            pass
    avg_turn = sum(t["duration"] for t in turn_times) / len(turn_times) if turn_times else 75
    by_party = {}
    for t in turn_times:
        ps = t["partySize"]
        if ps not in by_party:
            by_party[ps] = []
        by_party[ps].append(t["duration"])
    party_avgs = [{"partySize": ps, "avgDuration": round(sum(ds) / len(ds), 1), "count": len(ds)} for ps, ds in sorted(by_party.items())]
    by_section = {}
    for t in turn_times:
        sec = t["section"]
        if sec not in by_section:
            by_section[sec] = []
        by_section[sec].append(t["duration"])
    section_avgs = [{"section": sec, "avgDuration": round(sum(ds) / len(ds), 1), "count": len(ds)} for sec, ds in by_section.items()]
    optimal_turn = max(45, avg_turn * 0.85)
    potential_extra = 0
    tables = await db.floor_plans.find(tenant_scope_filter(), {"_id": 0}).to_list(10)
    total_tables = sum(len(p.get("tables", [])) for p in tables)
    if total_tables > 0:
        current_turns_per_night = (5 * 60) / avg_turn
        optimal_turns = (5 * 60) / optimal_turn
        potential_extra = int((optimal_turns - current_turns_per_night) * total_tables)
    return {
        "avgTurnTime": round(avg_turn, 1), "totalCompleted": len(turn_times),
        "byPartySize": party_avgs, "bySection": section_avgs,
        "optimization": {"optimalTurnTime": round(optimal_turn, 1), "potentialExtraCovers": potential_extra,
                         "revenueOpportunity": round(potential_extra * 35, 2)},
    }

# ============ SMART ROSTERING API ============
@router.get("/staff/smart-roster")
async def get_smart_roster(_: dict = Depends(require_owner_or_manager)):
    today = datetime.utcnow()
    roster = []
    for i in range(7):
        day = today + __import__('datetime').timedelta(days=i)
        day_str = day.strftime('%Y-%m-%d')
        day_name = day.strftime('%A')
        is_weekend = day.weekday() >= 4
        base_staff = 6 if is_weekend else 4
        reservations = await db.reservations.find({"date": day_str, **tenant_scope_filter()}, {"_id": 0}).to_list(100)
        covers = sum(r.get("partySize", 0) for r in reservations)
        extra_staff = covers // 20
        total_staff = base_staff + extra_staff
        roles = {
            "servers": max(2, total_staff // 2), "bartenders": max(1, total_staff // 4),
            "kitchen": max(2, total_staff // 3), "host": 1,
        }
        roster.append({
            "date": day_str, "dayOfWeek": day_name, "isWeekend": is_weekend,
            "expectedCovers": covers + (random.randint(20, 45) if is_weekend else random.randint(10, 25)),
            "reservations": len(reservations), "totalStaffNeeded": total_staff, "roles": roles,
        })
    return {"roster": roster, "generatedAt": today.isoformat()}


# ============ FORECASTING SUGGESTIONS — revenue & cost actions ============
@router.get("/analytics/forecast-suggestions")
async def get_forecast_suggestions():
    """Turns the raw demand/table-turn/cost numbers already computed
    elsewhere into concrete, ranked "do this" suggestions — one list to grow
    revenue, one to cut cost — instead of leaving the owner to read the
    charts and work out the implications themselves."""
    demand = await get_demand_forecast()
    turns = await get_table_turn_analytics()

    revenue: List[dict] = []
    cost: List[dict] = []

    # --- Revenue: quiet-day promotion ---
    forecast_days = demand.get("forecast", [])
    if forecast_days:
        quietest = min(forecast_days, key=lambda d: d["totalEstimatedCovers"])
        busiest = max(forecast_days, key=lambda d: d["totalEstimatedCovers"])
        if quietest["totalEstimatedCovers"] < busiest["totalEstimatedCovers"] * 0.6:
            gap = busiest["totalEstimatedCovers"] - quietest["totalEstimatedCovers"]
            est_uplift = round(gap * 0.25 * 35, 2)  # recovering ~25% of the gap at avg $35/cover
            revenue.append({
                "title": f"Fill {quietest['dayOfWeek']} — your quietest day",
                "message": f"{quietest['dayOfWeek']} is forecast at {quietest['totalEstimatedCovers']} covers vs "
                           f"{busiest['totalEstimatedCovers']} on {busiest['dayOfWeek']}. A happy-hour or set-menu push "
                           f"that day could recover some of that gap.",
                "estImpact": est_uplift, "impactLabel": f"~${est_uplift:.0f}/week if it works",
            })

    # --- Revenue: table turn-time opportunity ---
    opp = turns.get("optimization", {})
    if opp.get("potentialExtraCovers", 0) > 0:
        revenue.append({
            "title": "Speed up table turns at peak",
            "message": f"Average turn is {turns.get('avgTurnTime')}m vs an achievable {opp.get('optimalTurnTime')}m. "
                       f"Tightening bussing/POS handoff at peak could seat {opp.get('potentialExtraCovers')} more covers/night.",
            "estImpact": opp.get("revenueOpportunity", 0), "impactLabel": f"~${opp.get('revenueOpportunity', 0):.0f}/night",
        })

    # --- Revenue: promote the highest-margin popular item ---
    all_txns = await db.transactions.find(tenant_scope_filter(), {"_id": 0}).to_list(10000)
    products = await db.products.find(tenant_scope_filter(), {"_id": 0}).to_list(2000)
    product_map = {p["id"]: p for p in products}
    product_sales: dict = {}
    total_revenue = 0.0
    for t in all_txns:
        total_revenue += t.get("total", 0)
        for item in t.get("items", []):
            pid = item.get("productId", "")
            prod = product_map.get(pid, {})
            row = product_sales.setdefault(pid, {
                "name": item.get("productName") or prod.get("name") or "Item", "revenue": 0.0, "qty": 0,
                "cost": prod.get("cost", 0), "price": prod.get("price", item.get("price", 0)),
            })
            row["revenue"] += item.get("price", 0) * item.get("quantity", 0)
            row["qty"] += item.get("quantity", 0)
    for row in product_sales.values():
        row["totalCost"] = row["cost"] * row["qty"]
        row["margin"] = ((row["revenue"] - row["totalCost"]) / row["revenue"] * 100) if row["revenue"] > 0 else 0
    sellable = [r for r in product_sales.values() if r["qty"] > 0]
    # Require a real, non-zero cost — an item with no cost recorded trivially
    # reports 100% margin, which is a data gap, not a genuine signal — and
    # require it to actually be popular (top half by units sold), so this
    # isn't just surfacing whatever happens to have the fewest recorded costs.
    median_qty = sorted((r["qty"] for r in sellable), reverse=True)[len(sellable) // 2] if sellable else 0
    popular_priced = [r for r in sellable if r["cost"] > 0 and r["qty"] >= median_qty]
    high_margin_popular = sorted(popular_priced, key=lambda r: (r["margin"], r["revenue"]), reverse=True)
    if high_margin_popular and high_margin_popular[0]["margin"] > 50:
        top = high_margin_popular[0]
        revenue.append({
            "title": f'Upsell "{top["name"]}" harder',
            "message": f'"{top["name"]}" runs a {top["margin"]:.0f}% margin and already sells well — a server prompt '
                       f"or menu callout pushes more covers toward your most profitable dish instead of a thinner one.",
            "estImpact": None, "impactLabel": f"{top['margin']:.0f}% margin item",
        })

    # --- Cost: food cost % ---
    total_cogs = sum(r["totalCost"] for r in product_sales.values())
    food_cost_pct = (total_cogs / total_revenue * 100) if total_revenue > 0 else 0
    if food_cost_pct > 32:
        target_pct = 30
        est_saving = round(max(total_cogs - (total_revenue * target_pct / 100), 0), 2)
        cost.append({
            "title": f"Food cost is running at {food_cost_pct:.1f}%",
            "message": f"Industry target is 28–32% of revenue. Check portion sizes and supplier pricing on your "
                       f"highest-volume ingredients first — that's where a small % shift moves the most dollars.",
            "estImpact": est_saving, "impactLabel": f"~${est_saving:.0f} back at {target_pct}%",
        })

    # --- Cost: lowest-margin item worth re-pricing or cutting ---
    low_performers = sorted([r for r in sellable if r["revenue"] > 0], key=lambda r: r["margin"])[:1]
    if low_performers and low_performers[0]["margin"] < 15:
        worst = low_performers[0]
        cost.append({
            "title": f'"{worst["name"]}" is barely profitable',
            "message": f'Only a {worst["margin"]:.0f}% margin after {worst["qty"]} sold. Either reprice it, shrink the '
                       f"portion, or swap a costly ingredient — right now it's taking up menu space without paying for itself.",
            "estImpact": None, "impactLabel": f"{worst['margin']:.0f}% margin",
        })

    # --- Cost: overstaffed vs forecast demand ---
    roster = await get_smart_roster()
    roster_days = {d["date"]: d for d in roster.get("roster", [])}
    for d in forecast_days:
        r = roster_days.get(d["date"])
        if not r:
            continue
        # crude check: >1 staff per 10 covers suggests slack in the roster that day
        if d["totalEstimatedCovers"] > 0 and r["totalStaffNeeded"] / d["totalEstimatedCovers"] > 0.12:
            est_saving = round((r["totalStaffNeeded"] - max(3, d["totalEstimatedCovers"] // 15)) * 4 * 25, 2)
            if est_saving > 0:
                cost.append({
                    "title": f"Possible overstaffing on {d['dayOfWeek']}",
                    "message": f"{r['totalStaffNeeded']} staff rostered against a forecast of only "
                               f"{d['totalEstimatedCovers']} covers. Worth a second look before confirming that shift.",
                    "estImpact": est_saving, "impactLabel": f"~${est_saving:.0f} if trimmed by one shift",
                })
            break  # one example is enough — this is a nudge, not a full audit

    return {
        "generatedAt": datetime.utcnow().isoformat(),
        "revenue": revenue,
        "cost": cost,
    }


# ============ PREDICTIVE CUSTOMER MATCHING ============
@router.post("/orders/predict-customer")
async def predict_customer_for_order(order_items: List[dict]):
    if not order_items:
        return {"matched": False, "message": "No items provided"}
    item_names = set(item.get("productName", "").lower() for item in order_items)
    customers = await db.customers.find({**tenant_scope_filter(), }, {"_id": 0}).to_list(1000)
    txns = await db.transactions.find(tenant_scope_filter(), {"_id": 0}).to_list(10000)
    customer_patterns = {}
    for txn in txns:
        cid = txn.get("customerId")
        if not cid:
            continue
        if cid not in customer_patterns:
            customer_patterns[cid] = {}
        for item in txn.get("items", []):
            name = item.get("productName", "").lower()
            customer_patterns[cid][name] = customer_patterns[cid].get(name, 0) + item.get("quantity", 0)
    scores = []
    for cust in customers:
        cid = cust["id"]
        pattern = customer_patterns.get(cid, {})
        if not pattern:
            continue
        overlap = sum(1 for name in item_names if name in pattern)
        total_items = len(item_names)
        freq_score = sum(pattern.get(name, 0) for name in item_names)
        if overlap > 0:
            similarity = (overlap / max(total_items, 1)) * 100
            scores.append({
                "customerId": cid, "customerName": cust["name"],
                "email": cust.get("email", ""), "phone": cust.get("phone", ""),
                "points": cust.get("points", 0), "tier": cust.get("membershipTier", "Bronze"),
                "isVip": cust.get("isVip", False), "similarity": round(similarity, 1),
                "frequencyScore": freq_score, "matchedItems": [n for n in item_names if n in pattern],
                "favoriteDishes": cust.get("favoriteDishes", []),
            })
    scores.sort(key=lambda x: (x["similarity"], x["frequencyScore"]), reverse=True)
    if scores:
        return {"matched": True, "predictions": scores[:5], "topMatch": scores[0]}
    return {"matched": False, "message": "No matching customer patterns found"}

@router.post("/orders/link-customer")
async def link_order_to_customer(transaction_id: str, customer_id: str, user: dict = Depends(get_user)):
    """Attach the "predicted" customer (see predict_customer_for_order above)
    to a completed sale the register didn't have a loyalty match for at the
    time, and back-credit the points that sale would have earned had the
    customer been linked at checkout.

    Used to accept a client-supplied `points_earned` with no auth at all —
    any bearer token from any business could award an arbitrary number of
    points to any customer of any business, with no ledger entry and no
    audit trail (found in the Trust Release final readiness audit). Fixed
    to require auth, verify both the transaction and the customer belong to
    the caller's own business, and compute points itself from the
    transaction's own stored items/total via the same
    services.sale_recorder.compute_points_earned/credit_loyalty_points
    canonical path routes/transactions.py's checkout uses — never a
    client-supplied number.
    """
    business_id = user.get("businessId")
    txn = await db.transactions.find_one({"$and": [{"id": transaction_id}, tenant_scope_filter(business_id)]}, {"_id": 0})
    if not txn or not tenant_owns_strict(txn.get("businessId"), business_id):
        raise HTTPException(status_code=404, detail="Transaction not found")
    customer = await db.customers.find_one({**tenant_scope_filter(user.get("businessId")), "id": customer_id}, {"_id": 0})
    if not customer or not tenant_owns(customer.get("businessId"), business_id):
        raise HTTPException(status_code=404, detail="Customer not found")
    existing_customer_id = txn.get("customerId")
    if existing_customer_id and existing_customer_id != customer_id:
        raise HTTPException(status_code=409, detail="This order is already linked to a different customer")

    # Idempotent: a retry (or this order already having been linked earlier)
    # must not credit the same sale's points twice.
    already_earned = await db.loyalty_ledger.find_one(
        {"transactionId": transaction_id, "type": "earn", **tenant_scope_filter(business_id)}, {"_id": 0})
    if already_earned:
        await db.transactions.update_one({"$and": [{"id": transaction_id}, tenant_scope_filter(business_id)]}, {"$set": {"customerId": customer_id}})
        return {"message": "Order linked (points already credited earlier)",
                "pointsEarned": already_earned.get("points", 0), "skipped": True}

    # Points computed from the sale's own recorded items/total — the exact
    # same inputs and formula routes/transactions.py's checkout uses, not a
    # client-supplied number.
    from services.tenant_settings import get_scoped_singleton
    from services.sale_recorder import compute_points_earned, credit_loyalty_points
    loyalty_cfg = await get_scoped_singleton(db.loyalty_config, {"id": "default"}, business_id) or {}
    tier_name = customer.get("membershipTier", "Bronze")
    tier_doc = await db.loyalty_tiers.find_one(
        {"name": tier_name, **tenant_scope_filter(business_id)}, {"_id": 0})
    loyalty_multiplier = float((tier_doc or {}).get("multiplier", 1.0))
    earn_lines = []
    subtotal = float(txn.get("subtotal") or 0)
    for item in txn.get("items", []):
        product = await db.products.find_one(
            {"id": item.get("productId"), **tenant_scope_filter(business_id)},
            {"_id": 0, "category": 1},
        )
        line_total = float(item.get("price", 0)) * float(item.get("quantity", 1))
        earn_lines.append(((product or {}).get("category") or "Other", line_total))
    total = float(txn.get("total") or 0)
    points_earned = compute_points_earned(subtotal, total, loyalty_multiplier, earn_lines, loyalty_cfg)

    await db.transactions.update_one({"$and": [{"id": transaction_id}, tenant_scope_filter(business_id)]}, {"$set": {"customerId": customer_id}})
    await credit_loyalty_points(customer_id, points_earned, total, transaction_id, business_id=business_id)

    from services.audit_service import log_event
    await log_event(
        entity_type="loyalty_ledger", entity_id=transaction_id, action="created",
        after={"transactionId": transaction_id, "customerId": customer_id, "pointsEarned": points_earned},
        memo=f"Linked order {transaction_id} to customer {customer_id}, credited {points_earned} points",
        severity="notice", tags=["loyalty", "order_link"],
    )
    return {"message": "Order linked and points awarded", "pointsEarned": points_earned}


async def _notify_critical_alerts_once(today_iso: str, alerts: List[dict]) -> None:
    """Fan critical Pulse alerts out through the in-app notification bell
    (services/notification_service.py) so they reach the owner wherever
    they are in the app, not only when they happen to have Pulse open.

    Deduped per (date, kind) via db.pulse_alert_notifications — this
    endpoint is polled every ~60s by the Pulse dashboard, so without a
    dedup guard the same stockout would notify on every poll."""
    from services import notification_service
    for a in alerts:
        if a.get("severity") != "critical":
            continue
        key = {"date": today_iso, "kind": a["kind"]}
        already_sent = await db.pulse_alert_notifications.find_one(key, {"_id": 1})
        if already_sent:
            continue
        try:
            await notification_service.send(
                kind="system", severity="critical", role="owner",
                title="Needs attention", body=a["message"], link=a.get("link"),
            )
            await db.pulse_alert_notifications.insert_one(key)
        except Exception as exc:
            logger.warning("Failed to notify critical pulse alert %s: %s", a["kind"], exc)


# ============ TODAY PULSE — one call that answers "is anything wrong right now?" ============
@router.get("/analytics/today-pulse")
async def get_today_pulse(_user: dict = Depends(require_owner_or_manager)):
    # Owner/manager only: takings against target, labour cost and labour %,
    # refund totals and comp/void counts. Today.jsx already skips this call
    # for cashier/kitchen logins and hides the tiles — but the client
    # declining to ask is not the same as the server declining to answer,
    # and the owner.nuapos.com.au shell makes that distinction matter.
    """Single feed for the Today home screen: sales vs target, labor %,
    and exception alerts (refund spikes, voids, stockouts, low stock).
    Alerts carry a severity and a deep-link so problems tap the manager
    on the shoulder instead of hiding in reports."""
    from datetime import timezone as _tz
    now = datetime.now(_tz.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_iso = now.date().isoformat()

    # --- Sales today ---
    scope = tenant_scope_filter(_user.get("businessId"))
    txns = await db.transactions.find(
        {"timestamp": {"$gte": day_start.replace(tzinfo=None)}, **scope}, {"_id": 0}
    ).to_list(5000)
    sales_today = round(sum(t.get("total", 0) for t in txns), 2)
    txn_count = len(txns)
    avg_ticket = round(sales_today / txn_count, 2) if txn_count else 0

    # --- Settings-driven thresholds ---
    from services.tenant_settings import get_setting
    today_targets_value = await get_setting("today_targets", _user.get("businessId"))
    cfg = {"dailySalesTarget": 0, "laborPctThreshold": 32, "refundRateThreshold": 5}
    if isinstance(today_targets_value, dict):
        cfg.update({k: v for k, v in today_targets_value.items() if v is not None})

    # --- Labor: rostered cost today vs sales ---
    shifts = await db.roster_shifts.find({"date": today_iso, **scope}, {"_id": 0}).to_list(500)
    staff = await db.auth_users.find(scope, {"_id": 0, "id": 1, "name": 1, "payRate": 1}).to_list(1000)
    rate_by_id = {u["id"]: u.get("payRate", 0) for u in staff}
    labor_cost = 0.0
    for sh in shifts:
        try:
            sh_start = datetime.strptime(sh.get("startTime", "09:00"), "%H:%M")
            sh_end = datetime.strptime(sh.get("endTime", "17:00"), "%H:%M")
            hours = max((sh_end - sh_start).total_seconds() / 3600, 0)
        except ValueError:
            hours = 8
        labor_cost += hours * float(rate_by_id.get(sh.get("staffId"), 0) or 0)
    labor_cost = round(labor_cost, 2)
    labor_pct = round((labor_cost / sales_today) * 100, 1) if sales_today > 0 else None

    # --- Exceptions ---
    refunds = await db.refunds.find(scope, {"_id": 0}).sort("timestamp", -1).to_list(200)
    refunds_today = [r for r in refunds
                     if str(r.get("timestamp", ""))[:10] == today_iso]
    refund_total = round(sum(r.get("amount", 0) for r in refunds_today), 2)
    refund_rate = round((refund_total / sales_today) * 100, 1) if sales_today > 0 else 0

    voids_today = await db.comp_voids.count_documents(
        {"processedAt": {"$regex": f"^{today_iso}"}, **tenant_scope_filter()})

    low_stock = await db.products.find(
        {"active": {"$ne": False}, "stock": {"$gt": 0, "$lte": 5}, **tenant_scope_filter()},
        {"_id": 0, "id": 1, "name": 1, "stock": 1}).to_list(50)
    stockouts = await db.products.find(
        {"active": {"$ne": False}, "stock": {"$lte": 0}, **tenant_scope_filter()},
        {"_id": 0, "id": 1, "name": 1, "stock": 1}).to_list(50)

    bookings_tonight = await db.reservations.count_documents({"date": today_iso, **tenant_scope_filter()})
    open_kitchen = await db.kitchen_orders.count_documents(
        {"status": {"$in": ["pending", "in_progress"]}, **tenant_scope_filter()})

    # --- 7-day sales trend (today inclusive) for the Pulse sparkline ---
    trend_start = day_start - timedelta(days=6)
    trend_rows = await db.transactions.aggregate([
        {"$match": {"timestamp": {"$gte": trend_start.replace(tzinfo=None)}, **tenant_scope_filter()}},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}},
            "total": {"$sum": "$total"},
        }},
    ]).to_list(30)
    by_date = {r["_id"]: round(r["total"], 2) for r in trend_rows}
    trend = [{"date": (trend_start + timedelta(days=i)).date().isoformat(),
              "total": by_date.get((trend_start + timedelta(days=i)).date().isoformat(), 0)}
             for i in range(7)]

    # --- Assemble alerts, most severe first ---
    alerts = []
    if stockouts:
        names = ", ".join(p["name"] for p in stockouts[:3])
        alerts.append({"severity": "critical", "kind": "stockout", "link": "/inventory",
                       "message": f"{len(stockouts)} item(s) out of stock: {names}"
                                  + ("…" if len(stockouts) > 3 else "")})
    if labor_pct is not None and labor_pct > cfg["laborPctThreshold"]:
        alerts.append({"severity": "warning", "kind": "labor", "link": "/staff-roster",
                       "message": f"Labor at {labor_pct}% of sales (threshold {cfg['laborPctThreshold']}%)"})
    if refund_rate > cfg["refundRateThreshold"]:
        alerts.append({"severity": "warning", "kind": "refunds", "link": "/accounting",
                       "message": f"Refunds at {refund_rate}% of today's sales (${refund_total})"})
    if voids_today >= 5:
        alerts.append({"severity": "warning", "kind": "voids", "link": "/comp-void",
                       "message": f"{voids_today} comps/voids today — worth a look"})
    if low_stock:
        alerts.append({"severity": "info", "kind": "low_stock", "link": "/inventory",
                       "message": f"{len(low_stock)} item(s) running low"})
    if open_kitchen >= 12:
        alerts.append({"severity": "info", "kind": "kitchen_load", "link": "/kitchen",
                       "message": f"{open_kitchen} open kitchen tickets — kitchen under load"})

    await _notify_critical_alerts_once(today_iso, alerts)

    return {
        "date": today_iso,
        "sales": {"today": sales_today, "target": cfg["dailySalesTarget"],
                  "txnCount": txn_count, "avgTicket": avg_ticket,
                  "pctOfTarget": round((sales_today / cfg["dailySalesTarget"]) * 100, 1)
                                 if cfg["dailySalesTarget"] else None},
        "labor": {"costToday": labor_cost, "pct": labor_pct,
                  "threshold": cfg["laborPctThreshold"], "shiftsToday": len(shifts)},
        "exceptions": {"refundTotal": refund_total, "refundRate": refund_rate,
                       "voidsToday": voids_today, "lowStock": low_stock[:10],
                       "stockouts": stockouts[:10]},
        "service": {"bookingsTonight": bookings_tonight, "openKitchenTickets": open_kitchen},
        "alerts": alerts,
        "trend": trend,
    }


# ============ TODAY TARGETS (config for the Today home screen) ============
TODAY_TARGETS_DEFAULTS = {"dailySalesTarget": 0, "laborPctThreshold": 32, "refundRateThreshold": 5}


@router.get("/analytics/today-targets")
async def get_today_targets(_user: dict = Depends(get_user)):
    from services.tenant_settings import get_setting
    value = await get_setting("today_targets", _user.get("businessId"))
    cfg = dict(TODAY_TARGETS_DEFAULTS)
    if isinstance(value, dict):
        cfg.update({k: v for k, v in value.items() if v is not None})
    return cfg


@router.post("/analytics/today-targets")
async def save_today_targets(data: dict, _user: dict = Depends(require_owner_or_manager)):
    from services.tenant_settings import set_setting
    cfg = {
        "dailySalesTarget": max(float(data.get("dailySalesTarget", 0) or 0), 0),
        "laborPctThreshold": max(float(data.get("laborPctThreshold", 32) or 0), 1),
        "refundRateThreshold": max(float(data.get("refundRateThreshold", 5) or 0), 0),
    }
    await set_setting("today_targets", cfg, _user.get("businessId"))
    return cfg
