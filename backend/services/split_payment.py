"""Partial payment handling for guest bill-split.

Guests can pay partial amounts and put the remainder on a tab that staff
collects later (cash, tip, or future visit). Tracks partial payments,
remaining balance, and tab status.
"""
from __future__ import annotations
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from database import db
import uuid


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def create_guest_tab(split_id: str, guest_phone: str, total_amount: float,
                            claimed_lines: Optional[List[str]] = None,
                            slot_index: Optional[int] = None) -> Dict[str, Any]:
    """Create a new guest tab for partial payment."""
    tab_id = f"TAB-{str(uuid.uuid4())[:12].upper()}"

    tab = {
        "id": tab_id,
        "splitId": split_id,
        "guestPhone": guest_phone,
        "totalAmount": round(total_amount, 2),
        "paidAmount": 0.0,
        "remainingBalance": round(total_amount, 2),
        "claimedLines": claimed_lines or [],
        "slotIndex": slot_index,
        "payments": [],  # Track partial payments
        "status": "open",  # open, partial, paid, cancelled
        "createdAt": _now(),
        "expiresAt": None,  # Can set for time-limited tabs
    }

    await db.split_tabs.insert_one(tab)
    tab.pop("_id", None)
    return tab




async def get_guest_tabs(guest_phone: str) -> List[Dict[str, Any]]:
    """Get all open tabs for a guest (by phone)."""
    tabs = await db.split_tabs.find(
        {"guestPhone": guest_phone, "status": {"$in": ["open", "partial"]}},
        {"_id": 0}
    ).to_list(100)
    return tabs


async def close_tab(tab_id: str, force: bool = False) -> Dict[str, Any]:
    """Close a tab (mark as paid or cancelled)."""
    tab = await db.split_tabs.find_one({"id": tab_id})
    if not tab:
        return {"error": "Tab not found", "success": False}

    remaining = tab.get("remainingBalance", 0) or 0
    if remaining > 0 and not force:
        return {
            "error": f"Tab has ${remaining:.2f} remaining balance",
            "success": False,
            "remainingBalance": remaining,
        }

    status = "cancelled" if force else "paid"
    await db.split_tabs.update_one(
        {"id": tab_id},
        {"$set": {"status": status, "closedAt": _now()}}
    )

    return {"success": True, "status": status, "tabId": tab_id}


async def staff_process_tab_payment(tab_id: str, amount: float, method: str = "cash",
                                     idempotency_key: Optional[str] = None) -> Dict[str, Any]:
    """Staff processes remaining tab balance (e.g., cash physically collected
    at end of meal) — the only place a guest's partial-checkout intent (see
    routes/bill_split.py's partial_checkout) becomes an actual recorded
    payment.

    Two hardening fixes from the Trust Release release-closure pass:

    1. Idempotency — a staff device retrying a timed-out request, or a
       double-tap on "confirm cash received", used to double-count the same
       real payment, since nothing here recognised a resubmission. When the
       caller supplies idempotency_key, a payment already recorded under
       that exact key on this tab is returned as-is rather than recorded a
       second time.
    2. Atomicity — reading the tab, computing new totals, then writing them
       back separately raced the same way commerce_v29.py's voucher
       redemption used to: two concurrent staff-process-tab calls (two
       terminals, or a genuine retry racing the original) could both read
       the same stale balance and each apply their own payment against it,
       silently overcounting what was actually collected. Fixed with the
       same bounded compare-and-swap retry loop already used there: each
       attempt re-reads the tab fresh and writes with the filter pinned to
       the exact prior paidAmount/remainingBalance/status it read, so a
       losing concurrent attempt sees no match and retries against the
       winner's fresh state instead of clobbering it.
    """
    if idempotency_key:
        prior_tab = await db.split_tabs.find_one(
            {"id": tab_id, "payments.idempotencyKey": idempotency_key}, {"_id": 0})
        if prior_tab:
            prior_payment = next(
                p for p in prior_tab["payments"] if p.get("idempotencyKey") == idempotency_key)
            return {
                "success": True,
                "paymentId": prior_payment["id"],
                "paidAmount": prior_tab["paidAmount"],
                "remainingBalance": prior_tab["remainingBalance"],
                "status": prior_tab["status"],
                "replayed": True,
            }

    max_attempts = 8
    for _attempt in range(max_attempts):
        tab = await db.split_tabs.find_one({"id": tab_id})
        if not tab:
            return {"error": "Tab not found", "success": False}

        remaining = tab.get("remainingBalance", 0) or 0
        if remaining <= 0:
            return {"error": "Tab already paid", "success": False}

        applied = round(min(amount, remaining), 2)
        payment = {
            "id": f"PAY-{str(uuid.uuid4())[:12].upper()}",
            "amount": applied,
            "method": method,
            "reference": "staff_collected",
            "idempotencyKey": idempotency_key,
            "timestamp": _now(),
        }
        new_paid = round((tab.get("paidAmount", 0) or 0) + applied, 2)
        new_balance = round((tab.get("totalAmount", 0) or 0) - new_paid, 2)
        new_status = "paid" if new_balance <= 0 else "partial"

        cas_filter = {
            "id": tab_id,
            "paidAmount": tab.get("paidAmount", 0) or 0,
            "remainingBalance": tab.get("remainingBalance", 0) or 0,
            "status": tab.get("status"),
        }
        updated = await db.split_tabs.find_one_and_update(
            cas_filter,
            {
                "$push": {"payments": payment},
                "$set": {
                    "paidAmount": new_paid,
                    "remainingBalance": max(0, new_balance),
                    "status": new_status,
                    "updatedAt": _now(),
                },
            },
            return_document=True,
        )
        if updated is not None:
            return {
                "success": True,
                "paymentId": payment["id"],
                "paidAmount": new_paid,
                "remainingBalance": max(0, new_balance),
                "status": new_status,
            }
        # Someone else (another terminal, or a concurrent retry of this exact
        # request) wrote to this tab between our read and our write — loop
        # back and retry against fresh state.

    return {
        "error": "Tab was updated by another request at the same moment — please retry",
        "success": False,
    }
