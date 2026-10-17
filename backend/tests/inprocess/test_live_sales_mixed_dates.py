"""Live sales accept legacy ISO and BSON dates without inventing today's revenue."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from conftest import req


def test_live_sales_use_venue_day_and_normalized_dates_with_strict_tenant_scope(client, owner_headers, monkeypatch):
    from database import db
    from services import venue_time
    business = req(client, 'GET', '/api/auth/me', headers=owner_headers).json()['businessId']

    async def zone(business_id):
        assert business_id == business
        return 'Australia/Sydney'

    monkeypatch.setattr(venue_time, 'business_timezone', zone)
    day = datetime.now(ZoneInfo('Australia/Sydney')).replace(hour=0, minute=0, second=0, microsecond=0)
    early = day + timedelta(minutes=30)
    late = day + timedelta(hours=14)
    backup = client.portal.call(db.transactions.find({'businessId': business}).to_list, 50000)
    client.portal.call(db.transactions.delete_many, {'businessId': business})
    foreign_id = 'TEST-LIVE-SALES-FOREIGN'
    try:
        client.portal.call(db.transactions.insert_many, [
            {'id': 'early-string', 'businessId': business, 'total': 5, 'timestamp': early.astimezone(timezone.utc).isoformat()},
            {'id': 'late-bson', 'businessId': business, 'total': 10, 'timestamp': late.astimezone(timezone.utc).replace(tzinfo=None)},
            {'id': 'old', 'businessId': business, 'total': 100, 'timestamp': (day-timedelta(days=1)).isoformat()},
            {'id': 'tomorrow', 'businessId': business, 'total': 200, 'timestamp': (day+timedelta(days=1)).isoformat()},
            {'id': 'invalid', 'businessId': business, 'total': 300, 'timestamp': 'not-a-date'},
            {'id': foreign_id, 'businessId': 'FOREIGN-LIVE-SALES', 'total': 400, 'timestamp': late.isoformat()},
        ])
        response = req(client, 'GET', '/api/live-sales', headers=owner_headers)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data['totalSales'] == 15 and data['transactionCount'] == 2
        assert data['avgTicket'] == 7.5
        assert data['byHour'] == [{'hour': 0, 'count': 1, 'total': 5}, {'hour': 14, 'count': 1, 'total': 10}]
        assert [row['id'] for row in data['recentTransactions']] == ['late-bson', 'early-string']
        client.portal.call(db.transactions.delete_many, {'businessId': business, 'id': {'$in': ['early-string', 'late-bson']}})
        empty_today = req(client, 'GET', '/api/live-sales', headers=owner_headers).json()
        assert empty_today['totalSales'] == 0 and empty_today['transactionCount'] == 0
        assert empty_today['recentTransactions'] == []
    finally:
        client.portal.call(db.transactions.delete_many, {'businessId': business})
        client.portal.call(db.transactions.delete_many, {'id': foreign_id})
        if backup:
            client.portal.call(db.transactions.insert_many, backup)
