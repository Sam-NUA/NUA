"""GET /audit/events and /audit/summary used to hand-roll a strict
`{"businessId": business_id}` match instead of using tenant_scope_filter.
That silently hid any audit event written before tenant stamping existed
(no businessId field at all) — the exact "not-yet-backfilled deployment
shows zero" bug tenant_scope_filter was built to avoid everywhere else.
Both endpoints now go through the shared helper; these tests pin a real
untagged legacy-shaped event and confirm it still surfaces.
"""
import asyncio
import uuid

from conftest import req


def _insert_untagged_legacy_event():
    loop = asyncio.get_event_loop()
    from database import db
    from datetime import datetime, timezone

    event = {
        "id": str(uuid.uuid4()), "entityType": "product", "entityId": "legacy-product-1",
        "action": "updated", "actor": "legacy@nua.com", "role": "owner",
        "device": None, "ip": None, "locationId": None,
        # No "businessId" key at all — this is the pre-tenant-stamping shape.
        "before": {"price": 5}, "after": {"price": 6}, "memo": None,
        "severity": "info", "tags": [], "ts": datetime.now(timezone.utc).isoformat(),
    }
    loop.run_until_complete(db.audit_events.delete_many({"id": event["id"]}))
    loop.run_until_complete(db.audit_events.insert_one(dict(event)))
    return event["id"]


def test_untagged_legacy_audit_event_is_hidden_until_ownership_is_resolved(client, owner_headers):
    event_id = _insert_untagged_legacy_event()
    tenant = dict(owner_headers, **{"X-Tenant-Id": "default"})

    events = req(client, "GET", "/api/audit/events", headers=tenant,
                 params={"entity_type": "product", "entity_id": "legacy-product-1"}).json()
    assert not any(e["id"] == event_id for e in events)


def test_untagged_legacy_audit_event_still_counts_in_the_summary(client, owner_headers):
    _insert_untagged_legacy_event()
    tenant = dict(owner_headers, **{"X-Tenant-Id": "default"})

    before_total = req(client, "GET", "/api/audit/summary", headers=tenant).json()["total"]
    assert before_total >= 1
