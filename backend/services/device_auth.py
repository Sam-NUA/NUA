"""Device-revocation check shared by server.py's RequireAuthMiddleware and
routes/auth.py's get_current_user — kept in its own module (no routes/
imports) so both can import it without a circular dependency.
"""
from database import db


async def is_device_revoked_or_missing(device_id: str) -> bool:
    """True if this deviceId should no longer be trusted: explicitly
    revoked, or the row is gone entirely. An unknown id fails the same way
    an explicitly revoked one does — never ambiguous, never fail-open."""
    row = await db.devices.find_one({"id": device_id}, {"_id": 0, "status": 1})
    return (not row) or row.get("status") != "active"
