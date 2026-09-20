"""
Live-sync layer for the Owner Dashboard app — a plain FastAPI WebSocket, not
a third-party realtime vendor. The whole stack is already self-hosted (own
Mongo, own auth), so pushing sale/roster/alert events through a native
socket authenticated with the same JWT avoids adding a new vendor, a new AU
data-residency question, and duplicated auth logic for something this small.

This is a "nice to have instantly" layer, never the source of truth — every
client that uses it (see frontend/src/hooks/useLiveFeed.js) keeps its normal
polling running underneath. A dropped socket (regional connectivity, a proxy
that blocks WS upgrades) just means events arrive a little later via the
next poll instead of instantly; nothing breaks.
"""
from __future__ import annotations
from typing import Any, Dict, Optional
from fastapi import WebSocket
import logging

logger = logging.getLogger(__name__)

# Keyed by connection -> the business it belongs to (from the JWT used to
# open the socket) — every deployment on this codebase is actually
# multi-tenant (shared Mongo, businessId-stamped everywhere else), so
# without this every connected client saw every other business's live
# sales/roster/gift-card/floor-plan events in real time, not just their
# own. None means an old/legacy token with no businessId — treated the
# same "visible to everyone" way missing businessId is treated elsewhere
# in this codebase, not silently dropped.
_connections: Dict[WebSocket, Optional[str]] = {}


async def register(ws: WebSocket, business_id: Optional[str] = None) -> None:
    _connections[ws] = business_id


def unregister(ws: WebSocket) -> None:
    _connections.pop(ws, None)


async def broadcast(event: Dict[str, Any], business_id: Optional[str] = None) -> None:
    """Best-effort fan-out, scoped to one business's connections. Never let
    a dead/slow socket affect the caller — this is called inline after a
    sale/roster write, not queued.

    business_id defaults from the request's actor context (same pattern as
    notification_service.send()) so none of the dozen existing call sites
    (kitchen.py, transactions.py, reservations.py, v26_commerce.py,
    staff_management.py) need editing individually. None broadcasts to
    every connection, same backward-compat default used throughout —
    an event genuinely without a business context (or a caller with an
    old token) still reaches everyone rather than silently going nowhere.
    """
    if business_id is None:
        from middleware.actor_context import get_actor_context
        business_id = get_actor_context().get("businessId")
    dead = []
    for ws, conn_biz in list(_connections.items()):
        if business_id is not None and conn_biz is not None and conn_biz != business_id:
            continue
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _connections.pop(ws, None)


def connection_count() -> int:
    return len(_connections)
