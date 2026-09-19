"""
Table Course Management — dining courses, dwell timing, colour codes and the
"Send" nudge from the floor plan.

Concepts:
  • Course definitions live in `table_courses.settings` — owner/manager edits
    them once; the whole floor plan uses those thresholds to colour-code
    tables by their current course + dwell time.
  • Live table state (occupied since / current course) lives on the
    `table_states` collection keyed by tableId.
  • "Send" pushes a nudge to the assigned server via the dock's notification
    channel (persisted so the server can catch up if offline).
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel
from database import db
from deps import get_user
from middleware.actor_context import tenant_scope_filter, tenant_owns_strict
import uuid
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# ─── Defaults — sensible thresholds for a mid-tier venue ─────────────────
DEFAULT_COURSES = [
    {"key": "seated",    "label": "Seated",    "colour": "#1E293B", "maxMinutes": 5,   "next": "drinks"},
    {"key": "drinks",    "label": "Drinks",    "colour": "#38BDF8", "maxMinutes": 10,  "next": "entree"},
    {"key": "entree",    "label": "Entrée",    "colour": "#22C55E", "maxMinutes": 20,  "next": "main"},
    {"key": "main",      "label": "Main",      "colour": "#F59E0B", "maxMinutes": 45,  "next": "dessert"},
    {"key": "dessert",   "label": "Dessert",   "colour": "#EC4899", "maxMinutes": 20,  "next": "coffee"},
    {"key": "coffee",    "label": "Coffee",    "colour": "#8B5CF6", "maxMinutes": 15,  "next": "check"},
    {"key": "check",     "label": "Check",     "colour": "#EF4444", "maxMinutes": 10,  "next": None},
]
# A table past its course's maxMinutes gets flagged overdue (see `overdue` on
# each state below) — this is the accent colour the floor plan rings it in,
# layered on top of the course colour rather than replacing it, so staff can
# still see which course a late table is stuck in.
OVERDUE_COLOUR = "#F97316"


class Course(BaseModel):
    key: str
    label: str
    colour: str
    maxMinutes: int
    next: Optional[str] = None


class CoursesSettingsIn(BaseModel):
    courses: list[Course]
    overdueColour: Optional[str] = OVERDUE_COLOUR
    autoAdvance: bool = False        # if True, courses auto-advance when maxMinutes elapses


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# table_course_settings used to be a bare "_id": "singleton" doc shared by
# every business on the deployment. Re-keyed per business via
# services.tenant_settings.get_scoped_singleton/set_scoped_singleton — a
# business that has never customised its courses reads the legacy
# untagged document (same safe-default fallback as every other collection
# in this codebase), the first business to save its own gets its own
# tagged copy from then on. table_states and dock_notifications below were
# already fixed in an earlier pass (they're ordinary per-row collections,
# not singletons, and the gap there was worse than a read leak — see git
# history / TENANT_ISOLATION_REMAINING_WORK.md).
# ─── Settings CRUD ───────────────────────────────────────────────────────
@router.get("/table-courses/settings")
async def get_settings(user: dict = Depends(get_user)):
    from services.tenant_settings import get_scoped_singleton, set_scoped_singleton
    biz = user.get("businessId")
    row = await get_scoped_singleton(db.table_course_settings, {"scope": "singleton"}, biz)
    if not row:
        row = {
            "courses": DEFAULT_COURSES,
            "overdueColour": OVERDUE_COLOUR,
            "autoAdvance": False,
            "updatedAt": _now(),
        }
        await set_scoped_singleton(db.table_course_settings, {"scope": "singleton"}, row, biz)
    row.pop("_id", None)
    return row


@router.put("/table-courses/settings")
async def update_settings(body: CoursesSettingsIn, user: dict = Depends(get_user)):
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(403, "Owner or manager only")
    from services.tenant_settings import set_scoped_singleton
    payload = {
        "courses":       [c.dict() for c in body.courses],
        "overdueColour": body.overdueColour or OVERDUE_COLOUR,
        "autoAdvance":   bool(body.autoAdvance),
        "updatedAt":     _now(),
        "updatedBy":     user.get("email"),
    }
    await set_scoped_singleton(db.table_course_settings, {"scope": "singleton"}, payload, user.get("businessId"))
    return payload


# ─── Live table state ────────────────────────────────────────────────────
class TableStateIn(BaseModel):
    tableId: str
    course: Optional[str] = None
    partySize: Optional[int] = None
    serverId: Optional[str] = None
    reservationId: Optional[str] = None
    customerId: Optional[str] = None
    guestName: Optional[str] = None
    note: Optional[str] = None
    clearState: bool = False


@router.get("/table-courses/states")
async def list_states(user: dict = Depends(get_user)):
    """Return every table that has a live state (i.e. is currently occupied).
    Each row is enriched with derived colour + dwell minutes so the SPA can
    render without extra roundtrips."""
    states = await db.table_states.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}).to_list(500)
    from services.tenant_settings import get_scoped_singleton
    settings_row = await get_scoped_singleton(db.table_course_settings, {"scope": "singleton"}, user.get("businessId"))
    courses = (settings_row or {}).get("courses", DEFAULT_COURSES)
    overdue_colour = (settings_row or {}).get("overdueColour", OVERDUE_COLOUR)
    by_key = {c["key"]: c for c in courses}
    now = datetime.now(timezone.utc)

    # One batched lookup for every attached guest's VIP flag, instead of a
    # query per table — states rarely number more than a few dozen, but no
    # reason to pay N round trips for what's a single $in.
    customer_ids = [s["customerId"] for s in states if s.get("customerId")]
    vip_ids = set()
    if customer_ids:
        vip_customers = await db.customers.find(
            {**tenant_scope_filter(user.get("businessId")), "id": {"$in": customer_ids}, "isVip": True}, {"_id": 0, "id": 1}
        ).to_list(len(customer_ids))
        vip_ids = {c["id"] for c in vip_customers}

    enriched = []
    for s in states:
        course_obj = by_key.get(s.get("course"), by_key.get("seated", courses[0]))
        # Total dwell = since seatedAt; course dwell = since courseStartedAt.
        seated_at = s.get("seatedAt")
        course_at = s.get("courseStartedAt") or seated_at
        dwell_min = 0
        course_min = 0
        if seated_at:
            dwell_min = max(0, int((now - datetime.fromisoformat(seated_at)).total_seconds() // 60))
        if course_at:
            course_min = max(0, int((now - datetime.fromisoformat(course_at)).total_seconds() // 60))
        # `is not None`, not truthiness — a 0-minute threshold ("overdue the
        # moment this course starts") is a legitimate setting a venue can
        # dial in, but `0 and ...` short-circuits to falsy and would make it
        # unreachable.
        max_minutes = course_obj.get("maxMinutes")
        overdue = max_minutes is not None and course_min > max_minutes
        s["dwellMinutes"] = dwell_min
        s["courseMinutes"] = course_min
        s["courseLabel"] = course_obj.get("label")
        # The course's own colour, always — overdue is surfaced separately
        # via `overdue` (and the top-level `overdueColour`) so the floor
        # plan can ring a late table in the alert colour while still
        # showing which course it's stuck in, rather than replacing that
        # information with a flat "it's late" colour.
        s["colour"] = course_obj.get("colour")
        s["overdue"] = bool(overdue)
        s["isVip"] = s.get("customerId") in vip_ids
        enriched.append(s)
    return {"states": enriched, "courses": courses, "overdueColour": overdue_colour}


@router.post("/table-courses/states")
async def upsert_state(body: TableStateIn, user: dict = Depends(get_user)):
    """Seat a table, advance its course, or clear it (`clearState=true`)."""
    biz = user.get("businessId")
    scope = tenant_scope_filter(biz)
    if body.clearState:
        r = await db.table_states.delete_one({"tableId": body.tableId, **scope})
        return {"cleared": r.deleted_count > 0}

    existing = await db.table_states.find_one({"tableId": body.tableId, **scope})
    now = _now()
    if existing:
        update = {"updatedAt": now}
        if body.course and body.course != existing.get("course"):
            update["course"] = body.course
            update["courseStartedAt"] = now
        for f in ("partySize", "serverId", "reservationId", "customerId", "guestName", "note"):
            v = getattr(body, f)
            if v is not None:
                update[f] = v
        await db.table_states.update_one({"id": existing["id"]}, {"$set": update})
        return await db.table_states.find_one({"id": existing["id"]}, {"_id": 0})

    doc = {
        "id": str(uuid.uuid4()),
        "tableId": body.tableId,
        "course": body.course or "seated",
        "partySize": body.partySize,
        "serverId": body.serverId,
        "reservationId": body.reservationId,
        "customerId": body.customerId,
        "guestName": body.guestName,
        "note": body.note,
        "seatedAt": now,
        "courseStartedAt": now,
        "createdAt": now,
        "updatedAt": now,
        "createdBy": user.get("email"),
        "businessId": biz,
    }
    await db.table_states.insert_one(doc)
    doc.pop("_id", None)
    return doc


# ─── "Send" nudge from floor plan ────────────────────────────────────────
class SendNudgeIn(BaseModel):
    tableId: str
    message: str = "Please check on this table"
    targetServerId: Optional[str] = None      # overrides table's assigned server
    priority: str = "normal"                  # normal | urgent


@router.post("/table-courses/send")
async def send_nudge(body: SendNudgeIn, user: dict = Depends(get_user)):
    """Drops a notification into the dock for the server assigned to the
    table (or the explicit `targetServerId`). Also stored so the server can
    catch up when they log in."""
    biz = user.get("businessId")
    state = await db.table_states.find_one({"tableId": body.tableId, **tenant_scope_filter(biz)}, {"_id": 0})
    server_id = body.targetServerId or (state or {}).get("serverId")

    notif = {
        "id": str(uuid.uuid4()),
        "type": "table_nudge",
        "tableId": body.tableId,
        "serverId": server_id,          # None → broadcast to all servers
        "message": body.message,
        "priority": body.priority if body.priority in ("normal", "urgent") else "normal",
        "sentBy": user.get("email"),
        "sentAt": _now(),
        "read": False,
        "businessId": biz,
    }
    await db.dock_notifications.insert_one(notif)
    notif.pop("_id", None)

    # dock_notifications had no reader anywhere in the UI — a sent nudge was
    # persisted but never actually seen by the server it was meant for. Also
    # fan it out through the universal notification bell (already wired into
    # every staff screen), resolving serverId to their email when possible
    # and broadcasting to front-of-house otherwise.
    try:
        from services import notification_service
        target_email = None
        if server_id:
            staffer = await db.auth_users.find_one({"id": server_id}, {"_id": 0, "email": 1})
            target_email = (staffer or {}).get("email")
        await notification_service.send(
            kind="kitchen", title=f"Table {body.tableId} needs you", body=body.message,
            email=target_email, role=None if target_email else "cashier",
            severity="high" if notif["priority"] == "urgent" else "info",
            link="/floor-plan",
        )
    except Exception as e:
        from utils.errors import log_and_continue
        log_and_continue(logger, f"Table nudge bell notification failed for table {body.tableId}", e)

    return notif


@router.get("/table-courses/notifications")
async def list_notifications(serverId: Optional[str] = None, unreadOnly: bool = False,
                              user: dict = Depends(get_user)):
    q = tenant_scope_filter(user.get("businessId"))
    if serverId:
        q["$or"] = [{"serverId": serverId}, {"serverId": None}]
    if unreadOnly:
        q["read"] = False
    return await db.dock_notifications.find(q, {"_id": 0}).sort("sentAt", -1).to_list(200)


@router.post("/table-courses/notifications/{notif_id}/read")
async def mark_notif_read(notif_id: str, user: dict = Depends(get_user)):
    existing = await db.dock_notifications.find_one({"$and": [{"id": notif_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "businessId": 1})
    if not existing or not tenant_owns_strict(existing.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "Notification not found")
    r = await db.dock_notifications.update_one(
        {"$and": [{"id": notif_id}, tenant_scope_filter(user.get("businessId"))]},
        {"$set": {"read": True, "readAt": _now(), "readBy": user.get("email")}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Notification not found")
    return {"read": True}
