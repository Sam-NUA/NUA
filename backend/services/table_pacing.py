"""Bridge between kitchen coursing and floor-plan table pacing.

Two systems in this codebase are called "course" and mean different things:

  * `table_courses` — front-of-house pacing (seated -> drinks -> entree ->
    main -> dessert -> coffee -> check) with dwell timers and overdue colours
    on the floor plan.
  * kitchen coursing — which dish fires when, per ticket.

They ran independently, so the floor plan could show a table on "drinks"
twenty minutes after the kitchen fired its mains. Firing a kitchen course now
advances the table's pacing state to match, which means the dwell timers
measure something real.

This is best-effort on purpose: pacing is a display aid, and a failure to
advance it must never stop a course reaching the pass.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from database import db
import uuid

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _table_id_for_number(number: Optional[str], business_id: str) -> Optional[str]:
    """Pacing state is keyed by floor-plan table id, but a kitchen order only
    knows the table number the server typed."""
    if not number:
        return None
    try:
        from services import floor_tables
        hit = await floor_tables.resolve_table(number, business_id=business_id)
        return hit[0]["id"] if hit else None
    except Exception as e:                      # pragma: no cover - defensive
        log.warning("pacing: table lookup failed for %r: %s", number, e)
        return None


async def advance_for_course(order: Dict[str, Any], course: int,
                             config: Dict[str, Any]) -> Optional[str]:
    """Move the table's pacing state to whatever this kitchen course maps to.

    Returns the pacing key applied, or None when nothing was done (feature
    off, no mapping, no table, or the table isn't seated).
    """
    if not config.get("enabled") or not config.get("syncTablePacing"):
        return None
    pacing_key = (config.get("tablePacingMap") or {}).get(str(course))
    if not pacing_key:
        return None

    business_id = order.get("businessId")
    if not business_id:
        return None
    table_id = await _table_id_for_number(order.get("tableNumber"), business_id)
    if not table_id:
        return None

    # Food going to a table is the clearest possible signal it's occupied.
    # Waiting for payment to mark it would leave the floor plan showing an
    # empty table all through the meal.
    try:
        from services import floor_tables
        hit = await floor_tables.resolve_table(order.get("tableNumber"), business_id=business_id)
        if hit and hit[0].get("status") != "occupied":
            await floor_tables.set_table_status(hit[0]["id"], hit[1], "occupied", order.get("id"), business_id=business_id)
    except Exception as e:
        log.warning("pacing: could not mark table occupied: %s", e)

    try:
        existing = await db.table_states.find_one({"tableId": table_id, "businessId": business_id})
        now = _now()
        if not existing:
            # The table was never seated on the floor plan — the kitchen
            # firing food is good evidence someone is sitting there.
            await db.table_states.insert_one({
                "id": str(uuid.uuid4()), "tableId": table_id, "businessId": business_id,
                "course": pacing_key, "seatedAt": now, "courseStartedAt": now,
                "createdAt": now, "updatedAt": now,
                "guestName": order.get("guestName"),
                "createdBy": "coursing",
            })
            return pacing_key
        if existing.get("course") == pacing_key:
            return None                          # already there; don't reset the timer
        await db.table_states.update_one(
            {"tableId": table_id, "businessId": business_id},
            {"$set": {"course": pacing_key, "courseStartedAt": now, "updatedAt": now}},
        )
        return pacing_key
    except Exception as e:                       # pragma: no cover - defensive
        log.warning("pacing: advance failed for table %s: %s", table_id, e)
        return None
