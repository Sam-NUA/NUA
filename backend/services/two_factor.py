"""Second factor for the accounts that can move money.

What was here before was a stub that accepted the literal string "123456" and
was never consulted at login, so a venue could switch 2FA "on" in Settings and
be protected by nothing at all. That is worse than having no feature — it buys
false confidence. This is the real thing.

Three deliberate choices, all shaped by the fact that this runs on a restaurant
floor rather than in an office:

  * **Recovery codes are mandatory, not optional.** The owner's phone will end
    up in a bag behind the bar, or dead, or replaced. Being locked out of your
    own till during service is a worse outcome than most attacks, so there is
    always a printed way back in — single-use, hashed at rest.

  * **Trusted devices.** Asking for a code on every login would mean the floor
    tablet prompts at every shift change, and the staff response to that is to
    write the seed on a sticky note. So a device can be remembered, and the
    trust is a signed token bound to that user, revocable per device and
    expiring on its own.

  * **Used codes are burned.** A TOTP stays valid for its whole window, so a
    code shoulder-surfed off the owner's phone could otherwise be replayed by
    someone standing at the next terminal. Each accepted code is recorded for
    the length of its window and refused the second time.
"""
import hashlib
import hmac
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

import jwt
import pyotp

from database import db

log = logging.getLogger(__name__)

ISSUER = "NUA POS"

# A TOTP is valid for its own 30s step plus one either side, which covers a
# till tablet whose clock has drifted a little. Wider than that and a code
# glimpsed across the pass stays usable for too long.
VALID_WINDOW = 1
STEP_SECONDS = 30

RECOVERY_CODE_COUNT = 10
TRUSTED_DEVICE_DAYS = 30

# Which roles must carry a second factor once the venue turns enforcement on.
# Kitchen and cashier logins happen constantly on shared hardware and can't
# reach the money screens anyway, so forcing a code on them buys nothing.
ENFORCED_ROLES = ("owner", "manager")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _secret() -> str:
    return os.environ["JWT_SECRET"]


# ── Enrolment ──────────────────────────────────────────────────────────────

def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, email: str) -> str:
    """The otpauth:// URI an authenticator app scans."""
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=ISSUER)


def _hash_recovery(code: str) -> str:
    """Recovery codes are credentials, so they are stored the way credentials
    are. Plain SHA-256 rather than bcrypt is deliberate: these are 40 bits of
    fresh randomness, not a human-chosen password, so there is nothing for a
    slow hash to defend against and login stays fast."""
    return hashlib.sha256(code.encode()).hexdigest()


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> Tuple[List[str], List[dict]]:
    """Return (plaintext to show the owner once, hashed rows to store)."""
    plain = []
    for _ in range(count):
        raw = secrets.token_hex(5).upper()          # 10 hex chars, ~40 bits
        plain.append(f"{raw[:5]}-{raw[5:]}")
    stored = [{"hash": _hash_recovery(c), "usedAt": None} for c in plain]
    return plain, stored


async def begin_enrolment(user: dict) -> dict:
    """Mint a secret and hand back what the setup screen needs.

    Nothing is enforced yet — the secret sits unconfirmed until the user proves
    they can read a code off it, so a half-finished setup can never lock anyone
    out of their own venue.
    """
    secret = new_secret()
    await db.auth_users.update_one(
        {"id": user["id"]},
        {"$set": {"twoFactorSecretPending": secret,
                  "twoFactorPendingAt": _now().isoformat()}},
    )
    return {"secret": secret,
            "otpauthUri": provisioning_uri(secret, user.get("email", "user")),
            "issuer": ISSUER}


async def confirm_enrolment(user: dict, code: str) -> dict:
    """Turn a pending secret into a live one, once a real code proves it works."""
    fresh = await db.auth_users.find_one({"id": user["id"]})
    pending = (fresh or {}).get("twoFactorSecretPending")
    if not pending:
        raise ValueError("Start setup again — there's no pending code to confirm")
    if not pyotp.TOTP(pending).verify(_clean(code), valid_window=VALID_WINDOW):
        raise ValueError("That code didn't match. Check your phone's clock and try again")

    plain, stored = generate_recovery_codes()
    await db.auth_users.update_one(
        {"id": user["id"]},
        {"$set": {"twoFactorSecret": pending,
                  "twoFactorEnabled": True,
                  "twoFactorEnabledAt": _now().isoformat(),
                  "recoveryCodes": stored},
         "$unset": {"twoFactorSecretPending": "", "twoFactorPendingAt": ""}},
    )
    await _record_used(user["id"], _clean(code))
    log.info("2fa enabled for user %s", user["id"])
    # The plaintext codes are returned exactly once and never stored, so this
    # is the only moment they can be shown or printed.
    return {"enabled": True, "recoveryCodes": plain}


async def disable(user_id: str) -> None:
    await db.auth_users.update_one(
        {"id": user_id},
        {"$unset": {"twoFactorSecret": "", "twoFactorEnabled": "",
                    "twoFactorSecretPending": "", "recoveryCodes": "",
                    "twoFactorEnabledAt": ""}},
    )
    await db.trusted_devices.delete_many({"userId": user_id})
    log.info("2fa disabled for user %s", user_id)


async def regenerate_recovery_codes(user_id: str) -> List[str]:
    plain, stored = generate_recovery_codes()
    await db.auth_users.update_one({"id": user_id}, {"$set": {"recoveryCodes": stored}})
    return plain


# ── Verification ───────────────────────────────────────────────────────────

def _clean(code: str) -> str:
    return "".join(ch for ch in (code or "") if ch.isalnum()).upper()


async def _record_used(user_id: str, code: str) -> None:
    """Burn a code for the length of its validity window."""
    await db.totp_used.insert_one({
        "userId": user_id,
        "code": hashlib.sha256(code.encode()).hexdigest(),
        "at": _now(),
        "expiresAt": _now() + timedelta(seconds=STEP_SECONDS * (VALID_WINDOW * 2 + 2)),
    })


async def _already_used(user_id: str, code: str) -> bool:
    row = await db.totp_used.find_one({
        "userId": user_id, "code": hashlib.sha256(code.encode()).hexdigest()})
    if not row:
        return False
    # The TTL index does the real cleanup; this guards the window in case the
    # index hasn't been built yet on a fresh database.
    exp = row.get("expiresAt")
    if exp and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return not exp or exp > _now()


async def verify(user: dict, code: str) -> Tuple[bool, str]:
    """Check a TOTP or a recovery code. Returns (ok, how)."""
    code = _clean(code)
    if not code:
        return False, "empty"
    secret = user.get("twoFactorSecret")
    if not secret:
        return False, "not-enrolled"

    if len(code) == 6 and code.isdigit():
        if await _already_used(user["id"], code):
            return False, "replayed"
        if pyotp.TOTP(secret).verify(code, valid_window=VALID_WINDOW):
            await _record_used(user["id"], code)
            return True, "totp"
        return False, "bad-code"

    # Otherwise treat it as a recovery code — single use, burned on success.
    wanted = _hash_recovery(code if "-" in code else f"{code[:5]}-{code[5:]}")
    fresh = await db.auth_users.find_one({"id": user["id"]}, {"recoveryCodes": 1})
    for i, row in enumerate((fresh or {}).get("recoveryCodes") or []):
        if row.get("usedAt") is None and hmac.compare_digest(row.get("hash", ""), wanted):
            await db.auth_users.update_one(
                {"id": user["id"]},
                {"$set": {f"recoveryCodes.{i}.usedAt": _now().isoformat()}},
            )
            log.warning("2fa recovery code used for %s", user["id"])
            return True, "recovery"
    return False, "bad-code"


async def recovery_codes_remaining(user_id: str) -> int:
    fresh = await db.auth_users.find_one({"id": user_id}, {"recoveryCodes": 1})
    return len([r for r in ((fresh or {}).get("recoveryCodes") or []) if not r.get("usedAt")])


# ── Trusted devices ────────────────────────────────────────────────────────

def _device_fingerprint(request) -> str:
    """A weak hint, not an identity — the trust lives in the signed token.

    This exists only so a stolen token can't be replayed from a completely
    different browser, and so the owner sees something recognisable in the
    device list.
    """
    ua = request.headers.get("user-agent", "")
    return hashlib.sha256(ua.encode()).hexdigest()[:16]


def _device_label(request) -> str:
    ua = request.headers.get("user-agent", "")
    for needle, label in (("iPad", "iPad"), ("iPhone", "iPhone"), ("Android", "Android"),
                          ("Macintosh", "Mac"), ("Windows", "Windows"), ("Linux", "Linux")):
        if needle in ua:
            return label
    return "Unknown device"


async def trust_device(user: dict, request) -> str:
    """Mint a device-trust token so this terminal can skip the code next time."""
    device_id = secrets.token_urlsafe(16)
    expires = _now() + timedelta(days=TRUSTED_DEVICE_DAYS)
    await db.trusted_devices.insert_one({
        "id": device_id,
        "userId": user["id"],
        "fingerprint": _device_fingerprint(request),
        "label": _device_label(request),
        "createdAt": _now().isoformat(),
        "lastSeenAt": _now().isoformat(),
        "expiresAt": expires,
    })
    return jwt.encode({"sub": user["id"], "device": device_id, "type": "device",
                       "exp": expires}, _secret(), algorithm="HS256")


async def device_is_trusted(user: dict, token: Optional[str], request) -> bool:
    if not token:
        return False
    try:
        payload = jwt.decode(token, _secret(), algorithms=["HS256"])
    except Exception:
        return False
    if payload.get("type") != "device" or payload.get("sub") != user["id"]:
        return False
    row = await db.trusted_devices.find_one({"id": payload.get("device"),
                                             "userId": user["id"]})
    if not row:
        return False   # revoked
    if row.get("fingerprint") != _device_fingerprint(request):
        # Same token, different browser — treat it as stolen rather than moved.
        log.warning("device-trust token for %s presented from a different agent", user["id"])
        return False
    await db.trusted_devices.update_one(
        {"id": row["id"]}, {"$set": {"lastSeenAt": _now().isoformat()}})
    return True


async def list_devices(user_id: str) -> List[dict]:
    rows = await db.trusted_devices.find({"userId": user_id}, {"_id": 0}).to_list(50)
    for r in rows:
        exp = r.get("expiresAt")
        r["expiresAt"] = exp.isoformat() if hasattr(exp, "isoformat") else exp
    return rows


async def revoke_device(user_id: str, device_id: str) -> bool:
    r = await db.trusted_devices.delete_one({"id": device_id, "userId": user_id})
    return r.deleted_count > 0


# ── Policy ─────────────────────────────────────────────────────────────────

async def policy(business_id: Optional[str] = None) -> dict:
    """Defaults business_id from the request's actor context (same
    pattern as notification_service.send()) so existing callers don't
    need editing — this used to be one 2FA-enforcement policy shared by
    every business on the deployment; see services/tenant_settings.py."""
    from services.tenant_settings import get_setting
    value = await get_setting("two_factor_policy", business_id) or {}
    return {"required": bool(value.get("required", False)),
            "roles": value.get("roles") or list(ENFORCED_ROLES)}


async def set_policy(required: bool, roles: Optional[List[str]] = None, business_id: Optional[str] = None) -> dict:
    from services.tenant_settings import set_setting
    value = {"required": bool(required), "roles": roles or list(ENFORCED_ROLES)}
    await set_setting("two_factor_policy", value, business_id)
    return value


async def required_for(user: dict) -> bool:
    """Does this user have to pass a second factor to finish logging in?

    Yes if they have enrolled — someone who set it up expects it to be asked
    for. Also yes if the venue has turned enforcement on for their role, which
    is what makes them enrol in the first place.
    """
    if user.get("twoFactorEnabled"):
        return True
    p = await policy(user.get("businessId"))
    return p["required"] and user.get("role") in p["roles"]


async def ensure_indexes() -> None:
    try:
        await db.totp_used.create_index("expiresAt", expireAfterSeconds=0)
        await db.totp_used.create_index([("userId", 1), ("code", 1)])
        await db.trusted_devices.create_index("expiresAt", expireAfterSeconds=0)
        await db.trusted_devices.create_index("userId")
    except Exception as e:      # mongomock and older servers don't do TTL
        log.info("2fa indexes not created: %s", e)
