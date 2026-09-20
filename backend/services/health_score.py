"""
Business Health Score — composite 0-100 across 10 sub-scores.

Each sub-score is a deterministic function of live data, capped 0-100.
The overall score is the weighted mean; weights are env-configurable.
"""
from __future__ import annotations
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from database import db
from middleware.actor_context import tenant_scope_filter
import os
import logging

logger = logging.getLogger(__name__)


def _weight(k: str, default: float) -> float:
    try:
        return float(os.environ.get(f"HEALTH_W_{k.upper()}", default))
    except Exception:
        return default


def _clamp(x: float) -> float:
    return max(0.0, min(100.0, x))


async def _score_revenue(biz: dict) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    seven = (now - timedelta(days=7)).isoformat()
    prev_seven = (now - timedelta(days=14)).isoformat()
    recent = await db.transactions.find({"timestamp": {"$gte": seven}, **biz}, {"total": 1}).to_list(20000)
    prev = await db.transactions.find({"timestamp": {"$gte": prev_seven, "$lt": seven}, **biz}, {"total": 1}).to_list(20000)
    r_new = sum(float(t.get("total") or 0) for t in recent)
    r_prev = sum(float(t.get("total") or 0) for t in prev)
    if r_prev == 0:
        score = 70.0 if r_new > 0 else 40.0
    else:
        ratio = r_new / r_prev
        # 1.0 => 70, 1.2 => 90, 0.8 => 50
        score = _clamp(70 + (ratio - 1) * 100)
    return {"score": round(score, 1), "current": round(r_new, 2), "previous": round(r_prev, 2)}


async def _score_profit(biz: dict) -> Dict[str, Any]:
    # profit_and_loss() now scopes itself via the request's actor context
    # (services/accounting_service.py), so no business_id needs threading
    # through here explicitly.
    try:
        from services.accounting_service import profit_and_loss
        d = datetime.now(timezone.utc).date()
        pnl = await profit_and_loss((d - timedelta(days=30)).isoformat(), d.isoformat())
        gm = pnl["grossMarginPct"] or 0
        nm = pnl["netMarginPct"] or 0
        # Great gross margin for hospo = 65%+, net = 10%+
        gm_score = _clamp((gm / 65.0) * 100)
        nm_score = _clamp((nm / 10.0) * 100)
        score = round(gm_score * 0.6 + nm_score * 0.4, 1)
        return {"score": score, "grossMarginPct": gm, "netMarginPct": nm}
    except Exception as e:
        return {"score": 50.0, "error": str(e)}


async def _score_labour(biz: dict) -> Dict[str, Any]:
    seven = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    txns = await db.transactions.find({"timestamp": {"$gte": seven}, **biz}, {"total": 1}).to_list(20000)
    revenue = sum(float(t.get("total") or 0) for t in txns) or 1
    pay = await db.payroll_runs.find(biz, {"gross": 1}).sort("payDate", -1).limit(2).to_list(2) \
        if await db.payroll_runs.count_documents(biz) else []
    wages = sum(float(r.get("gross") or 0) for r in pay)
    ratio = (wages / revenue) if revenue else 0
    # Target 25-30%. Under 25 = 100, 30 = 70, 40 = 30, 50+ = 10
    if ratio <= 0.25:  score = 100.0
    elif ratio <= 0.30: score = 100 - (ratio - 0.25) * 600     # 100 → 70
    elif ratio <= 0.40: score = 70 - (ratio - 0.30) * 400     # 70 → 30
    else: score = max(10.0, 30 - (ratio - 0.40) * 200)
    return {"score": round(_clamp(score), 1), "ratioPct": round(ratio * 100, 1)}


async def _score_food_cost(biz: dict) -> Dict[str, Any]:
    products = await db.products.find(biz, {"cost": 1, "price": 1}).to_list(2000)
    margins = []
    for p in products:
        c = float(p.get("cost") or 0); pr = float(p.get("price") or 0)
        if c > 0 and pr > 0:
            margins.append((pr - c) / pr)
    if not margins:
        return {"score": 60.0, "avgMarginPct": None, "reason": "no product cost data"}
    avg = sum(margins) / len(margins)
    # target avg margin 60-70%
    score = _clamp((avg / 0.65) * 100)
    return {"score": round(score, 1), "avgMarginPct": round(avg * 100, 1)}


async def _score_csat(biz: dict) -> Dict[str, Any]:
    if await db.reviews.count_documents(biz) == 0:
        return {"score": 70.0, "note": "no reviews data"}
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    reviews = await db.reviews.find({"createdAt": {"$gte": since}, **biz}, {"rating": 1}).to_list(1000)
    if not reviews:
        return {"score": 70.0}
    avg = sum(float(r.get("rating") or 0) for r in reviews) / len(reviews)
    score = _clamp((avg / 5.0) * 100)
    return {"score": round(score, 1), "avgRating": round(avg, 2), "count": len(reviews)}


async def _score_inventory(biz: dict) -> Dict[str, Any]:
    products = await db.products.find(biz, {"stock": 1, "lowStockThreshold": 1, "parLevel": 1}).to_list(2000)
    if not products:
        return {"score": 60.0, "reason": "no products"}
    low = 0
    out = 0
    for p in products:
        s = float(p.get("stock") or 0)
        par = float(p.get("lowStockThreshold") or p.get("parLevel") or 5)
        if s <= 0: out += 1
        elif s < par: low += 1
    penalty = (out * 5) + (low * 1.5)
    score = _clamp(100 - penalty)
    return {"score": round(score, 1), "outOfStock": out, "lowStock": low, "total": len(products)}


async def _score_cash_flow(biz: dict) -> Dict[str, Any]:
    # Same actor-context self-scoping as _score_profit above.
    try:
        from services.accounting_service import cash_flow, balance_sheet
        d = datetime.now(timezone.utc).date()
        cf = await cash_flow((d - timedelta(days=30)).isoformat(), d.isoformat())
        bs = await balance_sheet(as_of=d.isoformat())
        cash = bs["totalAssets"]
        net = cf["netCash"]
        # Positive netCash & cash > $5k → high score
        base = 60 + min(30, net / 100)          # every $100 net cash = +1
        score = _clamp(base + (10 if cash > 5000 else -20 if cash < 500 else 0))
        return {"score": round(score, 1), "cash": round(cash, 2), "netCash30d": round(net, 2)}
    except Exception as e:
        return {"score": 50.0, "error": str(e)}


async def _score_compliance(biz: dict) -> Dict[str, Any]:
    """Rough compliance signal — count of open critical/high compliance-ish insights."""
    q = {"resolvedAt": None,
         "category": {"$in": ["theft", "fraud", "burnout", "waste"]},
         "severity": {"$in": ["high", "warning"]}, **biz}
    n = await db.ash_insights.count_documents(q)
    score = _clamp(100 - (n * 8))
    return {"score": round(score, 1), "openRisks": n}


async def _score_equipment(biz: dict) -> Dict[str, Any]:
    if await db.devices.count_documents(biz) == 0:
        return {"score": 80.0, "note": "no devices tracked"}
    total = await db.devices.count_documents(biz)
    healthy = await db.devices.count_documents({"status": {"$in": ["online", "healthy", "ok"]}, **biz})
    score = _clamp((healthy / max(1, total)) * 100)
    return {"score": round(score, 1), "healthy": healthy, "total": total}


async def _score_ai_confidence(biz: dict) -> Dict[str, Any]:
    """How much of Ash's output has been actioned lately? Rejected? Left open?"""
    total = await db.ash_insights.count_documents(biz)
    resolved = await db.ash_insights.count_documents({"resolvedAt": {"$ne": None}, **biz})
    rejected = await db.approvals.count_documents({"status": "rejected", **biz})
    approved = await db.approvals.count_documents({"status": "approved", **biz})
    resolution_ratio = (resolved / total) if total else 0.7
    trust = (approved / max(1, approved + rejected))
    score = _clamp(50 + (resolution_ratio * 25) + (trust * 25))
    return {"score": round(score, 1), "resolvedRatio": round(resolution_ratio, 2), "trust": round(trust, 2)}


SUBSCORES: Dict[str, tuple] = {
    "revenue":      (_score_revenue,      1.0),
    "profit":       (_score_profit,       1.2),
    "labour":       (_score_labour,       1.0),
    "foodCost":     (_score_food_cost,    0.8),
    "csat":         (_score_csat,         1.0),
    "inventory":    (_score_inventory,    0.8),
    "cashFlow":     (_score_cash_flow,    1.2),
    "compliance":   (_score_compliance,   0.8),
    "equipment":    (_score_equipment,    0.6),
    "aiConfidence": (_score_ai_confidence, 0.5),
}


async def compute_health(business_id: Optional[str] = None) -> Dict[str, Any]:
    if business_id is None:
        from middleware.actor_context import get_actor_context
        business_id = get_actor_context().get("businessId")
    biz = tenant_scope_filter(business_id)
    results: Dict[str, Any] = {}
    total_weight = 0.0
    weighted = 0.0
    for key, (fn, default_w) in SUBSCORES.items():
        w = _weight(key, default_w)
        try:
            sub = await fn(biz)
        except Exception as e:
            sub = {"score": 50.0, "error": str(e)}
        results[key] = {**sub, "weight": w}
        weighted += float(sub.get("score") or 50) * w
        total_weight += w
    overall = round(weighted / total_weight, 1) if total_weight else 0.0
    tier = "excellent" if overall >= 85 else "healthy" if overall >= 70 else \
            "watch" if overall >= 55 else "at_risk" if overall >= 40 else "critical"
    return {
        "overall": overall,
        "tier": tier,
        "subscores": results,
        "computedAt": datetime.now(timezone.utc).isoformat(),
    }
