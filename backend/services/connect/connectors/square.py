"""Square connector — the flagship, fully-built NUA Connect provider.

Built directly against Square's real, documented REST API
(https://developer.squareup.com/reference/square):
  - GET  /v2/locations                 connection test
  - POST /v2/catalog/search            inbound catalog sync -> db.products
  - POST /v2/orders/search             inbound sale sync (line items)
  - GET  /v2/payments                  inbound sale sync (tender/total)
  - POST /v2/customers/search          inbound customer sync -> db.customers
  - Webhook signature verification per
    https://developer.squareup.com/docs/webhooks/step3validate
    (HMAC-SHA256 of notification-url + raw body, base64-encoded, header
    `x-square-hmacsha256-signature`).

This sandbox has no outbound network path to squareup.com (or any other
third-party host — confirmed via the proxy allowlist), so this connector is
verified by a mocked-httpx test suite (tests/inprocess/test_connect_square.py)
against realistic Square response payloads, not a live call. It is written
to Square's real endpoint shapes so it is ready to run the moment it has
real credentials and network access.
"""
import base64
import functools
import hashlib
import hmac
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from database import db
from services.connect.base import BaseConnector, ConnectorError
from services.connect.sync_log import SyncRun
from middleware.actor_context import tenant_scope_filter

logger = logging.getLogger(__name__)


def _translate_network_errors(fn):
    """A DNS failure, timeout, or blocked outbound connection is not a code
    bug — it's Square being unreachable — but left as a raw httpx exception
    it would surface as an unhandled 500 instead of the clean 502
    ConnectorError callers (and routes/integrations.py) expect."""
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except httpx.HTTPError as e:
            raise ConnectorError(f"Square request failed: {e}") from e
    return wrapper


SQUARE_VERSION = "2024-01-18"
BASE_URLS = {
    "sandbox": "https://connect.squareupsandbox.com",
    "production": "https://connect.squareup.com",
}


def _base_url(credentials: Dict[str, Any]) -> str:
    return BASE_URLS.get(credentials.get("environment", "sandbox"), BASE_URLS["sandbox"])


def _headers(credentials: Dict[str, Any]) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {credentials.get('accessToken', '')}",
        "Square-Version": SQUARE_VERSION,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


class SquareConnector(BaseConnector):
    slug = "square"
    name = "Square"
    capabilities = {"catalog", "sales", "customers", "webhook"}

    # ---------------------------------------------------------------- test
    @_translate_network_errors
    async def test_connection(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        if not credentials.get("accessToken"):
            raise ConnectorError("accessToken is required")
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{_base_url(credentials)}/v2/locations", headers=_headers(credentials))
        if r.status_code != 200:
            raise ConnectorError(f"Square rejected credentials: HTTP {r.status_code} {r.text[:300]}")
        body = r.json()
        locations = body.get("locations", [])
        if credentials.get("locationId"):
            locations = [l for l in locations if l.get("id") == credentials["locationId"]]
            if not locations:
                raise ConnectorError(f"locationId {credentials['locationId']} not found for this access token")
        return {"locations": [{"id": l.get("id"), "name": l.get("name")} for l in locations]}

    # ------------------------------------------------------------- catalog
    @_translate_network_errors
    async def sync_catalog(self, credentials: Dict[str, Any], business_id: str, run: SyncRun) -> None:
        cursor = None
        async with httpx.AsyncClient(timeout=20) as client:
            while True:
                body: Dict[str, Any] = {"object_types": ["ITEM"], "include_related_objects": False}
                if cursor:
                    body["cursor"] = cursor
                r = await client.post(f"{_base_url(credentials)}/v2/catalog/search",
                                       headers=_headers(credentials), json=body)
                if r.status_code != 200:
                    raise ConnectorError(f"catalog/search failed: HTTP {r.status_code} {r.text[:300]}")
                page = r.json()
                for obj in page.get("objects", []):
                    run.bump("fetched")
                    run.add_sample(obj)
                    await self._upsert_catalog_item(obj, business_id)
                cursor = page.get("cursor")
                if not cursor:
                    break

    async def _upsert_catalog_item(self, obj: Dict[str, Any], business_id: str) -> None:
        item = obj.get("item_data", {})
        variations = item.get("variations", [])
        # NUA products are single-priced rows; a multi-variation Square item
        # becomes one NUA product per variation, named "Item - Variation"
        # (or just "Item" if there's exactly one, unnamed/default variation).
        for v in variations:
            vdata = v.get("item_variation_data", {})
            price_money = vdata.get("price_money", {}) or {}
            price = round((price_money.get("amount") or 0) / 100, 2)
            name = item.get("name", "Untitled")
            vname = vdata.get("name")
            if vname and vname.lower() not in ("regular", "default"):
                name = f"{name} - {vname}"
            doc = {
                "name": name,
                "category": (item.get("category_id") or "Square Import"),
                "price": price,
                "sku": vdata.get("sku", "") or "",
                "description": item.get("description", "") or "",
                "active": not obj.get("is_deleted", False),
                "updatedAt": datetime.now(timezone.utc),
            }
            existing = await db.products.find_one({"externalRefs.square": obj.get("id"), **tenant_scope_filter(business_id)}, {"_id": 0, "id": 1})
            if existing:
                await db.products.update_one(
                    {"id": existing["id"], **tenant_scope_filter(business_id)},
                    {"$set": {**doc, "externalRefs.square": obj.get("id")}},
                )
            else:
                import uuid
                new_id = str(uuid.uuid4())
                await db.products.insert_one({
                    "id": new_id, "businessId": business_id, "cost": 0.0, "stock": 0, "gstRate": 10.0,
                    "modifiers": [], "modifierIds": [], "locations": ["Main"],
                    "onlineChannels": [], "seoDescription": "", "allergens": [], "dietary": [],
                    "translations": {}, "eightySixed": False, "image": "",
                    "createdAt": datetime.now(timezone.utc),
                    "externalRefs": {"square": obj.get("id")},
                    **doc,
                })

    # --------------------------------------------------------------- sales
    @_translate_network_errors
    async def sync_sales(self, credentials: Dict[str, Any], business_id: str, run: SyncRun,
                          since: Optional[str] = None) -> None:
        location_id = credentials.get("locationId")
        if not location_id:
            raise ConnectorError("locationId is required to sync sales")
        since = since or "2000-01-01T00:00:00Z"
        cursor = None
        async with httpx.AsyncClient(timeout=20) as client:
            while True:
                body: Dict[str, Any] = {
                    "location_ids": [location_id],
                    "query": {
                        "filter": {"date_time_filter": {"closed_at": {"start_at": since}}},
                        "sort": {"sort_field": "CLOSED_AT", "sort_order": "ASC"},
                    },
                    "limit": 100,
                }
                if cursor:
                    body["cursor"] = cursor
                r = await client.post(f"{_base_url(credentials)}/v2/orders/search",
                                       headers=_headers(credentials), json=body)
                if r.status_code != 200:
                    raise ConnectorError(f"orders/search failed: HTTP {r.status_code} {r.text[:300]}")
                page = r.json()
                for order in page.get("orders", []):
                    if order.get("state") != "COMPLETED":
                        run.bump("skipped")
                        continue
                    run.bump("fetched")
                    run.add_sample(order)
                    await self._ingest_order(order, business_id, run)
                cursor = page.get("cursor")
                if not cursor:
                    break

    async def _ingest_order(self, order: Dict[str, Any], business_id: str, run: SyncRun) -> None:
        from services.sale_recorder import (
            compute_points_earned, credit_loyalty_points, record_sale_side_effects,
        )

        order_id = order.get("id")
        existing = await db.transactions.find_one({"externalRefs.square": order_id}, {"_id": 0, "id": 1})
        if existing:
            run.bump("skipped")
            return

        line_items = order.get("line_items", [])
        items_list = []
        subtotal = 0.0
        earn_lines: List[tuple] = []
        for li in line_items:
            qty = float(li.get("quantity", "1"))
            total_money = (li.get("total_money", {}) or {}).get("amount", 0) / 100
            unit_price = round(total_money / qty, 2) if qty else 0.0
            product = await db.products.find_one(
                {"externalRefs.square": li.get("catalog_object_id"), **tenant_scope_filter(business_id)}, {"_id": 0, "id": 1, "category": 1},
            )
            items_list.append({
                "productId": (product or {}).get("id", li.get("catalog_object_id") or "unknown"),
                "productName": li.get("name", "Item"),
                "quantity": int(qty),
                "price": unit_price,
                "total": round(total_money, 2),
                "modifiers": [],
            })
            subtotal += total_money
            earn_lines.append(((product or {}).get("category") or "Other", total_money))

        total_money_obj = order.get("total_money", {}) or {}
        total = round((total_money_obj.get("amount") or 0) / 100, 2)

        customer_id = None
        square_customer_id = order.get("customer_id")
        if square_customer_id:
            cust = await db.customers.find_one({**tenant_scope_filter(business_id), "externalRefs.square": square_customer_id}, {"_id": 0, "id": 1})
            customer_id = (cust or {}).get("id")

        from services.tenant_settings import get_scoped_singleton
        loyalty_cfg = await get_scoped_singleton(db.loyalty_config, {"id": "default"}, business_id) or {}
        loyalty_multiplier = 1.0
        if customer_id:
            customer = await db.customers.find_one({**tenant_scope_filter(business_id), "id": customer_id}, {"_id": 0, "membershipTier": 1})
            if customer:
                tier_doc = await db.loyalty_tiers.find_one(
                    {"$and": [tenant_scope_filter(business_id), {"name": customer.get("membershipTier", "Bronze")}]},
                    {"_id": 0},
                )
                loyalty_multiplier = float((tier_doc or {}).get("multiplier", 1.0))
        points_earned = compute_points_earned(subtotal, total, loyalty_multiplier, earn_lines, loyalty_cfg)

        gst = round(total / 11, 2)
        import uuid
        txn_dict = {
            "id": f"TXN-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}",
            "items": items_list,
            "subtotal": round(subtotal, 2),
            "discount": 0.0,
            "discountAmount": 0.0,
            "appliedDiscounts": [],
            "pointsRedeemed": 0,
            "pointsDiscount": 0.0,
            "splitDetails": [],
            "surchargeAmount": 0.0,
            "surchargePercent": 0.0,
            "surchargeReason": None,
            "gratuityAmount": 0.0,
            "gratuityPercent": 0.0,
            "gratuityLabel": None,
            "covers": None,
            "gst": gst,
            "total": total,
            "paymentMethod": "square",
            "customerId": customer_id,
            "location": "Square",
            "cashier": "Square Sync",
            "timestamp": datetime.utcnow(),
            "status": "completed",
            "receiptNumber": f"R-{uuid.uuid4().hex[:8].upper()}",
            "businessId": business_id,
            "externalRefs": {"square": order_id},
            "source": "connect:square",
        }
        await db.transactions.insert_one(dict(txn_dict))
        run.bump("created")

        if customer_id:
            await credit_loyalty_points(customer_id, points_earned, total, txn_dict["id"], business_id=business_id)
        await record_sale_side_effects(txn_dict, memo=f"Square sale synced (order {order_id})")

    # ----------------------------------------------------------- customers
    @_translate_network_errors
    async def sync_customers(self, credentials: Dict[str, Any], business_id: str, run: SyncRun) -> None:
        cursor = None
        async with httpx.AsyncClient(timeout=20) as client:
            while True:
                body: Dict[str, Any] = {"limit": 100}
                if cursor:
                    body["cursor"] = cursor
                r = await client.post(f"{_base_url(credentials)}/v2/customers/search",
                                       headers=_headers(credentials), json=body)
                if r.status_code != 200:
                    raise ConnectorError(f"customers/search failed: HTTP {r.status_code} {r.text[:300]}")
                page = r.json()
                for c in page.get("customers", []):
                    run.bump("fetched")
                    run.add_sample(c)
                    await self._upsert_customer(c, business_id)
                cursor = page.get("cursor")
                if not cursor:
                    break

    async def _upsert_customer(self, c: Dict[str, Any], business_id: str) -> None:
        email = c.get("email_address") or f"square-{c.get('id')}@no-email.nua"
        phone = c.get("phone_number") or ""
        name = " ".join(filter(None, [c.get("given_name"), c.get("family_name")])) or "Square Customer"
        doc = {"name": name, "email": email, "phone": phone}
        # externalRefs.square alone (with no businessId in the match filter)
        # let a repeated sync for one business match — and silently take
        # over — a customer imported by ANY OTHER business that happened to
        # reuse the same Square customer id (a real risk: Square ids are
        # global, not scoped to the merchant account that imported them
        # into this app). Both the lookup and the newly-created row are now
        # scoped to the business running this sync.
        existing = await db.customers.find_one(
            {**tenant_scope_filter(business_id), "externalRefs.square": c.get("id"), "businessId": business_id}, {"_id": 0, "id": 1})
        if existing:
            await db.customers.update_one(
                {**tenant_scope_filter(business_id), "id": existing["id"]},
                {"$set": {**doc, "externalRefs.square": c.get("id")}},
            )
        else:
            import uuid
            await db.customers.insert_one({
                "id": str(uuid.uuid4()), "membershipTier": "Bronze", "totalSpent": 0.0,
                "visits": 0, "points": 0, "dietaryRestrictions": [], "allergies": [],
                "favoriteDishes": [], "tags": ["square-import"], "isVip": False, "notes": "",
                "noShowCount": 0, "avgSpendPerVisit": 0.0, "feedbackRating": 0.0,
                "feedbackCount": 0, "reservationIds": [], "storeCredit": 0.0,
                "joinDate": datetime.now(timezone.utc),
                "externalRefs": {"square": c.get("id")},
                "businessId": business_id,
                **doc,
            })

    # ------------------------------------------------------------- webhook
    def verify_webhook(self, body: bytes, headers: Dict[str, str], credentials: Dict[str, Any]) -> bool:
        """Per Square's documented scheme: HMAC-SHA256(signature_key,
        notification_url + body), base64-encoded, compared to the
        `x-square-hmacsha256-signature` header. notification_url is the
        exact URL Square was configured to POST to — stored alongside the
        signature key at connect time (webhookNotificationUrl)."""
        signature_key = credentials.get("webhookSignatureKey", "")
        notification_url = credentials.get("webhookNotificationUrl", "")
        received = headers.get("x-square-hmacsha256-signature") or headers.get("Square-Signature", "")
        if not signature_key or not received:
            return False
        payload = notification_url.encode("utf-8") + body
        expected = base64.b64encode(
            hmac.new(signature_key.encode("utf-8"), payload, hashlib.sha256).digest()
        ).decode("utf-8")
        return hmac.compare_digest(expected, received)

    @_translate_network_errors
    async def handle_webhook_event(self, event: Dict[str, Any], business_id: str, run: SyncRun) -> None:
        event_type = event.get("type", "")
        run.add_sample(event)
        run.bump("fetched")
        credentials_provider = None
        from services.connect.credentials import get_credentials
        credentials = await get_credentials(business_id, "square")
        if not credentials:
            run.bump("skipped")
            return
        if event_type.startswith("order."):
            order = (event.get("data", {}).get("object", {}) or {}).get("order")
            if order and order.get("state") == "COMPLETED":
                await self._ingest_order(order, business_id, run)
            else:
                run.bump("skipped")
        elif event_type.startswith("customer."):
            customer = (event.get("data", {}).get("object", {}) or {}).get("customer")
            if customer:
                await self._upsert_customer(customer, business_id)
                run.bump("updated")
        elif event_type.startswith("catalog."):
            # Catalog webhooks only carry the changed object id — re-fetch it.
            obj_id = (event.get("data", {}).get("id"))
            if obj_id:
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.get(f"{_base_url(credentials)}/v2/catalog/object/{obj_id}",
                                          headers=_headers(credentials))
                if r.status_code == 200:
                    obj = r.json().get("object")
                    if obj:
                        await self._upsert_catalog_item(obj, business_id)
                        run.bump("updated")
        else:
            run.bump("skipped")
