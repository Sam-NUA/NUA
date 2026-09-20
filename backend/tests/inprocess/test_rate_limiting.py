"""Remediation of the final readiness audit's High finding on
server.py's RateLimitMiddleware: /api/public/* and /api/table/* were
excluded from rate limiting entirely, so an anonymous caller could hit
booking/waitlist creation, menu reads, or table order placement at
unlimited rate. Fixed with PREFIX_OVERRIDES (stricter limits for
booking/waitlist writes and the Twilio voice webhook) and a
GUEST_DEFAULT_LIMIT for everything else under those two prefixes.

These tests prove: (1) the new limits actually activate and return 429
once exceeded, (2) a bucket resets once its window has fully elapsed
rather than staying tripped forever, and (3) the deliberately generous
/api/voice/inbound limit does not incorrectly block genuine Twilio retry
traffic (a shared-IP pool that can fire several requests per call in
quick succession).
"""
import asyncio
import time as time_module

from database import db


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_public_book_endpoint_returns_429_once_its_limit_is_exceeded(anon):
    for i in range(10):
        r = anon.post("/api/public/book", json={})
        assert r.status_code != 429, f"request {i} was rate-limited too early"
    r = anon.post("/api/public/book", json={})
    assert r.status_code == 429, "the 11th request within the window must be rejected"
    assert "Rate limit exceeded" in r.json()["detail"]


def test_rate_limit_bucket_resets_after_the_window_elapses(anon, monkeypatch):
    import server
    real_time = time_module.time
    clock = {"now": real_time()}
    monkeypatch.setattr(server, "time", lambda: clock["now"])

    for _ in range(10):
        r = anon.post("/api/public/join-waitlist", json={})
        assert r.status_code != 429
    r = anon.post("/api/public/join-waitlist", json={})
    assert r.status_code == 429, "limit should be tripped before the window advances"

    clock["now"] += 61  # window is 60s
    r = anon.post("/api/public/join-waitlist", json={})
    assert r.status_code != 429, "the bucket must reset once the window has fully elapsed"


def test_twilio_retries_are_not_blocked_by_the_voice_inbound_rate_limit(anon, monkeypatch):
    import services.voice_calls as vc
    monkeypatch.setattr(vc, "validate_signature", lambda *a, **k: True)
    try:
        for i in range(20):  # well under the 60/60s limit; a real Twilio retry burst
            r = anon.post("/api/voice/inbound", data={
                "From": "+61400000199", "CallSid": f"CA-RL-RETRY-{i}", "To": "+61400099999",
            })
            assert r.status_code != 429, (
                f"request {i} was blocked by rate limiting — Twilio retries must not trip this"
            )
    finally:
        _run(db.voice_calls.delete_many({"twilioCallSid": {"$regex": "^CA-RL-RETRY-"}}))


def test_two_tables_guest_traffic_does_not_share_a_rate_limit_bucket(anon):
    """Several guests at one venue commonly share a single WiFi NAT's public
    IP — the guest-default bucket is keyed by table_id (not just IP) so one
    table's ordering traffic can't throttle another table's guests."""
    for _ in range(60):
        r = anon.get("/api/table/rl-test-table-a/menu")
        assert r.status_code != 429
    # Table A's bucket is now exhausted; table B must be unaffected.
    r = anon.get("/api/table/rl-test-table-b/menu")
    assert r.status_code != 429, "a different table must not share table A's exhausted bucket"
    r = anon.get("/api/table/rl-test-table-a/menu")
    assert r.status_code == 429, "table A's own bucket should still be exhausted"
