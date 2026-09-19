"""What happens to a table's kitchen ticket and floor-plan state when the
bill is paid.

Occupying a table and opening a ticket were both wired up; nothing closed
either. Over a service the floor plan filled and never drained, and a paid
table kept a live ticket — so the next party's first order would silently
join the previous party's bill.

Everything here is best-effort and idempotent: a payment has already been
taken by the time it runs, so a failure to tidy up must never surface as a
failed sale, and a retry must not double-apply.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import db
from middleware.actor_context import tenant_scope_filter, get_actor_context

log = logging.getLogger(__name__)

# A ticket in any of these is still the kitchen's problem.
OPEN_STATUSES = ["new", "preparing", "ready"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _biz(business_id: Optional[str]) -> Optional[str]:
    """None of this module's current callers routinely pass business_id
    (routes/coursing.py and v15_features.py run inside a request with an
    actor context; the two that don't — bill_split.py's guest checkout and
    refund_effects.py — target an already-known order_id or lack a business
    context of their own, a pre-existing gap this doesn't widen). Falling
    back to the actor context, same pattern as notification_service.send()
    and approval_service.enqueue_approval(), fixes the request-driven
    callers without editing them individually."""
    return business_id or get_actor_context().get("businessId")


async def close_tickets(table_number: Optional[str] = None,
                        transaction_id: Optional[str] = None,
                        order_id: Optional[str] = None,
                        actor: Optional[str] = None,
                        business_id: Optional[str] = None) -> List[str]:
    """Close the kitchen tickets a completed payment covers.

    Every course is marked served as well as the ticket — a ticket closed
    with courses still showing "fired" reads on the KDS as food nobody
    collected.
    """
    # By table/transaction, a business-scoped filter is essential — two
    # businesses on a shared deployment can both have an open "Table 5" or
    # reuse a transaction-id-shaped string, and without this a payment at
    # one business could silently close (and mark served) another
    # business's kitchen ticket. An explicit order_id is already an exact
    # match on one document, so it's left unscoped rather than risk
    # rejecting the legitimate case where the caller has no business
    # context to give (see _biz's docstring).
    query: Dict[str, Any] = {"status": {"$in": OPEN_STATUSES}}
    if order_id:
        query = {"id": order_id}
    elif transaction_id:
        query = {"transactionId": transaction_id, **query, **tenant_scope_filter(_biz(business_id))}
    elif table_number:
        query = {"tableNumber": table_number, **query, **tenant_scope_filter(_biz(business_id))}
    else:
        return []

    closed: List[str] = []
    now = _now()
    for order in await db.kitchen_orders.find(query, {"_id": 0}).to_list(50):
        courses = dict(order.get("courses") or {})
        for key, state in courses.items():
            if state.get("status") != "served":
                courses[key] = {**state, "status": "served",
                                "servedAt": state.get("servedAt") or now}
        await db.kitchen_orders.update_one(
            {"id": order["id"]},
            {"$set": {"status": "served", "servedAt": now, "courses": courses,
                      "closedBy": actor, "closedReason": "paid"}},
        )
        closed.append(order["id"])
    return closed


async def free_table(table_number: Optional[str], actor: Optional[str] = None) -> bool:
    """Release the table on the floor plan and clear its pacing state."""
    if not table_number:
        return False
    try:
        from services import floor_tables
        hit = await floor_tables.resolve_table(table_number)
        if not hit:
            return False
        table, plan_id = hit
        await floor_tables.set_table_status(table["id"], plan_id, "available")
        # Pacing state is what drives the dwell timers; leaving it behind
        # would show the next party as having been seated since lunch.
        await db.table_states.delete_one({"tableId": table["id"]})
        return True
    except Exception as e:
        log.warning("close: could not free table %r: %s", table_number, e)
        return False


async def settle_seats(seats: List[int], table_number: Optional[str] = None,
                       order_id: Optional[str] = None,
                       actor: Optional[str] = None,
                       business_id: Optional[str] = None) -> Dict[str, Any]:
    """Settle only the given seats' items on a table's ticket.

    A guest who pays and leaves at 8pm shouldn't still read as owing at 10pm.
    Their items are marked settled; the ticket itself only closes once every
    seat on it has paid, so the rest of the table carries on as normal.
    """
    query: Dict[str, Any] = {"status": {"$in": OPEN_STATUSES}}
    if order_id:
        query = {"id": order_id}
    elif table_number:
        query = {"tableNumber": table_number, **query, **tenant_scope_filter(_biz(business_id))}
    else:
        return {"settledSeats": [], "closedOrders": [], "remainingSeats": []}

    seats = [int(s) for s in seats or []]
    now = _now()
    settled_orders: List[str] = []
    closed: List[str] = []
    remaining: List[int] = []

    for order in await db.kitchen_orders.find(query, {"_id": 0}).to_list(50):
        items = [dict(i) for i in (order.get("items") or [])]
        touched = False
        for it in items:
            if it.get("seat") in seats and not it.get("settledAt"):
                it["settledAt"] = now
                it["settledBy"] = actor
                touched = True
        if not touched:
            continue
        settled_orders.append(order["id"])

        # Seats still owing: anything unsettled that has a seat, plus a flag
        # for unseated items (shared plates nobody has claimed yet).
        open_seats = sorted({i["seat"] for i in items
                             if i.get("seat") is not None and not i.get("settledAt")})
        unseated_open = any(i.get("seat") is None and not i.get("settledAt") for i in items)
        remaining.extend(open_seats)

        await db.kitchen_orders.update_one({"id": order["id"]}, {"$set": {"items": items}})
        if not open_seats and not unseated_open:
            # Everyone has paid — the ticket really is done.
            closed.extend(await close_tickets(order_id=order["id"], actor=actor))

    return {"settledSeats": seats, "closedOrders": closed,
            "settledOrders": settled_orders, "remainingSeats": sorted(set(remaining))}


async def settle(table_number: Optional[str] = None,
                 transaction_id: Optional[str] = None,
                 order_id: Optional[str] = None,
                 actor: Optional[str] = None,
                 release_table: bool = True,
                 seats: Optional[List[int]] = None,
                 business_id: Optional[str] = None) -> Dict[str, Any]:
    """Close tickets and (for dine-in) hand the table back.

    With `seats`, only those seats settle — and the table is only released
    once nothing is left owing on it.
    """
    if seats:
        result = await settle_seats(seats, table_number=table_number,
                                    order_id=order_id, actor=actor, business_id=business_id)
        fully_done = bool(result["closedOrders"]) and not result["remainingSeats"]
        freed = (await free_table(table_number, actor)
                 if (release_table and fully_done) else False)
        return {**result, "tableFreed": freed, "tableNumber": table_number,
                "partial": not fully_done}

    closed = await close_tickets(table_number=table_number,
                                 transaction_id=transaction_id,
                                 order_id=order_id, actor=actor, business_id=business_id)
    freed = await free_table(table_number, actor) if release_table else False
    return {"closedOrders": closed, "tableFreed": freed, "tableNumber": table_number,
            "partial": False}


async def move_ticket(from_table: str, to_table: str,
                      actor: Optional[str] = None,
                      business_id: Optional[str] = None) -> Dict[str, Any]:
    """Follow a moved/merged table with its kitchen ticket.

    Move Table relabelled the tab and left the kitchen ticket on the old
    number, so every later docket, the pacing state and the settle-on-payment
    lookup all pointed at a table the party had left.
    """
    moved: List[str] = []
    move_query = {"tableNumber": from_table, "status": {"$in": OPEN_STATUSES},
                  **tenant_scope_filter(_biz(business_id))}
    for order in await db.kitchen_orders.find(move_query, {"_id": 0}).to_list(50):
        await db.kitchen_orders.update_one(
            {"id": order["id"]},
            {"$set": {"tableNumber": to_table},
             "$push": {"tableMoves": {"from": from_table, "to": to_table,
                                      "at": _now(), "by": actor}}},
        )
        moved.append(order["id"])

    if moved:
        # Hand the old table back and carry the party's pacing across, so the
        # dwell timer doesn't restart just because they changed seats.
        try:
            from services import floor_tables
            old = await floor_tables.resolve_table(from_table)
            new = await floor_tables.resolve_table(to_table)
            if old and new:
                state = await db.table_states.find_one({"tableId": old[0]["id"]}, {"_id": 0})
                await floor_tables.set_table_status(old[0]["id"], old[1], "available")
                await floor_tables.set_table_status(new[0]["id"], new[1], "occupied", moved[0])
                if state:
                    await db.table_states.delete_one({"tableId": old[0]["id"]})
                    await db.table_states.update_one(
                        {"tableId": new[0]["id"]},
                        {"$set": {**{k: v for k, v in state.items() if k != "tableId"},
                                  "tableId": new[0]["id"], "updatedAt": _now()}},
                        upsert=True,
                    )
        except Exception as e:
            log.warning("move: floor plan follow-up failed %s -> %s: %s", from_table, to_table, e)
    return {"movedOrders": moved, "from": from_table, "to": to_table}


async def void_items(order_id: str, voids: List[dict], actor: Optional[str] = None,
                     business_id: Optional[str] = None) -> Dict[str, Any]:
    """Remove or reduce items on a live ticket.

    `voids` is [{productId|productName, quantity, course?, seat?}] — quantity
    is how many to take *off*. Anything already cooking still has to be told;
    silently dropping it from the POS leaves the kitchen plating a dish nobody
    is paying for.

    Returns the items actually removed, so the caller can print a void docket
    for the stations that were cooking them.
    """
    from middleware.actor_context import tenant_owns
    order = await db.kitchen_orders.find_one({"$and": [{"id": order_id}, tenant_scope_filter(_biz(business_id))]}, {"_id": 0})
    if not order or not tenant_owns(order.get("businessId"), _biz(business_id)):
        return {"ok": False, "removed": [], "reason": "not found"}

    items = [dict(i) for i in (order.get("items") or [])]
    removed: List[dict] = []

    for v in voids or []:
        want = int(v.get("quantity") or 0)
        if want <= 0:
            continue
        for it in items:
            if want <= 0:
                break
            same = (
                (v.get("productId") and it.get("productId") == v.get("productId"))
                or (v.get("productName") and it.get("productName") == v.get("productName"))
            )
            if not same:
                continue
            if v.get("course") is not None and int(it.get("course") or 1) != int(v["course"]):
                continue
            if v.get("seat") is not None and it.get("seat") != v.get("seat"):
                continue
            take = min(int(it.get("quantity") or 0), want)
            if take <= 0:
                continue
            it["quantity"] = int(it.get("quantity") or 0) - take
            want -= take
            removed.append({**{k: it.get(k) for k in
                               ("productId", "productName", "category", "course", "courseLabel", "seat")},
                            "quantity": take})

    if not removed:
        return {"ok": True, "removed": [], "order": order}

    kept = [i for i in items if int(i.get("quantity") or 0) > 0]
    # A course with nothing left on it shouldn't keep a fire state that
    # implies the kitchen still owes the table something.
    live_courses = {str(int(i.get("course") or 1)) for i in kept}
    courses = {k: v for k, v in (order.get("courses") or {}).items() if k in live_courses}

    voids_log = list(order.get("voids") or [])
    voids_log.append({"at": _now(), "by": actor, "items": removed})

    updated = await db.kitchen_orders.find_one_and_update(
        {"$and": [{"id": order_id}, tenant_scope_filter(_biz(business_id))]},
        {"$set": {"items": kept, "courses": courses, "voids": voids_log}},
        return_document=True,
    )
    if updated:
        updated.pop("_id", None)
    return {"ok": True, "removed": removed, "order": updated}
