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

Native reservations remain authoritative. Durable projection delivery lives
in booking_sync.py; reservation_store.py records intent transactionally.
"""
import logging
import os

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
