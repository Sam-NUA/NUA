"""Guests joining the public waitlist (POST /public/join-waitlist) got back a
position and an estimated wait, but never a way to check status again later
— the response didn't include the entry's own id, so there was nothing to
track with. This adds that id to the join response and the guest-facing
GET /waitlist/track/{code} it unlocks, with position recomputed live against
whoever is still actually waiting (not the stale value stamped at join time).
"""
from conftest import req


def test_joining_the_waitlist_returns_a_trackable_id(client):
    r = req(client, "POST", "/api/public/join-waitlist", json={
        "guestName": "Track Test Guest", "guestPhone": "0400000010", "partySize": 3, "business": "default"})
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert body.get("id"), "the join response must hand back an id — otherwise nothing can track it later"
    assert body["id"].startswith("WL-")


def test_track_endpoint_reports_live_position_not_the_stale_join_time_value(client, owner_headers):
    first = req(client, "POST", "/api/public/join-waitlist", json={
        "guestName": "Ahead Guest", "guestPhone": "0400000011", "partySize": 2, "business": "default"}).json()
    second = req(client, "POST", "/api/public/join-waitlist", json={
        "guestName": "Behind Guest", "guestPhone": "0400000012", "partySize": 4, "business": "default"}).json()

    track_second = req(client, "GET", f"/api/waitlist/track/{second['id']}")
    assert track_second.status_code == 200, track_second.text[:200]
    body = track_second.json()
    assert body["status"] == "waiting"
    assert body["aheadOfYou"] >= 1, "at least the first guest must still be counted ahead"
    assert body["position"] == body["aheadOfYou"] + 1

    # The guest ahead gets seated (a staff-only action) — position must drop
    # to reflect that, not stay pinned to the number handed out at join time.
    seat_r = req(client, "POST", f"/api/waitlist/{first['id']}/seat", headers=owner_headers)
    assert seat_r.status_code == 200, seat_r.text[:200]

    track_after = req(client, "GET", f"/api/waitlist/track/{second['id']}").json()
    assert track_after["aheadOfYou"] == body["aheadOfYou"] - 1
    assert track_after["position"] == body["position"] - 1


def test_a_seated_guest_no_longer_has_a_queue_position(client, owner_headers):
    entry = req(client, "POST", "/api/public/join-waitlist", json={
        "guestName": "Seated Soon Guest", "guestPhone": "0400000013", "partySize": 2, "business": "default"}).json()
    req(client, "POST", f"/api/waitlist/{entry['id']}/seat", headers=owner_headers)

    tracked = req(client, "GET", f"/api/waitlist/track/{entry['id']}")
    assert tracked.status_code == 200, tracked.text[:200]
    body = tracked.json()
    assert body["status"] == "seated"
    assert body["position"] is None
    assert body["aheadOfYou"] is None


def test_tracking_an_unknown_code_is_a_clean_404(client):
    r = req(client, "GET", "/api/waitlist/track/WL-NOPE0000")
    assert r.status_code == 404
