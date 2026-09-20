"""
WS /api/ws/live — authenticated live feed for the Owner Dashboard app.

Browsers can't attach an Authorization header to a WebSocket handshake, so
the same JWT the REST API already issues is passed as a query param instead
(`?token=...`) and verified with the identical secret/algorithm as
routes/auth.py. Anything else (missing token, expired, malformed) closes the
socket with 4401 rather than accepting an unauthenticated connection.
"""
from __future__ import annotations
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import jwt
import os
import logging

from services import realtime

logger = logging.getLogger(__name__)
router = APIRouter()


def _verify_token(token: str):
    try:
        return jwt.decode(token, os.environ["JWT_SECRET"], algorithms=["HS256"])
    except Exception:
        return None


@router.websocket("/ws/live")
async def live_feed(websocket: WebSocket, token: str = ""):
    payload = _verify_token(token)
    if not payload or not payload.get("sub"):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    await realtime.register(websocket, business_id=payload.get("businessId"))
    try:
        await websocket.send_json({"type": "connected"})
        while True:
            # Clients don't need to send anything — this keeps the socket
            # open and lets a client-side ping/pong (if any) pass through
            # without erroring on an unread message.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.info(f"[realtime] socket closed: {e}")
    finally:
        realtime.unregister(websocket)
