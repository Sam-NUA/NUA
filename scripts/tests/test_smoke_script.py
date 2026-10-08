import importlib.util
from pathlib import Path
from types import SimpleNamespace

import requests


def load_script(monkeypatch):
    spec = importlib.util.spec_from_file_location('live_smoke', Path(__file__).parents[1] / 'smoke_test_live_edge.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'BASE_URL', 'https://staging.invalid')
    monkeypatch.setattr(module, 'OWNER_PASSWORD', 'unit-test-only')
    monkeypatch.setattr(module, 'MONGO_URL', '')
    monkeypatch.setattr(module, 'DB_NAME', '')
    monkeypatch.setattr(module.sys, 'argv', ['smoke'])
    return module


def response(body):
    return SimpleNamespace(status_code=200, json=lambda: body, headers={'Content-Type': 'application/json'})


def test_timeout_after_account_creation_still_cleans_up(monkeypatch):
    module = load_script(monkeypatch)
    deleted = []
    def api(method, path, **kwargs):
        if path == '/api/health':
            return response({})
        if path == '/api/auth/login':
            return response({'token': 'unit-token', 'user': {'businessId': 'unit-business'}})
        if path == '/api/auth/staff/add':
            return response({'id': 'temporary-staff'})
        if path == '/api/auth/register':
            raise requests.Timeout()
        if method == 'DELETE':
            deleted.append(path)
            return response({})
        raise AssertionError('Unexpected request')
    monkeypatch.setattr(module, 'api', api)
    assert module.main() == 1
    assert deleted == ['/api/auth/staff/temporary-staff']


def test_login_html_is_not_successful_readiness(monkeypatch):
    module = load_script(monkeypatch)
    monkeypatch.setattr(module.sys, 'argv', ['smoke', '--health-only'])
    monkeypatch.setattr(module, 'api', lambda *a, **kw: SimpleNamespace(status_code=200, headers={'Content-Type': 'text/html'}))
    assert module.main() == 1
    assert len(module.FAILURES) == 3
