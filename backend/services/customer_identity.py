"""Customer identity — the free, ungated base layer.

One rule, enforced everywhere: every add-on's records foreign-key to the base
Customer identity (identity_customers.id) and NEVER to another add-on's
records. Bookings' GuestProfile, Loyalty's LoyaltyAccount, and Punch-card's
PunchCard all point at the same Customer id; none of them may point at each
other. A feature that wants another add-on's data reads it at query time
behind a feature-flag check and degrades gracefully when that add-on is off.

customer_identity itself is not a sellable feature: always on, never billed,
never shown as a toggle.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from database import db

VALID_SOURCES = ("pos_checkout", "booking", "loyalty_signup", "marketing_optin")

DEFAULT_SUBSCRIPTION = {
    "addons_enabled": ["bookings-guests", "loyalty", "marketing"],
    "feature_flags": {
        "customer_identity": True,   # invariant — never toggled, never billed
        "bookings_guests.enabled": True,
        "loyalty.enabled": True,
        "punch_card.enabled": False,
        "marketing.enabled": True,
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def get_subscription(business_id: Optional[str] = None) -> dict:
    """Defaults business_id from the request's actor context (same
    pattern as notification_service.send()) so existing callers don't
    need editing — this used to be one add-on subscription/entitlement
    record shared by every business on the deployment; see
    services/tenant_settings.py."""
    from services.tenant_settings import get_setting
    value = await get_setting("venue_subscription", business_id)
    sub = value if isinstance(value, dict) else dict(DEFAULT_SUBSCRIPTION)
    # customer_identity can never be switched off, whatever is stored.
    sub.setdefault("feature_flags", {})["customer_identity"] = True
    return sub


async def addon_enabled(flag: str) -> bool:
    sub = await get_subscription()
    return bool(sub.get("feature_flags", {}).get(flag, False))


async def _any_identity_consumer_enabled() -> bool:
    """Base-only venues (no bookings/loyalty/punch-card/marketing) get no
    identity records at all — no point collecting data nothing will use."""
    flags = (await get_subscription()).get("feature_flags", {})
    return any(flags.get(f) for f in (
        "bookings_guests.enabled", "loyalty.enabled", "punch_card.enabled", "marketing.enabled",
    ))


async def create_or_match(phone: Optional[str] = None, email: Optional[str] = None,
                          name: Optional[str] = None, source: str = "pos_checkout",
                          venue_id: str = "main") -> Optional[dict]:
    """Create-or-match a Customer identity by phone/email. Match precedence:
    phone first (most stable in hospitality), then email. Returns the identity
    record, or None when nothing identifying was supplied."""
    phone = (phone or "").strip() or None
    email = (email or "").strip().lower() or None
    if not phone and not email:
        return None
    if source not in VALID_SOURCES:
        source = "pos_checkout"

    existing = None
    if phone:
        existing = await db.identity_customers.find_one({"venue_id": venue_id, "phone": phone}, {"_id": 0})
    if not existing and email:
        existing = await db.identity_customers.find_one({"venue_id": venue_id, "email": email}, {"_id": 0})

    if existing:
        patch = {"last_seen_at": _now()}
        # Fill in whichever identifier we just learned.
        if phone and not existing.get("phone"):
            patch["phone"] = phone
        if email and not existing.get("email"):
            patch["email"] = email
        if name and not existing.get("name"):
            patch["name"] = name
        await db.identity_customers.update_one(
            {"id": existing["id"]}, {"$set": patch, "$inc": {"visit_count": 1}}
        )
        existing.update(patch)
        existing["visit_count"] = existing.get("visit_count", 0) + 1
        return existing

    record = {
        "id": f"IDC-{uuid.uuid4().hex[:10].upper()}",
        "venue_id": venue_id,
        "phone": phone,
        "email": email,
        "name": name,
        "first_seen_at": _now(),
        "last_seen_at": _now(),
        "visit_count": 1,
        "source": source,
    }
    await db.identity_customers.insert_one(dict(record))
    return record


async def record_touchpoint(phone: Optional[str], email: Optional[str],
                            name: Optional[str], source: str) -> Optional[dict]:
    """The one entry point modules call. Skips entirely for base-only venues."""
    if not await _any_identity_consumer_enabled():
        return None
    return await create_or_match(phone=phone, email=email, name=name, source=source)


# ---- Add-on record helpers (each FK's ONLY to the Customer id) ----

async def ensure_guest_profile(customer_id: str) -> dict:
    """bookings-guests add-on enrichment. 1:1 with Customer."""
    existing = await db.guest_profiles.find_one({"customer_id": customer_id}, {"_id": 0})
    if existing:
        return existing
    profile = {"customer_id": customer_id, "notes": "", "tags": [], "created_at": _now()}
    await db.guest_profiles.insert_one(dict(profile))
    return profile


async def ensure_loyalty_account(customer_id: str) -> dict:
    """loyalty add-on. Depends ONLY on Customer — never on GuestProfile."""
    existing = await db.loyalty_accounts.find_one({"customer_id": customer_id}, {"_id": 0})
    if existing:
        return existing
    account = {"customer_id": customer_id, "points_balance": 0, "tier": "Bronze", "enrolled_at": _now()}
    await db.loyalty_accounts.insert_one(dict(account))
    return account


async def ensure_punch_card(customer_id: str, reward_threshold: int = 10) -> dict:
    """punch-card-loyalty add-on. Same rule: FK to Customer only.

    KNOWN GAP, found while unifying the guest-facing loyalty view
    (LoyaltyGuestPortal.jsx) across the loyalty engine/badges/subscriptions
    systems: nothing anywhere in the codebase ever increments `punches`
    after this creates the card at 0 — there's no "add a punch" action on
    a POS sale or any other trigger. The card, the migration path
    (routes/identity.py's migrate-legacy-crm), and the IdentitySettings.jsx
    toggle are all real, but the feature can't actually be earned by a
    guest. Deliberately left OUT of the unified guest passport rather than
    shown as a permanently-stuck "0 punches" — showing a dead progress
    bar would be actively misleading. Wiring a real earn trigger is a
    separate, larger feature decision (how many punches per visit, which
    categories qualify) not attempted here.
    """
    existing = await db.punch_cards.find_one({"customer_id": customer_id}, {"_id": 0})
    if existing:
        return existing
    card = {"customer_id": customer_id, "punches": 0, "reward_threshold": reward_threshold, "created_at": _now()}
    await db.punch_cards.insert_one(dict(card))
    return card
