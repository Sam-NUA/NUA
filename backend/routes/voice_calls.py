"""AI outbound voice calls.

Lets the Concierge / Ash agent actually call a customer — to confirm a
booking, chase a no-show risk, or read back a message — rather than only
texting or emailing. Built on the same real, honestly-gated pattern as
Stripe/Coinbase checkout in this codebase: nothing here fakes a call being
placed. Without Twilio credentials configured, the initiating endpoint
returns a clear error instead of silently pretending to dial.

Conversation shape: Twilio rings the guest, hits our /voice/twiml/{id}
webhook for what to say, opens a speech <Gather>, and POSTs the guest's
spoken reply to /voice/gather/{id}. We classify the reply (confirmed /
declined / unclear) and either wrap up or ask a short follow-up, for a few
turns, then hang up — this is a short confirmation call, not open-ended
chat. Every turn is stored so staff can read the transcript afterwards.
"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Request, Response, Depends
from datetime import datetime, timezone
from typing import Optional
from database import db
from deps import get_user
from middleware.actor_context import tenant_scope_filter, tenant_owns, tenant_owns_strict, get_actor_context
from services import voice_calls as vc
import os
import uuid

router = APIRouter()

MAX_GATHER_TURNS = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _opening_message(purpose: str, *, name: Optional[str], context: dict) -> str:
    who = f"Hi {name}, " if name else "Hi there, "
    if purpose == "confirm_booking":
        party = context.get("partySize"); date = context.get("date"); time = context.get("time")
        details = f"{party} people on {date} at {time}" if (party and date and time) else "your upcoming booking"
        return f"{who}this is NUA calling to confirm {details}. Does that still work for you?"
    if purpose == "reminder":
        return f"{who}this is a reminder from NUA about your booking " \
               f"{('on ' + context['date']) if context.get('date') else ''}. See you soon — just say okay to confirm."
    if purpose == "custom":
        message = context.get("message") or "we wanted to give you a call."
        return f"{who}this is NUA calling — {message}"
    return f"{who}this is NUA calling."


def _classify_response(speech: str) -> str:
    s = (speech or "").lower()
    # Checked before the decline/confirm keyword scan below: "not sure"
    # contains "no" as a bare substring (of "n-O-t") and "sure" is also a
    # confirm keyword, so without this it collided into a false positive
    # both ways depending on scan order — genuine uncertainty first.
    if any(p in s for p in ("not sure", "don't know", "dont know", "no idea")):
        return "unclear"
    if any(w in s for w in ("no", "nope", "cancel", "can't make it", "cant make it", "reschedule", "won't", "wont")):
        return "declined"
    if any(w in s for w in ("yes", "yeah", "yep", "sure", "confirm", "sounds good", "that works", "correct", "okay")):
        return "confirmed"
    return "unclear"


def _closing_message(outcome: str) -> str:
    if outcome == "confirmed":
        return "Wonderful, you're all set. Thanks so much, see you then. Goodbye."
    if outcome == "declined":
        return "No problem at all — we'll follow up by text to sort out a new time. Goodbye."
    return "Thanks for your time — we'll follow up by text if we need anything else. Goodbye."


async def initiate_call(*, customer_id: Optional[str], phone: Optional[str], purpose: str,
                          context: Optional[dict], base_url: str, actor: Optional[dict],
                          business_id: Optional[str] = None) -> dict:
    """Shared by the HTTP endpoint and the Ash `call_customer` tool."""
    if business_id is None:
        business_id = get_actor_context().get("businessId")
    context = context or {}
    customer = None
    if customer_id:
        customer = await db.customers.find_one({**tenant_scope_filter(business_id), "id": customer_id}, {"_id": 0})
        if customer is None or not tenant_owns(customer.get("businessId"), business_id):
            raise HTTPException(status_code=404, detail="Customer not found")
        phone = phone or customer.get("phone")

    if not (phone or "").strip():
        raise HTTPException(status_code=400, detail="No phone number to call")

    if not vc.is_configured():
        raise HTTPException(status_code=500,
                             detail="Voice calling isn't set up yet — ask the owner to add Twilio credentials.")

    name = (customer or {}).get("name") or context.get("guestName")
    opening = _opening_message(purpose, name=name, context=context)

    call_id = f"CALL-{uuid.uuid4().hex[:8].upper()}"
    doc = {
        "id": call_id, "customerId": customer_id, "phone": phone, "purpose": purpose,
        "context": context, "openingMessage": opening,
        "transcript": [{"speaker": "nua", "text": opening, "at": _now()}],
        "turns": 0, "status": "initiating", "outcome": None,
        "createdBy": (actor or {}).get("name") or (actor or {}).get("id") or "ash-agent",
        "createdAt": _now(), "businessId": business_id,
    }
    await db.voice_calls.insert_one(dict(doc))

    base_url = base_url.rstrip("/")
    twiml_url = f"{base_url}/api/voice/twiml/{call_id}"
    status_url = f"{base_url}/api/voice/status/{call_id}"
    try:
        sid = vc.place_call(to=phone, twiml_url=twiml_url, status_callback_url=status_url)
    except vc.VoiceCallError as e:
        await db.voice_calls.update_one({"id": call_id}, {"$set": {"status": "failed", "error": str(e)}})
        raise HTTPException(status_code=500, detail=str(e))

    await db.voice_calls.update_one({"id": call_id}, {"$set": {"status": "ringing", "twilioCallSid": sid}})
    return {"callId": call_id, "status": "ringing", "twilioCallSid": sid}


@router.post("/voice/calls")
async def create_call(data: dict, http_request: Request, user: dict = Depends(get_user)):
    base_url = data.get("baseUrl") or str(http_request.base_url)
    return await initiate_call(
        customer_id=data.get("customerId"), phone=data.get("phone"),
        purpose=data.get("purpose", "custom"), context=data.get("context"),
        base_url=base_url, actor=user,
    )


@router.get("/voice/calls")
async def list_calls(limit: int = 50, user: dict = Depends(get_user)):
    limit = max(1, min(200, limit))
    rows = await db.voice_calls.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}) \
        .sort("createdAt", -1).to_list(limit)
    return rows


@router.get("/voice/calls/{call_id}")
async def get_call(call_id: str, user: dict = Depends(get_user)):
    row = await db.voice_calls.find_one({"$and": [{"id": call_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if row is None or not tenant_owns_strict(row.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Call not found")
    return row


# -- Twilio webhooks (public — validated by Twilio request signature) ------

def _public_url(request: Request) -> str:
    """The exact URL Twilio signed, matching whatever's actually reachable
    (a reverse proxy in front of this service means request.url can differ
    from what Twilio was told to call — TWILIO_WEBHOOK_BASE_URL overrides
    when that's the case)."""
    override = os.environ.get("TWILIO_WEBHOOK_BASE_URL")
    if override:
        return f"{override.rstrip('/')}{request.url.path}"
    return str(request.url)


async def _verify_twilio_request(request: Request, form: dict) -> None:
    signature = request.headers.get("X-Twilio-Signature")
    if not vc.validate_signature(_public_url(request), form, signature):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")


@router.post("/voice/twiml/{call_id}")
async def voice_twiml(call_id: str, request: Request):
    form = dict((await request.form()))
    await _verify_twilio_request(request, form)

    call = await db.voice_calls.find_one({"id": call_id}, {"_id": 0})
    if not call:
        # Twilio still needs valid TwiML back even for an id we don't
        # recognise, or the call hangs open on the guest's end.
        twiml = vc.say_and_gather_twiml(say="Sorry, something went wrong. Goodbye.", gather_action_url="", end_call=True)
        return Response(content=twiml, media_type="application/xml")

    await db.voice_calls.update_one({"id": call_id}, {"$set": {"status": "in_progress"}})
    base = str(request.base_url).rstrip("/")
    gather_url = f"{base}/api/voice/gather/{call_id}"
    twiml = vc.say_and_gather_twiml(say=call["openingMessage"], gather_action_url=gather_url)
    return Response(content=twiml, media_type="application/xml")


@router.post("/voice/gather/{call_id}")
async def voice_gather(call_id: str, request: Request):
    form = dict((await request.form()))
    await _verify_twilio_request(request, form)

    call = await db.voice_calls.find_one({"id": call_id}, {"_id": 0})
    if not call:
        twiml = vc.say_and_gather_twiml(say="Sorry, something went wrong. Goodbye.", gather_action_url="", end_call=True)
        return Response(content=twiml, media_type="application/xml")

    speech = form.get("SpeechResult", "")
    outcome = _classify_response(speech)
    turns = int(call.get("turns", 0)) + 1
    transcript_entry = {"speaker": "guest", "text": speech, "at": _now()}

    if outcome in ("confirmed", "declined") or turns >= MAX_GATHER_TURNS:
        closing = _closing_message(outcome)
        await db.voice_calls.update_one(
            {"id": call_id},
            {"$push": {"transcript": {"$each": [transcript_entry, {"speaker": "nua", "text": closing, "at": _now()}]}},
             "$set": {"status": "completed", "outcome": outcome, "turns": turns}},
        )
        twiml = vc.say_and_gather_twiml(say=closing, gather_action_url="", end_call=True)
        return Response(content=twiml, media_type="application/xml")

    follow_up = "Sorry, could you say that again — will that time work for you?"
    base = str(request.base_url).rstrip("/")
    gather_url = f"{base}/api/voice/gather/{call_id}"
    await db.voice_calls.update_one(
        {"id": call_id},
        {"$push": {"transcript": {"$each": [transcript_entry, {"speaker": "nua", "text": follow_up, "at": _now()}]}},
         "$set": {"turns": turns}},
    )
    twiml = vc.say_and_gather_twiml(say=follow_up, gather_action_url=gather_url)
    return Response(content=twiml, media_type="application/xml")


@router.post("/voice/status/{call_id}")
async def voice_status(call_id: str, request: Request):
    form = dict((await request.form()))
    await _verify_twilio_request(request, form)
    call_status = form.get("CallStatus")
    patch = {"twilioStatus": call_status, "endedAt": _now()}
    if call_status in ("no-answer", "busy", "failed", "canceled"):
        patch["status"] = "unreachable"
        patch["outcome"] = patch.get("outcome") or "unreachable"
    await db.voice_calls.update_one({"id": call_id}, {"$set": patch})
    return {"ok": True}
