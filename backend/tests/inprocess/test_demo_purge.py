"""Smoke test for POST /api/business/purge-demo-data.

Confirms the seeders tag their rows isDemo=True, the purge endpoint deletes
exactly those rows, requires the confirm token, and leaves non-demo data
(admin user, default business) untouched.
"""
from conftest import req


def test_purge_demo_data(client, owner_headers):
    from database import db
    import asyncio

    async def seed():
        from seeds.seed_customers import seed_demo_customers
        from services.alcohol_seeder import seed_alcohol_catalog
        await seed_demo_customers()
        await seed_alcohol_catalog(business_id="default")

    asyncio.get_event_loop().run_until_complete(seed())

    async def counts():
        return {
            "customers": await db.customers.count_documents({"isDemo": True}),
            "products": await db.products.count_documents({"isDemo": True}),
            "categories": await db.categories.count_documents({"isDemo": True}),
        }

    before = asyncio.get_event_loop().run_until_complete(counts())
    assert before["customers"] == 5
    assert before["products"] > 0
    assert before["categories"] > 0

    # Missing confirm token -> rejected, nothing deleted.
    r = req(client, "POST", "/api/business/purge-demo-data", json={}, headers=owner_headers)
    assert r.status_code == 400, r.text

    r = req(client, "POST", "/api/business/purge-demo-data", json={"confirm": "PURGE"}, headers=owner_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["purged"]["customers"] == 5
    assert body["purged"]["products"] == before["products"]
    assert body["purged"]["categories"] == before["categories"]

    after = asyncio.get_event_loop().run_until_complete(counts())
    assert after == {"customers": 0, "products": 0, "categories": 0}

    async def admin_and_business_intact():
        admin = await db.auth_users.find_one({"email": "owner@nua.com"})
        biz = await db.businesses.find_one({"id": "default"})
        return admin is not None, biz is not None

    admin_ok, biz_ok = asyncio.get_event_loop().run_until_complete(admin_and_business_intact())
    assert admin_ok and biz_ok
