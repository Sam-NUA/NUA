"""
Seeder — Alcoholic categories & products.

Idempotent: runs once, second run is a no-op.
Auto-links Measured Stock (StockUnit + SellVariant) for anything that's
poured, so the beverage-margin math is real from day one.

Called at server startup (see server.py) and also exposed via
POST /api/settings/seed-alcohol for manual re-runs.
"""
from __future__ import annotations
from typing import Any, Dict, List
from datetime import datetime, timezone
from database import db
from services.entity_service import stamped_insert
from middleware.actor_context import tenant_scope_filter, get_actor_context, _actor_ctx
import uuid


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Category tree ────────────────────────────────────────────────────────
# `sortOrder` starts at 100 so alcohol slots after the SEED_CATEGORIES (0-4)
# without conflicting with them.
CATEGORIES: List[Dict[str, Any]] = [
    # Existing food kept intact — these are the alcoholic + non-alcoholic drink families
    {"name": "Beer",              "group": "Alcohol",      "icon": "Beer",       "color": "#f59e0b", "sortOrder": 100, "prepTime": 2},
    {"name": "Wine — Red",        "group": "Alcohol",      "icon": "Wine",       "color": "#7f1d1d", "sortOrder": 101, "prepTime": 2},
    {"name": "Wine — White",      "group": "Alcohol",      "icon": "Wine",       "color": "#d4d4aa", "sortOrder": 102, "prepTime": 2},
    {"name": "Wine — Sparkling",  "group": "Alcohol",      "icon": "Wine",       "color": "#fef3c7", "sortOrder": 103, "prepTime": 2},
    {"name": "Wine — Rosé",       "group": "Alcohol",      "icon": "Wine",       "color": "#fbcfe8", "sortOrder": 104, "prepTime": 2},
    {"name": "Cocktails",         "group": "Alcohol",      "icon": "GlassWater", "color": "#ec4899", "sortOrder": 105, "prepTime": 6},
    {"name": "Spirits — Whisky",  "group": "Alcohol",      "icon": "GlassWater", "color": "#a16207", "sortOrder": 106, "prepTime": 2},
    {"name": "Spirits — Gin",     "group": "Alcohol",      "icon": "GlassWater", "color": "#0ea5e9", "sortOrder": 107, "prepTime": 2},
    {"name": "Spirits — Vodka",   "group": "Alcohol",      "icon": "GlassWater", "color": "#e5e7eb", "sortOrder": 108, "prepTime": 2},
    {"name": "Spirits — Rum",     "group": "Alcohol",      "icon": "GlassWater", "color": "#78350f", "sortOrder": 109, "prepTime": 2},
    {"name": "Spirits — Tequila", "group": "Alcohol",      "icon": "GlassWater", "color": "#84cc16", "sortOrder": 110, "prepTime": 2},
    {"name": "Liqueurs",          "group": "Alcohol",      "icon": "GlassWater", "color": "#a855f7", "sortOrder": 111, "prepTime": 2},
    {"name": "Non-Alcoholic",     "group": "Drinks",       "icon": "GlassWater", "color": "#22c55e", "sortOrder": 112, "prepTime": 2},
    {"name": "Coffee & Tea",      "group": "Drinks",       "icon": "Coffee",     "color": "#78350f", "sortOrder": 113, "prepTime": 4},
]

# ─── Products ─────────────────────────────────────────────────────────────
# Each entry:  (categoryName, productName, price, taxRate, measuredStock?)
# `measured` dict — if present, seed a StockUnit + SellVariant:
#   { bottle: {uom, totalMeasure, cost}, pour: {uom, amount, label} }
PRODUCTS: List[Dict[str, Any]] = [
    # Beer
    {"cat": "Beer", "name": "Craft Lager (Draft)", "price": 9.5, "measured": {
        "bottle": {"uom": "l", "totalMeasure": 50, "cost": 220},
        "pour":   {"uom": "ml", "amount": 425, "label": "Schooner 425ml"},
    }},
    {"cat": "Beer", "name": "IPA (Draft)", "price": 10.5, "measured": {
        "bottle": {"uom": "l", "totalMeasure": 50, "cost": 260},
        "pour":   {"uom": "ml", "amount": 425, "label": "Schooner 425ml"},
    }},
    {"cat": "Beer", "name": "Bottled Pale Ale 330ml", "price": 8.5},
    {"cat": "Beer", "name": "Cider (Draft)", "price": 9.5, "measured": {
        "bottle": {"uom": "l", "totalMeasure": 20, "cost": 130},
        "pour":   {"uom": "ml", "amount": 425, "label": "Schooner 425ml"},
    }},

    # Wine — Red
    {"cat": "Wine — Red", "name": "House Shiraz — Glass", "price": 12, "measured": {
        "bottle": {"uom": "ml", "totalMeasure": 750, "cost": 22},
        "pour":   {"uom": "ml", "amount": 150, "label": "Standard glass 150ml"},
    }},
    {"cat": "Wine — Red", "name": "Cabernet Sauvignon — Glass", "price": 14, "measured": {
        "bottle": {"uom": "ml", "totalMeasure": 750, "cost": 28},
        "pour":   {"uom": "ml", "amount": 150, "label": "Standard glass 150ml"},
    }},
    {"cat": "Wine — Red", "name": "Pinot Noir — Bottle", "price": 68},

    # Wine — White
    {"cat": "Wine — White", "name": "Sauvignon Blanc — Glass", "price": 12, "measured": {
        "bottle": {"uom": "ml", "totalMeasure": 750, "cost": 20},
        "pour":   {"uom": "ml", "amount": 150, "label": "Standard glass 150ml"},
    }},
    {"cat": "Wine — White", "name": "Chardonnay — Glass", "price": 13, "measured": {
        "bottle": {"uom": "ml", "totalMeasure": 750, "cost": 24},
        "pour":   {"uom": "ml", "amount": 150, "label": "Standard glass 150ml"},
    }},

    # Wine — Sparkling
    {"cat": "Wine — Sparkling", "name": "Prosecco — Glass", "price": 12, "measured": {
        "bottle": {"uom": "ml", "totalMeasure": 750, "cost": 18},
        "pour":   {"uom": "ml", "amount": 120, "label": "Flute 120ml"},
    }},
    {"cat": "Wine — Sparkling", "name": "Champagne — Bottle", "price": 120},

    # Wine — Rosé
    {"cat": "Wine — Rosé", "name": "Rosé — Glass", "price": 12, "measured": {
        "bottle": {"uom": "ml", "totalMeasure": 750, "cost": 20},
        "pour":   {"uom": "ml", "amount": 150, "label": "Standard glass 150ml"},
    }},

    # Cocktails (recipes not measured at ingredient level yet, price only)
    {"cat": "Cocktails", "name": "Espresso Martini", "price": 22},
    {"cat": "Cocktails", "name": "Negroni", "price": 20},
    {"cat": "Cocktails", "name": "Old Fashioned", "price": 22},
    {"cat": "Cocktails", "name": "Margarita", "price": 20},
    {"cat": "Cocktails", "name": "Aperol Spritz", "price": 18},
    {"cat": "Cocktails", "name": "Whisky Sour", "price": 20},
    {"cat": "Cocktails", "name": "Mojito", "price": 19},

    # Spirits — Whisky
    {"cat": "Spirits — Whisky", "name": "Scotch Single Malt — 30ml", "price": 16, "measured": {
        "bottle": {"uom": "ml", "totalMeasure": 700, "cost": 95},
        "pour":   {"uom": "ml", "amount": 30, "label": "Standard 30ml"},
    }},
    {"cat": "Spirits — Whisky", "name": "Bourbon — 30ml", "price": 12, "measured": {
        "bottle": {"uom": "ml", "totalMeasure": 700, "cost": 55},
        "pour":   {"uom": "ml", "amount": 30, "label": "Standard 30ml"},
    }},

    # Spirits — Gin
    {"cat": "Spirits — Gin", "name": "London Dry Gin — 30ml", "price": 11, "measured": {
        "bottle": {"uom": "ml", "totalMeasure": 700, "cost": 45},
        "pour":   {"uom": "ml", "amount": 30, "label": "Standard 30ml"},
    }},
    {"cat": "Spirits — Gin", "name": "Botanical Gin — 30ml", "price": 14, "measured": {
        "bottle": {"uom": "ml", "totalMeasure": 700, "cost": 65},
        "pour":   {"uom": "ml", "amount": 30, "label": "Standard 30ml"},
    }},

    # Spirits — Vodka
    {"cat": "Spirits — Vodka", "name": "Premium Vodka — 30ml", "price": 11, "measured": {
        "bottle": {"uom": "ml", "totalMeasure": 700, "cost": 42},
        "pour":   {"uom": "ml", "amount": 30, "label": "Standard 30ml"},
    }},

    # Spirits — Rum
    {"cat": "Spirits — Rum", "name": "Aged Rum — 30ml", "price": 12, "measured": {
        "bottle": {"uom": "ml", "totalMeasure": 700, "cost": 50},
        "pour":   {"uom": "ml", "amount": 30, "label": "Standard 30ml"},
    }},

    # Spirits — Tequila
    {"cat": "Spirits — Tequila", "name": "Reposado Tequila — 30ml", "price": 13, "measured": {
        "bottle": {"uom": "ml", "totalMeasure": 700, "cost": 55},
        "pour":   {"uom": "ml", "amount": 30, "label": "Standard 30ml"},
    }},

    # Liqueurs
    {"cat": "Liqueurs", "name": "Amaretto — 30ml", "price": 10, "measured": {
        "bottle": {"uom": "ml", "totalMeasure": 700, "cost": 38},
        "pour":   {"uom": "ml", "amount": 30, "label": "Standard 30ml"},
    }},
    {"cat": "Liqueurs", "name": "Baileys — 30ml", "price": 10, "measured": {
        "bottle": {"uom": "ml", "totalMeasure": 700, "cost": 32},
        "pour":   {"uom": "ml", "amount": 30, "label": "Standard 30ml"},
    }},

    # Non-Alcoholic
    {"cat": "Non-Alcoholic", "name": "Sparkling Water 500ml", "price": 5},
    {"cat": "Non-Alcoholic", "name": "Still Water 500ml", "price": 4},
    {"cat": "Non-Alcoholic", "name": "Soft Drink 330ml", "price": 5.5},
    {"cat": "Non-Alcoholic", "name": "Fresh Juice", "price": 8},
    {"cat": "Non-Alcoholic", "name": "Iced Tea", "price": 6},
    {"cat": "Non-Alcoholic", "name": "Kombucha", "price": 7},

    # Coffee & Tea
    {"cat": "Coffee & Tea", "name": "Flat White", "price": 5.5},
    {"cat": "Coffee & Tea", "name": "Latte", "price": 5.5},
    {"cat": "Coffee & Tea", "name": "Long Black", "price": 5.0},
    {"cat": "Coffee & Tea", "name": "Cappuccino", "price": 5.5},
    {"cat": "Coffee & Tea", "name": "Espresso", "price": 4.5},
    {"cat": "Coffee & Tea", "name": "Pot of Tea", "price": 6},
    {"cat": "Coffee & Tea", "name": "Chai Latte", "price": 6},
]


async def _upsert_category(cat: Dict[str, Any]) -> Dict[str, Any]:
    existing = await db.categories.find_one({"name": cat["name"], **tenant_scope_filter()}, {"_id": 0})
    if existing:
        # Repair: back-fill fields the initial seeder omitted so this category
        # renders correctly on the POS + Categories admin page.
        patch: Dict[str, Any] = {}
        if existing.get("active") is None:
            patch["active"] = True
        if existing.get("sortOrder") is None:
            patch["sortOrder"] = cat.get("sortOrder", 99)
        if not existing.get("channels"):
            patch["channels"] = ["dine-in", "pickup", "delivery"]
        if existing.get("prepTime") is None:
            patch["prepTime"] = cat.get("prepTime", 4)
        # Normalise legacy lowercase icon names (beer/wine/glass/…) to the
        # PascalCase keys the frontend icon map exposes.
        if existing.get("icon") in {"beer","wine","glass","cup-soda","coffee","martini"}:
            patch["icon"] = cat["icon"]
        if patch:
            await db.categories.update_one({"id": existing["id"]}, {"$set": patch})
            existing.update(patch)
        return existing
    doc = {
        "id": str(uuid.uuid4()),
        "name": cat["name"],
        "group": cat.get("group"),
        "icon": cat.get("icon"),
        "color": cat.get("color"),
        "active": True,
        "sortOrder": cat.get("sortOrder", 99),
        "prepTime": cat.get("prepTime", 4),
        "channels": ["dine-in", "pickup", "delivery"],
        "isDemo": True,
    }
    return await stamped_insert("categories", doc, entity_type="category")


async def _upsert_product(name: str, category: Dict[str, Any], price: float,
                            measured: Dict[str, Any] | None = None) -> Dict[str, Any]:
    existing = await db.products.find_one({"name": name, **tenant_scope_filter()}, {"_id": 0})
    if existing:
        # Repair: back-fill fields required by the Product Pydantic model so
        # GET /products doesn't 500 on legacy alcohol rows.
        patch: Dict[str, Any] = {}
        if existing.get("cost") is None:
            # Estimate cost from measured stock (pour cost) or 35% of price
            if measured:
                bottle_cost = float(measured["bottle"]["cost"])
                pour_share = float(measured["pour"]["amount"]) / float(measured["bottle"]["totalMeasure"])
                patch["cost"] = round(bottle_cost * pour_share, 2)
            else:
                patch["cost"] = round(price * 0.35, 2)
        if existing.get("sku") is None:
            patch["sku"] = f"ALC-{str(existing.get('id',''))[:8].upper()}"
        if existing.get("image") is None:
            patch["image"] = ""
        if existing.get("active") is None:
            patch["active"] = True
        if existing.get("eightySixed") is None:
            patch["eightySixed"] = False
        if patch:
            await db.products.update_one({"id": existing["id"]}, {"$set": patch})
            existing.update(patch)
        return existing
    # New product: seed cost from measured math (pour cost) or 35% of price
    if measured:
        bottle_cost = float(measured["bottle"]["cost"])
        pour_share = float(measured["pour"]["amount"]) / float(measured["bottle"]["totalMeasure"])
        est_cost = round(bottle_cost * pour_share, 2)
    else:
        est_cost = round(price * 0.35, 2)
    prod_id = str(uuid.uuid4())
    prod = {
        "id": prod_id,
        "name": name,
        "category": category["name"],
        "categoryId": category["id"],
        "price": price,
        "cost": est_cost,
        "stock": 0 if measured else 20,   # measured items don't use scalar stock
        "sku": f"ALC-{prod_id[:8].upper()}",
        "image": "",
        "parLevel": 3,
        "taxRate": 0.10,
        "gstRate": 10.0,
        "active": True,
        "eightySixed": False,
        "isMeasured": bool(measured),
        "isDemo": True,
    }
    saved = await stamped_insert("products", prod, entity_type="product")

    if measured:
        # Seed a stock unit (bought container) + sell variant (poured serve)
        su = await stamped_insert("stock_units", {
            "id": str(uuid.uuid4()),
            "productId": saved["id"],
            "uom": measured["bottle"]["uom"],
            "totalMeasure": measured["bottle"]["totalMeasure"],
            "costPerUnit": measured["bottle"]["cost"],
            "label": f"{measured['bottle']['totalMeasure']}{measured['bottle']['uom']} bottle",
            "isDemo": True,
        }, entity_type="stock_unit")
        await stamped_insert("sell_variants", {
            "id": str(uuid.uuid4()),
            "productId": saved["id"],
            "stockUnitId": su["id"],
            "uom": measured["pour"]["uom"],
            "deductAmount": measured["pour"]["amount"],
            "isDemo": True,
            "label": measured["pour"]["label"],
        }, entity_type="sell_variant")
    return saved


async def _repair_orphan_products() -> Dict[str, int]:
    """Back-fill fields required by the Product Pydantic model on ANY product
    (including legacy/test docs). Prevents GET /api/products from 500-ing when
    a document is missing `category`, `cost`, `sku`, or `image`."""
    fixed = 0
    orphans = await db.products.find({
        **tenant_scope_filter(),
        "$or": [
            {"category": {"$exists": False}}, {"category": None}, {"category": ""},
            {"cost": {"$exists": False}}, {"cost": None},
            {"sku": {"$exists": False}}, {"sku": None},
            {"image": {"$exists": False}}, {"image": None},
        ]
    }, {"_id": 0}).to_list(2000)
    for p in orphans:
        patch: Dict[str, Any] = {}
        if not p.get("category"):
            patch["category"] = "Uncategorized"
        if p.get("cost") is None:
            patch["cost"] = round(float(p.get("price", 0) or 0) * 0.35, 2)
        if p.get("sku") is None:
            patch["sku"] = f"LEG-{str(p.get('id',''))[:8].upper()}"
        if p.get("image") is None:
            patch["image"] = ""
        if patch:
            await db.products.update_one({"id": p["id"]}, {"$set": patch})
            fixed += 1
    return {"orphansFixed": fixed}


async def _repair_orphan_categories() -> Dict[str, int]:
    """Ensure every category has `active` (True) + `sortOrder` so it renders
    on the Categories admin page and appears on the POS. Non-destructive."""
    fixed = 0
    orphans = await db.categories.find({
        **tenant_scope_filter(),
        "$or": [
            {"active": {"$exists": False}},
            {"sortOrder": {"$exists": False}},
        ]
    }, {"_id": 0}).to_list(500)
    for c in orphans:
        patch: Dict[str, Any] = {}
        if c.get("active") is None:
            patch["active"] = True
        if c.get("sortOrder") is None:
            patch["sortOrder"] = 99
        if c.get("prepTime") is None:
            patch["prepTime"] = 4
        if not c.get("channels"):
            patch["channels"] = ["dine-in", "pickup", "delivery"]
        if patch:
            await db.categories.update_one({"id": c["id"]}, {"$set": patch})
            fixed += 1
    return {"orphansFixed": fixed}


async def seed_alcohol_catalog(business_id: str | None = None) -> Dict[str, Any]:
    business_id = business_id or get_actor_context().get("businessId")
    if not business_id:
        raise ValueError("Explicit business required for catalog seeding")
    token = _actor_ctx.set({**get_actor_context(), "businessId": business_id})
    try:
        return await _seed_alcohol_catalog()
    finally:
        _actor_ctx.reset(token)


async def _seed_alcohol_catalog() -> Dict[str, Any]:
    """Idempotent. Reports how many rows were newly created."""
    stats = {"categoriesInserted": 0, "productsInserted": 0, "stockUnitsInserted": 0}
    cat_map: Dict[str, Dict[str, Any]] = {}
    for cat in CATEGORIES:
        before = await db.categories.find_one({"name": cat["name"], **tenant_scope_filter()}, {"_id": 0})
        got = await _upsert_category(cat)
        cat_map[cat["name"]] = got
        if not before:
            stats["categoriesInserted"] += 1

    for p in PRODUCTS:
        cat = cat_map.get(p["cat"])
        if not cat:
            continue
        existing = await db.products.find_one({"name": p["name"], **tenant_scope_filter()}, {"_id": 0})
        await _upsert_product(p["name"], cat, p["price"], p.get("measured"))
        if not existing:
            stats["productsInserted"] += 1
            if p.get("measured"):
                stats["stockUnitsInserted"] += 1

    # One-shot repair of legacy/orphan docs so /products list endpoint
    # doesn't blow up on Pydantic validation.
    cat_fix = await _repair_orphan_categories()
    prod_fix = await _repair_orphan_products()
    stats["categoriesRepaired"] = cat_fix["orphansFixed"]
    stats["productsRepaired"] = prod_fix["orphansFixed"]

    return {"seededAt": _now(), **stats}
