"""GET /api/analytics/today-pulse returns a 7-day sales trend for the Pulse
dashboard sparkline, not just today's single number."""
from datetime import datetime, timedelta, timezone

from conftest import req


def test_today_pulse_includes_a_7_day_trend(client, owner_headers):
    from database import db
    import asyncio
    import uuid

    async def seed():
        now = datetime.now(timezone.utc)
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()), "total": 123.45, "timestamp": now - timedelta(days=2),
            "status": "completed", "businessId": "default",
        })

    asyncio.get_event_loop().run_until_complete(seed())

    r = req(client, "GET", "/api/analytics/today-pulse", headers=owner_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "trend" in body
    assert len(body["trend"]) == 7
    for row in body["trend"]:
        assert "date" in row and "total" in row

    today = datetime.now(timezone.utc).date().isoformat()
    two_days_ago = (datetime.now(timezone.utc).date() - timedelta(days=2)).isoformat()
    assert body["trend"][-1]["date"] == today
    match = next(row for row in body["trend"] if row["date"] == two_days_ago)
    assert match["total"] >= 123.45
