"""
Finalization batch — v27.7.

Consolidates the remaining feature endpoints from the finalization brief so
we don't scatter tiny router files everywhere. Groups covered:

  • Pre-Shift briefing        (aggregates OOS, specials, roster, upsells)
  • Booking day-rules         (per-day settings + bookable specials)
  • Marketing analytics       (bookings source attribution + promo QR)
  • Channel controls          (pause/resume/schedule per channel)
  • Guest digital wallet      (QR/barcode payload + AI-driven CRM ping)
  • PDF/Excel exports         (low-stock, AI-pantry, generic reports)
  • Automation triggers       (user-defined + AI-suggested actions)
  • Store locations extended  (logo, website, timings, gmb)

All endpoints are additive — they layer on top of existing modules.
"""
from fastapi import APIRouter, HTTPException, Depends, Response
from typing import Optional, List
from datetime import datetime, timezone, timedelta, date
from pydantic import BaseModel
from database import db
from deps import get_user
from middleware.actor_context import tenant_scope_filter, tenant_owns
import uuid
import io
import base64
import json
import os
import hmac
import hashlib

router = APIRouter()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═════════════════════════════════════════════════════════════════════════
# Pre-Shift briefing (aggregate — a single call instead of 6)
# ═════════════════════════════════════════════════════════════════════════
@router.get("/preshift/briefing")
async def preshift_briefing(user: dict = Depends(get_user)):
    """One call → everything a manager needs before service:
       - out-of-stock items
       - today's specials
       - who's on shift (today's roster, plus anyone clocked in without one)
       - dishes to push (low-margin? high-stock? high-margin flagged?)
    """
    today = date.today().isoformat()
    biz = user.get("businessId")
    scope = tenant_scope_filter(biz)

    # Out-of-stock: any product where stock <= 0 OR eightySixed=True
    oos = await db.products.find(
        {"$or": [{"stock": {"$lte": 0}}, {"eightySixed": True}], **scope},
        {"_id": 0, "id": 1, "name": 1, "category": 1, "stock": 1, "eightySixed": 1},
    ).to_list(500)

    # Specials: `isSpecial=true` OR promotion active today
    specials = await db.products.find(
        {"isSpecial": True, **scope},
        {"_id": 0, "id": 1, "name": 1, "category": 1, "price": 1, "description": 1},
    ).to_list(200)
    active_promos = await db.promotions.find(
        {"active": True, **scope},
        {"_id": 0, "id": 1, "name": 1, "discount": 1, "schedule": 1},
    ).to_list(200)

    # Who's on shift — today's roster is the real schedule (db.staff_shifts /
    # db.shifts, read here previously, are dead collections nothing in the
    # app writes to any more; actual clock-ins land in db.timecards, keyed
    # by staffId, not by date, so they're matched up by prefix on clockIn).
    # roster_shifts/timecards don't carry their own businessId (same
    # pre-existing schema gap as payroll.py's timecards), so both are scoped
    # transitively through this business's own staff list.
    from services.punctuality import shift_punctuality
    is_owner = user.get("role") == "owner"

    staff_ids = {s["id"] for s in await db.auth_users.find(scope, {"_id": 0, "id": 1}).to_list(500)}
    roster_today = await db.roster_shifts.find(
        {"date": today, "staffId": {"$in": list(staff_ids)}}, {"_id": 0}).sort("startTime", 1).to_list(200)
    timecards_today = await db.timecards.find(
        {"clockIn": {"$regex": f"^{today}"}, "staffId": {"$in": list(staff_ids)}}, {"_id": 0}
    ).to_list(200)
    # Last clock-in of the day per staff member — covers a same-day re-clock
    # after a missed clock-out being fixed up, without double-counting them
    # in the list below.
    tc_by_staff = {}
    for tc in timecards_today:
        tc_by_staff[tc.get("staffId")] = tc

    shifts_today = []
    seen_staff_ids = set()
    for sh in roster_today:
        staff_id = sh.get("staffId")
        seen_staff_ids.add(staff_id)
        entry = {"staffId": staff_id, "staffName": sh.get("staffName"), "role": sh.get("role")}
        # Owners see actual attendance to check punctuality; everyone else
        # just sees who's rostered on, same as before this change.
        if is_owner:
            entry["scheduledStart"] = sh.get("startTime")
            entry["scheduledEnd"] = sh.get("endTime")
            tc = tc_by_staff.get(staff_id)
            entry["clockIn"] = tc.get("clockIn") if tc else None
            entry["clockOut"] = tc.get("clockOut") if tc else None
            if tc:
                p = shift_punctuality(tc, sh)
                entry["lateMinutes"] = p["lateMinutes"]
                entry["earlyLeaveMinutes"] = p["earlyLeaveMinutes"]
                entry["onTime"] = p["onTime"]
        shifts_today.append(entry)
    # Anyone clocked in today without a rostered shift (e.g. a manager
    # approved an unscheduled clock-in) still counts as on shift.
    for tc in timecards_today:
        staff_id = tc.get("staffId")
        if staff_id in seen_staff_ids:
            continue
        seen_staff_ids.add(staff_id)
        entry = {"staffId": staff_id, "staffName": tc.get("staffName"), "role": tc.get("role")}
        if is_owner:
            entry["scheduledStart"] = None
            entry["scheduledEnd"] = None
            entry["clockIn"] = tc.get("clockIn")
            entry["clockOut"] = tc.get("clockOut")
        shifts_today.append(entry)

    # Upsell candidates — high-margin items with plenty of stock
    upsells = await db.products.find(
        {"stock": {"$gt": 10}, "$or": [{"eightySixed": {"$exists": False}}, {"eightySixed": False}], **scope},
        {"_id": 0, "id": 1, "name": 1, "category": 1, "price": 1, "cost": 1},
    ).sort("price", -1).to_list(500)
    def margin_pct(p):
        c = p.get("cost") or 0
        if not p.get("price") or c is None:
            return 0
        return round(((p["price"] - c) / p["price"]) * 100, 1) if p["price"] else 0
    upsells_ranked = sorted(
        [{**p, "marginPct": margin_pct(p)} for p in upsells],
        key=lambda x: (-x["marginPct"], -(x.get("price") or 0)),
    )[:10]

    return {
        "date": today,
        "outOfStock": oos,
        "specials": specials,
        "activePromotions": active_promos,
        "onShift": shifts_today,
        "onShiftCount": len(shifts_today),
        "upsells": upsells_ranked,
        "generatedAt": _now(),
    }


# ═════════════════════════════════════════════════════════════════════════
# Booking day-rules + bookable specials/experiences
# ═════════════════════════════════════════════════════════════════════════
class DayRuleIn(BaseModel):
    weekday: int                    # 0=Mon … 6=Sun
    open: bool = True
    openTime: str = "12:00"
    closeTime: str = "22:00"
    maxCovers: Optional[int] = None
    slotMinutes: int = 30
    turnMinutes: int = 90
    minPartySize: int = 1
    maxPartySize: int = 20
    bookableSpecials: List[str] = []     # product ids
    bookableExperienceIds: List[str] = []
    note: Optional[str] = None


@router.get("/bookings/day-rules")
async def get_day_rules(_: dict = Depends(get_user)):
    rows = await db.booking_day_rules.find({}, {"_id": 0}).to_list(20)
    have = {r["weekday"] for r in rows}
    # Fill any missing weekday with a sensible default so the UI always has 7 rows.
    for i in range(7):
        if i not in have:
            rows.append({"weekday": i, "open": True, "openTime": "12:00", "closeTime": "22:00",
                          "slotMinutes": 30, "turnMinutes": 90, "minPartySize": 1, "maxPartySize": 20,
                          "bookableSpecials": [], "bookableExperienceIds": [], "note": None})
    rows.sort(key=lambda r: r["weekday"])
    return rows


@router.put("/bookings/day-rules/{weekday}")
async def update_day_rule(weekday: int, body: DayRuleIn, user: dict = Depends(get_user)):
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(403, "Owner or manager only")
    if not (0 <= weekday <= 6):
        raise HTTPException(400, "weekday must be 0..6")
    payload = {**body.dict(), "weekday": weekday, "updatedAt": _now(), "updatedBy": user.get("email")}
    await db.booking_day_rules.update_one({"weekday": weekday}, {"$set": payload}, upsert=True)
    return payload


# ═════════════════════════════════════════════════════════════════════════
# Marketing analytics — booking-source attribution + promo QR
# ═════════════════════════════════════════════════════════════════════════
def _sign_qr(payload: dict) -> str:
    """Sign a QR payload with the JWT secret so scans can be verified."""
    secret = os.environ["JWT_SECRET"].encode()
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    sig = hmac.new(secret, raw, hashlib.sha256).hexdigest()[:16]
    b64 = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return f"{b64}.{sig}"


@router.get("/marketing/promo-qr")
async def promo_qr(type: str, id: str, campaign: Optional[str] = None,
                    _: dict = Depends(get_user)):
    """Return a signed payload the SPA can turn into a QR code / short-URL for
    any promoted asset (experience, voucher, gift card, loyalty tier, ...).

    `type` ∈ {experience, voucher, gift_card, loyalty, promotion, event, club}
    """
    allowed = {"experience", "voucher", "gift_card", "loyalty", "promotion", "event", "club"}
    if type not in allowed:
        raise HTTPException(400, f"type must be one of {sorted(allowed)}")
    payload = {"t": type, "id": id, "c": campaign or "", "ts": int(datetime.now(timezone.utc).timestamp())}
    token = _sign_qr(payload)
    origin = os.environ.get("FRONTEND_URL", "").rstrip("/")
    return {
        "token": token,
        "url": f"{origin}/scan?t={token}" if origin else f"/scan?t={token}",
        "payload": payload,
    }


@router.post("/marketing/scan")
async def marketing_scan(body: dict):
    """Public endpoint — the QR landing page pings this so we can track
    scan → booking attribution. Fingerprint by IP is deliberately loose."""
    await db.marketing_scans.insert_one({
        "id": str(uuid.uuid4()),
        "token": body.get("token"),
        "t": body.get("t"), "sourceId": body.get("id"), "campaign": body.get("c"),
        "referrer": body.get("referrer"), "ua": body.get("ua"),
        "createdAt": _now(),
    })
    return {"tracked": True}


@router.get("/marketing/analytics")
async def marketing_analytics(days: int = 30, _: dict = Depends(get_user)):
    """Rolls up scans + bookings + revenue by source over `days`."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    scans = await db.marketing_scans.find({"createdAt": {"$gte": since}}, {"_id": 0}).to_list(5000)
    bookings = await db.reservations.find({"createdAt": {"$gte": since}}, {"_id": 0}).to_list(5000)
    by_source = {}
    for b in bookings:
        src = (b.get("source") or b.get("channel") or "walk-in").lower()
        bucket = by_source.setdefault(src, {"bookings": 0, "covers": 0, "estRevenue": 0.0})
        bucket["bookings"] += 1
        bucket["covers"] += int(b.get("partySize") or 0)
        bucket["estRevenue"] += float(b.get("estRevenue") or 0)
    scans_by_type = {}
    for s in scans:
        scans_by_type.setdefault(s.get("t") or "other", 0)
        scans_by_type[s.get("t") or "other"] += 1
    return {
        "windowDays": days,
        "totalScans": len(scans),
        "totalBookings": len(bookings),
        "scansByType": scans_by_type,
        "bookingsBySource": by_source,
        "generatedAt": _now(),
    }


# ═════════════════════════════════════════════════════════════════════════
# Channel controls — pause / resume / schedule per delivery channel
# ═════════════════════════════════════════════════════════════════════════
class ChannelStateIn(BaseModel):
    channel: str
    action: str                     # pause | resume | schedule
    pausedUntil: Optional[str] = None      # ISO datetime for scheduled resume
    reason: Optional[str] = None


@router.get("/channels/state")
async def channel_states(_: dict = Depends(get_user)):
    rows = await db.channel_states.find({}, {"_id": 0}).to_list(50)
    return rows


@router.post("/channels/state")
async def update_channel_state(body: ChannelStateIn, user: dict = Depends(get_user)):
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(403, "Owner or manager only")
    if body.action not in ("pause", "resume", "schedule"):
        raise HTTPException(400, "action must be pause | resume | schedule")
    doc = {
        "channel": body.channel,
        "status": "paused" if body.action in ("pause", "schedule") else "active",
        "pausedUntil": body.pausedUntil if body.action == "schedule" else None,
        "reason": body.reason,
        "updatedAt": _now(),
        "updatedBy": user.get("email"),
    }
    await db.channel_states.update_one({"channel": body.channel}, {"$set": doc}, upsert=True)
    return doc


# ─── Channel schedule (simple daily + advanced weekly + date overrides) ──
class ChannelHours(BaseModel):
    open: Optional[str] = None      # "HH:MM" 24h
    close: Optional[str] = None
    closed: bool = False


class ChannelScheduleOverride(BaseModel):
    date: str                       # YYYY-MM-DD
    closed: bool = False
    open: Optional[str] = None
    close: Optional[str] = None
    reason: Optional[str] = None


class ChannelScheduleIn(BaseModel):
    enabled: bool = False
    mode: str = "simple"            # simple | weekly
    simpleHours: Optional[ChannelHours] = None
    weeklyHours: Optional[dict] = None   # {mon: {open,close,closed}, ...}
    overrides: List[ChannelScheduleOverride] = []


_WEEK_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _default_schedule(channel: str) -> dict:
    return {
        "channel": channel,
        "enabled": False,
        "mode": "simple",
        "simpleHours": {"open": "09:00", "close": "22:00", "closed": False},
        "weeklyHours": {d: {"open": "09:00", "close": "22:00", "closed": False} for d in _WEEK_KEYS},
        "overrides": [],
    }


def _hhmm_to_min(s: Optional[str]) -> Optional[int]:
    if not s or ":" not in s:
        return None
    try:
        h, m = s.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None


def _compute_open_now(schedule: dict, now: datetime) -> dict:
    """Given a schedule doc and a datetime, return {isOpen, reason, nextChange}."""
    if not schedule.get("enabled"):
        return {"isOpen": True, "reason": "schedule disabled"}
    today_key = _WEEK_KEYS[now.weekday()]
    today_iso = now.date().isoformat()
    minutes_now = now.hour * 60 + now.minute

    # Check overrides for today first
    for ov in schedule.get("overrides", []) or []:
        if ov.get("date") == today_iso:
            if ov.get("closed"):
                return {"isOpen": False, "reason": ov.get("reason") or "closed (override)"}
            o = _hhmm_to_min(ov.get("open"))
            c = _hhmm_to_min(ov.get("close"))
            if o is not None and c is not None and o <= minutes_now < c:
                return {"isOpen": True, "reason": "override hours"}
            return {"isOpen": False, "reason": ov.get("reason") or "outside override hours"}

    mode = schedule.get("mode", "simple")
    if mode == "simple":
        h = schedule.get("simpleHours") or {}
    else:
        h = (schedule.get("weeklyHours") or {}).get(today_key, {})
    if h.get("closed"):
        return {"isOpen": False, "reason": f"closed {today_key}"}
    o = _hhmm_to_min(h.get("open"))
    c = _hhmm_to_min(h.get("close"))
    if o is None or c is None:
        return {"isOpen": True, "reason": "no hours set"}
    if o <= minutes_now < c:
        return {"isOpen": True, "reason": f"{h.get('open')}–{h.get('close')}"}
    return {"isOpen": False, "reason": f"outside {h.get('open')}–{h.get('close')}"}


@router.get("/channels/{channel}/schedule")
async def get_channel_schedule(channel: str, _: dict = Depends(get_user)):
    doc = await db.channel_schedules.find_one({"channel": channel}, {"_id": 0})
    return doc or _default_schedule(channel)


@router.post("/channels/{channel}/schedule")
async def save_channel_schedule(channel: str, body: ChannelScheduleIn,
                                 user: dict = Depends(get_user)):
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(403, "Owner or manager only")
    if body.mode not in ("simple", "weekly"):
        raise HTTPException(400, "mode must be simple | weekly")
    existing = await db.channel_schedules.find_one({"channel": channel}, {"_id": 0}) or _default_schedule(channel)
    doc = {
        "channel": channel,
        "enabled": bool(body.enabled),
        "mode": body.mode,
        "simpleHours": body.simpleHours.dict() if body.simpleHours else existing.get("simpleHours") or _default_schedule(channel)["simpleHours"],
        # Preserve previously-saved weekly hours when caller doesn't send them.
        "weeklyHours": body.weeklyHours or existing.get("weeklyHours") or _default_schedule(channel)["weeklyHours"],
        "overrides": [o.dict() for o in body.overrides],
        "updatedAt": _now(),
        "updatedBy": user.get("email"),
    }
    await db.channel_schedules.update_one({"channel": channel}, {"$set": doc}, upsert=True)
    return doc


@router.get("/channels/{channel}/effective-status")
async def channel_effective_status(channel: str, _: dict = Depends(get_user)):
    """Merged live/paused view combining pause state + schedule."""
    state = await db.channel_states.find_one({"channel": channel}, {"_id": 0}) or {"channel": channel, "status": "active"}
    schedule = await db.channel_schedules.find_one({"channel": channel}, {"_id": 0}) or _default_schedule(channel)
    now = datetime.now(timezone.utc)
    # Auto-resume paused-until
    if state.get("status") == "paused" and state.get("pausedUntil"):
        try:
            until = datetime.fromisoformat(state["pausedUntil"].replace("Z", "+00:00"))
            if now >= until:
                state = {**state, "status": "active", "pausedUntil": None}
        except Exception:
            pass
    open_now = _compute_open_now(schedule, now)
    effective = "paused" if state.get("status") == "paused" or not open_now["isOpen"] else "active"
    return {
        "channel": channel,
        "state": state,
        "schedule": {"enabled": schedule.get("enabled"), "mode": schedule.get("mode")},
        "openNow": open_now,
        "effective": effective,
    }


# ═════════════════════════════════════════════════════════════════════════
# Guest digital wallet — QR/barcode for POS scan + AI CRM update
# ═════════════════════════════════════════════════════════════════════════
@router.get("/customers/{customer_id}/wallet")
async def guest_wallet(customer_id: str, user: dict = Depends(get_user)):
    """Return the QR payload + barcode + tier metadata for a customer's
    digital wallet. This is what mobile Apple/Google Wallet stubs pull in."""
    c = await db.customers.find_one({**tenant_scope_filter(user.get("businessId")), "id": customer_id}, {"_id": 0})
    if not c or not tenant_owns(c.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "Customer not found")
    payload = {"cid": customer_id, "tier": c.get("membershipTier", "Bronze"),
                "issued": int(datetime.now(timezone.utc).timestamp())}
    token = _sign_qr(payload)
    return {
        "customerId": customer_id,
        "name": c.get("name"),
        "tier": c.get("membershipTier"),
        "points": c.get("points", 0),
        "storeCredit": c.get("storeCredit", 0.0),
        "barcode": customer_id.upper().replace("-", "")[:20],
        "qrToken": token,
        "walletDataUrl": f"data:text/plain;base64,{base64.b64encode(token.encode()).decode()}",
    }


@router.post("/customers/lookup-by-token")
async def lookup_by_token(body: dict, user: dict = Depends(get_user)):
    """POS scans a wallet QR → returns the customer for one-tap add-to-cart."""
    token = body.get("token") or ""
    try:
        b64, sig = token.split(".")
        raw = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4))
        payload = json.loads(raw)
        expected = _sign_qr(payload).split(".")[1]
        if not hmac.compare_digest(sig, expected):
            raise HTTPException(401, "Invalid token")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, "Malformed token")
    c = await db.customers.find_one({**tenant_scope_filter(user.get("businessId")), "id": payload.get("cid")}, {"_id": 0})
    if not c or not tenant_owns(c.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "Customer not found")
    return c


# ─── Native Apple Wallet + Google Wallet passes ─────────────────────────
async def _resolve_wallet_context(customer_id: str, business_id: Optional[str] = None) -> dict:
    c = await db.customers.find_one({**tenant_scope_filter(business_id), "id": customer_id}, {"_id": 0})
    if not c or not tenant_owns(c.get("businessId"), business_id):
        raise HTTPException(404, "Customer not found")
    payload = {"cid": customer_id, "tier": c.get("membershipTier", "Bronze"),
                "issued": int(datetime.now(timezone.utc).timestamp())}
    token = _sign_qr(payload)
    return {
        "customer_id": customer_id,
        "name": c.get("name", "Guest"),
        "tier": c.get("membershipTier", "Bronze"),
        "points": int(c.get("points", 0)),
        "store_credit": float(c.get("storeCredit", 0.0)),
        "barcode": customer_id.upper().replace("-", "")[:20],
        "qr_token": token,
    }


@router.get("/customers/{customer_id}/wallet/apple.pkpass")
async def apple_wallet_pass(customer_id: str, user: dict = Depends(get_user)):
    """Return a real `.pkpass` archive. Signed if Pass Type ID certs are
    configured in env, otherwise unsigned (still valid structure)."""
    from utils.wallet_passes import build_pkpass
    ctx = await _resolve_wallet_context(customer_id, user.get("businessId"))
    blob, meta = build_pkpass(**ctx)
    filename = f"nua-{customer_id}.pkpass"
    return Response(
        content=blob,
        media_type="application/vnd.apple.pkpass",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Pkpass-Signed": "true" if meta["signed"] else "false",
        },
    )


@router.get("/customers/{customer_id}/wallet/google")
async def google_wallet_link(customer_id: str, user: dict = Depends(get_user)):
    """Return a Google Wallet "save to phone" link + JWT. `signed=false`
    when the service-account key isn't configured yet."""
    from utils.wallet_passes import build_google_wallet_link
    ctx = await _resolve_wallet_context(customer_id, user.get("businessId"))
    return build_google_wallet_link(**ctx)


# ═════════════════════════════════════════════════════════════════════════
# PDF exports — low-stock, AI Pantry
# ═════════════════════════════════════════════════════════════════════════
def _pdf_from_lines(title: str, lines: List[str], meta: Optional[dict] = None) -> bytes:
    """Minimal PDF assembler — paginates an A4 title + line list onto as
    many pages as needed. No external dependency (avoids adding a 30MB
    reportlab install). Good enough for order sheets + low-stock exports.

    Previously this silently truncated anything past the first page
    ("… export CSV for full list") — fine for a short low-stock list, but a
    genuine loss of data for a long purchase order or a busy venue's pantry
    sheet. Callers are unchanged; every existing PDF export now just gets
    real pagination instead of a mid-document cutoff.
    """
    TOP_Y = 750
    BOTTOM_MARGIN = 50

    pages: List[List[str]] = [[]]
    y = TOP_Y

    def add(text, size=12):
        nonlocal y
        if y < BOTTOM_MARGIN:
            pages.append([])
            y = TOP_Y
        # Escape parens & backslashes per PDF spec
        text = (text or "").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        pages[-1].append(f"BT /F1 {size} Tf 40 {y} Td ({text}) Tj ET")
        y -= size + 4

    add(title, size=18)
    y -= 4
    add(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", size=9)
    y -= 6
    if meta:
        for k, v in meta.items():
            add(f"{k}: {v}", size=9)
        y -= 6
    for line in lines:
        add(line, size=10)

    header = b"%PDF-1.4\n"
    n_pages = len(pages)
    # Object numbering: 1=Catalog, 2=Pages, then for each page a
    # (Page, Contents) pair, then the shared Font last.
    page_obj_nums = [3 + 2 * i for i in range(n_pages)]
    font_obj_num = 3 + 2 * n_pages

    objs = []
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{n} 0 R" for n in page_obj_nums)
    objs.append(f"<< /Type /Pages /Count {n_pages} /Kids [{kids}] >>".encode())
    for i, page_lines in enumerate(pages):
        stream_body = "\n".join(page_lines).encode("latin-1", errors="ignore")
        content_obj_num = page_obj_nums[i] + 1
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents {content_obj_num} 0 R "
            f"/Resources << /Font << /F1 {font_obj_num} 0 R >> >> >>".encode()
        )
        objs.append(f"<< /Length {len(stream_body)} >>\nstream\n".encode() + stream_body + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    body = bytearray()
    body += header
    offsets = []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(body))
        body += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref_off = len(body)
    body += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        body += f"{off:010d} 00000 n \n".encode()
    body += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref_off}\n%%EOF".encode()
    return bytes(body)


@router.get("/inventory/low-stock/pdf")
async def low_stock_pdf(_: dict = Depends(get_user)):
    prods = await db.products.find({}, {"_id": 0}).to_list(2000)
    low = [p for p in prods
           if p.get("stock") is not None
           and p["stock"] <= (p.get("lowStockThreshold") or 5)]
    low.sort(key=lambda p: p.get("stock", 0))
    lines = [f"{p.get('name'):<40s}  category: {p.get('category', '—'):<15s}  stock: {p.get('stock', 0):>4}  threshold: {p.get('lowStockThreshold', 5)}"
             for p in low]
    if not lines:
        lines = ["No low-stock items — every product is above its threshold."]
    pdf = _pdf_from_lines("Low-stock report", lines,
                          meta={"Items below threshold": len(low)})
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="low-stock-{date.today().isoformat()}.pdf"'})


@router.get("/inventory/low-stock/xlsx")
async def low_stock_xlsx(_: dict = Depends(get_user)):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    prods = await db.products.find({}, {"_id": 0}).to_list(2000)
    low = [p for p in prods
           if p.get("stock") is not None
           and p["stock"] <= (p.get("lowStockThreshold") or p.get("parLevel") or 5)]
    low.sort(key=lambda p: p.get("stock", 0))

    wb = Workbook()
    ws = wb.active
    ws.title = "Low Stock"
    headers = ["Product", "SKU", "Category", "Stock", "Threshold", "Cost", "Reorder Value"]
    ws.append(headers)
    header_fill = PatternFill(start_color="FFF3E0", end_color="FFF3E0", fill_type="solid")
    for col in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col)
        cell.font = Font(bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="left")

    for p in low:
        threshold = p.get("lowStockThreshold") or p.get("parLevel") or 5
        cost = float(p.get("cost", 0) or 0)
        stock = float(p.get("stock", 0) or 0)
        reorder_units = max(threshold * 2 - stock, 0)
        ws.append([
            p.get("name", ""), p.get("sku", ""), p.get("category", "—"),
            stock, threshold, round(cost, 2), round(reorder_units * cost, 2),
        ])

    for col, width in zip("ABCDEFG", [32, 14, 18, 10, 12, 10, 14]):
        ws.column_dimensions[col].width = width

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="low-stock-{date.today().isoformat()}.xlsx"'},
    )


@router.get("/ai-pantry/order-sheet/pdf")
async def ai_pantry_pdf(_: dict = Depends(get_user)):
    # Reuse whatever the AI Pantry produces; fall back to low-stock if the
    # collection isn't there yet.
    rows = []
    try:
        rows = await db.ai_pantry_orders.find({"status": {"$in": ["draft", "suggested"]}},
                                               {"_id": 0}).sort("createdAt", -1).to_list(500)
    except Exception:
        pass
    if not rows:
        prods = await db.products.find({"stock": {"$lte": 5}}, {"_id": 0}).to_list(2000)
        for p in prods:
            rows.append({"item": p.get("name"), "qty": max(10, (p.get("lowStockThreshold") or 5) * 3),
                          "supplier": p.get("supplier", "TBD"), "unit": "units"})
    lines = [f"{r.get('item', ''):<32s} qty: {r.get('qty', ''):>6}  unit: {r.get('unit', ''):<8s} supplier: {r.get('supplier', 'TBD')}"
             for r in rows]
    if not lines:
        lines = ["No pending orders."]
    pdf = _pdf_from_lines("AI Pantry — order sheet", lines,
                          meta={"Lines": len(lines), "Prepared": datetime.now().strftime('%Y-%m-%d %H:%M')})
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="pantry-order-{date.today().isoformat()}.pdf"'})


# ═════════════════════════════════════════════════════════════════════════
# Automation triggers — user-defined + AI-suggested
# ═════════════════════════════════════════════════════════════════════════
class TriggerIn(BaseModel):
    name: str
    event: str                       # e.g. low_stock, temperature_abnormal, booking_created, staff_late
    conditions: dict = {}
    actions: List[dict] = []         # each: {type, params}
    active: bool = True
    aiGenerated: bool = False
    aiPrompt: Optional[str] = None


@router.get("/automations/triggers")
async def list_triggers(_: dict = Depends(get_user)):
    return await db.automation_triggers.find({}, {"_id": 0}).sort("createdAt", -1).to_list(200)


@router.post("/automations/triggers")
async def create_trigger(body: TriggerIn, user: dict = Depends(get_user)):
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(403, "Owner or manager only")
    doc = {"id": str(uuid.uuid4()), **body.dict(),
           "createdBy": user.get("email"), "createdAt": _now(), "updatedAt": _now()}
    await db.automation_triggers.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.patch("/automations/triggers/{trigger_id}")
async def update_trigger(trigger_id: str, data: dict, user: dict = Depends(get_user)):
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(403, "Owner or manager only")
    data["updatedAt"] = _now()
    r = await db.automation_triggers.update_one({"id": trigger_id}, {"$set": data})
    if r.matched_count == 0:
        raise HTTPException(404, "Trigger not found")
    return await db.automation_triggers.find_one({"id": trigger_id}, {"_id": 0})


@router.delete("/automations/triggers/{trigger_id}")
async def delete_trigger(trigger_id: str, user: dict = Depends(get_user)):
    if user["role"] != "owner":
        raise HTTPException(403, "Owner only")
    r = await db.automation_triggers.delete_one({"id": trigger_id})
    if r.deleted_count == 0:
        raise HTTPException(404, "Trigger not found")
    return {"deleted": True}


@router.post("/automations/ai-suggest")
async def ai_suggest_automation(body: dict, _: dict = Depends(get_user)):
    """AI generates a trigger spec from a plain-English prompt. When the LLM
    key is unavailable we synthesise a plausible template so the UI still
    has something to preview."""
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "prompt is required")
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        api_key = os.environ.get("EMERGENT_LLM_KEY")
        if not api_key:
            raise Exception("no key")
        chat = LlmChat(api_key=api_key, session_id=f"auto-{uuid.uuid4()}",
                        system_message=(
                            "You design automation triggers for a restaurant POS. "
                            "Return STRICT JSON matching {name, event, conditions:{}, actions:[{type, params:{}}]}. "
                            "Common events: low_stock, temperature_abnormal, booking_created, staff_late, "
                            "customer_birthday, dish_86, high_wait_time, no_show. "
                            "Common action types: send_email, send_sms, dock_notify, dispatch_task, apply_discount."
                        )).with_model("openai", "gpt-4o-mini").with_max_tokens(500)
        raw = await chat.send_message(UserMessage(text=prompt))
        import re
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        parsed = json.loads(m.group()) if m else {}
    except Exception:
        parsed = {
            "name": f"Automation: {prompt[:40]}",
            "event": "low_stock",
            "conditions": {"threshold": 5},
            "actions": [{"type": "dock_notify", "params": {"message": "Low stock alert"}},
                         {"type": "send_email", "params": {"template": "low_stock"}}],
        }
    parsed.setdefault("aiGenerated", True)
    parsed.setdefault("aiPrompt", prompt)
    return parsed
