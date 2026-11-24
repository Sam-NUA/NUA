"""Smart Table Service: owner controls and staff-facing actionable alerts."""
from __future__ import annotations
from typing import Dict, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from database import db
from deps import get_user
from middleware.actor_context import tenant_scope_filter
from services import floor_tables, table_service_alerts as service

router = APIRouter(prefix="/table-service", tags=["Smart Table Service"])


def _business(user):
    biz = user.get("businessId")
    if not isinstance(biz, str) or not biz:
        raise HTTPException(403, "Business context required")
    return biz


def _floor_staff(user):
    if user.get("role") not in {"owner", "manager", "cashier", "server", "kitchen"}:
        raise HTTPException(403, "Floor staff or manager role required")


class RuleInput(BaseModel):
    enabled: bool = True
    warningMinutes: int = Field(ge=1, le=240)
    escalateMinutes: int = Field(ge=1, le=360)


class SettingsInput(BaseModel):
    enabled: bool = False
    popupEnabled: bool = True
    rules: Dict[str, RuleInput]


class SnoozeInput(BaseModel):
    minutes: Literal[1, 3, 5, 10, 15] = 3


class AssignServerInput(BaseModel):
    serverId: Optional[str] = None


class EventInput(BaseModel):
    event: Literal[
        "order_taken", "drinks_served", "food_order_taken", "entree_served",
        "follow_up_done", "bill_requested", "bill_delivered",
    ]


@router.get("/settings")
async def settings(user: dict = Depends(get_user)):
    _floor_staff(user)
    return await service.settings_for(_business(user))


@router.put("/settings")
async def save_settings(body: SettingsInput, user: dict = Depends(get_user)):
    if user.get("role") != "owner":
        raise HTTPException(403, "Only the business owner can adjust service reminders")
    biz = _business(user)
    if set(body.rules) != set(service.DEFAULT_RULES):
        raise HTTPException(422, "Specify exactly the supported service alert rules")
    rules = {key: val.dict() for key, val in body.rules.items()}
    for row in rules.values():
        if row["escalateMinutes"] < row["warningMinutes"]:
            raise HTTPException(422, "Escalation must not be earlier than the first warning")
    return await service.write_settings(biz, {
        "enabled": body.enabled, "popupEnabled": body.popupEnabled, "rules": rules,
    }, user.get("email"))


@router.get("/alerts")
async def alerts(includeResolved: bool = False, user: dict = Depends(get_user)):
    _floor_staff(user)
    cfg = await service.settings_for(_business(user))
    return {"alerts": await service.alerts_for(user, include_resolved=includeResolved),
            "enabled": cfg["enabled"], "popupEnabled": cfg["popupEnabled"]}


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge(alert_id: str, user: dict = Depends(get_user)):
    _floor_staff(user)
    if not await service.update_alert(user, alert_id, "acknowledge"):
        raise HTTPException(404, "Active service alert not found")
    return {"status": "acknowledged"}


@router.post("/alerts/{alert_id}/snooze")
async def snooze(alert_id: str, body: SnoozeInput, user: dict = Depends(get_user)):
    _floor_staff(user)
    if not await service.update_alert(user, alert_id, "snooze", minutes=body.minutes):
        raise HTTPException(404, "Active service alert not found")
    return {"status": "snoozed", "minutes": body.minutes}


@router.post("/alerts/{alert_id}/resolve")
async def resolve(alert_id: str, user: dict = Depends(get_user)):
    _floor_staff(user)
    if not await service.update_alert(user, alert_id, "resolve"):
        raise HTTPException(404, "Active service alert not found")
    return {"status": "resolved"}


@router.post("/tables/{table_id}/events")
async def mark_event(table_id: str, body: EventInput, user: dict = Depends(get_user)):
    _floor_staff(user)
    if user.get("role") == "kitchen" and body.event in {
        "order_taken", "drinks_served", "food_order_taken",
        "follow_up_done", "bill_requested", "bill_delivered",
    }:
        raise HTTPException(403, "Floor staff action required")
    biz = _business(user)
    # Check BOTH real floor-table ownership and active seating-session scope,
    # never allow a client to synthesize an event for an arbitrary table ID.
    table = await floor_tables.get_table_by_id(table_id, business_id=biz)
    if table is None:
        raise HTTPException(404, "Table not found at this venue")
    now = service.iso(service.now_utc())
    result = await db.table_states.update_one(
        {"tableId": table_id, **tenant_scope_filter(biz)},
        {"$set": {f"serviceEvents.{body.event}": now, "updatedAt": now}},
    )
    if result.matched_count != 1:
        raise HTTPException(409, "Seat the table on the floor plan first")
    return {"tableId": table_id, "event": body.event, "at": now}


@router.get("/servers")
async def available_floor_servers(user: dict = Depends(get_user)):
    if user.get("role") not in {"owner", "manager"}:
        raise HTTPException(403, "Manager permission required")
    biz = _business(user)
    return await db.auth_users.find(
        {"businessId": biz, "role": {"$in": ["owner", "manager", "cashier", "server"]},
         "isActive": {"$ne": False}},
        {"_id": 0, "id": 1, "email": 1, "name": 1, "role": 1},
    ).to_list(200)


@router.put("/tables/{table_id}/server")
async def assign_floor_server(table_id: str, body: AssignServerInput, user: dict = Depends(get_user)):
    if user.get("role") not in {"owner", "manager"}:
        raise HTTPException(403, "Manager permission required")
    biz = _business(user)
    if not await floor_tables.get_table_by_id(table_id, business_id=biz):
        raise HTTPException(404, "Table not found at this venue")
    if body.serverId:
        if not isinstance(body.serverId, str) or len(body.serverId) > 128:
            raise HTTPException(422, "Invalid staff identifier")
        server = await db.auth_users.find_one({
            "id": body.serverId, "businessId": biz, "_ownershipQuarantined": {"$ne": True},
            "isActive": {"$ne": False}, "role": {"$in": ["owner", "manager", "cashier", "server"]},
        }, {"_id": 0, "id": 1})
        if not server:
            raise HTTPException(422, "Staff member must belong to this business")
    scope = tenant_scope_filter(biz)
    current = await db.table_states.find_one({"tableId": table_id, **scope}, {"_id": 0, "id": 1})
    if not current:
        raise HTTPException(409, "Seat the table before assigning floor staff")
    await db.table_states.update_one(
        {"tableId": table_id, **scope}, {"$set": {"serverId": body.serverId}})
    await db.table_service_alerts.update_many(
        {"tableId": table_id, "sessionId": current.get("id"), **scope,
         "status": {"$ne": "resolved"}},
        {"$set": {"serverId": body.serverId}})
    return {"tableId": table_id, "serverId": body.serverId}
