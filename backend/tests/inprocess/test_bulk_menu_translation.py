"""The Customer Facing Display (and kiosk/QR/online menus) only ever shows a
guest's chosen language for a product that has a saved translations map —
and the only way to populate that map was the per-product Translate dialog,
one product and one language at a time. Nobody finishes that for a real
menu, so in practice the CFD kept falling back to English regardless of
language. POST /products/bulk-auto-translate exists to fix that in one
pass instead of per-product; these tests pin its actual behavior against a
mocked LLM call (no real network) rather than the wiring alone.
"""
import asyncio

from conftest import req


def test_bulk_translate_only_touches_products_missing_translations(monkeypatch):
    import routes.products
    from database import db

    calls = []

    async def fake_draft(name, description, session_suffix):
        calls.append(name)
        return {"it": {"name": f"{name} (IT)", "description": ""}}

    monkeypatch.setattr(routes.products, "_draft_translations_core", fake_draft)
    monkeypatch.setenv("EMERGENT_LLM_KEY", "fake-key-for-test")

    loop = asyncio.get_event_loop()
    loop.run_until_complete(db.products.insert_many([
        {"businessId": "default", "id": "BULKTR-1", "name": "Needs Translation", "description": "", "translations": {}},
        {"businessId": "default", "id": "BULKTR-2", "name": "Already Translated", "description": "",
         "translations": {"it": {"name": "Gia Tradotto", "description": ""}}},
    ]))
    try:
        # The mongomock DB is shared across the whole test session, so other
        # suites' seeded products (many with no translations field at all)
        # are also "missing translations" and get swept in here — assert on
        # our own two products' fates, not the global total, which is
        # unpredictable depending on test run order.
        result = loop.run_until_complete(
            routes.products.bulk_auto_translate_products(only_missing=True, user={"role": "owner", "businessId": "default"})
        )
        assert result["total"] >= 1
        assert "Needs Translation" in calls
        assert "Already Translated" not in calls, "must skip the product that already has translations"

        doc = loop.run_until_complete(db.products.find_one({"id": "BULKTR-1"}, {"_id": 0}))
        assert doc["translations"]["it"]["name"] == "Needs Translation (IT)"

        # The already-translated product must be untouched.
        doc2 = loop.run_until_complete(db.products.find_one({"id": "BULKTR-2"}, {"_id": 0}))
        assert doc2["translations"]["it"]["name"] == "Gia Tradotto"
    finally:
        loop.run_until_complete(db.products.delete_many({"id": {"$in": ["BULKTR-1", "BULKTR-2"]}}))


def test_bulk_translate_continues_past_a_single_product_failure(monkeypatch):
    import routes.products
    from database import db

    async def flaky_draft(name, description, session_suffix):
        if name == "Bad Product":
            raise ValueError("AI returned no usable translations")
        return {"it": {"name": f"{name} (IT)", "description": ""}}

    monkeypatch.setattr(routes.products, "_draft_translations_core", flaky_draft)
    monkeypatch.setenv("EMERGENT_LLM_KEY", "fake-key-for-test")

    loop = asyncio.get_event_loop()
    loop.run_until_complete(db.products.insert_many([
        {"businessId": "default", "id": "BULKTR-3", "name": "Bad Product", "description": "", "translations": {}},
        {"businessId": "default", "id": "BULKTR-4", "name": "Good Product", "description": "", "translations": {}},
    ]))
    try:
        # Same shared-DB caveat as the test above — assert on our own two
        # products, not on global totals that depend on what else is in the
        # (session-shared) mongomock collection.
        result = loop.run_until_complete(
            routes.products.bulk_auto_translate_products(only_missing=True, user={"role": "owner", "businessId": "default"})
        )
        assert result["failed"] >= 1, "one product failing must still be counted, not silently dropped"

        good = loop.run_until_complete(db.products.find_one({"id": "BULKTR-4"}, {"_id": 0}))
        assert good["translations"]["it"]["name"] == "Good Product (IT)"
        bad = loop.run_until_complete(db.products.find_one({"id": "BULKTR-3"}, {"_id": 0}))
        assert bad["translations"] == {}, "a failed draft must not overwrite the product with a partial/bad result"
    finally:
        loop.run_until_complete(db.products.delete_many({"id": {"$in": ["BULKTR-3", "BULKTR-4"]}}))


def test_bulk_translate_requires_owner_or_manager(client, owner_headers):
    r = req(client, "POST", "/api/products/bulk-auto-translate", headers=owner_headers)
    # Owner is allowed through the auth dependency — with no EMERGENT_LLM_KEY
    # configured in this test environment it should fail cleanly (503), not
    # crash or silently no-op.
    assert r.status_code in (200, 503), r.text[:200]

    anon_r = client.post("/api/products/bulk-auto-translate")
    assert anon_r.status_code in (401, 403), "must not be reachable without a staff credential"
