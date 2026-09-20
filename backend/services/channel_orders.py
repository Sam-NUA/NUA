"""Turn an order from any channel into a coursed kitchen ticket.

The POS had a route into the kitchen; QR got one; kiosk and online had none
at all — a kiosk checkout wrote a session total and stopped, and an accepted
online order sat in its own collection where no KDS would ever show it. This
is the one place a channel order becomes a real ticket, so a new channel gets
coursing, dockets and pacing for free instead of re-deriving them.

Takeaway and delivery straight-fire by default, which is what the coursing
config already says about those order types — nobody holds a courier's food
behind a starter.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import db
from models.kitchen_order import KitchenOrder
from middleware.actor_context import tenant_scope_filter, get_actor_context

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _enrich_categories(items: List[dict], business_id: Optional[str] = None) -> List[dict]:
    """Fill in each item's category from the product catalog.

    Coursing maps categories to courses, so an item without one silently
    lands on the default course — which is how QR ordering ended up
    uncoursable. Channels that only send a productId get it looked up here.
    """
    missing = [i.get("productId") for i in items if not i.get("category") and i.get("productId")]
    if not missing:
        return [dict(i) for i in items]
    query = {"$and": [tenant_scope_filter(business_id), {"id": {"$in": missing}}]}
    rows = await db.products.find(
        query,
        {"_id": 0, "id": 1, "category": 1, "name": 1, "allergens": 1, "dietary": 1},
    ).to_list(200)
    by_id = {r["id"]: r for r in rows}
    out = []
    for i in items:
        row = dict(i)
        hit = by_id.get(row.get("productId"))
        if hit:
            row.setdefault("category", hit.get("category"))
            row.setdefault("productName", row.get("name") or hit.get("name"))
            # Allergens matter most on the docket, so they travel with the item.
            if hit.get("allergens"):
                row.setdefault("allergens", hit["allergens"])
            if hit.get("dietary"):
                row.setdefault("dietary", hit["dietary"])
        out.append(row)
    return out


async def create_ticket(items: List[dict], *, order_type: str,
                        table_number: Optional[str] = None,
                        source: str = "channel",
                        guest_name: Optional[str] = None,
                        transaction_id: Optional[str] = None,
                        external_id: Optional[str] = None,
                        notes: Optional[str] = None,
                        actor: str = "system",
                        straight_fire: Optional[bool] = None,
                        business_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Create a coursed kitchen ticket for a channel order.

    Returns the ticket, or None when there's nothing to cook. Idempotent on
    `external_id`: replaying the same channel order returns the existing
    ticket rather than making a second one.

    `business_id` defaults from the request's actor context (same pattern
    used throughout this codebase's tenant-isolation fixes) — stamped on
    the kitchen order and used to scope the external_id idempotency lookup
    and category enrichment, so two businesses' channel orders (staff
    accepting an online order, the AI phone agent drafting one) can never
    collide or leak into each other's KDS. Callers with no business signal
    at all (the kiosk-checkout path, genuinely unauthenticated by design —
    see TENANT_ISOLATION_REMAINING_WORK.md) simply leave this None, same
    behavior as before this parameter existed.
    """
    if business_id is None:
        business_id = get_actor_context().get("businessId")

    if not business_id:
        raise ValueError("Business ownership required for a kitchen ticket")
    items = [i for i in (items or []) if i]
    if not items:
        return None

    if external_id:
        existing_query = {"$and": [tenant_scope_filter(business_id), {"externalId": external_id}]}
        existing = await db.kitchen_orders.find_one(existing_query, {"_id": 0})
        if existing:
            return existing

    from services import coursing, print_routing

    items = await _enrich_categories(items, business_id)
    config = await coursing.get_config(business_id=business_id)
    ot = str(order_type or "takeaway").replace("-", "_")
    straight = (coursing.is_straight_fire(ot, config, False)
                if straight_fire is None else bool(straight_fire))

    priced = [{**i, "round": 1} for i in coursing.assign_courses(items, config)]
    now = _now()
    order = KitchenOrder(
        transactionId=transaction_id,
        tableNumber=table_number,
        orderType=ot,
        items=priced,
        notes=notes,
        serverId=None,
        guestName=guest_name,
        createdByName=actor,
        deviceLabel=source,
        courses=coursing.initial_course_states(
            priced, config, ot, straight, fired_by=actor, now=now),
    )
    doc = order.dict()
    doc["source"] = source
    doc["externalId"] = external_id
    doc["straightFired"] = straight
    doc["businessId"] = business_id
    try:
        doc["orderStations"] = await print_routing.stations_for(priced)
    except Exception as e:
        log.warning("%s order: station stamp failed — %s", source, e)
    await db.kitchen_orders.insert_one(doc)
    doc.pop("_id", None)

    from services import course_events
    await course_events.record_initial(doc["id"], doc.get("courses") or {}, actor)

    # Same side effects a POS send gets: fired courses print, and a dine-in
    # table's pacing follows.
    fired = sorted(int(k) for k, v in (doc.get("courses") or {}).items()
                   if v.get("status") == "fired")
    for course in fired:
        label = next((str(c.get("label")) for c in (config.get("courses") or [])
                      if int(c.get("key")) == course), f"Course {course}")
        try:
            rows = [{**i, "courseLabel": label} for i in priced
                    if int(i.get("course") or 1) == course]
            if rows:
                await print_routing.route_and_queue(
                    rows, order_id=doc["id"], table_number=table_number,
                    extra={"course": course, "courseLabel": label,
                           "kitchenOrderId": doc["id"], "channel": source},
                )
        except Exception as e:
            log.warning("%s order %s: docket print failed — %s", source, doc["id"], e)

    if fired and table_number:
        try:
            from services import table_pacing
            await table_pacing.advance_for_course(doc, fired[-1], config)
        except Exception as e:
            log.warning("%s order %s: pacing sync failed — %s", source, doc["id"], e)
    return doc
