"""Stock-floor helper.

MongoDB serializes $inc at the document level, so two concurrent stock
decrements against the same product are each individually atomic — neither
lost-update-clobbers the other. What's missing is a *floor*: nothing stops
demand outpacing supply from leaving stock arbitrarily negative and staying
there indefinitely. This clamps it back to zero after the fact rather than
blocking the sale/waste-record/order-accept that caused it — oversell is a
real, accepted POS scenario (stale counts, walk-in demand), not something
this codebase has ever refused to let happen. See
backend/FINANCIAL_OFFLINE_INTEGRITY_REMAINING_WORK.md for the fuller
reasoning and what this deliberately does not do (reject a sale for
insufficient stock).
"""
from typing import Iterable
from database import db
from middleware.actor_context import tenant_scope_filter
from pymongo import UpdateOne


async def clamp_negative_stock(product_ids: Iterable[str]) -> None:
    """Call right after any stock-decrementing write. Cheap no-op when
    nothing in the given set actually went negative."""
    ids = [pid for pid in product_ids if pid]
    if not ids:
        return
    negative = await db.products.find(
        {"id": {"$in": ids}, "stock": {"$lt": 0}, **tenant_scope_filter()},
        {"_id": 0, "id": 1},
    ).to_list(len(ids))
    if not negative:
        return
    await db.products.bulk_write([
        UpdateOne(
            {"id": row["id"], "stock": {"$lt": 0}, **tenant_scope_filter()},
            {"$set": {"stock": 0}},
        )
        for row in negative
    ])
