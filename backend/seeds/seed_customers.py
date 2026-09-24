"""
Seed 5 rich demo customers — only if the `customers` collection is empty.

We also seed a few realistic reservations, transactions and feedbacks so the
360-Guest CRM tabs render meaningful data instead of "No history" placeholders.

Idempotent: a non-empty `customers` collection short-circuits this function,
so re-running on a restored DB never duplicates real guest records.
"""
from datetime import datetime, timedelta, timezone
import uuid
from typing import Any, Dict, List
from database import db
from services import reservation_store


def _iso(d: datetime) -> str:
    return d.replace(microsecond=0).isoformat()


DEMO_CUSTOMERS: List[Dict[str, Any]] = [
    {
        "name": "Olivia Bennett",
        "email": "olivia.bennett@example.com",
        "phone": "+61400111222",
        "membershipTier": "Platinum",
        "birthday": "1989-03-14",
        "company": "Bennett & Co. Architects",
        "seatingPreference": "window",
        "dietaryRestrictions": ["Gluten-Free"],
        "allergies": ["Peanuts"],
        "favoriteDishes": ["Truffle Risotto", "Lemon Tart"],
        "tags": ["VIP", "High Spender", "Reviewer"],
        "isVip": True,
        "notes": "Books quarterly. Prefers a quiet corner. Always orders the chef's tasting menu.",
        "totalSpent": 4280.50,
        "visits": 38,
        "points": 4280,
        "avgSpendPerVisit": 112.65,
        "feedbackRating": 4.8,
        "feedbackCount": 6,
        "noShowCount": 0,
        "lastVisitDate": _iso(datetime.now(timezone.utc) - timedelta(days=4)),
        "storeCredit": 50.0,
    },
    {
        "name": "Marcus Tan",
        "email": "marcus.tan@example.com",
        "phone": "+61400333444",
        "membershipTier": "Gold",
        "birthday": "1992-09-02",
        "company": "Tan Capital Partners",
        "seatingPreference": "booth",
        "dietaryRestrictions": ["Vegan"],
        "allergies": [],
        "favoriteDishes": ["Wild Mushroom Pizza", "Espresso Martini"],
        "tags": ["Corporate", "Regular"],
        "isVip": False,
        "notes": "Hosts client lunches on Wednesdays — needs printed receipt with company ABN.",
        "totalSpent": 2410.00,
        "visits": 22,
        "points": 2410,
        "avgSpendPerVisit": 109.55,
        "feedbackRating": 4.5,
        "feedbackCount": 4,
        "noShowCount": 1,
        "lastVisitDate": _iso(datetime.now(timezone.utc) - timedelta(days=12)),
        "storeCredit": 0.0,
    },
    {
        "name": "Priya Sharma",
        "email": "priya.sharma@example.com",
        "phone": "+61400555666",
        "membershipTier": "Silver",
        "birthday": "1995-11-21",
        "company": "",
        "seatingPreference": "outdoor",
        "dietaryRestrictions": ["Vegetarian"],
        "allergies": ["Tree Nuts", "Sesame"],
        "favoriteDishes": ["Margherita", "Tiramisu"],
        "tags": ["Birthday Month", "Influencer"],
        "isVip": False,
        "notes": "Active on Instagram (45k followers). Tag the venue when she posts.",
        "totalSpent": 985.75,
        "visits": 14,
        "points": 986,
        "avgSpendPerVisit": 70.41,
        "feedbackRating": 4.2,
        "feedbackCount": 3,
        "noShowCount": 0,
        "lastVisitDate": _iso(datetime.now(timezone.utc) - timedelta(days=2)),
        "storeCredit": 0.0,
    },
    {
        "name": "James O'Donnell",
        "email": "james.odonnell@example.com",
        "phone": "+61400777888",
        "membershipTier": "Bronze",
        "birthday": "1981-06-08",
        "company": "",
        "seatingPreference": "bar",
        "dietaryRestrictions": [],
        "allergies": ["Shellfish"],
        "favoriteDishes": ["Wagyu Burger", "IPA"],
        "tags": ["Regular"],
        "isVip": False,
        "notes": "Walk-in regular for the Friday-night bar crowd.",
        "totalSpent": 612.20,
        "visits": 9,
        "points": 612,
        "avgSpendPerVisit": 68.02,
        "feedbackRating": 4.0,
        "feedbackCount": 2,
        "noShowCount": 0,
        "lastVisitDate": _iso(datetime.now(timezone.utc) - timedelta(days=18)),
        "storeCredit": 0.0,
    },
    {
        "name": "Sofia Reyes",
        "email": "sofia.reyes@example.com",
        "phone": "+61400999000",
        "membershipTier": "Gold",
        "birthday": "1987-01-30",
        "company": "Reyes Wellness Studio",
        "seatingPreference": "indoor",
        "dietaryRestrictions": ["Dairy-Free", "Keto"],
        "allergies": ["Milk"],
        "favoriteDishes": ["Grilled Salmon", "Matcha Latte"],
        "tags": ["VIP", "Family"],
        "isVip": True,
        "notes": "Brings family of 5 every Sunday brunch. Pre-orders kids' menu.",
        "totalSpent": 3120.00,
        "visits": 31,
        "points": 3120,
        "avgSpendPerVisit": 100.65,
        "feedbackRating": 4.7,
        "feedbackCount": 5,
        "noShowCount": 0,
        "lastVisitDate": _iso(datetime.now(timezone.utc) - timedelta(days=6)),
        "storeCredit": 25.0,
    },
]


def _seed_reservations(customer_id: str, name: str, email: str, phone: str, count: int):
    """Generate `count` past + 1 upcoming reservation per customer."""
    rows = []
    for i in range(count):
        days_ago = (i + 1) * 14
        d = datetime.now(timezone.utc) - timedelta(days=days_ago)
        rows.append({
            "id": f"res-{uuid.uuid4().hex[:8]}",
            "customerId": customer_id,
            "customerName": name,
            "guestEmail": email,
            "customerPhone": phone,
            "date": d.date().isoformat(),
            "time": "19:00" if i % 2 == 0 else "12:30",
            "partySize": 2 + (i % 3),
            "tableNumber": (i % 12) + 1,
            "status": "completed",
            "specialRequests": "" if i % 2 else "Birthday cake at the end",
            "source": "in-app",
            "createdAt": _iso(d - timedelta(days=2)),
            "isDemo": True,
        })
    # 1 upcoming
    upcoming = datetime.now(timezone.utc) + timedelta(days=7)
    rows.append({
        "id": f"res-{uuid.uuid4().hex[:8]}",
        "customerId": customer_id,
        "customerName": name,
        "guestEmail": email,
        "customerPhone": phone,
        "date": upcoming.date().isoformat(),
        "time": "19:30",
        "partySize": 2,
        "tableNumber": 5,
        "status": "confirmed",
        "specialRequests": "",
        "source": "in-app",
        "createdAt": _iso(datetime.now(timezone.utc)),
    })
    return rows


def _seed_transactions(customer_id: str, count: int, avg_spend: float):
    """Generate `count` past transactions averaging ~avg_spend each."""
    rows = []
    items_catalog = [
        {"productId": "p-truffle", "name": "Truffle Risotto", "category": "Mains", "price": 38.0, "quantity": 1},
        {"productId": "p-margherita", "name": "Margherita Pizza", "category": "Pizza", "price": 22.0, "quantity": 1},
        {"productId": "p-salmon", "name": "Grilled Salmon", "category": "Mains", "price": 34.0, "quantity": 1},
        {"productId": "p-tiramisu", "name": "Tiramisu", "category": "Desserts", "price": 14.0, "quantity": 1},
        {"productId": "p-cappuccino", "name": "Cappuccino", "category": "Coffee", "price": 5.5, "quantity": 2},
        {"productId": "p-wagyu", "name": "Wagyu Burger", "category": "Mains", "price": 32.0, "quantity": 1},
    ]
    for i in range(count):
        days_ago = (i + 1) * 7
        d = datetime.now(timezone.utc) - timedelta(days=days_ago)
        pick = items_catalog[i % len(items_catalog)]
        sub = round(pick["price"] * pick["quantity"], 2)
        # pad subtotal toward the customer's typical spend
        pad_items = []
        remaining = avg_spend - sub
        while remaining > 6 and len(pad_items) < 3:
            extra = items_catalog[(i + len(pad_items) + 1) % len(items_catalog)]
            pad_items.append({**extra, "quantity": 1})
            remaining -= extra["price"]
        items = [pick] + pad_items
        subtotal = round(sum(it["price"] * it["quantity"] for it in items), 2)
        tax = round(subtotal * 0.10, 2)
        total = round(subtotal + tax, 2)
        rows.append({
            "id": f"tx-{uuid.uuid4().hex[:8]}",
            "customerId": customer_id,
            "items": items,
            "subtotal": subtotal,
            "tax": tax,
            "total": total,
            "paymentMethod": "card" if i % 2 == 0 else "cash",
            "timestamp": _iso(d),
            "status": "completed",
            "source": "pos",
            "isDemo": True,
        })
    return rows


def _seed_feedbacks(customer_id: str, name: str, count: int, avg_rating: float):
    rows = []
    comments = [
        "Service was on point, food beautifully presented.",
        "Loved the new menu items, will be back soon.",
        "Slightly slow on a Friday night but staff was apologetic.",
        "Best truffle risotto in town — Olivia knows!",
        "Brought the family, kids loved the dessert.",
        "Cocktail menu is creative; tasting notes were a nice touch.",
    ]
    for i in range(count):
        d = datetime.now(timezone.utc) - timedelta(days=(i + 1) * 21)
        rating = max(3, min(5, round(avg_rating - (i % 2) * 0.5)))
        rows.append({
            "id": f"fb-{uuid.uuid4().hex[:8]}",
            "customerId": customer_id,
            "guestName": name,
            "rating": rating,
            "foodRating": rating,
            "serviceRating": max(3, rating - (i % 2)),
            "ambienceRating": rating,
            "comment": comments[i % len(comments)],
            "status": "new" if i == 0 else "responded",
            "response": "" if i == 0 else "Thanks so much for the kind words!",
            "createdAt": _iso(d),
            "isDemo": True,
        })
    return rows


async def seed_demo_customers(business_id: str = "default"):
    """Insert 5 rich customers + reservations + transactions + feedback.

    Idempotent on a PER-CUSTOMER basis (matches on email) — so safe to run
    against a DB that already has real or test customers. Also performs a
    one-time cleanup of obviously-broken legacy rows (e.g. redacted
    placeholders with `@nua.local` emails) that break Pydantic EmailStr
    validation and cause the customers GET endpoint to 500."""
    seeded_ids = []
    skipped = 0
    for c in DEMO_CUSTOMERS:
        if await db.customers.count_documents({"email": c["email"], "businessId": business_id}):
            skipped += 1
            continue
        doc = {
            "id": str(uuid.uuid4()),
            **c,
            "joinDate": _iso(datetime.now(timezone.utc) - timedelta(days=180)),
            "reservationIds": [],
            "isDemo": True, "businessId": business_id,
        }
        await db.customers.insert_one(doc)
        seeded_ids.append(doc["id"])

        # Seed history rows proportional to the customer's visit count.
        n_visits = max(2, min(6, c["visits"] // 5))
        if c["visits"] > 0:
            res_rows = _seed_reservations(doc["id"], c["name"], c["email"], c["phone"], n_visits)
            for row in res_rows:
                row["businessId"] = business_id
            if res_rows:
                await reservation_store.insert_many(res_rows)
            tx_rows = _seed_transactions(doc["id"], n_visits, c.get("avgSpendPerVisit", 80.0))
            for row in tx_rows:
                row["businessId"] = business_id
            if tx_rows:
                await db.transactions.insert_many(tx_rows)
            fb_rows = _seed_feedbacks(doc["id"], c["name"], c["feedbackCount"], c.get("feedbackRating", 4.0))
            for row in fb_rows:
                row["businessId"] = business_id
            if fb_rows:
                await db.feedback.insert_many(fb_rows)

    return {
        "seeded": len(seeded_ids) > 0,
        "customerIds": seeded_ids,
        "count": len(seeded_ids),
        "skippedExisting": skipped,
    }
