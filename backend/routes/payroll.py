"""
Australian Payroll — enhanced compliance routes.

  • POST /payroll/payrun/calculate    — award-aware, PAYG-Sch1, SG-tiered pay run
  • POST /payroll/payrun/commit       — persist run + emit STP2 event
  • GET  /payroll/register            — pay run history (KPIs + rows)
  • GET  /payroll/ytd/{staffId}       — year-to-date summary per employee
  • GET  /payroll/payslip/{runId}/{staffId}/pdf   — Fair Work-compliant payslip
  • POST /payroll/stp/build           — STP2 pay-event shape for a run (no submit)
  • GET  /payroll/roster-compliance   — flag award/NES violations across shifts
"""
from fastapi import APIRouter, HTTPException, Depends, Response
from datetime import date, datetime, timezone, timedelta
from pydantic import BaseModel
from database import db
from deps import get_user
from middleware.actor_context import tenant_scope_filter
from utils.au_payroll import (
    sg_rate_for, super_due_date_for_quarter,
    assemble_payslip_row, build_stp2_pay_event, roster_compliance_issues,
    effective_hourly_rate,
)
import uuid

router = APIRouter()


def _quarter_bounds(dt: date) -> tuple[date, date]:
    q = (dt.month - 1) // 3
    start = date(dt.year, q * 3 + 1, 1)
    if q == 3:
        end = date(dt.year, 12, 31)
    else:
        end = date(dt.year, q * 3 + 4, 1) - timedelta(days=1)
    return start, end


class PayrunCalcIn(BaseModel):
    periodStart: str
    periodEnd: str
    payDate: str
    period: str = "week"     # week | fortnight | monthly
    country: str = "AU"


@router.post("/payroll/payrun/calculate")
async def calculate_payrun(body: PayrunCalcIn, user: dict = Depends(get_user)):
    """Aggregate all timecards in the period, apply base + penalty rates
    from the assigned award, compute PAYG (Sch 1) + SG."""
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(403, "Owner or manager only")

    p_start = date.fromisoformat(body.periodStart)
    p_end = date.fromisoformat(body.periodEnd)
    pay_date = date.fromisoformat(body.payDate)

    # Load staff, timecards, and per-employee award assignment.
    # Scoped by businessId: timecards/payrun_rows don't carry their own
    # businessId (pre-existing schema gap — see SECURITY_DEPENDENCY_DEBT.md-
    # style note in the P0.3 write-up), so isolation here goes through the
    # staff list instead — a business's payroll run can only ever include
    # staffIds that belong to its own auth_users records.
    biz = user.get("businessId")
    staff = await db.auth_users.find(
        {"role": {"$ne": "owner"}, "status": "active", **tenant_scope_filter(biz)},
        {"_id": 0, "password_hash": 0},
    ).to_list(500)
    staff_ids = {s["id"] for s in staff}
    timecards = await db.timecards.find(
        {"clockIn": {"$gte": p_start.isoformat()}, "clockOut": {"$lte": (p_end + timedelta(days=1)).isoformat()},
         "staffId": {"$in": list(staff_ids)}},
        {"_id": 0},
    ).to_list(50000)

    rows: list = []
    total_gross = total_tax = total_super = total_net = 0.0

    # YTD balances (start of fin-year = 1 Jul)
    fy_start = date(p_end.year if p_end.month >= 7 else p_end.year - 1, 7, 1)
    ytd_docs = await db.payrun_rows.find(
        {"payDate": {"$gte": fy_start.isoformat(), "$lt": pay_date.isoformat()},
         "staffId": {"$in": list(staff_ids)}},
        {"_id": 0},
    ).to_list(50000)
    ytd_map: dict = {}
    for d in ytd_docs:
        sid = d.get("staffId")
        b = ytd_map.setdefault(sid, {"gross": 0, "tax": 0, "super": 0})
        b["gross"] += d.get("grossPay", 0)
        b["tax"] += d.get("payg", 0)
        b["super"] += d.get("super", 0)

    for s in staff:
        cards = [tc for tc in timecards if tc.get("staffId") == s["id"]]
        total_hours = sum(tc.get("hoursWorked", 0) for tc in cards)
        base_rate = effective_hourly_rate(s.get("payRate"), s.get("salaryType"))
        if base_rate <= 0 or total_hours <= 0:
            continue
        emp_type = (s.get("employmentType") or "casual").lower()
        # Very small casual→FT/PT rate model: casual +25% loading is already
        # in payRate in most cases, so we just flag it. Fine-grained penalty
        # rates arrive when timecards carry {saturday, sunday, ph, night}
        # boolean flags — sum those into penalty_pay.
        penalty_pay = round(sum(tc.get("penaltyPay", 0) for tc in cards), 2)
        overtime_pay = round(sum(tc.get("overtimePay", 0) for tc in cards), 2)
        allowances = round(sum(tc.get("allowances", 0) for tc in cards), 2)

        ytd = ytd_map.get(s["id"], {"gross": 0, "tax": 0, "super": 0})

        row = assemble_payslip_row(
            name=s["name"], role=s.get("role", ""),
            employment_type=emp_type,
            hours_worked=total_hours, base_hourly=base_rate,
            pay_date=pay_date, period=body.period,
            penalty_pay=penalty_pay, allowances=allowances,
            overtime_pay=overtime_pay,
            ytd_gross=ytd["gross"], ytd_tax=ytd["tax"], ytd_super=ytd["super"],
            tfn_provided=bool(s.get("tfnProvided", True)),
            resident=bool(s.get("resident", True)),
            tft_claimed=bool(s.get("tftClaimed", True)),
            help_debt=bool(s.get("helpDebt", False)),
        )
        row["staffId"] = s["id"]
        row["timecardCount"] = len(cards)
        rows.append(row)
        total_gross += row["grossPay"]
        total_tax += row["payg"]
        total_super += row["super"]
        total_net += row["netPay"]

    q_start, q_end = _quarter_bounds(pay_date)
    return {
        "id": None,
        "periodStart": body.periodStart, "periodEnd": body.periodEnd,
        "payDate": body.payDate, "period": body.period,
        "rows": rows,
        "totals": {
            "grossPay": round(total_gross, 2),
            "payg": round(total_tax, 2),
            "super": round(total_super, 2),
            "netPay": round(total_net, 2),
            "employees": len(rows),
        },
        "compliance": {
            "paygScheduleVersion": "ATO Sch 1 (Nov 2023)",
            "sgRate": sg_rate_for(pay_date),
            "superDueBy": super_due_date_for_quarter(q_end).isoformat(),
            "quarterEnd": q_end.isoformat(),
        },
    }


@router.post("/payroll/payrun/commit")
async def commit_payrun(data: dict, user: dict = Depends(get_user)):
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(403, "Owner or manager only")
    run_id = f"PR-{uuid.uuid4().hex[:8].upper()}"
    biz = user.get("businessId")
    doc = {
        "id": run_id,
        "businessId": biz,
        "periodStart": data.get("periodStart"),
        "periodEnd": data.get("periodEnd"),
        "payDate": data.get("payDate"),
        "period": data.get("period", "week"),
        "totals": data.get("totals", {}),
        "compliance": data.get("compliance", {}),
        "status": "committed",
        "committedBy": user.get("email"),
        "committedAt": datetime.now(timezone.utc).isoformat(),
    }
    await db.payruns.insert_one(dict(doc))
    doc.pop("_id", None)   # in case insert_one mutated
    # Persist per-employee rows for YTD reconciliation
    for r in data.get("rows", []):
        await db.payrun_rows.insert_one({**r, "runId": run_id, "businessId": biz})

    # Build STP2 event immediately so the ATO submission is one click away.
    from services.tenant_settings import get_scoped_singleton
    biz = await get_scoped_singleton(db.business_settings, {"key": "main"}, user.get("businessId")) or {}
    stp = build_stp2_pay_event(
        employer_abn=biz.get("abn", ""),
        employer_name=biz.get("name", "NUA"),
        pay_date=date.fromisoformat(doc["payDate"]),
        period_start=date.fromisoformat(doc["periodStart"]),
        period_end=date.fromisoformat(doc["periodEnd"]),
        rows=data.get("rows", []),
    )
    await db.stp_events.insert_one({"runId": run_id, **stp, "status": "ready_to_submit"})
    return {"runId": run_id, "stpStatus": "ready_to_submit"}


@router.get("/payroll/register")
async def payroll_register(days: int = 90, user: dict = Depends(get_user)):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    runs = await db.payruns.find(
        {"committedAt": {"$gte": since}, **tenant_scope_filter(user.get("businessId"))},
        {"_id": 0}).sort("committedAt", -1).to_list(500)
    # Embed each run's per-employee rows so the register can expand a run and
    # link straight to that employee's payslip PDF — the register view
    # existed with just run-level totals for a while with nothing letting an
    # owner get from "here's a committed run" to an actual payslip without
    # knowing the runId/staffId to construct the URL by hand.
    for r in runs:
        r["rows"] = await db.payrun_rows.find({"runId": r["id"]}, {"_id": 0}).to_list(500)
    return {
        "count": len(runs),
        "totals": {
            "grossPay": round(sum(r.get("totals", {}).get("grossPay", 0) for r in runs), 2),
            "payg":     round(sum(r.get("totals", {}).get("payg", 0) for r in runs), 2),
            "super":    round(sum(r.get("totals", {}).get("super", 0) for r in runs), 2),
            "netPay":   round(sum(r.get("totals", {}).get("netPay", 0) for r in runs), 2),
        },
        "runs": runs,
    }


@router.get("/payroll/ytd/{staff_id}")
async def payroll_ytd(staff_id: str, user: dict = Depends(get_user)):
    from middleware.actor_context import tenant_owns_strict
    staff_doc = await db.auth_users.find_one({"$and": [{"id": staff_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "businessId": 1})
    if not staff_doc or not tenant_owns_strict(staff_doc.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "Staff member not found")
    today = date.today()
    fy_start = date(today.year if today.month >= 7 else today.year - 1, 7, 1)
    rows = await db.payrun_rows.find(
        {"staffId": staff_id, "payDate": {"$gte": fy_start.isoformat()}},
        {"_id": 0},
    ).to_list(2000)
    return {
        "staffId": staff_id,
        "financialYearStart": fy_start.isoformat(),
        "grossPay": round(sum(r.get("grossPay", 0) for r in rows), 2),
        "payg":     round(sum(r.get("payg", 0) for r in rows), 2),
        "super":    round(sum(r.get("super", 0) for r in rows), 2),
        "netPay":   round(sum(r.get("netPay", 0) for r in rows), 2),
        "hours":    round(sum(r.get("hoursWorked", 0) for r in rows), 2),
        "runCount": len(rows),
    }


@router.get("/payroll/payslip/{run_id}/{staff_id}/pdf")
async def payslip_pdf(run_id: str, staff_id: str, user: dict = Depends(get_user)):
    """Fair Work-compliant payslip PDF for one employee, one pay run."""
    from middleware.actor_context import tenant_owns_strict
    run = await db.payruns.find_one({"id": run_id}, {"_id": 0}) or {}
    if run and not tenant_owns_strict(run.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "Payslip not found")
    row = await db.payrun_rows.find_one({"runId": run_id, "staffId": staff_id}, {"_id": 0})
    if not row:
        raise HTTPException(404, "Payslip not found")
    from services.tenant_settings import get_scoped_singleton
    biz = await get_scoped_singleton(db.business_settings, {"key": "main"}, user.get("businessId")) or {}

    lines = [
        f"{biz.get('name', 'NUA')} — ABN {biz.get('abn', '')}",
        f"Employee: {row.get('name', '')}   (ID {staff_id})",
        f"Role: {row.get('role', '')}   Type: {row.get('employmentType', '')}",
        f"Period: {run.get('periodStart', '')} → {run.get('periodEnd', '')}",
        f"Pay date: {run.get('payDate', '')}",
        "",
        "Earnings",
        f"  Ordinary hours:  {row.get('hoursWorked', 0):>8.2f} @ ${row.get('baseHourly', 0):>7.2f} = ${row.get('ordinaryPay', 0):>10.2f}",
        f"  Penalty rates:                                  ${row.get('penaltyPay', 0):>10.2f}",
        f"  Overtime:                                        ${row.get('overtimePay', 0):>10.2f}",
        f"  Allowances:                                      ${row.get('allowances', 0):>10.2f}",
        f"  Gross pay:                                       ${row.get('grossPay', 0):>10.2f}",
        "",
        "Deductions",
        f"  PAYG withholding (Sch 1 · Scale {row.get('paygScale', '2')}):    ${row.get('payg', 0):>10.2f}",
        "",
        "Superannuation (paid by employer)",
        f"  OTE:                                             ${row.get('ote', 0):>10.2f}",
        f"  SG @ {row.get('sgRate', 0):>4.1f}% :                                ${row.get('super', 0):>10.2f}",
        "",
        "Net pay",
        f"  ${row.get('netPay', 0):>10.2f}",
        "",
        "Leave balances (accrued this period)",
        f"  Annual:   {row.get('leaveAccrual', {}).get('annual', 0):>6.4f} h    Personal: {row.get('leaveAccrual', {}).get('personal', 0):>6.4f} h    LSL: {row.get('leaveAccrual', {}).get('lsl', 0):>6.4f} h",
        "",
        "Year to date",
        f"  Gross: ${row.get('ytdGross', 0):>10.2f}    PAYG: ${row.get('ytdTax', 0):>10.2f}    Super: ${row.get('ytdSuper', 0):>10.2f}",
    ]
    # Reuse the tiny PDF assembler from finalize.py — DRY without adding a
    # heavy reportlab dep.
    from routes.finalize import _pdf_from_lines
    blob = _pdf_from_lines(f"Payslip · {row.get('name')} · {run.get('payDate')}", lines,
                            meta={"Run": run_id})
    return Response(content=blob, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="payslip-{run_id}-{staff_id}.pdf"'})


@router.post("/payroll/stp/build")
async def build_stp(data: dict, user: dict = Depends(get_user)):
    """Return the STP2 event body for a pay run — ready to hand off to a
    registered SBR2 submitter (Xero / KeyPay / Reckon / ATO Business Portal)."""
    from services.tenant_settings import get_scoped_singleton
    biz = await get_scoped_singleton(db.business_settings, {"key": "main"}, user.get("businessId")) or {}
    return build_stp2_pay_event(
        employer_abn=biz.get("abn", ""),
        employer_name=biz.get("name", "NUA"),
        pay_date=date.fromisoformat(data["payDate"]),
        period_start=date.fromisoformat(data["periodStart"]),
        period_end=date.fromisoformat(data["periodEnd"]),
        rows=data.get("rows", []),
    )


@router.get("/payroll/roster-compliance")
async def roster_compliance(days_ahead: int = 14, user: dict = Depends(get_user)):
    """Scan upcoming rostered shifts and flag Fair Work / Award violations."""
    # shifts don't carry their own businessId (same pre-existing schema gap
    # as timecards) — scope transitively through this business's own staff.
    staff_ids = {s["id"] for s in await db.auth_users.find(
        {**tenant_scope_filter(user.get("businessId"))}, {"_id": 0, "id": 1}).to_list(500)}
    cutoff = (datetime.now(timezone.utc) + timedelta(days=days_ahead)).isoformat()
    shifts = await db.shifts.find(
        {"start": {"$gte": datetime.now(timezone.utc).isoformat(), "$lte": cutoff},
         "staffId": {"$in": list(staff_ids)}},
        {"_id": 0},
    ).to_list(2000)
    flagged = []
    for s in shifts:
        try:
            issues = roster_compliance_issues(s)
            if issues:
                flagged.append({**s, "issues": issues})
        except Exception:
            continue
    return {
        "windowDays": days_ahead,
        "shiftsScanned": len(shifts),
        "flaggedCount": len(flagged),
        "flagged": flagged,
    }


# ─── Wallet credentials configuration (Apple + Google) ───────────────────
@router.get("/settings/wallet-credentials")
async def wallet_credentials_status(_: dict = Depends(get_user)):
    """Return which wallet cert / key envs are configured (never returns
    the actual secrets)."""
    import os
    apple_ready = all(bool(os.environ.get(k)) for k in ("PASS_TYPE_CERT_PEM", "PASS_TYPE_KEY_PEM", "APPLE_WWDR_CERT_PEM"))
    google_ready = bool(os.environ.get("GOOGLE_WALLET_SERVICE_ACCOUNT_KEY")) and bool(os.environ.get("GOOGLE_WALLET_ISSUER_ID"))
    persisted = await db.wallet_credentials.find_one({"id": "singleton"}, {"_id": 0}) or {}
    return {
        "apple": {
            "envReady": apple_ready,
            "passTypeId": os.environ.get("PASS_TYPE_IDENTIFIER", ""),
            "teamId": os.environ.get("APPLE_TEAM_ID", ""),
            "persistedInDb": bool(persisted.get("apple")),
        },
        "google": {
            "envReady": google_ready,
            "issuerId": os.environ.get("GOOGLE_WALLET_ISSUER_ID", ""),
            "classId": os.environ.get("GOOGLE_WALLET_CLASS_ID", ""),
            "persistedInDb": bool(persisted.get("google")),
        },
    }


@router.post("/settings/wallet-credentials")
async def save_wallet_credentials(body: dict, user: dict = Depends(get_user)):
    """Persist wallet credentials to DB + apply to process env immediately.
    Owner-only. NEVER logged."""
    if user["role"] != "owner":
        raise HTTPException(403, "Owner only")
    import os
    apple = body.get("apple") or {}
    google = body.get("google") or {}
    # Apply to running process env so the current pod picks it up without restart.
    for key, env in [("passTypeCertPem", "PASS_TYPE_CERT_PEM"),
                      ("passTypeKeyPem", "PASS_TYPE_KEY_PEM"),
                      ("appleWwdrCertPem", "APPLE_WWDR_CERT_PEM"),
                      ("passTypeIdentifier", "PASS_TYPE_IDENTIFIER"),
                      ("teamId", "APPLE_TEAM_ID")]:
        v = apple.get(key)
        if v:
            os.environ[env] = v
    for key, env in [("serviceAccountKey", "GOOGLE_WALLET_SERVICE_ACCOUNT_KEY"),
                      ("issuerId", "GOOGLE_WALLET_ISSUER_ID"),
                      ("classId", "GOOGLE_WALLET_CLASS_ID"),
                      ("issuerEmail", "GOOGLE_WALLET_ISSUER_EMAIL")]:
        v = google.get(key)
        if v:
            os.environ[env] = v
    await db.wallet_credentials.update_one(
        {"id": "singleton"},
        {"$set": {"apple": apple, "google": google,
                   "updatedBy": user.get("email"),
                   "updatedAt": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return {"ok": True, "applied": True}


# ─── Load persisted wallet credentials at import time ────────────────────
# Cold-start: pull any DB-persisted certs into process env so wallet_passes
# picks them up on the very first request after a pod restart.
async def _apply_persisted_wallet_credentials() -> None:
    import os
    doc = await db.wallet_credentials.find_one({"id": "singleton"}, {"_id": 0})
    if not doc:
        return
    apple = doc.get("apple") or {}
    google = doc.get("google") or {}
    mapping = {
        "passTypeCertPem": "PASS_TYPE_CERT_PEM",
        "passTypeKeyPem": "PASS_TYPE_KEY_PEM",
        "appleWwdrCertPem": "APPLE_WWDR_CERT_PEM",
        "passTypeIdentifier": "PASS_TYPE_IDENTIFIER",
        "teamId": "APPLE_TEAM_ID",
    }
    for k, e in mapping.items():
        if apple.get(k) and not os.environ.get(e):
            os.environ[e] = apple[k]
    for k, e in [("serviceAccountKey", "GOOGLE_WALLET_SERVICE_ACCOUNT_KEY"),
                  ("issuerId", "GOOGLE_WALLET_ISSUER_ID"),
                  ("classId", "GOOGLE_WALLET_CLASS_ID"),
                  ("issuerEmail", "GOOGLE_WALLET_ISSUER_EMAIL")]:
        if google.get(k) and not os.environ.get(e):
            os.environ[e] = google[k]
