"""A lost provider response must retry the same Stripe request identity."""
from functools import partial
from types import SimpleNamespace

import pytest

from database import db
from conftest import req
from services import payment_idempotency as claims


@pytest.mark.parametrize('order_id', [None, ''])
def test_lost_checkout_response_reuses_provider_key_and_metadata(client, owner_headers, monkeypatch, order_id):
    import stripe
    requests = []

    async def create(**kwargs):
        requests.append(kwargs)
        if len(requests) == 1:
            raise RuntimeError('simulated response lost after provider creation')
        return SimpleNamespace(id='cs_test_lost_reply', url='https://checkout.stripe.com/lost-reply')

    monkeypatch.setenv('STRIPE_API_KEY', 'test-only-retry-boundary')
    monkeypatch.setattr(stripe.checkout.Session, 'create_async', create)
    payload = {'originUrl': 'http://testserver', 'amount': 19.5, 'idempotencyKey': 'lost-provider-reply', 'orderId': order_id}
    try:
        assert req(client, 'POST', '/api/stripe/checkout', headers=owner_headers, json=payload).status_code == 500
        response = req(client, 'POST', '/api/stripe/checkout', headers=owner_headers, json=payload)
        assert response.status_code == 200, response.text
        assert len(requests) == 2 and requests[0] == requests[1]
        assert requests[0]['idempotency_key']
        assert response.json()['sessionId'] == 'cs_test_lost_reply'
    finally:
        client.portal.call(db.payment_session_claims.delete_many, {'key': {'$regex': ':lost-provider-reply$'}})
        client.portal.call(db.payment_transactions.delete_many, {'sessionId': 'cs_test_lost_reply'})


def test_provider_claim_generation_is_stable_scoped_and_rotates_after_expiry(client):
    async def verify():
        for key in ('business-a:generation', 'business-b:generation'):
            await claims.claim_or_wait('stripe', key, payload_fingerprint='same-cart')
        first = await claims.provider_request_key('stripe', 'business-a:generation')
        assert first == await claims.provider_request_key('stripe', 'business-a:generation')
        assert first != await claims.provider_request_key('stripe', 'business-b:generation')
        await db.payment_session_claims.update_one({'claimKey': 'stripe:business-a:generation'},
            {'$set': {'createdAt': '2000-01-01T00:00:00+00:00'}})
        assert await claims.claim_or_wait('stripe', 'business-a:generation', 'same-cart') is None
        assert first != await claims.provider_request_key('stripe', 'business-a:generation')

    try:
        client.portal.call(verify)
        with pytest.raises(claims.IdempotencyConflict):
            client.portal.call(partial(claims.provider_request_key, 'stripe', 'missing-claim'))
    finally:
        client.portal.call(db.payment_session_claims.delete_many, {'key': {'$in': ['business-a:generation', 'business-b:generation']}})
