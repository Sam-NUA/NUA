from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from datetime import datetime, timezone
import asyncio
import json
import logging
import os
import uuid
from database import db
from deps import get_user, optional_user, require_owner_or_manager
from models.product import Product, ProductCreate, ProductUpdate
from middleware.actor_context import tenant_scope_filter, tenant_owns_strict
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)

# Must stay in sync with frontend/src/i18n/translations.js's LANGUAGES list
# (minus 'en', which is the untranslated base). There's no shared source of
# truth between the two stacks for this today.
_TRANSLATABLE_LANGUAGES = {
    "it": "Italian", "zh": "Chinese (Simplified)", "hi": "Hindi",
    "es": "Spanish", "vi": "Vietnamese", "ar": "Arabic", "pt": "Portuguese",
}

# ============ PRODUCTS API ============
# Deliberately reachable without logging in: the kiosk and the QR table-order
# page are the menu, and they render before anyone has a session. What a guest
# must NOT get is the trade side of the catalogue — what each dish costs us and
# how much of it is in the building — so that gets stripped for guests only.
GUEST_HIDDEN_PRODUCT_FIELDS = ("cost", "stock", "sku")


@router.get("/products", response_model=List[Product])
async def get_products(category: Optional[str] = None, search: Optional[str] = None,
                       include_deleted: bool = False, business: Optional[str] = None, user=Depends(optional_user)):
    query = {}
    and_clauses = []
    if not include_deleted:
        and_clauses.append({"$or": [{"deletedAt": None}, {"deletedAt": {"$exists": False}}]})
    from routes.online_orders import resolve_or_require_business_id
    business_id = user["businessId"] if user else await resolve_or_require_business_id(business)
    tenant_filter = tenant_scope_filter(business_id)
    if tenant_filter:
        and_clauses.append(tenant_filter)
    if and_clauses:
        query["$and"] = and_clauses
    if category:
        query["category"] = category
    if search:
        # Matches name OR sku OR barcode — a barcode scanner fires this
        # exact same search endpoint with the scanned digits, so it has to
        # hit on more than just the display name.
        and_clauses.append({"$or": [
            {"name": {"$regex": search, "$options": "i"}},
            {"sku": {"$regex": search, "$options": "i"}},
            {"barcode": search},
        ]})
        query["$and"] = and_clauses
    products = await db.products.find(query).to_list(1000)
    if not user:
        # Guests never see deleted rows either, whatever they ask for.
        products = [p for p in products if not p.get("deletedAt")]
        for p in products:
            for f in GUEST_HIDDEN_PRODUCT_FIELDS:
                p.pop(f, None)
    return [Product(**p) for p in products]

@router.get("/products/{product_id}/variants", response_model=List[Product])
async def get_product_variants(product_id: str, business: Optional[str] = None, user=Depends(optional_user)):
    """Every sellable row under a variant-grouping product (e.g. a T-shirt's
    Small/Red, Small/Blue, Medium/Red... rows) — the parent itself is never
    sold, only listed here so POS/edit UI can render its variant matrix."""
    from routes.online_orders import resolve_or_require_business_id
    business_id = user["businessId"] if user else await resolve_or_require_business_id(business)
    tenant_filter = tenant_scope_filter(business_id)
    query = {"parentId": product_id, "$or": [{"deletedAt": None}, {"deletedAt": {"$exists": False}}]}
    if tenant_filter:
        query = {"$and": [query, tenant_filter]}
    variants = await db.products.find(query).to_list(500)
    return [Product(**v) for v in variants]

@router.post("/products", response_model=Product)
async def create_product(product: ProductCreate, _: dict = Depends(require_owner_or_manager)):
    from services.entity_service import stamped_insert
    product_dict = product.dict()
    now_iso = datetime.now(timezone.utc).isoformat()
    product_obj = Product(**product_dict, createdAt=now_iso, updatedAt=now_iso)
    doc = await stamped_insert("products", product_obj.dict(), entity_type="product")
    return Product(**doc)

@router.put("/products/{product_id}", response_model=Product)
async def update_product(product_id: str, product_update: ProductUpdate, user: dict = Depends(require_owner_or_manager)):
    from services.entity_service import stamped_update
    existing = await db.products.find_one({"$and": [{"id": product_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "businessId": 1})
    if not existing or not tenant_owns_strict(existing.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Product not found")
    update_data = {k: v for k, v in product_update.dict().items() if v is not None}
    result = await stamped_update("products", product_id, update_data, entity_type="product")
    if not result:
        raise HTTPException(status_code=404, detail="Product not found")
    return Product(**result)

@router.delete("/products/{product_id}")
async def delete_product(product_id: str, user: dict = Depends(require_owner_or_manager)):
    from services.entity_service import soft_delete
    existing = await db.products.find_one({"$and": [{"id": product_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "businessId": 1})
    if not existing or not tenant_owns_strict(existing.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Product not found")
    result = await soft_delete("products", product_id, entity_type="product")
    if not result:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"message": "Product soft-deleted", "id": product_id}

@router.post("/products/{product_id}/adjust-stock")
async def adjust_stock(product_id: str, data: dict, user: dict = Depends(require_owner_or_manager)):
    adjustment = data.get("adjustment", 0)
    reason = data.get("reason", "Manual adjustment")
    location = data.get("location")  # optional — see below
    product = await db.products.find_one({"$and": [{"id": product_id}, tenant_scope_filter(user.get("businessId"))]})
    if not product or not tenant_owns_strict(product.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Product not found")

    if location:
        # Per-location count (e.g. a physical stocktake at one branch) —
        # only touches that location's entry in stockByLocation, leaving
        # the flat `stock` total (what checkout/purchase-orders read) alone.
        # A business using per-location tracking is expected to also keep
        # `stock` in sync itself via its own totals process; this endpoint
        # doesn't guess at that for them.
        current = (product.get("stockByLocation") or {}).get(location, 0)
        new_location_stock = current + adjustment
        if new_location_stock < 0:
            raise HTTPException(status_code=400, detail="Stock cannot go below zero")
        await db.products.update_one({"$and": [{"id": product_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": {f"stockByLocation.{location}": new_location_stock}})
        await db.stock_adjustments.insert_one({
            "productId": product_id, "productName": product.get("name", ""), "location": location,
            "previousStock": current, "adjustment": adjustment,
            "newStock": new_location_stock, "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        return {"message": "Stock adjusted", "newStock": new_location_stock, "location": location}

    new_stock = product.get("stock", 0) + adjustment
    if new_stock < 0:
        raise HTTPException(status_code=400, detail="Stock cannot go below zero")
    await db.products.update_one({"$and": [{"id": product_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": {"stock": new_stock}})
    await db.stock_adjustments.insert_one({
        "productId": product_id, "productName": product.get("name", ""),
        "previousStock": product.get("stock", 0), "adjustment": adjustment,
        "newStock": new_stock, "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    return {"message": "Stock adjusted", "newStock": new_stock}


async def _draft_translations_core(name: str, description: str, session_suffix: str) -> dict:
    """Shared LLM call behind both the single-product and bulk auto-translate
    endpoints. Raises ValueError/whatever the SDK raises on any failure —
    callers decide how that should surface (a hard 502 for one product vs.
    just skipping that item out of a bulk run)."""
    lang_list = ", ".join(f"{code} ({label})" for code, label in _TRANSLATABLE_LANGUAGES.items())
    system = (
        "You translate restaurant menu items. Given a dish name and optional "
        "description, translate both into every requested language. Keep dish "
        "names natural for a menu (don't over-literalize), and keep descriptions "
        "concise. Respond with ONLY a JSON object, no prose, no markdown fences, "
        'shaped exactly like: {"it": {"name": "...", "description": "..."}, "es": '
        '{"name": "...", "description": "..."}, ...} — one key per language code, '
        "using every language code requested. Omit \"description\" for a language "
        "entry if the source description was empty."
    )
    user_text = f"Languages: {lang_list}\n\nDish name: {name}\nDescription: {description or '(none)'}"

    from emergentintegrations.llm.chat import LlmChat, UserMessage
    chat = LlmChat(
        api_key=os.environ["EMERGENT_LLM_KEY"], session_id=f"translate-{session_suffix}",
        system_message=system,
    ).with_model("openai", "gpt-5.2")
    resp = await chat.send_message(UserMessage(text=user_text))
    text = (resp or "").strip().strip("`")
    try:
        drafted = json.loads(text)
    except Exception:
        import re
        m = re.search(r"\{.*\}", text, re.DOTALL)
        drafted = json.loads(m.group(0)) if m else {}

    # Only keep languages we actually asked for, and only well-formed entries —
    # never let a malformed LLM response corrupt existing saved translations.
    cleaned = {
        code: {"name": v.get("name", "").strip(), "description": (v.get("description") or "").strip()}
        for code, v in (drafted or {}).items()
        if code in _TRANSLATABLE_LANGUAGES and isinstance(v, dict) and v.get("name", "").strip()
    }
    if not cleaned:
        raise ValueError("AI returned no usable translations")
    return cleaned


@router.post("/products/{product_id}/auto-translate")
async def auto_translate_product(product_id: str, user: dict = Depends(require_owner_or_manager)):
    """AI-draft translations for every supported language from this
    product's name/description, for staff to review before saving.

    Menu translations only ever showed up on the Customer Facing Display
    (and kiosk/QR/online menus) when a staff member manually typed every
    language for every product one at a time via the Translate dialog — a
    real, tedious per-item task nobody does for a full menu, so in
    practice almost every product just fell back to English regardless of
    what language a guest picked. This doesn't remove that manual step
    (staff still review and hit Save), it just means starting from an AI
    draft instead of a blank form. For translating the whole menu in one
    go instead of one product at a time, see bulk_auto_translate_products
    below.
    """
    product = await db.products.find_one({"$and": [{"id": product_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not product or not tenant_owns_strict(product.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Product not found")

    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="AI translation is not configured")

    name = product.get("name", "")
    if not name:
        raise HTTPException(status_code=400, detail="Product has no name to translate")

    try:
        cleaned = await _draft_translations_core(
            name, product.get("description", ""), f"{product_id}-{uuid.uuid4().hex[:6]}")
    except Exception as e:
        logger.warning(f"Auto-translate failed for product {product_id}: {e}")
        raise HTTPException(status_code=502, detail="AI translation failed — try again")
    return {"translations": cleaned}


@router.post("/products/bulk-auto-translate")
async def bulk_auto_translate_products(only_missing: bool = True, user: dict = Depends(require_owner_or_manager)):
    """AI-draft AND SAVE translations for every product on the menu in one
    pass, instead of the per-product Translate dialog's one-at-a-time flow.

    That per-product flow (including its own AI-draft button) still needed
    a staff member to open each product and hit Save individually — for a
    50+ item menu that's realistically never finished, which is exactly why
    the Customer Facing Display kept showing English regardless of the
    language a guest picked. This saves directly rather than requiring
    per-product review (reviewing 50+ drafts one at a time defeats the
    point of "in one pass"); a manager who wants to hand-correct a specific
    dish can still do that afterward via the normal Translate dialog.

    only_missing=True (default) skips products that already have at least
    one saved translation, so re-running this after a manual correction
    doesn't clobber it. Runs up to 5 products concurrently — serial would
    make a real menu take minutes.
    """
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="AI translation is not configured")

    query = tenant_scope_filter(user.get("businessId"))
    if only_missing:
        query = {"$and": [query, {"$or": [{"translations": {"$exists": False}}, {"translations": {}}]}]}
    products = await db.products.find(query, {"_id": 0, "id": 1, "name": 1, "description": 1}).to_list(2000)

    sem = asyncio.Semaphore(5)
    counts = {"translated": 0, "failed": 0, "skipped": 0}

    async def _one(p):
        if not p.get("name"):
            counts["skipped"] += 1
            return
        async with sem:
            try:
                cleaned = await _draft_translations_core(
                    p["name"], p.get("description", ""), f"bulk-{p['id']}-{uuid.uuid4().hex[:4]}")
            except Exception as e:
                logger.warning(f"Bulk auto-translate failed for product {p['id']}: {e}")
                counts["failed"] += 1
                return
        await db.products.update_one({"id": p["id"]}, {"$set": {"translations": cleaned}})
        counts["translated"] += 1

    await asyncio.gather(*(_one(p) for p in products))
    return {"total": len(products), **counts}


# ============ BULK PRODUCT EDIT ============
class BulkProductEdit(BaseModel):
    productIds: List[str]
    # Optional fields — only fields present (non-None) are applied
    category: Optional[str] = None
    categoryId: Optional[str] = None
    pricePercentDelta: Optional[float] = None  # e.g. +10 = +10%, -5 = -5%
    cost: Optional[float] = None
    gstRate: Optional[float] = None
    image: Optional[str] = None
    eightySixed: Optional[bool] = None
    active: Optional[bool] = None
    addModifierIds: Optional[List[str]] = None      # union into existing
    removeModifierIds: Optional[List[str]] = None   # subtract from existing
    replaceModifierIds: Optional[List[str]] = None  # overwrite entirely
    onlineChannels: Optional[List[str]] = None

@router.post("/products/bulk-edit")
async def bulk_edit_products(payload: BulkProductEdit, user: dict = Depends(require_owner_or_manager)):
    if not payload.productIds:
        raise HTTPException(status_code=400, detail="productIds is required")
    now_iso = datetime.now(timezone.utc).isoformat()

    # ---- Fast path: when no per-row math (pricePercentDelta) AND no modifier
    # add/remove (which require per-row union/difference), apply update_many.
    needs_per_row = (
        payload.pricePercentDelta is not None
        or bool(payload.addModifierIds)
        or bool(payload.removeModifierIds)
    )
    common: dict = {"updatedAt": now_iso}
    if payload.category is not None:
        common["category"] = payload.category
    if payload.categoryId is not None:
        common["categoryId"] = payload.categoryId
    if payload.cost is not None:
        common["cost"] = payload.cost
    if payload.gstRate is not None:
        common["gstRate"] = payload.gstRate
    if payload.image is not None:
        common["image"] = payload.image
    if payload.eightySixed is not None:
        common["eightySixed"] = payload.eightySixed
        common["eightySixedAt"] = now_iso if payload.eightySixed else None
    if payload.active is not None:
        common["active"] = payload.active
    if payload.onlineChannels is not None:
        common["onlineChannels"] = payload.onlineChannels
    if payload.replaceModifierIds is not None:
        common["modifierIds"] = list(payload.replaceModifierIds)

    tenant_filter = tenant_scope_filter(user.get("businessId"))

    if not needs_per_row:
        res = await db.products.update_many(
            {"id": {"$in": payload.productIds}, **tenant_filter},
            {"$set": common},
        )
        return {"updated": res.modified_count, "failed": [], "mode": "update_many"}

    # ---- Slow path: per-row math
    updated = 0
    failed: List[str] = []
    for pid in payload.productIds:
        prod = await db.products.find_one({"id": pid, **tenant_filter})
        if not prod:
            failed.append(pid)
            continue
        patch: dict = dict(common)
        if payload.pricePercentDelta is not None:
            # Clamp to avoid driving prices below zero (a -100% would zero them;
            # anything < -99 is almost certainly a typo).
            delta = max(-99.0, float(payload.pricePercentDelta))
            base_price = float(prod.get("price", 0) or 0)
            patch["price"] = round(max(0.0, base_price * (1 + delta / 100.0)), 2)
        # Modifier ops
        if payload.replaceModifierIds is None and (payload.addModifierIds or payload.removeModifierIds):
            existing_mods = list(prod.get("modifierIds", []) or [])
            if payload.addModifierIds:
                existing_mods = list({*existing_mods, *payload.addModifierIds})
            if payload.removeModifierIds:
                existing_mods = [m for m in existing_mods if m not in payload.removeModifierIds]
            patch["modifierIds"] = existing_mods
        await db.products.update_one({"id": pid}, {"$set": patch})
        updated += 1
    return {"updated": updated, "failed": failed, "mode": "per_row"}


# ============ PRODUCT IMAGE LIBRARY ============
class ImageLibraryEntry(BaseModel):
    id: str
    name: str
    contentType: str
    dataUrl: str         # full data URL (data:image/png;base64,XXX)
    tags: List[str] = []
    createdAt: str
    createdBy: Optional[str] = None
    sizeBytes: int = 0

class ImageUploadBody(BaseModel):
    name: str
    contentType: str
    dataUrl: str
    tags: List[str] = []
    createdBy: Optional[str] = None

MAX_IMAGE_BYTES = 1_500_000  # ~1.5MB after base64 — keep db lean

@router.get("/product-images", response_model=List[ImageLibraryEntry])
async def list_images(_: dict = Depends(get_user), search: Optional[str] = None, tag: Optional[str] = None, limit: int = 100):
    # Any signed-in staff can browse the library (cashiers need to see images);
    # owner/manager required for mutations below.
    # Cap list size — each entry can carry ~1.5MB base64 so a large list quickly
    # exhausts response bandwidth. Default 100 is plenty for a hand-curated library.
    limit = max(1, min(500, limit))
    query: dict = {}
    if search:
        query["name"] = {"$regex": search, "$options": "i"}
    if tag:
        query["tags"] = tag
    rows = await db.product_images.find(query).sort("createdAt", -1).to_list(limit)
    out = []
    for r in rows:
        out.append(ImageLibraryEntry(
            id=r.get("id"), name=r.get("name", ""), contentType=r.get("contentType", "image/png"),
            dataUrl=r.get("dataUrl", ""), tags=r.get("tags", []), createdAt=r.get("createdAt", ""),
            createdBy=r.get("createdBy"), sizeBytes=r.get("sizeBytes", 0),
        ))
    return out

@router.post("/product-images", response_model=ImageLibraryEntry)
async def upload_image(body: ImageUploadBody, user: dict = Depends(require_owner_or_manager)):
    if not body.dataUrl.startswith("data:"):
        raise HTTPException(status_code=400, detail="dataUrl must be a data: URL")
    size = len(body.dataUrl)
    if size > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail=f"Image too large ({size} > {MAX_IMAGE_BYTES})")
    entry = ImageLibraryEntry(
        id=str(uuid.uuid4()),
        name=body.name,
        contentType=body.contentType,
        dataUrl=body.dataUrl,
        tags=body.tags,
        createdAt=datetime.now(timezone.utc).isoformat(),
        createdBy=body.createdBy or user.get("name"),
        sizeBytes=size,
    )
    await db.product_images.insert_one(entry.dict())
    return entry

@router.delete("/product-images/{image_id}")
async def delete_image(image_id: str, _: dict = Depends(require_owner_or_manager)):
    res = await db.product_images.delete_one({"id": image_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Image not found")
    return {"deleted": True}


# Categories & Modifiers moved to routes/items_system.py
