"""
Superannuation Guarantee (SG) — Fair Work Commission compliant.

This module owns:
  • GET  /super/rate                       — current SG rate, auto-tiered by pay date
  • POST /super/calc                       — compute SG for a specific pay run (with per-employee breakdown)
  • POST /super/weekly-runs                — commit a weekly SG summary to the ledger
  • GET  /super/weekly-runs                — history (filterable by date range)
  • GET  /super/bas-line                   — the "Superannuation payable" line item that BAS/GST pulls in
  • GET  /super/summary                    — quarterly totals for a given financial year

Rate policy (Fair Work Commission):
    Pay date ≥ 2025-07-01  → 12.0 %
    Pay date ≥ 2024-07-01  → 11.5 %
    Pay date ≥ 2023-07-01  → 11.0 %
    otherwise               → 10.5 %

Owners can override by passing an explicit `rate` in /super/calc; the tier
lookup is only the default.
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from datetime import datetime, date, timezone
from pydantic import BaseModel
from database import db
from deps import get_user
from middleware.actor_context import tenant_scope_filter, tenant_owns_strict
import uuid

router = APIRouter()

# ─── Rate tiers (per Fair Work Commission) ───────────────────────────────
SG_TIERS = [
    (date(2025, 7, 1), 12.0),
    (date(2024, 7, 1), 11.5),
    (date(2023, 7, 1), 11.0),
    (date(2022, 7, 1), 10.5),
]


def _sg_rate_for(pay_date: date) -> float:
    """Return the SG rate applicable on `pay_date`. Fair Work publishes rates
    that take effect on 1 July each year; we tier accordingly."""
    for effective_from, rate in SG_TIERS:
        if pay_date >= effective_from:
            return rate
    return 10.0  # historical fallback


# ─── Models ──────────────────────────────────────────────────────────────
class StaffPay(BaseModel):
    staffId: Optional[str] = None
    name: str
    role: Optional[str] = None
    grossPay: float                # gross wages for the period ($)
    ordinaryTimeEarnings: Optional[float] = None   # OTE — used if provided, else grossPay
    awardCode: Optional[str] = None


class SuperCalcIn(BaseModel):
    payPeriodStart: str            # ISO date
    payPeriodEnd: str              # ISO date
    payDate: str                   # ISO date — used to pick the SG rate tier
    staff: List[StaffPay]
    rate: Optional[float] = None   # explicit override (e.g. salary sacrifice arrangement)


class WeeklyRunIn(BaseModel):
    payPeriodStart: str
    payPeriodEnd: str
    payDate: str
    staff: List[StaffPay]
    rate: Optional[float] = None
    note: Optional[str] = None


# ─── Endpoints ───────────────────────────────────────────────────────────
@router.get("/super/rate")
async def get_current_rate(payDate: Optional[str] = None, _: dict = Depends(get_user)):
    """Returns the SG rate that would apply on `payDate` (defaults to today).
    Also surfaces the full tier ladder so the UI can render an explainer."""
    d = date.fromisoformat(payDate) if payDate else date.today()
    return {
        "date": d.isoformat(),
        "rate": _sg_rate_for(d),
        "source": "fair_work_commission",
        "tiers": [
            {"effectiveFrom": t[0].isoformat(), "rate": t[1]} for t in SG_TIERS
        ],
        "nextChange": {
            "effectiveFrom": "2025-07-01",
            "rate": 12.0,
            "note": "SG reaches its legislated cap of 12% from 1 July 2025.",
        },
    }


def _compute_row(row: StaffPay, rate: float) -> dict:
    ote = row.ordinaryTimeEarnings if row.ordinaryTimeEarnings is not None else row.grossPay
    contribution = round(float(ote) * (rate / 100.0), 2)
    return {
        "staffId": row.staffId,
        "name": row.name,
        "role": row.role,
        "awardCode": row.awardCode,
        "grossPay": float(row.grossPay),
        "ordinaryTimeEarnings": float(ote),
        "rate": rate,
        "superContribution": contribution,
    }


@router.post("/super/calc")
async def calculate(body: SuperCalcIn, _: dict = Depends(get_user)):
    """Compute SG for the supplied pay run. Uses the tier-lookup by default,
    or the explicit `rate` when provided (must be between 0 and 30)."""
    try:
        pay_date = date.fromisoformat(body.payDate)
    except ValueError:
        raise HTTPException(400, "payDate must be ISO-formatted (YYYY-MM-DD)")

    if body.rate is not None:
        if not (0.0 <= float(body.rate) <= 30.0):
            raise HTTPException(400, "rate must be between 0 and 30 %")
        rate = float(body.rate)
        rate_source = "override"
    else:
        rate = _sg_rate_for(pay_date)
        rate_source = "fair_work_tier"

    rows = [_compute_row(s, rate) for s in body.staff]
    total = round(sum(r["superContribution"] for r in rows), 2)
    total_ote = round(sum(r["ordinaryTimeEarnings"] for r in rows), 2)

    return {
        "payPeriodStart": body.payPeriodStart,
        "payPeriodEnd": body.payPeriodEnd,
        "payDate": body.payDate,
        "rate": rate,
        "rateSource": rate_source,
        "totalOTE": total_ote,
        "totalSuper": total,
        "employees": rows,
        "computedAt": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/super/weekly-runs")
async def commit_weekly_run(body: WeeklyRunIn, user: dict = Depends(get_user)):
    """Commit a computed weekly SG summary to the ledger. This is what BAS/GST
    reads from when preparing the 'Superannuation payable' line for the quarter."""
    if user["role"] != "owner":
        raise HTTPException(403, "Owner only")

    calc = await calculate(SuperCalcIn(**body.dict()), user)

    doc = {
        "id": str(uuid.uuid4()),
        **calc,
        "note": body.note,
        "committedBy": user.get("email"),
        "committedAt": datetime.now(timezone.utc).isoformat(),
        "status": "unpaid",       # UI can mark paid once STP/Clearing House confirms
        "businessId": user.get("businessId"),
    }
    await db.super_weekly_runs.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/super/weekly-runs")
async def list_weekly_runs(startDate: Optional[str] = None, endDate: Optional[str] = None,
                           user: dict = Depends(get_user)):
    """List committed weekly runs. Filter by pay-date range so BAS can pull
    'runs where payDate ∈ [Q_start, Q_end]'."""
    query = tenant_scope_filter(user.get("businessId"))
    if startDate:
        query["payDate"] = {"$gte": startDate}
    if endDate:
        query.setdefault("payDate", {})["$lte"] = endDate
    rows = await db.super_weekly_runs.find(query, {"_id": 0}).sort("payDate", -1).to_list(500)
    return rows


@router.patch("/super/weekly-runs/{run_id}")
async def mark_paid(run_id: str, data: dict, user: dict = Depends(get_user)):
    """Owner marks a committed run as paid to the clearing house / super fund."""
    if user["role"] != "owner":
        raise HTTPException(403, "Owner only")
    guard = await db.super_weekly_runs.find_one({"$and": [{"id": run_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "id": 1, "businessId": 1})
    if guard is None or not tenant_owns_strict(guard.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "Super run not found")
    allowed = {"status", "paidAt", "clearingHouseRef", "note"}
    update = {k: v for k, v in data.items() if k in allowed}
    if not update:
        raise HTTPException(400, "Nothing to update")
    if "status" in update and update["status"] not in ("unpaid", "paid", "reversed"):
        raise HTTPException(400, "status must be unpaid | paid | reversed")
    update["updatedAt"] = datetime.now(timezone.utc).isoformat()
    r = await db.super_weekly_runs.update_one({"$and": [{"id": run_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": update})
    if r.matched_count == 0:
        raise HTTPException(404, "Super run not found")
    return await db.super_weekly_runs.find_one({"$and": [{"id": run_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})


@router.get("/super/bas-line")
async def bas_line(quarterStart: str, quarterEnd: str, user: dict = Depends(get_user)):
    """The 'Superannuation payable' line item that BAS/GST reports pull in.

    Returns the total SG accrued in the quarter plus a paid/unpaid breakdown
    so the owner can see how much still needs to hit the clearing house before
    the ATO cut-off (28 days after quarter end)."""
    rows = await db.super_weekly_runs.find(
        {"payDate": {"$gte": quarterStart, "$lte": quarterEnd}, **tenant_scope_filter(user.get("businessId"))},
        {"_id": 0},
    ).to_list(500)

    total_super = round(sum(r.get("totalSuper", 0) for r in rows), 2)
    total_ote = round(sum(r.get("totalOTE", 0) for r in rows), 2)
    total_paid = round(sum(r.get("totalSuper", 0) for r in rows if r.get("status") == "paid"), 2)
    total_unpaid = round(total_super - total_paid, 2)

    return {
        "quarterStart": quarterStart,
        "quarterEnd": quarterEnd,
        "runsIncluded": len(rows),
        "totalOTE": total_ote,
        "totalSuper": total_super,
        "totalSuperPaid": total_paid,
        "totalSuperOutstanding": total_unpaid,
        # ATO reporting-cutoff = 28 days after quarter end
        "reportingDueBy": _due_by(quarterEnd),
        "asOf": datetime.now(timezone.utc).isoformat(),
    }


def _due_by(quarter_end_iso: str) -> str:
    """28 calendar days after the quarter's last day — the ATO deadline for SG."""
    from datetime import timedelta
    qe = date.fromisoformat(quarter_end_iso)
    return (qe + timedelta(days=28)).isoformat()


@router.get("/super/summary")
async def yearly_summary(fy: Optional[str] = None, user: dict = Depends(get_user)):
    """Quarterly rollup for a financial year (default = current AU FY).

    FY string format: '2025-2026' (July → June). Returns 4 quarter buckets
    with totals — useful for the owner's annual view.
    """
    today = date.today()
    if fy:
        try:
            start_y = int(fy.split("-")[0])
        except Exception:
            raise HTTPException(400, "fy must be like '2025-2026'")
    else:
        # AU financial year rolls on 1 July
        start_y = today.year if today.month >= 7 else today.year - 1
    fy_start = date(start_y, 7, 1)

    quarters = [
        ("Q1", date(start_y, 7, 1),  date(start_y, 9, 30)),
        ("Q2", date(start_y, 10, 1), date(start_y, 12, 31)),
        ("Q3", date(start_y + 1, 1, 1), date(start_y + 1, 3, 31)),
        ("Q4", date(start_y + 1, 4, 1), date(start_y + 1, 6, 30)),
    ]

    all_runs = await db.super_weekly_runs.find(
        {"payDate": {"$gte": fy_start.isoformat(),
                     "$lte": date(start_y + 1, 6, 30).isoformat()},
         **tenant_scope_filter(user.get("businessId"))},
        {"_id": 0},
    ).to_list(2000)

    def in_range(r, lo, hi):
        return lo.isoformat() <= r.get("payDate", "") <= hi.isoformat()

    buckets = []
    for name, lo, hi in quarters:
        rows = [r for r in all_runs if in_range(r, lo, hi)]
        buckets.append({
            "quarter": name,
            "start": lo.isoformat(),
            "end":   hi.isoformat(),
            "runs":  len(rows),
            "totalOTE":   round(sum(r.get("totalOTE", 0) for r in rows), 2),
            "totalSuper": round(sum(r.get("totalSuper", 0) for r in rows), 2),
            "totalPaid":  round(sum(r.get("totalSuper", 0) for r in rows if r.get("status") == "paid"), 2),
        })
    return {
        "fy": f"{start_y}-{start_y+1}",
        "quarters": buckets,
        "totalOTE":   round(sum(b["totalOTE"]   for b in buckets), 2),
        "totalSuper": round(sum(b["totalSuper"] for b in buckets), 2),
        "totalPaid":  round(sum(b["totalPaid"]  for b in buckets), 2),
    }
