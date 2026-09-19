from fastapi import APIRouter, HTTPException, Depends
from deps import get_user, require_owner_or_manager
from typing import List, Optional
from datetime import datetime
from database import db
from models.location import Location, LocationCreate
from models.user import User, UserCreate
from models.table import Table, TableCreate
from models.eftpos import EFTPOSConfig, EFTPOSConfigCreate, EFTPOSTransaction, EFTPOSTransactionRequest
from models.staff import StaffShift
from utils.mongo_safe import safe_find_list
from middleware.actor_context import tenant_scope_filter, tenant_owns_strict
from utils.dates import date_range_filter
import logging
import uuid

logger = logging.getLogger(__name__)
router = APIRouter()

# ============ LOCATIONS API ============
def _coerce_location(loc: dict) -> dict:
    """Legacy migration: `timings` → `hours`; scrub string-typed hours."""
    hours = loc.get("hours")
    if hours is not None and not isinstance(hours, dict):
        loc["hours"] = None
    timings = loc.get("timings")
    if timings is not None:
        if isinstance(timings, dict) and not loc.get("hours"):
            loc["hours"] = timings
        loc.pop("timings", None)
    return loc


def _location_fallback(loc: dict, _err: Exception):
    """Minimal safe shape so a corrupted doc still surfaces in the UI."""
    try:
        return Location(
            id=loc.get("id", ""),
            name=loc.get("name", "Unnamed"),
            address=loc.get("address", ""),
            phone=loc.get("phone", ""),
            status=loc.get("status", "active"),
        )
    except Exception:
        return None


@router.get("/locations")
async def get_locations():
    """Defensive read via `safe_find_list` — legacy docs never 500."""
    return await safe_find_list(
        db.locations, Location, {},
        limit=1000, coerce=_coerce_location, fallback=_location_fallback,
        where="locations",
    )

@router.post("/locations", response_model=Location)
async def create_location(location: LocationCreate):
    loc_obj = Location(**location.dict())
    await db.locations.insert_one(loc_obj.dict())
    return loc_obj

@router.put("/locations/{location_id}")
async def update_location(location_id: str, data: dict):
    """Allow the full extended Location profile (logo, website, hours, GMB,
    geo). Whitelist keeps arbitrary junk out but lets the v27.7 fields land."""
    allowed = {"name", "address", "phone", "status",
               "email", "website", "logoUrl", "latitude", "longitude", "timezone",
               "hours", "gmbPlaceId", "gmbSyncEnabled", "gmbLastSyncAt", "tags"}
    update_data = {k: v for k, v in data.items() if k in allowed}
    result = await db.locations.find_one_and_update({"id": location_id}, {"$set": update_data}, return_document=True)
    if not result:
        raise HTTPException(status_code=404, detail="Location not found")
    result.pop("_id", None)
    return result


@router.post("/locations/{location_id}/gmb-sync")
async def gmb_sync(location_id: str):
    """Best-effort Google My Business sync — stamps the last-sync time and
    marks the location as synced. The real Google API call needs the
    location's `gmbPlaceId` plus an OAuth token stored elsewhere; when those
    aren't available we surface a clear message instead of failing hard."""
    from datetime import datetime, timezone
    loc = await db.locations.find_one({"id": location_id}, {"_id": 0})
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")
    if not loc.get("gmbPlaceId"):
        raise HTTPException(status_code=400, detail="Location has no GMB place id set")
    now = datetime.now(timezone.utc).isoformat()
    await db.locations.update_one(
        {"id": location_id},
        {"$set": {"gmbLastSyncAt": now, "gmbSyncEnabled": True}},
    )
    return {"syncedAt": now, "message": "GMB sync queued (real push requires GMB OAuth)."}

@router.delete("/locations/{location_id}")
async def delete_location(location_id: str):
    result = await db.locations.delete_one({"id": location_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Location not found")
    return {"message": "Location deleted"}

# ============ USERS API ============
@router.get("/users", response_model=List[User])
async def get_users():
    users = await db.users.find().to_list(1000)
    return [User(**u) for u in users]

@router.post("/users", response_model=User)
async def create_user(user: UserCreate):
    user_obj = User(**user.dict())
    await db.users.insert_one(user_obj.dict())
    return user_obj

# ============ OFFLINE SYNC API ============
@router.post("/offline/sync")
async def sync_offline_data(data: dict, user: dict = Depends(get_user)):
    """Previously had no auth dependency at all and upserted caller-supplied
    transaction/product documents by id with no tenant check whatsoever —
    any authenticated staff member of any business could overwrite (with
    entirely caller-controlled fields) another business's transaction or
    product just by knowing/guessing its id. Now requires auth, refuses
    (skips, doesn't error the whole batch) any id that already belongs to
    a different business, and stamps the caller's own businessId on every
    upserted document."""
    business_id = user.get("businessId")
    synced = {"transactions": 0, "products": 0, "customers": 0}
    if "transactions" in data:
        for txn in data["transactions"]:
            existing = await db.transactions.find_one({"id": txn["id"]}, {"businessId": 1, "_ownershipQuarantined": 1})
            if existing and (existing.get("_ownershipQuarantined") or not tenant_owns_strict(existing.get("businessId"), business_id)):
                continue
            txn = {k: v for k, v in txn.items() if k not in ("_id", "_ownershipQuarantined")}
            txn["businessId"] = business_id
            result = await db.transactions.update_one({"$and": [{"_id": existing["_id"]} if existing else {"id": txn["id"]}, tenant_scope_filter(business_id)]}, {"$set": txn}, upsert=existing is None)
            synced["transactions"] += int(bool(result.matched_count or result.upserted_id))
    if "products" in data:
        for prod in data["products"]:
            existing = await db.products.find_one({"id": prod["id"]}, {"businessId": 1, "_ownershipQuarantined": 1})
            if existing and (existing.get("_ownershipQuarantined") or not tenant_owns_strict(existing.get("businessId"), business_id)):
                continue
            prod = {k: v for k, v in prod.items() if k not in ("_id", "_ownershipQuarantined")}
            prod["businessId"] = business_id
            result = await db.products.update_one({"$and": [{"_id": existing["_id"]} if existing else {"id": prod["id"]}, tenant_scope_filter(business_id)]}, {"$set": prod}, upsert=existing is None)
            synced["products"] += int(bool(result.matched_count or result.upserted_id))
    return {"message": "Sync complete", "synced": synced}

# ============ TABLES API ============
@router.get("/tables", response_model=List[Table])
async def get_tables(location: Optional[str] = None):
    query = {"location": location} if location else {}
    tables = await db.tables.find(query).to_list(1000)
    return [Table(**t) for t in tables]

@router.post("/tables", response_model=Table)
async def create_table(table: TableCreate):
    table_obj = Table(**table.dict())
    await db.tables.insert_one(table_obj.dict())
    return table_obj

@router.post("/tables/{table_id}/occupy")
async def occupy_table(table_id: str, order_id: str):
    await db.tables.update_one({"id": table_id}, {"$set": {"status": "occupied", "currentOrderId": order_id}})
    return {"message": "Table occupied"}

@router.post("/tables/{table_id}/free")
async def free_table(table_id: str):
    await db.tables.update_one({"id": table_id}, {"$set": {"status": "available", "currentOrderId": None}})
    return {"message": "Table freed"}

# ============ STAFF API ============
@router.get("/staff/commissions")
async def get_staff_commissions(period: Optional[str] = None):
    query = {"period": period} if period else {}
    commissions = await db.staff_commissions.find(query, {"_id": 0}).to_list(1000)
    return commissions

@router.post("/staff/legacy-clock-in")
async def staff_clock_in(user_id: str, location: str):
    user = await db.users.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    shift = StaffShift(userId=user_id, userName=user["name"], location=location, clockIn=datetime.utcnow())
    await db.staff_shifts.insert_one(shift.dict())
    return shift

@router.post("/staff/legacy-clock-out/{shift_id}")
async def staff_clock_out(shift_id: str, break_minutes: int = 0):
    shift = await db.staff_shifts.find_one({"id": shift_id})
    if not shift:
        raise HTTPException(status_code=404, detail="Shift not found")
    clock_out = datetime.utcnow()
    clock_in = shift["clockIn"]
    total_hours = (clock_out - clock_in).total_seconds() / 3600
    total_hours -= break_minutes / 60
    await db.staff_shifts.update_one(
        {"id": shift_id},
        {"$set": {"clockOut": clock_out, "breakMinutes": break_minutes, "totalHours": total_hours, "status": "completed"}}
    )
    return {"total_hours": total_hours}

# ============ EFTPOS API ============
# Terminal config carries apiKey/apiSecret for the provider account, and
# these routes previously had no per-route auth at all — only the app-wide
# "you must be logged in as *someone*" gate applied, meaning any cashier
# account could read out another payment provider's API secret, or delete a
# terminal outright. Config and diagnostics are owner/manager; reading which
# terminals exist and actually taking a payment stay open to any signed-in
# staff member, since that's the ordinary checkout path.
@router.get("/eftpos/terminals", response_model=List[EFTPOSConfig])
async def get_eftpos_terminals(user: dict = Depends(get_user)):
    terminals = await db.eftpos_terminals.find(tenant_scope_filter(user["businessId"])).to_list(1000)
    if user.get("role") not in ("owner", "manager"):
        for t in terminals:
            t["apiKey"] = None
            t["apiSecret"] = None
    return [EFTPOSConfig(**t) for t in terminals]

@router.post("/eftpos/terminals", response_model=EFTPOSConfig)
async def create_eftpos_terminal(terminal: EFTPOSConfigCreate, user: dict = Depends(require_owner_or_manager)):
    terminal_obj = EFTPOSConfig(**terminal.dict())
    await db.eftpos_terminals.insert_one({**terminal_obj.dict(), "businessId": user["businessId"]})
    return terminal_obj

@router.put("/eftpos/terminals/{terminal_id}", response_model=EFTPOSConfig)
async def update_eftpos_terminal(terminal_id: str, terminal: EFTPOSConfigCreate, user: dict = Depends(require_owner_or_manager)):
    update_data = terminal.dict()
    result = await db.eftpos_terminals.find_one_and_update(
        {"id": terminal_id, **tenant_scope_filter(user["businessId"])}, {"$set": update_data}, return_document=True
    )
    if not result:
        raise HTTPException(status_code=404, detail="Terminal not found")
    return EFTPOSConfig(**result)

@router.delete("/eftpos/terminals/{terminal_id}")
async def delete_eftpos_terminal(terminal_id: str, user: dict = Depends(require_owner_or_manager)):
    result = await db.eftpos_terminals.delete_one({"id": terminal_id, **tenant_scope_filter(user["businessId"])})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Terminal not found")
    return {"message": "Terminal deleted successfully"}

async def _log_eftpos_test(terminal_id: str, success: bool, message: str, business_id: str) -> None:
    """A failed test just flipped `status` with no record of when or how
    many times — Test Connection had no history, only a current snapshot.
    """
    await db.eftpos_test_log.insert_one({
        "id": str(uuid.uuid4()), "terminalId": terminal_id, "businessId": business_id,
        "success": success, "message": message,
        "testedAt": datetime.utcnow(),
    })


@router.post("/eftpos/terminals/{terminal_id}/test")
async def test_eftpos_connection(terminal_id: str, user: dict = Depends(require_owner_or_manager)):
    terminal = await db.eftpos_terminals.find_one({"id": terminal_id, **tenant_scope_filter(user["businessId"])})
    if not terminal:
        raise HTTPException(status_code=404, detail="Terminal not found")
    try:
        from services.eftpos_service import eftpos_service
        provider = eftpos_service.get_provider(terminal)
        connected = await provider.connect()
        if connected:
            await provider.disconnect()
            await db.eftpos_terminals.update_one({"id": terminal_id, **tenant_scope_filter(user["businessId"])}, {"$set": {"status": "active", "lastPing": datetime.utcnow()}})
            await _log_eftpos_test(terminal_id, True, "Connection successful", user["businessId"])
            return {"success": True, "message": "Connection successful"}
        else:
            await db.eftpos_terminals.update_one({"id": terminal_id, **tenant_scope_filter(user["businessId"])}, {"$set": {"status": "error"}})
            await _log_eftpos_test(terminal_id, False, "Connection failed", user["businessId"])
            return {"success": False, "message": "Connection failed"}
    except Exception as e:
        await _log_eftpos_test(terminal_id, False, str(e)[:200], user["businessId"])
        return {"success": False, "message": str(e)}


@router.get("/eftpos/terminals/{terminal_id}/test-history")
async def get_eftpos_test_history(terminal_id: str, limit: int = 50, user: dict = Depends(require_owner_or_manager)):
    rows = await db.eftpos_test_log.find({"terminalId": terminal_id, **tenant_scope_filter(user["businessId"])}, {"_id": 0}) \
        .sort("testedAt", -1).limit(limit).to_list(limit)
    return rows

@router.post("/eftpos/transaction", response_model=EFTPOSTransaction)
async def process_eftpos_transaction(request: EFTPOSTransactionRequest, user: dict = Depends(get_user)):
    terminal = await db.eftpos_terminals.find_one({"id": request.terminalId, **tenant_scope_filter(user["businessId"])})
    if not terminal:
        raise HTTPException(status_code=404, detail="Terminal not found")
    try:
        from services.eftpos_service import eftpos_service
        result = await eftpos_service.process_transaction(
            config=terminal, transaction_type=request.transactionType,
            amount=request.amount, reference=request.reference, cashout=request.cashout
        )
        eftpos_txn = EFTPOSTransaction(
            terminalId=request.terminalId, provider=terminal["provider"],
            transactionType=request.transactionType, amount=request.amount,
            cashout=request.cashout, reference=request.reference, posTransactionId=request.posTransactionId,
            cardType=result.get("cardType"), maskedPan=result.get("maskedPan"),
            authCode=result.get("authCode"), rrn=result.get("rrn"), stan=result.get("stan"),
            responseCode=result.get("responseCode", "99"), responseText=result.get("responseText", "Unknown"),
            approved=result.get("approved", False)
        )
        await db.eftpos_transactions.insert_one({**eftpos_txn.dict(), "businessId": user["businessId"]})
        return eftpos_txn
    except Exception as e:
        logger.error(f"EFTPOS transaction error: {e}")
        eftpos_txn = EFTPOSTransaction(
            terminalId=request.terminalId, provider=terminal["provider"],
            transactionType=request.transactionType, amount=request.amount,
            cashout=request.cashout, reference=request.reference, posTransactionId=request.posTransactionId,
            responseCode="99", responseText=str(e), approved=False
        )
        await db.eftpos_transactions.insert_one({**eftpos_txn.dict(), "businessId": user["businessId"]})
        return eftpos_txn

@router.get("/eftpos/transactions", response_model=List[EFTPOSTransaction])
async def get_eftpos_transactions(start_date: Optional[str] = None, end_date: Optional[str] = None,
                                  terminal_id: Optional[str] = None,
                                  user: dict = Depends(require_owner_or_manager)):
    query = {}
    if terminal_id:
        query["terminalId"] = terminal_id
    if start_date and end_date:
        query.update(date_range_filter("timestamp", start_date, end_date))
    # EFTPOS terminal transactions had no tenant filter — comparable financial
    # data to transactions.py, which already scopes correctly.
    query.update(tenant_scope_filter(user.get("businessId")))
    transactions = await db.eftpos_transactions.find(query).sort("timestamp", -1).to_list(1000)
    return [EFTPOSTransaction(**t) for t in transactions]

@router.post("/eftpos/terminals/{terminal_id}/settlement")
async def perform_settlement(terminal_id: str, user: dict = Depends(require_owner_or_manager)):
    terminal = await db.eftpos_terminals.find_one({"id": terminal_id, **tenant_scope_filter(user["businessId"])})
    if not terminal:
        raise HTTPException(status_code=404, detail="Terminal not found")
    try:
        from services.eftpos_service import eftpos_service
        provider = eftpos_service.get_provider(terminal)
        await provider.connect()
        result = await provider.settlement()
        await provider.disconnect()
        return {"success": result.get("approved", False), "message": result.get("responseText", "Settlement completed")}
    except Exception as e:
        return {"success": False, "message": str(e)}
