from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime
from database import db
from deps import get_user
import logging
import uuid

router = APIRouter()

# ============ TABLE-SIDE ORDERING API ============
#
# Tenant resolution: an optional `business` query param (same slug-or-id
# convention as routes/public.py and routes/online_orders.py's public
# storefronts — see routes/online_orders.py's _resolve_business_id
# docstring) scopes the menu/order/status lookups to a real business.
# GET /tables/qr-codes (staff-facing, below) embeds the caller's own
# business slug into every QR code URL it generates, so a freshly-
# generated/reprinted QR code is properly scoped once scanned; an
# existing QR code printed before this change has no ?business= param and
# keeps today's exact behavior (pooled across every business on the
# deployment) until it's regenerated. _table_tenant_filter deliberately
# does NOT fall back to the actor context for a missing/unresolved
# business the way middleware.actor_context.tenant_scope_filter does —
# every route here is genuinely anonymous (QR scan, no JWT), and that
# fallback reads ActorContextMiddleware's context, which for a request
# with no JWT is populated from the client-supplied X-Tenant-Id/
# X-Business-Id headers. Trusting that here would let an anonymous caller
# steer which business's menu/orders a "no ?business=" request reads or
# writes — see routes/public.py's _public_tenant_filter, the same fix
# applied there.


def _table_tenant_filter(business_id: Optional[str]) -> dict:
    from middleware.actor_context import tenant_scope_filter
    return tenant_scope_filter(business_id or "")



@router.get("/table/{table_id}/menu")
async def get_table_menu(table_id: str, business: Optional[str] = None):
    """Get menu for a specific table (public endpoint for QR scan)"""
    from routes.online_orders import _resolve_business_id
    business_id = await _resolve_business_id(business)
    biz_filter = _table_tenant_filter(business_id)

    products = await db.products.find({"stock": {"$gt": 0}, **biz_filter}, {"_id": 0}).to_list(1000)
    categories = {}
    for p in products:
        cat = p.get("category", "Other")
        if cat not in categories:
            categories[cat] = {"name": cat, "items": []}
        categories[cat]["items"].append({
            "id": p["id"], "name": p["name"], "price": p.get("price", 0),
            "description": p.get("description", ""),
            "image": p.get("image", ""),
            "dietary": p.get("dietary", []),
            "allergens": p.get("allergens", []),
            "translations": p.get("translations", {}),
        })
    # Get table info
    table_info = None
    floor_plans = await db.floor_plans.find(biz_filter, {"_id": 0}).to_list(10)
    for fp in floor_plans:
        for t in fp.get("tables", []):
            if t.get("id") == table_id:
                table_info = {"id": t["id"], "number": t.get("number", ""), "section": t.get("section", "")}
                break
    return {
        "tableId": table_id,
        "tableInfo": table_info,
        "categories": list(categories.values()),
        "restaurantName": "NUA",
    }

@router.post("/table/{table_id}/order")
async def place_table_order(table_id: str, data: dict, business: Optional[str] = None):
    """Place an order from a table (customer-initiated)"""
    from routes.online_orders import _resolve_business_id
    business_id = await _resolve_business_id(business or data.get("business"))
    biz_filter = _table_tenant_filter(business_id)

    items = data.get("items", [])
    customer_name = data.get("customerName", "Table Guest")
    notes = data.get("notes", "")

    if not items:
        raise HTTPException(status_code=400, detail="No items in order")

    # Build kitchen order items
    kitchen_items = []
    subtotal = 0
    for item in items:
        product = await db.products.find_one({"id": item["productId"], **biz_filter}, {"_id": 0})
        if not product:
            continue
        qty = item.get("quantity", 1)
        price = product.get("price", 0)
        kitchen_items.append({
            "productId": product["id"], "name": product["name"],
            # Coursing maps categories to courses, and the docket reads
            # productName — without both, a QR order lands entirely on the
            # default course and prints without a name on some paths.
            "productName": product["name"],
            "category": product.get("category") or "Other",
            "quantity": qty, "price": price,
            "modifications": item.get("modifications", ""),
        })
        subtotal += price * qty

    # Get table number
    table_number = table_id
    floor_plans = await db.floor_plans.find(biz_filter, {"_id": 0}).to_list(10)
    for fp in floor_plans:
        for t in fp.get("tables", []):
            if t.get("id") == table_id:
                table_number = t.get("number", table_id)
                break

    # Create kitchen order
    order_id = f"TORD-{str(uuid.uuid4())[:8].upper()}"
    order_doc = {
        "id": order_id,
        "tableId": table_id,
        "tableNumber": table_number,
        "businessId": business_id,
        "items": kitchen_items,
        "customerName": customer_name,
        "notes": notes,
        "source": "table_qr",
        "status": "new",
        # Menu prices are GST-inclusive — total is the subtotal itself, GST is
        # the disclosed component within it, not an amount added on top.
        "subtotal": round(subtotal, 2),
        "gst": round(subtotal / 11, 2),
        "total": round(subtotal, 2),
        "createdAt": datetime.utcnow().isoformat(),
        "priority": "normal",
    }
    # A QR table order is a dine-in order like any other, so it goes through
    # the same coursing rules the POS uses. Without this a QR table could
    # never be coursed — the items arrived with no course at all.
    try:
        from services import coursing as _coursing
        _cfg = await _coursing.get_config(business_id=business_id)
        order_doc["items"] = [{**i, "round": 1}
                              for i in _coursing.assign_courses(order_doc["items"], _cfg)]
        order_doc["courses"] = _coursing.initial_course_states(
            order_doc["items"], _cfg, "dine_in",
            straight_fire=False, fired_by="QR order",
            now=order_doc["createdAt"],
        )
        order_doc["orderType"] = "dine_in"
    except Exception as _e:
        logging.getLogger(__name__).warning("QR order: coursing skipped — %s", _e)

    await db.kitchen_orders.insert_one(order_doc)
    order_doc.pop("_id", None)

    # Update table status
    for fp in floor_plans:
        for t in fp.get("tables", []):
            if t.get("id") == table_id:
                t["status"] = "occupied"
                await db.floor_plans.update_one(
                    {"id": fp["id"]}, {"$set": {"tables": fp["tables"]}}
                )
                break

    return {
        "orderId": order_id,
        "tableNumber": table_number,
        # The stored items, not the pre-coursing list — otherwise the guest's
        # own screen shows no courses while the kitchen ticket has them.
        "items": order_doc["items"],
        "courses": order_doc.get("courses") or {},
        "subtotal": order_doc["subtotal"],
        "gst": order_doc["gst"],
        "total": order_doc["total"],
        "status": "new",
        "message": "Order placed! Your food is being prepared.",
    }

@router.get("/table/{table_id}/orders")
async def get_table_orders(table_id: str, business: Optional[str] = None):
    """Get active orders for a table"""
    from routes.online_orders import _resolve_business_id
    business_id = await _resolve_business_id(business)
    orders = await db.kitchen_orders.find(
        {"tableId": table_id, "status": {"$in": ["new", "preparing", "ready"]}, **_table_tenant_filter(business_id)},
        {"_id": 0}
    ).sort("createdAt", -1).to_list(50)
    return orders

@router.get("/table/order/{order_id}/status")
async def get_order_status(order_id: str, business: Optional[str] = None):
    """Check status of a specific order.

    order_id (TORD-<8 hex chars>, only ever handed back to the guest who
    placed that exact order — see place_table_order's response) is
    already the real access-control primitive here, the same
    possession-implies-authorization model this codebase already uses for
    Stripe/Coinbase session ids and split-bill line ids. `business` is
    accepted for symmetry with the rest of this router but only narrows an
    already-specific lookup further — a resolved business that doesn't
    own this order_id 404s exactly like an unknown order_id would, rather
    than silently ignoring the mismatch."""
    from routes.online_orders import _resolve_business_id
    business_id = await _resolve_business_id(business)
    order = await db.kitchen_orders.find_one({"id": order_id, **_table_tenant_filter(business_id)}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return {
        "orderId": order["id"],
        "status": order["status"],
        "items": order.get("items", []),
        "total": order.get("total", 0),
        "createdAt": order.get("createdAt"),
        "startedAt": order.get("startedAt"),
        "readyAt": order.get("readyAt"),
    }

# ============ TABLE QR CODE GENERATION (Staff) ============
@router.get("/tables/qr-codes")
async def get_table_qr_codes(user: dict = Depends(get_user)):
    """Generate QR code data for all tables.

    Was reachable by any authenticated user regardless of business (no
    Depends at all — the module-level auth middleware still required a
    valid token, since this path isn't in server.py's public allowlist,
    but any logged-in staff member at any business could see every other
    business's floor plan/table layout). Now scoped to the caller's own
    business, and the business slug is embedded in `businessSlug` so a
    caller building the actual QR-code URL can append `?business=<slug>`
    and get a properly-scoped table_id/menu/order flow once it's scanned."""
    from middleware.actor_context import tenant_scope_filter
    business_id = user.get("businessId")
    biz = await db.businesses.find_one({"id": business_id}, {"_id": 0, "slug": 1}) if business_id else None
    business_slug = biz.get("slug") if biz else None
    floor_plans = await db.floor_plans.find(tenant_scope_filter(business_id), {"_id": 0}).to_list(10)
    tables = []
    for fp in floor_plans:
        for t in fp.get("tables", []):
            tables.append({
                "tableId": t.get("id"),
                "number": t.get("number", ""),
                "section": t.get("section", ""),
                "status": t.get("status", "available"),
                "businessSlug": business_slug,
            })
    return tables
