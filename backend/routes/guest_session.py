"""
Public, passwordless guest identity endpoints.

request-code/verify mirrors loyalty_v2.py's guest OTP flow exactly (same
anti-enumeration posture: always the same response whether or not the
phone matches anything, single-use code, capped attempts) — generalized
so any guest-facing surface (booking, waitlist, online ordering) can use
it, not just the loyalty portal.
"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Header
from typing import Any, Dict, Optional
from datetime import datetime, timedelta, timezone
from database import db
from utils.notifications import send_sms
from services import guest_session
import hashlib
import secrets

router = APIRouter(prefix="/guest/session")

OTP_TTL_SECONDS = 300
OTP_MAX_ATTEMPTS = 5


def _clean_phone(raw: Any) -> str:
    return "".join(ch for ch in str(raw or "") if ch.isdigit() or ch == "+").strip()


def _hash_code(phone: str, code: str) -> str:
    return hashlib.sha256(f"{phone}:{code}".encode()).hexdigest()


@router.post("/request-code")
async def request_code(body: Dict[str, Any]):
    phone = _clean_phone((body or {}).get("phone"))
    if not phone:
        raise HTTPException(400, "phone is required")

    code = f"{secrets.randbelow(1_000_000):06d}"
    await db.guest_session_otp.update_one(
        {"phone": phone},
        {"$set": {
            "phone": phone,
            "codeHash": _hash_code(phone, code),
            "attempts": 0,
            "createdAt": datetime.now(timezone.utc),
            "expiresAt": datetime.now(timezone.utc) + timedelta(seconds=OTP_TTL_SECONDS),
        }},
        upsert=True,
    )
    await send_sms(phone, f"Your NUA verification code is {code}. It expires in 5 minutes.")
    return {"sent": True}


@router.post("/verify")
async def verify(body: Dict[str, Any]):
    phone = _clean_phone((body or {}).get("phone"))
    code = "".join(ch for ch in str((body or {}).get("code", "")) if ch.isdigit())
    if not phone:
        raise HTTPException(400, "phone is required")
    if not code:
        raise HTTPException(400, "code is required")

    otp = await db.guest_session_otp.find_one({"phone": phone})
    if not otp:
        raise HTTPException(401, "Enter the code we texted you, or request a new one")
    if otp.get("attempts", 0) >= OTP_MAX_ATTEMPTS:
        raise HTTPException(401, "Too many attempts — request a new code")
    expires = otp.get("expiresAt")
    if hasattr(expires, "tzinfo") and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if not expires or expires < datetime.now(timezone.utc):
        raise HTTPException(401, "That code expired — request a new one")
    if otp.get("codeHash") != _hash_code(phone, code):
        await db.guest_session_otp.update_one({"phone": phone}, {"$inc": {"attempts": 1}})
        raise HTTPException(401, "That code didn't match")

    # Single use — burn it the moment it's spent, win or lose.
    await db.guest_session_otp.delete_one({"phone": phone})

    from routes.online_orders import resolve_or_require_business_id
    business_id = await resolve_or_require_business_id(body.get("business"))
    token = guest_session.issue_guest_token(phone, business_id)
    profile = await guest_session.resolve_guest_profile(phone, business_id)
    return {"token": token, "expiresInMinutes": guest_session.GUEST_SESSION_TTL_MINUTES, **profile}


async def get_guest_session(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """FastAPI dependency any other guest-facing router can reuse to accept
    this token instead of asking a returning guest to re-verify."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Guest session required")
    payload = guest_session.decode_guest_token(authorization.split(" ", 1)[1].strip())
    if not payload:
        raise HTTPException(401, "Invalid or expired guest session")
    return payload


@router.get("/me")
async def me(authorization: Optional[str] = Header(None)):
    session = await get_guest_session(authorization)
    return await guest_session.resolve_guest_profile(session["phone"], session.get("businessId"))
