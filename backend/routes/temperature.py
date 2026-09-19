"""
Fridge / Freezer temperature monitoring — HACCP-friendly, hardware-agnostic.

The owner (or a manager) registers each cold-storage unit (fridge, freezer,
cool-room) and pairs it with a supported sensor brand — SensorPush, Govee,
Inkbird, ThermoPro, Monnit, Cooper-Atkins, or a generic HTTP/webhook feed.
NUA then ingests readings via either:

  1. Generic webhook — third-party devices POST to /api/temperature/ingest
     with a shared secret and their own device identifier.
  2. Manual entry — for battery/device failures. Staff can log a reading
     from the POS at any time.
  3. Twice-daily reminder — the scheduler nudges staff to record if no
     automatic reading has landed in 12 h.

Alerts fire when a reading is outside the device's normal range (owner
configurable) — both via email and via a POS dock notification.

Reports: weekly, monthly, yearly, plus a custom (start, end) window for
audits and food-safety inspectors.
"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from typing import Optional
from datetime import datetime, timedelta, timezone, date
from pydantic import BaseModel
from database import db
from deps import get_user
from middleware.actor_context import tenant_scope_filter, tenant_owns_strict
import uuid
import os
import statistics

router = APIRouter()

# ─── Supported sensor brands ─────────────────────────────────────────────
# The registry is what the owner sees when adding a device. New brands are
# added by simply extending this list — the ingestion path itself is generic.
SUPPORTED_BRANDS = [
    {"key": "sensorpush",        "label": "SensorPush",         "connectivity": ["bluetooth", "wifi_gateway"],
     "productLine": ["HT.w", "HTP.xw", "HT1", "HT.wsx"], "hasCloudAPI": True,
     "docsUrl": "https://www.sensorpush.com/gateway-cloud-api"},
    {"key": "govee",             "label": "Govee",              "connectivity": ["bluetooth", "wifi"],
     "productLine": ["H5075", "H5100", "H5101", "H5074"], "hasCloudAPI": True,
     "docsUrl": "https://developer.govee.com/"},
    {"key": "inkbird",           "label": "Inkbird",            "connectivity": ["bluetooth", "wifi"],
     "productLine": ["IBS-TH2", "IBS-TH1 Plus", "ITH-20B", "IBS-M1"], "hasCloudAPI": True,
     "docsUrl": "https://developer.inkbird.com/"},
    {"key": "thermopro",         "label": "ThermoPro",          "connectivity": ["bluetooth", "wifi"],
     "productLine": ["TP357", "TP359", "TP63", "TP49"], "hasCloudAPI": False,
     "docsUrl": ""},
    {"key": "monnit",            "label": "Monnit",             "connectivity": ["wifi", "cellular", "lora"],
     "productLine": ["ALTA", "MoWi Temp", "Coin Cell"], "hasCloudAPI": True,
     "docsUrl": "https://www.monnit.com/support/documentation/api"},
    {"key": "cooper_atkins",     "label": "Cooper-Atkins (Emerson)", "connectivity": ["wifi", "wireless_gateway"],
     "productLine": ["TempTrak", "Blue2"], "hasCloudAPI": True,
     "docsUrl": "https://www.emerson.com/en-us/support"},
    {"key": "hobo_onset",        "label": "HOBO (Onset)",       "connectivity": ["bluetooth", "wifi_gateway"],
     "productLine": ["MX2201", "MX2301", "MX2303", "MX Gateway"], "hasCloudAPI": True,
     "docsUrl": "https://www.onsetcomp.com/support/hoboconnect-api"},
    {"key": "lacrosse",          "label": "La Crosse View",     "connectivity": ["wifi"],
     "productLine": ["View series"], "hasCloudAPI": True,
     "docsUrl": "https://lacrossetechnology.com/pages/api"},
    {"key": "ambient_weather",   "label": "Ambient Weather",    "connectivity": ["wifi"],
     "productLine": ["WS-8482", "WS-2902"], "hasCloudAPI": True,
     "docsUrl": "https://ambientweather.docs.apiary.io/"},
    {"key": "wireless_tag",      "label": "Wireless Sensor Tags", "connectivity": ["bluetooth", "wifi_gateway"],
     "productLine": ["Ethernet Tag Manager"], "hasCloudAPI": True,
     "docsUrl": "https://wirelesstag.net/apidoc.html"},
    {"key": "sensaphone",        "label": "Sensaphone",         "connectivity": ["cellular", "wifi", "landline"],
     "productLine": ["Sentinel Pro", "WSG30"], "hasCloudAPI": True,
     "docsUrl": "https://www.sensaphone.com/support/"},
    {"key": "generic",           "label": "Generic (HTTP webhook)", "connectivity": ["wifi", "cellular"],
     "productLine": [], "hasCloudAPI": False,
     "docsUrl": ""},
    {"key": "manual",            "label": "Manual entry only",  "connectivity": [],
     "productLine": [], "hasCloudAPI": False,
     "docsUrl": ""},
]

# Sensible defaults (°C) for common cold-storage types.
DEFAULT_RANGES = {
    "fridge":     {"minC": 1.0,  "maxC": 5.0},
    "freezer":    {"minC": -22.0, "maxC": -15.0},
    "cool_room":  {"minC": 2.0,  "maxC": 8.0},
    "display":    {"minC": 2.0,  "maxC": 6.0},
    "warmer":     {"minC": 60.0, "maxC": 80.0},   # hot-hold cabinets (HACCP > 60°C)
}


# ─── Models ──────────────────────────────────────────────────────────────
class Device(BaseModel):
    id: str
    name: str                        # human label — "Kitchen Fridge #1"
    unitType: str                    # fridge | freezer | cool_room | display | warmer
    brand: str                       # key from SUPPORTED_BRANDS
    model: Optional[str] = None
    connectivity: str = "wifi"       # bluetooth | wifi | wifi_gateway | cellular | manual
    deviceId: Optional[str] = None   # brand-native identifier used at ingest
    location: Optional[str] = None   # "Prep kitchen", "Bar", ...
    minC: float
    maxC: float
    active: bool = True
    ingestSecret: Optional[str] = None   # webhook secret for the generic path
    createdAt: str
    updatedAt: str


class DeviceIn(BaseModel):
    name: str
    unitType: str = "fridge"
    brand: str = "manual"
    model: Optional[str] = None
    connectivity: str = "wifi"
    deviceId: Optional[str] = None
    location: Optional[str] = None
    minC: Optional[float] = None
    maxC: Optional[float] = None
    active: bool = True


class ReadingIn(BaseModel):
    deviceId: str                    # our device.id, NOT the vendor id
    temperatureC: float
    humidity: Optional[float] = None
    batteryPct: Optional[int] = None
    source: str = "manual"           # manual | webhook | scheduled_reminder
    recordedAt: Optional[str] = None # ISO — defaults to now
    note: Optional[str] = None


class WebhookIn(BaseModel):
    """Payload from a third-party device (or a companion Bluetooth app on
    a phone) — must include our shared `ingestSecret` for auth."""
    deviceId: str                    # our device.id
    ingestSecret: str
    temperatureC: float
    humidity: Optional[float] = None
    batteryPct: Optional[int] = None
    vendorDeviceId: Optional[str] = None   # informational — logged for traceability
    recordedAt: Optional[str] = None


# ─── Helpers ─────────────────────────────────────────────────────────────
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _classify(temp_c: float, dev: dict) -> str:
    """abnormal_low | normal | abnormal_high"""
    if temp_c < dev["minC"]:
        return "abnormal_low"
    if temp_c > dev["maxC"]:
        return "abnormal_high"
    return "normal"


async def _create_alert(device: dict, reading: dict, background_tasks: Optional[BackgroundTasks] = None):
    alert = {
        "id": str(uuid.uuid4()),
        "deviceId": device["id"],
        "deviceName": device["name"],
        "unitType": device["unitType"],
        "temperatureC": reading["temperatureC"],
        "status": reading["status"],            # abnormal_low | abnormal_high
        "expectedRange": {"minC": device["minC"], "maxC": device["maxC"]},
        "recordedAt": reading["recordedAt"],
        "acknowledged": False,
        "acknowledgedBy": None,
        "acknowledgedAt": None,
        "createdAt": _now_iso(),
        "businessId": device.get("businessId"),
    }
    await db.temperature_alerts.insert_one(alert)
    # Fire the notification asynchronously so ingest stays snappy.
    if background_tasks is not None:
        background_tasks.add_task(_send_alert_email, alert, device)


async def _send_alert_email(alert: dict, device: dict):
    """Best-effort email — logs on failure so ingest never breaks."""
    try:
        from utilities.email_sender import send_email
    except Exception:
        return
    subject = f"⚠️ Temperature alert: {device['name']} — {alert['temperatureC']}°C"
    body = (
        f"Hi team,\n\n{device['name']} ({device.get('unitType')}) recorded "
        f"{alert['temperatureC']}°C at {alert['recordedAt']}.\n"
        f"Expected range: {device['minC']}°C to {device['maxC']}°C.\n"
        f"Status: {alert['status']}.\n\n"
        "Please inspect the unit and take corrective action. This alert is also "
        "visible in the POS notifications dock.\n\n— Nua Restaurant OS"
    )
    to = os.environ.get("TEMP_ALERT_EMAIL") or os.environ.get("OWNER_EMAIL")
    if to:
        try:
            await send_email(to=to, subject=subject, body=body)
        except Exception:
            pass


# ─── Device catalog ──────────────────────────────────────────────────────
@router.get("/temperature/brands")
async def brands(_: dict = Depends(get_user)):
    """Sensor brands & product lines that NUA knows how to work with."""
    return {
        "brands": SUPPORTED_BRANDS,
        "defaultRanges": DEFAULT_RANGES,
    }


@router.get("/temperature/devices")
async def list_devices(user: dict = Depends(get_user)):
    q = tenant_scope_filter(user.get("businessId"))
    return await db.temperature_devices.find(q, {"_id": 0, "ingestSecret": 0}).sort("createdAt", -1).to_list(200)


@router.post("/temperature/devices")
async def create_device(body: DeviceIn, user: dict = Depends(get_user)):
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(403, "Owner or manager only")
    if body.unitType not in DEFAULT_RANGES:
        raise HTTPException(400, f"unitType must be one of {sorted(DEFAULT_RANGES)}")
    if not any(b["key"] == body.brand for b in SUPPORTED_BRANDS):
        raise HTTPException(400, "unknown brand — see /temperature/brands")

    defaults = DEFAULT_RANGES[body.unitType]
    doc = {
        "id": str(uuid.uuid4()),
        "name": body.name,
        "unitType": body.unitType,
        "brand": body.brand,
        "model": body.model,
        "connectivity": body.connectivity,
        "deviceId": body.deviceId,
        "location": body.location,
        "minC": float(body.minC if body.minC is not None else defaults["minC"]),
        "maxC": float(body.maxC if body.maxC is not None else defaults["maxC"]),
        "active": body.active,
        "ingestSecret": uuid.uuid4().hex,   # rotate via /temperature/devices/{id}/rotate-secret
        "createdBy": user.get("email"),
        "createdAt": _now_iso(),
        "updatedAt": _now_iso(),
        "businessId": user.get("businessId"),
    }
    await db.temperature_devices.insert_one(doc)
    doc.pop("_id", None)
    return doc   # includes the secret exactly ONCE for the owner to copy into the device.


@router.patch("/temperature/devices/{device_id}")
async def update_device(device_id: str, data: dict, user: dict = Depends(get_user)):
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(403, "Owner or manager only")
    guard = await db.temperature_devices.find_one({"$and": [{"id": device_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "id": 1, "businessId": 1})
    if guard is None or not tenant_owns_strict(guard.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "Device not found")
    allowed = {"name", "unitType", "brand", "model", "connectivity", "deviceId",
               "location", "minC", "maxC", "active"}
    update = {k: v for k, v in data.items() if k in allowed}
    if not update:
        raise HTTPException(400, "Nothing to update")
    update["updatedAt"] = _now_iso()
    r = await db.temperature_devices.update_one({"$and": [{"id": device_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": update})
    if r.matched_count == 0:
        raise HTTPException(404, "Device not found")
    return await db.temperature_devices.find_one({"$and": [{"id": device_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "ingestSecret": 0})


@router.delete("/temperature/devices/{device_id}")
async def delete_device(device_id: str, user: dict = Depends(get_user)):
    if user["role"] != "owner":
        raise HTTPException(403, "Owner only")
    guard = await db.temperature_devices.find_one({"$and": [{"id": device_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "id": 1, "businessId": 1})
    if guard is None or not tenant_owns_strict(guard.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "Device not found")
    r = await db.temperature_devices.delete_one({"$and": [{"id": device_id}, tenant_scope_filter(user.get("businessId"))]})
    if r.deleted_count == 0:
        raise HTTPException(404, "Device not found")
    return {"deleted": True}


@router.post("/temperature/devices/{device_id}/rotate-secret")
async def rotate_secret(device_id: str, user: dict = Depends(get_user)):
    if user["role"] != "owner":
        raise HTTPException(403, "Owner only")
    guard = await db.temperature_devices.find_one({"$and": [{"id": device_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "id": 1, "businessId": 1})
    if guard is None or not tenant_owns_strict(guard.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "Device not found")
    new_secret = uuid.uuid4().hex
    r = await db.temperature_devices.update_one(
        {"$and": [{"id": device_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": {"ingestSecret": new_secret, "updatedAt": _now_iso()}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Device not found")
    return {"ingestSecret": new_secret}


# ─── Readings + ingest ───────────────────────────────────────────────────
@router.post("/temperature/readings")
async def log_reading(body: ReadingIn, background_tasks: BackgroundTasks,
                       user: dict = Depends(get_user)):
    """Manual reading endpoint — used from the POS 'Log now' button and as a
    fallback when a sensor is offline or its battery died."""
    device = await db.temperature_devices.find_one({"$and": [{"id": body.deviceId}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not device or not tenant_owns_strict(device.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "Device not found")
    return await _persist_reading(device, body.temperatureC, body.humidity,
                                  body.batteryPct, body.source or "manual",
                                  body.recordedAt, body.note, user.get("email"),
                                  background_tasks)


@router.post("/temperature/ingest")
async def webhook_ingest(body: WebhookIn, background_tasks: BackgroundTasks):
    """Generic webhook — any third-party device (or its cloud bridge) can POST
    here. Auth is per-device via the `ingestSecret` we hand out at device
    creation. No login required — devices don't do JWT."""
    device = await db.temperature_devices.find_one({"id": body.deviceId}, {"_id": 0})
    if not device or device.get("ingestSecret") != body.ingestSecret:
        # Constant-response body so an attacker can't tell "device not found"
        # apart from "wrong secret".
        raise HTTPException(401, "Unauthorized")
    note = f"vendorDeviceId={body.vendorDeviceId}" if body.vendorDeviceId else None
    return await _persist_reading(device, body.temperatureC, body.humidity,
                                  body.batteryPct, "webhook",
                                  body.recordedAt, note, f"device:{device['brand']}",
                                  background_tasks)


async def _persist_reading(device, temp_c, humidity, battery, source, recorded_at,
                            note, recorded_by, background_tasks):
    status = _classify(float(temp_c), device)
    doc = {
        "id": str(uuid.uuid4()),
        "deviceId": device["id"],
        "deviceName": device["name"],
        "unitType": device["unitType"],
        "temperatureC": round(float(temp_c), 2),
        "humidity": humidity,
        "batteryPct": battery,
        "source": source,
        "status": status,
        "recordedAt": recorded_at or _now_iso(),
        "recordedBy": recorded_by,
        "note": note,
        "createdAt": _now_iso(),
        "businessId": device.get("businessId"),
    }
    await db.temperature_readings.insert_one(doc)
    if status != "normal":
        await _create_alert(device, doc, background_tasks)
    doc.pop("_id", None)
    return doc


@router.get("/temperature/readings")
async def list_readings(deviceId: Optional[str] = None,
                         start: Optional[str] = None, end: Optional[str] = None,
                         limit: int = 500, user: dict = Depends(get_user)):
    query = tenant_scope_filter(user.get("businessId"))
    if deviceId:
        query["deviceId"] = deviceId
    if start:
        query["recordedAt"] = {"$gte": start}
    if end:
        query.setdefault("recordedAt", {})["$lte"] = end
    return await db.temperature_readings.find(query, {"_id": 0}).sort("recordedAt", -1).to_list(limit)


# ─── Alerts ──────────────────────────────────────────────────────────────
@router.get("/temperature/alerts")
async def list_alerts(unacknowledgedOnly: bool = False, user: dict = Depends(get_user)):
    query = tenant_scope_filter(user.get("businessId"))
    if unacknowledgedOnly:
        query["acknowledged"] = False
    return await db.temperature_alerts.find(query, {"_id": 0}).sort("createdAt", -1).to_list(200)


@router.post("/temperature/alerts/{alert_id}/acknowledge")
async def ack_alert(alert_id: str, user: dict = Depends(get_user)):
    guard = await db.temperature_alerts.find_one({"$and": [{"id": alert_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "id": 1, "businessId": 1})
    if guard is None or not tenant_owns_strict(guard.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "Alert not found")
    r = await db.temperature_alerts.update_one(
        {"$and": [{"id": alert_id}, tenant_scope_filter(user.get("businessId"))]},
        {"$set": {"acknowledged": True, "acknowledgedBy": user.get("email"),
                  "acknowledgedAt": _now_iso()}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Alert not found")
    return {"acknowledged": True}


# ─── Reports (W / M / Y / custom range) ──────────────────────────────────
def _period_bounds(period: str, anchor: Optional[str] = None):
    """Return (start_iso, end_iso) for `weekly | monthly | yearly` anchored on
    `anchor` (defaults to today)."""
    d = date.fromisoformat(anchor) if anchor else date.today()
    if period == "weekly":
        start = d - timedelta(days=d.weekday())     # Monday
        end   = start + timedelta(days=6)
    elif period == "monthly":
        start = d.replace(day=1)
        # end = last day of the month
        next_month = start.replace(day=28) + timedelta(days=4)
        end = next_month - timedelta(days=next_month.day)
    elif period == "yearly":
        start = d.replace(month=1, day=1)
        end   = d.replace(month=12, day=31)
    else:
        raise HTTPException(400, "period must be weekly | monthly | yearly")
    return start.isoformat(), end.isoformat()


@router.get("/temperature/report")
async def report(period: Optional[str] = None,
                  start: Optional[str] = None, end: Optional[str] = None,
                  deviceId: Optional[str] = None,
                  user: dict = Depends(get_user)):
    """Compliance-friendly summary sheet.

    Two modes:
      • `period=weekly|monthly|yearly` (optionally with `start=YYYY-MM-DD`
        as anchor) — automatic bounds.
      • `start` + `end` — arbitrary custom range for audits.

    Returns per-device aggregates + a chronological log the owner can print.
    """
    if period:
        s, e = _period_bounds(period, anchor=start)
    elif start and end:
        s, e = start, end
    else:
        # default to last 7 days
        s = (date.today() - timedelta(days=6)).isoformat()
        e = date.today().isoformat()

    range_start = f"{s}T00:00:00+00:00"
    range_end   = f"{e}T23:59:59+00:00"
    biz_scope = tenant_scope_filter(user.get("businessId"))
    q = {"recordedAt": {"$gte": range_start, "$lte": range_end}, **biz_scope}
    if deviceId:
        q["deviceId"] = deviceId
    readings = await db.temperature_readings.find(q, {"_id": 0}).sort("recordedAt", 1).to_list(5000)

    devices = {d["id"]: d for d in await db.temperature_devices.find(
        biz_scope, {"_id": 0, "ingestSecret": 0}).to_list(500)}

    per_device = {}
    for r in readings:
        pd = per_device.setdefault(r["deviceId"], {"readings": [], "abnormal": 0})
        pd["readings"].append(r)
        if r["status"] != "normal":
            pd["abnormal"] += 1

    devices_summary = []
    for dev_id, bucket in per_device.items():
        temps = [x["temperatureC"] for x in bucket["readings"]]
        dev = devices.get(dev_id, {"name": "Unknown", "unitType": "fridge",
                                    "minC": 0, "maxC": 8})
        devices_summary.append({
            "deviceId": dev_id,
            "deviceName": dev.get("name"),
            "unitType": dev.get("unitType"),
            "expectedRange": {"minC": dev.get("minC"), "maxC": dev.get("maxC")},
            "readingsCount": len(temps),
            "abnormalCount": bucket["abnormal"],
            "minObservedC":   round(min(temps), 2) if temps else None,
            "maxObservedC":   round(max(temps), 2) if temps else None,
            "avgObservedC":   round(statistics.fmean(temps), 2) if temps else None,
            "stdDevC":        round(statistics.pstdev(temps), 2) if len(temps) > 1 else 0.0,
        })

    return {
        "range": {"start": s, "end": e, "period": period or "custom"},
        "totalReadings": len(readings),
        "totalAbnormal": sum(d["abnormalCount"] for d in devices_summary),
        "devicesCovered": len(devices_summary),
        "devices": devices_summary,
        "readings": readings,
        "generatedAt": _now_iso(),
    }


# ─── Twice-daily reminder scan ───────────────────────────────────────────
@router.post("/temperature/scan-missing")
async def scan_missing(user: dict = Depends(get_user)):
    """Runs the twice-daily 'have you logged temperature?' check. Any active
    device with no reading in the last 12 h gets a reminder alert dropped
    into the POS dock. This is invoked either on a cron OR from the POS
    dock's periodic sweep."""
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=12)).isoformat()
    devices = await db.temperature_devices.find(
        {"active": True, **tenant_scope_filter(user.get("businessId"))}, {"_id": 0, "ingestSecret": 0}
    ).to_list(200)

    reminders = 0
    for dev in devices:
        latest = await db.temperature_readings.find_one(
            {"deviceId": dev["id"], "recordedAt": {"$gte": cutoff}}, {"_id": 0},
        )
        if latest:
            continue
        alert = {
            "id": str(uuid.uuid4()),
            "deviceId": dev["id"],
            "deviceName": dev["name"],
            "unitType": dev["unitType"],
            "temperatureC": None,
            "status": "missing_reading",
            "expectedRange": {"minC": dev["minC"], "maxC": dev["maxC"]},
            "recordedAt": None,
            "acknowledged": False,
            "createdAt": _now_iso(),
            "businessId": dev.get("businessId"),
        }
        await db.temperature_alerts.insert_one(alert)
        reminders += 1

    return {"remindersCreated": reminders, "scannedAt": _now_iso()}
