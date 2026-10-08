"""Serialize venue capacity changes within retryable Mongo transactions.

Writing the venue revision forces overlapping transactions to conflict. The
loser retries with a fresh snapshot before checking available capacity. There
is no expiring application lock whose former holder can still commit.
"""
from fastapi import HTTPException
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern
from pymongo.errors import OperationFailure

from database import client, db


def venue_scope(partner):
    return {'partner_id': partner['id'],
            'test': True if partner.get('test_mode') else {'$ne': True}}


async def run_for_venue(venue_id, partner, operation):
    async def execute(session):
        venue = await db.venues.find_one_and_update(
            {'id': venue_id, **venue_scope(partner)}, {'$inc': {'revision': 1}},
            return_document=True, session=session,
        )
        if venue is None:
            raise HTTPException(404, 'Venue not found')
        return await operation(venue, session)

    try:
        async with await client.start_session() as session:
            return await session.with_transaction(
                execute, read_concern=ReadConcern('snapshot'),
                write_concern=WriteConcern('majority'), max_commit_time_ms=10000,
            )
    except OperationFailure as exc:
        if exc.code in (20, 303):
            raise HTTPException(503, 'Bookings requires a transaction-capable Mongo replica set') from exc
        raise
