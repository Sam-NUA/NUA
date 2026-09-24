"""
AI Bookings Inbox.

A unified inbox that captures booking requests from any inbound channel
(social media DM, phone-call transcription, email, in-store form) and runs
them through an LLM to extract structured info (date, time, party size,
special requests, customer contact). The owner can acknowledge or convert
each into a Reservation.

Channels are stored as free-text strings so we can absorb new ones without a
migration.
"""
from fastapi import APIRouter, HTTPException, Response, Depends
from typing import Optional
from datetime import datetime, timezone, date as date_cls
from pydantic import BaseModel
from database import db
from services import reservation_store
from deps import get_user, require_owner_or_manager
from middleware.actor_context import tenant_scope_filter, tenant_owns_strict
import os
import json
import uuid
import hashlib

router = APIRouter()

class BookingInboxItem(BaseModel):
    id: str
    channel: str                # 'instagram_dm' | 'facebook_dm' | 'whatsapp' | 'sms' | 'phone' | 'email' | 'web_form' | 'walkin'
    rawMessage: str
    fromHandle: Optional[str] = None
    receivedAt: str
    parsed: Optional[dict] = None   # {date, time, partySize, name, phone, notes}
    aiSummary: Optional[str] = None
    suggestedReply: Optional[str] = None
    status: str = "new"             # new | acknowledged | converted | dismissed
    reservationId: Optional[str] = None
    acknowledgedAt: Optional[str] = None
    acknowledgedBy: Optional[str] = None

class IngestBody(BaseModel):
    channel: str
    rawMessage: str
    fromHandle: Optional[str] = None

@router.get("/bookings/inbox")
async def list_inbox(status: Optional[str] = None, channel: Optional[str] = None, limit: int = 100,
                      user: dict = Depends(get_user)):
    q: dict = tenant_scope_filter(user.get("businessId"))
    if status:
        q["status"] = status
    if channel:
        q["channel"] = channel
    limit = max(1, min(500, limit))
    rows = await db.booking_inbox.find(q, {"_id": 0}).sort("receivedAt", -1).to_list(limit)
    return rows

@router.post("/bookings/inbox")
async def ingest_booking(body: IngestBody, response: Response, user: dict = Depends(get_user)):
    """Accept a raw inbound message — run AI parse + suggested reply.

    Sets `x-ai-parsed-fallback: true` on the response when the LLM
    couldn't parse the message and we fell back to a templated response.
    The persisted document also carries `aiParsedFallback` so the UI can
    flag historic items even after a page reload.
    """
    item = {
        "id": str(uuid.uuid4()),
        "channel": body.channel,
        "rawMessage": body.rawMessage,
        "fromHandle": body.fromHandle,
        "receivedAt": datetime.now(timezone.utc).isoformat(),
        "status": "new",
        "businessId": user.get("businessId"),
    }

    parsed, summary, reply, fallback = await _ai_parse(body.rawMessage, body.channel)
    item["parsed"] = parsed
    item["aiSummary"] = summary
    item["suggestedReply"] = reply
    item["aiParsedFallback"] = bool(fallback)

    # Header so SPA fetch handlers can show "AI fell back" toasts immediately.
    response.headers["x-ai-parsed-fallback"] = "true" if fallback else "false"

    await db.booking_inbox.insert_one(dict(item))
    item.pop("_id", None)
    return item

@router.post("/bookings/inbox/{item_id}/ack")
async def acknowledge_booking(item_id: str, body: dict, user: dict = Depends(require_owner_or_manager)):
    """Mark as acknowledged. Optionally convert to a reservation.

    The acknowledging user is taken from the auth token, never from the body.
    """
    convert = bool(body.get("convertToReservation", False))
    user_name = user.get("name") or user.get("email") or "system"

    row = await db.booking_inbox.find_one({"$and": [{"id": item_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not row or not tenant_owns_strict(row.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Inbox item not found")

    if row.get("status") == "converted":
        return {"ok": True, "status": "converted", "reservationId": row.get("reservationId")}

    now = datetime.now(timezone.utc).isoformat()
    patch = {"status": "acknowledged", "acknowledgedAt": now, "acknowledgedBy": user_name}

    if convert:
        parsed = row.get("parsed") or {}
        from services.customer_match import find_matching_customer, guest_context
        customer = await find_matching_customer(
            name=parsed.get("name") or row.get("fromHandle"), phone=parsed.get("phone"))
        notes = parsed.get("notes") or ""
        if customer:
            notes = f"{notes} [Returning guest — {guest_context(customer)}]".strip()
        res = {
            "id": "res-inbox-" + hashlib.sha256(f"{user.get('businessId')}:{item_id}".encode()).hexdigest(),
            "guestName": parsed.get("name") or row.get("fromHandle") or "Guest",
            "guestPhone": parsed.get("phone") or (customer or {}).get("phone") or "",
            "customerId": (customer or {}).get("id"),
            "date": parsed.get("date") or "",
            "time": parsed.get("time") or "",
            "partySize": int(parsed.get("partySize") or 2),
            "notes": notes,
            "source": f"ai-inbox/{row.get('channel', 'unknown')}",
            "status": "confirmed",
            "createdAt": now,
            "businessId": user.get("businessId"),
        }
        from services.booking_rules_engine import capacity_lock, validate_and_enrich_booking, BookingRuleViolation
        try:
            async with capacity_lock(user.get("businessId"), res["date"]):
                existing = await db.reservations.find_one({"id": res["id"], "businessId": user.get("businessId")})
                if existing:
                    await db.booking_inbox.update_one({"id": item_id, "businessId": user.get("businessId")},
                        {"$set": {"status": "converted", "reservationId": existing["id"]}})
                    return {"ok": True, "status": "converted", "reservationId": existing["id"]}
                res["_id"] = res["id"]
                enrichment = await validate_and_enrich_booking(
                    date=res["date"], time=res["time"], party_size=res["partySize"],
                    source=res["source"], business_id=user.get("businessId"))
                res.update(enrichment)
                await reservation_store.insert_one(res)
        except (BookingRuleViolation, TimeoutError) as exc:
            raise HTTPException(409, str(exc)) from exc
        patch["status"] = "converted"
        patch["reservationId"] = res["id"]

    await db.booking_inbox.update_one({"$and": [{"id": item_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": patch})
    return {"ok": True, **patch}

@router.post("/bookings/inbox/{item_id}/dismiss")
async def dismiss(item_id: str, user: dict = Depends(require_owner_or_manager)):
    row = await db.booking_inbox.find_one({"$and": [{"id": item_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not row or not tenant_owns_strict(row.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Not found")
    await db.booking_inbox.update_one({"$and": [{"id": item_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": {"status": "dismissed"}})
    return {"ok": True}

# -- helpers ---------------------------------------------------------------
async def _ai_parse(message: str, channel: str):
    """Best-effort LLM parse. Returns (parsed, summary, reply, fallback)
    where `fallback=True` means the LLM was unavailable or its output was
    unusable and the caller is receiving a templated default."""
    fallback_parsed = {
        "date": None, "time": None, "partySize": None,
        "name": None, "phone": None, "notes": None,
    }
    fallback_summary = f"{channel.title()} message: {message[:120]}"
    fallback_reply = (
        "Thanks for the message — could you confirm the date, time, and party size?"
    )

    api_key = os.environ.get("EMERGENT_LLM_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return fallback_parsed, fallback_summary, fallback_reply, True

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        prompt = (
            "You are NUA, a restaurant booking assistant. From the inbound "
            f"{channel} message below, extract a JSON object with fields: "
            "date (YYYY-MM-DD or null), time (HH:MM 24h or null), partySize "
            "(int or null), name (string or null), phone (string or null), "
            "notes (string or null), summary (one short sentence), reply (a "
            "warm 1-2 sentence reply to send back). Return ONLY valid JSON.\n\n"
            f"Message: {message}"
        )
        session_id = f"bookings-{uuid.uuid4().hex[:8]}"
        model_name = os.environ.get("BOOKINGS_INBOX_MODEL", "gpt-4o-mini")
        chat = LlmChat(api_key=api_key, session_id=session_id, system_message="Be precise; never invent details").with_model("openai", model_name)
        msg = UserMessage(text=prompt)
        raw = await chat.send_message(msg)
        # Strip code fences if present
        text = (raw or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text.split("\n", 1)[1] if "\n" in text else text
            if text.endswith("```"):
                text = text[:-3]
        data = json.loads(text)
        parsed = {
            "date": data.get("date"),
            "time": data.get("time"),
            "partySize": data.get("partySize"),
            "name": data.get("name"),
            "phone": data.get("phone"),
            "notes": data.get("notes"),
        }
        # Guard against the LLM picking a stale year for relative phrases
        # like "tonight" / "tomorrow" — clamp any past date to today.
        try:
            if parsed["date"]:
                d = date_cls.fromisoformat(parsed["date"])
                today = date_cls.today()
                if d < today:
                    parsed["date"] = today.isoformat()
        except Exception:
            # If the LLM returns a non-ISO string, leave it alone for manual fix
            pass
        return parsed, data.get("summary") or fallback_summary, data.get("reply") or fallback_reply, False
    except Exception as e:
        # Never fail the ingest just because the LLM stumbled
        return fallback_parsed, f"{fallback_summary} (AI parse skipped: {type(e).__name__})", fallback_reply, True
