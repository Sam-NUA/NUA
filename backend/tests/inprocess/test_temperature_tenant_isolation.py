"""routes/temperature.py's HACCP fridge/freezer monitoring (devices,
readings, alerts) had zero businessId scoping. The sharpest finding:
rotate-secret and delete had no ownership check at all, so any owner
could rotate or delete another business's real temperature sensor's
ingest secret — breaking that physical device's ability to report real
readings, or letting an attacker who learns the new secret inject fake
"normal" readings to hide a real food-safety failure.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Temperature Test Owner", "email": email, "password": "TemperatureTenantTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "TemperatureTenantTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def test_temperature_device_secret_rotation_and_delete_are_owned_per_business(client, owner_headers):
    other = _login_as(client, owner_headers, email="temp.device.other@nua.com", business_id="temp-device-other-biz")

    created = req(client, "POST", "/api/temperature/devices", headers=other, json={
        "name": "Other Biz Walk-In Freezer", "unitType": "freezer", "brand": "manual"})
    assert created.status_code == 200, created.text[:200]
    device_id = created.json()["id"]
    original_secret = created.json()["ingestSecret"]
    try:
        mine = req(client, "GET", "/api/temperature/devices", headers=owner_headers).json()
        assert not any(d["id"] == device_id for d in mine)

        rotate_mine = req(client, "POST", f"/api/temperature/devices/{device_id}/rotate-secret", headers=owner_headers)
        assert rotate_mine.status_code == 404, (
            "another business's device secret must never be rotatable — that breaks the real sensor "
            "and could let an attacker inject fake readings"
        )

        delete_mine = req(client, "DELETE", f"/api/temperature/devices/{device_id}", headers=owner_headers)
        assert delete_mine.status_code == 404

        # Confirm the secret is unchanged and the device still exists for its real owner.
        raw = _run(db.temperature_devices.find_one({"id": device_id}, {"_id": 0}))
        assert raw is not None
        assert raw["ingestSecret"] == original_secret
    finally:
        _run(db.temperature_devices.delete_one({"id": device_id}))


def test_readings_and_alerts_are_scoped_per_business(client, owner_headers):
    other = _login_as(client, owner_headers, email="temp.readings.other@nua.com", business_id="temp-readings-other-biz")

    created = req(client, "POST", "/api/temperature/devices", headers=other, json={
        "name": "Other Biz Fridge", "unitType": "fridge", "brand": "manual"})
    assert created.status_code == 200, created.text[:200]
    device_id = created.json()["id"]

    reading = req(client, "POST", "/api/temperature/readings", headers=other, json={
        "deviceId": device_id, "temperatureC": 25.0})  # abnormal -> also creates an alert
    assert reading.status_code == 200, reading.text[:200]
    try:
        my_readings = req(client, "GET", "/api/temperature/readings", headers=owner_headers).json()
        assert not any(r["deviceId"] == device_id for r in my_readings)

        my_alerts = req(client, "GET", "/api/temperature/alerts", headers=owner_headers).json()
        assert not any(a["deviceId"] == device_id for a in my_alerts)

        their_alerts = req(client, "GET", "/api/temperature/alerts", headers=other).json()
        matching = [a for a in their_alerts if a["deviceId"] == device_id]
        assert matching, "the owning business must still see its own alert"

        ack_mine = req(client, "POST", f"/api/temperature/alerts/{matching[0]['id']}/acknowledge", headers=owner_headers)
        assert ack_mine.status_code == 404

        log_mine = req(client, "POST", "/api/temperature/readings", headers=owner_headers, json={
            "deviceId": device_id, "temperatureC": 3.0})
        assert log_mine.status_code == 404, "must not be able to log a reading against another business's device"
    finally:
        _run(db.temperature_devices.delete_one({"id": device_id}))
        _run(db.temperature_readings.delete_many({"deviceId": device_id}))
        _run(db.temperature_alerts.delete_many({"deviceId": device_id}))
