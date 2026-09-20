"""services/realtime.py fanned every live event (sales, roster changes,
gift-card activity, floor-plan updates) out to EVERY connected WebSocket
client regardless of which business they belonged to — the module's own
comment said so explicitly ("No multi-tenant partitioning yet... this
deployment model is one business per backend"), which doesn't match the
rest of this codebase's actual shared-Mongo, businessId-stamped-
everywhere multi-tenant reality. Any authenticated staff member of any
business, once connected to /ws/live, saw every other business's live
activity in real time.
"""
import asyncio

from middleware.actor_context import set_actor_context
from services import realtime


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _FakeSocket:
    def __init__(self):
        self.received = []

    async def send_json(self, event):
        self.received.append(event)


def test_broadcast_only_reaches_connections_for_the_same_business():
    mine = _FakeSocket()
    theirs = _FakeSocket()
    _run(realtime.register(mine, business_id="realtime-biz-mine"))
    _run(realtime.register(theirs, business_id="realtime-biz-other"))
    try:
        _run(realtime.broadcast({"type": "sale.completed", "total": 42}, business_id="realtime-biz-mine"))
        assert mine.received == [{"type": "sale.completed", "total": 42}]
        assert theirs.received == [], "a broadcast for one business must not reach another business's connection"
    finally:
        realtime.unregister(mine)
        realtime.unregister(theirs)


def test_broadcast_defaults_business_id_from_the_current_actor_context():
    """None of the dozen existing call sites (kitchen.py, transactions.py,
    reservations.py, v26_commerce.py, staff_management.py) pass business_id
    explicitly — broadcast() must pick it up from the request's own actor
    context so those call sites are scoped without editing each one."""
    mine = _FakeSocket()
    theirs = _FakeSocket()
    _run(realtime.register(mine, business_id="realtime-ctx-mine"))
    _run(realtime.register(theirs, business_id="realtime-ctx-other"))
    set_actor_context({"businessId": "realtime-ctx-mine"})
    try:
        _run(realtime.broadcast({"type": "roster.updated"}))
        assert mine.received == [{"type": "roster.updated"}]
        assert theirs.received == []
    finally:
        realtime.unregister(mine)
        realtime.unregister(theirs)
        set_actor_context({})


def test_a_connection_with_no_business_id_still_receives_broadcasts():
    """An old/legacy token with no businessId claim — treated the same
    'visible to everyone' way a missing businessId is treated everywhere
    else in this codebase, not silently dropped."""
    legacy = _FakeSocket()
    _run(realtime.register(legacy, business_id=None))
    try:
        _run(realtime.broadcast({"type": "sale.completed"}, business_id="realtime-legacy-biz"))
        assert legacy.received == [{"type": "sale.completed"}]
    finally:
        realtime.unregister(legacy)
