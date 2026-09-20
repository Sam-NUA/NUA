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

    product = await db.products.find_one({"$and": [{"id": data.productId}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
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
        {"$inc": {field: -data.quantity}},
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
    await db.stock_transfers.insert_one(dict(transfer))
    transfer.pop("_id", None)
    return transfer


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


@router.post("/stock-transfers/{transfer_id}/receive", response_model=StockTransfer)
async def receive_transfer(transfer_id: str, user: dict = Depends(require_owner_or_manager)):
    transfer = await db.stock_transfers.find_one({"$and": [{"id": transfer_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not transfer or not tenant_owns_strict(transfer.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Transfer not found")
    if transfer["status"] != "in_transit":
        raise HTTPException(status_code=400, detail=f"Transfer is already {transfer['status']}")

    field = f"stockByLocation.{transfer['toLocation']}"
    await db.products.update_one({"id": transfer["productId"]}, {"$inc": {field: transfer["quantity"]}})

    now_iso = datetime.now(timezone.utc).isoformat()
    await db.stock_transfers.update_one(
        {"$and": [{"id": transfer_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": {"status": "received", "receivedAt": now_iso}},
    )
    updated = await db.stock_transfers.find_one({"$and": [{"id": transfer_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    return StockTransfer(**updated)


@router.post("/stock-transfers/{transfer_id}/cancel", response_model=StockTransfer)
async def cancel_transfer(transfer_id: str, user: dict = Depends(require_owner_or_manager)):
    """Cancels an in-transit transfer and returns the stock to its source —
    for a shipment that never actually left, or was requested by mistake."""
    transfer = await db.stock_transfers.find_one({"$and": [{"id": transfer_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not transfer or not tenant_owns_strict(transfer.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Transfer not found")
    if transfer["status"] != "in_transit":
        raise HTTPException(status_code=400, detail=f"Transfer is already {transfer['status']}")

    field = f"stockByLocation.{transfer['fromLocation']}"
    await db.products.update_one({"id": transfer["productId"]}, {"$inc": {field: transfer["quantity"]}})

    await db.stock_transfers.update_one({"$and": [{"id": transfer_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": {"status": "cancelled"}})
    updated = await db.stock_transfers.find_one({"$and": [{"id": transfer_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    return StockTransfer(**updated)
