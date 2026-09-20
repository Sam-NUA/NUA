"""routes/phase_ef.py's POST /phone-agent/simulate built its LLM system
prompt's "Today is ..." date from datetime.now().date() — the SERVER's own
clock — regardless of which business the caller belongs to. Fixed to use
services/venue_time.py's business-timezone-aware helper instead, the same
fix already applied to the real Twilio inbound webhook
(routes/voice_inbound.py). Found during the Trust Release final readiness
audit.

emergentintegrations isn't installed in this sandbox (see
test_phone_agent_order_and_channel_orders_tenant_isolation.py's own
docstring), so the LLM call itself is stubbed via sys.modules rather than
exercised for real — this test only needs to capture the system_message
LlmChat was constructed with, not actually classify anything.
"""
import asyncio
import sys
import types

from conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _install_fake_emergentintegrations(captured):
    class _FakeUserMessage:
        def __init__(self, text=""):
            self.text = text

    class _FakeLlmChat:
        def __init__(self, api_key=None, session_id=None, system_message=""):
            captured["system_message"] = system_message

        def with_model(self, *args, **kwargs):
            return self

        async def send_message(self, *args, **kwargs):
            return '{"intent": "other", "details": {}}'

    chat_mod = types.ModuleType("emergentintegrations.llm.chat")
    chat_mod.LlmChat = _FakeLlmChat
    chat_mod.UserMessage = _FakeUserMessage
    llm_mod = types.ModuleType("emergentintegrations.llm")
    llm_mod.chat = chat_mod
    root_mod = types.ModuleType("emergentintegrations")
    root_mod.llm = llm_mod
    sys.modules["emergentintegrations"] = root_mod
    sys.modules["emergentintegrations.llm"] = llm_mod
    sys.modules["emergentintegrations.llm.chat"] = chat_mod


def test_simulate_call_system_prompt_uses_the_venues_own_timezone_not_the_servers(client, owner_headers, monkeypatch):
    import services.venue_time as venue_time
    from datetime import datetime

    async def _fixed_venue_now(business_id):
        return datetime(2026, 3, 15, 10, 0, 0)

    monkeypatch.setattr(venue_time, "venue_now_for_business", _fixed_venue_now)

    captured = {}
    _install_fake_emergentintegrations(captured)
    try:
        r = req(client, "POST", "/api/phone-agent/simulate", headers=owner_headers, json={
            "caller": "+61400000009", "transcript": "Just calling to ask about your opening hours.",
        })
        assert r.status_code == 200, r.text
        assert "system_message" in captured, "the LLM must have been invoked (the fake import must have been used)"
        assert "Today is 2026-03-15" in captured["system_message"], (
            f"the system prompt's date must come from the fixed venue-local 'now' (2026-03-15), "
            f"not the server's real clock — got: {captured['system_message'][:200]}"
        )
    finally:
        for mod in ("emergentintegrations", "emergentintegrations.llm", "emergentintegrations.llm.chat"):
            sys.modules.pop(mod, None)
