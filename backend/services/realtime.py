"""Tenant-scoped invalidations persisted in Mongo for all function instances.
Local WebSocket delivery is retained for existing non-Vercel clients. The
HTTP feed is authoritative for cross-instance notifications; consumers must
also refresh application data after reconnect/overflow.
"""
from __future__ import annotations
from typing import Any, Dict, Optional
from fastapi import WebSocket
import logging
import asyncio
from database import db
from services.shared_runtime import SharedRuntime

logger = logging.getLogger(__name__)

_connections: Dict[WebSocket, Optional[str]] = {}


async def register(ws: WebSocket, business_id: Optional[str] = None) -> None:
    _connections[ws] = business_id


def unregister(ws: WebSocket) -> None:
    _connections.pop(ws, None)


async def broadcast(event: Dict[str, Any], business_id: Optional[str] = None) -> None:
    if business_id is None:
        from middleware.actor_context import get_actor_context
        business_id = get_actor_context().get("businessId")
    if not business_id:
        return
    try:
        await SharedRuntime(db).publish(business_id, event)
    except Exception:
        # The business write already committed; consumers keep normal polling.
        logger.error("Live invalidation persistence failed")
    dead = []
    for ws, conn_biz in list(_connections.items()):
        if conn_biz != business_id:
            continue
        try:
            await asyncio.wait_for(ws.send_json(event), timeout=1)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _connections.pop(ws, None)


def connection_count() -> int:
    return len(_connections)
