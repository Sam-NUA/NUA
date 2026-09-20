from fastapi import APIRouter, HTTPException, Depends
from database import db
from datetime import datetime, timezone
import uuid
import logging
from deps import require_owner, require_owner_or_manager, require_permission, optional_user, get_user
from middleware.actor_context import tenant_scope_filter, tenant_owns_strict

logger = logging.getLogger(__name__)

router = APIRouter()

# ============ CATEGORIES ============
@router.get("/categories")
async def get_categories(user=Depends(optional_user)):
    business_id = user.get("businessId") if user else None
    cats = await db.categories.find(tenant_scope_filter(business_id), {"_id": 0}).to_list(200)
    if not cats and business_id:
        # Only auto-seed when there's a real, authenticated business to own
        # the new rows. Previously this seeded 5 fixed-id, no-businessId
        # categories for ANY caller whose scoped query came back empty —
        # including a genuinely anonymous one — so the first caller ever to
        # hit this (any business, or a guest) created shared rows that
        # every other business's tenant_scope_filter query would also
        # match, and that update_category's fail-open tenant_owns() would
        # let ANY business rename out from under every other business
        # sharing it. An anonymous caller with no business now just gets
        # an empty list instead of ever creating untagged data; each
        # business gets its own copy, scoped and id-namespaced to it.
        defaults = [
            {"id": f"cat-beverages-{business_id}", "name": "Beverages", "sortOrder": 0, "active": True, "icon": "Coffee", "color": "#8b5cf6"},
            {"id": f"cat-food-{business_id}", "name": "Food", "sortOrder": 1, "active": True, "icon": "UtensilsCrossed", "color": "#f97316"},
            {"id": f"cat-bakery-{business_id}", "name": "Bakery", "sortOrder": 2, "active": True, "icon": "Croissant", "color": "#ec4899"},
            {"id": f"cat-alcohol-{business_id}", "name": "Alcohol", "sortOrder": 3, "active": True, "icon": "Wine", "color": "#ef4444"},
            {"id": f"cat-desserts-{business_id}", "name": "Desserts", "sortOrder": 4, "active": True, "icon": "Cake", "color": "#f59e0b"},
        ]
        for d in defaults:
            d["businessId"] = business_id
            await db.categories.insert_one(d)
            d.pop("_id", None)
        return defaults
    return cats

@router.post("/categories")
async def create_category(data: dict, user: dict = Depends(require_owner_or_manager)):
    cat = {
        "id": f"cat-{str(uuid.uuid4())[:8]}",
        "businessId": user.get("businessId"),
        "name": data.get("name", ""), "sortOrder": data.get("sortOrder", 99),
        "active": data.get("active", True),
        "icon": data.get("icon", "Tag"),          # lucide-react icon name
        "color": data.get("color", "#6366f1"),    # tile accent
        # Online-ordering: how long this category takes to prep (mins) and which
        # channels it's available on.
        "prepTime": int(data.get("prepTime", 8)),
        "channels": data.get("channels", ["dine-in", "pickup", "delivery"]),
        # Menu organisation: nest under another category (drag-and-drop in the UI).
        "parentId": data.get("parentId") or None,
        # Reporting rollup: sales in this category display under the target
        # category's name in revenue reports. None = reports as itself.
        "reportsUnderId": data.get("reportsUnderId") or None,
    }
    await db.categories.insert_one(cat)
    cat.pop("_id", None)
    return cat


async def _would_create_cycle(cat_id: str, new_parent_id: str, field: str = "parentId") -> bool:
    """Walk the target's chain (parentId or reportsUnderId) looking for cat_id.
    Used to reject drag-drop nesting/reporting assignments that would loop."""
    seen = set()
    current_id = new_parent_id
    while current_id:
        if current_id == cat_id or current_id in seen:
            return True
        seen.add(current_id)
        node = await db.categories.find_one({"id": current_id}, {"_id": 0, field: 1})
        current_id = node.get(field) if node else None
    return False


@router.put("/categories/{cat_id}")
async def update_category(cat_id: str, data: dict, user: dict = Depends(require_owner_or_manager)):
    # tenant_owns_strict, not tenant_owns: get_categories' auto-seed now
    # stamps a real, per-business businessId on every category it creates
    # (release-closure pass — see that function's own docstring), so the
    # only way to reach an untagged category here is pre-fix legacy data.
    # Quarantined (refused, not auto-owned) until the migration resolves
    # it, rather than editable by whichever business asks first.
    existing = await db.categories.find_one({"$and": [{"id": cat_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "businessId": 1})
    if not existing or not tenant_owns_strict(existing.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Not found")
    allowed = {"name", "sortOrder", "active", "icon", "color", "prepTime", "channels", "parentId", "reportsUnderId"}
    update = {k: v for k, v in data.items() if k in allowed}
    if "prepTime" in update: update["prepTime"] = int(update["prepTime"] or 0)
    if update.get("parentId"):
        if update["parentId"] == cat_id:
            raise HTTPException(status_code=400, detail="A category can't be its own sub-category")
        if await _would_create_cycle(cat_id, update["parentId"], "parentId"):
            raise HTTPException(status_code=400, detail="That would nest a category under its own sub-category")
    if update.get("reportsUnderId"):
        if update["reportsUnderId"] == cat_id:
            raise HTTPException(status_code=400, detail="A category can't report under itself")
        if await _would_create_cycle(cat_id, update["reportsUnderId"], "reportsUnderId"):
            raise HTTPException(status_code=400, detail="That would create a reporting loop")
    result = await db.categories.find_one_and_update({"$and": [{"id": cat_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": update}, return_document=True)
    if not result:
        raise HTTPException(status_code=404, detail="Not found")
    result.pop("_id", None)
    return result


@router.post("/categories/{source_id}/merge/{target_id}")
async def merge_categories(source_id: str, target_id: str, user: dict = Depends(require_owner_or_manager)):
    """Drag-and-drop merge: every product in `source` moves to `target`
    (matched by categoryId, falling back to the legacy name string for rows
    that predate categoryId), any sub-categories or reporting-rollups that
    pointed at `source` are re-pointed to `target`, then `source` is deleted.

    Found during the Trust Release final readiness audit: this endpoint had
    no tenant check at all, and its products.update_many had no businessId
    filter — any owner/manager could re-categorize (and, via the delete
    below, silently disappear) every OTHER business's products sharing the
    same category name, not just their own."""
    if source_id == target_id:
        raise HTTPException(status_code=400, detail="Can't merge a category into itself")
    # tenant_owns_strict — same reasoning as update_category's own comment:
    # get_categories' auto-seed now stamps a real businessId, so an
    # untagged category here can only be pre-fix legacy data.
    business_id = user.get("businessId")
    source = await db.categories.find_one({"$and": [{"id": source_id}, tenant_scope_filter(business_id)]}, {"_id": 0})
    target = await db.categories.find_one({"$and": [{"id": target_id}, tenant_scope_filter(business_id)]}, {"_id": 0})
    if (not source or not tenant_owns_strict(source.get("businessId"), business_id)
            or not target or not tenant_owns_strict(target.get("businessId"), business_id)):
        raise HTTPException(status_code=404, detail="Category not found")

    result = await db.products.update_many(
        {"$and": [tenant_scope_filter(business_id), {"$or": [
            {"categoryId": source_id},
            {"categoryId": {"$in": [None, ""]}, "category": source["name"]},
        ]}]},
        {"$set": {"categoryId": target_id, "category": target["name"]}},
    )
    await db.categories.update_many(
        {"$and": [tenant_scope_filter(business_id), {"parentId": source_id}]}, {"$set": {"parentId": target_id}})
    await db.categories.update_many(
        {"$and": [tenant_scope_filter(business_id), {"reportsUnderId": source_id}]}, {"$set": {"reportsUnderId": target_id}})
    await db.categories.delete_one({"$and": [{"id": source_id}, tenant_scope_filter(business_id)]})
    return {
        "message": f"Merged '{source['name']}' into '{target['name']}'",
        "productsMoved": result.modified_count,
        "targetId": target_id,
    }


async def build_reporting_map() -> dict:
    """name -> the name its sales should be attributed to in revenue reports,
    following reportsUnderId chains. Cycle-safe; falls back to the category's
    own name if the chain is broken or missing."""
    cats = await db.categories.find(tenant_scope_filter(), {"_id": 0}).to_list(500)
    by_id = {c["id"]: c for c in cats}

    def resolve(cat: dict, seen: set) -> str:
        target_id = cat.get("reportsUnderId")
        if not target_id or target_id == cat["id"] or cat["id"] in seen:
            return cat["name"]
        target = by_id.get(target_id)
        if not target:
            return cat["name"]
        seen.add(cat["id"])
        return resolve(target, seen)

    return {c["name"]: resolve(c, set()) for c in cats}


@router.post("/categories/cleanup-legacy")
async def cleanup_legacy_categories(user: dict = Depends(require_owner)):
    """Owner one-click: removes ANY category that has zero products attached
    AND is not in the canonical seed-catalog set (Coffee/Burgers/Mains/
    Cakes & Slices/Pasta). Safe — products are unaffected."""
    canonical = {c["name"] for c in SEED_CATEGORIES}
    scope = tenant_scope_filter(user.get("businessId"))
    all_cats = await db.categories.find(scope, {"_id": 0}).to_list(200)
    candidates = [cat for cat in all_cats if cat["name"] not in canonical]
    # One aggregation for all candidate categories' product counts, instead
    # of one count_documents() per category.
    counts_by_category = {}
    if candidates:
        agg = await db.products.aggregate([
            {"$match": {"category": {"$in": [c["name"] for c in candidates]}, **scope}},
            {"$group": {"_id": "$category", "count": {"$sum": 1}}},
        ]).to_list(len(candidates))
        counts_by_category = {row["_id"]: row["count"] for row in agg}
    removed, kept = [], []
    for cat in candidates:
        product_count = counts_by_category.get(cat["name"], 0)
        if product_count == 0:
            await db.categories.delete_one({"id": cat["id"], **scope})
            removed.append(cat["name"])
        else:
            kept.append({"name": cat["name"], "productCount": product_count})
    return {"removed": removed, "keptWithProducts": kept}

@router.delete("/categories/{cat_id}")
async def delete_category(cat_id: str, user: dict = Depends(require_owner)):
    # tenant_owns_strict — same reasoning as update_category's own comment.
    existing = await db.categories.find_one({"$and": [{"id": cat_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "businessId": 1})
    if not existing or not tenant_owns_strict(existing.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Not found")
    await db.categories.delete_one({"$and": [{"id": cat_id}, tenant_scope_filter(user.get("businessId"))]})
    return {"message": "Category deleted"}


# ============ SEED CATALOG (60 products + 10 modifiers) ============
SEED_CATEGORIES = [
    {"id": "cat-coffee", "name": "Coffee", "sortOrder": 0, "active": True, "icon": "Coffee", "color": "#92400e", "prepTime": 4, "channels": ["dine-in", "pickup", "delivery"]},
    {"id": "cat-burgers", "name": "Burgers", "sortOrder": 1, "active": True, "icon": "Beef", "color": "#dc2626", "prepTime": 12, "channels": ["dine-in", "pickup", "delivery"]},
    {"id": "cat-mains", "name": "Mains", "sortOrder": 2, "active": True, "icon": "UtensilsCrossed", "color": "#16a34a", "prepTime": 18, "channels": ["dine-in", "pickup"]},
    {"id": "cat-cakes", "name": "Cakes & Slices", "sortOrder": 3, "active": True, "icon": "Cake", "color": "#db2777", "prepTime": 2, "channels": ["dine-in", "pickup", "delivery"]},
    {"id": "cat-pasta", "name": "Pasta", "sortOrder": 4, "active": True, "icon": "Soup", "color": "#ea580c", "prepTime": 14, "channels": ["dine-in", "pickup", "delivery"]},
]

SEED_PRODUCTS = [
    # === 20 COFFEES ===
    *[{"name": n, "category": "Coffee", "price": p, "cost": round(p*0.35, 2), "stock": 200,
       "image": img}
      for n, p, img in [
        ("Espresso", 4.50, "https://images.unsplash.com/photo-1510707577719-ae7c14805e3a?w=400"),
        ("Double Espresso", 5.00, "https://images.unsplash.com/photo-1510591509098-f4fdc6d0ff04?w=400"),
        ("Long Black", 4.80, "https://images.unsplash.com/photo-1497935586351-b67a49e012bf?w=400"),
        ("Americano", 4.60, "https://images.unsplash.com/photo-1551030173-122aabc4489c?w=400"),
        ("Flat White", 5.20, "https://images.unsplash.com/photo-1517256064527-09c73fc73e38?w=400"),
        ("Cappuccino", 5.20, "https://images.unsplash.com/photo-1572442388796-11668a67e53d?w=400"),
        ("Latte", 5.40, "https://images.unsplash.com/photo-1561882468-9110e03e0f78?w=400"),
        ("Mocha", 5.80, "https://images.unsplash.com/photo-1578314675229-c1f3a9b5dbe6?w=400"),
        ("Macchiato", 4.90, "https://images.unsplash.com/photo-1607619056574-7b8d3ee536b2?w=400"),
        ("Piccolo Latte", 4.80, "https://images.unsplash.com/photo-1599506539953-a48aafa3c197?w=400"),
        ("Cortado", 5.00, "https://images.unsplash.com/photo-1568649929103-28ffbefaca1e?w=400"),
        ("Affogato", 7.50, "https://images.unsplash.com/photo-1497636577773-f1231844b336?w=400"),
        ("Iced Latte", 6.00, "https://images.unsplash.com/photo-1517701604599-bb29b565090c?w=400"),
        ("Iced Long Black", 5.50, "https://images.unsplash.com/photo-1461023058943-07fcbe16d735?w=400"),
        ("Cold Brew", 6.50, "https://images.unsplash.com/photo-1517959105821-eaf2591984ca?w=400"),
        ("Nitro Cold Brew", 7.20, "https://images.unsplash.com/photo-1559496417-e7f25cb247f3?w=400"),
        ("Chai Latte", 5.40, "https://images.unsplash.com/photo-1571934811356-5cc061b6821f?w=400"),
        ("Matcha Latte", 6.20, "https://images.unsplash.com/photo-1545518514-ce8448f542b3?w=400"),
        ("Dirty Chai", 6.00, "https://images.unsplash.com/photo-1518882570151-d3f5337d3ade?w=400"),
        ("Hot Chocolate", 5.40, "https://images.unsplash.com/photo-1542990253-0d0f5be5f0ed?w=400"),
      ]],
    # === 10 BURGERS ===
    *[{"name": n, "category": "Burgers", "price": p, "cost": round(p*0.32, 2), "stock": 80,
       "image": img}
      for n, p, img in [
        ("Classic Cheeseburger", 16.50, "https://images.unsplash.com/photo-1568901346375-23c9450c58cd?w=400"),
        ("Double Bacon Burger", 19.50, "https://images.unsplash.com/photo-1572802419224-296b0aeee0d9?w=400"),
        ("BBQ Brisket Burger", 21.00, "https://images.unsplash.com/photo-1586190848861-99aa4a171e90?w=400"),
        ("Crispy Chicken Burger", 17.80, "https://images.unsplash.com/photo-1606755962773-d324e0a13086?w=400"),
        ("Mushroom Swiss Burger", 18.50, "https://images.unsplash.com/photo-1550317138-10000687a72b?w=400"),
        ("Vegan Beetroot Burger", 17.00, "https://images.unsplash.com/photo-1525059696034-4967a729002e?w=400"),
        ("Wagyu Burger", 26.00, "https://images.unsplash.com/photo-1551782450-a2132b4ba21d?w=400"),
        ("Lamb Burger", 19.80, "https://images.unsplash.com/photo-1561758033-d89a9ad46330?w=400"),
        ("Smash Burger", 15.50, "https://images.unsplash.com/photo-1572448862527-d3c904757de6?w=400"),
        ("Spicy Halloumi Burger", 18.00, "https://images.unsplash.com/photo-1571091718767-18b5b1457add?w=400"),
      ]],
    # === 10 MAINS ===
    *[{"name": n, "category": "Mains", "price": p, "cost": round(p*0.30, 2), "stock": 50,
       "image": img}
      for n, p, img in [
        ("Eye Fillet Steak 250g", 38.00, "https://images.unsplash.com/photo-1546964124-0cce460f38ef?w=400"),
        ("Atlantic Salmon", 32.50, "https://images.unsplash.com/photo-1467003909585-2f8a72700288?w=400"),
        ("Crispy Pork Belly", 28.00, "https://images.unsplash.com/photo-1432139509613-5c4255815697?w=400"),
        ("Roast Lamb Rump", 33.00, "https://images.unsplash.com/photo-1544025162-d76694265947?w=400"),
        ("Chicken Schnitzel", 24.50, "https://images.unsplash.com/photo-1599487488170-d11ec9c172f0?w=400"),
        ("Fish & Chips", 22.00, "https://images.unsplash.com/photo-1580217593608-61931cefc821?w=400"),
        ("Duck Confit", 34.00, "https://images.unsplash.com/photo-1547573854-74d2a71d0826?w=400"),
        ("Beef Brisket Plate", 29.50, "https://images.unsplash.com/photo-1529694157872-4e0c0f3b238b?w=400"),
        ("Vegetarian Buddha Bowl", 19.50, "https://images.unsplash.com/photo-1512621776951-a57141f2eefd?w=400"),
        ("Slow-Cooked Lamb Shank", 31.00, "https://images.unsplash.com/photo-1544025162-d76694265947?w=400"),
      ]],
    # === 10 CAKES & SLICES ===
    *[{"name": n, "category": "Cakes & Slices", "price": p, "cost": round(p*0.28, 2), "stock": 30,
       "image": img}
      for n, p, img in [
        ("Flourless Chocolate Cake", 8.50, "https://images.unsplash.com/photo-1606313564200-e75d5e30476c?w=400"),
        ("Carrot Cake Slice", 7.80, "https://images.unsplash.com/photo-1621303837174-89787a7d4729?w=400"),
        ("New York Cheesecake", 8.90, "https://images.unsplash.com/photo-1567171466295-4afa63d45416?w=400"),
        ("Red Velvet Slice", 7.50, "https://images.unsplash.com/photo-1586788680434-30d324b2d46f?w=400"),
        ("Lemon Tart", 7.80, "https://images.unsplash.com/photo-1519915028121-7d3463d20b13?w=400"),
        ("Vanilla Slice", 6.80, "https://images.unsplash.com/photo-1488477181946-6428a0291777?w=400"),
        ("Caramel Slice", 6.50, "https://images.unsplash.com/photo-1551404973-761c83cf8c11?w=400"),
        ("Tiramisu Slice", 8.20, "https://images.unsplash.com/photo-1571877227200-a0d98ea607e9?w=400"),
        ("Pavlova Slice", 7.20, "https://images.unsplash.com/photo-1551024506-0bccd828d307?w=400"),
        ("Pistachio Brownie", 6.90, "https://images.unsplash.com/photo-1606312619070-d48b4c652a52?w=400"),
      ]],
    # === 10 PASTA ===
    *[{"name": n, "category": "Pasta", "price": p, "cost": round(p*0.27, 2), "stock": 60,
       "image": img}
      for n, p, img in [
        ("Spaghetti Carbonara", 21.00, "https://images.unsplash.com/photo-1612874742237-6526221588e3?w=400"),
        ("Penne Arrabbiata", 18.50, "https://images.unsplash.com/photo-1551183053-bf91a1d81141?w=400"),
        ("Fettuccine Alfredo", 19.80, "https://images.unsplash.com/photo-1645112411341-6c4fd023714a?w=400"),
        ("Lasagna Bolognese", 22.50, "https://images.unsplash.com/photo-1619895092538-128f4d0a4e0f?w=400"),
        ("Pesto Linguine", 20.00, "https://images.unsplash.com/photo-1473093226795-af9932fe5856?w=400"),
        ("Mushroom Tagliatelle", 21.80, "https://images.unsplash.com/photo-1473093295043-cdd812d0e601?w=400"),
        ("Prawn Aglio e Olio", 24.50, "https://images.unsplash.com/photo-1563379926898-05f4575a45d8?w=400"),
        ("Ravioli Ricotta & Spinach", 22.00, "https://images.unsplash.com/photo-1587740908075-9e245311cf67?w=400"),
        ("Gnocchi Sorrentina", 21.50, "https://images.unsplash.com/photo-1633436374961-09b92742047b?w=400"),
        ("Truffle Mac & Cheese", 24.00, "https://images.unsplash.com/photo-1612464962427-ed4d8b8b6f87?w=400"),
      ]],
]

SEED_MODIFIERS = [
    {"name": "Milk Choice", "type": "list", "mandatory": True, "multiSelect": False, "maxSelections": 1,
     "assignedCategories": ["Coffee"],
     "options": [{"name": "Full Cream", "price": 0}, {"name": "Skim", "price": 0}, {"name": "Oat", "price": 0.80},
                 {"name": "Almond", "price": 0.80}, {"name": "Soy", "price": 0.60}, {"name": "Lactose Free", "price": 0.60}]},
    {"name": "Extra Shot", "type": "list", "mandatory": False, "multiSelect": True, "maxSelections": 3,
     "assignedCategories": ["Coffee"],
     "options": [{"name": "Single Shot", "price": 0.80}, {"name": "Double Shot", "price": 1.50}]},
    {"name": "Coffee Strength", "type": "dropdown", "mandatory": False, "multiSelect": False, "maxSelections": 1,
     "assignedCategories": ["Coffee"],
     "options": [{"name": "Mild", "price": 0}, {"name": "Regular", "price": 0}, {"name": "Strong", "price": 0}, {"name": "Extra Strong", "price": 0.50}]},
    {"name": "Syrup", "type": "list", "mandatory": False, "multiSelect": True, "maxSelections": 2,
     "assignedCategories": ["Coffee"],
     "options": [{"name": "Vanilla", "price": 0.80}, {"name": "Caramel", "price": 0.80}, {"name": "Hazelnut", "price": 0.80}, {"name": "Sugar-Free Vanilla", "price": 0.80}]},
    {"name": "Burger Cheese", "type": "list", "mandatory": False, "multiSelect": True, "maxSelections": 2,
     "assignedCategories": ["Burgers"],
     "options": [{"name": "Cheddar", "price": 1.50}, {"name": "Blue Cheese", "price": 2.00}, {"name": "Swiss", "price": 1.80}, {"name": "Vegan Cheese", "price": 2.00}]},
    {"name": "Burger Add-ons", "type": "list", "mandatory": False, "multiSelect": True, "maxSelections": 5,
     "assignedCategories": ["Burgers"],
     "options": [{"name": "Bacon", "price": 3.00}, {"name": "Avocado", "price": 2.50}, {"name": "Pineapple", "price": 1.50},
                 {"name": "Fried Egg", "price": 2.00}, {"name": "Jalapeños", "price": 1.00}]},
    {"name": "Cooking Preference", "type": "dropdown", "mandatory": True, "multiSelect": False, "maxSelections": 1,
     "assignedCategories": ["Mains", "Burgers"],
     "options": [{"name": "Rare", "price": 0}, {"name": "Medium Rare", "price": 0}, {"name": "Medium", "price": 0},
                 {"name": "Medium Well", "price": 0}, {"name": "Well Done", "price": 0}]},
    {"name": "Side Choice", "type": "list", "mandatory": False, "multiSelect": False, "maxSelections": 1,
     "assignedCategories": ["Mains", "Burgers"],
     "options": [{"name": "Fries", "price": 0}, {"name": "Sweet Potato Fries", "price": 2.00},
                 {"name": "Garden Salad", "price": 1.50}, {"name": "Mashed Potato", "price": 1.50}]},
    {"name": "Pasta Style", "type": "list", "mandatory": False, "multiSelect": False, "maxSelections": 1,
     "assignedCategories": ["Pasta"],
     "options": [{"name": "Gluten Free", "price": 2.00}, {"name": "Wholemeal", "price": 1.00}, {"name": "Regular", "price": 0}]},
    {"name": "Sauce Add-on", "type": "list", "mandatory": False, "multiSelect": True, "maxSelections": 3,
     "assignedCategories": ["Pasta", "Mains", "Burgers"],
     "options": [{"name": "Garlic Aioli", "price": 1.00}, {"name": "BBQ", "price": 0.50},
                 {"name": "Sriracha", "price": 0.50}, {"name": "Truffle Mayo", "price": 1.50}]},
]


@router.post("/seed/catalog")
async def seed_catalog(user: dict = Depends(require_owner)):
    """Owner-only: seed 5 categories, 60 products, 10 modifiers. Idempotent —
    skips items that already exist by name+category, scoped to the caller's
    own business.

    Each item uses an atomic upsert (update_one(..., upsert=True)) rather
    than a find_one-then-insert_one pair. The old check-then-insert had a
    real race window: two calls close together (e.g. an onboarding
    auto-trigger racing a manual "Seed Demo Data" click, or a client retry
    after a slow response) could both see "nothing exists yet" and both
    insert, producing two rows with the same name/SKU but different ids —
    a duplicate menu item, silently. An upsert is atomic per document, so
    a second concurrent call for the same item is guaranteed to either lose
    the race entirely (matches the just-inserted document, updates it) or
    win it outright — never both insert.

    The upsert filter and $setOnInsert previously matched/created by NAME
    ALONE, with no businessId anywhere — so the first business ever to
    seed created shared, untagged rows, and every OTHER business's later
    seed call matched (and silently reused) that same first business's
    rows instead of creating its own: multi-tenant seeding was completely
    broken, not just imprecise. Now every match filter and every inserted
    document is scoped to the caller's own businessId.
    """
    business_id = user.get("businessId")
    # Categories
    cat_added = 0
    for c in SEED_CATEGORIES:
        result = await db.categories.update_one(
            {"name": c["name"], "businessId": business_id},
            {
                "$set": {"icon": c["icon"], "color": c["color"],
                         "prepTime": c["prepTime"], "channels": c["channels"]},
                "$setOnInsert": {**{k: v for k, v in c.items()
                                  if k not in ("icon", "color", "prepTime", "channels", "name")},
                                  "businessId": business_id},
            },
            upsert=True,
        )
        if result.upserted_id is not None:
            cat_added += 1
    # Products
    prod_added = 0
    for i, p in enumerate(SEED_PRODUCTS):
        sku = f"SEED-{p['category'][:3].upper()}-{i:03d}"
        product = {
            "id": str(uuid.uuid4()),
            "price": float(p["price"]), "cost": float(p["cost"]),
            "stock": int(p["stock"]),
            "sku": sku, "image": p["image"],
            "gstRate": 10.0, "modifiers": [], "locations": ["Main"],
            "onlineChannels": [], "seoDescription": "", "description": "",
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "businessId": business_id,
        }
        result = await db.products.update_one(
            {"name": p["name"], "category": p["category"], "businessId": business_id},
            {"$setOnInsert": product},
            upsert=True,
        )
        if result.upserted_id is not None:
            prod_added += 1
    # Modifiers
    mod_added = 0
    for m in SEED_MODIFIERS:
        mod = {
            "id": f"mod-{str(uuid.uuid4())[:8]}",
            "printWithItem": True,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "businessId": business_id,
            **{k: v for k, v in m.items() if k != "name"},
        }
        result = await db.modifiers.update_one(
            {"name": m["name"], "businessId": business_id},
            {"$setOnInsert": mod},
            upsert=True,
        )
        if result.upserted_id is not None:
            mod_added += 1
    return {
        "categoriesAdded": cat_added, "categoriesTotal": len(SEED_CATEGORIES),
        "productsAdded": prod_added, "productsTotal": len(SEED_PRODUCTS),
        "modifiersAdded": mod_added, "modifiersTotal": len(SEED_MODIFIERS),
    }

# ============ MODIFIERS (Universal) ============
@router.get("/modifiers")
async def get_modifiers(user: dict = Depends(get_user)):
    mods = await db.modifiers.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}).to_list(500)
    return mods

@router.post("/modifiers")
async def create_modifier(data: dict, user: dict = Depends(require_owner_or_manager)):
    mod = {
        "id": f"mod-{str(uuid.uuid4())[:8]}",
        "businessId": user.get("businessId"),
        "name": data.get("name", ""),
        "type": data.get("type", "list"),
        "mandatory": data.get("mandatory", False),
        "multiSelect": data.get("multiSelect", False),
        "maxSelections": data.get("maxSelections", 1),
        "options": data.get("options", []),
        "assignedCategories": data.get("assignedCategories", []),
        # Where this modifier is offered + when it's available on each channel.
        # channels = ["dine-in","pickup","delivery","uber-eats","doordash","online"]
        "channels": data.get("channels", ["dine-in", "pickup", "delivery"]),
        "availableFrom": data.get("availableFrom"),   # "HH:MM"
        "availableTo": data.get("availableTo"),       # "HH:MM"
        "activeDays": data.get("activeDays", []),     # ["Mon",...,"Sun"] empty=all
        "printWithItem": data.get("printWithItem", True),
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    await db.modifiers.insert_one(mod)
    mod.pop("_id", None)
    return mod

@router.put("/modifiers/{mod_id}")
async def update_modifier(mod_id: str, data: dict, user: dict = Depends(require_owner_or_manager)):
    # tenant_owns_strict — seed_catalog()'s upserts now match/create scoped
    # to the caller's own businessId (release-closure pass), so an untagged
    # modifier here can only be pre-fix legacy data.
    existing = await db.modifiers.find_one({"$and": [{"id": mod_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "businessId": 1})
    if not existing or not tenant_owns_strict(existing.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Not found")
    allowed = {"name", "type", "mandatory", "multiSelect", "maxSelections", "options",
               "assignedCategories", "printWithItem",
               "channels", "availableFrom", "availableTo", "activeDays"}
    update = {k: v for k, v in data.items() if k in allowed}
    update["updatedAt"] = datetime.now(timezone.utc).isoformat()
    result = await db.modifiers.find_one_and_update({"$and": [{"id": mod_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": update}, return_document=True)
    if not result:
        raise HTTPException(status_code=404, detail="Not found")
    result.pop("_id", None)
    return result

@router.delete("/modifiers/{mod_id}")
async def delete_modifier(mod_id: str, user: dict = Depends(require_owner_or_manager)):
    # tenant_owns_strict — same reasoning as update_modifier's own comment.
    existing = await db.modifiers.find_one({"$and": [{"id": mod_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "businessId": 1})
    if not existing or not tenant_owns_strict(existing.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Not found")
    await db.modifiers.delete_one({"$and": [{"id": mod_id}, tenant_scope_filter(user.get("businessId"))]})
    return {"message": "Modifier deleted"}

# ============ DISCOUNTS & OFFERS ============
@router.get("/discounts")
async def get_discounts(user: dict = Depends(get_user)):
    discounts = await db.discounts.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}).to_list(200)
    return discounts

@router.post("/discounts")
async def create_discount(data: dict, user: dict = Depends(require_owner)):
    disc = {
        "id": f"DISC-{str(uuid.uuid4())[:8].upper()}",
        "businessId": user.get("businessId"),
        "name": data.get("name", ""),
        "type": data.get("type", "percentage"),  # percentage, fixed, bundle, bogo, half_price
        "value": data.get("value", 0),  # % or $ amount
        "conditions": data.get("conditions", {}),  # e.g. {minQty: 2, productId: "..."}
        "active": data.get("active", True),
        "startDate": data.get("startDate"), "endDate": data.get("endDate"),
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    await db.discounts.insert_one(disc)
    disc.pop("_id", None)
    return disc

@router.put("/discounts/{disc_id}")
async def update_discount(disc_id: str, data: dict, user: dict = Depends(require_owner)):
    existing = await db.discounts.find_one({"$and": [{"id": disc_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "businessId": 1})
    if not existing or not tenant_owns_strict(existing.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Not found")
    allowed = {"name", "type", "value", "conditions", "active", "startDate", "endDate"}
    update = {k: v for k, v in data.items() if k in allowed}
    result = await db.discounts.find_one_and_update({"$and": [{"id": disc_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": update}, return_document=True)
    if not result:
        raise HTTPException(status_code=404, detail="Not found")
    result.pop("_id", None)
    return result

@router.delete("/discounts/{disc_id}")
async def delete_discount(disc_id: str, user: dict = Depends(require_owner)):
    existing = await db.discounts.find_one({"$and": [{"id": disc_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "businessId": 1})
    if not existing or not tenant_owns_strict(existing.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Not found")
    await db.discounts.delete_one({"$and": [{"id": disc_id}, tenant_scope_filter(user.get("businessId"))]})
    return {"message": "Discount deleted"}

# ============ COMP / VOID ============
@router.post("/comp-void")
async def create_comp_void(data: dict, user: dict = Depends(require_permission("comp-void"))):
    """Recording a comp/void was hard-coded to owner/manager only, which
    silently ignored the 'comp-void' permission catalog entry (and the fact
    cashiers get it by default) — the granular permission system now
    actually governs this, same as everywhere else it's used."""
    record = {
        "id": f"CV-{str(uuid.uuid4())[:8].upper()}",
        "businessId": user.get("businessId"),
        "type": data.get("type", "comp"),  # comp or void
        "transactionId": data.get("transactionId"),
        "items": data.get("items", []),
        "reason": data.get("reason", ""),
        "amount": data.get("amount", 0),
        "printVoid": data.get("printVoid", False),
        "processedBy": user["id"],
        "processedByName": user.get("name") or user.get("email"),
        "processedAt": datetime.now(timezone.utc).isoformat(),
    }
    await db.comp_voids.insert_one(record)
    record.pop("_id", None)

    # Comp/void records lived only in their own narrow list (the old
    # standalone Audit Log page, since retired in favor of the universal
    # one) — nothing wrote them into the real audit trail, so restoring a
    # transaction's history never showed the comp/void issued against it.
    try:
        from services.audit_service import log_event
        await log_event(
            entity_type="comp_void", entity_id=record["id"], action="created",
            after=record, severity="notice",
            memo=f"{record['type'].upper()} — {record['reason'] or 'no reason given'} (${record['amount']})",
        )
    except Exception as e:
        from utils.errors import log_and_continue
        log_and_continue(logger, f"Comp/void audit log write failed for {record['id']}", e)

    return record

@router.get("/comp-void")
async def get_comp_voids(user: dict = Depends(require_owner_or_manager)):
    records = await db.comp_voids.find(
        tenant_scope_filter(user.get("businessId")), {"_id": 0}).sort("processedAt", -1).to_list(500)
    return records

# ============ PAYMENT LINKS ============
@router.post("/payment-links")
async def create_payment_link(data: dict, user: dict = Depends(require_owner_or_manager)):
    link = {
        "id": f"PLINK-{str(uuid.uuid4())[:8].upper()}",
        "businessId": user.get("businessId"),
        "productId": data.get("productId"),
        "productName": data.get("productName", ""),
        "price": data.get("price", 0),
        "url": f"https://pay.nua.pos/{str(uuid.uuid4())[:12]}",
        "active": True,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    await db.payment_links.insert_one(link)
    link.pop("_id", None)
    return link

@router.get("/payment-links")
async def get_payment_links(user: dict = Depends(get_user)):
    links = await db.payment_links.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}).to_list(500)
    return links

@router.delete("/payment-links/{link_id}")
async def delete_payment_link(link_id: str, user: dict = Depends(require_owner_or_manager)):
    existing = await db.payment_links.find_one({"$and": [{"id": link_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "businessId": 1})
    if not existing or not tenant_owns_strict(existing.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Not found")
    await db.payment_links.delete_one({"$and": [{"id": link_id}, tenant_scope_filter(user.get("businessId"))]})
    return {"message": "Payment link deleted"}
