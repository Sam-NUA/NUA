"""Replica-set transactions for stock moves and appointment scheduling.

No process-local lock or nontransactional production fallback. Appointment
mutations write a venue fence before checking availability, preventing
snapshot-isolation write skew between different appointment documents.
"""
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from database import client, db


async def _transaction(operation):
    async with await client.start_session() as session:
        return await session.with_transaction(
            operation, read_concern=ReadConcern("snapshot"),
            write_concern=WriteConcern("majority"))


async def stock_change(operation):
    return await _transaction(operation)


async def appointment_change(business_id, operation):
    if not isinstance(business_id, str) or not business_id.strip():
        raise HTTPException(400, "Business context required")
    # Create the immutable fence outside the retry callback. Concurrent first
    # callers can race this upsert; only the same existing _id is acceptable.
    key = {"_id": business_id, "businessId": business_id}
    try:
        await db.appointment_calendars.update_one(
            key, {"$setOnInsert": {"version": 0}}, upsert=True)
    except DuplicateKeyError:
        if not await db.appointment_calendars.find_one(key):
            raise

    async def fenced(session):
        result = await db.appointment_calendars.update_one(
            key, {"$inc": {"version": 1}}, session=session)
        if result.matched_count != 1:
            raise HTTPException(409, "Appointment calendar changed; retry")
        return await operation(session)

    return await _transaction(fenced)
