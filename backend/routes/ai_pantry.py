from fastapi import APIRouter, HTTPException, Depends
from deps import get_user, require_owner_or_manager
from database import db
from middleware.actor_context import tenant_scope_filter, tenant_owns_strict
import os
import uuid
from datetime import datetime

router = APIRouter()

async def _get_ai_chat():
    from emergentintegrations.llm.chat import LlmChat
    key = os.environ.get("EMERGENT_LLM_KEY")
    if not key:
        raise HTTPException(status_code=500, detail="AI not configured")
    chat = LlmChat(api_key=key, session_id=f"pantry-{uuid.uuid4()}", system_message=(
        "You are an expert restaurant supply chain manager and chef. "
        "Analyze menu items, their descriptions, and sales data to determine exact ingredient needs. "
        "Always respond with valid JSON only, no markdown."
    ))
    chat.with_model("openai", "gpt-5.2")
    return chat

@router.get("/ai-pantry/generate")
async def generate_pantry_list(user: dict = Depends(require_owner_or_manager)):
    """AI-powered weekly ordering list based on menu, sales, and reservations"""

    # Gather data
    biz_scope = tenant_scope_filter(user.get("businessId"))
    products = await db.products.find(biz_scope, {"_id": 0}).to_list(1000)
    txns = await db.transactions.find(biz_scope, {"_id": 0}).to_list(5000)
    reservations = await db.reservations.find(biz_scope, {"_id": 0}).to_list(500)

    # Build sales summary
    product_sales = {}
    for txn in txns:
        for item in txn.get("items", []):
            pid = item.get("productId", "")
            product_sales[pid] = product_sales.get(pid, 0) + item.get("quantity", 0)

    upcoming_covers = sum(r.get("partySize", 0) for r in reservations if r.get("status") in ("confirmed", "seated"))

    menu_data = []
    for p in products:
        menu_data.append({
            "id": p["id"], "name": p["name"],
            "category": p.get("category", "Other"),
            "description": p.get("description", ""),
            "price": p.get("price", 0),
            "cost": p.get("cost", 0),
            "currentStock": p.get("stock", 0),
            "weeklySales": product_sales.get(p["id"], 0),
        })

    prompt = f"""Analyze this restaurant menu and sales data to generate a weekly ordering/pantry list.

Menu Items:
{str(menu_data)}

Upcoming reservations: {upcoming_covers} covers booked this week.
Total transactions last period: {len(txns)}

Generate a JSON response with this EXACT structure:
{{
  "orderingList": [
    {{
      "ingredient": "ingredient name",
      "category": "Produce|Dairy|Meat|Seafood|Dry Goods|Beverages|Other",
      "estimatedQuantity": "amount with unit (e.g., 5kg, 2L, 50 units)",
      "urgency": "high|medium|low",
      "estimatedCost": 0.00,
      "usedIn": ["menu item 1", "menu item 2"],
      "notes": "any wastage or storage notes"
    }}
  ],
  "wastageInsights": [
    {{
      "item": "ingredient name",
      "risk": "high|medium|low",
      "recommendation": "suggestion to minimize waste"
    }}
  ],
  "weeklyBudgetEstimate": 0.00,
  "coverForecast": 0,
  "summary": "brief summary of ordering priorities"
}}"""

    from emergentintegrations.llm.chat import UserMessage
    chat = await _get_ai_chat()
    response = await chat.send_message(UserMessage(text=prompt))

    import json
    try:
        parsed = json.loads(response)
    except json.JSONDecodeError:
        # Try extracting JSON from response
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(response[start:end])
        else:
            parsed = {"raw": response, "error": "Could not parse AI response"}

    # Save to DB
    pantry_doc = {
        "id": f"PANTRY-{str(uuid.uuid4())[:8].upper()}",
        "generatedAt": datetime.utcnow().isoformat(),
        "generatedBy": user["id"],
        "data": parsed,
        "menuItemCount": len(products),
        "transactionCount": len(txns),
        "upcomingCovers": upcoming_covers,
        "businessId": user.get("businessId"),
    }
    await db.pantry_lists.insert_one(pantry_doc)
    pantry_doc.pop("_id", None)
    return pantry_doc

@router.get("/ai-pantry/history")
async def get_pantry_history(user: dict = Depends(require_owner_or_manager)):
    """Get previous pantry list generations"""
    q = tenant_scope_filter(user.get("businessId"))
    lists = await db.pantry_lists.find(q, {"_id": 0}).sort("generatedAt", -1).to_list(20)
    return lists


# ============================================================================
# INVOICE OCR — upload supplier invoice → LLM extracts → auto-update products
# ============================================================================
@router.post("/ai-pantry/parse-invoice")
async def parse_invoice(data: dict, user: dict = Depends(require_owner_or_manager)):
    """Owner/manager uploads a supplier invoice as a base64 image (or pasted
    text). LLM extracts each line item (name, qty, unit cost) and we attempt to
    match each against existing products by fuzzy name. The caller can then
    confirm + commit price/cost updates via /ai-pantry/apply-invoice."""
    invoice_text = (data.get("text") or "").strip()
    image_b64 = data.get("imageBase64")
    if not invoice_text and not image_b64:
        raise HTTPException(status_code=400, detail="Provide either invoice 'text' or 'imageBase64'")

    sys_msg = (
        "You parse restaurant supplier invoices. Extract ALL line items and "
        "return STRICT JSON with this shape: {"
        '"supplier":"...", "invoiceNumber":"...", "invoiceDate":"YYYY-MM-DD", '
        '"items":[{"name":"...", "quantity":0, "unit":"kg|L|ea|box|case", '
        '"unitCost":0.00, "totalCost":0.00}], "subtotal":0, "gst":0, '
        '"total":0, "currency":"AUD"}. '
        "Use lower-case keys. If a value is missing use null. "
        "Best-guess parsing — do not invent items."
    )

    from emergentintegrations.llm.chat import LlmChat, UserMessage
    chat = LlmChat(
        api_key=os.environ.get("EMERGENT_LLM_KEY"),
        session_id=f"invoice-{uuid.uuid4().hex[:6]}",
        system_message=sys_msg,
    ).with_model("openai", "gpt-5.2")

    msg_args = {"text": invoice_text or "Parse the attached invoice image."}
    if image_b64:
        try:
            from emergentintegrations.llm.chat import ImageContent
            msg_args["file_contents"] = [ImageContent(image_base64=image_b64)]
        except Exception:
            pass
    reply = await chat.send_message(UserMessage(**msg_args))

    import json as _json
    parsed = None
    try:
        parsed = _json.loads(reply)
    except Exception:
        s, e = reply.find("{"), reply.rfind("}") + 1
        if s >= 0 and e > s:
            try: parsed = _json.loads(reply[s:e])
            except Exception: parsed = None
    if not parsed or "items" not in parsed:
        raise HTTPException(status_code=422, detail=f"Could not parse invoice. AI returned: {reply[:300]}")

    # Match each parsed line against existing products by case-insensitive name
    # — scoped to this business's own catalogue, so an invoice can never
    # match (and later, via apply-invoice, silently reprice) another
    # business's products.
    products = await db.products.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}).to_list(2000)
    by_name = {p["name"].lower(): p for p in products}
    matches = []
    for line in parsed.get("items", []):
        name = (line.get("name") or "").strip()
        if not name: continue
        # Best-match: exact lower-case, else token-overlap
        lower = name.lower()
        match = by_name.get(lower)
        if not match:
            tokens = set(t for t in lower.split() if len(t) > 2)
            best, best_score = None, 0
            for p in products:
                ptokens = set(t for t in p["name"].lower().split() if len(t) > 2)
                score = len(tokens & ptokens)
                if score > best_score:
                    best, best_score = p, score
            if best and best_score >= 1:
                match = best
        new_cost = float(line.get("unitCost") or 0)
        old_cost = float((match or {}).get("cost") or 0)
        # Default new price preserves the current margin (round to .99 if old price > 5)
        new_price = None
        if match and old_cost > 0 and new_cost > 0:
            margin = max(0, float(match["price"]) - old_cost) / max(0.01, float(match["price"]))
            suggested = round(new_cost / (1 - margin), 2) if margin < 1 else float(match["price"])
            new_price = suggested
        matches.append({
            "lineItem": line,
            "matchedProductId": match["id"] if match else None,
            "matchedProductName": match["name"] if match else None,
            "currentCost": old_cost,
            "newCost": new_cost,
            "currentPrice": (match or {}).get("price"),
            "suggestedPrice": new_price,
            "costDelta": round(new_cost - old_cost, 2) if match else None,
        })

    invoice_doc = {
        "id": f"INV-{uuid.uuid4().hex[:8].upper()}",
        "uploadedAt": datetime.utcnow().isoformat(),
        "uploadedBy": user["id"],
        "parsed": parsed,
        "matches": matches,
        "applied": False,
        "businessId": user.get("businessId"),
    }
    await db.invoices.insert_one(invoice_doc); invoice_doc.pop("_id", None)
    return invoice_doc


@router.post("/ai-pantry/apply-invoice/{invoice_id}")
async def apply_invoice(invoice_id: str, data: dict, user: dict = Depends(require_owner_or_manager)):
    """Apply selected price/cost updates from a parsed invoice. `selections` is
    a list of `{matchedProductId, applyPrice (bool), applyCost (bool), priceOverride}`."""
    inv = await db.invoices.find_one({"$and": [{"id": invoice_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not inv or not tenant_owns_strict(inv.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Invoice not found")
    selections = {s.get("matchedProductId"): s for s in (data.get("selections") or []) if s.get("matchedProductId")}
    updated, audit = 0, []
    for m in inv["matches"]:
        pid = m.get("matchedProductId")
        if not pid: continue
        sel = selections.get(pid)
        if not sel: continue
        upd = {}
        if sel.get("applyCost") and m.get("newCost") is not None:
            upd["cost"] = float(m["newCost"])
        if sel.get("applyPrice"):
            new_price = sel.get("priceOverride") or m.get("suggestedPrice")
            if new_price: upd["price"] = float(new_price)
        if not upd: continue
        # Defense in depth: parse-invoice already scopes its product match to
        # this business's own catalogue, but re-checking ownership here means
        # a crafted request can't reprice another business's product even if
        # it somehow got a matchedProductId that isn't really this business's.
        product = await db.products.find_one({"$and": [{"id": pid}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "id": 1, "businessId": 1})
        if product is None or not tenant_owns_strict(product.get("businessId"), user.get("businessId")):
            continue
        upd["updatedAt"] = datetime.utcnow().isoformat()
        await db.products.update_one({"$and": [{"id": pid}, tenant_scope_filter(user.get("businessId"))]}, {"$set": upd})
        audit.append({
            "productId": pid, "name": m.get("matchedProductName"),
            "from": {"price": m.get("currentPrice"), "cost": m.get("currentCost")},
            "to": {"price": upd.get("price"), "cost": upd.get("cost")},
        })
        updated += 1
    await db.invoices.update_one(
        {"$and": [{"id": invoice_id}, tenant_scope_filter(user.get("businessId"))]},
        {"$set": {"applied": True, "appliedAt": datetime.utcnow().isoformat(),
                  "appliedBy": user["id"], "audit": audit, "updatedCount": updated}},
    )
    return {"updated": updated, "audit": audit}


@router.get("/ai-pantry/invoices")
async def list_invoices(user: dict = Depends(require_owner_or_manager)):
    q = tenant_scope_filter(user.get("businessId"))
    rows = await db.invoices.find(q, {"_id": 0}).sort("uploadedAt", -1).to_list(50)
    return rows


# ============================================================================
# PRODUCT INSIGHTS — weekly sales + margin (for the dashboard tiles)
# ============================================================================
@router.get("/products/insights")
async def product_insights(user: dict = Depends(get_user)):
    """Returns per-product weekly sales count and margin %, for use as
    colour-coded badges on the Items dashboard."""
    if user["role"] not in ("owner", "manager", "cashier", "kitchen"):
        raise HTTPException(status_code=403, detail="Staff only")
    biz_scope = tenant_scope_filter(user.get("businessId"))
    now = datetime.now()
    week_ago = (now - __import__("datetime").timedelta(days=7)).isoformat()
    txns = await db.transactions.find(
        {"createdAt": {"$gte": week_ago}, **biz_scope}, {"_id": 0, "items": 1}).to_list(5000)
    sold = {}
    for t in txns:
        for it in t.get("items", []) or []:
            pid = it.get("productId") or it.get("id")
            sold[pid] = sold.get(pid, 0) + int(it.get("quantity", 0))
    products = await db.products.find(biz_scope, {"_id": 0}).to_list(2000)
    rows = []
    for p in products:
        price = float(p.get("price", 0) or 0)
        cost = float(p.get("cost", 0) or 0)
        margin_amt = max(0, price - cost)
        margin_pct = (margin_amt / price * 100) if price > 0 else 0
        rows.append({
            "productId": p["id"], "name": p["name"], "category": p.get("category"),
            "weeklyUnitsSold": sold.get(p["id"], 0),
            "weeklyRevenue": round(sold.get(p["id"], 0) * price, 2),
            "marginAmount": round(margin_amt, 2),
            "marginPct": round(margin_pct, 1),
        })
    return rows
