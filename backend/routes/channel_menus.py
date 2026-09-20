"""
Channel Menus — per-channel pricing, availability, prep time and AI discounts.

A "channel" is any place the menu surfaces: website, Uber Eats, DoorDash,
Menulog, Deliveroo, QR ordering, kiosk, etc. Each channel can override
per-product price, modifier price, prep time and availability without
mutating the master Product document.

Data model (collection: channel_menus):
  {
    id, channel, productId, available, priceOverride, costOverride,
    modifierPriceMultiplier (%), prepTimeMin, lastSyncedAt, source
  }
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
from database import db
from deps import get_user, require_owner_or_manager
from middleware.actor_context import tenant_scope_filter
import uuid

router = APIRouter()

# ---- supported channels (canonical slugs) -------------------------------
SUPPORTED_CHANNELS = [
    {"slug": "website", "label": "Website / Online Order"},
    {"slug": "uber_eats", "label": "Uber Eats"},
    {"slug": "doordash", "label": "DoorDash"},
    {"slug": "menulog", "label": "Menulog"},
    {"slug": "deliveroo", "label": "Deliveroo"},
    {"slug": "qr_order", "label": "QR Code Ordering"},
    {"slug": "kiosk", "label": "Self-Service Kiosk"},
    {"slug": "phone", "label": "Phone Order"},
]

# ---- auth helper (re-used pattern from products.py) ---------------------
# Now uses central deps.require_owner_or_manager for consistency.

# ---- Models -------------------------------------------------------------
class ChannelMenuRow(BaseModel):
    id: str
    channel: str
    productId: str
    productName: str = ""
    available: bool = True
    priceOverride: Optional[float] = None       # absolute override (after deltas)
    costOverride: Optional[float] = None
    modifierPriceMultiplier: float = 1.0        # 1.05 = +5%, 0.9 = -10%
    prepTimeMin: Optional[int] = None
    lastSyncedAt: Optional[str] = None
    aiNotes: Optional[str] = None

def _round(value: float, mode: str = "nearest_5c") -> float:
    if mode == "nearest_5c":
        return round(value * 20) / 20.0    # 0.05 increments
    if mode == "nearest_10c":
        return round(value * 10) / 10.0
    if mode == "psychological_99":
        # 4.49, 5.99 style — floor to int + .99
        return float(int(value)) + 0.99
    return round(value, 2)

# ---- Endpoints ----------------------------------------------------------
@router.get("/channel-menus/channels")
async def list_channels(_: dict = Depends(get_user)):
    return SUPPORTED_CHANNELS

@router.get("/channel-menus/{channel}")
async def list_channel_menu(channel: str, user: dict = Depends(get_user)):
    """Return the full per-product table for a given channel (merging the
    master product list with any per-channel overrides)."""
    biz = user.get("businessId")
    products = await db.products.find(tenant_scope_filter(biz), {"_id": 0}).to_list(2000)
    overrides_list = await db.channel_menus.find(
        {"channel": channel, **tenant_scope_filter(biz)}, {"_id": 0}
    ).to_list(2000)
    overrides = {o["productId"]: o for o in overrides_list}
    out = []
    for p in products:
        ov = overrides.get(p["id"])
        out.append({
            "productId": p["id"],
            "productName": p.get("name"),
            "category": p.get("category"),
            "basePrice": p.get("price"),
            "baseCost": p.get("cost"),
            "basePrepTime": p.get("prepTimeMin", 12),
            "modifierIds": p.get("modifierIds", []),
            "channel": channel,
            "available": ov.get("available", True) if ov else True,
            "priceOverride": (ov or {}).get("priceOverride"),
            "costOverride": (ov or {}).get("costOverride"),
            "modifierPriceMultiplier": (ov or {}).get("modifierPriceMultiplier", 1.0),
            "prepTimeMin": (ov or {}).get("prepTimeMin"),
            "lastSyncedAt": (ov or {}).get("lastSyncedAt"),
            "aiNotes": (ov or {}).get("aiNotes"),
        })
    return out

class ChannelMenuPatch(BaseModel):
    productId: str
    available: Optional[bool] = None
    priceOverride: Optional[float] = None
    costOverride: Optional[float] = None
    modifierPriceMultiplier: Optional[float] = None
    prepTimeMin: Optional[int] = None

@router.post("/channel-menus/{channel}/patch")
async def patch_row(channel: str, body: ChannelMenuPatch, user: dict = Depends(require_owner_or_manager)):
    update: dict = {k: v for k, v in body.dict().items() if k != "productId" and v is not None}
    if not update:
        return {"updated": 0}
    update["lastSyncedAt"] = datetime.now(timezone.utc).isoformat()
    update["channel"] = channel
    biz = user.get("businessId")
    res = await db.channel_menus.update_one(
        {"channel": channel, "productId": body.productId, **tenant_scope_filter(biz)},
        {"$set": update, "$setOnInsert": {"id": str(uuid.uuid4()), "businessId": biz}},
        upsert=True,
    )
    return {"updated": 1, "matched": res.matched_count, "upserted": bool(res.upserted_id)}

class BulkPriceBody(BaseModel):
    productIds: List[str] = []                  # empty = all products
    deltaPercent: Optional[float] = None
    deltaDollars: Optional[float] = None
    applyToModifiers: bool = False
    roundingMode: str = "nearest_5c"            # nearest_5c | nearest_10c | psychological_99 | none

@router.post("/channel-menus/{channel}/bulk-price")
async def bulk_price(channel: str, body: BulkPriceBody, user: dict = Depends(require_owner_or_manager)):
    """Apply a ± percent and/or ± dollars delta to a channel's prices, with
    rounding. Modifier multipliers are stored as a per-product factor so they
    cascade automatically at order time.
    """
    if body.deltaPercent is None and body.deltaDollars is None:
        raise HTTPException(status_code=400, detail="Provide deltaPercent and/or deltaDollars")
    biz = user.get("businessId")
    q: dict = tenant_scope_filter(biz)
    if body.productIds:
        q["id"] = {"$in": body.productIds}
    products = await db.products.find(q, {"_id": 0}).to_list(2000)
    if not products:
        return {"updated": 0, "message": "No products matched"}
    now_iso = datetime.now(timezone.utc).isoformat()
    mod_mult = 1.0
    if body.applyToModifiers and body.deltaPercent is not None:
        mod_mult = max(0.01, 1 + float(body.deltaPercent) / 100.0)

    pct = max(-99.0, float(body.deltaPercent or 0))
    fix = float(body.deltaDollars or 0)
    updated = 0
    for p in products:
        base = float(p.get("price") or 0)
        new_price = max(0.0, base * (1 + pct / 100.0) + fix)
        new_price = _round(new_price, body.roundingMode)
        patch = {
            "channel": channel,
            "productId": p["id"],
            "productName": p.get("name"),
            "priceOverride": round(new_price, 2),
            "lastSyncedAt": now_iso,
        }
        if body.applyToModifiers:
            patch["modifierPriceMultiplier"] = round(mod_mult, 4)
        await db.channel_menus.update_one(
            {"channel": channel, "productId": p["id"], **tenant_scope_filter(biz)},
            {"$set": patch, "$setOnInsert": {"id": str(uuid.uuid4()), "businessId": biz}},
            upsert=True,
        )
        updated += 1
    return {"updated": updated, "applyToModifiers": body.applyToModifiers, "roundingMode": body.roundingMode}


# ---- AI prep time sync (kitchen heat) -----------------------------------
@router.post("/channel-menus/{channel}/ai-prep-times")
async def ai_prep_times(channel: str, user: dict = Depends(require_owner_or_manager)):
    """Synchronise per-channel prep times based on current kitchen load.

    Heat = active KDS tickets in the last 30 minutes. We bump prep time by
    1.5x at >10 tickets, 1.25x at 6-10, 1.1x at 3-5, otherwise base.
    """
    biz = user.get("businessId")
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    ticket_count = await db.kds_orders.count_documents({
        "createdAt": {"$gte": cutoff},
        "status": {"$in": ["pending", "in_progress", "preparing"]},
        **tenant_scope_filter(biz),
    })
    if ticket_count > 10:
        mult, heat = 1.5, "very_high"
    elif ticket_count > 5:
        mult, heat = 1.25, "high"
    elif ticket_count > 2:
        mult, heat = 1.1, "warm"
    else:
        mult, heat = 1.0, "cool"

    products = await db.products.find(tenant_scope_filter(biz), {"_id": 0}).to_list(2000)
    now_iso = datetime.now(timezone.utc).isoformat()
    updated = 0
    for p in products:
        base_prep = int(p.get("prepTimeMin", 12) or 12)
        new_prep = max(1, int(round(base_prep * mult)))
        await db.channel_menus.update_one(
            {"channel": channel, "productId": p["id"], **tenant_scope_filter(biz)},
            {"$set": {
                "channel": channel, "productId": p["id"],
                "productName": p.get("name"),
                "prepTimeMin": new_prep,
                "aiNotes": f"Auto-set from kitchen heat ({heat}, ×{mult})",
                "lastSyncedAt": now_iso,
            }, "$setOnInsert": {"id": str(uuid.uuid4()), "businessId": biz}},
            upsert=True,
        )
        updated += 1
    return {"updated": updated, "heat": heat, "multiplier": mult, "activeTickets": ticket_count}


# ---- AI auto-discount on slow-movers ------------------------------------
@router.post("/channel-menus/{channel}/ai-discount-slow")
async def ai_discount_slow_movers(channel: str, body: dict, user: dict = Depends(require_owner_or_manager)):
    """Apply an AI-recommended discount to the bottom-N slowest-selling
    products of the last 7 days. Aims to clear stock + drive upsell.
    body: { discountPercent?: 15, bottomN?: 5, daysWindow?: 7 }
    """
    biz = user.get("businessId")
    discount = float(body.get("discountPercent", 15))
    bottom_n = int(body.get("bottomN", 5))
    days = int(body.get("daysWindow", 7))
    if not (1 <= discount <= 70):
        raise HTTPException(status_code=400, detail="discountPercent must be 1..70")

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    pipeline = [
        {"$match": {"createdAt": {"$gte": cutoff}, **tenant_scope_filter(biz)}},
        {"$unwind": "$items"},
        {"$group": {"_id": "$items.productId", "qty": {"$sum": "$items.quantity"}, "name": {"$first": "$items.productName"}}},
        {"$sort": {"qty": 1}},
    ]
    rows = await db.transactions.aggregate(pipeline).to_list(2000)
    sold_ids = {r["_id"] for r in rows}
    # Products that didn't sell at all are even slower — surface them first.
    all_products = await db.products.find(tenant_scope_filter(biz), {"_id": 0, "id": 1, "name": 1, "price": 1}).to_list(2000)
    unsold = [{"_id": p["id"], "qty": 0, "name": p["name"], "price": p["price"]} for p in all_products if p["id"] not in sold_ids]
    # Merge: unsold first, then weakest sellers
    weakest = unsold + rows
    weakest = weakest[:bottom_n]

    now_iso = datetime.now(timezone.utc).isoformat()
    # all_products (fetched above) already has price + name for every
    # product — this loop used to re-fetch each one individually with its
    # own find_one(), which was both an N+1 and, for every unsold row, a
    # literally redundant re-fetch of data already in hand.
    product_by_id = {p["id"]: p for p in all_products}
    applied = []
    for row in weakest:
        pid = row["_id"]
        prod = product_by_id.get(pid)
        if not prod:
            continue
        base = float(prod.get("price") or 0)
        new_price = _round(base * (1 - discount / 100.0), "nearest_5c")
        await db.channel_menus.update_one(
            {"channel": channel, "productId": pid, **tenant_scope_filter(biz)},
            {"$set": {
                "channel": channel, "productId": pid,
                "productName": prod.get("name"),
                "priceOverride": new_price,
                "aiNotes": f"AI slow-mover discount -{discount}% (sold {row.get('qty', 0)}/{days}d)",
                "lastSyncedAt": now_iso,
            }, "$setOnInsert": {"id": str(uuid.uuid4()), "businessId": biz}},
            upsert=True,
        )
        applied.append({
            "productId": pid,
            "productName": prod.get("name"),
            "basePrice": base,
            "newPrice": new_price,
            "soldQty": row.get("qty", 0),
        })
    return {"discountPercent": discount, "daysWindow": days, "applied": applied}


@router.delete("/channel-menus/{channel}/{product_id}")
async def remove_override(channel: str, product_id: str, user: dict = Depends(require_owner_or_manager)):
    res = await db.channel_menus.delete_one(
        {"channel": channel, "productId": product_id, **tenant_scope_filter(user.get("businessId"))}
    )
    return {"deleted": res.deleted_count}
