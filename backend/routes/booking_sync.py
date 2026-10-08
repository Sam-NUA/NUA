"""Owner-visible sync backlog, without exposing guest snapshots or keys."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from database import db
from deps import require_owner_or_manager
from middleware.actor_context import tenant_scope_filter

router = APIRouter()


@router.get('/booking-sync')
async def sync_status(user: dict = Depends(require_owner_or_manager)):
    scope = tenant_scope_filter(user.get('businessId'))
    counts = {}
    for status in ('pending', 'delivering', 'retrying', 'failed', 'delivered'):
        counts[status] = await db.booking_sync_outbox.count_documents({**scope, 'status': status})
    failures = await db.booking_sync_outbox.find(
        {**scope, 'status': 'failed'}, {'_id': 0, 'source_id': 1, 'reservationId': 1,
                                       'last_error': 1, 'updated_at': 1}).to_list(100)
    return {'counts': counts, 'failures': failures}


@router.post('/booking-sync/{source_id}/retry')
async def retry_sync(source_id: str, user: dict = Depends(require_owner_or_manager)):
    result = await db.booking_sync_outbox.update_one(
        {'_id': source_id, **tenant_scope_filter(user.get('businessId')), 'status': 'failed'},
        {'$set': {'status': 'pending', 'attempts': 0, 'next_attempt_at': datetime.now(timezone.utc).isoformat(),
                  'retriedBy': user.get('id') or user.get('email')},
         '$unset': {'claim_token': '', 'lease_until': ''}})
    if result.matched_count != 1:
        raise HTTPException(404, 'Failed delivery not found')
    return {'status': 'pending'}
