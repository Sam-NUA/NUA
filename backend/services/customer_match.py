"""Shared customer lookup — used anywhere an AI flow (Concierge, Bookings
Inbox, Ash tools) needs to check whether a booking request is coming from
an existing customer before creating a reservation blind.

Previously the AI Concierge and Bookings Inbox both parsed a guest message
into a name/phone/reservation and inserted it straight into
db.reservations with no lookup at all — a returning VIP with allergies on
file would get treated exactly like a first-time walk-in, and a second
booking from the same guest would never get linked back to their profile.
"""
from __future__ import annotations
import re
import uuid
from datetime import datetime
from typing import Optional
from database import db
from middleware.actor_context import tenant_scope_filter, get_actor_context


def _digits(s: Optional[str]) -> str:
    return re.sub(r"\D", "", s or "")


async def find_matching_customer(*, name: Optional[str] = None, phone: Optional[str] = None,
                                   email: Optional[str] = None,
                                   business_id: Optional[str] = None) -> Optional[dict]:
    """Best-effort match against db.customers, most-confident signal first.

    Phone/email are checked before name because first names collide
    constantly ("John") — matching on those first would misattribute a
    stranger's booking to an existing customer's history.

    Scoped to the caller's own business (default: whichever business the
    current request's JWT belongs to) so a returning-guest match can never
    pull in — and leak the profile, allergies, VIP status and history of —
    another business's customer. Missing business context matches no customers.
    """
    if business_id is None:
        business_id = get_actor_context().get("businessId")
    scope = tenant_scope_filter(business_id)

    if email:
        row = await db.customers.find_one(
            {"$and": [scope, {"email": {"$regex": f"^{re.escape(email.strip())}$", "$options": "i"}}]},
            {"_id": 0})
        if row:
            return row

    phone_digits = _digits(phone)
    if len(phone_digits) >= 6:
        # Compare the last 8 digits so a guest reading their number aloud
        # without a country code / leading 0 still matches how it was
        # originally entered into the CRM.
        tail = phone_digits[-8:]
        candidates = await db.customers.find(scope, {"_id": 0}).to_list(5000)
        for row in candidates:
            if _digits(row.get("phone")).endswith(tail):
                return row

    if name and name.strip():
        row = await db.customers.find_one(
            {"$and": [scope, {"name": {"$regex": re.escape(name.strip()), "$options": "i"}}]},
            {"_id": 0})
        if row:
            return row

    return None


def guest_context(customer: dict) -> str:
    """A short natural-language brief so a returning guest's preferences
    make it into the reservation notes / the AI's reply instead of being
    silently dropped."""
    bits = []
    if customer.get("isVip"):
        bits.append("VIP guest")
    tier = customer.get("membershipTier")
    if tier and tier != "Bronze":
        bits.append(f"{tier} member")
    if customer.get("visits"):
        bits.append(f"{customer['visits']} past visit(s)")
    allergies = customer.get("allergies") or []
    if allergies:
        bits.append(f"allergies: {', '.join(allergies)}")
    dietary = customer.get("dietaryRestrictions") or []
    if dietary:
        bits.append(f"dietary: {', '.join(dietary)}")
    if customer.get("seatingPreference"):
        bits.append(f"prefers {customer['seatingPreference']} seating")
    return "; ".join(bits) if bits else "no notable history yet"


async def find_or_create_customer_by_phone(phone: str, *, name: str = "Guest",
                                             tag: str = "guest",
                                             business_id: Optional[str] = None) -> dict:
    """Resolves an existing db.customers record by phone, or creates a
    minimal real one — used by guest self-checkout flows (bill splitting)
    where a phone is all that's verified.

    Bypasses the Customer/CustomerCreate Pydantic models directly: both
    require an email, which a phone-only guest never has yet. The
    resulting document is otherwise a fully normal db.customers record —
    it earns loyalty points on this transaction and every one after, shows
    up in the CRM, and can pick up an email later the same way any
    phone-first identity already does elsewhere in this codebase. This is
    deliberately db.customers, not services/customer_identity.py's
    separate identity_customers collection — create_transaction's loyalty
    math reads/writes db.customers, so that's the record that actually
    needs to exist for a split-bill payment to earn points.

    business_id must be supplied by the caller (the guest's own split/
    table already resolved one) and is stamped on a newly created record —
    previously omitted entirely, so every guest-checkout customer created
    this way had no businessId at all, regardless of which business's
    table they paid from.
    """
    if not business_id:
        raise ValueError("business_id is required to create a customer")
    existing = await find_matching_customer(phone=phone, business_id=business_id)
    if existing:
        return existing
    doc = {
        "id": str(uuid.uuid4()), "name": name, "email": None, "phone": phone,
        "membershipTier": "Bronze", "totalSpent": 0.0, "visits": 0, "points": 0,
        "joinDate": datetime.utcnow().isoformat(), "tags": [tag],
        "isVip": False, "notes": "", "noShowCount": 0, "avgSpendPerVisit": 0.0,
        "storeCredit": 0.0, "businessId": business_id,
    }
    await db.customers.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc
