"""Remediation of the final readiness audit's finding: GET/DELETE
/api/customers/{id}/gdpr-export and gdpr-erase (routes/v15_features.py)
had two real problems.

1. No tenant check at all — any owner/manager of ANY business could
   export or erase another business's customer's full personal data by
   customer_id alone.
2. This session's own remediation work added several new guest-
   identifiable data stores (db.loyalty_ledger, db.voice_calls,
   db.bill_splits/db.split_tabs) with no path into the export/erase at
   all — a GDPR Article 15 access request would silently omit them, and
   an erasure request would leave a guest's phone number sitting in
   voice call records and bill-split claims untouched.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id, role="owner"):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "GDPR Test Owner", "email": email, "password": "GdprTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": role, "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "GdprTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _seed_customer(customer_id, *, business_id="default", phone="+61412340001"):
    _run(db.customers.insert_one({
        "id": customer_id, "name": "Privacy Test Guest", "phone": phone,
        "email": "guest@example.com", "businessId": business_id,
    }))


def _cleanup(*, customer_ids=(), phones=(), biz_ids=()):
    if customer_ids:
        _run(db.customers.delete_many({"id": {"$in": list(customer_ids)}}))
    if phones:
        _run(db.voice_calls.delete_many({"phone": {"$in": list(phones)}}))
        _run(db.voice_calls.delete_many({"phone": "[REDACTED]", "_seed_marker": {"$in": list(phones)}}))
        _run(db.bill_splits.delete_many({"tableNumber": {"$in": [f"GDPR-{p}" for p in phones]}}))
        _run(db.split_tabs.delete_many({"_seed_marker": {"$in": list(phones)}}))
        _run(db.loyalty_ledger.delete_many({"customerId": {"$in": list(customer_ids)}}))
    if biz_ids:
        _run(db.businesses.delete_many({"id": {"$in": list(biz_ids)}}))
        _run(db.auth_users.delete_many({"businessId": {"$in": list(biz_ids)}}))


def _seed_full_guest_footprint(customer_id, phone, business_id="default"):
    _run(db.loyalty_ledger.insert_one({
        "id": f"LP-GDPR-{customer_id}", "customerId": customer_id, "transactionId": "TXN-GDPR-1",
        "type": "earn", "points": 42, "businessId": business_id, "createdAt": "2026-01-01T00:00:00",
    }))
    _run(db.voice_calls.insert_one({
        "id": f"INB-GDPR-{customer_id}", "direction": "inbound", "phone": phone,
        "businessId": business_id, "transcript": [{"speaker": "guest", "text": "hi", "at": "now"}],
        "status": "completed", "_seed_marker": phone,
    }))
    split_id = f"SPLIT-GDPR-{customer_id}"
    _run(db.bill_splits.insert_one({
        "id": split_id, "tableNumber": f"GDPR-{phone}", "businessId": business_id,
        "status": "open", "mode": "items",
        "lines": [{"id": "L1", "productName": "Burger", "unitPrice": 15.0,
                   "status": "claimed", "claimedByPhone": phone}],
        "equalParts": [],
    }))
    _run(db.split_tabs.insert_one({
        "id": f"TAB-GDPR-{customer_id}", "splitId": split_id, "guestPhone": phone,
        "totalAmount": 15.0, "paidAmount": 0.0, "remainingBalance": 15.0,
        "status": "open", "_seed_marker": phone,
    }))


def test_gdpr_export_includes_this_sessions_new_guest_data_stores(client, owner_headers):
    cid, phone = "gdpr-cust-1", "+61412340011"
    _seed_customer(cid, phone=phone)
    _seed_full_guest_footprint(cid, phone)
    try:
        r = req(client, "GET", f"/api/customers/{cid}/gdpr-export", headers=owner_headers)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert len(body["loyaltyHistory"]) == 1
        assert body["loyaltyHistory"][0]["points"] == 42
        assert len(body["voiceCalls"]) == 1
        assert body["voiceCalls"][0]["phone"] == phone
        assert len(body["billSplitClaims"]) == 1
        assert body["billSplitClaims"][0]["lines"][0]["claimedByPhone"] == phone
        assert len(body["guestTabs"]) == 1
        assert body["guestTabs"][0]["guestPhone"] == phone
    finally:
        _cleanup(customer_ids=[cid], phones=[phone])


def test_gdpr_erase_redacts_phone_across_voice_calls_and_bill_splits(client, owner_headers):
    cid, phone = "gdpr-cust-2", "+61412340022"
    _seed_customer(cid, phone=phone)
    _seed_full_guest_footprint(cid, phone)
    try:
        r = req(client, "DELETE", f"/api/customers/{cid}/gdpr-erase", headers=owner_headers)
        assert r.status_code == 200, r.text[:300]

        call = _run(db.voice_calls.find_one({"id": f"INB-GDPR-{cid}"}, {"_id": 0}))
        assert call["phone"] == "[REDACTED]"

        split = _run(db.bill_splits.find_one({"id": f"SPLIT-GDPR-{cid}"}, {"_id": 0}))
        assert split["lines"][0]["claimedByPhone"] == "[REDACTED]"

        tab = _run(db.split_tabs.find_one({"id": f"TAB-GDPR-{cid}"}, {"_id": 0}))
        assert tab["guestPhone"] == "[REDACTED]"
    finally:
        _cleanup(customer_ids=[cid], phones=[phone])


def test_gdpr_export_rejects_a_customer_from_a_different_business(client, owner_headers):
    biz_b = "gdpr-biz-b"
    cid, phone = "gdpr-cust-3", "+61412340033"
    _run(db.businesses.insert_one({"id": biz_b, "slug": biz_b, "name": "GDPR Biz B", "status": "active"}))
    biz_b_headers = _login_as(client, owner_headers, email="gdpr-b-owner@nua.com", business_id=biz_b)
    _seed_customer(cid, business_id="default", phone=phone)
    try:
        r = req(client, "GET", f"/api/customers/{cid}/gdpr-export", headers=biz_b_headers)
        assert r.status_code == 404, (
            "a different business's owner must never be able to export this customer's personal data"
        )
        r = req(client, "GET", f"/api/customers/{cid}/gdpr-export", headers=owner_headers)
        assert r.status_code == 200
    finally:
        _cleanup(customer_ids=[cid], biz_ids=[biz_b])


def test_gdpr_erase_rejects_a_customer_from_a_different_business(client, owner_headers):
    biz_b = "gdpr-biz-b2"
    cid, phone = "gdpr-cust-4", "+61412340044"
    _run(db.businesses.insert_one({"id": biz_b, "slug": biz_b, "name": "GDPR Biz B2", "status": "active"}))
    biz_b_headers = _login_as(client, owner_headers, email="gdpr-b2-owner@nua.com", business_id=biz_b)
    _seed_customer(cid, business_id="default", phone=phone)
    try:
        r = req(client, "DELETE", f"/api/customers/{cid}/gdpr-erase", headers=biz_b_headers)
        assert r.status_code == 404, (
            "a different business's owner must never be able to erase this customer's personal data"
        )
        unchanged = _run(db.customers.find_one({"id": cid}, {"_id": 0}))
        assert unchanged["phone"] == phone, "a rejected cross-tenant erase must not touch the record at all"
    finally:
        _cleanup(customer_ids=[cid], phones=[phone], biz_ids=[biz_b])


def test_gdpr_export_never_leaks_another_businesss_tab_sharing_the_same_phone(client, owner_headers):
    """split_tabs itself carries no businessId — a phone-only match could
    otherwise pull in an unrelated business's guest tab data just because
    a guest happened to reuse the same phone number there."""
    biz_b = "gdpr-biz-b3"
    cid, phone = "gdpr-cust-5", "+61412340055"
    _run(db.businesses.insert_one({"id": biz_b, "slug": biz_b, "name": "GDPR Biz B3", "status": "active"}))
    _seed_customer(cid, business_id="default", phone=phone)
    other_split_id = f"SPLIT-OTHERBIZ-{cid}"
    _run(db.bill_splits.insert_one({
        "id": other_split_id, "tableNumber": "OTHERBIZ-TABLE", "businessId": biz_b,
        "status": "open", "mode": "items", "lines": [], "equalParts": [],
    }))
    _run(db.split_tabs.insert_one({
        "id": f"TAB-OTHERBIZ-{cid}", "splitId": other_split_id, "guestPhone": phone,
        "totalAmount": 99.0, "paidAmount": 0.0, "remainingBalance": 99.0, "status": "open",
    }))
    try:
        r = req(client, "GET", f"/api/customers/{cid}/gdpr-export", headers=owner_headers)
        assert r.status_code == 200, r.text[:300]
        tab_ids = [t["id"] for t in r.json()["guestTabs"]]
        assert f"TAB-OTHERBIZ-{cid}" not in tab_ids, (
            "another business's guest tab must never be exported just because it shares a phone number"
        )
    finally:
        _cleanup(customer_ids=[cid], biz_ids=[biz_b])
        _run(db.bill_splits.delete_one({"id": other_split_id}))
        _run(db.split_tabs.delete_many({"splitId": other_split_id}))
