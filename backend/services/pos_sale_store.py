"""Atomic POS point debits, redemption ledger and sale insert.

The driver retries transient transactions and unknown commit results. Never
compensate a network error with an unconditional refund: the commit might
already exist. Client retries must retain clientOpId. Other sale effects
(stock, earned points, provider payments) remain outside this boundary.
"""
import copy
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from database import client
from middleware.actor_context import tenant_scope_filter


async def _transaction(operation):
    # Fail closed on standalone MongoDB; never silently fall back to separate writes.
    async with await client.start_session() as session:
        return await session.with_transaction(
            operation, read_concern=ReadConcern("snapshot"),
            write_concern=WriteConcern("majority"))


async def insert_with_redemptions(database, sale, redemptions):
    """Return (persisted sale, newly inserted). redemptions: (customer, points, value)."""
    business_id = sale.get("businessId")
    if not business_id:
        raise HTTPException(400, "Business context required")
    scope = tenant_scope_filter(business_id)
    replay_filter = {**scope, "clientOpId": sale.get("clientOpId")}

    async def operation(session):
        if sale.get("clientOpId"):
            prior = await database.transactions.find_one(replay_filter, {"_id": 0}, session=session)
            if prior:
                return prior, False
        # All split guests participate in the same transaction. A late
        # insufficient/locked/foreign account aborts every preceding debit.
        for customer_id, points, value in redemptions:
            if points <= 0:
                raise HTTPException(400, "Redemption must be positive")
            match = {**scope, "id": customer_id}
            changed = await database.customers.find_one_and_update(
                {**match, "points": {"$gte": points}, "loyaltyLocked": {"$ne": True}},
                {"$inc": {"points": -points}}, session=session)
            if not changed:
                customer = await database.customers.find_one(match, session=session) or {}
                if customer.get("loyaltyLocked"):
                    raise HTTPException(403, "Loyalty account locked pending fraud review")
                raise HTTPException(400, f"Insufficient points: {int(customer.get('points', 0))} available, {points} requested")
            await database.loyalty_ledger.insert_one({
                "id": f"LP-{uuid.uuid4().hex}", "businessId": business_id,
                "customerId": customer_id, "transactionId": sale["id"],
                "type": "redeem", "points": -points, "value": value,
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }, session=session)
        # Drivers may add _id to their argument; retry callbacks need a fresh copy.
        document = copy.deepcopy(sale)
        await database.transactions.insert_one(document, session=session)
        document.pop("_id", None)
        return document, True

    try:
        return await _transaction(operation)
    except DuplicateKeyError:
        # The failed transaction is aborted, including its debits. Only an
        # existing tenant-scoped operation may be treated as an idempotent replay.
        if sale.get("clientOpId"):
            prior = await database.transactions.find_one(replay_filter, {"_id": 0})
            if prior:
                return prior, False
        raise
