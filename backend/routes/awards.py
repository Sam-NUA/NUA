"""
Award + Superannuation engine.
Stores award catalogues (Fair Work Australia + multi-country) and computes
super contributions from existing payruns.

The seed catalogue ships with the app. The /awards/sync-fairwork endpoint
attempts to fetch the latest published rates from fairwork.gov.au's open
data feed; if the network or feed is unavailable, it falls back to the seed
+ flags a stale-data warning so the UI can prompt the user.
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel
from database import db
from deps import get_user, require_owner_or_manager
from middleware.actor_context import tenant_scope_filter, tenant_owns_strict
import uuid
import os

try:
    import httpx
except ImportError:  # pragma: no cover — httpx is in requirements
    httpx = None

router = APIRouter()

# --- Models ----------------------------------------------------------------
class AwardClassification(BaseModel):
    level: str                  # e.g. "Level 1", "Introductory"
    description: str = ""
    baseHourly: float           # adult full-time hourly rate
    casualHourly: Optional[float] = None
    saturdayLoading: float = 0.0   # %
    sundayLoading: float = 0.0
    publicHolidayLoading: float = 0.0
    overtime150: float = 50.0
    overtime200: float = 100.0

class Award(BaseModel):
    id: str
    code: str                    # e.g. "MA000119"
    name: str
    country: str = "AU"
    regulator: str = "Fair Work Australia"
    industry: str = ""
    superRate: float = 11.5      # % of OTE (FY25/26 default; ramps to 12% in FY26)
    classifications: List[AwardClassification] = []
    notes: str = ""
    sourceUrl: str = ""
    installed: bool = False
    installedAt: Optional[str] = None

# --- Seed catalogue --------------------------------------------------------
# Numbers below are illustrative round figures; a production system would pull
# the exact published rate from each regulator. Hourly rates are AUD (adult FT)
# / NZD for NZ / GBP for UK etc.
SEED_AWARDS: list[dict] = [
    {
        "code": "MA000119", "name": "Restaurant Industry Award", "country": "AU",
        "industry": "Restaurants", "superRate": 11.5,
        "sourceUrl": "https://www.fairwork.gov.au/employment-conditions/awards/awards-summary/ma000119-summary",
        "classifications": [
            {"level": "Introductory", "baseHourly": 23.23, "casualHourly": 29.04, "saturdayLoading": 25, "sundayLoading": 50, "publicHolidayLoading": 225},
            {"level": "Level 1 (Food & Beverage)", "baseHourly": 24.10, "casualHourly": 30.13, "saturdayLoading": 25, "sundayLoading": 50, "publicHolidayLoading": 225},
            {"level": "Level 2 (Cook/Server)", "baseHourly": 24.95, "casualHourly": 31.19, "saturdayLoading": 25, "sundayLoading": 50, "publicHolidayLoading": 225},
            {"level": "Level 3 (Senior Cook/Bartender)", "baseHourly": 25.81, "casualHourly": 32.26, "saturdayLoading": 25, "sundayLoading": 50, "publicHolidayLoading": 225},
            {"level": "Level 4 (Tradesperson Cook)", "baseHourly": 27.21, "casualHourly": 34.01, "saturdayLoading": 25, "sundayLoading": 50, "publicHolidayLoading": 225},
            {"level": "Level 5 (Senior Tradesperson)", "baseHourly": 28.83, "casualHourly": 36.04, "saturdayLoading": 25, "sundayLoading": 50, "publicHolidayLoading": 225},
            {"level": "Level 6 (Supervisor)", "baseHourly": 29.59, "casualHourly": 36.99, "saturdayLoading": 25, "sundayLoading": 50, "publicHolidayLoading": 225},
        ],
    },
    {
        "code": "MA000009", "name": "Hospitality Industry General Award", "country": "AU",
        "industry": "Hotels, Pubs, Clubs", "superRate": 11.5,
        "sourceUrl": "https://www.fairwork.gov.au/employment-conditions/awards/awards-summary/ma000009-summary",
        "classifications": [
            {"level": "Level 1", "baseHourly": 23.23, "casualHourly": 29.04, "saturdayLoading": 25, "sundayLoading": 50, "publicHolidayLoading": 225},
            {"level": "Level 2", "baseHourly": 24.10, "casualHourly": 30.13, "saturdayLoading": 25, "sundayLoading": 50, "publicHolidayLoading": 225},
            {"level": "Level 3", "baseHourly": 24.95, "casualHourly": 31.19, "saturdayLoading": 25, "sundayLoading": 50, "publicHolidayLoading": 225},
            {"level": "Level 4", "baseHourly": 26.10, "casualHourly": 32.63, "saturdayLoading": 25, "sundayLoading": 50, "publicHolidayLoading": 225},
            {"level": "Level 5", "baseHourly": 27.21, "casualHourly": 34.01, "saturdayLoading": 25, "sundayLoading": 50, "publicHolidayLoading": 225},
            {"level": "Level 6", "baseHourly": 28.83, "casualHourly": 36.04, "saturdayLoading": 25, "sundayLoading": 50, "publicHolidayLoading": 225},
        ],
    },
    {
        "code": "MA000003", "name": "Fast Food Industry Award", "country": "AU",
        "industry": "QSR & Cafes", "superRate": 11.5,
        "sourceUrl": "https://www.fairwork.gov.au/employment-conditions/awards/awards-summary/ma000003-summary",
        "classifications": [
            {"level": "Level 1", "baseHourly": 23.23, "casualHourly": 29.04, "saturdayLoading": 25, "sundayLoading": 50, "publicHolidayLoading": 225},
            {"level": "Level 2", "baseHourly": 24.10, "casualHourly": 30.13, "saturdayLoading": 25, "sundayLoading": 50, "publicHolidayLoading": 225},
            {"level": "Level 3 (Manager)", "baseHourly": 27.50, "casualHourly": 34.38, "saturdayLoading": 25, "sundayLoading": 50, "publicHolidayLoading": 225},
        ],
    },
    {
        "code": "MA000004", "name": "General Retail Industry Award", "country": "AU",
        "industry": "Retail", "superRate": 11.5,
        "sourceUrl": "https://www.fairwork.gov.au/employment-conditions/awards/awards-summary/ma000004-summary",
        "classifications": [
            {"level": "Level 1", "baseHourly": 23.85, "casualHourly": 29.81, "saturdayLoading": 25, "sundayLoading": 100, "publicHolidayLoading": 225},
            {"level": "Level 2", "baseHourly": 24.30, "casualHourly": 30.38, "saturdayLoading": 25, "sundayLoading": 100, "publicHolidayLoading": 225},
            {"level": "Level 3", "baseHourly": 24.65, "casualHourly": 30.81, "saturdayLoading": 25, "sundayLoading": 100, "publicHolidayLoading": 225},
        ],
    },
    {
        "code": "UK-NMW", "name": "UK National Minimum Wage", "country": "UK",
        "regulator": "HMRC", "industry": "All", "superRate": 3.0,
        "sourceUrl": "https://www.gov.uk/national-minimum-wage-rates",
        "classifications": [
            {"level": "Age 21+", "baseHourly": 11.44, "casualHourly": 11.44, "saturdayLoading": 0, "sundayLoading": 0, "publicHolidayLoading": 100},
            {"level": "Age 18-20", "baseHourly": 8.60, "casualHourly": 8.60, "saturdayLoading": 0, "sundayLoading": 0, "publicHolidayLoading": 100},
        ],
    },
    {
        "code": "NZ-MW", "name": "NZ Minimum Wage (Adult)", "country": "NZ",
        "regulator": "MBIE NZ", "industry": "All", "superRate": 3.0,
        "sourceUrl": "https://www.employment.govt.nz/hours-and-wages/pay/minimum-wage/",
        "classifications": [
            {"level": "Adult", "baseHourly": 23.15, "casualHourly": 23.15, "saturdayLoading": 0, "sundayLoading": 0, "publicHolidayLoading": 50},
        ],
    },
    {
        "code": "US-FED-MW", "name": "US Federal Minimum Wage", "country": "US",
        "regulator": "Department of Labor", "industry": "All", "superRate": 0.0,
        "sourceUrl": "https://www.dol.gov/agencies/whd/minimum-wage",
        "classifications": [
            {"level": "Tipped Server", "baseHourly": 2.13, "casualHourly": 2.13, "saturdayLoading": 0, "sundayLoading": 0, "publicHolidayLoading": 0},
            {"level": "Non-tipped", "baseHourly": 7.25, "casualHourly": 7.25, "saturdayLoading": 0, "sundayLoading": 0, "publicHolidayLoading": 0},
        ],
    },
]

# --- Endpoints -------------------------------------------------------------
@router.get("/awards/catalogue")
async def awards_catalogue(country: Optional[str] = None, user: dict = Depends(get_user)):
    """List the seed awards (available to install)."""
    out = []
    installed = {a["code"]: a async for a in db.awards.find(tenant_scope_filter(user.get("businessId")), {"_id": 0})}
    for s in SEED_AWARDS:
        if country and s["country"] != country:
            continue
        i = installed.get(s["code"])
        out.append({
            **s,
            "installed": bool(i),
            "installedAt": i.get("installedAt") if i else None,
            "id": (i or {}).get("id", ""),
        })
    return out

@router.post("/awards/install")
async def install_award(body: dict, user: dict = Depends(require_owner_or_manager)):
    """Install an award by code from the seed catalogue."""
    code = body.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="code is required")
    seed = next((s for s in SEED_AWARDS if s["code"] == code), None)
    if not seed:
        raise HTTPException(status_code=404, detail="Award not in catalogue")
    biz = user.get("businessId")
    doc = {
        "id": str(uuid.uuid4()),
        "code": seed["code"],
        "name": seed["name"],
        "country": seed.get("country", "AU"),
        "regulator": seed.get("regulator", "Fair Work Australia"),
        "industry": seed.get("industry", ""),
        "superRate": seed.get("superRate", 11.5),
        "classifications": seed.get("classifications", []),
        "sourceUrl": seed.get("sourceUrl", ""),
        "installedAt": datetime.now(timezone.utc).isoformat(),
        "businessId": biz,
    }
    # Keyed by (code, businessId), not code alone — an award like
    # "MA000119" is a shared national identifier, but "installed" is a
    # per-business choice. Two businesses installing the same award used
    # to collide on one shared document, so business A uninstalling it
    # silently uninstalled it for business B too, and business A could see
    # (and delete) business B's installed-awards list wholesale.
    await db.awards.update_one({"code": doc["code"], "businessId": biz}, {"$set": doc}, upsert=True)
    return doc

@router.get("/awards/installed")
async def list_installed_awards(user: dict = Depends(get_user)):
    rows = await db.awards.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}).to_list(200)
    return rows

@router.delete("/awards/{code}")
async def uninstall_award(code: str, user: dict = Depends(require_owner_or_manager)):
    """The old inline `$or businessId/None/$exists` filter was the same
    fail-open shape as tenant_owns() applied to a DELETE — awards are only
    ever written by install_award above, which always stamps a real
    businessId (no guest/anonymous path creates one), so an untagged award
    row can only be genuine pre-fix legacy data, not currently-active data
    from some other business — safe to quarantine with an exact match
    rather than delete on a fail-open guess."""
    biz = user.get("businessId")
    existing = await db.awards.find_one({"$and": [{"code": code}, tenant_scope_filter(biz)]}, {"_id": 0, "businessId": 1})
    if not existing or not tenant_owns_strict(existing.get("businessId"), biz):
        raise HTTPException(status_code=404, detail="Not installed")
    res = await db.awards.delete_one({"$and": [{"code": code}, tenant_scope_filter(biz)]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not installed")
    return {"deleted": True}


# --- Fair Work / regulator sync -------------------------------------------
FAIRWORK_FEED = os.environ.get("FAIRWORK_AWARDS_FEED", "https://api.fwc.gov.au/v1/awards")

@router.post("/awards/sync-fairwork")
async def sync_fairwork(user: dict = Depends(require_owner_or_manager)):
    """Best-effort sync against the Fair Work Modern Awards feed.

    Returns the merged catalogue and a `stale: bool` flag — when stale is
    True the response was served from the seed (network or feed unavailable).
    """
    if httpx is None:
        return {"stale": True, "reason": "httpx not installed", "count": len(SEED_AWARDS), "awards": SEED_AWARDS}

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(FAIRWORK_FEED)
            resp.raise_for_status()
            data = resp.json()
        # Caller can adapt — we only consume `awards` list of {code, name, classifications, superRate, ...}
        live = data.get("awards") if isinstance(data, dict) else data
        if not isinstance(live, list) or not live:
            return {"stale": True, "reason": "Feed returned no awards", "count": len(SEED_AWARDS), "awards": SEED_AWARDS}
        # Persist a cache entry for resilience
        now_iso = datetime.now(timezone.utc).isoformat()
        await db.award_cache.update_one(
            {"_id": "fairwork-latest"},
            {"$set": {"fetchedAt": now_iso, "awards": live}},
            upsert=True,
        )
        return {"stale": False, "fetchedAt": now_iso, "count": len(live), "awards": live}
    except Exception as e:
        # Try the cached snapshot first
        cached = await db.award_cache.find_one({"_id": "fairwork-latest"})
        if cached and cached.get("awards"):
            return {"stale": True, "reason": f"Live feed unreachable ({type(e).__name__}); served from cache", "fetchedAt": cached.get("fetchedAt"), "count": len(cached["awards"]), "awards": cached["awards"]}
        return {"stale": True, "reason": f"Live feed unreachable ({type(e).__name__}); served from seed", "count": len(SEED_AWARDS), "awards": SEED_AWARDS}

# --- Super calc from payruns ----------------------------------------------
@router.post("/payruns/super-by-award")
async def super_by_award(body: dict, user: dict = Depends(require_owner_or_manager)):
    """Compute super contributions for each staff member in a payrun using
    the installed Award's superRate.

    Body: { period: "week" | "fortnight" | "month", awardCode: str (optional)
            payrun: { staffPayroll: [{name, role, grossPay, awardCode?, classification?}, ...] } }

    If `awardCode` is supplied at the top level it applies to everyone unless
    the row has its own awardCode. Falls back to 11.5% if no award installed.
    """
    awardCode = body.get("awardCode")
    staff = (body.get("payrun") or {}).get("staffPayroll", [])
    if not isinstance(staff, list):
        raise HTTPException(status_code=400, detail="payrun.staffPayroll must be a list")

    # Pull installed awards into a {code: doc} map — scoped to this
    # business, since superRate is a compliance-sensitive figure that must
    # come from THIS business's own installed award, never another
    # tenant's (whose install/uninstall choices this business never made).
    installed = {a["code"]: a async for a in db.awards.find(tenant_scope_filter(user.get("businessId")), {"_id": 0})}

    out = []
    total = 0.0
    unresolved: set[str] = set()
    for row in staff:
        gross = float(row.get("grossPay", 0) or 0)
        code = row.get("awardCode") or awardCode
        rate = 11.5
        award_name = None
        if code:
            doc = installed.get(code)
            if doc:
                rate = float(doc.get("superRate", 11.5))
                award_name = doc.get("name")
            else:
                # Referenced but not installed — surface to UI so it can prompt
                unresolved.add(code)
        contribution = round(gross * (rate / 100.0), 2)
        out.append({
            **row,
            "awardCode": code,
            "awardName": award_name,
            "superRate": rate,
            "superContribution": contribution,
        })
        total += contribution

    return {
        "totalSuper": round(total, 2),
        "staffSuper": out,
        "unresolvedAwards": sorted(unresolved),
        "computedAt": datetime.now(timezone.utc).isoformat(),
    }
