from fastapi import APIRouter, HTTPException, Depends, Request
from typing import Optional
import logging
from datetime import datetime, timezone
from database import db
from deps import get_user, require_permission
from middleware.actor_context import tenant_scope_filter
from models.kitchen_order import KitchenOrder, KitchenOrderCreate

router = APIRouter()
log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _course_label(course: int, coursing_config: dict) -> str:
    """The venue's own name for a course, falling back to a generic one."""
    for c in (coursing_config or {}).get("courses") or []:
        try:
            if int(c.get("key")) == int(course):
                return str(c.get("label") or f"Course {course}")
        except (TypeError, ValueError):
            continue
    return {1: "Starter", 2: "Main", 3: "Dessert", 4: "Coffee"}.get(course, f"Course {course}")


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def _broadcast_kitchen_update(order: dict, event: str) -> None:
    """Best-effort push to any connected Kitchen/FloorPlan screen so a board
    refresh feels instant instead of waiting for the next poll. Mirrors the
    sale.completed pattern in transactions.py — never lets a broadcast
    failure affect the actual ticket mutation."""
    try:
        from services import realtime
        await realtime.broadcast({
            "type": "kitchen_order.updated", "event": event, "orderId": order.get("id"),
            "status": order.get("status"), "tableNumber": order.get("tableNumber"),
        })
    except Exception:
        pass


async def _clear_overnight_tickets(business_id: Optional[str] = None) -> int:
    """A ticket left in new/preparing/ready from a previous day (chef forgot
    to mark it served, or it was superseded by close of service) shouldn't
    carry over and clutter tomorrow's board. Runs on every board read rather
    than a scheduled job, so it's correct even if the server restarted
    overnight or the scheduler missed a beat — the board self-heals the
    moment anyone opens it."""
    today = _today_str()
    query = {"status": {"$in": ["new", "preparing", "ready"]}, **tenant_scope_filter(business_id)}
    stale = await db.kitchen_orders.find(
        query,
        {"_id": 0, "id": 1, "createdAt": 1},
    ).to_list(500)
    stale_ids = [o["id"] for o in stale if (o.get("createdAt") or "")[:10] < today]
    if stale_ids:
        await db.kitchen_orders.update_many(
            {"id": {"$in": stale_ids}},
            {"$set": {"status": "cancelled", "cancelledAt": _now(),
                      "autoCleared": True, "notes": "Auto-cleared overnight — not served by close of previous day"}},
        )
    return len(stale_ids)


# ============ KITCHEN DISPLAY (KDS) API ============
@router.get("/kitchen/orders")
async def get_kitchen_orders(status: Optional[str] = None, user: dict = Depends(get_user)):
    biz = user.get("businessId")
    await _clear_overnight_tickets(biz)
    query = {**tenant_scope_filter(biz)}
    if status:
        query["status"] = status
    else:
        query["status"] = {"$in": ["new", "preparing", "ready"]}
    orders = await db.kitchen_orders.find(query, {"_id": 0}).sort("createdAt", 1).to_list(100)
    return orders


async def _avg_order_minutes_today(business_id: Optional[str] = None) -> tuple[float, int]:
    today = _today_str()
    orders = await db.kitchen_orders.find(
        {"createdAt": {"$gte": today}, "readyAt": {"$ne": None}, **tenant_scope_filter(business_id)},
        {"_id": 0, "createdAt": 1, "readyAt": 1},
    ).to_list(1000)
    durations = []
    for o in orders:
        try:
            created = datetime.fromisoformat(o["createdAt"])
            ready = datetime.fromisoformat(o["readyAt"])
            mins = (ready - created).total_seconds() / 60
            if mins >= 0:
                durations.append(mins)
        except (ValueError, TypeError, KeyError):
            continue
    avg = round(sum(durations) / len(durations), 1) if durations else 0
    return avg, len(durations)


@router.get("/kitchen/avg-order-time")
async def get_avg_order_time(user: dict = Depends(get_user)):
    """Average minutes from order fired to ready, across today's completed
    tickets — a rough live gauge for the chef to judge pace mid-service."""
    avg, count = await _avg_order_minutes_today(user.get("businessId"))
    return {"avgOrderMinutes": avg, "ordersCompletedToday": count}


async def _active_queue_depth(business_id: Optional[str] = None) -> tuple[int, int, float]:
    """(orders cooking, orders fully held, weighted work in the queue).

    A ticket sitting on held courses isn't work the kitchen is doing — a table
    holding its mains for another twenty minutes shouldn't inflate the wait
    quoted to someone at the counter. Tickets with no course map at all count
    as active, which keeps every pre-coursing ticket behaving as before.

    The third number is the one the ETA should use. Counting tickets treats a
    twenty-item delivery the same as a single coffee, which is how a counter
    ends up quoting five minutes in front of an hour of work. Only the items
    actually cooking count — a held course is not on the stove yet.
    """
    rows = await db.kitchen_orders.find(
        {"status": {"$in": ["new", "preparing"]}, **tenant_scope_filter(business_id)},
        {"_id": 0, "courses": 1, "items": 1}).to_list(500)
    active = held = 0
    work = 0.0
    for o in rows:
        courses = o.get("courses") or {}
        items = o.get("items") or []
        if not courses:
            active += 1
            work += _ticket_work(items)
            continue
        statuses = [(v or {}).get("status") for v in courses.values()]
        if any(s in ("queued", "fired", "ready") for s in statuses):
            active += 1
            cooking = {int(k) for k, v in courses.items()
                       if (v or {}).get("status") in ("queued", "fired", "ready")}
            work += _ticket_work([i for i in items if int(i.get("course") or 1) in cooking])
        elif all(s == "held" for s in statuses):
            held += 1
    return active, held, round(work, 2)


def _ticket_work(items: list) -> float:
    """How much of the kitchen's attention a set of items represents.

    Deliberately sublinear in quantity: three of the same dish is more work
    than one, but nowhere near three times — they cook together. Any non-empty
    set is worth at least one unit, because even a single coffee costs a trip
    to the machine.
    """
    if not items:
        return 0.0
    units = 0.0
    for i in items:
        qty = max(1, int(i.get("quantity") or 1))
        units += 1 + (qty - 1) * 0.4
    return max(1.0, units)


@router.get("/kitchen/next-order-eta")
async def get_next_order_eta(user: dict = Depends(get_user)):
    """A quick, honest ballpark for "how long for a takeaway right now?" when
    a customer asks at the counter.

    Today's average ticket time, plus time for the work already ahead of it —
    weighted by how much food that work actually is, not by how many tickets
    it happens to be split across.
    """
    biz = user.get("businessId")
    avg, completed_count = await _avg_order_minutes_today(biz)
    queue_depth, held_depth, queue_work = await _active_queue_depth(biz)
    baseline = avg if completed_count > 0 else 12.0  # no data yet today — a sane starting guess
    minutes_per_work_unit = 1.2
    estimated = round(baseline + queue_work * minutes_per_work_unit, 1)
    return {
        "avgOrderMinutes": avg, "ordersCompletedToday": completed_count,
        "queueDepth": queue_depth,
        # Surfaced so the counter can see the difference between "the kitchen
        # is slammed" and "there are tables holding their mains".
        "heldOrders": held_depth,
        # What the estimate is actually based on — two tickets can be very
        # different amounts of work, and this is the number that says so.
        "queueWorkUnits": queue_work,
        "estimatedWaitMinutes": estimated,
    }


@router.post("/kitchen/orders")
async def create_kitchen_order(order: KitchenOrderCreate, request: Request, user: dict = Depends(get_user)):
    """Create a kitchen ticket. Auto-enriches docket fields from the request context:
    who created (user), device (X-Device-Label header or User-Agent), covers
    (from reservation if reservationId present), guest name (from reservation).
    """
    order_dict = order.dict()
    order_dict["businessId"] = user.get("businessId")

    # Actor metadata — always set unless already provided (e.g. by table QR flow)
    order_dict["createdByEmail"] = order_dict.get("createdByEmail") or user.get("email")
    order_dict["createdByName"] = order_dict.get("createdByName") or user.get("name") or user.get("email")

    # Device metadata — prefer explicit header, fall back to UA
    hdr_dev = request.headers.get("X-Device-Label") or request.headers.get("x-device-label")
    hdr_devid = request.headers.get("X-Device-Id") or request.headers.get("x-device-id")
    ua = request.headers.get("user-agent", "")
    if not order_dict.get("deviceLabel"):
        order_dict["deviceLabel"] = hdr_dev or ("Mobile" if "Mobile" in ua else "Web POS")
    if not order_dict.get("deviceId"):
        order_dict["deviceId"] = hdr_devid or (request.client.host if request.client else "?")

    # Enrich from reservation if present
    if order_dict.get("reservationId") and (not order_dict.get("covers") or not order_dict.get("guestName")):
        res = await db.reservations.find_one({"id": order_dict["reservationId"]}, {"_id": 0})
        if res:
            order_dict["covers"] = order_dict.get("covers") or res.get("partySize") or res.get("guests")
            order_dict["guestName"] = order_dict.get("guestName") or res.get("customerName") or res.get("guestName")

    order_obj = KitchenOrder(**order_dict)
    await db.kitchen_orders.insert_one(order_obj.dict())
    result = order_obj.dict()
    await _broadcast_kitchen_update(result, "created")
    return result


@router.post("/kitchen/orders/{order_id}/start")
async def start_kitchen_order(order_id: str, user: dict = Depends(get_user)):
    result = await db.kitchen_orders.find_one_and_update(
        {"id": order_id, **tenant_scope_filter(user.get("businessId"))},
        {"$set": {"status": "preparing", "startedAt": _now()}},
        return_document=True,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Order not found")
    result.pop("_id", None)
    await _broadcast_kitchen_update(result, "started")
    return result


@router.post("/kitchen/orders/{order_id}/ready")
async def mark_order_ready(order_id: str, user: dict = Depends(get_user)):
    result = await db.kitchen_orders.find_one_and_update(
        {"id": order_id, **tenant_scope_filter(user.get("businessId"))},
        {"$set": {"status": "ready", "readyAt": _now()}},
        return_document=True,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Order not found")
    result.pop("_id", None)
    await _broadcast_kitchen_update(result, "ready")
    try:
        from services import notification_service as ns
        server_email = result.get("serverId") or result.get("createdByEmail")
        if server_email:
            await ns.send(email=server_email, kind="kitchen", severity="info",
                            title=f"Table {result.get('tableNumber') or '?'} — order ready",
                            body=f"All items are ready to run for order {order_id[:8]}.",
                            link=f"/kitchen?order={order_id}",
                            data={"orderId": order_id, "tableNumber": result.get("tableNumber")})
        else:
            await ns.send(role="server", topic="kitchen.ready", kind="kitchen",
                            title=f"Table {result.get('tableNumber') or '?'} — order ready",
                            body=f"Order {order_id[:8]} is ready to run.",
                            link=f"/kitchen?order={order_id}",
                            data={"orderId": order_id})
    except Exception:
        pass
    return result


@router.post("/kitchen/orders/{order_id}/served")
async def mark_order_served(order_id: str, user: dict = Depends(get_user)):
    result = await db.kitchen_orders.find_one_and_update(
        {"id": order_id, **tenant_scope_filter(user.get("businessId"))},
        {"$set": {"status": "served", "servedAt": _now()}},
        return_document=True,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Order not found")
    result.pop("_id", None)
    await _broadcast_kitchen_update(result, "served")
    return result


@router.post("/kitchen/orders/{order_id}/cancel")
async def cancel_kitchen_order(order_id: str, user: dict = Depends(get_user)):
    result = await db.kitchen_orders.find_one_and_update(
        {"id": order_id, **tenant_scope_filter(user.get("businessId"))},
        {"$set": {"status": "cancelled", "cancelledAt": _now()}},
        return_document=True,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Order not found")
    result.pop("_id", None)
    await _broadcast_kitchen_update(result, "cancelled")
    return result


# ─── Course lifecycle — HOLD / FIRE / SERVE per course ────────────────────
@router.post("/kitchen/orders/{order_id}/hold-course/{course}")
async def hold_course(order_id: str, course: int,
                      user: dict = Depends(require_permission("fire-course"))):
    """Explicitly hold a course — it will NOT fire automatically."""
    from services import course_events
    scope = tenant_scope_filter(user.get("businessId"))
    prior = await db.kitchen_orders.find_one({"id": order_id, **scope}, {"_id": 0, "courses": 1})
    prev_state = course_events.course_state(prior or {}, course)

    key = f"courses.{course}"
    result = await db.kitchen_orders.find_one_and_update(
        {"id": order_id, **scope},
        {"$set": {f"{key}.status": "held", f"{key}.heldAt": _now(),
                    f"{key}.firedAt": None, f"{key}.firedBy": None}},
        return_document=True,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Order not found")
    result.pop("_id", None)
    await course_events.record_transition(order_id, course, "held",
                                          user.get("name") or user.get("email"), prev_state)
    await course_events.reconcile_status(order_id)
    return result


async def fire_course_internal(order_id: str, course: int, actor: str,
                                business_id: Optional[str] = None) -> dict:
    """Fire a course and run every side effect: print the station dockets for
    that course, advance the table's pacing, notify the server.

    Shared by the endpoint below and by the timing rules that fire a course
    automatically, so an auto-fire behaves exactly like a server tapping Fire
    rather than quietly skipping the printing. `business_id` is optional
    because the scheduler-driven auto-fire path already resolves order_ids
    from its own per-business scan (see coursing_scheduler.py) — pass it
    whenever the caller has an authenticated user in scope (the HTTP route
    below always does) so a cross-tenant order_id 404s instead of matching.
    """
    from services import course_events
    scope = tenant_scope_filter(business_id)
    prior = await db.kitchen_orders.find_one({"id": order_id, **scope}, {"_id": 0, "courses": 1})
    prev_state = course_events.course_state(prior or {}, course)

    key = f"courses.{course}"
    result = await db.kitchen_orders.find_one_and_update(
        {"id": order_id, **scope},
        {"$set": {
            "currentCourse": course,
            f"{key}.status": "fired",
            f"{key}.firedAt": _now(),
            f"{key}.firedBy": actor,
            f"{key}.heldAt": None,
        }},
        return_document=True,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Order not found")
    result.pop("_id", None)

    from services import coursing as _coursing
    cfg = await _coursing.get_config(business_id=business_id)
    label = _course_label(course, cfg)

    await course_events.record_transition(order_id, course, "fired", actor, prev_state)
    await course_events.reconcile_status(order_id)
    await course_events.audit(
        "course_fired", result, course=course, actor=actor,
        memo=f"{label} fired for table {result.get('tableNumber') or '?'}"
             + (" (automatic — timing rule)" if actor == "auto" else ""),
        after={"course": course, "label": label, "firedBy": actor},
    )

    # A station prints when the course is fired, not when the order is rung
    # up — that's the whole point of holding a course. Items carry their
    # course so the docket can label the block.
    try:
        from services import print_routing
        if cfg.get("enabled"):
            fired_items = [
                {**it, "course": course, "courseLabel": label}
                for it in (result.get("items") or [])
                if int(it.get("course") or 1) == int(course)
            ]
            if fired_items:
                await print_routing.route_and_queue(
                    fired_items,
                    order_id=result.get("id"),
                    table_number=result.get("tableNumber"),
                    extra={"course": course, "courseLabel": label,
                           "kitchenOrderId": result.get("id")},
                )
    except Exception as e:
        log.warning("fire-course: docket print failed for %s: %s", order_id, e)

    # Keep the floor plan's pacing in step with what the kitchen just did.
    try:
        from services import table_pacing
        await table_pacing.advance_for_course(result, course, cfg)
    except Exception as e:
        log.warning("fire-course: pacing sync failed for %s: %s", order_id, e)

    try:
        from services import notification_service as ns
        server_email = result.get("serverId") or result.get("createdByEmail")
        title = f"Table {result.get('tableNumber') or '?'} — {label} fired"
        if server_email:
            await ns.send(email=server_email, kind="kitchen", severity="info", title=title,
                          body=f"Kitchen just fired {label} for your order.",
                          link=f"/kitchen?order={order_id}",
                          data={"orderId": order_id, "course": course})
        else:
            await ns.send(role="server", topic="kitchen.fire", kind="kitchen", title=title,
                          body=f"Kitchen just fired {label}.",
                          link=f"/kitchen?order={order_id}",
                          data={"orderId": order_id, "course": course})
    except Exception:
        pass
    return result


@router.post("/kitchen/orders/{order_id}/fire-course/{course}")
async def fire_course(order_id: str, course: int, user: dict = Depends(require_permission("fire-course"))):
    """Fire a specific course — lifts any hold, prints that course's dockets,
    and advances the table's pacing."""
    return await fire_course_internal(order_id, course, user.get("name") or user.get("email"),
                                       business_id=user.get("businessId"))


@router.post("/kitchen/orders/{order_id}/ready-course/{course}")
async def ready_course(order_id: str, course: int, user: dict = Depends(require_permission("fire-course"))):
    """Mark a single course ready at the pass.

    Order-level `ready` already existed, but with coursing the server needs to
    know that *this* course is up — otherwise they're back to watching the
    pass, which is what coursing was supposed to stop.
    """
    key = f"courses.{course}"
    result = await db.kitchen_orders.find_one_and_update(
        {"id": order_id, **tenant_scope_filter(user.get("businessId"))},
        {"$set": {f"{key}.status": "ready", f"{key}.readyAt": _now()}},
        return_document=True,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Order not found")
    result.pop("_id", None)
    from services import course_events
    await course_events.record_transition(order_id, course, "ready",
                                          user.get("name") or user.get("email"), "fired")
    await course_events.reconcile_status(order_id)
    try:
        from services import coursing as _coursing, notification_service as ns
        label = _course_label(course, await _coursing.get_config())
        server_email = result.get("serverId") or result.get("createdByEmail")
        title = f"Table {result.get('tableNumber') or '?'} — {label} ready"
        body = f"{label} is up at the pass."
        if server_email:
            await ns.send(email=server_email, kind="kitchen", severity="info", title=title,
                          body=body, link=f"/pos?order={order_id}",
                          data={"orderId": order_id, "course": course, "event": "ready"})
        else:
            await ns.send(role="server", topic="kitchen.ready", kind="kitchen", title=title,
                          body=body, link=f"/pos?order={order_id}",
                          data={"orderId": order_id, "course": course, "event": "ready"})
    except Exception as e:
        log.warning("ready-course: notify failed for %s: %s", order_id, e)
    return result


@router.post("/kitchen/orders/{order_id}/serve-course/{course}")
async def serve_course(order_id: str, course: int, user: dict = Depends(require_permission("fire-course"))):
    from services import course_events
    scope = tenant_scope_filter(user.get("businessId"))
    prior = await db.kitchen_orders.find_one({"id": order_id, **scope}, {"_id": 0, "courses": 1})
    prev_state = course_events.course_state(prior or {}, course)

    key = f"courses.{course}"
    result = await db.kitchen_orders.find_one_and_update(
        {"id": order_id, **scope},
        {"$set": {f"{key}.status": "served", f"{key}.servedAt": _now()}},
        return_document=True,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Order not found")
    result.pop("_id", None)
    await course_events.record_transition(order_id, course, "served",
                                          user.get("name") or user.get("email"), prev_state)
    await course_events.reconcile_status(order_id)
    return result


@router.get("/kitchen/orders/{order_id}/timings")
async def course_timings(order_id: str, user: dict = Depends(get_user)):
    """Per-course timings derived from the ticket's history trail.

    `atPassMinutes` is the number that actually costs a venue: food sitting
    under a lamp between the kitchen calling it ready and someone running it.
    """
    from services import course_events
    order = await db.kitchen_orders.find_one(
        {"id": order_id, **tenant_scope_filter(user.get("businessId"))}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return {
        "orderId": order_id,
        "tableNumber": order.get("tableNumber"),
        "courses": course_events.summarise(order),
        "history": order.get("courseHistory") or [],
    }


@router.post("/kitchen/orders/{order_id}/priority")
async def set_order_priority(order_id: str, priority: str = "rush", user: dict = Depends(get_user)):
    result = await db.kitchen_orders.find_one_and_update(
        {"id": order_id, **tenant_scope_filter(user.get("businessId"))},
        {"$set": {"priority": priority}}, return_document=True,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Order not found")
    result.pop("_id", None)
    return result


# ─── Owner-configurable docket display ────────────────────────────────────
DEFAULT_DOCKET_CONFIG = {
    "showStaffName": True,
    "showDevice": True,
    "showCovers": True,
    "showFireTime": True,
    "showTable": True,
    "showGuestName": True,
    "showElapsedTimer": True,
    "showItemNotes": True,
    "showOrderNotes": True,
    "showModifiers": True,
    "fontSize": "medium",           # small | medium | large
    "colourByCourse": True,
    "warnMinutes": 15,              # elapsed threshold for amber warning
    "criticalMinutes": 25,          # elapsed threshold for red critical
    "sortMode": "rungIn",           # rungIn | alphabetical | category — order items appear within a ticket
}


@router.get("/kitchen/docket-config")
async def get_docket_config(_: dict = Depends(get_user)):
    row = await db.kitchen_docket_config.find_one({"_id": "singleton"}, {"_id": 0})
    if not row:
        row = dict(DEFAULT_DOCKET_CONFIG)
        await db.kitchen_docket_config.insert_one({"_id": "singleton", **row})
    return row


@router.put("/kitchen/docket-config")
async def update_docket_config(body: dict, user: dict = Depends(get_user)):
    if user.get("role") not in ("owner", "manager"):
        raise HTTPException(status_code=403, detail="Owner or manager only")
    allowed = set(DEFAULT_DOCKET_CONFIG.keys())
    patch = {k: v for k, v in body.items() if k in allowed}
    patch["updatedAt"] = _now()
    patch["updatedBy"] = user.get("email")
    await db.kitchen_docket_config.update_one(
        {"_id": "singleton"},
        {"$set": {"_id": "singleton", **patch}},
        upsert=True,
    )
    row = await db.kitchen_docket_config.find_one({"_id": "singleton"}, {"_id": 0})
    return row


# ============ PREP MANAGEMENT API ============
@router.get("/kitchen/prep-list")
async def get_prep_list(user: dict = Depends(get_user)):
    biz = user.get("businessId")
    scope = tenant_scope_filter(biz)
    today = datetime.utcnow().strftime('%Y-%m-%d')
    reservations = await db.reservations.find({"date": today, **scope}, {"_id": 0}).to_list(100)
    total_covers = sum(r.get("partySize", 0) for r in reservations)

    products = await db.products.find(scope, {"_id": 0}).to_list(1000)
    all_txns = await db.transactions.find(scope, {"_id": 0}).to_list(10000)

    product_popularity = {}
    for txn in all_txns:
        for item in txn.get("items", []):
            pid = item.get("productId", "")
            product_popularity[pid] = product_popularity.get(pid, 0) + item.get("quantity", 0)

    total_qty = sum(product_popularity.values()) or 1

    prep_items = []
    for p in products:
        pop_qty = product_popularity.get(p["id"], 0)
        popularity_pct = (pop_qty / total_qty) * 100
        est_qty = max(1, int((pop_qty / max(len(all_txns), 1)) * max(total_covers, 10)))
        prep_items.append({
            "productId": p["id"], "name": p["name"], "category": p.get("category", "Other"),
            "currentStock": p.get("stock", 0), "estimatedNeeded": est_qty,
            "popularityPct": round(popularity_pct, 1), "prepStatus": "pending",
        })

    prep_items.sort(key=lambda x: x["estimatedNeeded"], reverse=True)
    return {"date": today, "expectedCovers": total_covers, "totalReservations": len(reservations), "prepItems": prep_items[:20]}
