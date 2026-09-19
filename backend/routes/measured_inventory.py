"""
Measured / Fractional Stock — HTTP routes.

Every mutation goes through stamped_insert / stamped_update from
services/entity_service so version, audit, actor, device, ip are stamped
uniformly with the rest of the system.

Mount path: /api/measured-inventory
"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional, Dict, Any
from database import db
from deps import get_user
from middleware.actor_context import tenant_scope_filter
from services.entity_service import stamped_insert
from services import measured_inventory_service as mi
from models.measured_inventory import (
    StockUnitCreate, SellVariantCreate, OpenContainerCreate, WastageEventCreate,
)
import uuid

router = APIRouter(prefix="/measured-inventory")


def _require_manager(user: dict) -> None:
    if user.get("role") not in ("owner", "manager"):
        raise HTTPException(403, "Owner or manager only")


# stock_units/sell_variants/open_containers/wastage_events all get a
# businessId stamped automatically (stamped_insert -> _stamp_new), but
# nothing here ever filtered a READ by it — margin/cost/wastage data, so
# every staff member of every business could read and write any other
# business's pour costs, margins and stock-unit definitions. Scoped
# transitively through db.products (the FK every one of these ultimately
# chains back to) rather than a direct businessId match, deliberately: a
# transitive check still holds even for a document some other write path
# ever creates without stamped_insert's automatic stamping (unlike a plain
# tenant_scope_filter on businessId, which treats a missing field as
# universally visible — the right call for genuinely legacy pre-stamping
# data, not for a bug in a future writer of these specific collections).
async def _owned_product_ids(business_id: Optional[str]) -> Optional[set]:
    """None = don't restrict (no businessId on this caller — same safe
    default tenant_scope_filter itself uses)."""
    if not business_id:
        return None
    rows = await db.products.find(tenant_scope_filter(business_id), {"_id": 0, "id": 1}).to_list(100000)
    return {r["id"] for r in rows}


async def _owned_stock_unit_ids(business_id: Optional[str]) -> Optional[set]:
    owned_products = await _owned_product_ids(business_id)
    if owned_products is None:
        return None
    rows = await db.stock_units.find(
        {"productId": {"$in": list(owned_products)}}, {"_id": 0, "id": 1}
    ).to_list(100000)
    return {r["id"] for r in rows}


async def _product_owned(product_id: str, business_id: Optional[str]) -> bool:
    owned = await _owned_product_ids(business_id)
    return owned is None or product_id in owned


async def _stock_unit_owned(stock_unit_id: str, business_id: Optional[str]) -> bool:
    su = await db.stock_units.find_one({"id": stock_unit_id}, {"_id": 0, "productId": 1})
    if not su:
        return True  # let the 404 come from the caller's own not-found handling
    return await _product_owned(su["productId"], business_id)


async def _owned_open_container_ids(business_id: Optional[str]) -> Optional[set]:
    owned_su = await _owned_stock_unit_ids(business_id)
    if owned_su is None:
        return None
    rows = await db.open_containers.find(
        {"stockUnitId": {"$in": list(owned_su)}}, {"_id": 0, "id": 1}
    ).to_list(100000)
    return {r["id"] for r in rows}


# ─── StockUnit ────────────────────────────────────────────────────────────
@router.post("/stock-units")
async def create_stock_unit(body: StockUnitCreate, user: dict = Depends(get_user)):
    _require_manager(user)
    if not await _product_owned(body.productId, user.get("businessId")):
        raise HTTPException(404, "productId does not exist")
    doc = {"id": str(uuid.uuid4()), **body.dict()}
    return await stamped_insert("stock_units", doc, entity_type="stock_unit")


@router.get("/stock-units")
async def list_stock_units(productId: Optional[str] = None, user: dict = Depends(get_user)):
    q: Dict[str, Any] = {"deletedAt": None}
    owned = await _owned_product_ids(user.get("businessId"))
    if productId:
        # Requesting a specific product this business doesn't own must come
        # back empty, not silently fall through to every product's units.
        if owned is not None and productId not in owned:
            return []
        q["productId"] = productId
    elif owned is not None:
        q["productId"] = {"$in": list(owned)}
    return await db.stock_units.find(q, {"_id": 0}).to_list(500)


@router.post("/stock-units/{stock_unit_id}/open")
async def open_stock_unit(stock_unit_id: str, body: Optional[OpenContainerCreate] = None,
                            user: dict = Depends(get_user)):
    if not await _stock_unit_owned(stock_unit_id, user.get("businessId")):
        raise HTTPException(404, "Stock unit not found")
    station_id = (body.stationId if body else None) if body else None
    try:
        c = await mi.open_container(
            stock_unit_id,
            actor=user.get("email") or "system",
            station_id=station_id,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))
    return c


# ─── SellVariant ──────────────────────────────────────────────────────────
@router.post("/sell-variants")
async def create_sell_variant(body: SellVariantCreate, user: dict = Depends(get_user)):
    _require_manager(user)
    su = await db.stock_units.find_one({"id": body.stockUnitId}, {"_id": 0})
    if not su or not await _product_owned(su["productId"], user.get("businessId")):
        raise HTTPException(404, "stockUnitId does not exist")
    doc = {"id": str(uuid.uuid4()), **body.dict()}
    return await stamped_insert("sell_variants", doc, entity_type="sell_variant")


@router.get("/sell-variants")
async def list_sell_variants(productId: Optional[str] = None, user: dict = Depends(get_user)):
    q: Dict[str, Any] = {"deletedAt": None}
    owned = await _owned_product_ids(user.get("businessId"))
    if productId:
        if owned is not None and productId not in owned:
            return []
        q["productId"] = productId
    elif owned is not None:
        q["productId"] = {"$in": list(owned)}
    return await db.sell_variants.find(q, {"_id": 0}).to_list(500)


# ─── OpenContainer ────────────────────────────────────────────────────────
@router.get("/open-containers")
async def list_open_containers(stockUnitId: Optional[str] = None,
                                 stationId: Optional[str] = None,
                                 includeClosed: bool = False,
                                 user: dict = Depends(get_user)):
    q: Dict[str, Any] = {"deletedAt": None}
    if not includeClosed:
        q["closedAt"] = None
    owned_su = await _owned_stock_unit_ids(user.get("businessId"))
    if stockUnitId:
        if owned_su is not None and stockUnitId not in owned_su:
            return []
        q["stockUnitId"] = stockUnitId
    elif owned_su is not None:
        q["stockUnitId"] = {"$in": list(owned_su)}
    if stationId:
        q["stationId"] = stationId
    return await db.open_containers.find(q, {"_id": 0}).sort("openedAt", -1).to_list(500)


# ─── Wastage ──────────────────────────────────────────────────────────────
@router.post("/wastage")
async def log_wastage(body: WastageEventCreate, user: dict = Depends(get_user)):
    """Log a wastage event. If openContainerId is provided the container's
    remainingMeasure is decremented; otherwise it's logged against sealed
    stock only (no container mutation)."""
    if not body.openContainerId and not body.stockUnitId:
        raise HTTPException(400, "openContainerId or stockUnitId is required")
    check_su_id = body.stockUnitId
    if not check_su_id and body.openContainerId:
        oc = await db.open_containers.find_one({"id": body.openContainerId}, {"_id": 0, "stockUnitId": 1})
        check_su_id = oc.get("stockUnitId") if oc else None
    if check_su_id and not await _stock_unit_owned(check_su_id, user.get("businessId")):
        raise HTTPException(404, "stockUnitId does not exist")
    actor = user.get("email") or "system"
    doc = {"id": str(uuid.uuid4()), **body.dict(), "loggedBy": actor}
    saved = await stamped_insert("wastage_events", doc, entity_type="wastage_event")
    if body.openContainerId:
        try:
            await mi.apply_wastage_to_container(
                body.openContainerId, body.amount, body.uom, actor=actor,
            )
        except ValueError as e:
            raise HTTPException(404, str(e))
    return saved


@router.get("/wastage")
async def list_wastage(stockUnitId: Optional[str] = None,
                        openContainerId: Optional[str] = None,
                        limit: int = 200, user: dict = Depends(get_user)):
    q: Dict[str, Any] = {"deletedAt": None}
    if stockUnitId:
        if not await _stock_unit_owned(stockUnitId, user.get("businessId")):
            return []
        q["stockUnitId"] = stockUnitId
    if openContainerId:
        owned_oc_for_filter = await _owned_open_container_ids(user.get("businessId"))
        if owned_oc_for_filter is not None and openContainerId not in owned_oc_for_filter:
            return []
        q["openContainerId"] = openContainerId
    if not stockUnitId and not openContainerId:
        # A wastage event carries stockUnitId, openContainerId, or both
        # (both are optional on the model) — scoping must match either,
        # or a container-only-logged event would silently vanish from its
        # own business's list, not just from a different business's.
        owned_su = await _owned_stock_unit_ids(user.get("businessId"))
        if owned_su is not None:
            owned_oc = await _owned_open_container_ids(user.get("businessId"))
            q["$or"] = [{"stockUnitId": {"$in": list(owned_su)}},
                        {"openContainerId": {"$in": list(owned_oc)}}]
    return await db.wastage_events.find(q, {"_id": 0}).sort("createdAt", -1).limit(limit).to_list(limit)


# ─── Reconcile ────────────────────────────────────────────────────────────
@router.post("/stocktake/{stock_unit_id}/reconcile")
async def reconcile(stock_unit_id: str, body: dict, user: dict = Depends(get_user)):
    _require_manager(user)
    if not await _stock_unit_owned(stock_unit_id, user.get("businessId")):
        raise HTTPException(404, "Stock unit not found")
    if "countedRemaining" not in body or "uom" not in body:
        raise HTTPException(400, "countedRemaining and uom are required")
    try:
        return await mi.reconcile_stocktake(
            stock_unit_id, float(body["countedRemaining"]), body["uom"],
            actor=user.get("email") or "system",
            threshold_pct=float(body.get("thresholdPct") or 0.05),
        )
    except ValueError as e:
        raise HTTPException(404, str(e))


# ─── Read-only helpers for the UI ─────────────────────────────────────────
@router.get("/product/{product_id}/summary")
async def product_summary(product_id: str, user: dict = Depends(get_user)):
    """Everything the MeasuredStock UI needs for one product: its stock
    units, their live open containers, and its sell variants."""
    if not await _product_owned(product_id, user.get("businessId")):
        raise HTTPException(404, "product not found")
    stock_units = await db.stock_units.find({"productId": product_id, "deletedAt": None}, {"_id": 0}).to_list(50)
    sell_variants = await db.sell_variants.find({"productId": product_id, "deletedAt": None}, {"_id": 0}).to_list(50)
    su_ids = [s["id"] for s in stock_units]
    open_containers = []
    if su_ids:
        open_containers = await db.open_containers.find(
            {"stockUnitId": {"$in": su_ids}, "closedAt": None, "deletedAt": None},
            {"_id": 0},
        ).to_list(200)
    reorder = await mi.reorder_available(product_id)
    return {
        "productId": product_id,
        "stockUnits": stock_units,
        "sellVariants": sell_variants,
        "openContainers": open_containers,
        "reorderAvailable": reorder,
    }


@router.get("/beverage-margin/{product_id}")
async def beverage_margin(product_id: str, user: dict = Depends(get_user)):
    """True margin for a measured beverage product: pour cost vs sell price.
    Falls back with a `measured: False` payload for non-measured products
    so the UI can show recipe cost instead."""
    from middleware.actor_context import tenant_owns_strict
    prod = await db.products.find_one({"$and": [{"id": product_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not prod or not tenant_owns_strict(prod.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "product not found")
    cost = await mi.beverage_cost(product_id)
    if not cost:
        return {"measured": False, "productId": product_id,
                "price": float(prod.get("price") or 0)}
    price = float(prod.get("price") or 0)
    margin = price - cost["costPerPour"]
    margin_pct = (margin / price) if price > 0 else 0.0
    return {"measured": True, "productId": product_id,
            "productName": prod.get("name"), "price": price,
            "cost": cost["costPerPour"],
            "poursPerContainer": cost["poursPerContainer"],
            "containerCost": cost["containerCost"],
            "margin": round(margin, 2),
            "marginPct": round(margin_pct, 4)}


@router.get("/beverage-margin")
async def beverage_margin_all(user: dict = Depends(get_user)):
    """P&L-ready roll-up of every measured beverage's margin. Feeds NUA
    Finance and the Menu Engineering matrix so beverages sit on the same
    data as food items."""
    owned = await _owned_product_ids(user.get("businessId"))
    variant_q = {"deletedAt": None}
    if owned is not None:
        variant_q["productId"] = {"$in": list(owned)}
    variants = await db.sell_variants.find(variant_q, {"_id": 0}).to_list(500)
    seen: set = set()
    rows = []
    for v in variants:
        if v["productId"] in seen:
            continue
        seen.add(v["productId"])
        prod = await db.products.find_one({"id": v["productId"]}, {"_id": 0, "name": 1, "category": 1, "price": 1})
        if not prod:
            continue
        c = await mi.beverage_cost(v["productId"])
        if not c:
            continue
        price = float(prod.get("price") or 0)
        margin = price - c["costPerPour"]
        rows.append({
            "productId": v["productId"], "productName": prod.get("name"),
            "category": prod.get("category"), "price": price,
            "costPerPour": c["costPerPour"],
            "margin": round(margin, 2),
            "marginPct": round((margin / price) if price > 0 else 0, 4),
            "poursPerContainer": c["poursPerContainer"],
        })
    rows.sort(key=lambda x: x["marginPct"], reverse=True)
    return rows


@router.get("/open-containers/all")
async def all_open_containers(user: dict = Depends(get_user)):
    """Every container currently open, decorated with its stock unit +
    product for the top-level Measured Stock page."""
    oc_q: Dict[str, Any] = {"closedAt": None, "deletedAt": None}
    owned_su = await _owned_stock_unit_ids(user.get("businessId"))
    if owned_su is not None:
        oc_q["stockUnitId"] = {"$in": list(owned_su)}
    conts = await db.open_containers.find(oc_q, {"_id": 0}).sort("openedAt", -1).to_list(500)
    out = []
    for c in conts:
        su = await db.stock_units.find_one({"id": c["stockUnitId"]}, {"_id": 0})
        prod = None
        if su:
            prod = await db.products.find_one({"id": su["productId"]}, {"_id": 0, "id": 1, "name": 1, "category": 1})
        # Try to estimate "glasses left" using the SMALLEST sell variant
        est_serves = None
        if su:
            sv = await db.sell_variants.find_one(
                {"stockUnitId": c["stockUnitId"], "deletedAt": None}, {"_id": 0},
                sort=[("deductAmount", 1)],
            )
            if sv and float(sv.get("deductAmount") or 0) > 0:
                try:
                    remaining_in_sv_uom = await mi.convert(
                        float(c["remainingMeasure"]), su["uom"], sv["uom"],
                    )
                    est_serves = {
                        "count": round(remaining_in_sv_uom / float(sv["deductAmount"]), 1),
                        "label": sv.get("label") or f"{sv['deductAmount']}{sv['uom']}",
                    }
                except Exception:
                    pass
        out.append({
            **c,
            "stockUnit": su,
            "product": prod,
            "estimatedServes": est_serves,
        })
    return out
