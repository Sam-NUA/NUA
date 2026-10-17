"""Device identity — business → location → device → terminal → staff session.

A registered device gets a durable id embedded in future access tokens it
signs in with (see routes/auth.py's login()/create_access_token, and
routes/staff_management.py's PIN login — both accept an optional
X-Device-Id header). A revoked device's *future* logins are rejected
outright; an *already-issued* token for that device is rejected on its
next request by RequireAuthMiddleware's revocation check in server.py —
revocation is real-time, not "takes effect after the token expires."

Registration and revocation are owner/manager actions, same tier as other
terminal-affecting settings (POS session config, staff PINs) — a device is
venue infrastructure, not something an individual staff member manages.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from datetime import datetime, timezone

from database import db
from deps import get_user, require_owner_or_manager
from middleware.actor_context import tenant_scope_filter, tenant_owns_strict
from models.device import Device, DeviceRegister
from services.device_auth import is_device_revoked_or_missing  # re-exported for callers of this module

router = APIRouter(prefix="/devices")

ALLOWED_PLATFORMS = {"android", "ios", "windows", "web"}


@router.post("/register")
async def register_device(data: DeviceRegister, user: dict = Depends(get_user)):
    """Any authenticated staff member can claim a device identity for the
    terminal they're currently signed into — registration itself needs no
    elevated role (a cashier opening the app on a new tablet for the first
    time must be able to do this), but the device then belongs to the
    business, not to that staff member; only an owner/manager can list or
    revoke it afterward."""
    if data.platform not in ALLOWED_PLATFORMS:
        raise HTTPException(status_code=400, detail=f"platform must be one of {sorted(ALLOWED_PLATFORMS)}")
    business_id = user.get("businessId")
    if not business_id:
        raise HTTPException(status_code=400, detail="Active business membership required")
    device = Device.new(data, business_id, user["id"], user.get("name"))
    await db.devices.insert_one(device.dict())
    return device


@router.get("")
async def list_devices(user: dict = Depends(require_owner_or_manager)):
    rows = await db.devices.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}).sort("createdAt", -1).to_list(500)
    return rows


@router.post("/{device_id}/heartbeat")
async def device_heartbeat(device_id: str, user: dict = Depends(get_user)):
    """Cheap, called on app foreground/resume so `lastSeenAt` reflects real
    usage. Any authenticated staff member may call this for a device
    belonging to their own business — it reveals nothing and changes
    nothing but a timestamp."""
    scope = tenant_scope_filter(user.get("businessId"))
    result = await db.devices.find_one_and_update(
        {"id": device_id, **scope, "status": "active"},
        {"$set": {"lastSeenAt": datetime.now(timezone.utc).isoformat()}},
    )
    if not result:
        raise HTTPException(status_code=404, detail="Device not found or revoked")
    return {"ok": True}


@router.post("/{device_id}/revoke")
async def revoke_device(device_id: str, user: dict = Depends(require_owner_or_manager)):
    """Marks the device revoked. Already-issued access tokens carrying this
    deviceId are rejected on their very next request — see
    RequireAuthMiddleware in server.py — not just on their next refresh."""
    scope = tenant_scope_filter(user.get("businessId"))
    existing = await db.devices.find_one({"id": device_id, **scope}, {"_id": 0, "businessId": 1})
    if not existing or not tenant_owns_strict(existing.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Device not found")
    now = datetime.now(timezone.utc).isoformat()
    await db.devices.update_one(
        {"id": device_id, **scope},
        {"$set": {"status": "revoked", "revokedAt": now, "revokedBy": user["id"]}},
    )
    return {"ok": True}
