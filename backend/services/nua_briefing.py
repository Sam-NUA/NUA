"""
Ash Daily Briefing — the morning "Good Morning Sam" endpoint.

Deterministic data harvest + one LLM narrative call (GPT-5.2 via Emergent LLM key).
"""
from __future__ import annotations
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from database import db
from middleware.actor_context import tenant_scope_filter
import os
import logging
import uuid

logger = logging.getLogger(__name__)


async def _collect_briefing_data(business_id: Optional[str] = None) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    tomorrow = (now + timedelta(days=1)).date().isoformat()
    week_ago = (now - timedelta(days=7)).isoformat()
    biz_scope = tenant_scope_filter(business_id)

    # Revenue last 7 days
    txns = await db.transactions.find(
        {"timestamp": {"$gte": week_ago}, **biz_scope}, {"total": 1, "timestamp": 1}).to_list(20000)
    week_rev = sum(float(t.get("total") or 0) for t in txns)
    day_revs = {}
    for t in txns:
        d = (t.get("timestamp") or "")[:10]
        day_revs[d] = day_revs.get(d, 0) + float(t.get("total") or 0)
    forecast_today = round(sum(day_revs.values()) / max(1, len(day_revs)), 2)

    # Bookings today
    bookings_q = {"dateTime": {"$regex": f"^{today}"}, **biz_scope}
    bookings = await db.reservations.count_documents(bookings_q) if await db.reservations.count_documents(biz_scope) else 0
    vip = await db.reservations.count_documents({**bookings_q, "isVip": True}) \
        if await db.reservations.count_documents(biz_scope) else 0

    # Rostered staff
    rostered = await db.shifts.count_documents({"date": today, **biz_scope}) \
        if await db.shifts.count_documents(biz_scope) else 0

    # Inventory risks
    low_stock = 0
    async for p in db.products.find(biz_scope, {"stock": 1, "lowStockThreshold": 1}):
        s = float(p.get("stock") or 0)
        thr = float(p.get("lowStockThreshold") or 5)
        if s <= thr:
            low_stock += 1

    # Top open Ash insights
    top_insights = await db.ash_insights.find(
        {"resolvedAt": None, "severity": {"$in": ["high", "warning"]}, **biz_scope},
        {"_id": 0},
    ).sort("createdAt", -1).limit(5).to_list(5)

    # Birthdays (customers whose DoB matches today, month+day)
    birthdays = []
    if await db.customers.count_documents({**tenant_scope_filter(business_id), "birthday": {"$exists": True}, **biz_scope}):
        md = now.strftime("--%m-%d")
        async for c in db.customers.find({**tenant_scope_filter(business_id), "birthday": {"$regex": md}, **biz_scope}, {"_id": 0, "name": 1, "email": 1, "id": 1}):
            birthdays.append(c)

    # Pending approvals
    pending_approvals = await db.approvals.count_documents({"status": "pending", **biz_scope})

    return {
        "date": today, "tomorrow": tomorrow,
        "forecastRevenue": forecast_today,
        "bookingsToday": bookings, "vipCount": vip, "rosteredStaff": rostered,
        "lowStockCount": low_stock,
        "topInsights": top_insights,
        "birthdays": birthdays,
        "pendingApprovals": pending_approvals,
        "weekRevenue": round(week_rev, 2),
    }


async def generate_briefing(business_id: Optional[str] = None) -> Dict[str, Any]:
    if business_id is None:
        from middleware.actor_context import get_actor_context
        business_id = get_actor_context().get("businessId")
    data = await _collect_briefing_data(business_id)

    prompt = f"""Write a warm 5-sentence morning briefing for the owner.
- Today's date: {data['date']}
- Forecast revenue today: ${data['forecastRevenue']:,.2f}
- Bookings today: {data['bookingsToday']} (VIPs: {data['vipCount']})
- Rostered staff: {data['rosteredStaff']}
- Low-stock items: {data['lowStockCount']}
- Pending approvals: {data['pendingApprovals']}
- Top open insights: {[t.get('title') for t in data['topInsights']]}
- Birthdays today: {[b.get('name') for b in data['birthdays']]}

Start with "Good morning". End with ONE specific recommendation."""
    narrative = None
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        key = os.environ.get("EMERGENT_LLM_KEY")
        if key:
            chat = LlmChat(api_key=key, session_id=f"ash-briefing-{uuid.uuid4()}",
                            system_message="You are Ash, NUA's hospitality operating agent. Warm, concrete, brief.")\
                .with_model("openai", "gpt-5.2")
            narrative = await chat.send_message(UserMessage(text=prompt))
    except Exception as e:
        logger.warning(f"[briefing] LLM fallback: {e}")

    if not narrative:
        pieces = [f"Good morning. Today's forecast is roughly ${data['forecastRevenue']:,.0f}."]
        if data["bookingsToday"]:
            pieces.append(f"You have {data['bookingsToday']} bookings" +
                            (f" including {data['vipCount']} VIPs" if data['vipCount'] else "") + ".")
        if data["lowStockCount"]:
            pieces.append(f"{data['lowStockCount']} items are below their par level — worth a reorder call.")
        if data["pendingApprovals"]:
            pieces.append(f"{data['pendingApprovals']} approvals are waiting on you at /approvals.")
        if data["topInsights"]:
            pieces.append(f"Ash's top open item: “{data['topInsights'][0].get('title')}”.")
        pieces.append("Focus: clear the pending approvals first — they unlock automated action downstream.")
        narrative = " ".join(pieces)

    doc = {
        "id": str(uuid.uuid4()),
        "date": data["date"],
        "narrative": narrative,
        "data": data,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "businessId": business_id,
    }
    # Keyed by (date, businessId) — date alone let two businesses' briefings
    # collide on one document, so whichever business generated theirs last
    # on a given day silently overwrote every other business's morning
    # briefing (real revenue, bookings, approvals) for that date.
    await db.ash_briefings.update_one(
        {"date": data["date"], "businessId": business_id}, {"$set": doc}, upsert=True)
    return doc
