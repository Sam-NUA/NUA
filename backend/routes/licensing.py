"""NUA Enterprise Licensing & Entitlements System.

Implements:
- ABN-bound tenant licenses (one verified ABN per license, immutable post-issuance)
- Stripe Billing subscription enforcement (webhook-driven state machine)
- Device-level activation with short-lived signed JWT entitlement tokens
- Progressive lockout (warn → restrict → block) — never instant shutdown
- ABN change requests (owner + 2FA + ABR re-verification + grace period)
- Audit log of every state transition
"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Request, Header, Depends
from deps import get_user, require_owner, require_owner_or_manager
from database import db
from datetime import datetime, timezone, timedelta
from typing import Optional
import os
import uuid
import logging
import jwt
import stripe

from services.abr_service import lookup_abn, checksum_valid

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/license")

stripe.api_key = os.environ.get("STRIPE_API_KEY", "")

# --- Constants ----------------------------------------------------------------
ENTITLEMENT_TTL_MINUTES = 30
GRACE_PERIOD_DAYS = 7
RESTRICT_AFTER_DAYS = 2
BLOCK_AFTER_DAYS = 7

# License states
STATE_ACTIVE       = "active"
STATE_PAST_DUE     = "past_due"      # 1st failed payment, retrying
STATE_GRACE        = "grace"         # warnings + minor restrictions
STATE_SUSPENDED    = "suspended"     # block new sales
STATE_CANCELLED    = "cancelled"     # locked; allow renew/export only
STATE_ABN_REVIEW   = "abn_review"    # ABN change pending re-verification

# Error codes per spec
ERR_NO_LICENSE             = "NO_LICENSE"
ERR_DEVICE_NOT_AUTHORIZED  = "DEVICE_NOT_AUTHORIZED"
ERR_ABN_REVERIFY_REQUIRED  = "ABN_REVERIFY_REQUIRED"
ERR_SUBSCRIPTION_PAST_DUE  = "SUBSCRIPTION_PAST_DUE"
ERR_LICENSE_SUSPENDED      = "LICENSE_SUSPENDED"
ERR_LICENSE_CANCELLED      = "LICENSE_CANCELLED"


def _now(): return datetime.now(timezone.utc)
def _iso(dt): return dt.isoformat()
def _uid(prefix: str) -> str: return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def _sign_entitlement(tenant_id: str, device_id: str, state: str, expires_at: datetime) -> str:
    """Sign a short-lived entitlement token. POS devices cache this and revalidate periodically."""
    secret = os.environ["JWT_SECRET"]
    payload = {
        "tenantId": tenant_id, "deviceId": device_id, "state": state,
        "iat": int(_now().timestamp()), "exp": int(expires_at.timestamp()),
        "kind": "entitlement",
    }
    return jwt.encode(payload, secret, algorithm="HS256")


async def _audit(tenant_id: str, action: str, actor: str, details: dict | None = None):
    await db.license_audit.insert_one({
        "id": _uid("AUD"), "tenantId": tenant_id, "action": action,
        "actor": actor, "details": details or {}, "createdAt": _iso(_now()),
    })


async def _get_license(tenant_id: str) -> Optional[dict]:
    return await db.tenant_licenses.find_one({"tenantId": tenant_id}, {"_id": 0})


def _own_tenant_id(user: dict, data: Optional[dict] = None) -> str:
    """The tenantId for every licensing action is always the caller's own
    businessId — `user` carries no separate "tenantId" field (it never has;
    reading it was always None), and a client-supplied tenantId in the
    request body must never be trusted to pick which tenant's license gets
    onboarded, read, modified, or billed. A request-body tenantId is
    accepted only when it agrees with the caller's own business, for
    backward-compatible clients that still send it."""
    tenant_id = (user.get("businessId") or "default").strip()
    requested = ((data or {}).get("tenantId") or "").strip()
    if requested and requested != tenant_id:
        raise HTTPException(status_code=403, detail="tenantId must match your own business")
    return tenant_id


def _grace_end(failed_at_iso: str) -> str:
    failed = datetime.fromisoformat(failed_at_iso.replace("Z", "+00:00"))
    return _iso(failed + timedelta(days=GRACE_PERIOD_DAYS))


def _compute_state_from_days(failed_at_iso: str) -> str:
    """Map days-since-first-payment-failure to enforcement state (progressive)."""
    failed = datetime.fromisoformat(failed_at_iso.replace("Z", "+00:00"))
    days = (_now() - failed).days
    if days < RESTRICT_AFTER_DAYS:
        return STATE_PAST_DUE         # day 0-1: warn only
    if days < BLOCK_AFTER_DAYS:
        return STATE_GRACE            # day 2-6: restrict admin
    return STATE_SUSPENDED            # day 7+: block sales


# ============================================================================
# ONBOARDING — issue a new license (ABN + Stripe subscription required)
# ============================================================================
@router.post("/onboard")
async def onboard(data: dict, user: dict = Depends(require_owner)):
    """Create a tenant license bound to a verified ABN.

    Required: tenantId, abn, ownerEmail, plan (optional: stripeSubscriptionId).
    Calls ABR live; refuses to issue without a verified Active ABN.
    """

    tenant_id = _own_tenant_id(user, data)
    abn = (data.get("abn") or "").strip()
    plan = data.get("plan", "standard")
    max_devices = int(data.get("maxDevices", 3))

    existing = await _get_license(tenant_id)
    if existing:
        raise HTTPException(status_code=409, detail="License already exists for this tenant")

    if not checksum_valid(abn):
        raise HTTPException(status_code=422, detail="ABN failed local checksum")

    # Live ABR call (requires ABR_GUID). If a dev override is supplied AND the
    # environment explicitly opts in, we still demand a valid checksum but skip
    # the upstream network call. Production default is OFF — set ALLOW_ABR_DEV_SKIP=true
    # only on dev/staging.
    dev_skip = bool(data.get("devSkipAbr")) and os.environ.get("ALLOW_ABR_DEV_SKIP", "false").lower() == "true"
    if dev_skip:
        abr = {"abn": abn, "entityName": data.get("entityName", "DEMO ENTITY"),
               "gstRegistered": False, "raw": {"devSkipped": True}}
        logger.warning("ABR dev-skip used for tenant %s — production must remove this.", tenant_id)
    else:
        try:
            abr = await lookup_abn(abn)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except RuntimeError as e:
            msg = str(e)
            raise HTTPException(status_code=503 if "network" in msg.lower() or "HTTP" in msg else 500, detail=msg)

    lic = {
        "id": _uid("LIC"),
        "tenantId": tenant_id,
        "abn": abr["abn"],
        "abnVerified": True,
        "abnEntityName": abr["entityName"],
        "abnGstRegistered": abr["gstRegistered"],
        "abnVerifiedAt": _iso(_now()),
        "plan": plan,
        "state": STATE_ACTIVE,
        "ownerEmail": data.get("ownerEmail") or user.get("email"),
        "maxDevices": max_devices,
        "devices": [],
        "stripeCustomerId": data.get("stripeCustomerId"),
        "stripeSubscriptionId": data.get("stripeSubscriptionId"),
        "currentPeriodEnd": None,
        "lastValidationAt": _iso(_now()),
        "graceEndAt": None,
        "suspensionReason": None,
        "createdAt": _iso(_now()),
    }
    await db.tenant_licenses.insert_one(lic)
    lic.pop("_id", None)
    await _audit(tenant_id, "license.created", user["id"], {"abn": abr["abn"], "plan": plan})
    return lic


# ============================================================================
# RUNTIME — /api/license/validate — called by POS at startup + every N min
# ============================================================================
@router.post("/validate")
async def validate_license(data: dict, request: Request):
    """The POS device sends {tenantId, deviceId, appVersion, token?}.
    Server returns {ok, state, errorCode?, token?, grace?, message?}."""
    tenant_id = data.get("tenantId")
    device_id = data.get("deviceId")
    app_version = data.get("appVersion", "unknown")

    if not tenant_id or not device_id:
        raise HTTPException(status_code=400, detail="tenantId and deviceId required")

    lic = await _get_license(tenant_id)
    if not lic:
        return {"ok": False, "errorCode": ERR_NO_LICENSE, "message": "No license on file."}

    # Track last seen
    await db.tenant_licenses.update_one(
        {"tenantId": tenant_id},
        {"$set": {"lastValidationAt": _iso(_now()), "lastAppVersion": app_version}},
    )

    # 1) ABN review trumps everything
    if lic.get("state") == STATE_ABN_REVIEW:
        return {"ok": False, "errorCode": ERR_ABN_REVERIFY_REQUIRED,
                "state": STATE_ABN_REVIEW, "message": "ABN change pending re-verification."}

    # 2) Cancelled is hard
    if lic.get("state") == STATE_CANCELLED:
        return {"ok": False, "errorCode": ERR_LICENSE_CANCELLED, "state": STATE_CANCELLED,
                "message": "Subscription cancelled. Renew billing to restore."}

    # 3) Suspended blocks sales but allows owner billing recovery
    if lic.get("state") == STATE_SUSPENDED:
        return {"ok": False, "errorCode": ERR_LICENSE_SUSPENDED, "state": STATE_SUSPENDED,
                "message": lic.get("suspensionReason") or "Account suspended."}

    # 4) Device authorization (skip if no devices yet — first activation)
    if lic.get("devices") and device_id not in [d.get("deviceId") for d in lic["devices"]]:
        return {"ok": False, "errorCode": ERR_DEVICE_NOT_AUTHORIZED, "state": lic["state"],
                "message": "Device not in approved list. Owner must approve."}

    # 5) Past-due is allowed but warned
    if lic.get("state") in (STATE_PAST_DUE, STATE_GRACE):
        token_state = lic["state"]
    else:
        token_state = STATE_ACTIVE

    # Issue short-lived entitlement
    exp = _now() + timedelta(minutes=ENTITLEMENT_TTL_MINUTES)
    token = _sign_entitlement(tenant_id, device_id, token_state, exp)
    return {
        "ok": True, "state": token_state, "token": token,
        "expiresAt": _iso(exp), "ttlSeconds": ENTITLEMENT_TTL_MINUTES * 60,
        "graceEndAt": lic.get("graceEndAt"),
        "plan": lic.get("plan"), "abnEntityName": lic.get("abnEntityName"),
        "warnings": _build_warnings(lic),
    }


def _build_warnings(lic: dict) -> list[str]:
    out = []
    if lic.get("state") == STATE_PAST_DUE:
        out.append("Payment failed — please update billing to avoid restrictions.")
    if lic.get("state") == STATE_GRACE:
        out.append("Account in grace period. Settle the outstanding invoice to restore full access.")
    if lic.get("graceEndAt"):
        out.append(f"Grace period ends {lic['graceEndAt'][:10]}.")
    return out


# ============================================================================
# DEVICE ACTIVATION
# ============================================================================
@router.post("/device/activate")
async def activate_device(data: dict, user: dict = Depends(require_owner_or_manager)):
    """First-time device registration. The POS device generates a stable
    deviceId and submits it with an owner/manager auth header."""
    tenant_id = _own_tenant_id(user, data)
    device_id = data.get("deviceId")
    name = data.get("name", f"Device {device_id[:6] if device_id else '?'}")
    if not device_id:
        raise HTTPException(status_code=400, detail="deviceId required")

    lic = await _get_license(tenant_id)
    if not lic:
        raise HTTPException(status_code=404, detail="No license — onboard first")
    devices = lic.get("devices", [])
    if any(d.get("deviceId") == device_id for d in devices):
        return {"alreadyActive": True, "deviceId": device_id}
    if len(devices) >= lic.get("maxDevices", 3):
        raise HTTPException(status_code=403, detail=f"Device limit reached ({lic['maxDevices']})")
    new_dev = {"deviceId": device_id, "name": name, "activatedAt": _iso(_now()),
               "activatedBy": user["id"], "status": "active"}
    await db.tenant_licenses.update_one({"tenantId": tenant_id}, {"$push": {"devices": new_dev}})
    await _audit(tenant_id, "device.activated", user["id"], {"deviceId": device_id, "name": name})
    return {"activated": True, "device": new_dev}


@router.post("/device/revoke")
async def revoke_device(data: dict, user: dict = Depends(require_owner)):
    tenant_id = _own_tenant_id(user, data)
    device_id = data.get("deviceId")
    res = await db.tenant_licenses.update_one(
        {"tenantId": tenant_id},
        {"$pull": {"devices": {"deviceId": device_id}}},
    )
    if res.modified_count == 0:
        raise HTTPException(status_code=404, detail="Device not found")
    await _audit(tenant_id, "device.revoked", user["id"], {"deviceId": device_id})
    return {"revoked": True}


# ============================================================================
# ABN CHANGE REQUEST FLOW
# ============================================================================
@router.post("/abn/change-request")
async def request_abn_change(data: dict, user: dict = Depends(require_owner)):
    """Owner requests an ABN change. License goes into review state immediately.
    Requires owner role + 2FA token (we accept TOTP-style 6-digit OR a 'confirm'
    string for now — pyotp wiring is on the roadmap)."""
    twofa = (data.get("twoFactorCode") or "").strip()
    if not twofa or len(twofa) < 4:
        raise HTTPException(status_code=400, detail="2FA code required for ABN change")

    tenant_id = _own_tenant_id(user, data)
    new_abn = (data.get("newAbn") or "").strip()
    reason = data.get("reason", "")
    if not checksum_valid(new_abn):
        raise HTTPException(status_code=422, detail="New ABN failed checksum")

    lic = await _get_license(tenant_id)
    if not lic:
        raise HTTPException(status_code=404, detail="No license")

    # Live ABR check on the NEW abn
    try:
        abr = await lookup_abn(new_abn)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    req = {
        "id": _uid("ABNREQ"), "tenantId": tenant_id,
        "fromAbn": lic["abn"], "toAbn": abr["abn"], "newEntityName": abr["entityName"],
        "reason": reason, "status": "pending_approval",
        "requestedBy": user["id"], "requestedAt": _iso(_now()),
        "graceEndAt": _iso(_now() + timedelta(days=GRACE_PERIOD_DAYS)),
    }
    await db.abn_change_requests.insert_one(req)
    # Move tenant into review immediately — spec: "do not allow silent editing"
    await db.tenant_licenses.update_one(
        {"tenantId": tenant_id},
        {"$set": {"state": STATE_ABN_REVIEW, "pendingAbnRequestId": req["id"]}},
    )
    await _audit(tenant_id, "abn.change_requested", user["id"], {"from": lic["abn"], "to": abr["abn"]})
    req.pop("_id", None)
    return req


@router.post("/abn/approve/{req_id}")
async def approve_abn_change(req_id: str, request: Request, user: dict = Depends(require_owner)):
    """Per spec: 'do not allow to change ABN, once license is issued'.
    We retain the endpoint so support can override, but it is closed by default."""
    # Hard-gated: requires SUPPORT_OVERRIDE_KEY to be configured AND matched.
    # No hardcoded fallback — a default value here would be a documented,
    # source-visible backdoor around the "ABN cannot change" guarantee.
    # `not override_key` also covers the case where the env var is unset and
    # the header is unset too (both None): without that check, None == None
    # would pass the comparison and grant the override to anyone.
    override_key = os.environ.get("SUPPORT_OVERRIDE_KEY")
    override = request.headers.get("X-Support-Override")
    if not override_key or override != override_key:
        raise HTTPException(status_code=403, detail="ABN changes are not permitted once a license is issued. Contact support.")
    req = await db.abn_change_requests.find_one({"id": req_id}, {"_id": 0})
    if not req: raise HTTPException(status_code=404, detail="Request not found")
    await db.tenant_licenses.update_one(
        {"tenantId": req["tenantId"]},
        {"$set": {"abn": req["toAbn"], "abnEntityName": req["newEntityName"],
                  "abnVerifiedAt": _iso(_now()), "state": STATE_ACTIVE,
                  "pendingAbnRequestId": None}},
    )
    await db.abn_change_requests.update_one({"id": req_id},
        {"$set": {"status": "approved", "approvedBy": user["id"], "approvedAt": _iso(_now())}})
    await _audit(req["tenantId"], "abn.changed", user["id"], {"from": req["fromAbn"], "to": req["toAbn"]})
    return {"approved": True}


# ============================================================================
# BILLING / STRIPE WEBHOOKS
# ============================================================================
async def _move_state(tenant_id: str, new_state: str, reason: str = ""):
    update = {"state": new_state}
    if new_state == STATE_SUSPENDED:
        update["suspensionReason"] = reason
    await db.tenant_licenses.update_one({"tenantId": tenant_id}, {"$set": update})
    await _audit(tenant_id, f"state.{new_state}", "stripe_webhook", {"reason": reason})


@router.post("/stripe/webhook")
async def stripe_webhook(request: Request, stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature")):
    """Server-authoritative subscription state. Spec event types:
    invoice.paid, invoice.payment_failed, customer.subscription.updated, customer.subscription.deleted."""
    payload = await request.body()
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if not secret:
        # Fail closed. This endpoint is public/unauthenticated and drives
        # real tenant license/subscription state transitions (activation,
        # suspension) — accepting an unsigned payload here means anyone who
        # can reach this URL can flip any tenant's billing state. There is
        # no safe dev-fallback for a security-critical verification step;
        # if a deployment needs to exercise this path without real Stripe
        # webhooks, it must set STRIPE_WEBHOOK_SECRET to a test value and
        # sign requests with stripe.Webhook.generate_test_header, exactly
        # as tests/inprocess/test_licensing_webhook_signature.py does.
        logger.error("STRIPE_WEBHOOK_SECRET not set; rejecting webhook instead of skipping signature verification")
        raise HTTPException(status_code=503, detail="Webhook signature verification is not configured")
    try:
        # construct_event returns a stripe.Event — a StripeObject, not a
        # plain dict. It supports [] and attribute access but NOT .get(),
        # which raises AttributeError rather than falling back to a default
        # the way dict.get() does. Every call below uses .get() (an
        # intentional, defensive style for a webhook payload whose exact
        # shape isn't guaranteed) — so without this conversion, every
        # correctly-signed, real webhook delivery crashed with a 500
        # immediately on the first `event.get(...)`.
        event = stripe.Webhook.construct_event(payload, stripe_signature, secret).to_dict()
    except (ValueError, stripe.error.SignatureVerificationError) as e:
        raise HTTPException(status_code=400, detail=f"Webhook verification failed: {e}")

    et = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}
    cust_id = obj.get("customer")
    sub_id = obj.get("subscription") or obj.get("id")  # invoice.paid carries subscription, sub events carry id
    if not cust_id:
        return {"received": True, "ignored": "no customer"}
    lic = await db.tenant_licenses.find_one({"stripeCustomerId": cust_id}, {"_id": 0})
    if not lic:
        return {"received": True, "ignored": "no license linked"}
    # A Stripe customer can carry more than one Subscription object (a stray
    # duplicate, a test subscription, a plan-change that left the old one
    # lingering) — this license is tied to one specific stripeSubscriptionId
    # at creation time, so an event for a *different* subscription under the
    # same customer must not be allowed to flip this tenant's state. Only
    # enforced when both sides actually have a subscription id to compare —
    # invoice events on a not-yet-linked license, or a license created before
    # this field existed, fall through to the old any-event-for-this-customer
    # behavior rather than being silently ignored.
    linked_sub_id = lic.get("stripeSubscriptionId")
    if linked_sub_id and sub_id and sub_id != linked_sub_id:
        return {"received": True, "ignored": "event for a different subscription on this customer"}
    tenant_id = lic["tenantId"]

    if et == "invoice.paid":
        await db.tenant_licenses.update_one(
            {"tenantId": tenant_id},
            {"$set": {"state": STATE_ACTIVE, "suspensionReason": None, "graceEndAt": None,
                      "firstFailureAt": None,
                      "currentPeriodEnd": _iso(datetime.fromtimestamp(obj.get("period_end") or 0, tz=timezone.utc)) if obj.get("period_end") else None}},
        )
        await _audit(tenant_id, "billing.paid", "stripe_webhook", {"invoiceId": obj.get("id")})
    elif et == "invoice.payment_failed":
        # Mark first-failure timestamp if not set; compute progressive state
        existing = lic
        first_fail = existing.get("firstFailureAt") or _iso(_now())
        new_state = _compute_state_from_days(first_fail)
        await db.tenant_licenses.update_one(
            {"tenantId": tenant_id},
            {"$set": {"firstFailureAt": first_fail, "state": new_state,
                      "graceEndAt": _grace_end(first_fail),
                      "suspensionReason": "Payment failed" if new_state == STATE_SUSPENDED else None}},
        )
        await _audit(tenant_id, "billing.payment_failed", "stripe_webhook",
                     {"invoiceId": obj.get("id"), "newState": new_state})
    elif et == "customer.subscription.updated":
        # Subscription status can be: active, past_due, canceled, unpaid, trialing...
        ss = (obj.get("status") or "").lower()
        if ss == "active":
            await _move_state(tenant_id, STATE_ACTIVE, "")
            await db.tenant_licenses.update_one({"tenantId": tenant_id},
                {"$set": {"firstFailureAt": None, "graceEndAt": None}})
        elif ss == "past_due":
            existing = await _get_license(tenant_id)
            first_fail = (existing or {}).get("firstFailureAt") or _iso(_now())
            await db.tenant_licenses.update_one({"tenantId": tenant_id},
                {"$set": {"state": _compute_state_from_days(first_fail),
                          "firstFailureAt": first_fail, "graceEndAt": _grace_end(first_fail)}})
        elif ss in ("canceled", "unpaid"):
            await _move_state(tenant_id, STATE_CANCELLED if ss == "canceled" else STATE_SUSPENDED,
                              "Subscription " + ss)
    elif et == "customer.subscription.deleted":
        await _move_state(tenant_id, STATE_CANCELLED, "Subscription deleted")
    return {"received": True, "type": et}


# ============================================================================
# OWNER UI ENDPOINTS
# ============================================================================
@router.get("/me")
async def my_license(user: dict = Depends(get_user)):
    tenant_id = _own_tenant_id(user)
    lic = await _get_license(tenant_id)
    if not lic:
        return {"hasLicense": False, "tenantId": tenant_id}
    return {"hasLicense": True, **lic}


@router.get("/audit")
async def list_audit(user: dict = Depends(require_owner_or_manager)):
    tenant_id = _own_tenant_id(user)
    rows = await db.license_audit.find({"tenantId": tenant_id}, {"_id": 0}).sort("createdAt", -1).to_list(200)
    return rows


@router.post("/billing/recovery-link")
async def billing_recovery_link(data: dict, user: dict = Depends(require_owner)):
    """Generate a Stripe Billing Portal session URL so the owner can update their card."""
    tenant_id = _own_tenant_id(user, data)
    lic = await _get_license(tenant_id)
    if not lic or not lic.get("stripeCustomerId"):
        raise HTTPException(status_code=404, detail="No Stripe customer linked")
    return_url = data.get("returnUrl", "https://example.com/billing")
    try:
        sess = stripe.billing_portal.Session.create(customer=lic["stripeCustomerId"], return_url=return_url)
        return {"url": sess.url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stripe error: {e}")


# Dev-only manual state forcing — useful for QA / demos. Owner-gated.
@router.post("/dev/force-state")
async def force_state(data: dict, user: dict = Depends(require_owner)):
    tenant_id = _own_tenant_id(user, data)
    state = data.get("state")
    allowed = {STATE_ACTIVE, STATE_PAST_DUE, STATE_GRACE, STATE_SUSPENDED, STATE_CANCELLED, STATE_ABN_REVIEW}
    if state not in allowed:
        raise HTTPException(status_code=400, detail=f"Allowed states: {sorted(allowed)}")
    update = {"state": state}
    if state == STATE_SUSPENDED:
        update["suspensionReason"] = data.get("reason", "Manual force")
    if state == STATE_GRACE:
        update["firstFailureAt"] = _iso(_now() - timedelta(days=3))
        update["graceEndAt"] = _iso(_now() + timedelta(days=4))
    await db.tenant_licenses.update_one({"tenantId": tenant_id}, {"$set": update})
    await _audit(tenant_id, "state.forced", user["id"], {"state": state})
    return {"forced": state}
