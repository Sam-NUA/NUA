"""Platform-operator surface: partner provisioning and usage reports.
Guarded by the deploy-time admin key — partners never see these routes."""
from datetime import datetime, timezone
import secrets

from fastapi import APIRouter, Depends, HTTPException

from auth import generate_key, hash_key, require_platform_admin
from database import db
from models import Partner, PartnerCreate, PartnerApplicationCreate
from usage import monthly_report

router = APIRouter(prefix="/admin", dependencies=[Depends(require_platform_admin)])


def _provision_partner(body: PartnerCreate) -> tuple[dict, str, str]:
    """Shared by direct admin creation and application approval — exactly
    one place mints keys, so the two paths can never drift apart."""
    live_key = generate_key(test=False)
    test_key = generate_key(test=True)
    partner = Partner(
        **body.dict(),
        api_key_hash=hash_key(live_key),
        test_key_hash=hash_key(test_key),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    doc = partner.dict()
    doc["webhook_secret"] = secrets.token_urlsafe(32)
    return doc, live_key, test_key


@router.post("/partners")
async def create_partner(body: PartnerCreate):
    """Provision a partner. The raw live + sandbox keys are returned ONCE,
    here — only their hashes are stored."""
    partner_doc, live_key, test_key = _provision_partner(body)
    await db.partners.insert_one(partner_doc)
    out = dict(partner_doc)
    out.pop("_id", None)
    out.pop("api_key_hash"); out.pop("test_key_hash")
    out["api_key"] = live_key
    out["test_api_key"] = test_key
    return out


@router.get("/partners")
async def list_partners():
    rows = await db.partners.find({}, {"_id": 0, "api_key_hash": 0, "test_key_hash": 0, "webhook_secret": 0}).to_list(500)
    return rows


@router.post("/partners/{partner_id}/rotate-key")
async def rotate_key(partner_id: str, test: bool = False):
    partner = await db.partners.find_one({"id": partner_id}, {"_id": 0})
    if not partner:
        raise HTTPException(status_code=404, detail="Partner not found")
    new_key = generate_key(test=test)
    field = "test_key_hash" if test else "api_key_hash"
    await db.partners.update_one({"id": partner_id}, {"$set": {field: hash_key(new_key)}})
    return {"partner_id": partner_id, "test": test, "api_key": new_key}


@router.get("/usage/monthly")
async def usage_monthly(month: str):
    """month=YYYY-MM — the wholesale invoicing feed."""
    return {"month": month, "partners": await monthly_report(month)}


# ---- Partner application review queue ----
@router.get("/partner-applications")
async def list_applications(status: str = ""):
    q = {"status": status} if status else {}
    return await db.partner_applications.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)


@router.post("/partner-applications/{application_id}/approve")
async def approve_application(application_id: str, billing_tier: str = "standard"):
    application = await db.partner_applications.find_one({"id": application_id}, {"_id": 0})
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    if application["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Application already {application['status']}")

    partner_doc, live_key, test_key = _provision_partner(
        PartnerCreate(name=application["company_name"], billing_tier=billing_tier))
    await db.partners.insert_one(partner_doc)
    await db.partner_applications.update_one(
        {"id": application_id},
        {"$set": {"status": "approved", "partner_id": partner_doc["id"],
                  "resolved_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {
        "applicationId": application_id, "partnerId": partner_doc["id"],
        "name": partner_doc["name"], "api_key": live_key, "test_api_key": test_key,
    }


@router.post("/partner-applications/{application_id}/reject")
async def reject_application(application_id: str, reason: str = ""):
    application = await db.partner_applications.find_one({"id": application_id}, {"_id": 0})
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    if application["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Application already {application['status']}")

    await db.partner_applications.update_one(
        {"id": application_id},
        {"$set": {"status": "rejected", "rejection_reason": reason or None,
                  "resolved_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"applicationId": application_id, "status": "rejected"}


@router.post("/partners/{partner_id}/rotate-webhook-secret")
async def rotate_webhook_secret(partner_id: str):
    secret = secrets.token_urlsafe(32)
    result = await db.partners.update_one({"id": partner_id}, {"$set": {"webhook_secret": secret}})
    if not result.matched_count:
        raise HTTPException(404, "Partner not found")
    return {"partner_id": partner_id, "webhook_secret": secret}


@router.get('/webhook-deliveries')
async def webhook_deliveries(partner_id: str, status: str = 'failed'):
    if status not in ('pending', 'retrying', 'delivering', 'failed', 'delivered', 'skipped_no_url'):
        raise HTTPException(422, 'Invalid delivery status')
    return await db.webhook_outbox.find(
        {'partner_id': partner_id, 'status': status},
        {'_id': 0, 'id': 1, 'event': 1, 'status': 1, 'attempts': 1,
         'created_at': 1, 'last_error': 1}).sort('created_at', -1).to_list(100)


@router.post('/webhook-deliveries/{event_id}/retry')
async def retry_webhook(event_id: str):
    now = datetime.now(timezone.utc).isoformat()
    result = await db.webhook_outbox.update_one({'id': event_id, 'status': 'failed'}, {
        '$set': {'status': 'pending', 'attempts': 0, 'next_attempt_at': now, 'last_retried_at': now},
        '$inc': {'operator_retries': 1}, '$unset': {'claim_token': '', 'lease_until': ''}})
    if result.matched_count != 1:
        raise HTTPException(404, 'Failed delivery not found')
    return {'id': event_id, 'status': 'pending'}
