from fastapi import APIRouter, Depends, HTTPException, Request, Response
from deps import get_user
from middleware.actor_context import tenant_scope_filter, get_actor_context, set_actor_context
from pydantic import BaseModel, EmailStr
from typing import Optional, Any, cast
from datetime import datetime, timezone, timedelta
from database import db
import bcrypt
import jwt
import logging
import os

router = APIRouter(prefix="/auth")
logger = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"
ROLES_HIERARCHY = {"owner": 4, "manager": 3, "cashier": 2, "kitchen": 1}

ROLE_PERMISSIONS = {
    "owner": ["*"],
    "manager": ["pos", "tables", "customers", "reservations", "kitchen", "floor-plan", "waitlist",
                "products", "inventory", "promotions", "analytics", "automation", "loyalty",
                "forecasting", "menu-engineering", "what-if", "pre-shift", "command-center",
                "integrations", "ai-pantry", "members", "feedback", "reports"],
    "cashier": ["pos", "tables", "customers", "reservations", "waitlist", "products"],
    "kitchen": ["kitchen", "pre-shift"],
}

async def effective_permissions(user: dict) -> list:
    """Return the effective permission list for a user:
      1. custom overrides if present on the user doc
      2. else DB-persisted role defaults (`db.role_permissions`)
      3. else code-level fallbacks in DEFAULT_ROLE_PERMISSIONS
    Owner is always ["*"]."""
    role = user.get("role")
    if role == "owner":
        return ["*"]
    custom = user.get("customPermissions") or []
    if custom:
        return custom
    from services.permission_catalog import DEFAULT_ROLE_PERMISSIONS
    doc = await db.role_permissions.find_one({"role": role}, {"_id": 0})
    if doc and isinstance(doc.get("permissions"), list):
        return doc["permissions"]
    return list(DEFAULT_ROLE_PERMISSIONS.get(role, ROLE_PERMISSIONS.get(role, [])))

def _secret():
    return os.environ["JWT_SECRET"]

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    # PIN-only staff are stored with an empty hash; bcrypt raises on malformed
    # hashes, which would turn a bad login into a 500.
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False

def create_access_token(user_id: str, email: str, role: str, business_id: str = None) -> str:
    # businessId travels in the token (not just a header) so ActorContextMiddleware
    # can stamp createdBy/businessId on every write without a DB round-trip per
    # request — see middleware/actor_context.py.
    payload = {"sub": user_id, "email": email, "role": role, "businessId": business_id,
               "exp": datetime.now(timezone.utc) + timedelta(hours=8), "type": "access"}
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)

def create_refresh_token(user_id: str) -> str:
    payload = {"sub": user_id, "exp": datetime.now(timezone.utc) + timedelta(days=7), "type": "refresh"}
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)

async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = await cast(Any, db.auth_users).find_one({"id": payload["sub"]})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        if user.get("status") != "active" or not user.get("businessId"):
            raise HTTPException(status_code=403, detail="Active business membership required")
        set_actor_context({**get_actor_context(), "businessId": user["businessId"],
                           "email": user.get("email"), "role": user.get("role")})
        user.pop("_id", None)
        user.pop("password_hash", None)
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

def require_role(*roles):
    async def checker(request: Request):
        user = await get_current_user(request)
        if user["role"] not in roles and user["role"] != "owner":
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return checker

# Set COOKIE_SECURE=true in any HTTPS deployment so auth cookies are never
# sent over plain HTTP. Defaults to false for local development.
def _cookie_secure() -> bool:
    return os.environ.get("COOKIE_SECURE", "false").lower() in ("1", "true", "yes")

def _set_tokens(response: Response, access: str, refresh: str):
    secure = _cookie_secure()
    response.set_cookie("access_token", access, httponly=True, secure=secure, samesite="lax", max_age=28800, path="/")
    response.set_cookie("refresh_token", refresh, httponly=True, secure=secure, samesite="lax", max_age=604800, path="/")

# Models
class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    # Terminals that were told to remember themselves send the trust token back
    # here. Native/kiosk clients can't rely on cookies, so it's accepted in the
    # body too — the cookie is checked either way.
    deviceToken: Optional[str] = None

class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: str = "cashier"
    businessId: Optional[str] = None
    payRate: Optional[float] = None

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    password: str

# --- Endpoints ---
@router.post("/login")
async def login(req: LoginRequest, request: Request, response: Response):
    email = req.email.lower()
    # Brute force check — keyed on the account alone (email), NOT on
    # request.client.host. This used to be f"{request.client.host}:{email}",
    # which looked stricter (per-IP-per-account) but was actually WEAKER:
    # this deployment runs uvicorn with --proxy-headers
    # --forwarded-allow-ips '*' (see Dockerfile/railway.json), so
    # request.client.host reflects a caller-supplied X-Forwarded-For
    # verbatim whenever the container is reachable without a header-
    # stripping proxy in front of it — confirmed by direct reproduction
    # against a real uvicorn instance with these exact flags. Concatenating
    # a spoofable value into the lockout key let an attacker mint a fresh
    # bucket every request by rotating the header, resetting the count to
    # zero each time regardless of the fixed target email. Keying on the
    # account alone closes that for THIS specific brute-force guard,
    # independent of whatever the real deployment's proxy trust turns out
    # to be — see TRUST_RELEASE_FINAL_REPORT.md's X-Forwarded-For section
    # for the parts of the rate-limiting surface this can't fix (anonymous
    # guest/public endpoints and forgot-password's deliberately IP-keyed
    # anti-enumeration throttle have no non-spoofable identity to key on
    # instead).
    identifier = f"acct:{email}"
    attempts = await db.login_attempts.find_one({"identifier": identifier})
    if attempts and attempts.get("count", 0) >= 5:
        locked_until = attempts.get("locked_until")
        # Mongo returns naive UTC datetimes; normalize before comparing
        if locked_until and locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        if locked_until and datetime.now(timezone.utc) < locked_until:
            raise HTTPException(status_code=429, detail="Account locked. Try again in 15 minutes.")
        else:
            await db.login_attempts.delete_one({"identifier": identifier})

    user = await db.auth_users.find_one({"email": email})
    if not user or not verify_password(req.password, user.get("password_hash", "")):
        await db.login_attempts.update_one(
            {"identifier": identifier},
            {"$inc": {"count": 1}, "$set": {"locked_until": datetime.now(timezone.utc) + timedelta(minutes=15)}},
            upsert=True
        )
        raise HTTPException(status_code=401, detail="Invalid email or password")

    await db.login_attempts.delete_one({"identifier": identifier})

    # ── Second factor ──────────────────────────────────────────────────────
    # The password was right; that is not the same as being logged in. If this
    # account carries a second factor, no access token is minted here — the
    # caller gets a short-lived challenge token that is only good for
    # /auth/2fa/challenge and nothing else.
    from services import two_factor
    if await two_factor.required_for(user):
        device_token = req.deviceToken or request.cookies.get("device_token")
        trusted = await two_factor.device_is_trusted(user, device_token, request)
        if not trusted:
            if not user.get("twoFactorEnabled"):
                # Venue policy says this role needs a second factor and this
                # person hasn't set one up. Let them in far enough to enrol and
                # no further, rather than locking them out of their own venue.
                setup = create_challenge_token(user["id"], purpose="enrol")
                return {"twoFactorRequired": True, "enrolmentRequired": True,
                        "challengeToken": setup,
                        "message": "This venue requires a second factor for your role — set it up to continue"}
            return {"twoFactorRequired": True,
                    "challengeToken": create_challenge_token(user["id"]),
                    "recoveryAvailable": await two_factor.recovery_codes_remaining(user["id"]) > 0,
                    "message": "Enter the 6-digit code from your authenticator app"}

    return await _complete_login(user, response)


def create_challenge_token(user_id: str, purpose: str = "2fa", expires_minutes: int = 5) -> str:
    """A token that proves an earlier step passed and buys nothing else.

    Deliberately not type "access": the auth middleware and get_current_user
    both refuse anything that isn't an access token, so this cannot be used to
    read a single row of data. Five minutes is long enough to find your phone
    for 2FA; password_reset uses a longer window (see forgot_password) since
    it has to survive an email round-trip instead of an already-open app.
    """
    payload = {"sub": user_id, "type": "challenge", "purpose": purpose,
               "exp": datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)}
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)


def read_challenge_token(token: str, purpose: str = "2fa") -> str:
    try:
        payload = jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="That took too long — sign in again")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid sign-in session")
    if payload.get("type") != "challenge" or payload.get("purpose") != purpose:
        raise HTTPException(status_code=401, detail="Invalid sign-in session")
    return payload["sub"]


async def _complete_login(user: dict, response: Response) -> dict:
    access = create_access_token(user["id"], user["email"], user["role"], user.get("businessId"))
    refresh = create_refresh_token(user["id"])
    _set_tokens(response, access, refresh)
    user = dict(user)
    user.pop("_id", None)
    user.pop("password_hash", None)
    user.pop("twoFactorSecret", None)
    user.pop("twoFactorSecretPending", None)
    user.pop("recoveryCodes", None)
    # Add effective permissions (custom > role DB override > code default)
    user["permissions"] = await effective_permissions(user)
    return {"user": user, "token": access}


class TwoFactorChallenge(BaseModel):
    challengeToken: str
    code: str
    trustDevice: bool = False


@router.post("/2fa/challenge")
async def two_factor_challenge(req: TwoFactorChallenge, request: Request, response: Response):
    """Second half of login: the code, and optionally remembering this terminal."""
    from services import two_factor
    user_id = read_challenge_token(req.challengeToken)

    # The challenge itself is brute-forceable — a million codes is not many if
    # you can try them all — so it gets the same lockout the password does.
    # Keyed on user_id alone, not request.client.host — see login()'s own
    # comment on why the IP component was removed (spoofable via
    # X-Forwarded-For under this deployment's uvicorn proxy-trust config).
    identifier = f"2fa:{user_id}"
    attempts = await db.login_attempts.find_one({"identifier": identifier})
    if attempts and attempts.get("count", 0) >= 5:
        locked_until = attempts.get("locked_until")
        if locked_until and locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        if locked_until and datetime.now(timezone.utc) < locked_until:
            raise HTTPException(status_code=429, detail="Too many attempts. Try again in 15 minutes.")
        await db.login_attempts.delete_one({"identifier": identifier})

    user = await db.auth_users.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid sign-in session")

    ok, how = await two_factor.verify(user, req.code)
    if not ok:
        await db.login_attempts.update_one(
            {"identifier": identifier},
            {"$inc": {"count": 1},
             "$set": {"locked_until": datetime.now(timezone.utc) + timedelta(minutes=15)}},
            upsert=True)
        detail = ("That code was already used — wait for the next one"
                  if how == "replayed" else "Incorrect code")
        raise HTTPException(status_code=401, detail=detail)

    await db.login_attempts.delete_one({"identifier": identifier})
    out = await _complete_login(user, response)
    out["verifiedBy"] = how
    if how == "recovery":
        out["recoveryCodesRemaining"] = await two_factor.recovery_codes_remaining(user_id)
    if req.trustDevice:
        token = await two_factor.trust_device(user, request)
        out["deviceToken"] = token
        response.set_cookie("device_token", token, httponly=True, secure=_cookie_secure(),
                            samesite="lax", max_age=two_factor.TRUSTED_DEVICE_DAYS * 86400,
                            path="/")
    return out

@router.post("/register")
async def register(req: RegisterRequest, response: Response, request: Request):
    # Existing deployments enroll staff through an authenticated owner. Public
    # registration may bootstrap the first owner, never join an arbitrary venue.
    owner_exists = await db.auth_users.find_one({"role": "owner"}, {"_id": 0, "id": 1})
    if owner_exists:
        actor = await get_current_user(request)
        if actor.get("role") != "owner":
            raise HTTPException(status_code=403, detail="Owner access only")
        if req.businessId and req.businessId != actor["businessId"]:
            raise HTTPException(status_code=403, detail="Cannot enroll staff in another business")
        req.businessId = actor["businessId"]
    else:
        req.businessId = "default"
        req.role = "owner"
    email = req.email.lower()
    existing = await db.auth_users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    # Public registration must not mint privileged accounts. "owner" is only
    # allowed on first-run setup (no owner exists yet); anything else that
    # isn't a known non-privileged role falls back to cashier.
    if req.role == "owner":
        owner_exists = await db.auth_users.find_one({"role": "owner"})
        if owner_exists:
            raise HTTPException(status_code=403, detail="An owner account already exists")
    elif req.role not in ("cashier", "kitchen"):
        req.role = "cashier"
    import uuid
    user_doc = {
        "id": str(uuid.uuid4()),
        "name": req.name, "email": email,
        "password_hash": hash_password(req.password),
        "role": req.role, "businessId": req.businessId or "default",
        "payRate": req.payRate or 0,
        "status": "active",
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    await db.auth_users.insert_one(user_doc)
    user_doc.pop("_id", None)
    user_doc.pop("password_hash", None)
    access = create_access_token(user_doc["id"], email, user_doc["role"], user_doc.get("businessId"))
    refresh = create_refresh_token(user_doc["id"])
    _set_tokens(response, access, refresh)
    return {"user": user_doc, "token": access}

@router.get("/me")
async def me(request: Request):
    user = await get_current_user(request)
    user["permissions"] = await effective_permissions(user)
    return user

@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return {"message": "Logged out"}

@router.post("/forgot-password")
async def forgot_password(req: ForgotPasswordRequest, request: Request):
    """Request a password-reset email. Always answers the same way whether
    or not the email matches an account — a different response would let
    anyone enumerate which emails have accounts on this deployment. Rate
    limited by IP (not by email — an attacker fishing for valid accounts
    would just rotate emails against one IP, not the other way around),
    same lockout shape as the login/2FA brute-force guards above.
    """
    identifier = f"forgot-password:{request.client.host}"
    attempts = await db.login_attempts.find_one({"identifier": identifier})
    if attempts and attempts.get("count", 0) >= 5:
        locked_until = attempts.get("locked_until")
        if locked_until and locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        if locked_until and datetime.now(timezone.utc) < locked_until:
            raise HTTPException(status_code=429, detail="Too many requests. Try again in 15 minutes.")
        await db.login_attempts.delete_one({"identifier": identifier})
    await db.login_attempts.update_one(
        {"identifier": identifier},
        {"$inc": {"count": 1}, "$set": {"locked_until": datetime.now(timezone.utc) + timedelta(minutes=15)}},
        upsert=True,
    )

    user = await db.auth_users.find_one({"email": req.email.lower()})
    if user:
        from utils.notifications import send_email
        token = create_challenge_token(user["id"], purpose="password_reset", expires_minutes=30)
        reset_url = f"{os.environ.get('FRONTEND_URL', '').rstrip('/')}/reset-password?token={token}"
        await send_email(
            user["email"], "Reset your NUA password",
            f"<p>Someone requested a password reset for your NUA account.</p>"
            f"<p><a href=\"{reset_url}\">Reset your password</a> — this link expires in 30 minutes.</p>"
            f"<p>If you didn't request this, you can ignore this email.</p>",
        )
    return {"message": "If that email has an account, a reset link has been sent."}

@router.post("/reset-password")
async def reset_password(req: ResetPasswordRequest):
    user_id = read_challenge_token(req.token, purpose="password_reset")
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    result = await db.auth_users.update_one(
        {"id": user_id}, {"$set": {"password_hash": hash_password(req.password)}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"message": "Password updated — sign in with your new password"}

@router.post("/refresh")
async def refresh_token(request: Request, response: Response):
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token")
    try:
        payload = jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token")
        user = await cast(Any, db.auth_users).find_one({"id": payload["sub"]})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        access = create_access_token(user["id"], user["email"], user["role"], user.get("businessId"))
        response.set_cookie("access_token", access, httponly=True, secure=_cookie_secure(), samesite="lax", max_age=28800, path="/")
        # The frontend authenticates every API call with a Bearer header read
        # from localStorage, not the httpOnly cookie above — this endpoint
        # used to only ever set the cookie, which nothing actually reads for
        # API calls, making it silently useless for the auth flow the app
        # really uses. Returning the new token lets a caller update
        # localStorage and keep working past the 8-hour access-token expiry
        # instead of every long-running session (an unattended kiosk, an
        # overnight shift) hitting 401s with no recovery but a full re-login.
        return {"message": "Token refreshed", "token": access}
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

# --- Staff Management (Owner only) ---
@router.get("/staff")
async def get_staff(request: Request):
    user = await get_current_user(request)
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(status_code=403, detail="Owner/Manager access only")
    staff = await db.auth_users.find(tenant_scope_filter(user.get("businessId")), {"_id": 0, "password_hash": 0}).to_list(1000)
    if user["role"] == "manager":
        for s in staff:
            s.pop("payRate", None)
    return staff

@router.put("/staff/{staff_id}")
async def update_staff(staff_id: str, data: dict, request: Request):
    user = await get_current_user(request)
    if user["role"] != "owner":
        raise HTTPException(status_code=403, detail="Owner access only")
    allowed = {"name", "role", "status", "payRate", "salaryType", "pin"}
    update_data = {k: v for k, v in data.items() if k in allowed}
    result = await db.auth_users.find_one_and_update(
        {"id": staff_id, **tenant_scope_filter(user.get("businessId"))}, {"$set": update_data}, return_document=True
    )
    if not result:
        raise HTTPException(status_code=404, detail="Staff not found")
    result.pop("_id", None)
    result.pop("password_hash", None)
    return result

@router.post("/staff/add")
async def add_staff_simple(data: dict, request: Request):
    """Add staff without requiring email/password - PIN only"""
    user = await get_current_user(request)
    if user["role"] != "owner":
        raise HTTPException(status_code=403, detail="Owner access only")
    import uuid
    name = data.get("name", "")
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    staff_id = str(uuid.uuid4())
    email = data.get("email", "").lower().strip()
    password = data.get("password", "")
    user_doc = {
        "id": staff_id, "name": name,
        "email": email or f"staff-{staff_id[:8]}@nua.local",
        "role": data.get("role", "cashier"),
        "payRate": float(data.get("payRate", 0)),
        "salaryType": data.get("salaryType", "hourly"),
        "pin": data.get("pin", ""),
        "status": "active", "businessId": user["businessId"],
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    if password:
        user_doc["password_hash"] = hash_password(password)
    else:
        user_doc["password_hash"] = ""
    await db.auth_users.insert_one(user_doc)
    user_doc.pop("_id", None)
    user_doc.pop("password_hash", None)
    return user_doc

# Custom roles management
@router.get("/roles")
async def get_custom_roles(user: dict = Depends(get_user)):
    from services.tenant_settings import get_setting
    defaults = ["cashier", "kitchen", "manager", "barista", "bar", "floor", "host", "dishwasher"]
    value = await get_setting("custom_roles", user.get("businessId"))
    return value if value is not None else defaults

@router.post("/roles")
async def save_custom_roles(data: dict, request: Request):
    user = await get_current_user(request)
    if user["role"] != "owner":
        raise HTTPException(status_code=403, detail="Owner access only")
    from services.tenant_settings import set_setting
    roles = data.get("roles", [])
    await set_setting("custom_roles", roles, user.get("businessId"))
    return {"message": f"{len(roles)} roles saved", "roles": roles}

@router.delete("/staff/{staff_id}")
async def delete_staff(staff_id: str, request: Request):
    user = await get_current_user(request)
    if user["role"] != "owner":
        raise HTTPException(status_code=403, detail="Owner access only")
    if staff_id == user["id"]:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    await db.auth_users.delete_one({"id": staff_id})
    return {"message": "Staff deleted"}

# --- Owner-Only Reports ---
@router.get("/reports/labor-cost")
async def get_labor_cost_report(request: Request):
    from utils.au_payroll import effective_hourly_rate, STANDARD_WEEKLY_HOURS
    user = await get_current_user(request)
    if user["role"] != "owner":
        raise HTTPException(status_code=403, detail="Owner access only")
    staff = await db.auth_users.find({"role": {"$ne": "owner"}}, {"_id": 0}).to_list(1000)
    txns = await db.transactions.find({}, {"_id": 0}).to_list(10000)
    total_revenue = sum(t.get("total", 0) for t in txns)
    expenses = await db.expenses.find({}, {"_id": 0}).to_list(10000)
    total_expenses = sum(e.get("amount", 0) for e in expenses)
    total_cogs = sum(e.get("amount", 0) for e in expenses if e.get("category") in ("Ingredients", "Food Supplies", "Beverages"))
    # payRate is stored in whatever unit salaryType names — convert to an
    # hourly-equivalent before the *38 standard-week estimate, or a flat
    # hourly rate (like a casual on $30/hr) gets treated as if it were an
    # annual salary of $30/year and vice versa.
    rates = {s["id"]: effective_hourly_rate(s.get("payRate", 0), s.get("salaryType")) for s in staff}
    roster_cost = sum(rates[s["id"]] * STANDARD_WEEKLY_HOURS for s in staff)
    return {
        "staff": [{"name": s["name"], "role": s["role"], "payRate": s.get("payRate", 0),
                   "salaryType": s.get("salaryType", "hourly"),
                   "weeklyEstimate": round(rates[s["id"]] * STANDARD_WEEKLY_HOURS, 2)} for s in staff],
        "totalRosterCost": round(roster_cost, 2),
        "totalRevenue": round(total_revenue, 2),
        "cogs": round(total_cogs, 2),
        "otherExpenses": round(total_expenses - total_cogs, 2),
        "grossProfit": round(total_revenue - total_cogs, 2),
        "netProfit": round(total_revenue - total_cogs - (total_expenses - total_cogs) - roster_cost, 2),
        "laborPct": round((roster_cost / max(total_revenue, 1)) * 100, 1),
        "cogsPct": round((total_cogs / max(total_revenue, 1)) * 100, 1),
    }

# --- Seeding ---
async def seed_admin():
    email = os.environ.get("ADMIN_EMAIL", "owner@nua.com")
    password = os.environ.get("ADMIN_PASSWORD")
    await db.auth_users.create_index("email", unique=True)
    if not password:
        # No hardcoded fallback here on purpose: a default password baked into
        # source means every fresh deployment that forgets to set one ships a
        # public, guessable owner login. Skip seeding entirely instead — an
        # operator sets ADMIN_PASSWORD (and optionally ADMIN_EMAIL) to
        # bootstrap the first owner account. Local dev/test tooling
        # (tests/inprocess/conftest.py, run_demo_backend.py) sets an
        # explicit test-only ADMIN_PASSWORD so this never blocks them.
        logger.warning(
            "ADMIN_PASSWORD not set — skipping owner/demo-staff account seed. "
            "Set ADMIN_PASSWORD (and optionally ADMIN_EMAIL) to bootstrap the owner account."
        )
        return
    existing = await db.auth_users.find_one({"email": email})
    if not existing:
        import uuid
        await db.auth_users.insert_one({
            "id": str(uuid.uuid4()), "name": "Owner", "email": email,
            "password_hash": hash_password(password),
            "role": "owner", "businessId": "default", "payRate": 0,
            "status": "active", "createdAt": datetime.now(timezone.utc).isoformat(),
        })
    elif not verify_password(password, existing.get("password_hash", "")):
        await db.auth_users.update_one({"email": email}, {"$set": {"password_hash": hash_password(password)}})
    # Seed demo staff — reuses ADMIN_PASSWORD unless DEMO_STAFF_PASSWORD is set
    # separately, so a single env var still bootstraps a working demo/staging
    # environment without a hardcoded literal in source.
    demo_password = os.environ.get("DEMO_STAFF_PASSWORD", password)
    demo_staff = [
        {"name": "Sarah Manager", "email": "manager@nua.com", "role": "manager", "payRate": 35},
        {"name": "Tom Cashier", "email": "cashier@nua.com", "role": "cashier", "payRate": 25},
        {"name": "Chef Kim", "email": "kitchen@nua.com", "role": "kitchen", "payRate": 30},
    ]
    for s in demo_staff:
        exists = await db.auth_users.find_one({"email": s["email"]})
        if not exists:
            import uuid
            await db.auth_users.insert_one({
                "id": str(uuid.uuid4()), "name": s["name"], "email": s["email"],
                "password_hash": hash_password(demo_password),
                "role": s["role"], "businessId": "default", "payRate": s["payRate"],
                "status": "active", "createdAt": datetime.now(timezone.utc).isoformat(),
            })
        elif exists.get("role") != s["role"]:
            # Heal seed data — ensure demo accounts always have their canonical role
            await db.auth_users.update_one(
                {"email": s["email"]},
                {"$set": {"role": s["role"], "name": s["name"]}}
            )
