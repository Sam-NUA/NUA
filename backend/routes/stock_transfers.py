"""Stock transfers between locations for multi-location retailers.

A product's flat `stock` field (and the whole checkout/purchase-order/
stockout-prediction pipeline that reads it) stays untouched — this is an
additive, opt-in layer. A business that never uses transfers never
populates `stockByLocation` and nothing here affects them.

Modeled as two steps rather than one atomic move: `in_transit` (stock
already left the source, hasn't arrived yet) then `received` (confirmed
landed at the destination). Real inter-location transfers take hours or
days — collapsing that into one instant swap would just be wrong for how
retailers actually move stock, and it drops the "did this actually show
up" confirmation step that catches a shipment that went missing.
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel
import uuid

from database import db
from services import consistency_store
from deps import require_owner_or_manager
from middleware.actor_context import tenant_scope_filter, tenant_owns_strict

router = APIRouter()


class StockTransferCreate(BaseModel):
    productId: str
    fromLocation: str
    toLocation: str
    quantity: int
    notes: Optional[str] = ""


class StockTransfer(BaseModel):
    id: str
    productId: str
    productName: str
    fromLocation: str
    toLocation: str
    quantity: int
    status: str  # in_transit | received | cancelled
    notes: str = ""
    requestedBy: Optional[str] = None
    requestedByName: Optional[str] = None
    requestedAt: str
    receivedAt: Optional[str] = None
    businessId: Optional[str] = None


@router.post("/stock-transfers", response_model=StockTransfer)
async def create_transfer(data: StockTransferCreate, user: dict = Depends(require_owner_or_manager)):
    if data.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")
    if data.fromLocation == data.toLocation:
        raise HTTPException(status_code=400, detail="Source and destination must differ")

    async def operation(session):
        product = await db.products.find_one({"$and": [{"id": data.productId}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0}, session=session)
        if not product or not tenant_owns_strict(product.get("businessId"), user.get("businessId")):
            raise HTTPException(status_code=404, detail="Product not found")

        stock_by_loc = product.get("stockByLocation") or {}
        available = stock_by_loc.get(data.fromLocation, 0)
        if available < data.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Only {available} unit(s) of {product.get('name')} at {data.fromLocation}",
            )

        # Atomic guard: only decrements if the source still has enough at the
        # moment of the write, not just when we read it a moment ago — two
        # transfers requested for the last few units at once can't both succeed.
        field = f"stockByLocation.{data.fromLocation}"
        result = await db.products.update_one(
            {"$and": [{"id": data.productId, field: {"$gte": data.quantity}}, tenant_scope_filter(user.get("businessId"))]},
            {"$inc": {field: -data.quantity}}, session=session,
        )
        if result.modified_count == 0:
            raise HTTPException(status_code=409, detail="Stock changed — retry the transfer")

        now_iso = datetime.now(timezone.utc).isoformat()
        transfer = {
            "id": f"XFER-{str(uuid.uuid4())[:8].upper()}",
            "productId": data.productId,
            "productName": product.get("name", ""),
            "fromLocation": data.fromLocation,
            "toLocation": data.toLocation,
            "quantity": data.quantity,
            "status": "in_transit",
            "notes": data.notes or "",
            "requestedBy": user.get("id"),
            "requestedByName": user.get("name"),
            "requestedAt": now_iso,
            "receivedAt": None,
            "businessId": user.get("businessId"),
        }
        await db.stock_transfers.insert_one(dict(transfer), session=session)
        transfer.pop("_id", None)
        return transfer

    return await consistency_store.stock_change(operation)


@router.get("/stock-transfers", response_model=List[StockTransfer])
async def list_transfers(status: Optional[str] = None, productId: Optional[str] = None,
                          user: dict = Depends(require_owner_or_manager)):
    query: dict = {}
    tenant_filter = tenant_scope_filter(user.get("businessId"))
    and_clauses = [tenant_filter] if tenant_filter else []
    if status:
        and_clauses.append({"status": status})
    if productId:
        and_clauses.append({"productId": productId})
    if and_clauses:
        query["$and"] = and_clauses
    rows = await db.stock_transfers.find(query).sort("requestedAt", -1).to_list(1000)
    return [StockTransfer(**r) for r in rows]


async def _finish_transfer(transfer_id, status, user):
    scope = tenant_scope_filter(user.get("businessId"))

    async def operation(session):
        transfer = await db.stock_transfers.find_one(
            {"id": transfer_id, **scope}, {"_id": 0}, session=session)
        if not transfer or not tenant_owns_strict(transfer.get("businessId"), user.get("businessId")):
            raise HTTPException(404, "Transfer not found")
        if transfer["status"] != "in_transit":
            raise HTTPException(400, f"Transfer is already {transfer['status']}")
        location = transfer['toLocation'] if status == 'received' else transfer['fromLocation']
        result = await db.products.update_one(
            {"id": transfer["productId"], **scope},
            {"$inc": {f"stockByLocation.{location}": transfer["quantity"]}}, session=session)
        if result.matched_count == 0:
            raise HTTPException(404, "Product not found")
        changes = {"status": status}
        if status == "received":
            changes["receivedAt"] = datetime.now(timezone.utc).isoformat()
        changed = await db.stock_transfers.find_one_and_update(
            {"id": transfer_id, "status": "in_transit", **scope},
            {"$set": changes}, return_document=True, session=session)
        if not changed:
            raise HTTPException(409, "Transfer changed; retry")
        return StockTransfer(**changed)

    return await consistency_store.stock_change(operation)


@router.post("/stock-transfers/{transfer_id}/receive", response_model=StockTransfer)
async def receive_transfer(transfer_id: str, user: dict = Depends(require_owner_or_manager)):
    return await _finish_transfer(transfer_id, "received", user)


@router.post("/stock-transfers/{transfer_id}/cancel", response_model=StockTransfer)
async def cancel_transfer(transfer_id: str, user: dict = Depends(require_owner_or_manager)):
    """Cancel an in-transit transfer and return its stock to the source."""
    return await _finish_transfer(transfer_id, "cancelled", user)
