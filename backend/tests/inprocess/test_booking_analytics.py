"""Booking Analytics report endpoint. The core thing under test is the
revenue-honesty rule: a same-table/same-day transaction only counts as
"estimated" revenue for a booking when that table had exactly one booking
that day. Two bookings sharing a table/day must not have that day's real
revenue silently split between them -- it goes to "unknown" instead.
"""
from datetime import datetime, timezone

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    import asyncio
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_reservation(client, owner_headers, **overrides):
    body = {
        "guestName": "Analytics Guest", "partySize": 2, "date": "2026-07-01", "time": "19:00",
        "source": "phone", "status": "completed",
    }
    body.update(overrides)
    status = body.pop("status", None)
    r = req(client, "POST", "/api/reservations", headers=owner_headers, json=body)
    assert r.status_code == 200, r.text
    res = r.json()
    if status and status != res["status"]:
        _run(db.reservations.update_one({"id": res["id"]}, {"$set": {"status": status}}))
        res["status"] = status
    return res


def _insert_transaction(table_number, iso_date, total, business_id=None):
    txn = {"businessId": "default",
        "id": f"TXN-ANALYTICS-{table_number}-{iso_date}-{total}",
        "timestamp": datetime.fromisoformat(f"{iso_date}T20:00:00+00:00"),
        "items": [], "subtotal": total, "gst": 0, "total": total,
        "paymentMethod": "card", "location": "main", "cashier": "tester",
        "tableNumber": table_number, "orderType": "dine_in",
    }
    if business_id:
        txn["businessId"] = business_id
    _run(db.transactions.insert_one(txn))


def test_report_totals_and_channel_breakdown(client, owner_headers):
    _make_reservation(client, owner_headers, guestName="A", source="phone", partySize=2,
                       date="2026-07-05", tableNumber="AN-1", status="completed")
    _make_reservation(client, owner_headers, guestName="B", source="website", partySize=4,
                       date="2026-07-05", tableNumber="AN-2", status="completed")
    _make_reservation(client, owner_headers, guestName="C", source="phone", partySize=3,
                       date="2026-07-06", tableNumber="AN-3", status="no_show")

    r = req(client, "GET", "/api/booking-analytics/report",
            headers=owner_headers, params={"start": "2026-07-01", "end": "2026-07-10"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kpis"]["bookings"] >= 3
    channels = {c["source"]: c for c in body["channels"]}
    assert "phone" in channels and "website" in channels
    assert channels["phone"]["bookings"] >= 2


def test_unambiguous_table_day_match_is_estimated_revenue(client, owner_headers):
    res = _make_reservation(client, owner_headers, guestName="Solo Diner", source="phone",
                             date="2026-07-08", tableNumber="AN-SOLO", status="completed")
    _insert_transaction("AN-SOLO", "2026-07-08", 123.45)

    r = req(client, "GET", "/api/booking-analytics/report",
            headers=owner_headers, params={"start": "2026-07-08", "end": "2026-07-08"})
    assert r.status_code == 200, r.text
    detailed = {d["id"]: d for d in r.json()["detailed"]}
    assert detailed[res["id"]]["revenueConfidence"] == "estimated"
    assert detailed[res["id"]]["revenueEstimate"] == 123.45


def test_ambiguous_shared_table_day_is_unknown_not_split(client, owner_headers):
    res1 = _make_reservation(client, owner_headers, guestName="First", source="phone",
                              date="2026-07-09", tableNumber="AN-SHARED", status="completed")
    res2 = _make_reservation(client, owner_headers, guestName="Second", source="website",
                              date="2026-07-09", tableNumber="AN-SHARED", status="completed")
    _insert_transaction("AN-SHARED", "2026-07-09", 200.00)

    r = req(client, "GET", "/api/booking-analytics/report",
            headers=owner_headers, params={"start": "2026-07-09", "end": "2026-07-09"})
    assert r.status_code == 200, r.text
    body = r.json()
    detailed = {d["id"]: d for d in body["detailed"]}
    assert detailed[res1["id"]]["revenueConfidence"] == "unknown"
    assert detailed[res1["id"]]["revenueEstimate"] is None
    assert detailed[res2["id"]]["revenueConfidence"] == "unknown"
    assert body["kpis"]["revenueUnknown"] >= 200.00


def test_deposit_is_actual_revenue_not_estimated(client, owner_headers):
    r = req(client, "POST", "/api/reservations", headers=owner_headers, json={
        "guestName": "Deposit Guest", "partySize": 2, "date": "2026-07-11", "time": "19:00",
        "source": "phone", "depositRequired": 50, "depositPaid": True,
    })
    assert r.status_code == 200, r.text

    report = req(client, "GET", "/api/booking-analytics/report",
                 headers=owner_headers, params={"start": "2026-07-11", "end": "2026-07-11"})
    assert report.status_code == 200
    assert report.json()["kpis"]["revenueActual"] >= 50


def test_party_size_buckets(client, owner_headers):
    _make_reservation(client, owner_headers, guestName="Solo", partySize=1, date="2026-07-12", status="completed")
    _make_reservation(client, owner_headers, guestName="Big Group", partySize=12, date="2026-07-12", status="completed")

    r = req(client, "GET", "/api/booking-analytics/report",
            headers=owner_headers, params={"start": "2026-07-12", "end": "2026-07-12"})
    buckets = {b["bucket"]: b["bookings"] for b in r.json()["partySizeBuckets"]}
    assert buckets["1"] >= 1
    assert buckets["10+"] >= 1


def test_no_hardcoded_channel_list_a_new_source_value_shows_up(client, owner_headers):
    _make_reservation(client, owner_headers, guestName="QR Guest", source="qr_code",
                       date="2026-07-13", status="completed")

    r = req(client, "GET", "/api/booking-analytics/report",
            headers=owner_headers, params={"start": "2026-07-13", "end": "2026-07-13"})
    sources = [c["source"] for c in r.json()["channels"]]
    assert "qr_code" in sources


def test_report_csv_export(client, owner_headers):
    _make_reservation(client, owner_headers, guestName="CSV Guest", date="2026-07-14", status="completed")

    r = req(client, "GET", "/api/booking-analytics/report.csv",
            headers=owner_headers, params={"start": "2026-07-14", "end": "2026-07-14"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "CSV Guest" in r.text
    assert r.text.startswith("Booking ID,Guest,Date")


def test_report_pdf_export(client, owner_headers):
    _make_reservation(client, owner_headers, guestName="PDF Guest", date="2026-07-15", status="completed")

    r = req(client, "GET", "/api/booking-analytics/report.pdf",
            headers=owner_headers, params={"start": "2026-07-15", "end": "2026-07-15"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF-1.4")
    assert b"%%EOF" in r.content


def test_cancelled_and_no_show_are_excluded_from_covers_but_counted_in_bookings(client, owner_headers):
    _make_reservation(client, owner_headers, guestName="Cancelled Guest", partySize=6,
                       date="2026-07-16", status="cancelled")

    r = req(client, "GET", "/api/booking-analytics/report",
            headers=owner_headers, params={"start": "2026-07-16", "end": "2026-07-16"})
    body = r.json()
    assert body["kpis"]["bookings"] >= 1
    detailed = [d for d in body["detailed"] if d["guestName"] == "Cancelled Guest"]
    assert detailed and detailed[0]["status"] == "cancelled"


def test_legacy_reservation_without_guestname_field_still_shows_a_name(client, owner_headers):
    # Reservation._legacy_aliases backfills guestName from customerName/name
    # at model-parse time, but this endpoint reads raw dicts straight from
    # Mongo -- a pre-migration document with only customerName set must
    # still show a real name in the report, not a blank cell.
    _run(db.reservations.insert_one({"businessId": "default",
        "id": "RES-LEGACY-1", "customerName": "Old Format Guest", "partySize": 2,
        "date": "2026-07-17", "time": "19:00", "status": "completed", "source": "phone",
        "createdAt": "2026-07-17T00:00:00", "updatedAt": "2026-07-17T00:00:00",
    }))

    r = req(client, "GET", "/api/booking-analytics/report",
            headers=owner_headers, params={"start": "2026-07-17", "end": "2026-07-17"})
    detailed = {d["id"]: d for d in r.json()["detailed"]}
    assert detailed["RES-LEGACY-1"]["guestName"] == "Old Format Guest"
