"""P&L and accounting summary compute in the database, not in Python.

Both used to `.find().to_list(10000)` the whole transactions/expenses
collections and sum in Python — correct only as long as a venue never traded
past 10,000 transactions, after which the report would silently start
ignoring the oldest rows rather than erroring. These now run as aggregation
pipelines with an optional date range.

The app seeds demo transactions at startup and the client/database are shared
across every test module in this session, so tests measure the *delta* their
own seeded rows cause rather than asserting an absolute total — the report
should move by exactly what was added, regardless of what else is in there.
"""
from datetime import datetime, timezone

from conftest import req


def _summary(client, headers, **params):
    return req(client, "GET", "/api/accounting/summary", headers=headers, params=params).json()


def _pandl(client, headers, **params):
    return req(client, "GET", "/api/accounting/p-and-l", headers=headers, params=params).json()


def test_summary_sums_across_all_transactions_and_expenses(client, owner_headers):
    import asyncio
    from database import db
    loop = asyncio.get_event_loop()
    before = _summary(client, owner_headers)

    loop.run_until_complete(db.transactions.insert_many([
        {"businessId": "default", "id": "AGG-T1", "total": 100.0, "gst": 9.09,
         "timestamp": datetime(2026, 1, 15, tzinfo=timezone.utc)},
        {"businessId": "default", "id": "AGG-T2", "total": 200.0, "gst": 18.18,
         "timestamp": datetime(2026, 2, 15, tzinfo=timezone.utc)},
    ]))
    loop.run_until_complete(db.expenses.insert_many([
        {"businessId": "default", "id": "AGG-E1", "amount": 40.0, "gstAmount": 4.0, "category": "Ingredients",
         "date": datetime(2026, 1, 20, tzinfo=timezone.utc)},
        {"businessId": "default", "id": "AGG-E2", "amount": 20.0, "gstAmount": 2.0, "category": "Rent",
         "date": datetime(2026, 2, 20, tzinfo=timezone.utc)},
    ]))

    after = _summary(client, owner_headers)
    assert round(after["revenue"] - before["revenue"], 2) == 300.0
    assert round(after["gstCollected"] - before["gstCollected"], 2) == 27.27
    assert round(after["expenses"] - before["expenses"], 2) == 60.0
    assert round(after["gstPaid"] - before["gstPaid"], 2) == 6.0
    assert round(after["profit"] - before["profit"], 2) == 240.0


def test_summary_respects_an_optional_date_range(client, owner_headers):
    import asyncio
    from database import db
    loop = asyncio.get_event_loop()
    before = _summary(client, owner_headers,
                      start_date="2026-03-01", end_date="2026-03-31")

    loop.run_until_complete(db.transactions.insert_many([
        {"businessId": "default", "id": "AGG-RNG-JAN", "total": 100.0, "gst": 0,
         "timestamp": datetime(2026, 1, 15, tzinfo=timezone.utc)},
        {"businessId": "default", "id": "AGG-RNG-MAR", "total": 500.0, "gst": 0,
         "timestamp": datetime(2026, 3, 15, tzinfo=timezone.utc)},
    ]))

    after = _summary(client, owner_headers,
                     start_date="2026-03-01", end_date="2026-03-31")
    assert round(after["revenue"] - before["revenue"], 2) == 500.0, \
        "March window should pick up the March row and skip the January one"


def test_pandl_splits_cogs_from_operating_expenses(client, owner_headers):
    import asyncio
    from database import db
    loop = asyncio.get_event_loop()
    before = _pandl(client, owner_headers,
                    start_date="2026-04-01", end_date="2026-04-30")

    loop.run_until_complete(db.transactions.insert_one(
        {"businessId": "default", "id": "AGG-PL-T", "total": 300.0, "gst": 0,
         "timestamp": datetime(2026, 4, 10, tzinfo=timezone.utc)}))
    loop.run_until_complete(db.expenses.insert_many([
        {"businessId": "default", "id": "AGG-PL-COGS", "amount": 40.0, "gstAmount": 0, "category": "Ingredients",
         "date": datetime(2026, 4, 12, tzinfo=timezone.utc)},
        {"businessId": "default", "id": "AGG-PL-OPEX", "amount": 20.0, "gstAmount": 0, "category": "Rent",
         "date": datetime(2026, 4, 12, tzinfo=timezone.utc)},
    ]))

    after = _pandl(client, owner_headers,
                   start_date="2026-04-01", end_date="2026-04-30")
    assert round(after["revenue"] - before["revenue"], 2) == 300.0
    assert round(after["costOfGoods"] - before["costOfGoods"], 2) == 40.0, \
        "Ingredients should count as COGS"
    assert round(after["operatingExpenses"] - before["operatingExpenses"], 2) == 20.0, \
        "Rent should count as operating, not COGS"
    assert round(after["grossProfit"] - before["grossProfit"], 2) == 260.0
    assert round(after["netProfit"] - before["netProfit"], 2) == 240.0


def test_pandl_with_no_transactions_does_not_divide_by_zero(client, owner_headers):
    r = req(client, "GET", "/api/accounting/p-and-l", headers=owner_headers,
            params={"start_date": "2099-01-01", "end_date": "2099-01-02"})
    assert r.status_code == 200
    assert r.json()["revenue"] == 0
    assert r.json()["grossMargin"] == 0
