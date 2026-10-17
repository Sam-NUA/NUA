"""Guard tenant-owned references and immutable ownership at the write boundary."""
from conftest import req


def test_event_update_cannot_move_or_replace_event_identity(client, owner_headers):
    from database import db
    business = req(client, 'GET', '/api/auth/me', headers=owner_headers).json()['businessId']
    event = req(client, 'POST', '/api/events', headers=owner_headers,
        json={'name': 'Launch event', 'date': '2026-12-01', 'time': '18:00'}).json()
    try:
        response = req(client, 'PUT', f"/api/events/{event['id']}", headers=owner_headers,
            json={'name': 'Renamed', 'businessId': 'FOREIGN-LAUNCH-EVENT', 'id': 'replacement', 'ticketsBooked': 999})
        assert response.status_code == 200
        stored = client.portal.call(db.events.find_one, {'id': event['id']})
        assert stored['businessId'] == business and stored['name'] == 'Renamed'
        assert stored['ticketsBooked'] == 0
        assert client.portal.call(db.events.find_one, {'id': 'replacement'}) is None
    finally:
        client.portal.call(db.events.delete_one, {'id': event['id'], 'businessId': business})


def test_roster_rejects_foreign_and_missing_staff_on_create_and_reassignment(client, owner_headers):
    from database import db
    owner = req(client, 'GET', '/api/auth/me', headers=owner_headers).json()
    foreign_id = 'TEST-FOREIGN-ROSTER-USER'
    client.portal.call(db.auth_users.insert_one, {'id': foreign_id, 'businessId': 'FOREIGN-ROSTER-BIZ', 'name': 'Foreign'})
    shift = None
    try:
        for staff_id in [foreign_id, 'TEST-NONEXISTENT-ROSTER-USER']:
            response = req(client, 'POST', '/api/staff/roster', headers=owner_headers,
                json={'staffId': staff_id, 'date': '2026-12-01'})
            assert response.status_code == 404
            assert client.portal.call(db.roster_shifts.find_one, {'staffId': staff_id}) is None
        response = req(client, 'POST', '/api/staff/roster', headers=owner_headers,
            json={'staffId': owner['id'], 'staffName': owner['name'], 'date': '2026-12-01'})
        assert response.status_code == 200, response.text
        shift = response.json()
        denied = req(client, 'PUT', f"/api/staff/roster/{shift['id']}", headers=owner_headers,
            json={'staffId': foreign_id})
        assert denied.status_code == 404
        stored = client.portal.call(db.roster_shifts.find_one, {'id': shift['id']})
        assert stored['staffId'] == owner['id'] and stored['businessId'] == owner['businessId']
    finally:
        client.portal.call(db.auth_users.delete_one, {'id': foreign_id})
        if shift:
            client.portal.call(db.roster_shifts.delete_one, {'id': shift['id'], 'businessId': owner['businessId']})


def test_event_ticket_claims_cannot_be_negative_or_oversell_capacity(client, owner_headers):
    from concurrent.futures import ThreadPoolExecutor
    from database import db
    event = req(client, 'POST', '/api/events', headers=owner_headers,
        json={'name': 'Capacity test', 'date': '2026-12-01', 'time': '18:00', 'capacity': 1}).json()
    path = f"/api/events/{event['id']}/book"
    try:
        for quantity in [0, -1]:
            response = req(client, 'POST', path, headers=owner_headers, params={'quantity': quantity})
            assert response.status_code == 400
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: req(client, 'POST', path, headers=owner_headers), range(2)))
        assert sorted(response.status_code for response in responses) == [200, 400]
        stored = client.portal.call(db.events.find_one, {'id': event['id']})
        assert stored['ticketsBooked'] == 1
    finally:
        client.portal.call(db.events.delete_one, {'id': event['id']})


def test_loyalty_ledger_and_fraud_action_are_scoped_even_with_foreign_references(client, owner_headers):
    from database import db
    business = req(client, 'GET', '/api/auth/me', headers=owner_headers).json()['businessId']
    customer_id = 'launch-ledger-customer'
    client.portal.call(db.customers.insert_one, {'id': customer_id, 'businessId': business, 'name': 'Owned', 'points': 0})
    client.portal.call(db.loyalty_ledger.insert_one, {'id': 'launch-foreign-ledger', 'businessId': 'FOREIGN',
        'customerId': customer_id, 'transactionId': 'launch-collision', 'type': 'earn', 'points': 999})
    client.portal.call(db.vouchers.insert_one, {'id': 'launch-foreign-voucher', 'businessId': 'FOREIGN', 'status': 'active'})
    client.portal.call(db.loyalty_fraud_flags.insert_one, {'id': 'launch-owned-flag', 'businessId': business,
        'type': 'voucher_sharing', 'status': 'open', 'voucherId': 'launch-foreign-voucher'})
    try:
        ledger = req(client, 'GET', f'/api/loyalty/ledger/{customer_id}', headers=owner_headers)
        assert ledger.status_code == 200 and ledger.json() == []
        earned = req(client, 'POST', '/api/loyalty/earn', headers=owner_headers,
            json={'customerId': customer_id, 'transactionId': 'launch-collision',
                  'items': [{'quantity': 1, 'price': 5, 'category': 'Coffee'}]})
        assert earned.status_code == 200 and earned.json()['earned'] == 5
        denied = req(client, 'PUT', '/api/loyalty/reports/fraud-flags/launch-owned-flag',
            headers=owner_headers, json={'status': 'confirmed_abuse'})
        assert denied.status_code == 404
        assert client.portal.call(db.vouchers.find_one, {'id': 'launch-foreign-voucher'})['status'] == 'active'
        assert client.portal.call(db.loyalty_fraud_flags.find_one, {'id': 'launch-owned-flag'})['status'] == 'open'
    finally:
        client.portal.call(db.customers.delete_many, {'id': customer_id})
        client.portal.call(db.loyalty_ledger.delete_many, {'customerId': customer_id})
        client.portal.call(db.vouchers.delete_one, {'id': 'launch-foreign-voucher'})
        client.portal.call(db.loyalty_fraud_flags.delete_one, {'id': 'launch-owned-flag'})


def test_customer_erasure_cannot_redact_another_business_feedback(client, owner_headers):
    from database import db
    business = req(client, 'GET', '/api/auth/me', headers=owner_headers).json()['businessId']
    customer_id = 'launch-gdpr-customer'
    client.portal.call(db.customers.insert_one, {'id': customer_id, 'businessId': business, 'name': 'Owned'})
    for tenant in (business, 'FOREIGN-GDPR'):
        client.portal.call(db.feedback.insert_one, {'id': f'launch-feedback-{tenant}', 'businessId': tenant,
            'customerId': customer_id, 'customerName': 'Keep private'})
    try:
        response = req(client, 'DELETE', f'/api/customers/{customer_id}/gdpr-erase', headers=owner_headers)
        assert response.status_code == 200, response.text
        assert client.portal.call(db.feedback.find_one, {'id': f'launch-feedback-{business}'})['customerName'] == '[REDACTED]'
        assert client.portal.call(db.feedback.find_one, {'id': 'launch-feedback-FOREIGN-GDPR'})['customerName'] == 'Keep private'
    finally:
        client.portal.call(db.customers.delete_one, {'id': customer_id, 'businessId': business})
        client.portal.call(db.feedback.delete_many, {'customerId': customer_id})
