"""Missing legacy stock counters must not crash or leak another venue's inventory."""
from conftest import req


def test_low_stock_handles_missing_counters_and_keeps_tenant_scope(client, owner_headers):
    from database import db
    business = req(client, 'GET', '/api/auth/me', headers=owner_headers).json()['businessId']
    prefix = 'TEST-LEGACY-LOW-'
    rows = [
        {'id': prefix+'missing-stock', 'businessId': business, 'reorderLevel': 3},
        {'id': prefix+'null-stock', 'businessId': business, 'stock': None, 'reorderLevel': 3},
        {'id': prefix+'no-threshold', 'businessId': business},
        {'id': prefix+'sufficient', 'businessId': business, 'stock': 5, 'reorderLevel': 3},
        {'id': prefix+'foreign', 'businessId': 'FOREIGN-LOW-STOCK', 'stock': 0, 'reorderLevel': 3},
    ]
    try:
        client.portal.call(db.ingredients.insert_many, rows)
        result = req(client, 'GET', '/api/ingredients/low-stock', headers=owner_headers)
        assert result.status_code == 200, result.text
        returned = {item['id'] for item in result.json() if item['id'].startswith(prefix)}
        assert returned == {prefix+'missing-stock', prefix+'null-stock'}
    finally:
        client.portal.call(db.ingredients.delete_many, {'id': {'$in': [row['id'] for row in rows]}})
