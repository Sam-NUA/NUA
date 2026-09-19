"""
Passwordless guest identity — a guest currently re-types their name, phone,
and email on every surface that asks (BookingPortal's reservation form,
its waitlist form, online ordering) and none of them know about each
other. loyalty_v2.py already proved the safe pattern for this: a texted
one-time code beats a bare phone number as an identity credential
(anti-enumeration, rate-limited, single-use). This generalizes that
pattern into a short-lived guest session token any guest-facing surface
can accept, instead of it being loyalty-specific.

The token is NOT a staff JWT — a distinct type ("guest") with a short
lifetime and no role, so server.py's RequireAuthMiddleware (which rejects
any token whose type isn't None/"access") can never mistake it for, or let
it escalate into, a staff credential. routes/guest_session.py's endpoints
are on the public path allowlist for the same reason loyalty_v2.py's
guest-lookup is — this token is its own credential, verified by the route
itself, not by that middleware.
"""
from __future__ import annotations
from typing import Any, Dict, Optional
from datetime import datetime, timedelta, timezone
from database import db
import jwt
import os
from middleware.actor_context import tenant_scope_filter

GUEST_SESSION_TTL_MINUTES = 60


def _secret() -> str:
    return os.environ["JWT_SECRET"]


def issue_guest_token(phone: str, business_id: Optional[str] = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "type": "guest", "phone": phone, "businessId": business_id, "sub": f"guest:{phone}",
        "iat": now, "exp": now + timedelta(minutes=GUEST_SESSION_TTL_MINUTES),
    }
    return jwt.encode(payload, _secret(), algorithm="HS256")


def decode_guest_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        payload = jwt.decode(token, _secret(), algorithms=["HS256"])
    except Exception:
        return None
    if payload.get("type") != "guest" or not payload.get("phone"):
        return None
    return payload


async def resolve_guest_profile(phone: str, business_id: Optional[str] = None) -> Dict[str, Any]:
    """Best-known name/email for this phone, so a returning guest's forms
    can prefill instead of asking again — same identity key (phone) as
    loyalty_v2.py's guest_lookup, and deliberately just as minimal: name/
    email for prefill, never the full customer record."""
    customer = await db.customers.find_one({**tenant_scope_filter(business_id or ""), "phone": phone}, {"_id": 0, "name": 1, "email": 1})
    return {
        "phone": phone,
        "name": (customer or {}).get("name"),
        "email": (customer or {}).get("email"),
        "known": customer is not None,
    }
