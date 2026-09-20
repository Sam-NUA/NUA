from fastapi import APIRouter, HTTPException, Depends
from deps import get_user, require_owner
from database import db
from middleware.actor_context import tenant_scope_filter
from typing import Optional
import re
import uuid
from datetime import datetime, timezone

router = APIRouter(prefix="/business")

# ============ MULTI-BUSINESS / MULTI-TENANT ============


async def _unique_slug(name: str, exclude_id: Optional[str] = None) -> str:
    """URL-safe handle for the public online-ordering storefront
    (/order-online?business=<slug>) — friendlier than the raw BIZ-xxxxxxxx id.
    Not globally enforced at the DB level (no unique index; this is a
    small, owner-driven collection), just checked-and-retried here so two
    businesses named the same thing don't collide. `exclude_id` lets a
    business keep its own slug when re-slugging on rename/edit instead of
    always bumping onto "-2"."""
    base = re.sub(r"[^a-z0-9]+", "-", (name or "business").lower()).strip("-") or "business"
    slug = base
    n = 2
    while True:
        query = {"slug": slug}
        if exclude_id:
            query["id"] = {"$ne": exclude_id}
        if not await db.businesses.find_one(query, {"_id": 1}):
            return slug
        slug = f"{base}-{n}"
        n += 1


async def _owned_business_or_404(business_id: str, user: dict) -> dict:
    """Fetch a business the caller actually owns, or 404.

    require_owner only checks the caller's role — it says nothing about
    *which* business a path-supplied business_id belongs to. Every route
    below that takes business_id as a path parameter needs this before
    touching that business's data, the same way list_businesses already
    scopes to {"ownerId": user["id"]} rather than returning every business.
    404 (not 403) so this doesn't confirm to an unauthorized caller that
    the business_id even exists.

    seed_default_business() below stamps the bootstrap "default" business
    with ownerId="system", not a real user — it predates multi-business
    support, back when there was only ever one. Its real owner is whoever
    the seeded admin account (or anyone since assigned) actually has as
    their own businessId, so that's checked as a fallback rather than
    permanently locking every single-business deployment out of its own
    business record."""
    business = await db.businesses.find_one({"id": business_id}, {"_id": 0})
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    owner_id = business.get("ownerId")
    owns_it = owner_id == user["id"] or (owner_id == "system" and user.get("businessId") == business_id)
    if not owns_it:
        raise HTTPException(status_code=404, detail="Business not found")
    return business

@router.post("/create")
async def create_business(data: dict, user: dict = Depends(require_owner)):
    """Create a new business (Owner only)"""

    requested_slug_base = re.sub(r"[^a-z0-9]+", "-", (data.get("name", "") or "business").lower()).strip("-")
    slug = await _unique_slug(data.get("name", ""))
    business = {
        "id": f"BIZ-{str(uuid.uuid4())[:8].upper()}",
        "slug": slug,
        "name": data.get("name", ""),
        "type": data.get("type", "restaurant"),  # restaurant, cafe, bar, catering, retail, salon, services — see frontend/src/lib/businessVertical.js
        "abn": data.get("abn", ""),
        "address": data.get("address", ""),
        "phone": data.get("phone", ""),
        "email": data.get("email", ""),
        "timezone": data.get("timezone", "Australia/Sydney"),
        "currency": data.get("currency", "AUD"),
        "taxRate": data.get("taxRate", 10),
        "ownerId": user["id"],
        "status": "active",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        # False until the first-login setup wizard finishes (name/ABN/
        # vertical) — see frontend/src/pages/OnboardingWizard.jsx. Never
        # flips back to False once true; changing vertical afterward goes
        # through the ordinary Multi-Business settings, not the wizard.
        "onboardingComplete": False,
        "settings": {
            "autoGratuity": data.get("autoGratuity", 0),
            "serviceCharge": data.get("serviceCharge", 0),
            "bookingEnabled": True,
            "tableOrderingEnabled": True,
        }
    }
    await db.businesses.insert_one(business)
    business.pop("_id", None)
    # Tell the caller if the requested name collided with an existing
    # business's slug and got silently suffixed, so the UI can surface it
    # instead of leaving the owner to notice a "-2" in their storefront link.
    business["slugAdjusted"] = bool(requested_slug_base) and slug != requested_slug_base
    return business

@router.get("/list")
async def list_businesses(user: dict = Depends(require_owner)):
    """List all businesses for current owner"""
    businesses = await db.businesses.find({"ownerId": user["id"]}, {"_id": 0}).to_list(100)
    return businesses

@router.get("/{business_id}")
async def get_business(business_id: str, user: dict = Depends(require_owner)):
    return await _owned_business_or_404(business_id, user)

@router.put("/{business_id}")
async def update_business(business_id: str, data: dict, user: dict = Depends(require_owner)):
    await _owned_business_or_404(business_id, user)
    allowed = {"name", "type", "abn", "address", "phone", "email", "timezone", "currency", "taxRate", "settings", "slug", "onboardingComplete"}
    update_data = {k: v for k, v in data.items() if k in allowed}

    slug_adjusted = False
    if "slug" in update_data:
        requested_base = re.sub(r"[^a-z0-9]+", "-", (update_data["slug"] or "").lower()).strip("-")
        final_slug = await _unique_slug(update_data["slug"], exclude_id=business_id)
        slug_adjusted = bool(requested_base) and final_slug != requested_base
        update_data["slug"] = final_slug

    result = await db.businesses.find_one_and_update(
        {"id": business_id}, {"$set": update_data}, return_document=True
    )
    result.pop("_id", None)
    result["slugAdjusted"] = slug_adjusted
    return result

@router.get("/{business_id}/export")
async def export_business_data(business_id: str, collection: Optional[str] = None, user: dict = Depends(require_owner)):
    """Export all data for a specific business (Owner only)"""

    business = await _owned_business_or_404(business_id, user)

    collections_to_export = ["products", "transactions", "customers", "reservations",
                              "kitchen_orders", "expenses", "suppliers", "feedback",
                              "members", "vouchers"]

    if collection and collection in collections_to_export:
        collections_to_export = [collection]

    # tenant_scope_filter, not a bare {"businessId": business_id} fallback to
    # {} on empty results — this used to re-query with NO filter at all
    # whenever a business genuinely had zero docs in some collection (a
    # brand-new business with no transactions yet, say), handing the
    # exporting owner every OTHER business's data in that collection too.
    # tenant_scope_filter's own fail-open behavior (matching untagged legacy
    # rows) still covers the pre-tenant-stamping case this fallback was
    # trying to serve, without ever crossing into another business's data.
    biz_or_untagged = tenant_scope_filter(business_id)
    export_data = {"business": business, "exportedAt": datetime.now(timezone.utc).isoformat()}
    for coll_name in collections_to_export:
        coll = db[coll_name]
        docs = await coll.find(biz_or_untagged, {"_id": 0}).to_list(10000)
        export_data[coll_name] = {"count": len(docs), "data": docs}

    return export_data

@router.get("/{business_id}/summary")
async def get_business_summary(business_id: str, user: dict = Depends(require_owner)):
    """Quick summary stats for a business"""
    await _owned_business_or_404(business_id, user)

    # Scoped to this business_id specifically (not the caller's own token
    # businessId — an owner with multiple businesses needs to pull summaries
    # for businesses other than the one they're currently acting as), via
    # tenant_scope_filter (reused here rather than hand-rolled, so this
    # inherits any future change to the fallback) which still applies its
    # fail-open-to-untagged-legacy-data semantics so a not-yet-backfilled
    # deployment shows its real numbers instead of zero.
    biz_or_untagged = tenant_scope_filter(business_id)
    txns = await db.transactions.find(biz_or_untagged, {"_id": 0}).to_list(10000)
    products = await db.products.find(biz_or_untagged, {"_id": 0}).to_list(1000)
    customers = await db.customers.find(biz_or_untagged, {"_id": 0}).to_list(10000)
    # The member-portal router was removed rounds ago (nothing in this
    # codebase writes db.members anymore) — this count is permanently
    # frozen historical data from before that removal, not a live number.
    # Left in rather than dropped so a deployment with old member rows
    # doesn't lose that figure from its summary; new deployments will
    # always show 0 here.
    members = await db.members.find(biz_or_untagged, {"_id": 0}).to_list(10000)
    staff = await db.auth_users.find({"businessId": business_id}, {"_id": 0, "password_hash": 0}).to_list(100)
    # Online orders are tagged with businessId (added alongside the
    # per-business storefront slug) — biz_or_untagged still applies the
    # same fail-open-to-untagged-legacy-data rule as every other query on
    # this page, so pre-slug orders keep counting rather than vanishing.
    online_orders = await db.online_orders.find(biz_or_untagged, {"_id": 0, "paymentStatus": 1}).to_list(10000)
    payment_counts = {"paid": 0, "refunded": 0, "refund_failed": 0}
    for o in online_orders:
        status = o.get("paymentStatus")
        if status in payment_counts:
            payment_counts[status] += 1

    return {
        "businessId": business_id,
        "totalRevenue": round(sum(t.get("total", 0) for t in txns), 2),
        "totalTransactions": len(txns),
        "totalProducts": len(products),
        "totalCustomers": len(customers),
        "totalMembers": len(members),
        "totalStaff": len(staff),
        "onlineOrdersPaid": payment_counts["paid"],
        "onlineOrdersRefunded": payment_counts["refunded"],
        "onlineOrdersRefundFailed": payment_counts["refund_failed"],
    }

# Seed default business
async def seed_default_business():
    existing = await db.businesses.find_one({"id": "default"})
    if existing:
        if "onboardingComplete" not in existing:
            # Backfill for a "default" business created before this field
            # existed. Without this, App.js's `!business.onboardingComplete`
            # check traps the owner behind the first-run OnboardingWizard on
            # every login forever — the wizard *is* the whole shell (see
            # App.js's ProtectedRoutes), so there's no Settings page they
            # could otherwise reach to fix it themselves. Runs on every
            # startup (idempotent — a no-op once the field is set), so an
            # already-affected deployment self-heals on its next restart
            # with no manual step required.
            await db.businesses.update_one({"id": "default"}, {"$set": {"onboardingComplete": True}})
    else:
        await db.businesses.insert_one({
            "id": "default",
            "slug": "default",
            "name": "NUA Restaurant",
            "type": "restaurant",
            "abn": "",
            "address": "",
            "phone": "",
            "email": "info@nua.com",
            "timezone": "Australia/Sydney",
            "currency": "AUD",
            "taxRate": 10,
            "ownerId": "system",
            "status": "active",
            "createdAt": datetime.now(timezone.utc).isoformat(),
            # Grandfathered in as already-set-up — the wizard is for NEW
            # businesses created going forward (see create_business above),
            # not retroactively imposed on the seeded demo/default tenant
            # every existing deployment already depends on.
            "onboardingComplete": True,
            "settings": {"autoGratuity": 0, "serviceCharge": 0, "bookingEnabled": True, "tableOrderingEnabled": True}
        })


# Collections that get a businessId at write time now (see
# middleware/actor_context.py + entity_service.py) but predate that fix —
# every document in them either has no businessId field at all, or has it
# explicitly set to null (stamped_insert's setdefault wrote null before the
# actor context ever had a real value to give it). Backfilling them to
# "default" is the prerequisite for turning on any read-side tenant
# filtering: filtering today, before this runs, would make untagged data
# disappear rather than isolate it.
_BACKFILL_COLLECTIONS = ["customers", "vouchers", "wallet_ledger", "loyalty_ledger", "members",
                          "transactions", "refunds", "products", "expenses", "suppliers", "promotions",
                          "categories", "online_orders"]


@router.post("/backfill-tenant")
async def backfill_tenant(user: dict = Depends(require_owner)):
    """Retired: bulk assignment to default was not ownership evidence."""
    raise HTTPException(status_code=410, detail="Use the support-authorized ownership migration with evidence review")


# Every collection that can hold rows written by the startup seeders
# (seed_demo_customers, seed_alcohol_catalog) tagged isDemo=True at insert
# time. Anything a real venue enters themselves never gets this flag, so
# purging is a precise delete-where-isDemo, not a name/email guess.
_DEMO_TAGGED_COLLECTIONS = ["customers", "reservations", "transactions", "feedback",
                            "categories", "products", "stock_units", "sell_variants"]


@router.post("/purge-demo-data")
async def purge_demo_data(data: dict, user: dict = Depends(require_owner)):
    """Delete every row the startup seeders created for demo purposes
    (the 5 sample guests + their reservation/transaction/feedback history,
    and the starter alcohol catalog's categories/products/stock units/sell
    variants), so a pilot venue's database starts from zero before go-live.

    Never touches businesses, auth_users (admin/staff), changelog, or
    chart-of-accounts — none of the seeders that write those tag isDemo,
    and this only ever deletes on isDemo=True, so it can't reach them.

    Destructive and irreversible, so it requires an explicit
    {"confirm": "PURGE"} in the body rather than firing on a bare POST."""
    if data.get("confirm") != "PURGE":
        raise HTTPException(status_code=400, detail='Send {"confirm": "PURGE"} to purge demo data')

    results = {}
    for name in _DEMO_TAGGED_COLLECTIONS:
        r = await db[name].delete_many({"isDemo": True, **tenant_scope_filter(user["businessId"])})
        results[name] = r.deleted_count
    return {"purged": results, "total": sum(results.values())}


@router.get("/{business_id}/setup-status")
async def get_setup_status(business_id: str, user: dict = Depends(require_owner)):
    """Live view of the three Foundation Day runbook steps
    (docs/LAUNCH_FOUNDATION_RUNBOOK.md), so an owner can see launch
    readiness on the Pulse dashboard instead of running curl commands.
    Read-only — never modifies anything."""
    await _owned_business_or_404(business_id, user)
    # Only a deployment-wide readiness flag is exposed, never ambiguous rows
    # or counts attributed to an arbitrary business. Support resolves those.
    from services.ownership_migration import MIGRATABLE_COLLECTIONS
    review_required = False
    for name in MIGRATABLE_COLLECTIONS:
        if await db[name].find_one({"businessId": None}, {"_id": 1}):
            review_required = True
            break

    demo_total = 0
    for name in _DEMO_TAGGED_COLLECTIONS:
        demo_total += await db[name].count_documents({"isDemo": True, **tenant_scope_filter(business_id)})

    has_menu = await db.products.count_documents({"isDemo": {"$ne": True}, **tenant_scope_filter(business_id)}) > 0
    has_staff = await db.auth_users.count_documents({"businessId": business_id}) > 1

    checklist = {
        "backfillComplete": not review_required,
        "demoDataPurged": demo_total == 0,
        "hasMenu": has_menu,
        "hasStaff": has_staff,
    }
    return {**checklist, "ready": all(checklist.values()),
            "ownershipReviewRequired": review_required, "untaggedRowsRemaining": None, "demoRowsRemaining": demo_total}
