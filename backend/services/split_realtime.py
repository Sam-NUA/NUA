"""Real-time synchronization for guest bill-split.

Manages WebSocket connections, broadcasts updates to all connected clients
(guests and staff) viewing the same split, and maintains connection state.
"""
from __future__ import annotations
from typing import Optional, Dict, Any, Set
from datetime import datetime, timezone
from database import db
import logging

log = logging.getLogger("split_realtime")

# In-memory connection tracking (in production, use Redis)
_connections: Dict[str, Set] = {}  # split_id -> set of websocket connections


class SplitRealtimeManager:
    """Manages real-time split updates and WebSocket broadcasts."""

    def __init__(self):
        self.connections = {}  # split_id -> [websocket_connections]

    async def register_connection(self, split_id: str, websocket) -> None:
        """Register a new WebSocket connection for a split."""
        if split_id not in self.connections:
            self.connections[split_id] = []
        self.connections[split_id].append(websocket)
        log.info(f"Connected to split {split_id}: {len(self.connections[split_id])} clients")

    async def unregister_connection(self, split_id: str, websocket) -> None:
        """Unregister a WebSocket connection."""
        if split_id in self.connections:
            self.connections[split_id] = [
                ws for ws in self.connections[split_id] if ws != websocket
            ]
            if not self.connections[split_id]:
                del self.connections[split_id]
            log.info(f"Disconnected from split {split_id}")

    async def broadcast_update(self, split_id: str, event_type: str, data: Dict[str, Any]) -> None:
        """Broadcast an update to all connected clients for a split."""
        if split_id not in self.connections:
            return

        message = {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "splitId": split_id,
            "data": data,
        }

        dead_connections = []
        for websocket in self.connections.get(split_id, []):
            try:
                await websocket.send_json(message)
            except Exception as e:
                log.warning(f"Failed to send to websocket: {e}")
                dead_connections.append(websocket)

        # Clean up dead connections
        for ws in dead_connections:
            await self.unregister_connection(split_id, ws)

    async def broadcast_claim(self, split_id: str, line_ids: list) -> None:
        """Broadcast item claim to all clients.

        Never includes the claiming guest's phone number — this websocket
        has no authentication at all by design (see routes/bill_split.py's
        websocket_split_updates docstring), so anyone who can open it for a
        split_id can watch every event on it. Connected clients that need
        to know per-line claim state re-fetch the split itself (already
        redacted via _public_view), rather than trust broadcast payloads
        for anything phone-identifying."""
        await self.broadcast_update(split_id, "item_claimed", {
            "lineIds": line_ids,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    async def broadcast_payment(self, split_id: str, amount: float) -> None:
        """Broadcast payment from guest — no guest_phone, same reasoning as
        broadcast_claim above."""
        await self.broadcast_update(split_id, "payment_received", {
            "amount": amount,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    async def broadcast_split_update(self, split_id: str) -> None:
        """Broadcast full split status update, redacted the same way the
        websocket's own connect/sync_request messages are (see
        routes/bill_split.py's _public_view) — this method sends to the
        exact same unauthenticated audience, so it must never leak
        claimedByPhone either."""
        split = await db.bill_splits.find_one({"id": split_id}, {"_id": 0})
        if split:
            redacted = dict(split)
            redacted["lines"] = [
                {k: v for k, v in line.items() if k != "claimedByPhone"}
                for line in (split.get("lines") or [])
            ]
            redacted["equalParts"] = [
                {k: v for k, v in part.items() if k != "claimedByPhone"}
                for part in (split.get("equalParts") or [])
            ]
            await self.broadcast_update(split_id, "split_updated", redacted)

    async def broadcast_group_invite(self, split_id: str) -> None:
        """Broadcast group invite notification — no invited_phone, same
        reasoning as broadcast_claim above."""
        await self.broadcast_update(split_id, "group_invite_sent", {
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    async def get_connection_count(self, split_id: str) -> int:
        """Get number of active connections for a split."""
        return len(self.connections.get(split_id, []))

    async def get_active_splits(self) -> list:
        """Get list of splits with active connections."""
        return list(self.connections.keys())


# Global manager instance
_manager = SplitRealtimeManager()


def get_manager() -> SplitRealtimeManager:
    """Get the global realtime manager."""
    return _manager
