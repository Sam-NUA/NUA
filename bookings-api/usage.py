"""Usage metering for wholesale invoicing. Every billable action is logged
against partner_id + venue_id; the monthly report aggregates them for the
invoice run. Deliberately separate from NUA's consumer price list — partner
wholesale rates are a different catalog entirely."""
import uuid
from datetime import datetime, timezone

from database import db


async def log_usage(partner_id: str, venue_id: str, event_type: str, test: bool = False, session=None) -> None:
    # Sandbox traffic is logged for observability but excluded from invoices.
    await db.usage_events.insert_one({
        "id": f"USG-{uuid.uuid4().hex[:10].upper()}",
        "partner_id": partner_id,
        "venue_id": venue_id,
        "type": event_type,
        "test": test,
        "ts": datetime.now(timezone.utc).isoformat(),
    }, session=session)


async def monthly_report(month: str) -> list[dict]:
    """month is 'YYYY-MM'. Returns one row per partner: billable bookings
    created and distinct active venues that month."""
    prefix = month
    events = await db.usage_events.find(
        {"ts": {"$gte": f"{prefix}-01"}, "test": {"$ne": True}},
        {"_id": 0},
    ).to_list(100000)
    events = [e for e in events if e["ts"][:7] == prefix]

    by_partner: dict[str, dict] = {}
    for e in events:
        row = by_partner.setdefault(e["partner_id"], {
            "partner_id": e["partner_id"], "month": prefix,
            "bookings_created": 0, "venues": set(),
        })
        if e["type"] == "booking.created":
            row["bookings_created"] += 1
        row["venues"].add(e["venue_id"])

    out = []
    for row in by_partner.values():
        partner = await db.partners.find_one({"id": row["partner_id"]}, {"_id": 0, "name": 1, "billing_tier": 1})
        out.append({
            "partner_id": row["partner_id"],
            "partner_name": (partner or {}).get("name", "?"),
            "billing_tier": (partner or {}).get("billing_tier", "standard"),
            "month": prefix,
            "bookings_created": row["bookings_created"],
            "active_venues": len(row["venues"]),
        })
    out.sort(key=lambda r: -r["bookings_created"])
    return out
