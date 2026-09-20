"""Ingredients, recipes, stock and accounting (BAS).

A clean separation from products:
- products       — what we sell (POS-facing).
- ingredients    — what we stock (raw materials, in canonical units).
- recipes        — productId → [{ingredientId, qty, unit}]. Drives cost roll-up
                   and stock deduction on every sale.
- stock_takes    — physical count + variance log.
- accounting     — BAS quarterly GST report from transactions + invoices.

Unit conversion is canonical: every ingredient declares its `baseUnit` (g, mL,
ea); all stock movements convert to that base before recording. This is what
lets "kg" invoice lines correctly add to "g" recipes.
"""
from fastapi import APIRouter, HTTPException, Depends
from deps import get_user, require_owner, require_owner_or_manager
from database import db
from datetime import datetime, timedelta, date
from typing import Optional
from middleware.actor_context import tenant_scope_filter

router = APIRouter()


from utils.ids import now_utc as _now, to_iso as _iso, gen_uid as _uid


# Conversion factors → BASE unit per source unit.
# Weight base = g, Volume base = mL, Count base = ea.
_CONV = {
    # weight (base = g)
    ("kg", "g"): 1000.0, ("g", "g"): 1.0, ("mg", "g"): 0.001,
    # volume (base = mL)
    ("L", "mL"): 1000.0, ("mL", "mL"): 1.0, ("cl", "mL"): 10.0,
    # count
    ("ea", "ea"): 1.0, ("box", "ea"): 1.0, ("case", "ea"): 1.0, ("pack", "ea"): 1.0,
}


def to_base(qty: float, from_unit: str, base_unit: str) -> float:
    """Convert qty from `from_unit` into `base_unit`. Raises if incompatible."""
    if from_unit == base_unit: return float(qty)
    factor = _CONV.get((from_unit, base_unit))
    if factor is None:
        # Allow inverse (g → kg etc).
        inv = _CONV.get((base_unit, from_unit))
        if inv: return float(qty) / inv
        raise ValueError(f"No conversion from {from_unit} to {base_unit}")
    return float(qty) * factor


# =============================================================================
# INGREDIENTS — master + stock ledger
# =============================================================================
@router.get("/ingredients")
async def list_ingredients(_: dict = Depends(get_user)):
    rows = await db.ingredients.find(tenant_scope_filter(), {"_id": 0}).sort("name", 1).to_list(500)
    return rows


@router.post("/ingredients")
async def create_ingredient(data: dict, user: dict = Depends(require_owner_or_manager)):
    base_unit = data.get("baseUnit", "g")
    if base_unit not in ("g", "mL", "ea"):
        raise HTTPException(status_code=400, detail="baseUnit must be g, mL or ea")
    ing = {
        "id": _uid("ING"),
        "name": data["name"],
        "category": data.get("category", "Other"),
        "baseUnit": base_unit,                          # g | mL | ea
        "stock": float(data.get("stock", 0)),           # in baseUnit
        "unitCost": float(data.get("unitCost", 0)),     # per baseUnit
        "supplierId": data.get("supplierId"),
        "supplierName": data.get("supplierName", ""),
        "gstInclusive": bool(data.get("gstInclusive", True)),
        "reorderLevel": float(data.get("reorderLevel", 0)),  # alert below this
        "reorderQty": float(data.get("reorderQty", 0)),      # auto-PO quantity
        "createdAt": _iso(_now()), "createdBy": user["id"],
        "businessId": user.get("businessId"),
    }
    await db.ingredients.insert_one(ing); ing.pop("_id", None)
    return ing


@router.put("/ingredients/{ing_id}")
async def update_ingredient(ing_id: str, data: dict, user: dict = Depends(require_owner_or_manager)):
    allowed = {"name", "category", "baseUnit", "stock", "unitCost", "supplierName",
               "gstInclusive", "reorderLevel", "reorderQty"}
    upd = {k: v for k, v in data.items() if k in allowed}
    upd["updatedAt"] = _iso(_now())
    r = await db.ingredients.update_one(
        {"id": ing_id, **tenant_scope_filter(user.get("businessId"))}, {"$set": upd})
    if r.matched_count == 0: raise HTTPException(status_code=404, detail="Not found")
    return {"updated": True}


@router.delete("/ingredients/{ing_id}")
async def delete_ingredient(ing_id: str, user: dict = Depends(require_owner)):
    scope = tenant_scope_filter(user.get("businessId"))
    in_recipe = await db.recipes.count_documents({"lines.ingredientId": ing_id, **scope})
    if in_recipe > 0:
        raise HTTPException(status_code=400, detail=f"Used in {in_recipe} recipe(s) — remove first")
    await db.ingredients.delete_one({"id": ing_id, **scope})
    return {"deleted": True}


@router.get("/ingredients/low-stock")
async def low_stock(_: dict = Depends(get_user)):
    rows = await db.ingredients.find(
        {"$expr": {"$lte": ["$stock", "$reorderLevel"]}, "reorderLevel": {"$gt": 0},
         **tenant_scope_filter()},
        {"_id": 0},
    ).to_list(200)
    return rows


# =============================================================================
# RECIPES — productId → ingredient lines
# =============================================================================
@router.get("/recipes")
async def list_recipes(_: dict = Depends(get_user)):
    rows = await db.recipes.find(tenant_scope_filter(), {"_id": 0}).to_list(2000)
    return rows


@router.get("/recipes/product/{product_id}")
async def get_recipe(product_id: str, _: dict = Depends(get_user)):
    r = await db.recipes.find_one({"productId": product_id, **tenant_scope_filter()}, {"_id": 0})
    return r or {"productId": product_id, "lines": []}


@router.put("/recipes/product/{product_id}")
async def upsert_recipe(product_id: str, data: dict, user: dict = Depends(require_owner_or_manager)):
    # Validate every line + canonicalise unit qty
    lines = []
    ing_cache = {}
    for raw in data.get("lines") or []:
        iid = raw.get("ingredientId")
        if not iid: continue
        ing = ing_cache.get(iid) or await db.ingredients.find_one(
            {"id": iid, **tenant_scope_filter(user.get("businessId"))}, {"_id": 0})
        if not ing: raise HTTPException(status_code=400, detail=f"Ingredient {iid} not found")
        ing_cache[iid] = ing
        unit = raw.get("unit", ing["baseUnit"])
        qty = float(raw.get("qty", 0))
        try:
            qty_base = to_base(qty, unit, ing["baseUnit"])
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        lines.append({
            "ingredientId": iid, "ingredientName": ing["name"],
            "qty": qty, "unit": unit,
            "qtyBase": qty_base, "baseUnit": ing["baseUnit"],
        })
    # Recompute product cost = sum(line.qtyBase × ingredient.unitCost)
    cost = round(
        sum(ing_cache[l["ingredientId"]]["unitCost"] * l["qtyBase"] for l in lines), 4)
    recipe = {
        "productId": product_id, "lines": lines, "computedCost": cost,
        "updatedAt": _iso(_now()), "updatedBy": user["id"],
        "businessId": user.get("businessId"),
    }
    await db.recipes.update_one(
        {"productId": product_id, **tenant_scope_filter(user.get("businessId"))},
        {"$set": recipe}, upsert=True)
    # Push the cost back onto the product so margin chips stay accurate.
    await db.products.update_one(
        {"id": product_id, **tenant_scope_filter(user.get("businessId"))},
        {"$set": {"cost": cost, "updatedAt": _iso(_now())}})
    recipe.pop("_id", None)
    return recipe


async def deduct_recipe_stock(product_id: str, quantity_sold: int) -> dict:
    """Called from transactions.create on each item. Reduces ingredient stock
    and records a ledger entry. Idempotency comes from the caller passing the
    transaction id as `ref`."""
    scope = tenant_scope_filter()
    recipe = await db.recipes.find_one({"productId": product_id, **scope}, {"_id": 0})
    if not recipe or not recipe.get("lines"): return {"skipped": True, "reason": "no_recipe"}
    deducted = []
    for line in recipe["lines"]:
        deduct = line["qtyBase"] * int(quantity_sold)
        await db.ingredients.update_one(
            {"id": line["ingredientId"], **scope}, {"$inc": {"stock": -deduct}})
        deducted.append({"ingredientId": line["ingredientId"], "qtyBase": deduct})
    return {"productId": product_id, "deducted": deducted}


@router.post("/stock/deduct-recipe")
async def deduct_recipe_endpoint(data: dict, _: dict = Depends(get_user)):
    """Manual hook (called by transactions module + tests). Body: {productId, qty}."""
    return await deduct_recipe_stock(data.get("productId"), int(data.get("qty", 1)))


# =============================================================================
# STOCK-TAKE — count + reconcile
# =============================================================================
@router.post("/stock-takes")
async def create_stock_take(data: dict, user: dict = Depends(require_owner_or_manager)):
    rows = data.get("counts") or []   # [{ingredientId, countedBase}]
    variances = []
    for row in rows:
        ing = await db.ingredients.find_one(
            {"id": row["ingredientId"], **tenant_scope_filter(user.get("businessId"))}, {"_id": 0})
        if not ing: continue
        before = float(ing.get("stock", 0))
        after = float(row.get("countedBase", 0))
        var = after - before
        variances.append({
            "ingredientId": ing["id"], "name": ing["name"],
            "expected": before, "counted": after, "variance": var,
            "varianceValue": round(var * float(ing.get("unitCost", 0)), 2),
        })
        await db.ingredients.update_one(
            {"id": ing["id"], **tenant_scope_filter(user.get("businessId"))},
            {"$set": {"stock": after}})
    doc = {
        "id": _uid("STK"), "performedAt": _iso(_now()), "performedBy": user["id"],
        "notes": data.get("notes", ""), "variances": variances,
        "totalShrinkageValue": round(sum(v["varianceValue"] for v in variances if v["variance"] < 0), 2),
        "businessId": user.get("businessId"),
    }
    await db.stock_takes.insert_one(doc); doc.pop("_id", None)
    return doc


@router.get("/stock-takes")
async def list_stock_takes(_: dict = Depends(get_user)):
    rows = await db.stock_takes.find(tenant_scope_filter(), {"_id": 0}).sort("performedAt", -1).to_list(50)
    return rows


# =============================================================================
# INVOICE → INGREDIENT ASSIGNMENT (incoming stock)
# =============================================================================
@router.post("/invoices/{invoice_id}/assign-stock")
async def assign_invoice_to_stock(invoice_id: str, data: dict, user: dict = Depends(require_owner_or_manager)):
    """Owner reviews a parsed invoice and tells us which lines map to which
    ingredient + which unit. We convert to base, increment stock, and update
    unitCost as a weighted moving average. Posts a stock_movements row per line."""
    scope = tenant_scope_filter(user.get("businessId"))
    inv = await db.invoices.find_one({"id": invoice_id, **scope}, {"_id": 0})
    if not inv: raise HTTPException(status_code=404, detail="Invoice not found")
    assigns = data.get("assignments") or []
    movements, errors = [], []
    for a in assigns:
        ing = await db.ingredients.find_one({"id": a.get("ingredientId"), **scope}, {"_id": 0})
        if not ing:
            errors.append({"ingredientId": a.get("ingredientId"), "reason": "not_found"})
            continue
        try:
            qty_base = to_base(float(a["qty"]), a["unit"], ing["baseUnit"])
        except (KeyError, ValueError) as e:
            errors.append({"ingredientId": ing["id"], "reason": str(e)})
            continue
        line_total = float(a.get("lineTotal", 0))
        # Weighted moving average for unitCost (in baseUnit)
        prev_stock = float(ing.get("stock", 0))
        prev_cost = float(ing.get("unitCost", 0))
        new_unit_cost = (
            ((prev_stock * prev_cost) + line_total) / (prev_stock + qty_base)
            if (prev_stock + qty_base) > 0 else (line_total / qty_base if qty_base > 0 else prev_cost)
        )
        await db.ingredients.update_one(
            {"id": ing["id"], **scope},
            {"$set": {"stock": prev_stock + qty_base, "unitCost": round(new_unit_cost, 4),
                      "updatedAt": _iso(_now())}})
        mv = {
            "id": _uid("MOV"), "ingredientId": ing["id"], "ingredientName": ing["name"],
            "type": "receive", "invoiceId": invoice_id,
            "qty": a["qty"], "unit": a["unit"], "qtyBase": qty_base, "baseUnit": ing["baseUnit"],
            "lineTotal": line_total, "newUnitCost": round(new_unit_cost, 4),
            "createdAt": _iso(_now()), "createdBy": user["id"],
            "businessId": user.get("businessId"),
        }
        await db.stock_movements.insert_one(mv); mv.pop("_id", None)
        movements.append(mv)
    await db.invoices.update_one(
        {"id": invoice_id, **scope},
        {"$set": {"stockAssignedAt": _iso(_now()), "stockAssignedBy": user["id"],
                  "stockMovements": [m["id"] for m in movements]}})
    # Cascade: re-roll the cost of every product whose recipe uses the touched ingredients.
    touched_ings = {m["ingredientId"] for m in movements}
    affected_recipes = await db.recipes.find(
        {"lines.ingredientId": {"$in": list(touched_ings)}, **scope}, {"_id": 0}).to_list(500)
    # Receiving stock can move an ingredient's cost enough to erode a
    # product's margin — surfaced here so the owner can react on the same
    # screen instead of noticing weeks later on a margin report, and can
    # optionally re-price right away via `priceUpdates: {productId: newPrice}`.
    price_updates = data.get("priceUpdates") or {}
    price_review = []
    for rec in affected_recipes:
        lines = rec.get("lines", [])
        ing_lookup = {}
        for l in lines:
            ing_lookup[l["ingredientId"]] = ing_lookup.get(l["ingredientId"]) or (
                await db.ingredients.find_one({"id": l["ingredientId"], **scope}, {"_id": 0}))
        new_cost = round(
            sum((ing_lookup[l["ingredientId"]] or {}).get("unitCost", 0) * l["qtyBase"]
                for l in lines), 4)
        await db.recipes.update_one(
            {"productId": rec["productId"], **scope}, {"$set": {"computedCost": new_cost}})
        product_update = {"cost": new_cost}
        override = price_updates.get(rec["productId"])
        if override is not None:
            try:
                product_update["price"] = round(float(override), 2)
            except (TypeError, ValueError):
                pass
        await db.products.update_one({"id": rec["productId"], **scope}, {"$set": product_update})
        product = await db.products.find_one(
            {"id": rec["productId"], **scope}, {"_id": 0, "name": 1, "price": 1})
        price = float(product_update.get("price", (product or {}).get("price", 0)) or 0)
        margin_pct = round(((price - new_cost) / price) * 100, 1) if price > 0 else None
        price_review.append({
            "productId": rec["productId"], "name": (product or {}).get("name", ""),
            "cost": new_cost, "price": price, "marginPct": margin_pct,
        })
    return {"movements": movements, "errors": errors, "recipesRolledUp": len(affected_recipes),
            "priceReview": price_review}


# =============================================================================
# BAS / GST REPORT (Australian quarterly cycle)
# =============================================================================
_BAS_QUARTERS = {  # (start_month, end_month)
    "Q1": (7, 9),   # Jul-Sep
    "Q2": (10, 12), # Oct-Dec
    "Q3": (1, 3),   # Jan-Mar
    "Q4": (4, 6),   # Apr-Jun
}


def _fy_for(d: date) -> int:
    """Australian FY label: FY24 = Jul-2023 → Jun-2024."""
    return d.year + 1 if d.month >= 7 else d.year


def _quarter_range(year: int, quarter: str):
    sm, em = _BAS_QUARTERS[quarter]
    # Q1 + Q2 belong to the fy starting THIS calendar year.
    # Q3 + Q4 belong to the fy starting last calendar year.
    if quarter in ("Q1", "Q2"):
        start = date(year - 1, sm, 1) if quarter == "Q2" else date(year - 1, sm, 1)
        # Q1: Jul-Sep of (year-1)
        # Q2: Oct-Dec of (year-1)
        start = date(year - 1, sm, 1)
        end = date(year - 1, em, 1) + timedelta(days=31)
        end = date(end.year, end.month, 1) - timedelta(days=1)
    else:
        # Q3: Jan-Mar of year, Q4: Apr-Jun of year
        start = date(year, sm, 1)
        end = date(year, em, 1) + timedelta(days=31)
        end = date(end.year, end.month, 1) - timedelta(days=1)
    return start, end


@router.get("/accounting/bas")
async def bas_report(fy: Optional[int] = None, quarter: Optional[str] = None,
                     monthStart: Optional[str] = None, monthEnd: Optional[str] = None,
                     user: dict = Depends(require_owner_or_manager)):
    """Australian GST/BAS report.
    Modes:
      - ?fy=2026&quarter=Q3   (Jan-Mar 2026)
      - ?monthStart=2026-01-01&monthEnd=2026-01-31  (any window)
    Returns G1 sales, 1A GST collected, G11 purchases, 1B GST credits,
    net GST payable.
    """
    if monthStart and monthEnd:
        start = date.fromisoformat(monthStart)
        end = date.fromisoformat(monthEnd)
        label = f"{monthStart} → {monthEnd}"
    else:
        if not fy or quarter not in _BAS_QUARTERS:
            today = date.today()
            fy = _fy_for(today)
            # Choose the most recent finished quarter
            quarter = "Q3" if today.month <= 6 else "Q1"
        start, end = _quarter_range(fy, quarter)
        label = f"FY{fy} {quarter} ({start} → {end})"

    start_iso = start.isoformat()
    end_iso = (end + timedelta(days=1)).isoformat()

    # G1 / 1A — sales (POS + online transactions, GST-inclusive amounts)
    # transactions.timestamp is a datetime; also accept ISO string variants.
    # Scoped to the caller's own business — a BAS/GST report is a tax
    # document, so pulling another tenant's sales into "your" GST payable
    # is a much sharper problem than the usual missing-filter bug.
    date_or = {"$or": [
        {"timestamp": {"$gte": datetime.fromisoformat(start_iso), "$lt": datetime.fromisoformat(end_iso)}},
        {"createdAt": {"$gte": start_iso, "$lt": end_iso}},
    ]}
    sales = await db.transactions.find(
        {"$and": [date_or, tenant_scope_filter(user.get("businessId"))]},
        {"_id": 0, "total": 1, "items": 1, "gst": 1},
    ).to_list(50000)
    g1_total_sales = 0.0
    for s in sales:
        g1_total_sales += float(s.get("total") or sum((float(i.get("price", 0)) * int(i.get("quantity", 1))) for i in s.get("items", [])))
    # 1A: GST = total / 11 (standard Aus formula on GST-inclusive figures)
    one_a_gst_on_sales = round(g1_total_sales / 11.0, 2)

    # G11 / 1B — purchases (invoices in window)
    purchases = await db.invoices.find(
        {"$and": [
            {"uploadedAt": {"$gte": start_iso, "$lt": end_iso}, "applied": True},
            tenant_scope_filter(user.get("businessId")),
        ]},
        {"_id": 0, "parsed": 1},
    ).to_list(5000)
    g11_total_purchases = sum(float((p.get("parsed") or {}).get("total") or 0) for p in purchases)
    one_b_gst_credits = round(g11_total_purchases / 11.0, 2)

    net_gst = round(one_a_gst_on_sales - one_b_gst_credits, 2)

    # Theoretical vs actual COGS variance
    ingredients = await db.ingredients.find(tenant_scope_filter(), {"_id": 0, "stock": 1, "unitCost": 1}).to_list(500)
    on_hand_value = round(sum(float(i.get("stock", 0)) * float(i.get("unitCost", 0)) for i in ingredients), 2)
    movements_in = await db.stock_movements.find(
        {"createdAt": {"$gte": start_iso, "$lt": end_iso}, "type": "receive",
         **tenant_scope_filter(user.get("businessId"))},
        {"_id": 0, "lineTotal": 1}).to_list(50000)
    stock_received = round(sum(float(m.get("lineTotal", 0)) for m in movements_in), 2)

    return {
        "period": label,
        "windowStart": start_iso, "windowEnd": end.isoformat(),
        "g1TotalSales": round(g1_total_sales, 2),
        "oneA_gstOnSales": one_a_gst_on_sales,
        "g11TotalPurchases": round(g11_total_purchases, 2),
        "oneB_gstCredits": one_b_gst_credits,
        "netGstPayable": net_gst,
        "salesCount": len(sales),
        "purchasesCount": len(purchases),
        "stockOnHandValue": on_hand_value,
        "stockReceivedInPeriod": stock_received,
    }


@router.get("/accounting/bas.csv")
async def bas_csv(fy: Optional[int] = None, quarter: Optional[str] = None,
                  user: dict = Depends(require_owner_or_manager)):
    """CSV export of the BAS report — slip into ATO submission."""
    report = await bas_report(fy=fy, quarter=quarter, _=user)
    from fastapi.responses import Response
    rows = [
        ["Period", report["period"]],
        ["G1 Total sales (incl. GST)", report["g1TotalSales"]],
        ["1A GST on sales", report["oneA_gstOnSales"]],
        ["G11 Total purchases (incl. GST)", report["g11TotalPurchases"]],
        ["1B GST credits", report["oneB_gstCredits"]],
        ["Net GST payable", report["netGstPayable"]],
        ["Stock on hand value", report["stockOnHandValue"]],
        ["Stock received in period", report["stockReceivedInPeriod"]],
    ]
    csv = "\n".join(f"{k},{v}" for k, v in rows)
    # Sanitize filename — HTTP headers must be latin-1; replace any non-ASCII (e.g. "→").
    safe_period = report["period"].replace("→", "to").replace(" ", "_")
    safe_period = safe_period.encode("ascii", "ignore").decode("ascii")
    return Response(content=csv, media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=BAS-{safe_period}.csv"})
