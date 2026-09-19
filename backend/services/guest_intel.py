"""Guest intelligence for the booking desk and the NUA phone agent.

Turns a customer's raw history into the handful of facts whoever is taking
the booking actually needs in the moment: when they last booked, when they
last came in, what they ate, what they order most, and what they always ask
for. Read-only and defensive — a guest with no history still returns a valid
(empty) summary rather than erroring, because a half-known guest is the
normal case at the booking desk.
"""
import re
from collections import Counter
from typing import Optional

from database import db
from middleware.actor_context import tenant_scope_filter

# Requests that recur across visits are worth surfacing; one-off notes aren't.
FREQUENT_REQUEST_MIN_COUNT = 2
# Very short notes ("x", "-") are noise, not preferences.
MIN_REQUEST_LEN = 3


def normalize_phone(phone: str) -> str:
    """Compare phone numbers by digits only. A guest saved as
    '+61 400 111 222' must still match caller ID '0400111222' — the last 8
    digits are the stable part across national/international formats."""
    digits = re.sub(r"\D", "", phone or "")
    return digits[-8:] if len(digits) >= 8 else digits


def _iso_date(value) -> str:
    if not value:
        return ""
    s = str(value)
    return s[:10]


async def find_customers(query: str = "", phone: str = "", email: str = "",
                         limit: int = 8, business_id: Optional[str] = None) -> list[dict]:
    """Match on name, phone, or email. Phone matching is digit-normalized so
    an inbound caller ID matches however the number was typed when saved."""
    matches: list[dict] = []
    seen: set[str] = set()
    scope = tenant_scope_filter(business_id)

    def _add(rows):
        for c in rows:
            if c.get("id") not in seen:
                seen.add(c.get("id"))
                matches.append(c)

    if phone:
        digits = re.sub(r"\D", "", phone)
        if digits:
            # Mongo can't normalize stored formatting, so scan candidates and
            # compare digits in Python. Customer lists are small enough
            # (thousands) that this stays comfortably fast.
            everyone = await db.customers.find(scope, {"_id": 0}).to_list(5000)
            tail = normalize_phone(phone)
            # Exact tail match first — that's the caller-ID case, where the
            # whole number is known and the best match must win.
            _add([c for c in everyone if normalize_phone(c.get("phone", "")) == tail])
            # Then partial: staff typing a number into the booking dialog only
            # get a few digits in before they expect to see the guest. Also try
            # without a leading trunk zero — staff type the local form
            # ("0400 111…") for numbers stored internationally ("+61 400 111…"),
            # where that zero doesn't exist.
            variants = {digits, digits.lstrip("0")}
            _add([c for c in everyone
                  if any(v and v in re.sub(r"\D", "", c.get("phone", "") or "")
                         for v in variants)])

    if email:
        _add(await db.customers.find(
            {**tenant_scope_filter(business_id), "$and": [scope, {"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}}]}, {"_id": 0}
        ).to_list(20))

    if query:
        _add(await db.customers.find({**tenant_scope_filter(business_id), "$and": [scope, {"$or": [
            {"name": {"$regex": re.escape(query), "$options": "i"}},
            {"email": {"$regex": re.escape(query), "$options": "i"}},
            {"phone": {"$regex": re.escape(query), "$options": "i"}},
        ]}]}, {"_id": 0}).to_list(limit))

    return matches[:limit]


async def build_guest_intel(customer: dict, business_id: Optional[str] = None) -> dict:
    """The booking-desk summary for one customer."""
    cid = customer.get("id")
    email = (customer.get("email") or "").strip()
    phone_tail = normalize_phone(customer.get("phone", ""))
    scope = tenant_scope_filter(business_id or customer.get("businessId"))

    # --- Reservations (match by id, email, or phone; older rows may lack
    # customerId entirely, and a guest who only ever gave a phone number at
    # booking time — no account, no email — would otherwise never show up in
    # their own history here). The regex lets any non-digit separator
    # ("+61 400 111 222" vs "0400111222") sit between each digit of the
    # tail, so it matches regardless of how the number was formatted when
    # each reservation was taken — Mongo can't normalize that itself.
    or_clauses = [{"customerId": cid}]
    if email:
        or_clauses.append({"guestEmail": email})
    if phone_tail:
        phone_regex = r"\D*".join(re.escape(d) for d in phone_tail)
        or_clauses.append({"guestPhone": {"$regex": phone_regex}})
    res_query = {"$and": [scope, {"$or": or_clauses}]}
    reservations = await db.reservations.find(res_query, {"_id": 0}).to_list(500)
    reservations.sort(key=lambda r: f"{r.get('date','')} {r.get('time','')}", reverse=True)

    # --- Transactions (what they actually ate/drank)
    transactions = await db.transactions.find(
        {"$and": [scope, {"customerId": cid}]}, {"_id": 0}
    ).to_list(500)
    transactions.sort(key=lambda t: str(t.get("timestamp", "")), reverse=True)

    # Last booking = most recent reservation of any status.
    last_booking = None
    if reservations:
        r = reservations[0]
        last_booking = {
            "date": _iso_date(r.get("date")), "time": r.get("time", ""),
            "partySize": r.get("partySize"), "status": r.get("status", ""),
            "tableNumber": r.get("tableNumber"),
        }

    # Last visit = they actually turned up. A seated/completed booking counts,
    # and so does a POS transaction (walk-ins never had a booking at all).
    visited = [r for r in reservations if r.get("status") in ("seated", "completed")]
    last_visit_date = ""
    last_visit_source = ""
    if visited:
        last_visit_date = _iso_date(visited[0].get("date"))
        last_visit_source = "booking"
    if transactions:
        txn_date = _iso_date(transactions[0].get("timestamp"))
        if txn_date > last_visit_date:
            last_visit_date = txn_date
            last_visit_source = "pos"

    # What they had last time — items from the most recent transaction.
    last_order_items = []
    if transactions:
        for it in (transactions[0].get("items") or []):
            last_order_items.append({
                "name": it.get("productName", ""),
                "quantity": it.get("quantity", 1),
            })

    # What they order most — across all their transactions.
    counter: Counter = Counter()
    for t in transactions:
        for it in (t.get("items") or []):
            name = (it.get("productName") or "").strip()
            if name:
                counter[name] += int(it.get("quantity", 1) or 1)
    top_items = [{"name": n, "timesOrdered": c} for n, c in counter.most_common(5)]

    # Frequent requests — notes they've repeated across bookings, plus the
    # standing preferences already on their profile (allergies never expire).
    request_counter: Counter = Counter()
    for r in reservations:
        for field in ("specialRequests", "notes"):
            text = (r.get(field) or "").strip()
            if len(text) >= MIN_REQUEST_LEN:
                request_counter[text] += 1
    frequent_requests = [
        {"request": text, "times": n}
        for text, n in request_counter.most_common(5)
        if n >= FREQUENT_REQUEST_MIN_COUNT
    ]

    standing_prefs = []
    for allergy in (customer.get("allergies") or []):
        standing_prefs.append({"type": "allergy", "value": allergy})
    for diet in (customer.get("dietaryRestrictions") or []):
        standing_prefs.append({"type": "dietary", "value": diet})
    if customer.get("seatingPreference"):
        standing_prefs.append({"type": "seating", "value": customer["seatingPreference"]})

    spend = sum(float(t.get("total", 0) or 0) for t in transactions)
    completed_visits = len([r for r in reservations if r.get("status") == "completed"])

    return {
        "customerId": cid,
        "name": customer.get("name", ""),
        "phone": customer.get("phone", ""),
        "email": customer.get("email", ""),
        "isVip": bool(customer.get("isVip")),
        "membershipTier": customer.get("membershipTier", ""),
        "tags": customer.get("tags") or [],
        "notes": customer.get("notes", ""),
        "lastBooking": last_booking,
        "lastVisit": {"date": last_visit_date, "source": last_visit_source} if last_visit_date else None,
        "lastOrderItems": last_order_items,
        "topItems": top_items,
        "frequentRequests": frequent_requests,
        "standingPreferences": standing_prefs,
        "stats": {
            "totalBookings": len(reservations),
            "completedVisits": completed_visits,
            "noShows": int(customer.get("noShowCount", 0) or 0),
            "totalSpend": round(spend, 2),
            "avgSpend": round(spend / len(transactions), 2) if transactions else 0.0,
        },
    }


async def lookup(query: str = "", phone: str = "", email: str = "",
                 limit: int = 8, with_intel: bool = True,
                 business_id: Optional[str] = None) -> list[dict]:
    """One call for both front doors: staff typing a name/phone/email into the
    booking dialog, and the phone agent resolving an inbound caller ID."""
    customers = await find_customers(query=query, phone=phone, email=email, limit=limit,
                                      business_id=business_id)
    if not with_intel:
        return [{
            "customerId": c.get("id"), "name": c.get("name", ""),
            "phone": c.get("phone", ""), "email": c.get("email", ""),
            "isVip": bool(c.get("isVip")),
        } for c in customers]
    return [await build_guest_intel(c, business_id=business_id) for c in customers]
