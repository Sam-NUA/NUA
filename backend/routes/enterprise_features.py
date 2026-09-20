from fastapi import APIRouter, HTTPException, Depends
from deps import require_owner, require_owner_or_manager, get_user
from database import db
from middleware.actor_context import tenant_scope_filter
from datetime import datetime, timezone
import uuid

router = APIRouter()

# ============ AUTO SURCHARGING (Public Holiday + Weekend) ============
# Every endpoint in this file previously had no auth dependency at all, and
# every db.settings read/write below was a single document shared by every
# business on the deployment — see services/tenant_settings.py.
@router.get("/surcharge/settings")
async def get_surcharge_settings(user: dict = Depends(get_user)):
    from services.tenant_settings import get_setting
    value = await get_setting("surcharge_config", user.get("businessId"))
    return value or {
        "weekendSurcharge": 0, "publicHolidaySurcharge": 0, "enabled": False,
        "publicHolidays": [], "weekendDays": ["Saturday", "Sunday"],
    }

@router.post("/surcharge/settings")
async def save_surcharge_settings(data: dict, user: dict = Depends(require_owner)):
    from services.tenant_settings import set_setting
    await set_setting("surcharge_config", data, user.get("businessId"))
    return {"message": "Surcharge settings saved"}

@router.get("/surcharge/check")
async def check_surcharge(user: dict = Depends(get_user)):
    """Check if surcharge applies right now"""
    from services.tenant_settings import get_setting
    config = await get_setting("surcharge_config", user.get("businessId")) or {}
    if not config.get("enabled"):
        return {"surchargePercent": 0, "reason": None}
    now = datetime.now(timezone.utc)
    day_name = now.strftime("%A")
    date_str = now.strftime("%Y-%m-%d")
    if date_str in config.get("publicHolidays", []):
        return {"surchargePercent": config.get("publicHolidaySurcharge", 0), "reason": "Public Holiday Surcharge"}
    if day_name in config.get("weekendDays", []):
        return {"surchargePercent": config.get("weekendSurcharge", 0), "reason": "Weekend Surcharge"}
    return {"surchargePercent": 0, "reason": None}

# ============ AUTO-GRATUITY ============
# Multiple conditional rates (e.g. 18% for parties of 6+, 10% default), and a
# choice of whether the rate applies to the pre-discount subtotal or the
# discounted net — a discount shouldn't quietly shrink the tip a server
# earned for the same work.
@router.get("/gratuity/settings")
async def get_gratuity_settings(user: dict = Depends(get_user)):
    from services.tenant_settings import get_setting
    value = await get_setting("gratuity_config", user.get("businessId"))
    return value or {
        "enabled": False,
        "calculateOn": "post_discount",  # pre_discount | post_discount
        "rates": [],  # [{id, label, percent, minCovers, maxCovers}]
    }

@router.post("/gratuity/settings")
async def save_gratuity_settings(data: dict, user: dict = Depends(require_owner)):
    from services.tenant_settings import set_setting
    await set_setting("gratuity_config", data, user.get("businessId"))
    return {"message": "Gratuity settings saved"}

def _match_gratuity_rate(rates, covers):
    """Most specific match wins: a rule scoped to a covers range beats the
    unconditional default, so a 6+ party gets 18% instead of falling through
    to the standard 10%."""
    if covers is not None:
        for r in rates:
            lo, hi = r.get("minCovers"), r.get("maxCovers")
            if lo is not None or hi is not None:
                if (lo is None or covers >= lo) and (hi is None or covers <= hi):
                    return r
    for r in rates:
        if r.get("minCovers") is None and r.get("maxCovers") is None:
            return r
    return None

@router.get("/gratuity/check")
async def check_gratuity(covers: int = None, user: dict = Depends(get_user)):
    """Which gratuity rate (if any) applies right now, for this party size."""
    from services.tenant_settings import get_setting
    config = await get_setting("gratuity_config", user.get("businessId")) or {}
    calculate_on = config.get("calculateOn", "post_discount")
    if not config.get("enabled"):
        return {"gratuityPercent": 0, "label": None, "calculateOn": calculate_on}
    rate = _match_gratuity_rate(config.get("rates") or [], covers)
    if not rate:
        return {"gratuityPercent": 0, "label": None, "calculateOn": calculate_on}
    return {"gratuityPercent": float(rate.get("percent") or 0), "label": rate.get("label"), "calculateOn": calculate_on}

# ============ LIVE SALES REPORTING ============
@router.get("/live-sales")
async def get_live_sales(user: dict = Depends(require_owner_or_manager)):
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    all_txns = await db.transactions.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}).to_list(50000)
    # Filter today's transactions
    today_txns = []
    for t in all_txns:
        ts = t.get("timestamp")
        if ts and hasattr(ts, 'replace'):
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= today_start:
                today_txns.append(t)
        else:
            today_txns.append(t)
    if not today_txns and all_txns:
        today_txns = all_txns[-20:]  # Fallback: show last 20

    total = sum(t.get("total", 0) for t in today_txns)
    count = len(today_txns)
    avg = total / max(count, 1)
    # By hour
    by_hour = {}
    for t in today_txns:
        ts = t.get("timestamp")
        h = ts.hour if ts and hasattr(ts, 'hour') else 0
        by_hour[h] = by_hour.get(h, {"count": 0, "total": 0})
        by_hour[h]["count"] += 1
        by_hour[h]["total"] += t.get("total", 0)
    # Last 5 transactions
    last5 = sorted(today_txns, key=lambda x: x.get("timestamp", ""), reverse=True)[:5]
    for t in last5:
        t.pop("_id", None)

    return {
        "totalSales": round(total, 2), "transactionCount": count, "avgTicket": round(avg, 2),
        "byHour": [{"hour": h, "count": v["count"], "total": round(v["total"], 2)} for h, v in sorted(by_hour.items())],
        "recentTransactions": last5,
        "timestamp": now.isoformat(),
    }

# ============ CUSTOM PERMISSIONS (Granular) ============
from services.permission_catalog import (
    DEFAULT_ROLE_PERMISSIONS,
    all_permission_ids, catalog_for_ui,
)

ALL_PERMISSIONS = all_permission_ids()


async def _role_permissions_for(role: str, business_id: str) -> list:
    """Read per-role permission list from `role_permissions` collection, with
    fallback to the code-level DEFAULT_ROLE_PERMISSIONS. Owner is always full."""
    if role == "owner":
        return ["*"]
    doc = await db.role_permissions.find_one(
        {"role": role, **tenant_scope_filter(business_id)}, {"_id": 0})
    if doc and isinstance(doc.get("permissions"), list):
        return [p for p in doc["permissions"] if p in ALL_PERMISSIONS]
    return list(DEFAULT_ROLE_PERMISSIONS.get(role, []))


@router.get("/permissions/all")
async def get_all_permissions():
    # Kept flat for backwards-compat; new UIs should call /permissions/catalog.
    return ALL_PERMISSIONS


@router.get("/permissions/catalog")
async def get_permission_catalog():
    """Section-grouped catalog for the Settings UI."""
    return {"sections": catalog_for_ui(), "totalFeatures": len(ALL_PERMISSIONS)}


@router.get("/permissions/roles")
async def list_role_permissions(user: dict = Depends(require_owner_or_manager)):
    """List of every role → its effective default permissions.

    Includes Owner (always `*`), the four built-in roles, plus any custom roles
    referenced on `auth_users`. Owner uses this to grant/revoke by role.
    """
    roles = list(DEFAULT_ROLE_PERMISSIONS.keys())
    # Pick up any custom roles staff members were assigned
    user_roles = await db.auth_users.distinct(
        "role", tenant_scope_filter(user.get("businessId")))
    for r in user_roles or []:
        if r and r not in roles:
            roles.append(r)
    out = []
    for r in roles:
        perms = await _role_permissions_for(r, user.get("businessId"))
        # Look up whether it's persisted (dbOverride) or still using code default
        doc = await db.role_permissions.find_one(
            {"role": r, **tenant_scope_filter(user.get("businessId"))}, {"_id": 0})
        out.append({
            "role": r,
            "permissions": perms,
            "isOverridden": bool(doc),
            "isOwner": r == "owner",
            "featureCount": len(ALL_PERMISSIONS) if perms == ["*"] else len(perms),
        })
    return {"roles": out, "totalFeatures": len(ALL_PERMISSIONS)}


@router.post("/permissions/roles/{role}")
async def set_role_permissions(role: str, data: dict, user: dict = Depends(require_owner)):
    """Owner-only: update the default permission list for a role. Owner role
    itself can't be modified — Owner always has full access."""
    role = role.strip()
    if role == "owner":
        raise HTTPException(status_code=400, detail="Owner permissions cannot be modified")
    perms = data.get("permissions", [])
    if not isinstance(perms, list):
        raise HTTPException(status_code=400, detail="permissions must be a list")
    valid = [p for p in perms if p in ALL_PERMISSIONS]
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.role_permissions.update_one(
        {"role": role, **tenant_scope_filter(user.get("businessId"))},
        {"$set": {"role": role, "permissions": valid, "updatedAt": now_iso,
                  "businessId": user.get("businessId")}},
        upsert=True,
    )
    return {
        "role": role,
        "permissions": valid,
        "featureCount": len(valid),
        "message": f"Saved {len(valid)} permissions for {role}",
    }


@router.delete("/permissions/roles/{role}")
async def reset_role_permissions(role: str, user: dict = Depends(require_owner)):
    """Owner-only: reset a role back to its built-in defaults."""
    if role == "owner":
        raise HTTPException(status_code=400, detail="Owner permissions cannot be modified")
    await db.role_permissions.delete_one(
        {"role": role, **tenant_scope_filter(user.get("businessId"))})
    return {"role": role, "permissions": list(DEFAULT_ROLE_PERMISSIONS.get(role, [])), "message": f"{role} reset to defaults"}


@router.get("/permissions/staff/{staff_id}")
async def get_staff_permissions(staff_id: str, user: dict = Depends(require_owner_or_manager)):
    staff = await db.auth_users.find_one(
        {"id": staff_id, **tenant_scope_filter(user.get("businessId"))},
        {"_id": 0, "password_hash": 0},
    )
    if not staff:
        raise HTTPException(status_code=404, detail="Staff not found")
    # Effective = customPermissions if set, else the role default
    custom = staff.get("customPermissions")
    role_default = await _role_permissions_for(staff.get("role"), user.get("businessId"))
    return {
        "staffId": staff_id,
        "name": staff.get("name"),
        "role": staff.get("role"),
        "customPermissions": custom or [],
        "roleDefaults": role_default,
        "usingRoleDefaults": not bool(custom),
    }


@router.post("/permissions/staff/{staff_id}")
async def set_staff_permissions(staff_id: str, data: dict, user: dict = Depends(require_owner)):
    permissions = data.get("permissions", [])
    valid = [p for p in permissions if p in ALL_PERMISSIONS]
    result = await db.auth_users.update_one(
        {"id": staff_id, **tenant_scope_filter(user.get("businessId"))},
        {"$set": {"customPermissions": valid}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Staff not found")
    return {"message": f"Permissions updated ({len(valid)} permissions set)", "permissions": valid}


@router.delete("/permissions/staff/{staff_id}")
async def clear_staff_override(staff_id: str, user: dict = Depends(require_owner)):
    """Remove per-staff overrides — the user falls back to their role defaults."""
    result = await db.auth_users.update_one(
        {"id": staff_id, **tenant_scope_filter(user.get("businessId"))},
        {"$unset": {"customPermissions": ""}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Staff not found")
    role_default = []
    staff = await db.auth_users.find_one(
        {"id": staff_id, **tenant_scope_filter(user.get("businessId"))}, {"_id": 0, "role": 1})
    if staff:
        role_default = await _role_permissions_for(staff.get("role"), user.get("businessId"))
    return {"message": "Reverted to role defaults", "roleDefaults": role_default}

# ============ AUTOMATED REPORTING ============
@router.get("/reports/automated-config")
async def get_report_config(user: dict = Depends(require_owner)):
    from services.tenant_settings import get_setting
    value = await get_setting("auto_report_config", user.get("businessId"))
    return value or {
        "enabled": False, "frequency": "daily", "time": "23:00",
        "reportTypes": ["itemised", "category", "detailed"],
        "recipientEmail": "", "includeAIInsights": True,
    }

@router.post("/reports/automated-config")
async def save_report_config(data: dict, user: dict = Depends(require_owner)):
    from services.tenant_settings import set_setting
    await set_setting("auto_report_config", data, user.get("businessId"))
    return {"message": "Automated report settings saved"}

# ============ HARDWARE INTEGRATIONS ============
@router.get("/hardware/printers")
async def get_printer_configs(_: dict = Depends(get_user)):
    printers = await db.hardware_printers.find(tenant_scope_filter(), {"_id": 0}).to_list(100)
    return printers

@router.post("/hardware/printers")
async def add_printer(data: dict, user: dict = Depends(require_owner_or_manager)):
    printer = {
        "id": f"PRT-{str(uuid.uuid4())[:8].upper()}",
        "name": data.get("name", ""), "type": data.get("type", "receipt"),
        "connectionType": data.get("connectionType", "usb"),  # usb, network, bluetooth
        "ipAddress": data.get("ipAddress", ""), "port": data.get("port", 9100),
        "model": data.get("model", ""), "status": "configured",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "businessId": user.get("businessId"),
    }
    await db.hardware_printers.insert_one(printer)
    printer.pop("_id", None)
    return printer

@router.delete("/hardware/printers/{printer_id}")
async def delete_printer(printer_id: str, user: dict = Depends(require_owner_or_manager)):
    await db.hardware_printers.delete_one({"id": printer_id, **tenant_scope_filter(user.get("businessId"))})
    return {"message": "Printer removed"}

@router.get("/hardware/scanners")
async def get_scanner_configs(_: dict = Depends(get_user)):
    scanners = await db.hardware_scanners.find(tenant_scope_filter(), {"_id": 0}).to_list(100)
    return scanners

@router.post("/hardware/scanners")
async def add_scanner(data: dict, user: dict = Depends(require_owner_or_manager)):
    scanner = {
        "id": f"SCN-{str(uuid.uuid4())[:8].upper()}",
        "name": data.get("name", ""), "type": data.get("type", "barcode"),
        "connectionType": data.get("connectionType", "usb"),
        "model": data.get("model", ""), "status": "configured",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "businessId": user.get("businessId"),
    }
    await db.hardware_scanners.insert_one(scanner)
    scanner.pop("_id", None)
    return scanner
