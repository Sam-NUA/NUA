"""Dry-run by default; normalize one venue atomically after operator review.

Run with service environment configured:
  python scripts/migrate_booking_times.py VENUE_ID [--apply]
Ambiguous local times abort without writes; resolve their offsets first.
"""
import argparse
import asyncio
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import db
from booking_time import window
from transactions import run_for_venue


async def migrate(venue_id, apply):
    venue = await db.venues.find_one({'id': venue_id})
    if not venue:
        raise RuntimeError('Venue not found')
    partner = {'id': venue['partner_id'], 'test_mode': bool(venue.get('test'))}

    async def operation(current, session):
        rows = await db.bookings.find({'venue_id': venue_id, 'time_format': {'$ne': 'utc-v1'}}, session=session).to_list(10001)
        if len(rows) > 10000:
            raise RuntimeError('More than 10000 legacy rows: prepare a reviewed batch migration')
        patches = []
        for row in rows:
            start, end = window(current, row['start_time'], row['end_time'])
            patches.append((row['_id'], {'start_time': start, 'end_time': end, 'time_format': 'utc-v1'}))
        if apply:
            for key, patch in patches:
                await db.bookings.update_one({'_id': key}, {'$set': patch}, session=session)
        return len(patches)
    count = await run_for_venue(venue_id, partner, operation) if apply else await operation(venue, None)
    print(f'{"Migrated" if apply else "Validated (dry run)"}: {count} booking times')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('venue_id')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    asyncio.run(migrate(args.venue_id, args.apply))
