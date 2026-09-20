from fastapi import APIRouter, HTTPException, Depends
from deps import get_user, require_owner, require_owner_or_manager, optional_user
from database import db
from middleware.actor_context import tenant_scope_filter, tenant_owns_strict
from datetime import datetime, timezone, timedelta
from typing import Optional
import uuid
import json

import os


router = APIRouter()

# ============ BUSINESS SETTINGS ============
@router.get("/business/settings")
async def get_business_settings(user: dict = Depends(get_user)):
    from services.tenant_settings import get_scoped_singleton
    biz = await get_scoped_singleton(db.business_settings, {"key": "main"}, user.get("businessId"))
    return biz or {"name": "NUA", "abn": "", "address": "", "phone": "", "email": "", "taxId": ""}

@router.post("/business/settings")
async def save_business_settings(data: dict, user: dict = Depends(require_owner_or_manager)):
    from services.tenant_settings import set_scoped_singleton
    await set_scoped_singleton(db.business_settings, {"key": "main"}, data, user.get("businessId"))
    return {"message": "Business settings saved"}


# Brand theme (colors) — shared across every terminal/device for the business,
# not just the browser that changed it. The Settings color pickers still give
# an instant local preview as you drag/type; "Save" is what makes it apply
# everywhere else too.
@router.get("/business/theme")
async def get_business_theme(user: Optional[dict] = Depends(optional_user)):
    """Deliberately optional_user, not required auth: ThemeProvider mounts
    this call at the app root, above both staff routes and every guest-
    facing page (booking portal, waitlist tracking, loyalty rewards) — a
    guest visiting one of those must keep getting a theme back, not a 401.
    A guest carries no business signal (same deferred gap as public.py/
    table_ordering.py), so falls back to the shared legacy theme exactly
    as before this fix; an authenticated staff member now gets their own
    business's theme once one has been saved."""
    from services.tenant_settings import get_setting
    return await get_setting("business_theme", (user or {}).get("businessId"))


@router.post("/business/theme")
async def save_business_theme(data: dict, user: dict = Depends(require_owner_or_manager)):
    from services.tenant_settings import set_setting
    allowed = {"primary", "secondary", "accent", "background", "text", "sidebar"}
    theme = {k: v for k, v in data.items() if k in allowed and isinstance(v, str)}
    await set_setting("business_theme", theme, user.get("businessId"))
    return theme


# POS layout — the three regions (category bar, product grid, cart) stay
# structurally fixed; what's configurable is what's *within* them. A POS is
# touch/speed-critical, so free-form drag-and-drop positioning was
# deliberately ruled out — a badly-arranged custom layout becomes a live-
# service liability, not a convenience, and it would fight directly against
# the touch-target and contrast work already in place. This is the
# structured alternative: cart side, tile density, which quick actions show.
POS_LAYOUT_DEFAULTS = {
    "cartPosition": "right",     # "left" | "right"
    "tileSize": "comfortable",   # "compact" | "comfortable" | "large"
    "quickActions": {"hold": True, "tabs": True},
}


@router.get("/pos/layout")
async def get_pos_layout(user: dict = Depends(get_user)):
    """Any signed-in staff member can read this — the POS terminal itself
    needs it to render, same as the theme."""
    from services.tenant_settings import get_setting
    saved = await get_setting("pos_layout", user.get("businessId")) or {}
    return {**POS_LAYOUT_DEFAULTS, **saved,
            "quickActions": {**POS_LAYOUT_DEFAULTS["quickActions"], **(saved.get("quickActions") or {})}}


@router.post("/pos/layout")
async def save_pos_layout(data: dict, user: dict = Depends(require_owner_or_manager)):
    from services.tenant_settings import set_setting
    cart_position = data.get("cartPosition")
    if cart_position not in ("left", "right"):
        cart_position = POS_LAYOUT_DEFAULTS["cartPosition"]
    tile_size = data.get("tileSize")
    if tile_size not in ("compact", "comfortable", "large"):
        tile_size = POS_LAYOUT_DEFAULTS["tileSize"]
    quick_in = data.get("quickActions") or {}
    quick_actions = {"hold": bool(quick_in.get("hold", True)), "tabs": bool(quick_in.get("tabs", True))}

    layout = {"cartPosition": cart_position, "tileSize": tile_size, "quickActions": quick_actions}
    await set_setting("pos_layout", layout, user.get("businessId"))
    return layout


# ============ TIP MANAGEMENT (Toast-style) ============
@router.post("/tips/add")
async def add_tip(data: dict, user: dict = Depends(get_user)):
    tip = {
        "id": f"TIP-{str(uuid.uuid4())[:8].upper()}",
        "transactionId": data.get("transactionId", ""),
        "staffId": data.get("staffId", ""),
        "staffName": data.get("staffName", ""),
        "amount": data.get("amount", 0),
        "method": data.get("method", "card"),  # card, cash, digital
        "pooled": data.get("pooled", False),
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "businessId": user.get("businessId"),
    }
    await db.tips.insert_one(tip)
    tip.pop("_id", None)
    return tip

@router.get("/tips")
async def get_tips(user: dict = Depends(require_owner_or_manager)):
    q = tenant_scope_filter(user.get("businessId"))
    tips = await db.tips.find(q, {"_id": 0}).sort("createdAt", -1).to_list(5000)
    return tips

@router.get("/tips/summary")
async def get_tips_summary(user: dict = Depends(require_owner_or_manager)):
    q = tenant_scope_filter(user.get("businessId"))
    tips = await db.tips.find(q, {"_id": 0}).to_list(10000)
    total = sum(t.get("amount", 0) for t in tips)
    by_staff = {}
    for t in tips:
        sid = t.get("staffId", "unknown")
        if sid not in by_staff:
            by_staff[sid] = {"name": t.get("staffName", "Unknown"), "total": 0, "count": 0}
        by_staff[sid]["total"] += t.get("amount", 0)
        by_staff[sid]["count"] += 1
    pooled = sum(t.get("amount", 0) for t in tips if t.get("pooled"))
    return {
        "totalTips": round(total, 2),
        "pooledAmount": round(pooled, 2),
        "byStaff": sorted(by_staff.values(), key=lambda x: x["total"], reverse=True),
        "tipCount": len(tips),
    }

@router.post("/tips/pool-distribute")
async def distribute_tip_pool(user: dict = Depends(require_owner)):
    """Distribute pooled tips equally among eligible staff"""
    biz_scope = tenant_scope_filter(user.get("businessId"))
    pooled = await db.tips.find({"pooled": True, "distributed": {"$ne": True}, **biz_scope}, {"_id": 0}).to_list(10000)
    pool_total = sum(t.get("amount", 0) for t in pooled)
    staff = await db.auth_users.find(
        {"role": {"$in": ["cashier", "manager"]}, "status": "active", **biz_scope}, {"_id": 0}).to_list(100)
    if not staff or pool_total == 0:
        return {"distributed": 0, "perPerson": 0}
    per_person = round(pool_total / len(staff), 2)
    for tip in pooled:
        await db.tips.update_one({"id": tip["id"]}, {"$set": {"distributed": True}})
    return {"distributed": round(pool_total, 2), "perPerson": per_person, "staffCount": len(staff)}

# ============ TRAINING MODE (Clover-style) ============
@router.get("/settings/training-mode")
async def get_training_mode(user: dict = Depends(get_user)):
    from services.tenant_settings import get_setting
    value = await get_setting("training_mode", user.get("businessId"))
    return {"enabled": bool(value)}

@router.post("/settings/training-mode")
async def toggle_training_mode(data: dict, user: dict = Depends(require_owner_or_manager)):
    from services.tenant_settings import set_setting
    enabled = data.get("enabled", False)
    await set_setting("training_mode", enabled, user.get("businessId"))
    return {"enabled": enabled, "message": f"Training mode {'enabled' if enabled else 'disabled'}"}

# ============ END-OF-DAY REPORTS (Square-style, Comprehensive) ============
@router.get("/reports/end-of-day")
async def get_end_of_day_report( period: str = "today", start_date: str = None, end_date: str = None, user: dict = Depends(require_owner_or_manager)):
    biz_scope = tenant_scope_filter(user.get("businessId"))

    now = datetime.now(timezone.utc)
    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now
    elif period == "yesterday":
        start = (now - __import__('datetime').timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start.replace(hour=23, minute=59, second=59)
    elif period == "week":
        start = (now - __import__('datetime').timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = now
    elif period == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = now
    elif period == "quarter":
        q_month = ((now.month - 1) // 3) * 3 + 1
        start = now.replace(month=q_month, day=1, hour=0, minute=0, second=0, microsecond=0)
        end = now
    elif period == "custom" and start_date and end_date:
        start = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
        end = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
    else:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now

    # Get all transactions (filter by date). Timestamps land in Mongo both as
    # native datetimes (the live POS checkout path) and as ISO strings (some
    # seed/demo data) — str also has a .replace() method (substring
    # replacement), so a naive hasattr(ts, 'replace') check treats both the
    # same and crashes on ts.tzinfo for strings. Normalize explicitly instead.
    def _parse_ts(ts):
        if isinstance(ts, datetime):
            return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
        if isinstance(ts, str):
            try:
                parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
            except ValueError:
                return None
        return None

    all_txns = await db.transactions.find(biz_scope, {"_id": 0}).to_list(50000)
    txns = []
    for t in all_txns:
        parsed = _parse_ts(t.get("timestamp"))
        if parsed is None or start <= parsed <= end:
            txns.append(t)

    total_sales = sum(t.get("total", 0) for t in txns)
    total_txns = len(txns)
    avg_ticket = total_sales / max(total_txns, 1)

    # By payment method
    by_payment = {}
    for t in txns:
        m = t.get("paymentMethod", "Unknown")
        by_payment[m] = by_payment.get(m, 0) + t.get("total", 0)

    # By hour
    by_hour = {}
    for t in txns:
        parsed = _parse_ts(t.get("timestamp"))
        if parsed is not None:
            by_hour[parsed.hour] = by_hour.get(parsed.hour, 0) + t.get("total", 0)

    # By category — categories marked "reports under" another category roll
    # their sales up into that category's label (e.g. an "Iced Coffee"
    # sub-category reporting as "Coffee"), resolved from the current
    # category setup at report time.
    from routes.items_system import build_reporting_map
    reporting_map = await build_reporting_map()
    by_category = {}
    product_sales = {}
    for t in txns:
        for item in t.get("items", []):
            cat = reporting_map.get(item.get("category", "Uncategorized"), item.get("category", "Uncategorized"))
            pid = item.get("productId", "")
            qty = item.get("quantity", 0)
            rev = item.get("price", 0) * qty
            by_category[cat] = by_category.get(cat, {"qty": 0, "revenue": 0})
            by_category[cat]["qty"] += qty
            by_category[cat]["revenue"] += rev
            if pid not in product_sales:
                product_sales[pid] = {"name": item.get("productName", ""), "category": cat, "qty": 0, "revenue": 0}
            product_sales[pid]["qty"] += qty
            product_sales[pid]["revenue"] += rev

    top_items = sorted(product_sales.values(), key=lambda x: x["revenue"], reverse=True)[:15]

    # Refunds & tips
    refunds = await db.refunds.find(biz_scope, {"_id": 0}).to_list(1000)
    total_refunds = sum(r.get("amount", 0) for r in refunds)
    tips = await db.tips.find(biz_scope, {"_id": 0}).to_list(10000)
    total_tips = sum(t.get("amount", 0) for t in tips)
    total_gst = sum(t.get("gst", 0) for t in txns)

    # Customer analytics
    customer_ids = [t.get("customerId") for t in txns if t.get("customerId")]
    unique_customers = len(set(customer_ids))
    customers = await db.customers.find(biz_scope, {"_id": 0}).to_list(10000)
    cust_map = {c.get("id"): c for c in customers}
    new_customers = 0
    returning_customers = 0
    for cid in set(customer_ids):
        c = cust_map.get(cid, {})
        if c.get("visits", 0) <= 1:
            new_customers += 1
        else:
            returning_customers += 1
    walk_ins = total_txns - len(customer_ids)
    total_covers = total_txns  # each txn = 1 cover approx

    # Spending habits
    spend_by_customer = {}
    for t in txns:
        cid = t.get("customerId", "walk-in")
        spend_by_customer[cid] = spend_by_customer.get(cid, 0) + t.get("total", 0)
    avg_customer_spend = sum(spend_by_customer.values()) / max(len(spend_by_customer), 1)
    top_spenders = sorted(
        [{"id": k, "name": cust_map.get(k, {}).get("name", "Walk-in"), "total": round(v, 2)} for k, v in spend_by_customer.items()],
        key=lambda x: x["total"], reverse=True
    )[:10]

    return {
        "period": period,
        "dateRange": {"start": start.isoformat(), "end": end.isoformat()},
        "summary": {
            "totalSales": round(total_sales, 2), "totalTransactions": total_txns,
            "avgTicket": round(avg_ticket, 2), "totalRefunds": round(total_refunds, 2),
            "totalTips": round(total_tips, 2), "totalGST": round(total_gst, 2),
            "netSales": round(total_sales - total_refunds, 2),
        },
        "byPaymentMethod": [{"method": m, "total": round(v, 2)} for m, v in sorted(by_payment.items(), key=lambda x: x[1], reverse=True)],
        "byHour": [{"hour": h, "total": round(v, 2)} for h, v in sorted(by_hour.items())],
        "byCategory": [{"category": k, "qty": v["qty"], "revenue": round(v["revenue"], 2)} for k, v in sorted(by_category.items(), key=lambda x: x[1]["revenue"], reverse=True)],
        "topItems": top_items,
        "customerAnalytics": {
            "totalCovers": total_covers,
            "uniqueCustomers": unique_customers,
            "walkIns": walk_ins,
            "newCustomers": new_customers,
            "returningCustomers": returning_customers,
            "avgCustomerSpend": round(avg_customer_spend, 2),
            "topSpenders": top_spenders,
        },
    }

# ============ EMAIL MARKETING CAMPAIGNS ============
# Predrafted starting points the owner can pick instead of writing from
# scratch. {business_name}/{tier} are filled in server-side; {first_name}
# is left as a token so send_campaign can personalize per recipient.
PREDRAFTED_TEMPLATES = [
    {"key": "win_back", "label": "We miss you (win-back)", "category": "Win-back", "targetTier": "",
     "subject": "It's been a while, {first_name} — come back to {business_name}",
     "body": "Hi {first_name},\n\nWe haven't seen you in a bit and wanted to say we miss you! "
             "Come back and treat yourself — we'd love to host you again soon.\n\n"
             "See you soon,\nThe {business_name} Team"},
    {"key": "new_menu", "label": "New menu launch", "category": "Launch", "targetTier": "",
     "subject": "Something new is cooking at {business_name}",
     "body": "Hi {first_name},\n\nOur kitchen has been busy — we just launched a brand new menu "
             "and we think you're going to love it. Come try it this week!\n\n"
             "See you soon,\nThe {business_name} Team"},
    {"key": "happy_hour", "label": "Happy hour push", "category": "Recurring", "targetTier": "",
     "subject": "Happy Hour is calling your name",
     "body": "Hi {first_name},\n\nJoin us for Happy Hour — great drinks, great food, great company. "
             "Grab your table before it fills up!\n\nCheers,\nThe {business_name} Team"},
    {"key": "birthday", "label": "Birthday treat", "category": "Occasion", "targetTier": "",
     "subject": "Happy Birthday from {business_name}!",
     "body": "Hi {first_name},\n\nHappy Birthday! We'd love to help you celebrate — swing by any "
             "time this month and let us spoil you a little.\n\nWarmly,\nThe {business_name} Team"},
    {"key": "weekend_special", "label": "Weekend special", "category": "Recurring", "targetTier": "",
     "subject": "This weekend only at {business_name}",
     "body": "Hi {first_name},\n\nWe've got something special planned this weekend and didn't want "
             "you to miss it. Book your table now — spots go fast.\n\nSee you there,\nThe {business_name} Team"},
    {"key": "tier_perk", "label": "Loyalty tier perk", "category": "Loyalty", "targetTier": "Gold",
     "subject": "A perk just for our {tier} members",
     "body": "Hi {first_name},\n\nAs one of our valued {tier} members, we wanted to give you first "
             "access to something special. Come in and enjoy it on us.\n\n"
             "Thank you for being with us,\nThe {business_name} Team"},
]


async def _business_name(business_id: Optional[str] = None) -> str:
    from services.tenant_settings import get_scoped_singleton
    biz = await get_scoped_singleton(db.business_settings, {"key": "main"}, business_id)
    return (biz or {}).get("name") or "us"


def _fill_template(text: str, *, business_name: str, tier: str = "") -> str:
    return (text.replace("{business_name}", business_name)
                .replace("{tier}", tier or "member"))


@router.get("/marketing/campaigns/templates")
async def get_campaign_templates(user: dict = Depends(require_owner_or_manager)):
    business_name = await _business_name(user.get("businessId"))
    return [
        {**t, "subject": _fill_template(t["subject"], business_name=business_name, tier=t.get("targetTier", "")),
         "body": _fill_template(t["body"], business_name=business_name, tier=t.get("targetTier", ""))}
        for t in PREDRAFTED_TEMPLATES
    ]


@router.post("/marketing/campaigns/draft")
async def draft_campaign(data: dict, user: dict = Depends(require_owner_or_manager)):
    """AI-predrafted email: start from a template and/or a plain-English brief
    ('promote our new summer menu to Gold members') and return a ready-to-edit
    {name, subject, body}. Falls back to the raw template / a plain heuristic
    draft when no LLM key is configured."""
    business_name = await _business_name(user.get("businessId"))
    brief = (data.get("brief") or "").strip()
    target_tier = data.get("targetTier") or ""
    template = next((t for t in PREDRAFTED_TEMPLATES if t["key"] == data.get("templateKey")), None)

    from routes.v26_commerce import _llm_json
    sys_msg = (
        "You are NUA's email marketing copywriter for an independent restaurant/bar. "
        "Draft ONE promotional email. Keep the body under 160 words, warm and concrete "
        "(no generic filler), explain the offer clearly, and end with one specific "
        "call-to-action that drives a visit or booking. Keep the literal token "
        "{first_name} exactly as written wherever you'd personalize a greeting — it is "
        "filled in per recipient at send time. Return STRICT JSON: "
        '{"name":"internal campaign name","subject":"...","body":"..."}'
    )
    user_text = json.dumps({
        "businessName": business_name, "brief": brief or None, "targetTier": target_tier or None,
        "startingTemplate": template,
    })
    draft = await _llm_json(f"campaign-draft-{uuid.uuid4().hex[:6]}", sys_msg, user_text)

    if not draft or not draft.get("body"):
        if template:
            draft = {
                "name": template["label"],
                "subject": _fill_template(template["subject"], business_name=business_name, tier=target_tier),
                "body": _fill_template(template["body"], business_name=business_name, tier=target_tier),
            }
        else:
            headline = brief or "something special"
            draft = {
                "name": (brief[:40] if brief else "New campaign"),
                "subject": f"{business_name}: {headline}",
                "body": (f"Hi {{first_name}},\n\nWe wanted to let you know about {headline} at "
                         f"{business_name}. Come in and check it out — we'd love to see you.\n\n"
                         f"See you soon,\nThe {business_name} Team"),
            }
    return draft


@router.post("/marketing/campaigns/improve")
async def improve_campaign_copy(data: dict, _: dict = Depends(require_owner_or_manager)):
    """AI-rewrite an in-progress subject/body for clearer wording, a better
    explanation of the offer, and a stronger call-to-action aimed at turning
    the read into a visit (a lead). Preserves {first_name}/voucher tokens."""
    subject = (data.get("subject") or "").strip()
    body = (data.get("body") or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="Nothing to improve yet — write a draft first")
    goal = (data.get("goal") or "").strip()

    from routes.v26_commerce import _llm_json
    sys_msg = (
        "You are an expert hospitality email copywriter. Rewrite the given subject and "
        "body: tighten the wording, make the offer's value obvious, and close with one "
        "compelling call-to-action that turns the reader into a booking/visit (a lead). "
        "Preserve any {first_name} or voucher-code tokens/placeholders exactly as given — "
        "never remove or rename them. Keep roughly the same length. Return STRICT JSON: "
        '{"subject":"...","body":"..."}'
    )
    user_text = json.dumps({"subject": subject, "body": body, "goal": goal or None})
    improved = await _llm_json(f"campaign-improve-{uuid.uuid4().hex[:6]}", sys_msg, user_text)

    if not improved or not improved.get("body"):
        cta_markers = ("book", "visit", "come in", "order", "reserve", "redeem", "see you")
        new_body = body
        if not any(m in body.lower() for m in cta_markers):
            new_body = body.rstrip() + "\n\nBook your table today — we can't wait to see you!"
        improved = {"subject": subject or "A little something for you", "body": new_body}
    return improved


def _split_first_name(full_name: str) -> str:
    return (full_name or "").strip().split(" ")[0] or "there"


# ============ AUDIENCE SEGMENTS ============
# Campaign targeting used to mean "all customers" or "one loyalty tier" —
# nothing in between. Rules are intentionally flat (AND'd together) rather
# than a general expression engine: the fields are exactly the ones the
# Customer record already carries (no time-windowed spend/visit aggregation
# over raw transactions, which would need new infrastructure this doesn't
# have yet).
def _build_segment_query(rules: dict) -> dict:
    q: dict = {}
    if rules.get("tier"):
        q["membershipTier"] = rules["tier"]
    if rules.get("minSpend") not in (None, "", 0):
        q["totalSpent"] = {"$gte": float(rules["minSpend"])}
    if rules.get("minVisits") not in (None, "", 0):
        q["visits"] = {"$gte": int(rules["minVisits"])}
    if rules.get("inactiveForDays") not in (None, ""):
        # "Hasn't visited in N days" — win-back targeting. Customers with no
        # lastVisitDate at all (never actually visited) count as inactive.
        cutoff = (datetime.now(timezone.utc) - timedelta(days=int(rules["inactiveForDays"]))).date().isoformat()
        q["$or"] = [{"lastVisitDate": {"$lt": cutoff}}, {"lastVisitDate": None}, {"lastVisitDate": {"$exists": False}}]
    return q


async def _customer_ids_spending_in_window(days: int, min_spend: float) -> set:
    """"Spent >= $X in the last N days" — totalSpent on the customer record
    is a lifetime total, so this can't be a customer-field filter; it needs
    an aggregation over actual transactions in the window."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    pipeline = [
        {"$match": {"customerId": {"$ne": None}, "timestamp": {"$gte": cutoff}}},
        {"$group": {"_id": "$customerId", "spend": {"$sum": "$total"}}},
        {"$match": {"spend": {"$gte": min_spend}}},
    ]
    rows = await db.transactions.aggregate(pipeline).to_list(20000)
    return {r["_id"] for r in rows}


async def _resolve_segment_customers(rules: dict, *, limit: int = 10000,
                                      business_id: str = None) -> list:
    query = _build_segment_query(rules)
    # _build_segment_query can itself set a top-level "$or" (the
    # inactiveForDays rule) — a plain dict.update() with
    # tenant_scope_filter()'s own "$or" would silently clobber that rule's
    # condition instead of ANDing with it, which would make "hasn't visited
    # in N days" match everyone in the business instead of just the
    # inactive ones. $and keeps both conditions intact.
    scope = tenant_scope_filter(business_id)
    if scope:
        query = {"$and": [query, scope]} if query else scope
    window_days = rules.get("spendInLastDays")
    window_min = rules.get("minSpendInWindow")
    if window_days not in (None, "") and window_min not in (None, "", 0):
        ids = await _customer_ids_spending_in_window(int(window_days), float(window_min))
        query["id"] = {"$in": list(ids)}
    return await db.customers.find(query, {"_id": 0, "password_hash": 0}).to_list(limit)


@router.post("/marketing/segments/preview")
async def preview_segment(data: dict, user: dict = Depends(require_owner_or_manager)):
    rules = data.get("rules") or {}
    customers = await _resolve_segment_customers(rules, business_id=user.get("businessId"))
    sample = [{"id": c["id"], "name": c.get("name"), "email": c.get("email"),
               "totalSpent": c.get("totalSpent", 0), "visits": c.get("visits", 0),
               "membershipTier": c.get("membershipTier")} for c in customers[:20]]
    return {"count": len(customers), "sample": sample}


@router.get("/marketing/segments")
async def list_segments(user: dict = Depends(require_owner_or_manager)):
    q = tenant_scope_filter(user.get("businessId"))
    return await db.customer_segments.find(q, {"_id": 0}).sort("createdAt", -1).to_list(200)


@router.get("/marketing/segments/{segment_id}/customers")
async def get_segment_customers(segment_id: str, limit: int = 500, user: dict = Depends(require_owner_or_manager)):
    """The full matching list, not just preview's 20-row sample — for an
    owner who wants to actually see (or export) who's in a segment."""
    segment = await db.customer_segments.find_one({"$and": [{"id": segment_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not segment or not tenant_owns_strict(segment.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Segment not found")
    customers = await _resolve_segment_customers(segment.get("rules") or {}, limit=min(limit, 5000),
                                                  business_id=user.get("businessId"))
    return {
        "segment": segment,
        "count": len(customers),
        "customers": [{"id": c["id"], "name": c.get("name"), "email": c.get("email"),
                       "totalSpent": c.get("totalSpent", 0), "visits": c.get("visits", 0),
                       "membershipTier": c.get("membershipTier")} for c in customers],
    }


@router.put("/marketing/segments/{segment_id}")
async def update_segment(segment_id: str, data: dict, user: dict = Depends(require_owner_or_manager)):
    existing = await db.customer_segments.find_one({"$and": [{"id": segment_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not existing or not tenant_owns_strict(existing.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Segment not found")
    name = (data.get("name") or existing["name"]).strip()
    if not name:
        raise HTTPException(status_code=400, detail="Segment name is required")
    updated = {**existing, "name": name, "rules": data.get("rules", existing["rules"]),
               "updatedBy": user["id"], "updatedAt": datetime.now(timezone.utc).isoformat()}
    await db.customer_segments.replace_one({"id": segment_id}, updated)
    return updated


@router.post("/marketing/segments")
async def create_segment(data: dict, user: dict = Depends(require_owner_or_manager)):
    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Segment name is required")
    rules = data.get("rules") or {}
    segment = {
        "id": f"SEG-{str(uuid.uuid4())[:8].upper()}",
        "name": name, "rules": rules,
        "createdBy": user["id"], "createdAt": datetime.now(timezone.utc).isoformat(),
        "businessId": user.get("businessId"),
    }
    await db.customer_segments.insert_one(dict(segment))
    segment.pop("_id", None)
    return segment


@router.delete("/marketing/segments/{segment_id}")
async def delete_segment(segment_id: str, user: dict = Depends(require_owner_or_manager)):
    existing = await db.customer_segments.find_one({"$and": [{"id": segment_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not existing or not tenant_owns_strict(existing.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Segment not found")
    result = await db.customer_segments.delete_one({"$and": [{"id": segment_id}, tenant_scope_filter(user.get("businessId"))]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Segment not found")
    return {"deleted": True}


async def _campaign_recipients(campaign: dict) -> list:
    """Resolve a campaign's actual recipient list against the LIVE customer
    collection. Older campaigns only ever set targetTier; segmentId (or an
    inline rules dict) is additive, not a replacement — either narrows who
    a campaign reaches, never both at once.

    This used to query db.members, a collection nothing has written to
    since the member-portal router was removed several rounds ago — on any
    deployment created after that removal, every campaign silently had 0
    real recipients. db.customers is the actual, live guest record.
    """
    business_id = campaign.get("businessId")
    if campaign.get("segmentId"):
        segment = await db.customer_segments.find_one({"$and": [{"id": campaign["segmentId"]}, tenant_scope_filter(business_id)]}, {"_id": 0})
        if segment and not tenant_owns_strict(segment.get("businessId"), business_id):
            segment = None
        rules = (segment or {}).get("rules") or {}
    elif campaign.get("segmentRules"):
        rules = campaign["segmentRules"]
    else:
        rules = {}
    if campaign.get("targetTier"):
        rules = {**rules, "tier": campaign["targetTier"]}
    return await _resolve_segment_customers(rules, business_id=business_id)


@router.post("/marketing/campaigns")
async def create_campaign(data: dict, user: dict = Depends(require_owner_or_manager)):

    campaign = {
        "id": f"CMP-{str(uuid.uuid4())[:8].upper()}",
        "name": data.get("name", ""),
        "subject": data.get("subject", ""),
        "body": data.get("body", ""),
        "targetTier": data.get("targetTier"),  # None = all customers
        "segmentId": data.get("segmentId"),  # optional saved segment, narrows targetTier further
        "segmentRules": data.get("segmentRules"),  # or inline rules, for a one-off segment never saved
        "status": "draft",
        "createdBy": user["id"],
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "sentAt": None,
        "recipientCount": 0,
        "openCount": 0,
        "voucherId": None,
        "voucherCode": None,
        "businessId": user.get("businessId"),
    }

    # Optional: attach one shared voucher code every recipient of this
    # campaign can redeem at the venue (POS already knows how to apply
    # any v26 commerce_vouchers code, so cashiers need no new workflow).
    voucher_req = data.get("voucher") or {}
    if voucher_req.get("enabled"):
        from routes.v26_commerce import _new_code, _uid, _now as _v26_now, _iso as _v26_iso
        codes = _new_code("PROMO")
        expires_in_days = int(voucher_req.get("expiresInDays") or 30)
        voucher_doc = {
            "id": _uid("VCH"),
            "name": f"Campaign: {campaign['name'] or campaign['id']}",
            "kind": "marketing",
            "discountType": voucher_req.get("valueType", "percent"),
            "value": float(voucher_req.get("value") or 10),
            "appliesTo": "cart",
            "category": None, "productIds": [],
            "minSpend": float(voucher_req.get("minSpend") or 0),
            "maxUses": int(voucher_req.get("maxUses") or 0),  # 0 = unlimited
            "usedCount": 0,
            "validFrom": None,
            "validTo": _v26_iso(_v26_now() + timedelta(days=expires_in_days)),
            "termsAndConditions": "Issued via email campaign; one redemption per visit unless stated otherwise.",
            "active": True,
            **codes,
            "createdAt": _v26_iso(_v26_now()),
            "createdBy": user["id"],
            "campaignId": campaign["id"],
            "businessId": user.get("businessId"),
        }
        await db.commerce_vouchers.insert_one(dict(voucher_doc))
        campaign["voucherId"] = voucher_doc["id"]
        campaign["voucherCode"] = voucher_doc["manualCode"]
        redeem_blurb = (f"\n\n---\nShow this code at the venue to redeem: {voucher_doc['manualCode']}"
                        f" ({voucher_doc['value']:.0f}{'%' if voucher_doc['discountType'] == 'percent' else '$'} off"
                        f"{', min spend $' + str(voucher_doc['minSpend']) if voucher_doc['minSpend'] else ''}, "
                        f"valid until {voucher_doc['validTo'][:10]}).")
        if voucher_doc["manualCode"] not in campaign["body"]:
            campaign["body"] = (campaign["body"] or "") + redeem_blurb

    # Recurring: a saved segment re-resolved fresh on every run (that's the
    # entire point — "newly inactive" or "just crossed $X spend" changes
    # week to week) instead of a one-off snapshot sent once and done.
    # There's no background scheduler in this codebase — automations
    # (agent_tick, automation triggers) are all "due work runs when
    # something calls the tick endpoint," not self-scheduling, and this
    # follows the same established pattern rather than introducing a new one.
    recurring_req = data.get("recurring") or {}
    if recurring_req.get("enabled"):
        interval_days = max(1, int(recurring_req.get("intervalDays") or 7))
        campaign["recurring"] = {"enabled": True, "intervalDays": interval_days}
        campaign["status"] = "recurring"
        campaign["nextRunAt"] = datetime.now(timezone.utc).isoformat()
        campaign["lastRunAt"] = None
        campaign["runCount"] = 0
    else:
        campaign["recurring"] = None

    # Count target recipients against the live customer collection.
    campaign["recipientCount"] = len(await _campaign_recipients(campaign))
    await db.campaigns.insert_one(dict(campaign))
    campaign.pop("_id", None)
    return campaign

@router.get("/marketing/campaigns")
async def get_campaigns(user: dict = Depends(require_owner_or_manager)):
    q = tenant_scope_filter(user.get("businessId"))
    campaigns = await db.campaigns.find(q, {"_id": 0}).sort("createdAt", -1).to_list(100)
    return campaigns


async def _send_campaign_emails(campaign: dict) -> dict:
    """The actual send loop, shared by the one-off Send button and the
    recurring run/run-due path — a recurring campaign never reaches
    "sent" as a terminal status, it just runs again."""
    members = await _campaign_recipients(campaign)
    from utils.notifications import send_email

    # Log + best-effort send each recipient. A delivery failure on one
    # member never blocks the rest — same resilience pattern as the rest
    # of the notification layer.
    delivered_count = 0
    for m in members:
        personalized_body = (campaign["body"] or "").replace(
            "{first_name}", _split_first_name(m.get("name", ""))
        )
        receipt = {"channel": "email", "delivered": False, "reason": "unknown"}
        try:
            receipt = await send_email(m.get("email"), campaign["subject"], personalized_body)
        except Exception as e:
            receipt = {"channel": "email", "delivered": False, "reason": str(e)[:120]}
        if receipt.get("delivered"):
            delivered_count += 1
        await db.campaign_sends.insert_one({
            "campaignId": campaign["id"], "memberId": m["id"],
            "email": m.get("email"), "status": "sent" if receipt.get("delivered") else "queued",
            "deliveryReason": receipt.get("reason"),
            "sentAt": datetime.now(timezone.utc).isoformat(),
        })
    return {"recipientCount": len(members), "deliveredCount": delivered_count}


@router.post("/marketing/campaigns/{campaign_id}/send")
async def send_campaign(campaign_id: str, user: dict = Depends(require_owner_or_manager)):
    campaign = await db.campaigns.find_one({"$and": [{"id": campaign_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not campaign or not tenant_owns_strict(campaign.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.get("status") == "recurring":
        raise HTTPException(status_code=400, detail="Recurring campaigns run automatically — use run-now instead")

    result = await _send_campaign_emails(campaign)
    await db.campaigns.update_one(
        {"$and": [{"id": campaign_id}, tenant_scope_filter(user.get("businessId"))]},
        {"$set": {"status": "sent", "sentAt": datetime.now(timezone.utc).isoformat(),
                   "recipientCount": result["recipientCount"], "deliveredCount": result["deliveredCount"]}}
    )
    return {"message": f"Campaign sent to {result['recipientCount']} members ({result['deliveredCount']} delivered via SendGrid, "
                        f"rest queued — configure SENDGRID_API_KEY to send live)",
            **result}


async def _run_recurring_campaign(campaign: dict) -> dict:
    result = await _send_campaign_emails(campaign)
    interval_days = campaign.get("recurring", {}).get("intervalDays", 7)
    now = datetime.now(timezone.utc)
    await db.campaigns.update_one(
        {"id": campaign["id"]},
        {"$set": {"lastRunAt": now.isoformat(),
                   "nextRunAt": (now + timedelta(days=interval_days)).isoformat(),
                   "recipientCount": result["recipientCount"], "deliveredCount": result["deliveredCount"]},
         "$inc": {"runCount": 1}}
    )
    return result


@router.post("/marketing/campaigns/{campaign_id}/run-now")
async def run_campaign_now(campaign_id: str, user: dict = Depends(require_owner_or_manager)):
    """Manually fire one recurring campaign immediately, without waiting
    for its schedule — same effect as run-due picking it up, just now."""
    campaign = await db.campaigns.find_one({"$and": [{"id": campaign_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not campaign or not tenant_owns_strict(campaign.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.get("status") != "recurring":
        raise HTTPException(status_code=400, detail="Only recurring campaigns can be run this way")
    result = await _run_recurring_campaign(campaign)
    return {"message": f"Sent to {result['recipientCount']} members", **result}


@router.post("/marketing/campaigns/run-due")
async def run_due_campaigns(user: dict = Depends(require_owner_or_manager)):
    """Process every recurring campaign whose nextRunAt has passed. No
    background scheduler exists in this codebase (see agent_tick) — this
    is meant to be called periodically the same way, or via the "Run due
    campaigns" button in Email Marketing. Scoped to the caller's own
    business — this is triggered by a business's own owner/manager, not a
    system-wide cron, so it must never fire another business's recurring
    campaigns (and send their emails) on this business's behalf."""
    now_iso = datetime.now(timezone.utc).isoformat()
    due = await db.campaigns.find(
        {"status": "recurring", "nextRunAt": {"$lte": now_iso}, **tenant_scope_filter(user.get("businessId"))},
        {"_id": 0}
    ).to_list(200)
    results = []
    for campaign in due:
        result = await _run_recurring_campaign(campaign)
        results.append({"campaignId": campaign["id"], "name": campaign["name"], **result})
    return {"ran": len(results), "campaigns": results}


@router.delete("/marketing/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: str, user: dict = Depends(require_owner_or_manager)):
    campaign = await db.campaigns.find_one({"$and": [{"id": campaign_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not campaign or not tenant_owns_strict(campaign.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Campaign not found")
    await db.campaigns.delete_one({"$and": [{"id": campaign_id}, tenant_scope_filter(user.get("businessId"))]})
    return {"message": "Campaign deleted"}


# ============ AI EOD INSIGHTS ============
@router.post("/reports/ai-insights")
async def generate_ai_insights(data: dict, _: dict = Depends(require_owner_or_manager)):

    report_data = data.get("reportData", {})
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        api_key = os.environ.get("EMERGENT_LLM_KEY", "")
        chat = LlmChat(api_key=api_key, session_id=f"eod-{uuid.uuid4()}", system_message="You are an expert restaurant business analyst. Provide concise, actionable insights from POS data. Use bullet points. Be specific with numbers. Keep response under 300 words.")
        chat.with_model("openai", "gpt-5.2")

        summary = report_data.get("summary", {})
        prompt = f"""Analyze this restaurant's End-of-Day report and provide actionable insights:

Sales: ${summary.get('totalSales', 0):.2f} | Net: ${summary.get('netSales', 0):.2f} | Transactions: {summary.get('totalTransactions', 0)}
Avg Ticket: ${summary.get('avgTicket', 0):.2f} | GST: ${summary.get('totalGST', 0):.2f}
Refunds: ${summary.get('totalRefunds', 0):.2f} | Tips: ${summary.get('totalTips', 0):.2f}

Payment Methods: {report_data.get('byPaymentMethod', [])}
Top Items: {report_data.get('topItems', [])[:5]}
Categories: {report_data.get('byCategory', [])}
Customer Analytics: {report_data.get('customerAnalytics', {})}
Hourly Sales: {report_data.get('byHour', [])}

Provide:
1. Key Performance Highlights (2-3 bullets)
2. Areas of Concern (if any)
3. Actionable Recommendations (2-3 specific suggestions)
4. Staffing Insight based on hourly data
5. Customer Retention Insight"""

        msg = UserMessage(text=prompt)
        response = await chat.send_message(msg)

        insight = {
            "id": f"AI-{str(uuid.uuid4())[:8].upper()}",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "insights": response,
            "period": data.get("period", "today"),
        }
        await db.ai_insights.insert_one(insight)
        insight.pop("_id", None)
        return insight
    except Exception as e:
        return {"insights": f"AI insights unavailable: {str(e)}", "generatedAt": datetime.now(timezone.utc).isoformat()}
