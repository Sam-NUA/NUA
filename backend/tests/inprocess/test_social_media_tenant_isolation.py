"""routes/social_media.py had zero businessId scoping across social
account connections, posts, and AI weekly-plan jobs. Any business could
list, edit, delete, or "publish" any other business's draft/scheduled
social media posts (brand/reputation risk), and connected-account/
promotion/product data leaked cross-tenant into AI-generated captions
and weekly plans.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Social Media Test Owner", "email": email, "password": "SocialMediaTenantTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "SocialMediaTenantTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def test_social_accounts_are_scoped_per_business(client, owner_headers):
    other = _login_as(client, owner_headers, email="social.accounts.other@nua.com", business_id="social-accounts-other-biz")

    connected = req(client, "POST", "/api/social/accounts", headers=other, json={
        "platform": "instagram", "handle": "other_biz_secret_handle"})
    assert connected.status_code == 200, connected.text[:200]
    account_id = connected.json()["id"]
    try:
        mine = req(client, "GET", "/api/social/accounts", headers=owner_headers).json()
        assert not any(a["id"] == account_id for a in mine)

        disconnect_mine = req(client, "DELETE", f"/api/social/accounts/{account_id}", headers=owner_headers)
        assert disconnect_mine.status_code == 404

        still_there = req(client, "GET", "/api/social/accounts", headers=other).json()
        assert any(a["id"] == account_id for a in still_there)
    finally:
        _run(db.social_accounts.delete_one({"id": account_id}))


def test_social_posts_are_not_visible_or_actionable_across_businesses(client, owner_headers):
    other = _login_as(client, owner_headers, email="social.posts.other@nua.com", business_id="social-posts-other-biz")

    req(client, "POST", "/api/social/accounts", headers=other, json={
        "platform": "instagram", "handle": "other_biz_handle_2"})
    created = req(client, "POST", "/api/social/posts", headers=other, json={
        "platform": "instagram", "postType": "post", "caption": "Other business's secret campaign",
        "hashtags": ["#secret"], "status": "draft"})
    assert created.status_code == 200, created.text[:200]
    post_id = created.json()["id"]
    try:
        mine = req(client, "GET", "/api/social/posts", headers=owner_headers).json()
        assert not any(p["id"] == post_id for p in mine)

        update_mine = req(client, "PATCH", f"/api/social/posts/{post_id}", headers=owner_headers, json={"caption": "hijacked"})
        assert update_mine.status_code == 404

        publish_mine = req(client, "POST", f"/api/social/posts/{post_id}/publish", headers=owner_headers)
        assert publish_mine.status_code == 404

        delete_mine = req(client, "DELETE", f"/api/social/posts/{post_id}", headers=owner_headers)
        assert delete_mine.status_code == 404

        duplicate_mine = req(client, "POST", f"/api/social/posts/{post_id}/duplicate", headers=owner_headers, json={})
        assert duplicate_mine.status_code == 404

        still_theirs = req(client, "GET", "/api/social/posts", headers=other).json()
        found = next(p for p in still_theirs if p["id"] == post_id)
        assert found["caption"] == "Other business's secret campaign", "cross-tenant attempts must not have mutated it"
        assert found["status"] == "draft", "must not have been published by a different business"
    finally:
        _run(db.social_posts.delete_one({"id": post_id}))
        _run(db.social_accounts.delete_many({"businessId": "social-posts-other-biz"}))
