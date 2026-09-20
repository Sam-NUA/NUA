"""Remediation of the final readiness audit's High findings on Voice POS
inbound calling (routes/voice_inbound.py):

1. Both webhook paths were unreachable — not on server.py's public
   allowlist, so Twilio's unauthenticated POST 401'd before the route's
   own signature check ever ran. Fixed: exactly POST /api/voice/inbound
   (exact path) and POST /api/voice/inbound/gather/{call_id} (a prefix
   that can't match the owner/staff-facing sub-paths) are now public;
   everything else in this file still requires a real session.
2. The business greeting/context was resolved via
   db.businesses.find_one({}) — no filter at all, always the first
   business in the collection regardless of which number was dialled.
   Fixed: resolved from Twilio's own "To" number against a verified,
   owner-configured, uniquely-indexed mapping — refusing (not guessing)
   on an unknown or ambiguous number.
3. Voice-created reservations bypassed services.booking_rules_engine
   entirely (a bare db.reservations.insert_one) — no capacity, blackout,
   or booking-window checks a web/staff booking is held to. Fixed: routes
   through validate_and_enrich_booking, behind a mandatory spoken "yes"
   confirmation turn, with ASR-confidence gating and Twilio-retry replay
   protection (CallSid dedup on the opening webhook, "already completed"
   short-circuit on the gather webhook) and audit logging of every
   call-lifecycle event.

Twilio's own request-signature cryptography is unit-tested directly in
test_voice_calls.py; these tests monkeypatch it to True/False as needed
so they can focus on the business logic behind it.
"""
import asyncio

from database import db


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Voice Inbound Test Owner", "email": email, "password": "VoiceInboundTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "VoiceInboundTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _make_business(biz_id, *, number=None, name="Voice Test Biz"):
    doc = {"id": biz_id, "name": name, "status": "active", "slug": biz_id.lower()}
    if number:
        doc["inboundVoiceNumber"] = number
    _run(db.businesses.insert_one(doc))


def _cleanup(*, biz_ids=(), call_ids=(), reservation_ids=()):
    if biz_ids:
        _run(db.businesses.delete_many({"id": {"$in": list(biz_ids)}}))
    if call_ids:
        _run(db.voice_calls.delete_many({"id": {"$in": list(call_ids)}}))
    if reservation_ids:
        _run(db.reservations.delete_many({"id": {"$in": list(reservation_ids)}}))
    _run(db.audit_events.delete_many({"entityId": {"$in": list(call_ids)}}))


def test_inbound_webhook_is_reachable_with_no_auth_token(anon, monkeypatch):
    """The core reachability fix: Twilio carries no JWT at all — this must
    not 401 at the middleware before the route's own signature check runs."""
    import services.voice_calls as vc
    monkeypatch.setattr(vc, "validate_signature", lambda *a, **k: True)
    r = anon.post("/api/voice/inbound", data={"From": "+61400000000", "CallSid": "CA-REACH-1", "To": "+61499999999"})
    assert r.status_code != 401, f"inbound webhook must be reachable with no auth token — got {r.status_code}"


def test_inbound_webhook_rejects_an_unsigned_request(anon, monkeypatch):
    import services.voice_calls as vc
    monkeypatch.setattr(vc, "validate_signature", lambda *a, **k: False)
    r = anon.post("/api/voice/inbound", data={"From": "+61400000000", "CallSid": "CA-BADSIG-1"})
    assert r.status_code == 403


def test_staff_only_voice_inbound_endpoints_still_require_auth(anon):
    assert anon.get("/api/voice/inbound/status").status_code == 401
    assert anon.post("/api/voice/inbound/config", json={}).status_code == 401
    assert anon.get("/api/voice/inbound/recent").status_code == 401
    assert anon.get("/api/voice/inbound/active").status_code == 401


def test_unknown_dialled_number_is_refused_not_misattributed(anon, monkeypatch):
    import services.voice_calls as vc
    monkeypatch.setattr(vc, "validate_signature", lambda *a, **k: True)
    r = anon.post("/api/voice/inbound", data={
        "From": "+61400000001", "CallSid": "CA-UNKNOWN-1", "To": "+61400000000",  # nobody registered this
    })
    assert r.status_code == 200  # valid TwiML response, just a polite decline
    assert "isn't set up" in r.text or "not set up" in r.text.lower()
    assert _run(db.voice_calls.find_one({"twilioCallSid": "CA-UNKNOWN-1"})) is None, (
        "an unresolvable number must not create a call/booking session at all"
    )


def test_two_businesses_with_different_numbers_are_never_mixed_up(client, owner_headers, monkeypatch):
    """The actual exploit the old db.businesses.find_one({}) allowed: with
    more than one business in the deployment, an inbound call for Business
    B's number must resolve to Business B, never to whichever business
    happens to be first in the collection (which could easily be A)."""
    import services.voice_calls as vc
    monkeypatch.setattr(vc, "validate_signature", lambda *a, **k: True)
    biz_a, biz_b = "voice-two-biz-a", "voice-two-biz-b"
    num_a, num_b = "+61411111111", "+61422222222"
    _make_business(biz_a, number=num_a, name="Business A")
    _make_business(biz_b, number=num_b, name="Business B")
    call_id = None
    try:
        r = client.post("/api/voice/inbound", data={
            "From": "+61400000002", "CallSid": "CA-TWOBIZ-1", "To": num_b,
        })
        assert r.status_code == 200
        call = _run(db.voice_calls.find_one({"twilioCallSid": "CA-TWOBIZ-1"}, {"_id": 0}))
        assert call is not None
        call_id = call["id"]
        assert call["businessId"] == biz_b, (
            f"a call to Business B's number must resolve to Business B, got {call['businessId']}"
        )
    finally:
        _cleanup(biz_ids=[biz_a, biz_b], call_ids=[call_id] if call_id else [])


def test_ambiguous_duplicate_number_mapping_is_refused(client, monkeypatch):
    """A legacy/corrupted deployment where two businesses somehow claim the
    same number (the unique index prevents this going forward, but must be
    defended against for data that predates it) must refuse the call
    outright, never silently pick one business over the other."""
    import services.voice_calls as vc
    monkeypatch.setattr(vc, "validate_signature", lambda *a, **k: True)
    biz_c, biz_d = "voice-dup-biz-c", "voice-dup-biz-d"
    shared_number = "+61433333333"
    _make_business(biz_c, number=shared_number, name="Dup Biz C")
    # The unique index this same pass added (services/db_indexes.py) would
    # otherwise refuse to let a second business claim the same number at
    # insert time — correct for new writes, but this test exists to prove
    # the read-side defensive check for data that predates that index (a
    # migration-era duplicate). Drop it here to simulate that, and restore
    # it in the finally block so no other test in this session runs
    # without it.
    _run(db.businesses.drop_index("inboundVoiceNumber_1"))
    try:
        _make_business(biz_d, number=shared_number, name="Dup Biz D")
        r = client.post("/api/voice/inbound", data={
            "From": "+61400000003", "CallSid": "CA-AMBIG-1", "To": shared_number,
        })
        assert r.status_code == 200
        assert _run(db.voice_calls.find_one({"twilioCallSid": "CA-AMBIG-1"})) is None, (
            "an ambiguous number mapping must refuse the call, not create a session for either business"
        )
    finally:
        _cleanup(biz_ids=[biz_c, biz_d])
        _run(db.businesses.create_index("inboundVoiceNumber", unique=True, sparse=True))


def test_a_retried_opening_webhook_rejoins_the_same_call_not_a_second_one(client, monkeypatch):
    import services.voice_calls as vc
    monkeypatch.setattr(vc, "validate_signature", lambda *a, **k: True)
    biz_id, number = "voice-retry-biz-1", "+61444444444"
    _make_business(biz_id, number=number)
    try:
        first = client.post("/api/voice/inbound", data={
            "From": "+61400000004", "CallSid": "CA-RETRY-1", "To": number,
        })
        second = client.post("/api/voice/inbound", data={
            "From": "+61400000004", "CallSid": "CA-RETRY-1", "To": number,  # Twilio retry: same CallSid
        })
        assert first.status_code == 200 and second.status_code == 200
        calls = _run(db.voice_calls.find({"twilioCallSid": "CA-RETRY-1"}, {"_id": 0}).to_list(10))
        assert len(calls) == 1, "a retried opening webhook must not fork a second parallel conversation"
    finally:
        _cleanup(biz_ids=[biz_id], call_ids=[c["id"] for c in _run(
            db.voice_calls.find({"twilioCallSid": "CA-RETRY-1"}, {"_id": 0}).to_list(10))])


def test_low_confidence_speech_does_not_populate_a_slot(client, monkeypatch):
    import services.voice_calls as vc
    monkeypatch.setattr(vc, "validate_signature", lambda *a, **k: True)
    biz_id, number = "voice-confidence-biz-1", "+61455555555"
    _make_business(biz_id, number=number)
    call_id = None
    try:
        opening = client.post("/api/voice/inbound", data={
            "From": "+61400000005", "CallSid": "CA-CONF-1", "To": number,
        })
        call = _run(db.voice_calls.find_one({"twilioCallSid": "CA-CONF-1"}, {"_id": 0}))
        call_id = call["id"]
        # A garbled, low-confidence "four" must not be trusted as party size.
        r = client.post(f"/api/voice/inbound/gather/{call_id}",
                        data={"SpeechResult": "four", "Confidence": "0.2"})
        assert r.status_code == 200
        updated = _run(db.voice_calls.find_one({"id": call_id}, {"_id": 0}))
        assert not updated["state"].get("partySize"), (
            "a low-confidence utterance must not be trusted into a booking slot"
        )
    finally:
        _cleanup(biz_ids=[biz_id], call_ids=[call_id] if call_id else [])


def test_completing_all_slots_asks_for_confirmation_before_booking(client, monkeypatch):
    """The mandatory-confirmation fix: reaching all four slots must not
    immediately insert a reservation — it must ask a yes/no question first."""
    import services.voice_calls as vc
    monkeypatch.setattr(vc, "validate_signature", lambda *a, **k: True)
    biz_id, number = "voice-confirm-biz-1", "+61466666666"
    _make_business(biz_id, number=number)
    call_id = None
    try:
        client.post("/api/voice/inbound", data={"From": "+61400000006", "CallSid": "CA-CONFIRM-1", "To": number})
        call = _run(db.voice_calls.find_one({"twilioCallSid": "CA-CONFIRM-1"}, {"_id": 0}))
        call_id = call["id"]

        # Seed the four slots directly rather than via several natural-
        # language turns: extract_party_size/extract_time/extract_name's
        # regex heuristics overlap on plain-digit and short-phrase input
        # (e.g. a bare "4" satisfies both extract_party_size and
        # extract_time; "half past six" satisfies both extract_time and
        # extract_party_size's word-number table) in ways that are
        # pre-existing and out of this pass's scope to redesign. This test
        # is about the confirmation-gate transition, not the NLP slot
        # extraction (covered separately by the low-confidence test above),
        # so it drives that transition directly and deterministically.
        state = {"_ctx": call["state"]["_ctx"], "partySize": 4, "date": "2026-09-20",
                 "time": "19:00", "name": "John Smith"}
        _run(db.voice_calls.update_one({"id": call_id}, {"$set": {"state": state}}))
        r = client.post(f"/api/voice/inbound/gather/{call_id}", data={"SpeechResult": "", "Confidence": "1.0"})
        assert r.status_code == 200
        assert "confirm" in r.text.lower() or "shall i book" in r.text.lower()

        no_reservation_yet = _run(db.reservations.find_one({"callId": call_id}))
        assert no_reservation_yet is None, "a reservation must not be created before the guest says yes"

        updated = _run(db.voice_calls.find_one({"id": call_id}, {"_id": 0}))
        assert updated["state"].get("awaitingConfirmation") is True
        assert updated["status"] == "in_progress"
    finally:
        _cleanup(biz_ids=[biz_id], call_ids=[call_id] if call_id else [],
                 reservation_ids=[r["id"] for r in _run(db.reservations.find({"callId": call_id}, {"_id": 0}).to_list(5))] if call_id else [])


def test_a_spoken_yes_creates_a_real_reservation_via_the_rules_engine(client, monkeypatch):
    import services.voice_calls as vc
    monkeypatch.setattr(vc, "validate_signature", lambda *a, **k: True)
    biz_id, number = "voice-book-biz-1", "+61477777777"
    _make_business(biz_id, number=number)
    call_id = None
    reservation_id = None
    try:
        client.post("/api/voice/inbound", data={"From": "+61400000007", "CallSid": "CA-BOOK-1", "To": number})
        call = _run(db.voice_calls.find_one({"twilioCallSid": "CA-BOOK-1"}, {"_id": 0}))
        call_id = call["id"]
        # Slots seeded directly (see the confirmation test's own comment on
        # why) — this test is about the rules-engine integration and
        # replay-safety on the confirmation turn, not the NLP extraction.
        from datetime import datetime, timedelta, timezone
        future_date = (datetime.now(timezone.utc) + timedelta(days=7)).date().isoformat()
        state = {"_ctx": call["state"]["_ctx"], "partySize": 2, "date": future_date,
                 "time": "19:00", "name": "Jane Doe", "awaitingConfirmation": True}
        _run(db.voice_calls.update_one({"id": call_id}, {"$set": {"state": state}}))
        r = client.post(f"/api/voice/inbound/gather/{call_id}", data={"SpeechResult": "yes", "Confidence": "1.0"})
        assert r.status_code == 200

        updated = _run(db.voice_calls.find_one({"id": call_id}, {"_id": 0}))
        assert updated["status"] == "completed"
        assert updated["outcome"] == "booked"
        reservation_id = updated.get("bookingId")
        assert reservation_id

        res = _run(db.reservations.find_one({"id": reservation_id}, {"_id": 0}))
        assert res is not None
        assert res["source"] == "phone"
        assert res["businessId"] == biz_id
        assert res["partySize"] == 2

        # And a retry of this exact final webhook must not double-book.
        retry = client.post(f"/api/voice/inbound/gather/{call_id}", data={"SpeechResult": "yes", "Confidence": "1.0"})
        assert retry.status_code == 200
        count = _run(db.reservations.count_documents({"callId": call_id}))
        assert count == 1, "a Twilio retry of an already-completed call must not create a second reservation"

        audits = _run(db.audit_events.find({"entityId": call_id}, {"_id": 0}).to_list(20))
        actions = {a["action"] for a in audits}
        assert "created" in actions or len(audits) > 0, "call lifecycle events must be audited"
    finally:
        _cleanup(biz_ids=[biz_id], call_ids=[call_id] if call_id else [],
                 reservation_ids=[reservation_id] if reservation_id else [])


def test_a_spoken_date_is_resolved_in_the_venues_own_timezone_not_the_servers(client, monkeypatch):
    """extract_date's "today" used to always be datetime.now(timezone.utc) —
    the SERVER's own clock — regardless of which business the caller was
    talking to. A guest saying "tomorrow" near midnight in their own
    venue's timezone could get a booking dated one day off from what they
    meant. Fixed: the gather webhook now resolves "today" via
    services.venue_time's business-timezone-aware helper before calling
    extract_date. Found during the Trust Release final readiness audit."""
    import services.voice_calls as vc
    monkeypatch.setattr(vc, "validate_signature", lambda *a, **k: True)

    import services.venue_time as venue_time
    from datetime import datetime

    async def _fixed_venue_now(business_id):
        # A fixed, deterministic "venue-local now" independent of whatever
        # day this test actually runs on.
        return datetime(2026, 3, 15, 10, 0, 0)

    monkeypatch.setattr(venue_time, "venue_now_for_business", _fixed_venue_now)

    biz_id, number = "voice-tz-date-biz-1", "+61488888888"
    _make_business(biz_id, number=number)
    call_id = None
    try:
        client.post("/api/voice/inbound", data={"From": "+61400000008", "CallSid": "CA-TZDATE-1", "To": number})
        call = _run(db.voice_calls.find_one({"twilioCallSid": "CA-TZDATE-1"}, {"_id": 0}))
        call_id = call["id"]

        r = client.post(f"/api/voice/inbound/gather/{call_id}",
                         data={"SpeechResult": "tomorrow", "Confidence": "1.0"})
        assert r.status_code == 200
        updated = _run(db.voice_calls.find_one({"id": call_id}, {"_id": 0}))
        assert updated["state"].get("date") == "2026-03-16", (
            f"'tomorrow' relative to the fixed venue-local now (2026-03-15) must resolve to "
            f"2026-03-16, got {updated['state'].get('date')}"
        )
    finally:
        _cleanup(biz_ids=[biz_id], call_ids=[call_id] if call_id else [])
