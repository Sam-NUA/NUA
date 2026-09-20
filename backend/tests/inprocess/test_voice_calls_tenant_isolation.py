"""routes/voice_calls.py's AI outbound voice calling (real Twilio calls to
customers, with full spoken transcripts) had zero businessId scoping:
initiate_call never stamped one, list_calls read every business's call
history/transcripts, get_call had no ownership check, and a caller could
place a call against another business's customer_id.
"""
import asyncio
from unittest.mock import patch

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Voice Test Owner", "email": email, "password": "VoiceTenantTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "VoiceTenantTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def test_voice_calls_are_scoped_and_owned_per_business(client, owner_headers):
    other = _login_as(client, owner_headers, email="voice.calls.other@nua.com", business_id="voice-calls-other-biz")
    call_doc = {
        "id": "CALL-OTHERBIZ1", "customerId": None, "phone": "+15551234567", "purpose": "custom",
        "context": {}, "openingMessage": "hi", "transcript": [], "turns": 0,
        "status": "completed", "outcome": "confirmed", "createdBy": "test",
        "createdAt": "2026-01-01T00:00:00+00:00", "businessId": "voice-calls-other-biz",
    }
    _run(db.voice_calls.insert_one(dict(call_doc)))
    try:
        mine_list = req(client, "GET", "/api/voice/calls", headers=owner_headers).json()
        assert not any(c["id"] == "CALL-OTHERBIZ1" for c in mine_list)

        cross_get = req(client, "GET", "/api/voice/calls/CALL-OTHERBIZ1", headers=owner_headers)
        assert cross_get.status_code == 404

        own_get = req(client, "GET", "/api/voice/calls/CALL-OTHERBIZ1", headers=other)
        assert own_get.status_code == 200
    finally:
        _run(db.voice_calls.delete_one({"id": "CALL-OTHERBIZ1"}))


def test_initiate_call_cannot_target_another_businesss_customer(client, owner_headers):
    other = _login_as(client, owner_headers, email="voice.init.other@nua.com", business_id="voice-init-other-biz")
    foreign_customer = {"id": "CUST-VOICE-FOREIGN", "businessId": "voice-init-other-biz",
                        "name": "Foreign Guest", "phone": "+15559876543"}
    _run(db.customers.insert_one(dict(foreign_customer)))
    try:
        with patch("services.voice_calls.is_configured", return_value=True), \
             patch("services.voice_calls.place_call", return_value="SID123"):
            cross = req(client, "POST", "/api/voice/calls", headers=owner_headers,
                       json={"customerId": "CUST-VOICE-FOREIGN", "purpose": "custom",
                             "context": {"message": "hi"}})
        assert cross.status_code == 404, "must not be able to call another business's customer"
    finally:
        _run(db.customers.delete_one({"id": "CUST-VOICE-FOREIGN"}))


def test_initiate_call_stamps_business_id(client, owner_headers):
    with patch("services.voice_calls.is_configured", return_value=True), \
         patch("services.voice_calls.place_call", return_value="SID456"):
        created = req(client, "POST", "/api/voice/calls", headers=owner_headers,
                     json={"phone": "+15550001111", "purpose": "custom", "context": {"message": "hi"}})
    assert created.status_code == 200, created.text[:200]
    call_id = created.json()["callId"]
    try:
        raw = _run(db.voice_calls.find_one({"id": call_id}, {"_id": 0}))
        assert raw is not None
        assert raw["businessId"] == "default"
    finally:
        _run(db.voice_calls.delete_one({"id": call_id}))
