"""An offline context header restricts the verified actor; it never selects a tenant."""
from tests.inprocess.conftest import req


def test_offline_business_header_cannot_select_another_tenant(client, owner_headers):
    me = req(client, "GET", "/api/auth/me", headers=owner_headers)
    assert me.status_code == 200
    business = me.json()["businessId"]
    wrong = req(client, "GET", "/api/products", headers={**owner_headers, "X-Offline-Business-Id": "foreign-business"})
    assert wrong.status_code == 403
    own = req(client, "GET", "/api/products", headers={**owner_headers, "X-Offline-Business-Id": business})
    assert own.status_code == 200


def test_offline_business_header_does_not_authenticate_an_anonymous_request(anon):
    result = req(anon, "GET", "/api/products", headers={"X-Offline-Business-Id": "claimed-business"})
    assert result.status_code in (401, 403)
