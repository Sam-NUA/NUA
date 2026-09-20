"""AI outbound voice calls (Twilio).

This sandbox has no path to Twilio's real API, so "real" here means: the
Twilio Python SDK's own request-signing/validation algorithm is exercised
with a hand-computed HMAC (same as Twilio's public spec), and the actual
outbound `calls.create()` call is mocked at the one seam that would
otherwise need live network + a real phone number — everything else
(TwiML generation, transcript classification, conversation state, the
public-webhook signature gate) runs for real.
"""
import base64
import hashlib
import hmac

import pytest

from conftest import req


def _twilio_signature(auth_token: str, url: str, params: dict) -> str:
    """Twilio's documented X-Twilio-Signature algorithm: sort params by
    key, append each key+value (no separator) to the full URL, HMAC-SHA1
    with the auth token, base64-encode."""
    data = url + "".join(f"{k}{v}" for k, v in sorted(params.items()))
    digest = hmac.new(auth_token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


# --------------------------------------------------------------- service unit

def test_is_configured_false_without_env(monkeypatch):
    import services.voice_calls as vc
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TWILIO_FROM_PHONE", raising=False)
    assert vc.is_configured() is False


def test_is_configured_true_with_full_env(monkeypatch):
    import services.voice_calls as vc
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC123")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok123")
    monkeypatch.setenv("TWILIO_FROM_PHONE", "+15550001111")
    assert vc.is_configured() is True


def test_place_call_raises_when_not_configured(monkeypatch):
    import services.voice_calls as vc
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    with pytest.raises(vc.VoiceCallError):
        vc.place_call(to="+15551234567", twiml_url="https://x/twiml", status_callback_url="https://x/status")


def test_validate_signature_true_for_a_correctly_signed_request(monkeypatch):
    import services.voice_calls as vc
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "my-auth-token")
    url = "https://pos.example.com/api/voice/gather/CALL-1"
    params = {"SpeechResult": "yes that works", "CallSid": "CA999"}
    sig = _twilio_signature("my-auth-token", url, params)
    assert vc.validate_signature(url, params, sig) is True


def test_validate_signature_false_for_a_bad_signature(monkeypatch):
    import services.voice_calls as vc
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "my-auth-token")
    url = "https://pos.example.com/api/voice/gather/CALL-1"
    assert vc.validate_signature(url, {"SpeechResult": "yes"}, "not-the-real-signature") is False


def test_validate_signature_false_when_not_configured(monkeypatch):
    import services.voice_calls as vc
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    assert vc.validate_signature("https://x/y", {}, "anything") is False


def test_say_and_gather_twiml_opens_a_gather():
    import services.voice_calls as vc
    xml = vc.say_and_gather_twiml(say="Hello there", gather_action_url="https://x/gather/1")
    assert "<Gather" in xml and "Hello there" in xml and "<Hangup" in xml


def test_say_and_gather_twiml_hangs_up_when_ending():
    import services.voice_calls as vc
    xml = vc.say_and_gather_twiml(say="Goodbye", gather_action_url="", end_call=True)
    assert "<Gather" not in xml and "Goodbye" in xml and "<Hangup" in xml


# -------------------------------------------------------------- POST /voice/calls

def test_create_call_requires_auth(anon):
    r = req(anon, "POST", "/api/voice/calls", json={"phone": "+15551234567", "purpose": "custom"})
    assert r.status_code == 401


def test_create_call_refuses_when_not_configured(client, owner_headers, monkeypatch):
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TWILIO_FROM_PHONE", raising=False)
    r = req(client, "POST", "/api/voice/calls", headers=owner_headers,
            json={"phone": "+15551234567", "purpose": "custom", "context": {"message": "hi"}})
    assert r.status_code == 500
    assert "aren't set up" in r.json()["detail"].lower() or "isn't set up" in r.json()["detail"].lower()


def test_create_call_400s_without_phone_or_customer(client, owner_headers, monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC123")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok123")
    monkeypatch.setenv("TWILIO_FROM_PHONE", "+15550001111")
    r = req(client, "POST", "/api/voice/calls", headers=owner_headers, json={"purpose": "custom"})
    assert r.status_code == 400


def test_create_call_404s_for_unknown_customer(client, owner_headers, monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC123")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok123")
    monkeypatch.setenv("TWILIO_FROM_PHONE", "+15550001111")
    r = req(client, "POST", "/api/voice/calls", headers=owner_headers,
            json={"customerId": "no-such-customer", "purpose": "custom"})
    assert r.status_code == 404


def test_create_call_places_a_real_call_and_stores_the_doc(client, owner_headers, monkeypatch):
    import asyncio
    import routes.voice_calls as rvc
    from database import db

    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC123")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok123")
    monkeypatch.setenv("TWILIO_FROM_PHONE", "+15550001111")

    placed = {}

    def fake_place_call(*, to, twiml_url, status_callback_url):
        placed["to"] = to
        placed["twiml_url"] = twiml_url
        return "CAxxxxfakesid"

    monkeypatch.setattr(rvc.vc, "place_call", fake_place_call)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(db.customers.insert_one({"businessId": "default",
        "id": "CUST-VOICE-1", "name": "Priya Singh", "email": "priya@example.com",
        "phone": "+61412345678", "isVip": True,
    }))
    try:
        r = req(client, "POST", "/api/voice/calls", headers=owner_headers,
                json={"customerId": "CUST-VOICE-1", "purpose": "confirm_booking",
                      "context": {"partySize": 4, "date": "2026-08-20", "time": "19:00"}})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "ringing"
        assert body["twilioCallSid"] == "CAxxxxfakesid"
        assert placed["to"] == "+61412345678"

        doc = loop.run_until_complete(db.voice_calls.find_one({"id": body["callId"]}, {"_id": 0}))
        assert doc["purpose"] == "confirm_booking"
        assert "Priya" in doc["openingMessage"]
        assert "4 people on 2026-08-20 at 19:00" in doc["openingMessage"]
        assert doc["status"] == "ringing"
    finally:
        loop.run_until_complete(db.customers.delete_one({"id": "CUST-VOICE-1"}))
        loop.run_until_complete(db.voice_calls.delete_many({"customerId": "CUST-VOICE-1"}))


# --------------------------------------------------------- Twilio webhooks

def test_twiml_endpoint_rejects_an_unsigned_request(client):
    r = client.post("/api/voice/twiml/CALL-NOPE", data={})
    assert r.status_code == 403


def test_twiml_endpoint_says_the_opening_message_when_signed(client, monkeypatch):
    import asyncio
    import routes.voice_calls as rvc
    from database import db

    monkeypatch.setattr(rvc.vc, "validate_signature", lambda *a, **kw: True)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(db.voice_calls.insert_one({"businessId": "default",
        "id": "CALL-TWIML-1", "openingMessage": "Hi Sam, this is NUA calling to confirm your booking.",
        "status": "ringing", "transcript": [], "turns": 0,
    }))
    try:
        r = client.post("/api/voice/twiml/CALL-TWIML-1", data={"CallSid": "CA1"})
        assert r.status_code == 200
        assert "Hi Sam" in r.text
        assert "<Gather" in r.text
    finally:
        loop.run_until_complete(db.voice_calls.delete_one({"id": "CALL-TWIML-1"}))


def test_gather_endpoint_confirms_and_ends_the_call(client, monkeypatch):
    import asyncio
    import routes.voice_calls as rvc
    from database import db

    monkeypatch.setattr(rvc.vc, "validate_signature", lambda *a, **kw: True)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(db.voice_calls.insert_one({"businessId": "default",
        "id": "CALL-GATHER-1", "openingMessage": "Confirm?", "status": "in_progress",
        "transcript": [], "turns": 0,
    }))
    try:
        r = client.post("/api/voice/gather/CALL-GATHER-1",
                         data={"SpeechResult": "Yes that works great", "CallSid": "CA1"})
        assert r.status_code == 200
        assert "<Hangup" in r.text
        assert "<Gather" not in r.text

        doc = loop.run_until_complete(db.voice_calls.find_one({"id": "CALL-GATHER-1"}, {"_id": 0}))
        assert doc["status"] == "completed"
        assert doc["outcome"] == "confirmed"
        assert any(t["text"] == "Yes that works great" for t in doc["transcript"])
    finally:
        loop.run_until_complete(db.voice_calls.delete_one({"id": "CALL-GATHER-1"}))


def test_gather_endpoint_asks_again_when_unclear_then_gives_up(client, monkeypatch):
    import asyncio
    import routes.voice_calls as rvc
    from database import db

    monkeypatch.setattr(rvc.vc, "validate_signature", lambda *a, **kw: True)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(db.voice_calls.insert_one({"businessId": "default",
        "id": "CALL-UNCLEAR-1", "openingMessage": "Confirm?", "status": "in_progress",
        "transcript": [], "turns": 0,
    }))
    try:
        r1 = client.post("/api/voice/gather/CALL-UNCLEAR-1", data={"SpeechResult": "umm what"})
        assert "<Gather" in r1.text  # still open — asks again

        doc = loop.run_until_complete(db.voice_calls.find_one({"id": "CALL-UNCLEAR-1"}, {"_id": 0}))
        assert doc["turns"] == 1
        assert doc["status"] == "in_progress"

        # Ride out the remaining turns until MAX_GATHER_TURNS forces a hangup
        # even without ever getting a clear yes/no.
        r2 = client.post("/api/voice/gather/CALL-UNCLEAR-1", data={"SpeechResult": "not sure"})
        r3 = client.post("/api/voice/gather/CALL-UNCLEAR-1", data={"SpeechResult": "still not sure"})
        assert "<Hangup" in r3.text
        doc = loop.run_until_complete(db.voice_calls.find_one({"id": "CALL-UNCLEAR-1"}, {"_id": 0}))
        assert doc["status"] == "completed"
        assert doc["outcome"] == "unclear"
    finally:
        loop.run_until_complete(db.voice_calls.delete_one({"id": "CALL-UNCLEAR-1"}))


def test_status_endpoint_marks_unreachable_on_no_answer(client, monkeypatch):
    import asyncio
    import routes.voice_calls as rvc
    from database import db

    monkeypatch.setattr(rvc.vc, "validate_signature", lambda *a, **kw: True)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(db.voice_calls.insert_one({"businessId": "default", "id": "CALL-STATUS-1", "status": "ringing"}))
    try:
        r = client.post("/api/voice/status/CALL-STATUS-1", data={"CallStatus": "no-answer"})
        assert r.status_code == 200
        doc = loop.run_until_complete(db.voice_calls.find_one({"id": "CALL-STATUS-1"}, {"_id": 0}))
        assert doc["status"] == "unreachable"
    finally:
        loop.run_until_complete(db.voice_calls.delete_one({"id": "CALL-STATUS-1"}))


# --------------------------------------------------------------- Ash tool

def test_call_customer_tool_is_registered_and_requires_approval():
    from services.nua_tools import TOOLS
    tool = TOOLS["call_customer"]
    assert tool.default_permission == "approval"
    assert tool.module == "Marketing"


def test_call_customer_tool_errors_cleanly_without_a_public_base_url(monkeypatch):
    import asyncio
    from services.nua_tools import TOOLS
    monkeypatch.delenv("TWILIO_WEBHOOK_BASE_URL", raising=False)
    monkeypatch.delenv("BACKEND_PUBLIC_URL", raising=False)
    out = asyncio.get_event_loop().run_until_complete(
        TOOLS["call_customer"].execute({"phone": "+15551234567", "purpose": "custom"}))
    assert "error" in out
