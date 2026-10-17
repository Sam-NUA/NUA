"""Directive Phase 11 — application versioning.

GET /api/version is the client-friendly way to ask "am I out of date";
VersionGateMiddleware (middleware/version_middleware.py) is the actual
server-side enforcement. The two must agree, and the enforcement must
never trip on the overwhelming majority of real traffic today — no
existing web/Android/iOS/Windows build sends X-App-Version yet.
"""
from conftest import req
import version as app_version


def test_version_endpoint_is_public_and_reports_the_real_constants(anon):
    r = req(anon, "GET", "/api/version")
    assert r.status_code == 200
    body = r.json()
    assert body["appVersion"] == app_version.APP_VERSION
    assert body["apiVersion"] == app_version.API_VERSION
    assert body["minSupportedVersion"] == app_version.MIN_SUPPORTED_APP_VERSION


def test_no_version_header_is_never_blocked(anon):
    # Every real client in production today sends no X-App-Version header
    # at all — this must keep working exactly as before.
    assert req(anon, "GET", "/api/business/theme").status_code == 200


def test_current_and_newer_client_version_is_allowed(anon):
    ok = req(anon, "GET", "/api/business/theme", headers={"X-App-Version": app_version.MIN_SUPPORTED_APP_VERSION})
    assert ok.status_code == 200
    newer = req(anon, "GET", "/api/business/theme", headers={"X-App-Version": "99.0.0"})
    assert newer.status_code == 200


def test_old_client_version_is_rejected_with_upgrade_required(anon):
    r = req(anon, "GET", "/api/business/theme", headers={"X-App-Version": "0.0.1"})
    assert r.status_code == 426
    assert r.json()["minSupportedVersion"] == app_version.MIN_SUPPORTED_APP_VERSION


def test_garbled_version_header_is_treated_as_too_old_not_a_server_error(anon):
    r = req(anon, "GET", "/api/business/theme", headers={"X-App-Version": "not-a-version"})
    assert r.status_code == 426


def test_health_and_healthz_stay_exempt_so_load_balancers_are_never_gated(anon):
    # Deliberately exempt — see version_middleware.py's own comment.
    assert req(anon, "GET", "/api/health", headers={"X-App-Version": "0.0.1"}).status_code == 200
    assert req(anon, "GET", "/api/healthz", headers={"X-App-Version": "0.0.1"}).status_code == 200


def test_version_endpoint_itself_is_reachable_even_by_a_too_old_client(anon):
    # The whole point of /api/version: a client that's already out of date
    # must still be able to ask what it should update to, not get 426 on
    # the one call that would tell it that.
    r = req(anon, "GET", "/api/version", headers={"X-App-Version": "0.0.1"})
    assert r.status_code == 200
