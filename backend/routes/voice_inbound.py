"""
AI Concierge — inbound voice reservations.

Twilio hits POST /api/voice/inbound when a customer dials one of the
business's registered Twilio numbers. We greet, gather party-size / date /
time / name across up to MAX_INBOUND_TURNS speech turns, ask for an
explicit spoken "yes" before committing, run the exact same booking-rules
engine every other channel is held to, then create a real reservation in
db.reservations with `source="phone"` and hang up gracefully.

Design guardrails:
- These two webhook paths (POST /voice/inbound and POST
  /voice/inbound/gather/{call_id}) are the *only* /api/voice/inbound/*
  routes on server.py's PUBLIC_API_PREFIXES allowlist — every other path
  in this file (status/config/recent/active) stays behind the normal
  auth middleware. Twilio can't carry our JWT, so request-signature
  validation (services.voice_calls.validate_signature, which itself fails
  closed whenever TWILIO_AUTH_TOKEN isn't configured) is what actually
  gates these two.
- The business is resolved from the actual Twilio "To" number against a
  verified, owner-configured mapping (db.businesses.inboundVoiceNumber) —
  never an unfiltered "first business in the collection". An unknown,
  inactive, or ambiguously-duplicated number mapping is refused rather
  than guessed at.
- Every guest utterance is stored so staff can review the transcript, and
  every call-lifecycle event (start, business resolved, confirmed,
  booked, rejected, handed off, failed) is written to the audit log.
- If we can't extract everything after N turns, or a spoken confidence is
  too low to trust, we ask again rather than guessing — never invent a
  date, time, name, table or venue.
- A real reservation is only ever created after an explicit spoken "yes"
  to a read-back confirmation, and only if services.booking_rules_engine
  accepts it — the same capacity/blackout/window/tier rules a web or
  staff booking is held to, not a separate bare insert.
- Both webhook paths are replay-safe against a Twilio retry: the initial
  webhook is deduped on CallSid (a retry rejoins the same call instead of
  forking a second parallel conversation), and a retry of an
  already-completed call's final gather turn re-serves the same recorded
  outcome instead of re-processing speech or double-booking.
- Business-hours check refuses politely when the venue is closed.
"""
from __future__ import annotations
import os
import re
import uuid
from datetime import datetime, timezone, timedelta, date
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response
from database import db
from services import voice_calls as vc


router = APIRouter()

MAX_INBOUND_TURNS = 5
# Twilio's own ASR confidence score (0.0-1.0) on the <Gather> result. Below
# this, the transcription is unreliable enough that acting on it risks
# inventing a wrong date/time/name — re-prompt instead of guessing.
MIN_SPEECH_CONFIDENCE = 0.55


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return f"INB-{uuid.uuid4().hex[:8].upper()}"


def _form_str(form: dict, key: str, default: str = "") -> str:
    """Twilio always sends these fields as plain strings, but starlette
    types a form field as `str | UploadFile` (multipart can carry a file
    part under any name) — coerce explicitly so a crafted request can't
    hand an UploadFile object into signature validation, ASR-confidence
    parsing, or audit logging further down."""
    value = form.get(key, default)
    return value if isinstance(value, str) else default


async def _audit(action: str, call_id: str, business_id: Optional[str], memo: str,
                  severity: str = "info", after: Optional[dict] = None) -> None:
    try:
        from services import audit_service
        await audit_service.log_event(
            entity_type="voice_call", entity_id=call_id, action=action,
            after=after, memo=memo, severity=severity,
            tags=["voice_inbound"],
        )
    except Exception:
        pass


# ─── Extractors ────────────────────────────────────────────────────────────
_WORD_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "a couple": 2, "couple": 2, "few": 3, "several": 4,
}

_AFFIRMATIVE = {"yes", "yeah", "yep", "yup", "correct", "confirm", "confirmed",
                "sounds good", "that's right", "thats right", "right", "sure", "please do"}
_NEGATIVE = {"no", "nope", "nah", "cancel", "not right", "wrong", "incorrect", "start over"}


def _is_affirmative(text: str) -> Optional[bool]:
    s = (text or "").strip().lower()
    if not s:
        return None
    if any(s == p or s.startswith(p + " ") or s.startswith(p + ",") for p in _AFFIRMATIVE):
        return True
    if any(s == p or s.startswith(p + " ") or s.startswith(p + ",") for p in _NEGATIVE):
        return False
    return None


def extract_party_size(text: str) -> Optional[int]:
    s = (text or "").lower()
    # Digit form: "table for 4", "4 people", "party of six"
    m = re.search(r"\b(\d{1,2})\b", s)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 20:
            return n
    for word, n in _WORD_NUM.items():
        if word in s:
            return n
    return None


def extract_time(text: str) -> Optional[str]:
    """Return an HH:MM 24h string, or None."""
    s = (text or "").lower()
    # "7pm", "7 pm", "7:30pm", "19:00", "half past six"
    m = re.search(r"\b(\d{1,2})[:.]?(\d{2})?\s*(am|pm)?\b", s)
    if m:
        h = int(m.group(1))
        mm = int(m.group(2) or 0)
        ampm = m.group(3)
        if ampm == "pm" and h < 12:
            h += 12
        if ampm == "am" and h == 12:
            h = 0
        if 0 <= h < 24 and 0 <= mm < 60:
            return f"{h:02d}:{mm:02d}"
    if "half past" in s:
        m = re.search(r"half past (\w+)", s)
        if m and m.group(1) in _WORD_NUM:
            h = _WORD_NUM[m.group(1)]
            if "morning" not in s and h < 8:
                h += 12
            return f"{h:02d}:30"
    return None


def extract_date(text: str, today: Optional[date] = None) -> Optional[str]:
    """Return an ISO YYYY-MM-DD, or None. Handles today/tomorrow/day-of-week.

    `today` should be the venue's own local date (services.venue_time), not
    the server's — a guest saying "tomorrow" near midnight means tomorrow
    in the restaurant's timezone, not the server's, and "today" said late
    in the evening server-UTC-time could otherwise resolve to a date that's
    already tomorrow at the venue. Defaults to server UTC date only for
    callers that don't have a business_id in scope yet."""
    s = (text or "").lower()
    if today is None:
        today = datetime.now(timezone.utc).date()
    if "tonight" in s or "today" in s or "this evening" in s:
        return today.isoformat()
    if "tomorrow" in s:
        return (today + timedelta(days=1)).isoformat()
    weekdays = ["monday", "tuesday", "wednesday", "thursday",
                "friday", "saturday", "sunday"]
    for i, w in enumerate(weekdays):
        if w in s:
            days_ahead = (i - today.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            return (today + timedelta(days=days_ahead)).isoformat()
    # explicit dd/mm or mm/dd — treat as dd/mm since AU-first
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", s)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        y = today.year
        if m.group(3):
            y = int(m.group(3))
            if y < 100:
                y += 2000
        try:
            return date(y, mo, d).isoformat()
        except Exception:
            return None
    return None


def extract_name(text: str) -> Optional[str]:
    """Simple heuristic — grab the token after 'name is' or after 'this is'."""
    s = (text or "").strip()
    m = re.search(r"(?:name(?:'s)? is|this is|it'?s|i'?m)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
                  s, re.IGNORECASE)
    if m:
        return m.group(1).title()
    # If the whole utterance is 1-3 title-case words, treat as a name.
    tokens = re.findall(r"[A-Za-z]+", s)
    if 1 <= len(tokens) <= 3 and all(t.isalpha() for t in tokens):
        return " ".join(t.capitalize() for t in tokens)
    return None


# ─── Business resolution from the dialled Twilio number ────────────────────
async def _resolve_business_by_dialled_number(to_number: str) -> dict:
    """Resolve the business (and, if configured, location) this call is
    actually for, from the Twilio "To" number the guest dialled — never an
    unfiltered "whichever business Mongo returns first" lookup.

    Returns {"ok": True, "business": {...}} on a clean single match, or
    {"ok": False, "reason": "..."} for anything else (no number configured
    at all, no match, an inactive business, or — because
    db.businesses.inboundVoiceNumber has no uniqueness guarantee on a
    partially-migrated deployment — more than one business claiming the
    same number). Ambiguous is refused, never guessed at.
    """
    if not to_number:
        return {"ok": False, "reason": "no_dialled_number"}
    matches = await db.businesses.find(
        {"inboundVoiceNumber": to_number}, {"_id": 0}
    ).to_list(5)
    if not matches:
        return {"ok": False, "reason": "unknown_number"}
    if len(matches) > 1:
        return {"ok": False, "reason": "ambiguous_number", "count": len(matches)}
    biz = matches[0]
    if biz.get("status") and biz["status"] not in ("active",):
        return {"ok": False, "reason": "inactive_business"}
    return {"ok": True, "business": biz}


async def _greeting_and_context(to_number: str) -> dict:
    """Fetch the resolved business's inbound-call greeting + open hours, or
    a resolution-failure reason if the dialled number can't be safely
    attributed to exactly one active business."""
    resolved = await _resolve_business_by_dialled_number(to_number)
    if not resolved["ok"]:
        return {"resolved": False, "reason": resolved["reason"]}
    biz = resolved["business"]
    inbound = (biz.get("inboundVoice") or {}) if isinstance(biz.get("inboundVoice"), dict) else {}
    name = biz.get("name") or "our restaurant"
    return {
        "resolved": True,
        "businessId": biz.get("id"),
        "locationId": biz.get("inboundVoiceLocationId"),
        "timezone": biz.get("timezone"),
        "businessName": name,
        "greeting": inbound.get("greeting")
                    or f"Thanks for calling {name}. I can help you book a table — how many people?",
        "closedMessage": inbound.get("closedMessage")
                    or f"Sorry, we're closed right now. Please try again during business hours, or book online at {biz.get('domain') or 'our website'}. Goodbye.",
        "hoursCheckEnabled": bool(inbound.get("hoursCheckEnabled", False)),
        "openHours": inbound.get("openHours") or {},  # {mon:{open,close,closed}, ...}
    }


def _is_open_now(open_hours: dict, tz_name: Optional[str] = None) -> bool:
    if not open_hours:
        return True
    from services.venue_time import venue_now
    weekdays = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    now = venue_now(tz_name)
    today = open_hours.get(weekdays[now.weekday()], {})
    if today.get("closed"):
        return False
    o, c = today.get("open"), today.get("close")
    if not o or not c:
        return True
    now_hm = now.strftime("%H:%M")
    return o <= now_hm < c


def _next_prompt(state: dict) -> str:
    if not state.get("partySize"):
        return "How many people would you like to book for?"
    if not state.get("date"):
        return "Great. What day were you thinking — tonight, tomorrow, or a specific date?"
    if not state.get("time"):
        return "And what time would suit you?"
    if not state.get("name"):
        return "Perfect. Can I grab a name for the booking?"
    return "Wonderful. Let me confirm."


def _confirmation_question(state: dict) -> str:
    return (f"So that's {state.get('partySize')} people for {state.get('name')} "
            f"on {state.get('date')} at {state.get('time')}. Shall I book that in? "
            "Please say yes to confirm, or no to start again.")


async def _load_call(call_id: str) -> Optional[dict]:
    return await db.voice_calls.find_one({"id": call_id}, {"_id": 0})


async def _finalise_booking(state: dict, call_id: str, caller: str) -> dict:
    """Runs the exact same booking-rules engine every other channel
    (web/staff/QR) is held to — capacity, blackout dates, booking window,
    party-size tiers/deposit/approval — instead of a bare insert_one that
    skips all of it. Returns {"ok": True, "reservationId": ...} or
    {"ok": False, "reason": "<guest-facing rejection message>"}."""
    ctx = state.get("_ctx", {}) or {}
    business_id = ctx.get("businessId")
    from services.booking_rules_engine import validate_and_enrich_booking, BookingRuleViolation, capacity_lock
    from services.cancellation_policy import snapshot_cutoff_hours
    try:
        async with capacity_lock(business_id, state["date"]):
            enrichment = await validate_and_enrich_booking(
                date=state["date"], time=state["time"], party_size=int(state["partySize"]),
                source="phone", business_id=business_id,
            )
            res_id = f"RES-{uuid.uuid4().hex[:8].upper()}"
            booking = {
                "id": res_id,
                "businessId": business_id,
                "locationId": ctx.get("locationId"),
                "date": state["date"],
                "time": state["time"],
                "partySize": int(state["partySize"]),
                "guestName": state.get("name") or "Phone booking",
                "guestPhone": caller,
                "status": "confirmed",
                "source": "phone",
                "callId": call_id,
                "createdAt": _now(),
                "cancellationCutoffHours": await snapshot_cutoff_hours(business_id),
                **enrichment,
            }
            await db.reservations.insert_one(booking)
    except BookingRuleViolation as e:
        return {"ok": False, "reason": str(e)}
    except Exception:
        return {"ok": False, "reason": "Sorry, I couldn't complete that booking. A team member will call you back."}
    return {"ok": True, "reservationId": res_id}


# ─── Twilio validation ─────────────────────────────────────────────────────
def _public_url(request: Request) -> str:
    override = os.environ.get("TWILIO_WEBHOOK_BASE_URL")
    if override:
        return f"{override.rstrip('/')}{request.url.path}"
    return str(request.url)


async def _verify(request: Request, form: dict) -> None:
    signature = request.headers.get("X-Twilio-Signature")
    if not vc.validate_signature(_public_url(request), form, signature):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")


def _end_call_twiml(message: str) -> Response:
    twiml = vc.say_and_gather_twiml(say=message, gather_action_url="", end_call=True)
    return Response(content=twiml, media_type="application/xml")


# ─── Webhooks ──────────────────────────────────────────────────────────────
@router.post("/voice/inbound")
async def voice_inbound(request: Request):
    """Twilio POSTs here when a customer dials a registered business number.
    We create a new voice_calls record and hand back the greeting + open
    Gather — or, on a Twilio retry of this exact call, rejoin the existing
    conversation instead of forking a second one."""
    form = dict(await request.form())
    await _verify(request, form)

    caller = _form_str(form, "From", "unknown")
    twilio_sid = _form_str(form, "CallSid")
    to_number = _form_str(form, "To")

    # Twilio retries a webhook that didn't answer inside its timeout — the
    # SAME CallSid arrives twice. Rejoin the call already in progress rather
    # than creating a second parallel conversation with its own call_id.
    if twilio_sid:
        existing = await db.voice_calls.find_one(
            {"twilioCallSid": twilio_sid, "direction": "inbound"}, {"_id": 0})
        if existing:
            base = str(request.base_url).rstrip("/")
            gather_url = f"{base}/api/voice/inbound/gather/{existing['id']}"
            twiml = vc.say_and_gather_twiml(say=existing["openingMessage"], gather_action_url=gather_url)
            return Response(content=twiml, media_type="application/xml")

    call_id = _uid()
    ctx = await _greeting_and_context(to_number)
    await _audit("call_started", call_id, ctx.get("businessId"),
                 f"Inbound call from {caller} to {to_number}")

    if not ctx.get("resolved"):
        # Fail closed on any resolution ambiguity — unknown number, inactive
        # business, or a duplicated mapping — rather than falling back to
        # "whichever business happens to be first", which would silently
        # misattribute the call (and any booking it creates) to the wrong
        # venue on any multi-tenant deployment.
        await _audit("business_resolution_failed", call_id, None,
                      f"Could not resolve business for dialled number {to_number}: {ctx.get('reason')}",
                      severity="warning")
        return _end_call_twiml(
            "Sorry, this number isn't set up to take bookings right now. Please try again later."
        )
    await _audit("business_resolved", call_id, ctx["businessId"],
                 f"Resolved to business {ctx['businessId']} ({ctx.get('businessName')})")

    if ctx["hoursCheckEnabled"] and not _is_open_now(ctx["openHours"], ctx.get("timezone")):
        return _end_call_twiml(ctx["closedMessage"])

    doc = {
        "id": call_id,
        "direction": "inbound",
        "purpose": "book_reservation",
        "phone": caller,
        "twilioCallSid": twilio_sid,
        "toNumber": to_number,
        "businessId": ctx["businessId"],
        "locationId": ctx.get("locationId"),
        "openingMessage": ctx["greeting"],
        "transcript": [{"speaker": "nua", "text": ctx["greeting"], "at": _now()}],
        "state": {"_ctx": {"businessId": ctx["businessId"], "locationId": ctx.get("locationId"),
                            "businessName": ctx["businessName"]}},
        "turns": 0,
        "status": "in_progress",
        "outcome": None,
        "createdAt": _now(),
    }
    await db.voice_calls.insert_one(dict(doc))

    base = str(request.base_url).rstrip("/")
    gather_url = f"{base}/api/voice/inbound/gather/{call_id}"
    twiml = vc.say_and_gather_twiml(say=ctx["greeting"], gather_action_url=gather_url)
    return Response(content=twiml, media_type="application/xml")


@router.post("/voice/inbound/gather/{call_id}")
async def voice_inbound_gather(call_id: str, request: Request):
    form = dict(await request.form())
    await _verify(request, form)

    call = await _load_call(call_id)
    if not call:
        return _end_call_twiml("Sorry, something went wrong. Goodbye.")

    # A Twilio retry landing on a turn that already finished (the call is
    # already completed) must not re-process the speech or run
    # _finalise_booking a second time — re-serve the exact outcome already
    # recorded instead.
    if call.get("status") == "completed":
        outcome = call.get("outcome")
        if outcome == "booked":
            confirmation = call.get("finalMessage") or "You're all booked in. Thanks for calling — goodbye."
        elif outcome == "handoff":
            confirmation = call.get("finalMessage") or "A team member will call you back shortly. Goodbye."
        else:
            confirmation = call.get("finalMessage") or "Thanks for calling — goodbye."
        return _end_call_twiml(confirmation)

    speech = _form_str(form, "SpeechResult").strip()
    try:
        confidence = float(_form_str(form, "Confidence", "1.0") or "1.0")
    except ValueError:
        confidence = 1.0
    state = dict(call.get("state") or {})
    turns = int(call.get("turns", 0)) + 1
    entry_guest = {"speaker": "guest", "text": speech, "at": _now(), "confidence": confidence}
    business_id = (state.get("_ctx") or {}).get("businessId")

    low_confidence = bool(speech) and confidence < MIN_SPEECH_CONFIDENCE

    # ── Awaiting the guest's spoken yes/no on the read-back confirmation ──
    if state.get("awaitingConfirmation") and not low_confidence:
        answer = _is_affirmative(speech)
        if answer is True:
            result = await _finalise_booking(state, call_id, call.get("phone") or "unknown")
            if result["ok"]:
                confirmation = "You're all booked in. We'll send a confirmation text if we have your number. Thanks for calling — goodbye."
                await _audit("booking_created", call_id, business_id,
                              f"Reservation {result['reservationId']} created from inbound call",
                              severity="notice", after={"reservationId": result["reservationId"]})
                await db.voice_calls.update_one({"id": call_id}, {"$set": {
                    "state": state, "turns": turns, "status": "completed",
                    "outcome": "booked", "bookingId": result["reservationId"],
                    "finalMessage": confirmation, "endedAt": _now(),
                }, "$push": {"transcript": {"$each": [entry_guest, {"speaker": "nua", "text": confirmation, "at": _now()}]}}})
                return _end_call_twiml(confirmation)
            else:
                # A real rule rejection (capacity, blackout, booking window,
                # etc.) — same message a web/staff booking would see, spoken
                # instead of shown, and never silently downgraded to "booked
                # anyway".
                rejection = f"{result['reason']} A team member will call you back to help find another time. Goodbye."
                await _audit("booking_rejected", call_id, business_id,
                              f"Booking rules rejected the call: {result['reason']}", severity="notice")
                await db.voice_calls.update_one({"id": call_id}, {"$set": {
                    "state": state, "turns": turns, "status": "completed",
                    "outcome": "rejected", "finalMessage": rejection, "endedAt": _now(),
                }, "$push": {"transcript": {"$each": [entry_guest, {"speaker": "nua", "text": rejection, "at": _now()}]}}})
                return _end_call_twiml(rejection)
        elif answer is False:
            # Never silently guess a correction — restart slot collection
            # cleanly rather than trying to infer which single field was wrong.
            ctx = state.get("_ctx", {})
            state = {"_ctx": ctx, "awaitingConfirmation": False}
            prompt = "No problem, let's start again. " + _next_prompt(state)
            base = str(request.base_url).rstrip("/")
            gather_url = f"{base}/api/voice/inbound/gather/{call_id}"
            await db.voice_calls.update_one({"id": call_id}, {"$set": {
                "state": state, "turns": turns,
            }, "$push": {"transcript": {"$each": [entry_guest, {"speaker": "nua", "text": prompt, "at": _now()}]}}})
            return Response(content=vc.say_and_gather_twiml(say=prompt, gather_action_url=gather_url),
                             media_type="application/xml")
        # Neither a clear yes nor no (or nothing heard) — ask again rather
        # than guessing which the guest meant.
        if turns >= MAX_INBOUND_TURNS:
            closing = "Sorry, I didn't catch that. A team member will call you back to finish the booking. Goodbye."
            await _audit("call_handoff", call_id, business_id, "Max turns reached awaiting yes/no confirmation")
            await db.voice_calls.update_one({"id": call_id}, {"$set": {
                "state": state, "turns": turns, "status": "completed",
                "outcome": "handoff", "finalMessage": closing, "endedAt": _now(),
            }, "$push": {"transcript": {"$each": [entry_guest, {"speaker": "nua", "text": closing, "at": _now()}]}}})
            return _end_call_twiml(closing)
        reprompt = "Sorry, I didn't catch that — was that a yes or a no?"
        base = str(request.base_url).rstrip("/")
        gather_url = f"{base}/api/voice/inbound/gather/{call_id}"
        await db.voice_calls.update_one({"id": call_id}, {"$set": {
            "state": state, "turns": turns,
        }, "$push": {"transcript": {"$each": [entry_guest, {"speaker": "nua", "text": reprompt, "at": _now()}]}}})
        return Response(content=vc.say_and_gather_twiml(say=reprompt, gather_action_url=gather_url),
                         media_type="application/xml")

    # ── Normal slot-filling ──
    if not low_confidence:
        if not state.get("partySize"):
            v = extract_party_size(speech)
            if v: state["partySize"] = v
        if not state.get("date"):
            from services.venue_time import venue_now_for_business
            venue_today = (await venue_now_for_business(business_id)).date()
            v = extract_date(speech, today=venue_today)
            if v: state["date"] = v
        if not state.get("time"):
            v = extract_time(speech)
            if v: state["time"] = v
        if not state.get("name"):
            v = extract_name(speech)
            if v: state["name"] = v

    complete = all(state.get(k) for k in ("partySize", "date", "time", "name"))
    exhausted = turns >= MAX_INBOUND_TURNS

    if complete:
        state["awaitingConfirmation"] = True
        confirmation = _confirmation_question(state)
        base = str(request.base_url).rstrip("/")
        gather_url = f"{base}/api/voice/inbound/gather/{call_id}"
        await db.voice_calls.update_one({"id": call_id}, {"$set": {
            "state": state, "turns": turns,
        }, "$push": {"transcript": {"$each": [entry_guest, {"speaker": "nua", "text": confirmation, "at": _now()}]}}})
        return Response(content=vc.say_and_gather_twiml(say=confirmation, gather_action_url=gather_url),
                         media_type="application/xml")

    if exhausted:
        closing = ("Sorry, I didn't quite catch everything. A team member will call you back "
                   "shortly to finish the booking. Thanks for calling — goodbye.")
        await _audit("call_handoff", call_id, business_id, "Max turns reached during slot-filling")
        await db.voice_calls.update_one({"id": call_id}, {"$set": {
            "state": state, "turns": turns, "status": "completed",
            "outcome": "handoff", "finalMessage": closing, "endedAt": _now(),
        }, "$push": {"transcript": {"$each": [entry_guest, {"speaker": "nua", "text": closing, "at": _now()}]}}})
        return _end_call_twiml(closing)

    prompt = ("Sorry, I didn't quite catch that — " + _next_prompt(state)) if low_confidence else _next_prompt(state)
    base = str(request.base_url).rstrip("/")
    gather_url = f"{base}/api/voice/inbound/gather/{call_id}"
    await db.voice_calls.update_one({"id": call_id}, {"$set": {
        "state": state, "turns": turns,
    }, "$push": {"transcript": {"$each": [entry_guest, {"speaker": "nua", "text": prompt, "at": _now()}]}}})
    twiml = vc.say_and_gather_twiml(say=prompt, gather_action_url=gather_url)
    return Response(content=twiml, media_type="application/xml")


# ─── Owner-facing config + inbox ───────────────────────────────────────────
from routes.auth import get_current_user  # noqa: E402


@router.get("/voice/inbound/status")
async def inbound_status(request: Request):
    user = await get_current_user(request)
    if user.get("role") not in ("owner", "manager"):
        raise HTTPException(403, "Owner or manager only")
    biz = await db.businesses.find_one({"id": user.get("businessId")}, {"_id": 0})
    biz = biz or {}
    inbound = (biz.get("inboundVoice") or {}) if isinstance(biz.get("inboundVoice"), dict) else {}
    return {
        "configured": vc.is_configured() and bool(biz.get("inboundVoiceNumber")),
        "inboundNumber": biz.get("inboundVoiceNumber"),
        "locationId": biz.get("inboundVoiceLocationId"),
        "greeting": inbound.get("greeting"),
        "closedMessage": inbound.get("closedMessage"),
        "hoursCheckEnabled": bool(inbound.get("hoursCheckEnabled", False)),
        "openHours": inbound.get("openHours") or {},
    }


@router.post("/voice/inbound/config")
async def inbound_config(request: Request):
    user = await get_current_user(request)
    if user.get("role") not in ("owner",):
        raise HTTPException(403, "Owner only")
    business_id = user.get("businessId")
    if not business_id:
        raise HTTPException(400, "No business on this account")
    body = await request.json()
    patch = {}
    for k in ("greeting", "closedMessage"):
        if k in body:
            patch[f"inboundVoice.{k}"] = body[k]
    if "hoursCheckEnabled" in body:
        patch["inboundVoice.hoursCheckEnabled"] = bool(body["hoursCheckEnabled"])
    if "openHours" in body:
        patch["inboundVoice.openHours"] = body["openHours"]
    if "phoneNumber" in body:
        number = (body["phoneNumber"] or "").strip()
        if number:
            # Refuse to save a number another business already claims —
            # the write-side half of "reject ambiguous number mappings",
            # so a duplicate can't even be created through this endpoint,
            # not just detected later at call time.
            clash = await db.businesses.find_one(
                {"inboundVoiceNumber": number, "id": {"$ne": business_id}}, {"_id": 0, "id": 1})
            if clash:
                raise HTTPException(409, "This phone number is already registered to another business")
        patch["inboundVoiceNumber"] = number or None
    if "locationId" in body:
        patch["inboundVoiceLocationId"] = body["locationId"]
    if patch:
        await db.businesses.update_one({"id": business_id}, {"$set": patch})
    return {"ok": True, "patch": patch}


@router.get("/voice/inbound/recent")
async def inbound_recent(request: Request, limit: int = 20):
    user = await get_current_user(request)
    if user.get("role") not in ("owner", "manager"):
        raise HTTPException(403, "Owner or manager only")
    limit = max(1, min(100, limit))
    from middleware.actor_context import tenant_scope_filter
    rows = await db.voice_calls.find(
        {"direction": "inbound", **tenant_scope_filter(user.get("businessId"))}, {"_id": 0}
    ).sort("createdAt", -1).to_list(limit)
    return rows


@router.get("/voice/inbound/active")
async def inbound_active(request: Request):
    """Currently in-progress inbound call(s), so the Bookings screen can
    show a live banner: 'NUA is on a call — party of 4 for Friday at 7pm…'
    with the transcript streaming in. Small payload, safe to poll every 2s."""
    user = await get_current_user(request)
    if user.get("role") not in ("owner", "manager", "cashier", "kitchen"):
        raise HTTPException(403, "Staff only")
    # Anything that started in the last 5 minutes and hasn't ended is live.
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    from middleware.actor_context import tenant_scope_filter
    rows = await db.voice_calls.find(
        {"direction": "inbound", "status": "in_progress", "createdAt": {"$gte": cutoff},
         **tenant_scope_filter(user.get("businessId"))},
        {"_id": 0}
    ).sort("createdAt", -1).to_list(5)
    # Compact projection — banner only needs the shape of the call, not history.
    def _slim(c: dict) -> dict:
        st = c.get("state") or {}
        return {
            "id": c.get("id"),
            "phone": c.get("phone"),
            "startedAt": c.get("createdAt"),
            "turns": c.get("turns", 0),
            "slots": {
                "partySize": st.get("partySize"),
                "date": st.get("date"),
                "time": st.get("time"),
                "name": st.get("name"),
            },
            "transcript": (c.get("transcript") or [])[-6:],  # last 3 exchanges
        }
    return [_slim(r) for r in rows]
