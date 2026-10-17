"""Device-revocation check shared by server.py's RequireAuthMiddleware and
routes/auth.py's get_current_user — kept in its own module (no routes/
imports) so both can import it without a circular dependency.
"""
from database import db
from fastapi import HTTPException


async def is_device_revoked_or_missing(device_id: str, business_id: str = None) -> bool:
    """True if this deviceId should no longer be trusted: explicitly
    revoked, or the row is gone entirely. An unknown id fails the same way
    an explicitly revoked one does — never ambiguous, never fail-open."""
    query = {"id": device_id}
    if business_id is not None:
        query["businessId"] = business_id
    row = await db.devices.find_one(query, {"_id": 0, "status": 1})
    return (not row) or row.get("status") != "active"


async def validate_session_device(payload: dict, business_id: str):
    """Binding is immutable and applies to pre-binding access/refresh tokens too.

    The lookup is by a server-issued session id and subject. Inspect ownership
    explicitly: filtering away a moved account's old binding would fail open.
    """
    device_id = payload.get("deviceId")
    session_id = payload.get("sessionId")
    if session_id:
        binding = await db.terminal_sessions.find_one({"_id": session_id})
        if binding:
            if (binding.get("userId") != payload.get("sub")
                    or binding.get("businessId") != business_id
                    or (device_id and device_id != binding.get("deviceId"))):
                raise HTTPException(status_code=401, detail="Terminal session changed; sign in again")
            device_id = binding["deviceId"]
    if device_id:
        if (not business_id or (payload.get("businessId") and payload["businessId"] != business_id)
                or await is_device_revoked_or_missing(device_id, business_id)):
            raise HTTPException(status_code=401, detail="This terminal is unavailable for this business")
    return device_id
