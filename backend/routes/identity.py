"""Customer identity API — the free base layer plus the owner-only migration
that splits the legacy combined "Loyalty & CRM" module into per-add-on
enrichment tables, all pointing at the same Customer id."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from database import db
from deps import get_user, require_owner
from services.customer_identity import (
    addon_enabled, create_or_match, ensure_guest_profile, ensure_loyalty_account,
    get_subscription, _now,
)
from middleware.actor_context import tenant_scope_filter

router = APIRouter()


@router.get("/identity/entitlements")
async def entitlements(user: dict = Depends(get_user)):
    return await get_subscription(user.get("businessId"))


@router.put("/identity/entitlements")
async def set_entitlements(data: dict, user: dict = Depends(require_owner)):
    from services.tenant_settings import set_setting
    flags = data.get("feature_flags") or {}
    # customer_identity is not a switch — silently keep it on no matter
    # what a client sends.
    flags["customer_identity"] = True
    value = {
        "addons_enabled": data.get("addons_enabled") or [],
        "feature_flags": flags,
    }
    await set_setting("venue_subscription", value, user.get("businessId"))
    return value


def _venue_scope_filter(business_id: Optional[str]) -> dict:
    """create_or_match already had a venue_id concept — just never wired to
    anything real, so every caller left it at the default "main" and every
    business's identity_customers ended up sharing one venue. This matches
    tenant_scope_filter's own backward-compat shape (match this business,
    or the untagged/legacy state) but keyed on venue_id instead of
    businessId, and treats "main" as that legacy/untagged sentinel — the
    value every pre-existing record actually has — rather than a real venue."""
    if not business_id:
        return {}
    return {"$or": [{"venue_id": business_id}, {"venue_id": {"$exists": False}}, {"venue_id": "main"}]}


def _venue_owns(doc_venue_id: Optional[str], business_id: Optional[str]) -> bool:
    if not business_id or not doc_venue_id or doc_venue_id == "main":
        return True
    return doc_venue_id == business_id


@router.get("/identity/customers")
async def search_identity(search: Optional[str] = None, user: dict = Depends(get_user)):
    query = _venue_scope_filter(user.get("businessId"))
    if search:
        text_match = {"$or": [
            {"name": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
            {"phone": {"$regex": search, "$options": "i"}},
        ]}
        query = {"$and": [query, text_match]} if query else text_match
    return await db.identity_customers.find(query, {"_id": 0}).sort("last_seen_at", -1).to_list(500)


@router.get("/identity/customers/{customer_id}")
async def get_identity(customer_id: str, user: dict = Depends(get_user)):
    """The identity record plus whichever add-ons' enrichment is enabled.
    Reads degrade gracefully: a disabled add-on's data simply isn't included —
    never a hard dependency between add-ons."""
    base = await db.identity_customers.find_one({"id": customer_id}, {"_id": 0})
    if not base or not _venue_owns(base.get("venue_id"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Customer not found")
    out = {"customer": base}
    if await addon_enabled("bookings_guests.enabled"):
        out["guest_profile"] = await db.guest_profiles.find_one({"customer_id": customer_id}, {"_id": 0})
    if await addon_enabled("loyalty.enabled"):
        out["loyalty_account"] = await db.loyalty_accounts.find_one({"customer_id": customer_id}, {"_id": 0})
    if await addon_enabled("punch_card.enabled"):
        out["punch_card"] = await db.punch_cards.find_one({"customer_id": customer_id}, {"_id": 0})
    return out


@router.post("/identity/segments/preview")
async def segment_preview(definition: dict, user: dict = Depends(get_user)):
    """Marketing segments read Customer, and optionally LoyaltyAccount /
    GuestProfile fields IF those add-ons are enabled — but must degrade to
    Customer-only filtering when they're not (rule 3 of the identity spec)."""
    if not await addon_enabled("marketing.enabled"):
        raise HTTPException(status_code=403, detail="Marketing add-on not enabled")

    min_visits = int(definition.get("min_visits", 0) or 0)
    source = definition.get("source")
    query = _venue_scope_filter(user.get("businessId"))
    if min_visits > 0:
        query["visit_count"] = {"$gte": min_visits}
    if source:
        query["source"] = source
    customers = await db.identity_customers.find(query, {"_id": 0}).to_list(5000)

    degraded = []
    min_tier = definition.get("min_loyalty_tier")
    if min_tier:
        if await addon_enabled("loyalty.enabled"):
            order = ["Bronze", "Silver", "Gold", "Platinum"]
            floor = order.index(min_tier) if min_tier in order else 0
            # One batched $in lookup instead of one find_one() per customer —
            # this ran a query per row on every segment preview keystroke.
            cust_ids = [c["id"] for c in customers]
            tier_by_customer = {}
            if cust_ids:
                accts = await db.loyalty_accounts.find(
                    {"customer_id": {"$in": cust_ids}}, {"_id": 0, "customer_id": 1, "tier": 1}
                ).to_list(len(cust_ids))
                tier_by_customer = {a["customer_id"]: a.get("tier", "Bronze") for a in accts}
            keep = []
            for c in customers:
                tier = tier_by_customer.get(c["id"], "Bronze")
                if order.index(tier) >= floor if tier in order else False:
                    keep.append(c)
            customers = keep
        else:
            degraded.append("min_loyalty_tier ignored — loyalty add-on not enabled")

    tag = definition.get("guest_tag")
    if tag:
        if await addon_enabled("bookings_guests.enabled"):
            cust_ids = [c["id"] for c in customers]
            tags_by_customer = {}
            if cust_ids:
                profs = await db.guest_profiles.find(
                    {"customer_id": {"$in": cust_ids}}, {"_id": 0, "customer_id": 1, "tags": 1}
                ).to_list(len(cust_ids))
                tags_by_customer = {p["customer_id"]: (p.get("tags") or []) for p in profs}
            customers = [c for c in customers if tag in tags_by_customer.get(c["id"], [])]
        else:
            degraded.append("guest_tag ignored — bookings-guests add-on not enabled")

    return {"count": len(customers), "customers": customers[:100], "degraded": degraded}


@router.post("/identity/migrate-legacy-crm")
async def migrate_legacy_crm(user: dict = Depends(require_owner)):
    """Split pilot data from the old combined Loyalty & CRM customers
    collection: notes/tags/visit-history enrichment goes to GuestProfile
    (bookings-guests), points/tier go to LoyaltyAccount (loyalty) — both
    keyed to one new base Customer identity. Idempotent: rows already
    migrated (matched by phone/email) are enriched, not duplicated."""
    biz = user.get("businessId")
    legacy = await db.customers.find(tenant_scope_filter(biz), {"_id": 0}).to_list(10000)
    migrated = 0
    skipped = 0
    for c in legacy:
        identity = await create_or_match(
            phone=c.get("phone"), email=c.get("email"), name=c.get("name"),
            source="pos_checkout", venue_id=biz or "main",
        )
        if identity is None:
            skipped += 1
            continue
        cid = identity["id"]

        profile = await ensure_guest_profile(cid)
        await db.guest_profiles.update_one(
            {"customer_id": cid},
            {"$set": {
                "notes": c.get("notes", "") or profile.get("notes", ""),
                "tags": sorted(set((profile.get("tags") or []) + (c.get("tags") or []))),
                "is_vip": bool(c.get("isVip")),
                "allergies": c.get("allergies") or [],
                "dietary_restrictions": c.get("dietaryRestrictions") or [],
                "seating_preference": c.get("seatingPreference"),
                "visit_history_reservation_ids": c.get("reservationIds") or [],
                "legacy_customer_id": c.get("id"),
            }},
        )

        await ensure_loyalty_account(cid)
        await db.loyalty_accounts.update_one(
            {"customer_id": cid},
            {"$set": {
                "points_balance": int(c.get("points", 0) or 0),
                "tier": c.get("membershipTier", "Bronze"),
                "legacy_customer_id": c.get("id"),
            }},
        )

        # Gift cards sold against the legacy customer follow the identity, not
        # the profile — they're loyalty-side value.
        await db.gift_cards.update_many(
            {"customerId": c.get("id")}, {"$set": {"identity_customer_id": cid}}
        )

        # Keep the legacy row linked so old code paths still resolve.
        await db.customers.update_one({**tenant_scope_filter(user.get("businessId")), "id": c["id"]}, {"$set": {"identityCustomerId": cid}})
        migrated += 1

    return {"migrated": migrated, "skipped_no_contact": skipped, "at": _now()}
