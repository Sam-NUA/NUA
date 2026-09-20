"""
Predictive signals — the rules engine's 22-event catalog was entirely
reactive: inventory.low_stock and inventory.stockout only fire once a
product has already crossed a threshold or hit zero. A product selling
20/day with a 5-unit low-stock threshold can go from "fine" to "stocked
out" inside a single service, so by the time low_stock fires there may be
almost no lead time left to act on it.

This computes a forward-looking projection from recent sales velocity —
"at this rate, product X runs out in N days" — and emits it as a new event
(inventory.predicted_stockout) through the same emit_event()/ACTION_LIBRARY
pipeline every other event already uses, so existing actions (create_po,
dock_notify, etc.) work on it with no changes. It is deliberately narrow in
scope: one signal, computed from data already being written (transactions,
products), no new inputs and no model to train or maintain.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta, timezone
from database import db
from middleware.actor_context import tenant_scope_filter
from services import rules_engine
import logging

logger = logging.getLogger(__name__)

DEDUPE_HOURS = 12  # don't re-emit for the same product more than this often


async def compute_predicted_stockouts(lookback_days: int = 7, horizon_days: float = 2.0,
                                       business_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Project days-remaining for every product from its actual sales
    velocity over the last `lookback_days`, and return the ones projected
    to hit zero within `horizon_days`. Products already at/below zero are
    excluded — inventory.stockout already owns that case."""
    biz_scope = tenant_scope_filter(business_id)
    cutoff = datetime.utcnow() - timedelta(days=lookback_days)
    txns = await db.transactions.find(
        {"timestamp": {"$gte": cutoff}, "status": "completed", **biz_scope},
        {"_id": 0, "items": 1},
    ).to_list(5000)

    usage: Dict[str, float] = {}
    for t in txns:
        for it in (t.get("items") or []):
            pid = it.get("productId")
            if not pid:
                continue
            usage[pid] = usage.get(pid, 0.0) + float(it.get("quantity") or 0)

    if not usage:
        return []

    products = await db.products.find(
        {"id": {"$in": list(usage.keys())}, **biz_scope}, {"_id": 0, "id": 1, "name": 1, "stock": 1},
    ).to_list(2000)

    predictions = []
    for p in products:
        stock = p.get("stock")
        if stock is None or stock <= 0:
            continue
        avg_daily = usage.get(p["id"], 0.0) / lookback_days
        if avg_daily <= 0:
            continue
        days_remaining = stock / avg_daily
        if days_remaining <= horizon_days:
            predictions.append({
                "productId": p["id"], "productName": p.get("name"),
                "currentStock": stock, "avgDailyUsage": round(avg_daily, 2),
                "daysRemaining": round(days_remaining, 1),
            })
    predictions.sort(key=lambda x: x["daysRemaining"])
    return predictions


async def _recently_emitted(product_id: str, business_id: Optional[str] = None) -> bool:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=DEDUPE_HOURS)).isoformat()
    row = await db.rule_events.find_one({
        "type": "inventory.predicted_stockout", "entityId": product_id, "ts": {"$gte": cutoff},
        **tenant_scope_filter(business_id),
    })
    return row is not None


async def scan_and_emit_predicted_stockouts(*, lookback_days: int = 7, horizon_days: float = 2.0,
                                             business_id: Optional[str] = None) -> Dict[str, Any]:
    """Compute predictions and emit one event per product not already
    flagged in the last DEDUPE_HOURS — called from the hourly Ash scheduler
    loop, same cadence as the rest of the insight scan.

    business_id is None (scans every business) when called from that
    scheduler loop, which has no per-request actor context — a known,
    documented gap shared with nua_intelligence.py's own generators.
    routes/rules_engine.py's manual-trigger endpoint passes the caller's
    own businessId explicitly.
    """
    predictions = await compute_predicted_stockouts(
        lookback_days=lookback_days, horizon_days=horizon_days, business_id=business_id)
    emitted = []
    for pred in predictions:
        if await _recently_emitted(pred["productId"], business_id):
            continue
        try:
            await rules_engine.emit_event("inventory.predicted_stockout", pred, entity_id=pred["productId"],
                                           business_id=business_id)
            emitted.append(pred["productId"])
        except Exception as e:
            logger.warning(f"[predictive] emit failed for {pred['productId']}: {e}")
    return {"predicted": len(predictions), "emitted": len(emitted), "predictions": predictions}
