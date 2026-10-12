"""services/wallet_service.py used customerId alone for birthday-voucher
duplicate detection, wallet listing, redemption and expiry — never a
businessId. Two businesses sharing a duplicate customer id (the same
adversarial scenario already covered for products in
test_launch_access_and_scope.py) could see or affect each other's wallet
vouchers. Fixed by deriving ownership from the customer record's own
verified businessId and scoping every voucher read/write by it.
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from database import db
import services.wallet_service as wallet_service


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _birthday_today_str() -> str:
    today = datetime.now(timezone.utc)
    return f"1990-{today.month:02d}-{today.day:02d}"


def test_birthday_voucher_duplicate_detection_is_tenant_scoped():
    """Two businesses with a customer sharing the same id, both due a
    birthday voucher this month: business A's existing voucher must never
    be read as "already issued" for business B's customer of the same id."""
    shared_id = str(uuid.uuid4())
    bday = _birthday_today_str()
    customer_a = {"id": shared_id, "businessId": "wallet-tenant-a", "birthday": bday, "name": "A's customer"}
    customer_b = {"id": shared_id, "businessId": "wallet-tenant-b", "birthday": bday, "name": "B's customer"}
    try:
        voucher_a = _run(wallet_service.ensure_birthday_voucher(customer_a))
        assert voucher_a is not None
        assert voucher_a["businessId"] == "wallet-tenant-a"

        # Business B's customer, same id, must still get its own voucher —
        # not be told "already issued" because of A's row.
        voucher_b = _run(wallet_service.ensure_birthday_voucher(customer_b))
        assert voucher_b is not None
        assert voucher_b["businessId"] == "wallet-tenant-b"
        assert voucher_b["id"] != voucher_a["id"]

        # Idempotent within the same business: running it again for A finds A's own voucher, issues nothing new.
        again = _run(wallet_service.ensure_birthday_voucher(customer_a))
        assert again is None
    finally:
        _run(db.vouchers.delete_many({"customerId": shared_id}))


def test_ensure_birthday_voucher_skips_customer_with_no_business():
    customer = {"id": str(uuid.uuid4()), "birthday": _birthday_today_str(), "name": "Unowned"}
    assert _run(wallet_service.ensure_birthday_voucher(customer)) is None
    assert _run(db.vouchers.find_one({"customerId": customer["id"]})) is None


def test_wallet_listing_is_tenant_scoped_for_duplicate_customer_id():
    # customers.id carries a global unique index (unlike products.id, which
    # the launch audit found duplicated across tenants) — so this exercises
    # the realistic variant instead: one real customer, and a stray
    # mis-tagged voucher under a different businessId (e.g. a legacy row
    # from before voucher writes were tenant-stamped), to confirm wallet
    # listing still only ever shows the caller's own business's vouchers.
    shared_id = str(uuid.uuid4())
    try:
        _run(db.customers.insert_one({"id": shared_id, "businessId": "wallet-tenant-a", "name": "A"}))
        _run(db.vouchers.insert_one({
            "id": f"VCH-{uuid.uuid4().hex[:8]}", "customerId": shared_id, "businessId": "wallet-tenant-a",
            "amount": 5.0, "status": "active", "createdAt": datetime.now(timezone.utc).isoformat(),
        }))
        _run(db.vouchers.insert_one({
            "id": f"VCH-{uuid.uuid4().hex[:8]}", "customerId": shared_id, "businessId": "wallet-tenant-b",
            "amount": 50.0, "status": "active", "createdAt": datetime.now(timezone.utc).isoformat(),
        }))

        wallet_a = _run(wallet_service.get_wallet(shared_id, business_id="wallet-tenant-a"))
        assert wallet_a is not None
        assert len(wallet_a["vouchers"]) == 1
        assert wallet_a["vouchers"][0]["businessId"] == "wallet-tenant-a"
        assert wallet_a["totalVoucherValue"] == 5.0, (
            "the stray business-B-tagged voucher on the same customerId must never be counted "
            "into this business's wallet total or voucher list"
        )
    finally:
        _run(db.customers.delete_many({"id": shared_id}))
        _run(db.vouchers.delete_many({"customerId": shared_id}))


def test_redeem_wallet_voucher_cannot_redeem_a_foreign_business_voucher():
    voucher_id = f"VCH-{uuid.uuid4().hex[:8]}"
    _run(db.vouchers.insert_one({
        "id": voucher_id, "businessId": "wallet-tenant-b", "value": 20.0, "valueType": "amount",
        "status": "active", "redemptionCount": 0,
    }))
    try:
        applied = _run(wallet_service.redeem_wallet_voucher(
            voucher_id, "txn-cross-tenant", 20.0, business_id="wallet-tenant-a"))
        assert applied == 0.0

        untouched = _run(db.vouchers.find_one({"id": voucher_id}, {"_id": 0}))
        assert untouched["status"] == "active"
        assert untouched["redemptionCount"] == 0

        # The rightful business can still redeem it.
        applied_owner = _run(wallet_service.redeem_wallet_voucher(
            voucher_id, "txn-same-tenant", 20.0, business_id="wallet-tenant-b"))
        assert applied_owner == 20.0
    finally:
        _run(db.vouchers.delete_many({"id": voucher_id}))


def test_expire_stale_vouchers_only_touches_the_callers_own_business():
    customer_id = str(uuid.uuid4())
    expired_iso = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    ids = {
        "a": f"VCH-{uuid.uuid4().hex[:8]}",
        "b": f"VCH-{uuid.uuid4().hex[:8]}",
        "legacy": f"VCH-{uuid.uuid4().hex[:8]}",
    }
    try:
        _run(db.vouchers.insert_one({"id": ids["a"], "customerId": customer_id, "businessId": "wallet-tenant-a",
                                      "status": "active", "expiresAt": expired_iso}))
        _run(db.vouchers.insert_one({"id": ids["b"], "customerId": customer_id, "businessId": "wallet-tenant-b",
                                      "status": "active", "expiresAt": expired_iso}))
        # Legacy/unowned row — no businessId at all, pre-dating tenant stamping.
        _run(db.vouchers.insert_one({"id": ids["legacy"], "customerId": customer_id,
                                      "status": "active", "expiresAt": expired_iso}))

        _run(wallet_service.expire_stale_vouchers(customer_id, "wallet-tenant-a"))

        row_a = _run(db.vouchers.find_one({"id": ids["a"]}, {"_id": 0}))
        row_b = _run(db.vouchers.find_one({"id": ids["b"]}, {"_id": 0}))
        row_legacy = _run(db.vouchers.find_one({"id": ids["legacy"]}, {"_id": 0}))
        assert row_a["status"] == "expired"
        assert row_b["status"] == "active", "business A's expiry pass must never touch business B's voucher"
        assert row_legacy["status"] == "active", (
            "an unowned legacy voucher must stay untouched until the reviewed ownership-migration "
            "workflow assigns it — never silently swept up by whichever business happens to read it first"
        )
    finally:
        _run(db.vouchers.delete_many({"customerId": customer_id}))
