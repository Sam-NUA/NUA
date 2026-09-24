"""NUA Counter's integration with the standalone NUA Bookings API.

NUA Counter is deliberately "just another partner" of the Bookings platform
(partner name: nua-native) — it talks to the same hosted /v1 API with the same
kind of key an external POS would use. That keeps the platform honest: if the
public API can't support NUA's own POS, it can't support anyone's.

Disabled unless all four env vars are set:
  NUA_BOOKINGS_API_URL   e.g. https://nua-bookings-api.fly.dev
  NUA_BOOKINGS_API_KEY   the nua-native partner key (live or sandbox)
  NUA_BOOKINGS_VENUE_ID  this venue's id on the Bookings platform
  NUA_BOOKINGS_BUSINESS_ID  the single local business allowed to mirror

Mirroring is fire-and-forget: a Bookings outage must never block taking a
reservation at the counter.
"""
import asyncio
import logging
import os

import httpx

logger = logging.getLogger("nua.bookings_partner")


def _config(business_id=None):
    url = os.environ.get("NUA_BOOKINGS_API_URL", "").rstrip("/")
    key = os.environ.get("NUA_BOOKINGS_API_KEY", "")
    venue = os.environ.get("NUA_BOOKINGS_VENUE_ID", "")
    business = os.environ.get("NUA_BOOKINGS_BUSINESS_ID", "")
    if url and key and venue and business and business_id == business:
        return {"url": url, "key": key, "venue": venue}
    return None


def enabled(business_id=None) -> bool:
    return _config(business_id) is not None


async def _post(path: str, payload: dict, business_id: str, request_id: str) -> dict | None:
    cfg = _config(business_id)
    if not cfg:
        return None
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.post(
                f"{cfg['url']}{path}", json=payload,
                headers={"Authorization": f"Bearer {cfg['key']}",
                         "Idempotency-Key": f"counter:{business_id}:{request_id}"},
            )
        if r.status_code >= 400:
            logger.warning("bookings mirror %s got HTTP %s", path, r.status_code)
            return None
        return r.json()
    except Exception as exc:
        logger.warning("bookings mirror %s failed (%s)", path, type(exc).__name__)
        return None


def mirror_reservation_created(reservation: dict) -> None:
    """Mirror a Counter reservation into the Bookings platform, in the
    background. Stores nothing locally — the platform's booking id comes back
    on the reservation document via the update below when it succeeds."""
    cfg = _config(reservation.get("businessId"))
    if not cfg:
        return

    async def _run():
        payload = {
            "venue_id": cfg["venue"],
            "party_size": reservation.get("partySize", 2),
            "start_time": f"{reservation.get('date')}T{reservation.get('time')}:00",
            "contact_name": reservation.get("guestName", "Guest"),
            "contact_email": reservation.get("guestEmail"),
            "contact_phone": reservation.get("guestPhone"),
            "notes": reservation.get("notes"),
        }
        result = await _post("/v1/bookings", payload, reservation["businessId"], reservation["id"])
        if result and result.get("id"):
            from database import db
            await db.reservations.update_one(
                {"id": reservation["id"], "businessId": reservation["businessId"]},
                {"$set": {"bookingsPlatformId": result["id"]}},
            )

    asyncio.create_task(_run())


def mirror_reservation_status(reservation: dict, status: str) -> None:
    """Push a status change (cancelled / seated / no_show) for a mirrored
    reservation to the platform."""
    cfg = _config(reservation.get("businessId"))
    platform_id = reservation.get("bookingsPlatformId")
    if not cfg or not platform_id:
        return

    async def _run():
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.patch(
                    f"{cfg['url']}/v1/bookings/{platform_id}",
                    json={"status": status},
                    headers={"Authorization": f"Bearer {cfg['key']}"},
                )
                response.raise_for_status()
        except Exception as exc:
            logger.warning("bookings status mirror failed (%s)", type(exc).__name__)

    asyncio.create_task(_run())
