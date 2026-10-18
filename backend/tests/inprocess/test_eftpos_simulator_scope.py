"""Merchant-entered terminal labels cannot identify a tenant ledger."""
import pytest

from services.eftpos_service import SimulatorProvider, eftpos_service


@pytest.mark.parametrize('other_business,other_id', [
    ('simulator-venue-b', 'simulator-record-a'),
    ('simulator-venue-a', 'simulator-record-b'),
])
def test_refund_cannot_use_another_scoped_terminal_purchase(client, monkeypatch, other_business, other_id):
    monkeypatch.setattr(SimulatorProvider, '_ledgers', {})
    original = {'provider': 'simulator', 'businessId': 'simulator-venue-a',
                'id': 'simulator-record-a', 'terminalId': 'SHARED-MERCHANT-LABEL'}
    other = {**original, 'businessId': other_business, 'id': other_id}
    purchase = client.portal.call(eftpos_service.process_transaction, original, 'purchase', 25.0, 'SHARED-REF')
    assert purchase['approved'] is True

    denied = client.portal.call(eftpos_service.process_transaction, other, 'refund', 25.0, 'SHARED-REF')
    assert denied['approved'] is False
    assert denied['responseCode'] == '78'

    # A new provider instance for the original tenant/config must retain its ledger.
    refund = client.portal.call(eftpos_service.process_transaction, original, 'refund', 25.0, 'SHARED-REF')
    assert refund['approved'] is True


@pytest.mark.parametrize('missing', ['businessId', 'id'])
def test_simulator_refuses_missing_scoped_identity(missing):
    config = {'provider': 'simulator', 'businessId': 'simulator-venue-a',
              'id': 'simulator-record-a', 'terminalId': 'SHARED-MERCHANT-LABEL'}
    del config[missing]
    with pytest.raises(ValueError, match='scoped terminal identity'):
        SimulatorProvider(config)
