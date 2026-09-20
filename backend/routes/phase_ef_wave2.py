"""Phase E + F — Wave 2.

E5  Auto-upsell suggestions for cart       POST /api/ai/upsell
E6  Auto-price-tune recommendations         POST /api/ai/price-tune
E7  Overbooking guardrail                    POST /api/ai/overbooking-check
F5  AI Cost Coach                            GET  /api/ai/cost-coach
F6  Predictive Labor Forecast                GET  /api/ai/labor-forecast
F7  Dynamic Surge Pricing                    GET  /api/ai/surge-recommendations
                                             POST /api/ai/surge/apply
F8  Voice-to-Recipe                          POST /api/ai/voice-recipe
F9  Kitchen-Load Balancing                   GET  /api/ai/kitchen-load
"""
from fastapi import APIRouter, HTTPException, Depends
from deps import get_user, require_owner, require_owner_or_manager
from database import db
from middleware.actor_context import tenant_scope_filter
from services import floor_tables
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict
import uuid
import os
import json
import re
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
async def _llm_json(session_id: str, system: str, user_text: str, model: str = "gpt-5.2"):
    """Run an LLM call expecting strict JSON in the response. Returns parsed dict
    or {} on failure."""
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=os.environ.get("EMERGENT_LLM_KEY"),
            session_id=session_id,
            system_message=system,
        ).with_model("openai", model)
        resp = await chat.send_message(UserMessage(text=user_text))
        text = (resp or "").strip().strip("`")
        try:
            return json.loads(text)
        except Exception:
            m = re.search(r"\{.*\}|\[.*\]", text, re.DOTALL)
            return json.loads(m.group(0)) if m else {}
    except Exception as e:
        logger.warning("LLM call failed [%s]: %s", session_id, str(e)[:200])
        return {"_error": str(e)[:200]}


# ============================================================================
# E5 — AUTO-UPSELL FOR CART
# ============================================================================
@router.post("/ai/upsell")
async def upsell_for_cart(data: dict, user: dict = Depends(get_user)):
    """Given the current cart, recommend 1-3 high-margin add-ons.
    Returns {suggestions: [{productId, name, price, reason}]}"""
    cart = data.get("cart", [])
    if not isinstance(cart, list) or len(cart) == 0:
        return {"suggestions": []}

    # Pull product catalog with margin info — keep small to control tokens
    products = await db.products.find(
        {"active": {"$ne": False}, **tenant_scope_filter(user.get("businessId"))},
        {"_id": 0, "id": 1, "name": 1, "price": 1, "cost": 1, "category": 1},
    ).to_list(200)
    # Compute margin
    def margin(p):
        try:
            return round((float(p.get("price", 0)) - float(p.get("cost", 0) or 0)), 2)
        except Exception:
            return 0
    # Sort high margin first, drop items already in cart
    cart_ids = {it.get("productId") or it.get("id") for it in cart}
    candidates = [p for p in products if p["id"] not in cart_ids]
    candidates.sort(key=margin, reverse=True)
    candidates = candidates[:30]

    cart_lines = "\n".join(
        f"- {it.get('name','?')} x{it.get('quantity', 1)} @ ${float(it.get('price',0)):.2f}"
        for it in cart
    )
    cand_lines = "\n".join(
        f"- id:{p['id']} | {p['name']} | ${float(p['price']):.2f} | margin ${margin(p):.2f} | {p.get('category','')}"
        for p in candidates
    )
    sys_msg = (
        "You are a restaurant upsell coach. Suggest 1-3 add-on items the guest is most likely "
        "to accept given their current order. Prefer high-margin pairings (drink with main, "
        "dessert after big plates, side with mains). Return STRICT JSON: "
        '{"suggestions":[{"productId":"...","name":"...","price":12.5,"reason":"..."}]}'
    )
    user_msg = f"Current cart:\n{cart_lines}\n\nCandidate add-ons:\n{cand_lines}"
    out = await _llm_json(f"upsell-{uuid.uuid4().hex[:8]}", sys_msg, user_msg)
    suggestions = out.get("suggestions", []) if isinstance(out, dict) else []
    # Cap to 3 and ensure ids exist
    valid_ids = {p["id"] for p in candidates}
    suggestions = [s for s in suggestions if s.get("productId") in valid_ids][:3]
    return {"suggestions": suggestions}


# ============================================================================
# E6 — AUTO-PRICE-TUNE RECOMMENDATIONS
# ============================================================================
@router.get("/ai/price-tune")
async def price_tune_recs(user: dict = Depends(require_owner_or_manager)):
    """Analyze 30-day sales velocity vs current price; return rec'd nudges."""
    biz_scope = tenant_scope_filter(user.get("businessId"))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    tx = await db.transactions.find(
        {"createdAt": {"$gte": cutoff}, **biz_scope}, {"_id": 0, "items": 1}
    ).to_list(5000)
    sales = Counter()
    for t in tx:
        for it in (t.get("items") or []):
            pid = it.get("productId")
            if pid:
                sales[pid] += int(it.get("quantity", 1))
    products = await db.products.find(
        {"active": {"$ne": False}, **biz_scope}, {"_id": 0}
    ).to_list(500)
    # Compute median velocity to use as baseline
    velocities = sorted(sales.values()) or [0]
    median = velocities[len(velocities) // 2] if velocities else 0
    recs = []
    for p in products:
        v = sales.get(p["id"], 0)
        price = float(p.get("price", 0) or 0)
        if price <= 0:
            continue
        # High velocity (≥ 2x median) + margin > 30% → raise 5%
        if v >= max(median * 2, 10) and (price - float(p.get("cost", 0) or 0)) / max(price, 0.01) > 0.30:
            recs.append({
                "productId": p["id"], "name": p["name"], "currentPrice": price,
                "recommendedPrice": round(price * 1.05, 2), "delta": round(price * 0.05, 2),
                "direction": "raise", "reason": f"Sold {v} in 30d (median {median}) — high demand, raise 5%",
            })
        # Low velocity (≤ 0.3x median) with healthy margin → drop 5%
        elif v <= max(median * 0.3, 1) and price > 5:
            recs.append({
                "productId": p["id"], "name": p["name"], "currentPrice": price,
                "recommendedPrice": round(price * 0.95, 2), "delta": round(price * -0.05, 2),
                "direction": "drop", "reason": f"Sold {v} in 30d (median {median}) — low demand, drop 5%",
            })
    return {"medianVelocity": median, "recommendations": recs[:30]}


@router.post("/ai/price-tune/apply")
async def apply_price_tune(data: dict, user: dict = Depends(require_owner_or_manager)):
    pid = data.get("productId")
    new_price = float(data.get("newPrice"))
    if not pid or new_price <= 0:
        raise HTTPException(status_code=400, detail="productId + newPrice required")
    res = await db.products.update_one(
        {"id": pid, **tenant_scope_filter(user.get("businessId"))},
        {"$set": {
            "price": new_price,
            "lastPriceChange": {
                "by": user["id"], "newPrice": new_price,
                "at": datetime.now(timezone.utc).isoformat(),
                "reason": "AI price-tune",
            },
        }, "$push": {
            "priceHistory": {
                "newPrice": new_price,
                "by": user["id"],
                "at": datetime.now(timezone.utc).isoformat(),
                "reason": "AI price-tune",
            }
        }},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")
    await db.agent_decisions.insert_one({
        "id": f"AGT-{uuid.uuid4().hex[:8].upper()}",
        "actionType": "price_tuned",
        "summary": f"AI price-tune applied to {pid} → ${new_price:.2f}",
        "payload": {"productId": pid, "newPrice": new_price},
        "status": "executed",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "businessId": user.get("businessId"),
    })
    return {"updated": True, "productId": pid, "newPrice": new_price}


# ============================================================================
# E7 — OVERBOOKING GUARDRAIL
# ============================================================================
@router.post("/ai/overbooking-check")
async def overbooking_check(data: dict, user: dict = Depends(get_user)):
    """Staff pre-flight advisory before creating a reservation — does the
    exact same capacity math services.booking_rules_engine now enforces at
    write time (when Settings > Booking Rules has capacity enforcement
    turned on), via the same shared capacity_for_slot(), so this warning and
    what actually gets blocked can't drift apart."""
    date = data.get("date")
    time_str = data.get("time")
    party_size = int(data.get("partySize", 2))
    if not date or not time_str:
        raise HTTPException(status_code=400, detail="date + time required")

    from services.booking_rules_engine import get_rules, capacity_for_slot
    rules = await get_rules(user.get("businessId"))
    cap_info = await capacity_for_slot(date, time_str, rules, business_id=user.get("businessId"))
    available = cap_info["available"]
    allow = available >= party_size
    return {
        "allow": allow,
        "capacity": cap_info["capacity"],
        "withBuffer": cap_info["capacity"],
        "alreadyBooked": cap_info["booked"],
        "requested": party_size,
        "available": available,
        "reason": (
            f"Slot has {available} seats left (capacity {cap_info['capacity']}, "
            f"{cap_info['booked']} booked)."
            if allow else
            f"OVERBOOKED — only {available} seats left, need {party_size}."
        ),
    }


# ============================================================================
# F5 — AI COST COACH
# ============================================================================
@router.get("/ai/cost-coach")
async def cost_coach(user: dict = Depends(require_owner_or_manager)):
    """Analyze food cost % vs target, surface top offenders + LLM advice."""
    target_cost_pct = 32.0  # industry standard
    biz_scope = tenant_scope_filter(user.get("businessId"))

    products = await db.products.find(
        {"active": {"$ne": False}, **biz_scope}, {"_id": 0, "id": 1, "name": 1, "price": 1, "cost": 1, "category": 1}
    ).to_list(500)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    tx = await db.transactions.find(
        {"createdAt": {"$gte": cutoff}, **biz_scope}, {"_id": 0, "items": 1}
    ).to_list(5000)
    units = Counter()
    revenue = defaultdict(float)
    food_cost = defaultdict(float)
    for t in tx:
        for it in (t.get("items") or []):
            pid = it.get("productId")
            if not pid:
                continue
            qty = int(it.get("quantity", 1) or 1)
            units[pid] += qty
            revenue[pid] += float(it.get("price", 0) or 0) * qty
    pmap = {p["id"]: p for p in products}
    for pid, qty in units.items():
        c = float(pmap.get(pid, {}).get("cost", 0) or 0)
        food_cost[pid] = c * qty

    total_rev = sum(revenue.values()) or 1
    total_cost = sum(food_cost.values())
    overall_pct = (total_cost / total_rev) * 100

    offenders = []
    for pid, qty in units.most_common(40):
        r = revenue[pid]
        c = food_cost[pid]
        if r <= 0:
            continue
        pct = (c / r) * 100
        if pct > target_cost_pct + 5:
            offenders.append({
                "productId": pid, "name": pmap.get(pid, {}).get("name", "?"),
                "units": qty, "revenue": round(r, 2), "foodCost": round(c, 2),
                "costPct": round(pct, 1),
            })
    offenders.sort(key=lambda x: x["costPct"], reverse=True)
    offenders = offenders[:10]

    advice = ""
    if offenders:
        lines = "\n".join(
            f"- {o['name']}: {o['costPct']}% food cost on ${o['revenue']:.0f} rev" for o in offenders
        )
        out = await _llm_json(
            f"cost-coach-{uuid.uuid4().hex[:8]}",
            (
                "You are a restaurant CFO. Given the top food-cost offenders, give 3 short, concrete "
                "actions to bring food cost back to target. Return STRICT JSON: "
                '{"actions":["...","...","..."]}'
            ),
            f"Overall cost %: {overall_pct:.1f}, target {target_cost_pct}%.\nOffenders:\n{lines}",
        )
        advice = out.get("actions", []) if isinstance(out, dict) else []
    return {
        "overallCostPct": round(overall_pct, 1),
        "targetCostPct": target_cost_pct,
        "totalRevenue30d": round(total_rev, 2),
        "totalFoodCost30d": round(total_cost, 2),
        "offenders": offenders,
        "actions": advice,
    }


# ============================================================================
# F6 — PREDICTIVE LABOR FORECAST
# ============================================================================
@router.get("/ai/labor-forecast")
async def labor_forecast(user: dict = Depends(require_owner_or_manager)):
    """Forecast next 7 days of staffing needs from historical transactions."""

    # Look back 8 weeks to get day-of-week + hour patterns
    cutoff = (datetime.now(timezone.utc) - timedelta(days=56)).isoformat()
    tx = await db.transactions.find(
        {"createdAt": {"$gte": cutoff}, **tenant_scope_filter(user.get("businessId"))},
        {"_id": 0, "createdAt": 1, "total": 1}
    ).to_list(20000)
    # Buckets[day_of_week][hour] = list of (orders, revenue)
    buckets = defaultdict(lambda: defaultdict(lambda: [0, 0.0]))
    for t in tx:
        try:
            dt = datetime.fromisoformat(t["createdAt"].replace("Z", "+00:00"))
            buckets[dt.weekday()][dt.hour][0] += 1
            buckets[dt.weekday()][dt.hour][1] += float(t.get("total", 0) or 0)
        except Exception:
            continue

    # Average over the 8 weeks (= 8 samples per day-of-week)
    weeks = 8
    # Build next 7 days forecast
    forecast = []
    today = datetime.now(timezone.utc).date()
    for offset in range(7):
        d = today + timedelta(days=offset)
        dow = d.weekday()
        hour_block = []
        for h in range(8, 23):  # operating hours 8am-10pm
            o, r = buckets[dow].get(h, [0, 0.0])
            avg_orders = o / weeks
            avg_rev = r / weeks
            # Rule: 1 FOH per 12 orders/hour, min 1 if any; 1 BOH per $250/hr revenue
            foh = max(1, round(avg_orders / 12)) if avg_orders > 0 else 0
            boh = max(1, round(avg_rev / 250)) if avg_rev > 0 else 0
            hour_block.append({
                "hour": h, "avgOrders": round(avg_orders, 1),
                "avgRevenue": round(avg_rev, 2),
                "foh": foh, "boh": boh, "total": foh + boh,
            })
        forecast.append({
            "date": d.isoformat(), "dayOfWeek": d.strftime("%A"),
            "hours": hour_block,
            "peakHour": max(hour_block, key=lambda x: x["total"])["hour"] if hour_block else None,
            "totalStaffHours": sum(h["total"] for h in hour_block),
        })
    return {"weeks_analyzed": weeks, "forecast": forecast}


# ============================================================================
# F7 — DYNAMIC SURGE PRICING
# ============================================================================
@router.get("/ai/surge-recommendations")
async def surge_recommendations(user: dict = Depends(require_owner_or_manager)):
    """Per-hour-of-week surge multipliers based on historical demand peaks."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=56)).isoformat()
    tx = await db.transactions.find(
        {"createdAt": {"$gte": cutoff}, **tenant_scope_filter(user.get("businessId"))},
        {"_id": 0, "createdAt": 1}
    ).to_list(20000)
    by_hour = Counter()
    for t in tx:
        try:
            dt = datetime.fromisoformat(t["createdAt"].replace("Z", "+00:00"))
            by_hour[(dt.weekday(), dt.hour)] += 1
        except Exception:
            continue
    if not by_hour:
        return {"recommendations": []}
    avg = sum(by_hour.values()) / len(by_hour)
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    recs = []
    for (dow, hour), count in by_hour.most_common(168):
        ratio = count / avg if avg > 0 else 1
        # Surge: 1.0 (base) → 1.20 (top decile)
        if ratio >= 1.7:
            mult = 1.15
        elif ratio >= 1.3:
            mult = 1.08
        elif ratio <= 0.3:
            mult = 0.95
        else:
            mult = 1.0
        if mult != 1.0:
            recs.append({
                "day": days[dow], "dow": dow, "hour": hour,
                "demandRatio": round(ratio, 2), "multiplier": mult,
                "reason": (
                    f"{ratio:.1f}x avg demand — peak surcharge"
                    if mult > 1 else f"{ratio:.1f}x avg — discount to drive traffic"
                ),
            })
    return {"avgOrdersPerHour": round(avg, 2), "recommendations": recs[:30]}


@router.post("/ai/surge/apply")
async def apply_surge(data: dict, user: dict = Depends(require_owner)):
    """Persist a surge rule to settings so POS can pick it up.

    Scoped to the caller's own business — without this, one business
    applying surge pricing wiped (delete_many({})) and replaced every
    other business's surge rules on the deployment.
    """
    biz = user.get("businessId")
    rules = data.get("rules", [])
    await db.surge_rules.delete_many(tenant_scope_filter(biz))
    if rules:
        for r in rules:
            r["id"] = f"SURGE-{uuid.uuid4().hex[:6].upper()}"
            r["createdAt"] = datetime.now(timezone.utc).isoformat()
            r["businessId"] = biz
            await db.surge_rules.insert_one(r)
    return {"applied": len(rules)}


@router.get("/ai/surge/active")
async def active_surge(user: dict = Depends(get_user)):
    """Get current applied surge rules — for POS to multiply prices."""
    rules = await db.surge_rules.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}).to_list(200)
    now = datetime.now()
    dow, hour = now.weekday(), now.hour
    active = next((r for r in rules if r.get("dow") == dow and r.get("hour") == hour), None)
    return {"active": active, "all": rules}


# ============================================================================
# F8 — VOICE-TO-RECIPE
# ============================================================================
@router.post("/ai/voice-recipe")
async def voice_to_recipe(data: dict, user: dict = Depends(get_user)):
    """Convert a free-form chef description into a structured recipe spec."""
    if user["role"] not in ("owner", "manager", "kitchen"):
        raise HTTPException(status_code=403, detail="Kitchen/Manager/Owner only")
    text = (data.get("text") or "").strip()
    audio_base64 = data.get("audioBase64")
    mime = data.get("mime", "audio/webm")

    transcript = text
    # Optional voice path: transcribe with whisper first
    if not transcript and audio_base64:
        try:
            from emergentintegrations.llm.openai.audio import OpenAIAudio
            audio = OpenAIAudio(api_key=os.environ.get("EMERGENT_LLM_KEY"))
            import base64
            audio_bytes = base64.b64decode(audio_base64)
            transcript = await audio.audio_to_text(
                content=audio_bytes, mime_type=mime, language="en"
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")

    if not transcript:
        raise HTTPException(status_code=400, detail="text or audio required")

    sys_msg = (
        "You are a kitchen recipe converter. Given a chef's free-form description, "
        "extract a structured recipe. Return STRICT JSON: "
        '{"name":"...","yield":"4 portions","prepMin":15,"cookMin":20,'
        '"ingredients":[{"item":"...","quantity":"200g"}],"steps":["...","..."],'
        '"allergens":["gluten","dairy"],"tags":["vegan","spicy"]}'
    )
    out = await _llm_json(f"recipe-{uuid.uuid4().hex[:8]}", sys_msg, transcript)
    if "_error" in out:
        raise HTTPException(status_code=500, detail=f"LLM error: {out['_error']}")
    # Validate before persisting — name + at least one ingredient required
    if not isinstance(out, dict) or not out.get("name") or not out.get("ingredients"):
        raise HTTPException(status_code=422, detail="LLM returned incomplete recipe — please rephrase with more detail.")

    recipe = {
        "id": f"RCP-{uuid.uuid4().hex[:8].upper()}",
        "transcript": transcript,
        "createdBy": user["id"],
        "createdAt": datetime.now(timezone.utc).isoformat(),
        **(out if isinstance(out, dict) else {}),
        "businessId": user.get("businessId"),
    }
    await db.recipes.insert_one(recipe)
    recipe.pop("_id", None)
    return recipe


@router.get("/ai/recipes")
async def list_recipes(user: dict = Depends(get_user)):
    recipes = await db.recipes.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}).sort("createdAt", -1).to_list(100)
    return recipes


# ============================================================================
# F9 — KITCHEN LOAD BALANCING
# ============================================================================
@router.get("/ai/kitchen-load")
async def kitchen_load(user: dict = Depends(get_user)):
    """Surface station load + recommend rebalancing."""
    if user["role"] not in ("owner", "manager", "kitchen"):
        raise HTTPException(status_code=403, detail="Kitchen/Manager/Owner only")
    biz_scope = tenant_scope_filter(user.get("businessId"))
    # Pull open kitchen orders
    orders = await db.kitchen_orders.find(
        {"status": {"$in": ["pending", "in_progress"]}, **biz_scope}, {"_id": 0}
    ).to_list(500)
    # Group items by station (product.station or category fallback)
    products = {p["id"]: p for p in await db.products.find(biz_scope, {"_id": 0}).to_list(2000)}
    by_station = defaultdict(lambda: {"items": 0, "orders": 0, "wait": 0.0})
    now = datetime.now(timezone.utc)
    for o in orders:
        stations_in_order = set()
        for it in (o.get("items") or []):
            pid = it.get("productId")
            p = products.get(pid, {})
            station = p.get("station") or p.get("category") or "Hot Line"
            qty = int(it.get("quantity", 1) or 1)
            by_station[station]["items"] += qty
            stations_in_order.add(station)
        try:
            created = datetime.fromisoformat(o["createdAt"].replace("Z", "+00:00"))
            wait_min = (now - created).total_seconds() / 60
        except Exception:
            wait_min = 0
        for s in stations_in_order:
            by_station[s]["orders"] += 1
            by_station[s]["wait"] = max(by_station[s]["wait"], wait_min)

    stations = [
        {"station": k, "items": v["items"], "orders": v["orders"],
         "oldestWaitMin": round(v["wait"], 1)}
        for k, v in by_station.items()
    ]
    stations.sort(key=lambda x: x["oldestWaitMin"], reverse=True)

    # Recommendations: if any station >2x median items, suggest pulling staff
    if stations:
        items_sorted = sorted([s["items"] for s in stations])
        median = items_sorted[len(items_sorted) // 2] or 1
        suggestions = []
        for s in stations:
            if s["items"] >= median * 2 and median > 0:
                # Find the lightest station
                light = min(stations, key=lambda x: x["items"])
                if light["station"] != s["station"]:
                    suggestions.append({
                        "action": "rebalance",
                        "from": light["station"],
                        "to": s["station"],
                        "reason": (
                            f"{s['station']} has {s['items']} items ({s['oldestWaitMin']}min wait) — "
                            f"{light['station']} has {light['items']}. Pull 1 hand."
                        ),
                    })
            elif s["oldestWaitMin"] > 15:
                suggestions.append({
                    "action": "priority_alert",
                    "station": s["station"],
                    "reason": f"Oldest ticket on {s['station']} is {s['oldestWaitMin']} min — risk of walkout.",
                })
        return {"stations": stations, "suggestions": suggestions[:5]}
    return {"stations": [], "suggestions": []}
