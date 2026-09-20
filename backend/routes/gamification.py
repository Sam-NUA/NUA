from fastapi import APIRouter, Request, Depends
from typing import Optional
from deps import get_user, require_owner, require_owner_or_manager
from database import db
from datetime import datetime, timezone
from middleware.actor_context import tenant_scope_filter
from services.punctuality import shift_punctuality
import uuid, os

router = APIRouter()

# ============ STAFF LEADERBOARD ============
async def compute_staff_performance(business_id: Optional[str] = None) -> list[dict]:
    """Unranked per-staff performance rows — the same composite score the
    leaderboard shows, factored out so other features (e.g. auto-rostering)
    can weigh staff by performance without duplicating this math.

    Scoped by business_id: transactions carry their own businessId so those
    are filtered directly; timecards/tips/roster_shifts don't (pre-existing
    schema gap — same as payroll.py), so those are filtered transitively
    through this business's own staff list instead. Without this, one
    business's leaderboard/tip-pool/roster math was silently computed across
    every tenant's staff and sales combined."""
    staff = await db.auth_users.find(
        {"status": "active", "role": {"$ne": "owner"}, **tenant_scope_filter(business_id)},
        {"_id": 0, "password_hash": 0}).to_list(100)
    staff_ids = {s["id"] for s in staff}
    txns = await db.transactions.find({**tenant_scope_filter(business_id)}, {"_id": 0}).to_list(50000)
    timecards = await db.timecards.find(
        {"clockOut": {"$ne": None}, "staffId": {"$in": list(staff_ids)}}, {"_id": 0}).to_list(50000)
    tips = await db.tips.find({"staffId": {"$in": list(staff_ids)}}, {"_id": 0}).to_list(10000)
    # Every rostered shift ever, keyed by (staffId, date) — used to check
    # each completed timecard against the shift it was actually rostered
    # for, the same pairing preshift_briefing() uses.
    roster_shifts = await db.roster_shifts.find(
        {"staffId": {"$in": list(staff_ids)}}, {"_id": 0}).to_list(20000)
    roster_by_staff_date = {(sh.get("staffId"), sh.get("date")): sh for sh in roster_shifts}

    leaderboard = []
    for s in staff:
        staff_txns = [t for t in txns if t.get("cashier") == s["name"] or t.get("cashierId") == s["id"]]
        staff_tips = [t for t in tips if t.get("staffId") == s["id"] or t.get("staffName") == s["name"]]
        staff_cards = [tc for tc in timecards if tc.get("staffId") == s["id"]]
        total_sales = sum(t.get("total", 0) for t in staff_txns)
        total_txns = len(staff_txns)
        total_tips = sum(t.get("amount", 0) for t in staff_tips)
        total_hours = sum(tc.get("hoursWorked", 0) for tc in staff_cards)
        avg_txn = total_sales / max(total_txns, 1)
        sales_per_hour = total_sales / max(total_hours, 1)

        # Punctuality — only judged against shifts that actually had a
        # rostered start/end time to be measured against; an unscheduled or
        # ad-hoc shift can't be "late" for anything, so it's skipped rather
        # than silently counted as on time or held against them.
        matched = []
        for tc in staff_cards:
            clock_in = tc.get("clockIn") or ""
            sh = roster_by_staff_date.get((s["id"], clock_in[:10]))
            if sh:
                matched.append(shift_punctuality(tc, sh))
        if matched:
            punctuality_rate = sum(1 for m in matched if m["onTime"]) / len(matched)
            late_values = [m["lateMinutes"] for m in matched if m["lateMinutes"] and m["lateMinutes"] > 0]
            avg_late_minutes = round(sum(late_values) / len(late_values), 1) if late_values else 0.0
        else:
            punctuality_rate = None
            avg_late_minutes = 0.0
        # A staff member with no rostered history to check contributes
        # nothing either way — they're not rewarded or punished for a gap
        # in scheduling that isn't their doing.
        punctuality_bonus = round((punctuality_rate * 15) - (avg_late_minutes * 0.5), 2) if punctuality_rate is not None else 0.0

        # Performance score: weighted composite, now including punctuality
        score = round((total_sales * 0.4) + (total_txns * 2) + (total_tips * 3) + (sales_per_hour * 0.5) + punctuality_bonus, 2)

        leaderboard.append({
            "id": s["id"], "name": s["name"], "role": s["role"],
            "totalSales": round(total_sales, 2), "totalTransactions": total_txns,
            "totalTips": round(total_tips, 2), "totalHours": round(total_hours, 2),
            "avgTransaction": round(avg_txn, 2), "salesPerHour": round(sales_per_hour, 2),
            "punctualityRate": round(punctuality_rate, 2) if punctuality_rate is not None else None,
            "avgLateMinutes": avg_late_minutes, "shiftsTracked": len(matched),
            "performanceScore": score,
        })

    return leaderboard


@router.get("/staff/leaderboard")
async def get_staff_leaderboard(user: dict = Depends(get_user)):
    leaderboard = await compute_staff_performance(user.get("businessId"))
    leaderboard.sort(key=lambda x: x["performanceScore"], reverse=True)
    for i, s in enumerate(leaderboard):
        s["rank"] = i + 1

    return {"leaderboard": leaderboard, "generatedAt": datetime.now(timezone.utc).isoformat()}


# ============ SMART TIP DISTRIBUTION (Hours + Performance) ============
@router.post("/tips/smart-distribute")
async def smart_distribute_tips(user: dict = Depends(require_owner)):
    """Distribute pooled tips based on hours worked and performance score"""
    biz = user.get("businessId")

    # Get staff first — tips/timecards are filtered transitively through
    # this business's own staff (see compute_staff_performance's note on
    # why), so a business can't accidentally pool and distribute money
    # figured from another tenant's tips/sales.
    staff = await db.auth_users.find(
        {"status": "active", "role": {"$ne": "owner"}, **tenant_scope_filter(biz)},
        {"_id": 0, "password_hash": 0}).to_list(100)
    staff_ids = {s["id"] for s in staff}

    tips = await db.tips.find(
        {"pooled": True, "distributed": {"$ne": True}, "staffId": {"$in": list(staff_ids)}},
        {"_id": 0}).to_list(10000)
    pool_total = sum(t.get("amount", 0) for t in tips)
    if pool_total <= 0:
        return {"message": "No pooled tips to distribute", "distributed": 0}

    timecards = await db.timecards.find(
        {"clockOut": {"$ne": None}, "staffId": {"$in": list(staff_ids)}}, {"_id": 0}).to_list(50000)
    txns = await db.transactions.find({**tenant_scope_filter(biz)}, {"_id": 0}).to_list(50000)

    staff_weights = []
    total_weight = 0
    for s in staff:
        hours = sum(tc.get("hoursWorked", 0) for tc in timecards if tc.get("staffId") == s["id"])
        sales = sum(t.get("total", 0) for t in txns if t.get("cashier") == s["name"])
        # Weight = hours * (1 + performance_bonus)
        perf_bonus = min(sales / max(sum(t.get("total", 0) for t in txns), 1), 0.5)
        weight = hours * (1 + perf_bonus)
        staff_weights.append({"staff": s, "hours": hours, "sales": sales, "weight": weight})
        total_weight += weight

    if total_weight == 0:
        return {"message": "No staff hours recorded", "distributed": 0}

    distributions = []
    for sw in staff_weights:
        if sw["weight"] <= 0:
            continue
        share = round((sw["weight"] / total_weight) * pool_total, 2)
        distributions.append({
            "staffId": sw["staff"]["id"], "staffName": sw["staff"]["name"],
            "hours": round(sw["hours"], 2), "performanceWeight": round(sw["weight"], 2),
            "share": share,
        })

    # Mark tips as distributed
    tip_ids = [t.get("id") for t in tips]
    if tip_ids:
        await db.tips.update_many({"id": {"$in": tip_ids}}, {"$set": {"distributed": True}})

    # Log distribution
    dist_record = {
        "id": f"DIST-{str(uuid.uuid4())[:8].upper()}",
        "type": "smart", "poolTotal": round(pool_total, 2),
        "distributions": distributions,
        "distributedAt": datetime.now(timezone.utc).isoformat(),
    }
    await db.tip_distributions.insert_one(dist_record)
    dist_record.pop("_id", None)

    return dist_record

# ============ QUARTERLY REVIEW (Top/Worst Items + AI Alternatives) ============
@router.get("/reports/quarterly-review")
async def quarterly_review(user: dict = Depends(require_owner_or_manager)):
    scope = tenant_scope_filter(user.get("businessId"))
    txns = await db.transactions.find(scope, {"_id": 0}).to_list(50000)
    products = await db.products.find(scope, {"_id": 0}).to_list(10000)

    # Calculate item performance
    item_stats = {}
    for t in txns:
        for item in t.get("items", []):
            pid = item.get("productId", "")
            if pid not in item_stats:
                p = next((pr for pr in products if pr.get("id") == pid), {})
                item_stats[pid] = {
                    "id": pid, "name": item.get("productName", ""), "category": p.get("category", ""),
                    "price": p.get("price", 0), "cost": p.get("cost", 0),
                    "qtySold": 0, "revenue": 0,
                }
            item_stats[pid]["qtySold"] += item.get("quantity", 0)
            item_stats[pid]["revenue"] += item.get("price", 0) * item.get("quantity", 0)

    for item in item_stats.values():
        item["profit"] = round(item["revenue"] - (item["cost"] * item["qtySold"]), 2)
        item["margin"] = round((item["profit"] / max(item["revenue"], 0.01)) * 100, 1)

    sorted_items = sorted(item_stats.values(), key=lambda x: x["revenue"], reverse=True)
    top_sellers = sorted_items[:10]
    worst_sellers = sorted_items[-10:] if len(sorted_items) > 10 else []
    # Items with negative or very low margin
    underperformers = [i for i in sorted_items if i["margin"] < 20 and i["qtySold"] > 0]

    return {
        "period": "quarterly",
        "topSellers": top_sellers,
        "worstSellers": worst_sellers,
        "underperformers": underperformers[:10],
        "totalItems": len(sorted_items),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }

@router.post("/reports/quarterly-review/ai-alternatives")
async def quarterly_ai_alternatives(data: dict, _: dict = Depends(require_owner)):
    """AI suggests alternatives for worst-performing items"""

    items = data.get("items", [])
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        api_key = os.environ.get("EMERGENT_LLM_KEY", "")
        chat = LlmChat(api_key=api_key, session_id=f"quarterly-{uuid.uuid4()}", system_message="You are a restaurant menu consultant. Suggest replacement items for underperforming menu items. Be specific with names, pricing, and why they'd perform better. Keep each suggestion to 2-3 sentences.")
        chat.with_model("openai", "gpt-5.2")

        items_text = "\n".join([f"- {i.get('name')} (${i.get('price')}, margin {i.get('margin')}%, sold {i.get('qtySold')}x)" for i in items[:10]])
        prompt = f"""These menu items are underperforming. Suggest a replacement for each that would:
1. Appeal to the same customer segment
2. Have better margins (target 60%+)
3. Use similar or simpler ingredients

Underperforming items:
{items_text}

For each item, suggest ONE replacement with: name, suggested price, estimated food cost %, and brief reasoning."""

        msg = UserMessage(text=prompt)
        response = await chat.send_message(msg)
        return {"suggestions": response, "generatedAt": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        return {"suggestions": f"AI unavailable: {str(e)}", "generatedAt": datetime.now(timezone.utc).isoformat()}

# ============ CATEGORY-WISE PRINT ROUTING ============
# Drinks must reach the bar, not the kitchen. The seeded drinks catalog uses
# real category names ("Cocktails", "Wine — Red", "Spirits — Gin", …), so
# routing on the generic words "Beverages"/"Alcohol" alone silently sent every
# Negroni to the kitchen printer. These are listed explicitly, and anything
# else in a drinks category group falls back to the bar via _route_for_item.
# Routing defaults live with the routing logic so the two cannot drift.
from services.print_routing import DEFAULT_PRINT_ROUTING


@router.get("/print-routing/config")
async def get_print_routing(user: dict = Depends(get_user)):
    """Returns the current print-routing config. Auto-heals legacy shapes
    (e.g. an old dict-shaped `routes` field from a pre-v27 save) so the SPA
    can always call `config.routes.map(...)` without crashing.

    Previously had no auth dependency at all — any caller with no
    credential could read a business's print-routing config (which
    printer each category routes to). Also previously a single global
    document shared by every business on the deployment; see
    services/tenant_settings.py.
    """
    import copy
    from services.tenant_settings import get_setting
    defaults = copy.deepcopy(DEFAULT_PRINT_ROUTING)
    value = await get_setting("print_routing", user.get("businessId"))
    if not value:
        return defaults

    cfg = value if isinstance(value, dict) else {}
    # Coerce legacy `routes` shapes into a list.
    routes = cfg.get("routes")
    if isinstance(routes, dict):
        # Old shape: {"kitchen": "Kitchen Printer", ...}. Convert to the new
        # array-of-route-objects, preserving category → printer intent.
        cfg["routes"] = [
            {"category": cat.title(), "printer": prn, "priority": 2}
            for cat, prn in routes.items() if isinstance(prn, str)
        ]
    elif routes is None or not isinstance(routes, list):
        cfg["routes"] = defaults["routes"]
    cfg.setdefault("enabled", True)
    cfg.setdefault("defaultPrinter", defaults["defaultPrinter"])
    cfg.setdefault("defaultPriority", defaults["defaultPriority"])
    return cfg


@router.post("/print-routing/config")
async def save_print_routing(data: dict, user: dict = Depends(require_owner_or_manager)):
    """Persist print-routing config. Validates `routes` is an array of
    `{category, printer, priority}` objects — rejects legacy dict shapes so
    the SPA never crashes on a subsequent read."""
    from fastapi import HTTPException
    routes = data.get("routes", [])
    if not isinstance(routes, list):
        raise HTTPException(400, "`routes` must be an array of {category, printer, priority}")
    clean = []
    for r in routes:
        if not isinstance(r, dict) or not r.get("category") or not r.get("printer"):
            continue
        try:
            pr = int(r.get("priority", 2))
        except Exception:
            pr = 2
        clean.append({"category": r["category"], "printer": r["printer"], "priority": pr})
    payload = {
        "enabled": bool(data.get("enabled", True)),
        "routes": clean,
        "defaultPrinter": data.get("defaultPrinter") or "Kitchen Printer",
        "defaultPriority": int(data.get("defaultPriority") or 2),
    }
    from services.tenant_settings import set_setting
    await set_setting("print_routing", payload, user.get("businessId"))
    return {"message": "Print routing saved", "config": payload}

@router.post("/print-routing/send")
async def send_to_printers(data: dict, _: dict = Depends(get_user)):
    """Route order items to station printers.

    The routing itself lives in services/print_routing.py so that firing a
    single course can queue dockets through exactly the same path.
    """
    from services import print_routing
    records = await print_routing.route_and_queue(
        data.get("items", []),
        order_id=data.get("orderId"),
        table_number=data.get("tableNumber"),
    )
    return {"jobs": records, "totalPrinters": len(records)}

@router.get("/print-routing/queue")
async def get_print_queue(request: Request, printer: str = None):
    query = {"status": {"$in": ["queued", "printing"]}}
    if printer:
        query["printer"] = printer
    jobs = await db.print_jobs.find(query, {"_id": 0}).sort("priority", 1).to_list(100)
    return jobs

@router.post("/print-routing/complete/{job_id}")
async def complete_print_job(job_id: str):
    await db.print_jobs.update_one({"id": job_id}, {"$set": {"status": "printed", "printedAt": datetime.now(timezone.utc).isoformat()}})
    return {"message": "Print job completed"}
