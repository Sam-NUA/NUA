"""Shared "a sale happened" logic, factored out of routes/transactions.py so
it has exactly one implementation instead of two.

Historically this all lived inline inside create_transaction(). That was fine
while NUA POS was the only thing that could ever produce a completed sale.
It stopped being fine the moment an external system (Square, and eventually
any other Connect provider) can also produce one: a synced Square sale needs
the *same* loyalty-earning math, the *same* audit trail, the *same* GL
posting, and the *same* rules-engine event as a native POS sale — otherwise
Ash's transaction-fed insight generators, spend-based Marketing segments and
the accounting ledger quietly diverge depending on which register the money
came through.

What's deliberately NOT in here: pricing, discounts, voucher/points
*redemption*, split-payment allocation, stock deduction, kitchen routing.
Those are concepts that only make sense for a bill NUA itself priced at the
counter. An externally-sourced sale (e.g. from Square) arrives already
priced and already paid — NUA is recording it, not computing it — so a
connector builds its own txn_dict from the provider's totals and calls only
the functions below.
"""
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from database import db
from utils.errors import log_and_continue
from middleware.actor_context import tenant_scope_filter

logger = logging.getLogger(__name__)


def compute_points_earned(
    subtotal: float,
    total: float,
    loyalty_multiplier: float,
    earn_lines: List[tuple],
    loyalty_cfg: Dict[str, Any],
) -> int:
    """Points earned = post-discount total x membership-tier multiplier x
    earnRate x a blended category multiplier (each line's category weighted
    by its share of the subtotal). Returns 0 if loyalty is inactive."""
    if not loyalty_cfg.get("active", True):
        return 0
    earn_rate = float(loyalty_cfg.get("earnRate", 1.0))
    category_mults = loyalty_cfg.get("categoryMultipliers", {})
    if subtotal > 0 and category_mults:
        category_mult = sum(
            line_total * float(category_mults.get(cat, 1.0)) for cat, line_total in earn_lines
        ) / subtotal
    else:
        category_mult = 1.0
    return int(total * loyalty_multiplier * earn_rate * category_mult)


async def credit_loyalty_points(customer_id: str, points_earned: int, total: float, transaction_id: str,
                                 business_id: Optional[str] = None) -> None:
    """$inc a customer's points/totalSpent/visits and write the earn-side
    loyalty ledger entry for one sale. Safe to call with points_earned == 0
    (still records the visit/spend)."""
    await db.customers.update_one(
        {**tenant_scope_filter(business_id), "id": customer_id},
        {
            "$inc": {"totalSpent": total, "visits": 1, "points": points_earned},
            # Two fields for the same fact, kept in lockstep on purpose:
            # lastVisit (bare ISO string) is what nua_intelligence.py,
            # nua_tools.py and v25_suite.py read; lastVisitDate is the
            # Customer model's declared field and what loyalty_engine's
            # segmentation and the marketing segment builder's "inactive for
            # N days" rule read. Writing only one starves the other's
            # readers of any real data.
            "$set": {"lastVisit": datetime.utcnow().isoformat(),
                     "lastVisitDate": datetime.utcnow().date().isoformat()},
        },
    )
    if points_earned > 0:
        try:
            await db.loyalty_ledger.insert_one({
                "id": f"LP-{str(uuid.uuid4())[:8].upper()}",
                "customerId": customer_id,
                "transactionId": transaction_id,
                "type": "earn",
                "points": points_earned,
                "businessId": business_id,
                "createdAt": datetime.utcnow().isoformat(),
            })
        except Exception:
            pass


async def record_sale_side_effects(txn_dict: Dict[str, Any], memo: Optional[str] = None) -> None:
    """Audit log + double-entry GL auto-post + rules-engine `pos.sale.completed`
    emit for one already-persisted transaction document. Each side effect is
    independently best-effort (a GL posting failure must never roll back the
    sale record, same as it never did inline in create_transaction) and is
    logged rather than silently swallowed.
    """
    try:
        from services.audit_service import log_event
        await log_event(
            entity_type="transaction", entity_id=txn_dict["id"],
            action="created", after=txn_dict,
            memo=memo or f"Sale {txn_dict.get('paymentMethod')} ${txn_dict.get('total')}",
        )
    except Exception as e:
        log_and_continue(logger, f"Sale audit log write failed for txn {txn_dict.get('id')}", e)

    try:
        from services.accounting_service import auto_post_pos_sale
        ts = txn_dict.get("timestamp")
        auto_txn = {**txn_dict, "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else ts}
        await auto_post_pos_sale(auto_txn)
    except Exception as e:
        log_and_continue(logger, "Sale ledger auto-post skipped", e)

    try:
        from services.rules_engine import safe_emit
        safe_emit("pos.sale.completed", {
            "id": txn_dict["id"], "total": txn_dict["total"],
            "customerId": txn_dict.get("customerId"),
            "items": [i.get("productId") for i in txn_dict.get("items", [])],
            "paymentMethod": txn_dict.get("paymentMethod"),
        }, entity_id=txn_dict["id"])
    except Exception:
        pass
