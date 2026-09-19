"""
Ash — NUA's autonomous operating layer.

Sixteen insight generators, each returning zero or more `Insight`s that
land in `db.ash_insights`. Insights are pure — they *never* mutate the
underlying system. Recommended actions are surfaced to the user; the
Rules Engine + Approval Queue handle any execution.

Design
──────
• Each generator is a stateless async function returning `List[Insight]`.
• The `run_all_insights()` entry point runs them concurrently and upserts
  by (category, key) so repeat runs replace stale rows.
• The weekly summary is the ONE LLM-narrated output. Everything else is
  deterministic heuristics that scale.
"""
from __future__ import annotations
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from database import db
from middleware.actor_context import tenant_scope_filter, get_actor_context, _actor_ctx
import asyncio
import os
import uuid
import logging
import statistics

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d) -> str:
    return d.isoformat() if hasattr(d, "isoformat") else str(d)


def _mk(category: str, key: str, severity: str, title: str, body: str,
        actions: Optional[List[Dict[str, Any]]] = None,
        data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "category": category,
        "key": key,
        "severity": severity,
        "title": title,
        "body": body,
        "recommendedActions": actions or [],
        "data": data or {},
        "createdAt": _now().isoformat(),
    }


# ─── 1. Staffing shortage ────────────────────────────────────────────────
async def predict_staffing_shortage() -> List[Dict[str, Any]]:
    tomorrow = (_now() + timedelta(days=1)).date()
    reservations = await db.reservations.count_documents({**tenant_scope_filter(),
        "dateTime": {"$regex": f"^{tomorrow.isoformat()}"},
    })
    rostered = await db.shifts.count_documents({**tenant_scope_filter(),
        "date": tomorrow.isoformat(), "status": {"$in": ["scheduled", "confirmed"]},
    })
    if reservations >= 20 and rostered < max(3, reservations // 8):
        return [_mk("staffing", "shortage_tomorrow", "high",
                     f"Understaffed for tomorrow — {reservations} bookings vs {rostered} staff",
                     f"Forecast covers exceed rostered hours; recommend adding {max(1, reservations // 8 - rostered)} staff.",
                     actions=[{"type": "recommend_roster_add", "params": {"date": tomorrow.isoformat()}}],
                     data={"reservations": reservations, "rostered": rostered})]
    return []


# ─── 2. Theft detection ──────────────────────────────────────────────────
async def detect_theft_signals() -> List[Dict[str, Any]]:
    since = (_now() - timedelta(days=7)).isoformat()
    voids = await db.transactions.find({**tenant_scope_filter(), "status": "voided", "timestamp": {"$gte": since}}, {"_id": 0}).to_list(2000)
    hits: List[Dict[str, Any]] = []
    by_staff: Dict[str, int] = {}
    for v in voids:
        by_staff[v.get("cashier", "unknown")] = by_staff.get(v.get("cashier", "unknown"), 0) + 1
    for cashier, n in by_staff.items():
        if n >= 5:
            hits.append(_mk("theft", f"voids_{cashier}", "warning",
                             f"Unusual voids by {cashier} — {n} in 7 days",
                             "Review the transaction log; consider a manager-only void policy.",
                             actions=[{"type": "review_voids", "params": {"cashier": cashier}}],
                             data={"voids": n, "cashier": cashier}))

    # Pour variance — flagged stocktake reconciles beyond threshold.
    try:
        recs = await db.stocktake_reconciles.find(
            {**tenant_scope_filter(), "reconciledAt": {"$gte": since}, "flagged": True},
            {"_id": 0},
        ).sort("reconciledAt", -1).to_list(500)
    except Exception:
        recs = []
    for r in recs:
        variance = float(r.get("variance") or 0)
        pct = float(r.get("variancePct") or 0)
        if variance <= 0:
            continue    # gain, not loss — not a theft signal
        su_id = r.get("stockUnitId") or "?"
        # Severity by size: 15% -> warning, 25% -> high
        sev = "high" if pct >= 0.25 else "warning"
        hits.append(_mk("theft", f"pour_variance_{su_id}_{r.get('reconciledAt', '')[:10]}", sev,
                         f"Pour variance {pct*100:.1f}% on stock unit {su_id[:8]}",
                         f"Stocktake counted {r.get('counted')}{r.get('uom')} — theoretical was "
                         f"{r.get('theoretical')}{r.get('uom')} (variance {variance:.1f}{r.get('uom')}).",
                         actions=[{"type": "review_pour_variance",
                                    "params": {"stockUnitId": su_id, "reconciledAt": r.get("reconciledAt")}}],
                         data={"variance": variance, "variancePct": pct}))
    return hits


# ─── 3. Fraud detection ─────────────────────────────────────────────────
async def detect_fraud_signals() -> List[Dict[str, Any]]:
    since = (_now() - timedelta(days=1)).isoformat()
    refunds = await db.refunds.find({**tenant_scope_filter(), "createdAt": {"$gte": since}}, {"_id": 0}).to_list(1000) \
        if await db.refunds.count_documents({**tenant_scope_filter(), }) else []
    if len(refunds) >= 10:
        return [_mk("fraud", "refund_velocity", "high",
                     f"Refund velocity spike — {len(refunds)} refunds in 24h",
                     "Verify each refund. High velocity often indicates skimming.",
                     actions=[{"type": "review_refunds", "params": {"since": since}}],
                     data={"count": len(refunds)})]
    return []


# ─── 4. Pricing recommendations ─────────────────────────────────────────
async def recommend_pricing() -> List[Dict[str, Any]]:
    products = await db.products.find({**tenant_scope_filter(), }, {"_id": 0}).to_list(2000)
    hits = []
    for p in products:
        cost = float(p.get("cost") or 0)
        price = float(p.get("price") or 0)
        if cost > 0 and price > 0:
            margin = (price - cost) / price
            if margin < 0.30:
                target = round(cost / 0.65, 2)
                hits.append(_mk("pricing", f"low_margin_{p['id']}", "notice",
                                 f"Low margin on {p.get('name')} — {margin*100:.1f}%",
                                 f"Cost ${cost:.2f} vs price ${price:.2f}. Suggested price ${target:.2f} to hit 35% margin.",
                                 actions=[{"type": "adjust_price", "params": {"productId": p["id"], "newPrice": target}}],
                                 data={"currentPrice": price, "cost": cost, "margin": round(margin, 3)}))
    return hits[:10]


# ─── 5. Promotion suggestions ──────────────────────────────────────────
async def suggest_promotions() -> List[Dict[str, Any]]:
    products = await db.products.find({**tenant_scope_filter(), "stock": {"$gt": 30}}, {"_id": 0}).limit(20).to_list(20)
    hits = []
    for p in products[:3]:
        hits.append(_mk("promotion", f"slow_mover_{p['id']}", "info",
                         f"Slow mover: {p.get('name')} — stock {p.get('stock')}",
                         "Consider a 15% happy-hour push, a bundle with a fast-mover, or a limited-time voucher.",
                         actions=[{"type": "create_promotion", "params": {"productId": p["id"], "discount": 15}}],
                         data={"stock": p.get("stock")}))
    return hits


# ─── 6. Food waste prediction ──────────────────────────────────────────
async def predict_food_waste() -> List[Dict[str, Any]]:
    ingredients = await db.ingredients.find({**tenant_scope_filter(), }, {"_id": 0}).to_list(1000) \
        if await db.ingredients.count_documents({**tenant_scope_filter(), }) else []
    hits = []
    for i in ingredients:
        stock = float(i.get("stock") or 0)
        avg_daily = float(i.get("avgDailyUse") or 0)
        expiry = i.get("expiryDate")
        if avg_daily > 0 and expiry:
            try:
                dte = (datetime.fromisoformat(expiry).date() - _now().date()).days
                if dte < (stock / avg_daily) and dte < 5:
                    hits.append(_mk("waste", f"expiring_{i['id']}", "warning",
                                     f"{i.get('name')} will expire before it's used",
                                     f"Stock {stock:.1f} vs {avg_daily:.1f}/day, expires in {dte} days.",
                                     actions=[{"type": "create_promotion", "params": {"ingredientId": i["id"]}}],
                                     data={"daysLeft": dte, "stock": stock}))
            except Exception:
                pass

    # Wastage-event spike detection (measured stock).
    try:
        since = (_now() - timedelta(days=7)).isoformat()
        events = await db.wastage_events.find(
            {**tenant_scope_filter(), "createdAt": {"$gte": since}, "deletedAt": None}, {"_id": 0},
        ).to_list(2000)
    except Exception:
        events = []
    if events:
        by_su: Dict[str, Dict[str, float]] = {}
        for e in events:
            su_id = e.get("stockUnitId") or e.get("openContainerId") or "?"
            r = by_su.setdefault(su_id, {"amount": 0.0, "count": 0, "reasons": {}})
            r["amount"] += float(e.get("amount") or 0)
            r["count"] += 1
            reason = e.get("reason") or "other"
            r["reasons"][reason] = r["reasons"].get(reason, 0) + 1
        for su_id, r in by_su.items():
            if r["count"] >= 3 or r["amount"] >= 500:
                # Look up product name via stock unit → product
                pname = "?"
                if su_id and su_id != "?":
                    try:
                        su_row = await db.stock_units.find_one({**tenant_scope_filter(), "id": su_id}, {"_id": 0})
                        if su_row:
                            p = await db.products.find_one({**tenant_scope_filter(), "id": su_row.get("productId")}, {"_id": 0, "name": 1})
                            if p: pname = p.get("name") or pname
                    except Exception:
                        pass
                top_reason = max(r["reasons"].items(), key=lambda x: x[1])[0] if r["reasons"] else "unknown"
                hits.append(_mk("waste", f"wastage_spike_{su_id}", "warning",
                                 f"Wastage spike on {pname} — {r['count']} events / {r['amount']:.0f} units in 7 days",
                                 f"Top reason: {top_reason}. Investigate pour training, storage or supplier quality.",
                                 actions=[{"type": "review_wastage", "params": {"stockUnitId": su_id}}],
                                 data={**r, "productName": pname}))
    return hits[:15]


# ─── 7. Labour cost anomalies ─────────────────────────────────────────
async def detect_labour_anomalies() -> List[Dict[str, Any]]:
    # Wages ÷ revenue over the last 7 days
    since = (_now() - timedelta(days=7)).isoformat()
    txns = await db.transactions.find({**tenant_scope_filter(), "timestamp": {"$gte": since}}, {"_id": 0}).to_list(20000)
    revenue = sum(float(t.get("total") or 0) for t in txns) or 1
    # Very rough — use most recent pay run total or estimate from shifts
    pay_runs = await db.payroll_runs.find({**tenant_scope_filter(), }, {"_id": 0}).sort("payDate", -1).limit(2).to_list(2) \
        if await db.payroll_runs.count_documents({**tenant_scope_filter(), }) else []
    wages = sum(float(r.get("gross") or 0) for r in pay_runs)
    ratio = wages / revenue if revenue else 0
    if ratio > 0.35:
        return [_mk("labour", "high_wage_ratio", "warning",
                     f"Labour cost {ratio*100:.1f}% of revenue — target 25–30%",
                     f"Wages ${wages:,.0f} vs revenue ${revenue:,.0f} over the last 7 days.",
                     actions=[{"type": "review_roster", "params": {}}],
                     data={"wages": wages, "revenue": revenue, "ratio": round(ratio, 3)})]
    return []


# ─── 8. Menu underperformance ─────────────────────────────────────────
async def detect_menu_underperformance() -> List[Dict[str, Any]]:
    since = (_now() - timedelta(days=30)).isoformat()
    txns = await db.transactions.find({**tenant_scope_filter(), "timestamp": {"$gte": since}}, {"_id": 0}).to_list(20000)
    sales_by_product: Dict[str, int] = {}
    for t in txns:
        for i in (t.get("items") or []):
            pid = i.get("productId")
            if pid:
                sales_by_product[pid] = sales_by_product.get(pid, 0) + int(i.get("quantity") or 1)
    if len(sales_by_product) < 5:
        return []
    med = statistics.median(sales_by_product.values())
    low = [pid for pid, n in sales_by_product.items() if n < max(1, med * 0.2)]
    hits = []
    for pid in low[:5]:
        p = await db.products.find_one({**tenant_scope_filter(), "id": pid}, {"_id": 0})
        if p:
            hits.append(_mk("menu", f"underperformer_{pid}", "info",
                             f"{p.get('name')} sold only {sales_by_product[pid]} in 30 days",
                             "Consider re-engineering, repositioning on the menu, or 86'ing it.",
                             actions=[{"type": "review_menu_item", "params": {"productId": pid}}],
                             data={"sold": sales_by_product[pid], "median": med}))
    return hits


# ─── 9-10. Weather + public holiday demand ────────────────────────────
async def forecast_weather_impact() -> List[Dict[str, Any]]:
    """Simple stub — pulls yesterday's cover count vs the day before as
    a proxy signal until a real weather API is wired up."""
    d1 = (_now() - timedelta(days=1)).date().isoformat()
    d2 = (_now() - timedelta(days=2)).date().isoformat()
    c1 = await db.transactions.count_documents({**tenant_scope_filter(), "timestamp": {"$regex": f"^{d1}"}})
    c2 = await db.transactions.count_documents({**tenant_scope_filter(), "timestamp": {"$regex": f"^{d2}"}})
    if c2 > 10 and c1 < c2 * 0.5:
        return [_mk("weather", "rain_impact", "info",
                     "Cover drop yesterday suggests weather impact",
                     f"Covers {c1} vs {c2} the day before — check the weather feed and consider pre-emptive delivery push.",
                     actions=[{"type": "boost_delivery", "params": {}}],
                     data={"yesterday": c1, "priorDay": c2})]
    return []


async def forecast_public_holiday_demand() -> List[Dict[str, Any]]:
    """Look ahead 7 days for known public holidays (heuristic list)."""
    au_holidays = {"01-01": "New Year's Day", "01-26": "Australia Day",
                   "04-25": "ANZAC Day", "12-25": "Christmas Day", "12-26": "Boxing Day"}
    hits = []
    for i in range(7):
        d = (_now() + timedelta(days=i)).date()
        key = d.strftime("%m-%d")
        if key in au_holidays:
            hits.append(_mk("demand", f"holiday_{key}_{d.year}", "info",
                             f"{au_holidays[key]} coming in {i} days",
                             "Historical bookings for public holidays run 2× normal — pre-load stock and staff.",
                             actions=[{"type": "boost_roster", "params": {"date": d.isoformat()}}],
                             data={"date": d.isoformat(), "holiday": au_holidays[key]}))
    return hits


# ─── 11. Purchasing recommendations ───────────────────────────────────
async def recommend_purchasing() -> List[Dict[str, Any]]:
    products = await db.products.find({**tenant_scope_filter(), "stock": {"$gte": 0}}, {"_id": 0}).to_list(2000)
    hits = []
    # Lazy import to avoid a cycle
    from services import measured_inventory_service as _mi
    for p in products:
        stock = float(p.get("stock") or 0)
        par = float(p.get("parLevel") or p.get("lowStockThreshold") or 5)

        # Measured-stock: fold currently-open containers into the available count.
        try:
            info = await _mi.reorder_available(p["id"])
        except Exception:
            info = {"measured": False}
        effective = stock + float(info.get("partial") or 0) if info.get("measured") else stock

        if effective < par:
            reorder_qty = max(1, int(par * 2 - effective))
            body_note = f"Suggested order quantity: {reorder_qty}"
            if info.get("measured"):
                body_note += (f" · sealed {info.get('sealed', 0)} + open "
                              f"{info.get('partial', 0):.2f} = {info.get('equivalent', 0):.2f} eqv units")
            hits.append(_mk("purchasing", f"reorder_{p['id']}", "notice",
                             f"Reorder {p.get('name')} — available {effective:.2f} < par {par:.0f}",
                             body_note,
                             actions=[{"type": "create_purchase_order",
                                        "params": {"productId": p["id"], "quantity": reorder_qty}}],
                             data={"stock": stock, "par": par, "reorderQty": reorder_qty,
                                    "measured": info}))
    return hits[:10]


# ─── 12. Roster change recommendations ────────────────────────────────
async def recommend_roster_changes() -> List[Dict[str, Any]]:
    # Simple: if forecasted bookings today > threshold and current shifts less than needed
    today = _now().date().isoformat()
    bookings_today = await db.reservations.count_documents({**tenant_scope_filter(), "dateTime": {"$regex": f"^{today}"}})
    rostered = await db.shifts.count_documents({**tenant_scope_filter(), "date": today})
    if bookings_today >= 15 and rostered < max(3, bookings_today // 8):
        return [_mk("roster", "roster_gap_today", "high",
                     f"Roster gap today — {bookings_today} bookings, {rostered} shifts scheduled",
                     "Consider calling in an on-call, extending an existing shift, or reallocating cross-trained staff.",
                     actions=[{"type": "recommend_roster_add", "params": {"date": today}}],
                     data={"bookings": bookings_today, "rostered": rostered})]
    return []


# ─── 13. Staff burnout risk ───────────────────────────────────────────
async def predict_staff_burnout() -> List[Dict[str, Any]]:
    since = (_now() - timedelta(days=14)).isoformat()
    time_entries = await db.time_entries.find({**tenant_scope_filter(), "clockIn": {"$gte": since}}, {"_id": 0}).to_list(5000) \
        if await db.time_entries.count_documents({**tenant_scope_filter(), }) else []
    hours_by_staff: Dict[str, float] = {}
    for e in time_entries:
        hours_by_staff[e.get("staffId", "?")] = hours_by_staff.get(e.get("staffId", "?"), 0) + float(e.get("hours") or 0)
    hits = []
    for sid, hrs in hours_by_staff.items():
        if hrs > 80:  # >40h/wk for 2 weeks
            hits.append(_mk("burnout", f"burnout_{sid}", "warning",
                             f"Staff {sid} has worked {hrs:.1f} hours in the last 14 days",
                             "High risk of burnout. Consider mandating a day off or redistributing shifts.",
                             actions=[{"type": "schedule_rest_day", "params": {"staffId": sid}}],
                             data={"hours": hrs}))
    return hits


# ─── 14. Customer churn prediction ────────────────────────────────────
async def predict_customer_churn() -> List[Dict[str, Any]]:
    customers = await db.customers.find({**tenant_scope_filter(), "visits": {"$gte": 5}}, {"_id": 0}).limit(500).to_list(500)
    hits = []
    for c in customers:
        last = c.get("lastVisit")
        if last:
            try:
                dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                days = (_now() - dt).days
                # Higher tier → churn faster to detect
                threshold = 30 if c.get("membershipTier") in ("Platinum", "VIP") else 60
                if days > threshold:
                    hits.append(_mk("churn", f"churn_{c['id']}", "notice",
                                     f"{c.get('name')} hasn't visited in {days} days",
                                     f"Historical visit cadence suggests churn risk. Send a win-back offer.",
                                     actions=[{"type": "issue_voucher",
                                                "params": {"customerId": c["id"], "value": 15,
                                                            "label": "We miss you"}}],
                                     data={"daysSinceLastVisit": days, "tier": c.get("membershipTier")}))
            except Exception:
                pass
    return hits[:10]


# ─── 15. Menu engineering matrix ──────────────────────────────────────
async def recommend_menu_engineering() -> List[Dict[str, Any]]:
    since = (_now() - timedelta(days=30)).isoformat()
    txns = await db.transactions.find({**tenant_scope_filter(), "timestamp": {"$gte": since}}, {"_id": 0}).to_list(20000)
    sales: Dict[str, Dict[str, float]] = {}
    for t in txns:
        for i in (t.get("items") or []):
            pid = i.get("productId")
            if not pid: continue
            r = sales.setdefault(pid, {"units": 0, "revenue": 0})
            r["units"] += float(i.get("quantity") or 1)
            r["revenue"] += float(i.get("price") or 0) * float(i.get("quantity") or 1)
    if len(sales) < 4:
        return []
    med_units = statistics.median(v["units"] for v in sales.values())
    med_rev = statistics.median(v["revenue"] for v in sales.values())
    hits = []
    for pid, v in sales.items():
        q = None
        if v["units"] >= med_units and v["revenue"] >= med_rev: q = "Star"
        elif v["units"] >= med_units: q = "Plow-Horse"
        elif v["revenue"] >= med_rev: q = "Puzzle"
        else: q = "Dog"
        if q in ("Dog", "Puzzle"):
            p = await db.products.find_one({**tenant_scope_filter(), "id": pid}, {"_id": 0})
            if p:
                msg = "Consider removing" if q == "Dog" else "Consider repositioning higher on the menu / renaming"
                hits.append(_mk("menu_engineering", f"me_{pid}", "info" if q == "Puzzle" else "warning",
                                 f"{p.get('name')} classified as {q}",
                                 msg,
                                 actions=[{"type": "review_menu_item", "params": {"productId": pid}}],
                                 data={"quadrant": q, **v}))
    return hits[:8]


# ─── 16. Weekly summary — the ONE LLM call ────────────────────────────
async def generate_weekly_summary() -> Optional[Dict[str, Any]]:
    since = (_now() - timedelta(days=7)).isoformat()
    txns = await db.transactions.find({**tenant_scope_filter(), "timestamp": {"$gte": since}}, {"_id": 0}).to_list(20000)
    revenue = sum(float(t.get("total") or 0) for t in txns)
    covers = len(txns)
    bookings = await db.reservations.count_documents({**tenant_scope_filter(), "createdAt": {"$gte": since}})
    refunds = await db.refunds.count_documents({**tenant_scope_filter(), "createdAt": {"$gte": since}}) if await db.refunds.count_documents({**tenant_scope_filter(), }) else 0
    top = await db.customers.find({**tenant_scope_filter(), }, {"_id": 0}).sort("totalSpent", -1).limit(3).to_list(3)

    prompt = f"""Write a warm, insightful 4-sentence business summary for the last 7 days.
- Revenue: ${revenue:,.2f}
- Covers: {covers}
- New bookings: {bookings}
- Refunds: {refunds}
- Top guests: {', '.join(c.get('name','?') for c in top)}
End with ONE specific recommendation."""
    summary_text = None
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        key = os.environ.get("EMERGENT_LLM_KEY")
        if key:
            chat = LlmChat(api_key=key, session_id=f"ash-{uuid.uuid4()}",
                            system_message="You are Ash, NUA's hospitality business analyst. Warm, concrete, brief.")\
                .with_model("openai", "gpt-5.2")
            summary_text = await chat.send_message(UserMessage(text=prompt))
    except Exception as e:
        logger.warning(f"[ash weekly] LLM fallback: {e}")
    if not summary_text:
        summary_text = (
            f"This week you booked ${revenue:,.2f} across {covers} covers with {bookings} new reservations and "
            f"{refunds} refunds. "
            + (f"Top guests included {', '.join(c.get('name','?') for c in top)}. " if top else "")
            + "Focus recommendation: run a weekend loyalty push to top-tier guests to accelerate visits."
        )
    doc = _mk("summary", f"weekly_{_now().date().isoformat()}", "info",
                "Weekly business summary", summary_text,
                data={"revenue": round(revenue, 2), "covers": covers, "bookings": bookings, "refunds": refunds})
    return doc


# ═════════════════════════════════════════════════════════════════════════
# Runner
# ═════════════════════════════════════════════════════════════════════════
GENERATORS = [
    ("staffing", predict_staffing_shortage),
    ("theft", detect_theft_signals),
    ("fraud", detect_fraud_signals),
    ("pricing", recommend_pricing),
    ("promotion", suggest_promotions),
    ("waste", predict_food_waste),
    ("labour", detect_labour_anomalies),
    ("menu", detect_menu_underperformance),
    ("weather", forecast_weather_impact),
    ("demand", forecast_public_holiday_demand),
    ("purchasing", recommend_purchasing),
    ("roster", recommend_roster_changes),
    ("burnout", predict_staff_burnout),
    ("churn", predict_customer_churn),
    ("menu_engineering", recommend_menu_engineering),
]


async def run_all_insights(include_summary: bool = False, business_id: Optional[str] = None) -> Dict[str, Any]:
    """Run every generator within one verified tenant and restore caller context."""
    business_id = business_id or get_actor_context().get("businessId")
    if not business_id:
        raise ValueError("Business context required for insight generation")
    token = _actor_ctx.set({**get_actor_context(), "businessId": business_id})
    try:
        return await _run_scoped_insights(include_summary, business_id)
    finally:
        _actor_ctx.reset(token)


async def _run_scoped_insights(include_summary: bool, business_id: str) -> Dict[str, Any]:
    tasks = [g() for _, g in GENERATORS]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    all_insights: List[Dict[str, Any]] = []
    per_category: Dict[str, int] = {}
    errors: Dict[str, str] = {}
    for (name, _), r in zip(GENERATORS, results):
        if isinstance(r, Exception):
            errors[name] = str(r)
            continue
        for ins in r:
            all_insights.append(ins)
            per_category[ins["category"]] = per_category.get(ins["category"], 0) + 1

    if include_summary:
        try:
            weekly = await generate_weekly_summary()
            if weekly:
                all_insights.append(weekly)
                per_category["summary"] = 1
        except Exception as e:
            errors["summary"] = str(e)

    # Upsert into `ash_insights`, indexed by (category, key, businessId) —
    # businessId is part of the key itself, not just a stamped field, so two
    # businesses' same-named insight can never collide on one document.
    for ins in all_insights:
        ins["businessId"] = business_id
        await db.ash_insights.update_one(
            {"category": ins["category"], "key": ins["key"], "businessId": business_id},
            {"$set": ins, "$setOnInsert": {"firstSeenAt": ins["createdAt"]}},
            upsert=True,
        )
    # Mark stale insights (not touched this run) as resolved — scoped to
    # this business's own insights, so running the scan for one business
    # never resolves another business's still-active ones.
    fresh_keys = [(i["category"], i["key"]) for i in all_insights]
    resolved = 0
    if fresh_keys:
        cursor = db.ash_insights.find(
            {"resolvedAt": None, **tenant_scope_filter(business_id)},
            {"_id": 0, "category": 1, "key": 1})
        async for row in cursor:
            if (row["category"], row["key"]) not in fresh_keys:
                await db.ash_insights.update_one(
                    {"category": row["category"], "key": row["key"], **tenant_scope_filter(business_id)},
                    {"$set": {"resolvedAt": _now().isoformat()}},
                )
                resolved += 1
    return {"generated": len(all_insights), "perCategory": per_category,
            "errors": errors, "autoResolved": resolved}
