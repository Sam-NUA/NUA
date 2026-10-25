"""Tenant-isolated local printer dispatch: one delivery per target, never broadcast from every till.

A backend print job fans out to registered targets for its station. Each target
has an exclusive designated gateway, and each delivery can be claimed once.
A lost acknowledgement is **uncertain**, never blindly retried: the printer
may have received the bytes before connectivity was lost.
"""
from datetime import datetime, timedelta, timezone
import base64
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from database import db
from deps import get_user
from middleware.actor_context import tenant_scope_filter

router = APIRouter(prefix="/printer-fleet", tags=["Printer fleet"])
_KEY = re.compile(r"^[a-zA-Z0-9_-]{8,100}$")
_MAX_DEVICES = 32
_MAX_CLAIM = 12


def _now():
    return datetime.now(timezone.utc).isoformat()


def _identifier(value):
    if not isinstance(value, str) or not _KEY.fullmatch(value):
        raise HTTPException(422, "Invalid device or gateway identifier")
    return value


def _manage(user):
    if user.get("role") not in ("owner", "manager"):
        raise HTTPException(403, "Owner or manager only")


async def enqueue_for_station(job):
    """Create target-specific deliveries before the legacy backend send.

    A station with enabled local devices MUST NOT also be auto-printed by the
    cloud server; otherwise one order produces duplicate tickets.
    """
    scope = tenant_scope_filter(job.get("businessId"))
    targets = await db.printer_fleet_devices.find(
        {"station": job["printer"], "enabled": True, **scope}, {"_id": 0}
    ).to_list(_MAX_DEVICES)
    for device in targets:
        delivery_id = f"{job['id']}:{device['id']}"
        await db.printer_fleet_deliveries.update_one(
            {"_id": delivery_id, **scope},
            {"$setOnInsert": {
                "id": delivery_id, "jobId": job["id"], "deviceId": device["id"],
                "gatewayId": device["gatewayId"], "station": job["printer"],
                "businessId": job["businessId"], "status": "queued",
                "createdAt": _now(),
            }},
            upsert=True,
        )
    return bool(targets)


@router.get("/devices")
async def list_devices(user: dict = Depends(get_user)):
    _manage(user)
    return await db.printer_fleet_devices.find(
        tenant_scope_filter(user.get("businessId")), {"_id": 0}
    ).to_list(_MAX_DEVICES)


@router.put("/devices/{device_id}")
async def save_device(device_id: str, body: dict, user: dict = Depends(get_user)):
    _manage(user)
    device_id = _identifier(device_id)
    gateway_id = _identifier(body.get("gatewayId"))
    station = body.get("station")
    name = body.get("name")
    transport = body.get("transport")
    if not isinstance(station, str) or not 1 <= len(station.strip()) <= 100:
        raise HTTPException(422, "Station name required")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
        raise HTTPException(422, "Printer name required")
    if transport not in ("wifi", "bluetooth", "usb", "windows-spooler", "ble"):
        raise HTTPException(422, "Unsupported transport")
    scope = tenant_scope_filter(user.get("businessId"))
    existing = await db.printer_fleet_devices.find_one({"id": device_id, **scope})
    if not existing:
        count = await db.printer_fleet_devices.count_documents(scope)
        if count >= _MAX_DEVICES:
            raise HTTPException(409, "Maximum 32 printer targets per business")
    # Device connection secrets, host/IP and Bluetooth identifiers live only
    # on the chosen gateway: never distribute a MAC or printer IP to all users.
    document = {
        "id": device_id, "gatewayId": gateway_id,
        "businessId": user.get("businessId"), "station": station.strip(),
        "name": name.strip(), "transport": transport,
        "enabled": body.get("enabled") is True, "updatedAt": _now(),
        "updatedBy": user.get("id"),
        "width": min(96, max(24, int(body.get("width") or 48))),
        "codepage": body.get("codepage") if body.get("codepage") in ("cp437", "cp850") else "cp437",
        "cut": body.get("cut") if body.get("cut") in ("partial", "full", "legacy", "none") else "partial",
    }
    await db.printer_fleet_devices.update_one(
        {"id": device_id, **scope}, {"$set": document}, upsert=True
    )
    return document


@router.post("/devices/{device_id}/disable")
async def disable_device(device_id: str, user: dict = Depends(get_user)):
    _manage(user)
    scope = tenant_scope_filter(user.get("businessId"))
    result = await db.printer_fleet_devices.update_one(
        {"id": _identifier(device_id), **scope},
        {"$set": {"enabled": False, "updatedAt": _now()}}
    )
    if not result.matched_count:
        raise HTTPException(404, "Device not found")
    return {"disabled": True}


@router.post("/claim")
async def claim_deliveries(body: dict, user: dict = Depends(get_user)):
    """Claim independently per connected printer, capped at 12 per poll."""
    _manage(user)
    gateway = _identifier(body.get("gatewayId"))
    scope = tenant_scope_filter(user.get("businessId"))
    if not await db.printer_fleet_devices.find_one(
        {"gatewayId": gateway, "enabled": True, **scope}
    ):
        raise HTTPException(403, "Printer gateway not enabled for this business")
    # If a prior gateway died between sending and ack, DON'T retry:
    # acknowledgement timeout cannot tell if paper was produced.
    expiry = (datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat()
    await db.printer_fleet_deliveries.update_many(
        {"gatewayId": gateway, "status": "printing", "claimedAt": {"$lt": expiry}, **scope},
        {"$set": {"status": "uncertain", "error": "Gateway acknowledgement timed out"}},
    )
    maximum = min(_MAX_CLAIM, max(1, int(body.get("maxJobs") or 8)))
    out = []
    from services import escpos
    for _ in range(maximum):
        token = str(uuid.uuid4())
        delivery = await db.printer_fleet_deliveries.find_one_and_update(
            {"gatewayId": gateway, "status": "queued", **scope},
            {"$set": {"status": "printing", "claimToken": token, "claimedAt": _now()}},
            return_document=True,
        )
        if delivery is None:
            break
        target = await db.printer_fleet_devices.find_one(
            {"id": delivery["deviceId"], "gatewayId": gateway, "enabled": True, **scope}, {"_id": 0})
        job = await db.print_jobs.find_one(
            {"id": delivery["jobId"], **scope}, {"_id": 0})
        if not target or not job:
            await db.printer_fleet_deliveries.update_one(
                {"_id": delivery["_id"], "claimToken": token, **scope},
                {"$set": {"status": "uncertain", "error": "Printer disabled or source job missing"}},
            )
            continue
        payload = escpos.render(job, width=target["width"],
            codepage=target["codepage"], cut=target["cut"])
        out.append({"id": delivery["id"], "token": token, "deviceId": target["id"],
                    "station": target["station"], "transport": target["transport"],
                    "payload": base64.b64encode(payload).decode("ascii"),
                    "job": job})
    return {"deliveries": out}


@router.post("/complete")
async def complete_delivery(body: dict, user: dict = Depends(get_user)):
    _manage(user)
    delivery_id, token, gateway = body.get("id"), body.get("token"), body.get("gatewayId")
    _identifier(gateway)
    if not isinstance(delivery_id, str) or len(delivery_id) > 220 or not isinstance(token, str):
        raise HTTPException(422, "Invalid delivery acknowledgement")
    status = body.get("status")
    if status not in ("submitted", "uncertain"):
        raise HTTPException(422, "Invalid delivery status")
    scope = tenant_scope_filter(user.get("businessId"))
    changed = await db.printer_fleet_deliveries.update_one(
        {"id": delivery_id, "claimToken": token, "gatewayId": gateway,
         "status": "printing", **scope},
        {"$set": {"status": status, "completedAt": _now(),
                  "error": str(body.get("error") or "")[:250] if status == "uncertain" else ""}},
    )
    if changed.modified_count != 1:
        raise HTTPException(409, "Delivery already acknowledged or claim no longer valid")
    return {"status": status}


@router.get("/status")
async def delivery_status(user: dict = Depends(get_user)):
    _manage(user)
    return await db.printer_fleet_deliveries.find(
        tenant_scope_filter(user.get("businessId")), {"_id": 0, "claimToken": 0}
    ).sort("createdAt", -1).to_list(100)


@router.post("/retry/{delivery_id:path}")
async def manual_retry(delivery_id: str, user: dict = Depends(get_user)):
    """Only explicit operator intervention may resend an uncertain ticket."""
    _manage(user)
    scope = tenant_scope_filter(user.get("businessId"))
    result = await db.printer_fleet_deliveries.update_one(
        {"id": delivery_id, "status": "uncertain", **scope},
        {"$set": {"status": "queued", "error": "", "requeuedAt": _now()},
         "$unset": {"claimToken": "", "claimedAt": ""}},
    )
    if result.modified_count != 1:
        raise HTTPException(409, "Only uncertain deliveries can be manually retried")
    return {"status": "queued"}
