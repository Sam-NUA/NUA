from fastapi import APIRouter, Depends
from deps import require_owner_or_manager
from database import db
from middleware.actor_context import tenant_scope_filter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, List
import uuid, os, base64

router = APIRouter()


async def _existing_categories(business_id: str = None) -> List[Dict[str, Any]]:
    return await db.categories.find(tenant_scope_filter(business_id), {"_id": 0}).to_list(200)


async def _existing_modifiers(business_id: str = None) -> List[Dict[str, Any]]:
    return await db.modifiers.find(tenant_scope_filter(business_id), {"_id": 0}).to_list(500)


def _fuzzy_match_category(proposed: str, cats: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    """Return the best matching existing category (score >= 0.55), else None."""
    if not proposed:
        return None
    proposed_l = proposed.lower().strip()
    best: tuple[float, Dict[str, Any] | None] = (0.0, None)
    for c in cats:
        cname = str(c.get("name", "")).lower()
        # Direct contains gives a boost (Cocktails vs "Cocktail" / Wine — Red vs "Red Wine")
        if proposed_l == cname:
            return c
        if proposed_l in cname or cname in proposed_l:
            score = 0.85
        else:
            score = SequenceMatcher(None, proposed_l, cname).ratio()
        if score > best[0]:
            best = (score, c)
    return best[1] if best[0] >= 0.55 else None


def _suggest_modifiers(category_name: str, mods: List[Dict[str, Any]]) -> List[str]:
    """Return modifier IDs whose `assignedCategories` include this category."""
    out: List[str] = []
    for m in mods:
        assigned = m.get("assignedCategories") or []
        if category_name in assigned:
            out.append(m.get("id"))
    return out


async def _run_vision_extraction(file_data: str, file_type: str) -> Dict[str, Any]:
    """Shared: pull items out of an image/pdf. Returns {items, message, rawResponse?}."""
    import json as _json

    # Normalise base64 — strip any leading data URL prefix
    if "," in file_data and file_data.startswith("data:"):
        file_data = file_data.split(",", 1)[1]
    if not file_data:
        return {"items": [], "message": "No file data received"}

    system_msg = (
        "You are a menu extraction expert. Extract EVERY menu item you can see.\n"
        "Return ONLY a JSON array — no markdown fences, no explanations — with this exact shape:\n"
        '[{"name": "Item Name", "category": "Category", "price": 12.50, "cost": 4.00, "description": "Brief desc"}]\n'
        "Category should reflect what the menu itself uses (e.g. Coffee, Wine — Red, Cocktails, Mains, Beer). Prefer specific over generic.\n"
        "If cost is not on the menu, estimate at 30–35% of price. Include description only if the menu shows one."
    )

    from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent
    api_key = os.environ.get("EMERGENT_LLM_KEY", "")
    if not api_key:
        return {"items": [], "message": "LLM key not configured"}

    chat = LlmChat(
        api_key=api_key,
        session_id=f"menu-import-{uuid.uuid4()}",
        system_message=system_msg,
    ).with_model("openai", "gpt-5.2")

    if file_type == "pdf":
        try:
            import pypdf, io
            pdf_bytes = base64.b64decode(file_data)
            reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
            pdf_text = "\n\n".join((page.extract_text() or "") for page in reader.pages).strip()
            if not pdf_text:
                return {"items": [], "message": "Could not read any text from the PDF. Try uploading a photo of the menu instead."}
            user_msg = UserMessage(text=f"Parse this menu text and return the JSON array of items:\n\n{pdf_text[:12000]}")
        except Exception as pdf_err:
            return {"items": [], "message": f"PDF parse failed: {pdf_err}"}
    else:
        user_msg = UserMessage(
            text="Extract every menu item from this image and return the JSON array.",
            file_contents=[ImageContent(image_base64=file_data)],
        )

    response = await chat.send_message(user_msg)

    text = (response or "").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text.lstrip("`")
        if text.lstrip().lower().startswith("json"):
            text = text.split("\n", 1)[1] if "\n" in text else text[4:]
        text = text.rsplit("```", 1)[0].strip()

    try:
        parsed = _json.loads(text)
    except Exception:
        return {"items": [], "message": "Could not auto-parse the LLM response.", "rawResponse": response}

    if isinstance(parsed, list):
        items = parsed
    elif isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
        items = parsed["items"]
    else:
        items = []

    return {"items": items, "message": ""}


# ============ AI MENU IMPORT — PREVIEW (no DB writes) ============
@router.post("/menu/ai-preview")
async def ai_menu_preview(data: dict, user: dict = Depends(require_owner_or_manager)):
    """Extract menu items from image/PDF, enrich with fuzzy-matched existing
    categories + suggested modifiers. **Does not write to the DB** — the UI
    shows a review table and calls /menu/ai-commit once the owner is happy.
    """
    result = await _run_vision_extraction(data.get("fileData", "") or "", (data.get("fileType") or "image").lower())
    raw_items = result.get("items") or []
    if not raw_items:
        return {"items": [], "count": 0, "message": result.get("message") or "No menu items detected. Try a clearer image.", "rawResponse": result.get("rawResponse")}

    biz = user.get("businessId")
    cats = await _existing_categories(biz)
    mods = await _existing_modifiers(biz)

    proposed: List[Dict[str, Any]] = []
    for item in raw_items:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        try:
            price = float(item.get("price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        try:
            cost = float(item.get("cost") or 0) or round(price * 0.35, 2)
        except (TypeError, ValueError):
            cost = round(price * 0.35, 2)
        proposed_cat = str(item.get("category") or "").strip()
        matched = _fuzzy_match_category(proposed_cat, cats)
        matched_cat_name = matched["name"] if matched else (proposed_cat or "Food")
        matched_cat_id = matched.get("id") if matched else None
        suggested_mod_ids = _suggest_modifiers(matched_cat_name, mods)
        # Check if a same-name product already exists (helps UI mark duplicates)
        # — scoped to this business's own catalogue, so another business's
        # product of the same name never gets treated as "already exists".
        existing = await db.products.find_one(
            {"name": name, **tenant_scope_filter(biz)}, {"_id": 0, "id": 1})
        proposed.append({
            "tempId": str(uuid.uuid4()),
            "name": name,
            "proposedCategory": proposed_cat,
            "category": matched_cat_name,
            "categoryId": matched_cat_id,
            "categoryMatched": bool(matched),
            "price": price,
            "cost": cost,
            "description": str(item.get("description") or ""),
            "suggestedModifierIds": suggested_mod_ids,
            "isDuplicate": bool(existing),
            "include": not bool(existing),
        })

    known_cats = [{"id": c.get("id"), "name": c.get("name"), "color": c.get("color"), "icon": c.get("icon")} for c in cats]
    known_mods = [{"id": m.get("id"), "name": m.get("name"), "assignedCategories": m.get("assignedCategories") or []} for m in mods]
    return {
        "items": proposed,
        "count": len(proposed),
        "knownCategories": known_cats,
        "knownModifiers": known_mods,
        "message": f"Detected {len(proposed)} item{'s' if len(proposed) != 1 else ''} — review and commit.",
    }


# ============ AI MENU IMPORT — COMMIT (reviewed items → DB) ============
@router.post("/menu/ai-commit")
async def ai_menu_commit(data: dict, user: dict = Depends(require_owner_or_manager)):
    """Persist reviewed items to /products. Expects
    { items: [ { name, category, categoryId?, price, cost, description?, modifierIds?, skipIfDuplicate? } ] }
    Skips rows where `name` is blank or (if `skipIfDuplicate`) an item with the
    same name already exists.
    """
    from services.entity_service import stamped_insert
    biz = user.get("businessId")
    items = data.get("items") or []
    created: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for it in items:
        name = str(it.get("name") or "").strip()
        if not name:
            skipped.append({"reason": "empty name", "item": it}); continue
        if it.get("skipIfDuplicate"):
            dup = await db.products.find_one({"name": name, **tenant_scope_filter(biz)}, {"_id": 0, "id": 1})
            if dup:
                skipped.append({"reason": "duplicate", "name": name}); continue
        try:
            price = float(it.get("price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        try:
            cost = float(it.get("cost") or 0) or round(price * 0.35, 2)
        except (TypeError, ValueError):
            cost = round(price * 0.35, 2)
        cat_name = str(it.get("category") or "Food").strip() or "Food"
        cat_id = it.get("categoryId")
        prod_id = str(uuid.uuid4())
        prod = {
            "id": prod_id,
            "name": name,
            "category": cat_name,
            "categoryId": cat_id,
            "price": price,
            "cost": cost,
            "stock": int(it.get("stock") or 100),
            "sku": f"AI-{prod_id[:8].upper()}",
            "image": str(it.get("image") or ""),
            "gstRate": float(it.get("gstRate") or 10.0),
            "description": str(it.get("description") or ""),
            "modifierIds": list(it.get("modifierIds") or []),
            "active": True,
            "eightySixed": False,
        }
        saved = await stamped_insert("products", prod, entity_type="product")
        saved.pop("_id", None)
        created.append(saved)
    return {
        "created": len(created),
        "skipped": len(skipped),
        "skippedDetails": skipped,
        "items": created,
        "message": f"Imported {len(created)} · Skipped {len(skipped)}",
    }


# ============ AI MENU IMPORT (LEGACY one-shot — kept for compat) ============
@router.post("/menu/ai-import")
async def ai_import_menu(data: dict, user: dict = Depends(require_owner_or_manager)):
    """Backwards-compatible one-shot endpoint that extracts AND writes in one
    call. New UIs should prefer /menu/ai-preview → /menu/ai-commit."""
    result = await _run_vision_extraction(data.get("fileData", "") or "", (data.get("fileType") or "image").lower())
    raw_items = result.get("items") or []
    if not raw_items:
        return {"items": [], "count": 0, "message": result.get("message") or "No items detected"}
    biz = user.get("businessId")
    cats = await _existing_categories(biz)
    mods = await _existing_modifiers(biz)
    from services.entity_service import stamped_insert
    created = []
    for item in raw_items:
        name = str(item.get("name") or "").strip()
        if not name: continue
        try: price = float(item.get("price") or 0)
        except (TypeError, ValueError): price = 0.0
        try: cost = float(item.get("cost") or 0) or round(price * 0.35, 2)
        except (TypeError, ValueError): cost = round(price * 0.35, 2)
        matched = _fuzzy_match_category(str(item.get("category") or ""), cats)
        cat_name = matched["name"] if matched else (str(item.get("category") or "Food") or "Food")
        cat_id = matched.get("id") if matched else None
        prod_id = str(uuid.uuid4())
        product = {
            "id": prod_id, "name": name, "category": cat_name, "categoryId": cat_id,
            "price": price, "cost": cost, "stock": 100,
            "sku": f"AI-{prod_id[:8].upper()}", "image": "", "gstRate": 10.0,
            "description": str(item.get("description") or ""),
            "modifierIds": _suggest_modifiers(cat_name, mods),
            "active": True, "eightySixed": False,
        }
        saved = await stamped_insert("products", product, entity_type="product")
        saved.pop("_id", None)
        created.append(saved)
    return {"items": created, "count": len(created), "message": f"Successfully imported {len(created)} menu items"}

# ============ PRICE ADJUSTMENT (Bulk) ============
@router.post("/menu/price-adjust")
async def bulk_price_adjust(data: dict, user: dict = Depends(require_owner_or_manager)):
    """Adjust prices by category with inflation/percentage"""

    category = data.get("category")  # None = all categories
    adjustment_type = data.get("type", "percentage")  # percentage or fixed
    amount = float(data.get("amount", 0))  # e.g. 5 for 5% or $5
    direction = data.get("direction", "increase")  # increase or decrease

    # Scoped to the caller's own business — without this, "adjust all Wine
    # prices" (or, worse, an empty category = "all products") repriced
    # every business's matching products on the deployment, not just this
    # business's own.
    biz_scope = tenant_scope_filter(user.get("businessId"))
    query = {"category": category, **biz_scope} if category else biz_scope
    products = await db.products.find(query, {"_id": 0}).to_list(10000)

    updated = []
    for p in products:
        old_price = p.get("price", 0)
        if adjustment_type == "percentage":
            change = old_price * (amount / 100)
        else:
            change = amount

        new_price = old_price + change if direction == "increase" else old_price - change
        new_price = max(round(new_price, 2), 0.01)

        # Re-applies the same scope as a defense-in-depth check, not just an
        # id match — belt-and-braces against this list ever including a
        # product this business doesn't own.
        await db.products.update_one(
            {"id": p["id"], **biz_scope},
            {"$set": {"price": new_price, "updatedAt": datetime.now(timezone.utc).isoformat()}})
        updated.append({"id": p["id"], "name": p["name"], "oldPrice": old_price, "newPrice": new_price})

    return {"updated": len(updated), "items": updated, "message": f"Adjusted {len(updated)} items by {amount}{'%' if adjustment_type == 'percentage' else '$'} {direction}"}

# ============ WHAT-IF SIMULATOR (Enhanced with Quantity) ============
@router.post("/analytics/what-if-advanced")
async def what_if_advanced(data: dict, user: dict = Depends(require_owner_or_manager)):
    """Enhanced what-if with manual quantity projections"""

    biz_scope = tenant_scope_filter(user.get("businessId"))
    changes = data.get("changes", [])
    results = []
    total_current_revenue = 0
    total_projected_revenue = 0
    total_current_profit = 0
    total_projected_profit = 0

    for c in changes:
        pid = c.get("productId")
        product = await db.products.find_one({"id": pid, **biz_scope}, {"_id": 0})
        if not product:
            continue

        current_price = product.get("price", 0)
        current_cost = product.get("cost", 0)
        new_price = c.get("newPrice", current_price)
        new_cost = c.get("newCost", current_cost)
        projected_qty = c.get("projectedQty", 0)  # NEW: manual quantity

        # Calculate using projected quantity
        if projected_qty > 0:
            current_revenue = current_price * projected_qty
            projected_revenue = new_price * projected_qty
            current_profit = (current_price - current_cost) * projected_qty
            projected_profit = (new_price - new_cost) * projected_qty
        else:
            # Fallback to historical average (from transactions)
            txns = await db.transactions.find(biz_scope, {"_id": 0, "items": 1}).to_list(10000)
            qty_sold = 0
            for t in txns:
                for item in t.get("items", []):
                    if item.get("productId") == pid:
                        qty_sold += item.get("quantity", 0)
            avg_daily = max(qty_sold / 30, 1)
            projected_qty = round(avg_daily * 30)
            current_revenue = current_price * projected_qty
            projected_revenue = new_price * projected_qty
            current_profit = (current_price - current_cost) * projected_qty
            projected_profit = (new_price - new_cost) * projected_qty

        results.append({
            "productId": pid, "productName": product.get("name", ""),
            "currentPrice": current_price, "newPrice": new_price,
            "currentCost": current_cost, "newCost": new_cost,
            "projectedQty": projected_qty,
            "currentRevenue": round(current_revenue, 2),
            "projectedRevenue": round(projected_revenue, 2),
            "currentProfit": round(current_profit, 2),
            "projectedProfit": round(projected_profit, 2),
            "revenueChange": round(projected_revenue - current_revenue, 2),
            "profitChange": round(projected_profit - current_profit, 2),
        })
        total_current_revenue += current_revenue
        total_projected_revenue += projected_revenue
        total_current_profit += current_profit
        total_projected_profit += projected_profit

    return {
        "items": results,
        "summary": {
            "currentRevenue": round(total_current_revenue, 2),
            "projectedRevenue": round(total_projected_revenue, 2),
            "revenueChange": round(total_projected_revenue - total_current_revenue, 2),
            "currentProfit": round(total_current_profit, 2),
            "projectedProfit": round(total_projected_profit, 2),
            "profitChange": round(total_projected_profit - total_current_profit, 2),
        }
    }
