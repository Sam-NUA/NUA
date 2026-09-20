"""routes/reservations.py's waitlist API (GET/POST /waitlist, PUT/seat/DELETE
/waitlist/{entry_id}) had zero auth and zero businessId scoping at all —
discovered while building Loyalty 3.0's Silver+ "Priority waitlist" perk
(the perk needed a real, tenant-scoped waitlist to enforce against). Any
unauthenticated caller could list, edit, seat or delete any business's
waitlist entries. Fixed by requiring get_user and scoping/owning every
entry by businessId, same pattern as every other Trust Release fix.

Also covers the new priority-queue behaviour: a customer whose current
loyalty tier includes the "Priority waitlist" perk (Silver+, see
routes/loyalty.py's seed tiers) jumps ahead of non-members who joined
earlier, but never ahead of an earlier-joined fellow priority guest — both
in staff's GET /waitlist ordering and in the guest-facing
/waitlist/track/{code} "ahead of you" count.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Waitlist Test Owner", "email": email, "password": "WaitlistTenant2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "WaitlistTenant2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def test_waitlist_requires_auth(client):
    # No Authorization header at all — every staff-facing waitlist endpoint
    # must reject this, not silently serve/mutate global data.
    assert req(client, "GET", "/api/waitlist").status_code in (401, 403)
    assert req(client, "POST", "/api/waitlist", json={"guestName": "X"}).status_code in (401, 403)
    assert req(client, "PUT", "/api/waitlist/WL-NOPE", json={}).status_code in (401, 403)
    assert req(client, "POST", "/api/waitlist/WL-NOPE/seat").status_code in (401, 403)
    assert req(client, "DELETE", "/api/waitlist/WL-NOPE").status_code in (401, 403)


def test_waitlist_is_scoped_and_owned_per_business(client, owner_headers):
    other = _login_as(client, owner_headers, email="waitlist.other@nua.com", business_id="waitlist-other-biz")
    try:
        created = req(client, "POST", "/api/waitlist", headers=other, json={
            "guestName": "Other Biz Guest", "partySize": 2,
        })
        assert created.status_code == 200, created.text[:200]
        entry_id = created.json()["id"]
        assert created.json()["businessId"] == "waitlist-other-biz"

        mine_list = req(client, "GET", "/api/waitlist", headers=owner_headers).json()
        assert not any(e["id"] == entry_id for e in mine_list)

        cross_update = req(client, "PUT", f"/api/waitlist/{entry_id}", headers=owner_headers,
                            json={"notes": "hacked"})
        assert cross_update.status_code == 404
        cross_seat = req(client, "POST", f"/api/waitlist/{entry_id}/seat", headers=owner_headers)
        assert cross_seat.status_code == 404
        cross_delete = req(client, "DELETE", f"/api/waitlist/{entry_id}", headers=owner_headers)
        assert cross_delete.status_code == 404

        own_list = req(client, "GET", "/api/waitlist", headers=other).json()
        assert any(e["id"] == entry_id for e in own_list)
    finally:
        _run(db.waitlist.delete_many({"businessId": "waitlist-other-biz"}))


def test_priority_waitlist_perk_orders_members_ahead(client, owner_headers):
    biz = "waitlist-priority-biz"
    staff = _login_as(client, owner_headers, email="waitlist.priority@nua.com", business_id=biz)
    import uuid
    member_phone = f"+61400{uuid.uuid4().int % 1000000:06d}"
    member = {
        "id": str(uuid.uuid4()), "name": "Silver Member", "email": f"{uuid.uuid4().hex[:8]}@test.com",
        "phone": member_phone, "points": 500, "visits": 0, "totalSpent": 0.0, "referrals": 0,
        "membershipTier": "Silver", "businessId": biz,
    }
    try:
        # routes/public.py's POST /public/join-waitlist is deliberately left
        # unscoped (no business signal in that guest-facing form — see
        # TENANT_ISOLATION_REMAINING_WORK.md), so other test files that hit
        # it (test_waitlist_tracking.py) leave untagged "waiting" entries
        # behind that tenant_scope_filter's safe default correctly still
        # surfaces to every business's "ahead of you" count — including
        # this fresh one. Clear them first so this test's own two entries
        # are the only "waiting" ones in scope for a deterministic count,
        # same pattern as test_loyalty_v2_tenant_isolation.py's untagged
        # badge/milestone cleanup.
        _run(db.waitlist.delete_many({"businessId": None, "status": "waiting"}))
        _run(db.customers.insert_one(dict(member)))
        # Ensure this business's tier catalog exists with the real perk list
        # (routes/loyalty.py seeds it lazily on first GET, same as loyalty_v2).
        req(client, "GET", "/api/loyalty/tiers", headers=staff)

        non_member = req(client, "POST", "/api/waitlist", headers=staff, json={
            "guestName": "Walk-in", "guestPhone": "+61499999999", "partySize": 2,
        })
        assert non_member.status_code == 200, non_member.text[:200]
        assert non_member.json()["priority"] is False

        member_entry = req(client, "POST", "/api/waitlist", headers=staff, json={
            "guestName": "Silver Member", "guestPhone": member_phone, "partySize": 2,
        })
        assert member_entry.status_code == 200, member_entry.text[:200]
        assert member_entry.json()["priority"] is True, "Silver+ tier must grant the Priority waitlist perk"

        # Member joined SECOND (higher position) but must be ordered FIRST.
        listing = req(client, "GET", "/api/waitlist", headers=staff).json()
        ids_in_order = [e["id"] for e in listing if e["businessId"] == biz]
        assert ids_in_order.index(member_entry.json()["id"]) < ids_in_order.index(non_member.json()["id"])

        # Guest-facing tracking must agree: the later-joined member sees 0
        # people ahead, the earlier-joined non-member now sees the member
        # ahead of them (1), not 0.
        member_track = req(client, "GET", f"/api/waitlist/track/{member_entry.json()['id']}").json()
        assert member_track["aheadOfYou"] == 0

        non_member_track = req(client, "GET", f"/api/waitlist/track/{non_member.json()['id']}").json()
        assert non_member_track["aheadOfYou"] == 1
    finally:
        _run(db.customers.delete_one({"id": member["id"]}))
        _run(db.waitlist.delete_many({"businessId": biz}))
