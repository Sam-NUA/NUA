"""routes/items_system.py (categories, modifiers, discounts, comp/void,
payment links) had ZERO tenant scoping anywhere — missed by every prior
tenant-isolation sweep. Found during a second independent final readiness
audit, commissioned specifically to check the results of the first one.

- GET /modifiers, GET /discounts, GET /payment-links had no auth
  dependency and no scoping at all: `db.<collection>.find({}, ...)`
  returned every business's full catalog to any authenticated caller.
- PUT/DELETE on a category/modifier/discount/payment-link, and
  POST /categories/{source}/merge/{target}, were gated only by
  require_owner/require_owner_or_manager (a role check, not an ownership
  check) — any owner/manager of ANY business could edit, delete, or merge
  any OTHER business's menu configuration by id.
- merge_categories's `db.products.update_many` had no businessId filter at
  all, so a merge could re-categorize every business's products sharing
  the same category name, not just the caller's own.
- create_modifier/create_discount/create_payment_link/create_comp_void
  never stamped a businessId on the new document at all.

Fixed with the same tenant_owns()/tenant_scope_filter() pattern used
throughout this codebase's other tenant-isolation fixes.
"""
import asyncio

from conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_business(client, owner_headers, *, biz_id, email):
    from database import db
    _run(db.businesses.insert_one({
        "id": biz_id, "slug": biz_id, "name": f"Biz {biz_id}", "status": "active",
    }))
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Items System Test Owner", "email": email, "password": "ItemsSystemTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": biz_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "ItemsSystemTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _cleanup_business(biz_id):
    from database import db
    _run(db.businesses.delete_many({"id": biz_id}))
    _run(db.auth_users.delete_many({"businessId": biz_id}))


# --------------------------------------------------------------- categories


def test_update_category_rejects_another_businesss_category(client, owner_headers):
    biz_b = "items-tenant-biz-cat-upd"
    try:
        biz_b_headers = _make_business(client, owner_headers, biz_id=biz_b, email="items-cat-upd-b@nua.com")
        created = req(client, "POST", "/api/categories", headers=biz_b_headers, json={"name": "B's Category"})
        assert created.status_code == 200, created.text[:200]
        cat_id = created.json()["id"]

        default_tenant = dict(owner_headers, **{"X-Tenant-Id": "default"})
        r = req(client, "PUT", f"/api/categories/{cat_id}", headers=default_tenant, json={"name": "Hijacked"})
        assert r.status_code == 404, r.text
    finally:
        _cleanup_business(biz_b)


def test_delete_category_rejects_another_businesss_category(client, owner_headers):
    biz_b = "items-tenant-biz-cat-del"
    try:
        biz_b_headers = _make_business(client, owner_headers, biz_id=biz_b, email="items-cat-del-b@nua.com")
        created = req(client, "POST", "/api/categories", headers=biz_b_headers, json={"name": "B's Category 2"})
        cat_id = created.json()["id"]

        default_tenant = dict(owner_headers, **{"X-Tenant-Id": "default"})
        r = req(client, "DELETE", f"/api/categories/{cat_id}", headers=default_tenant)
        assert r.status_code == 404, r.text

        from database import db
        still_there = _run(db.categories.find_one({"id": cat_id}))
        assert still_there is not None, "a rejected cross-tenant delete must not remove the category"
    finally:
        _cleanup_business(biz_b)


def test_merge_categories_rejects_a_target_belonging_to_another_business(client, owner_headers):
    biz_b = "items-tenant-biz-cat-merge"
    try:
        biz_b_headers = _make_business(client, owner_headers, biz_id=biz_b, email="items-cat-merge-b@nua.com")
        default_tenant = dict(owner_headers, **{"X-Tenant-Id": "default"})

        own_cat = req(client, "POST", "/api/categories", headers=default_tenant, json={"name": "Own Source Cat"})
        own_cat_id = own_cat.json()["id"]
        other_cat = req(client, "POST", "/api/categories", headers=biz_b_headers, json={"name": "B's Target Cat"})
        other_cat_id = other_cat.json()["id"]

        r = req(client, "POST", f"/api/categories/{own_cat_id}/merge/{other_cat_id}", headers=default_tenant)
        assert r.status_code == 404, r.text

        from database import db
        still_there = _run(db.categories.find_one({"id": own_cat_id}))
        assert still_there is not None, "a rejected cross-tenant merge must not delete the caller's own source category"
    finally:
        _cleanup_business(biz_b)


def test_merge_categories_does_not_recategorize_another_businesss_products(client, owner_headers):
    """The real exploit: merge_categories's products.update_many had no
    businessId filter, so merging two SAME-NAMED categories (a very common
    case — most businesses start from the same seeded/default catalog)
    could silently re-tag every other business's matching products too."""
    biz_b = "items-tenant-biz-cat-prodmerge"
    try:
        biz_b_headers = _make_business(client, owner_headers, biz_id=biz_b, email="items-cat-prodmerge-b@nua.com")
        default_tenant = dict(owner_headers, **{"X-Tenant-Id": "default"})

        # Both businesses create a same-named category (collision on purpose).
        own_source = req(client, "POST", "/api/categories", headers=default_tenant, json={"name": "Shared Name Src"})
        own_target = req(client, "POST", "/api/categories", headers=default_tenant, json={"name": "Shared Name Tgt"})
        own_source_id, own_target_id = own_source.json()["id"], own_target.json()["id"]

        from database import db
        _run(db.products.insert_one({
            "id": "ITEMS-TENANT-PROD-B1", "name": "B's Product", "price": 5.0,
            "category": "Shared Name Src", "categoryId": None, "businessId": biz_b,
        }))

        r = req(client, "POST", f"/api/categories/{own_source_id}/merge/{own_target_id}", headers=default_tenant)
        assert r.status_code == 200, r.text

        b_product = _run(db.products.find_one({"id": "ITEMS-TENANT-PROD-B1"}, {"_id": 0}))
        assert b_product["category"] == "Shared Name Src", (
            "another business's product sharing the same category NAME must not be recategorized "
            "by the caller's own merge"
        )
    finally:
        _run(__import__("database").db.products.delete_many({"id": "ITEMS-TENANT-PROD-B1"}))
        _cleanup_business(biz_b)


# ---------------------------------------------------------------- modifiers


def test_get_modifiers_never_returns_another_businesss_modifier(client, owner_headers):
    biz_b = "items-tenant-biz-mod-list"
    try:
        biz_b_headers = _make_business(client, owner_headers, biz_id=biz_b, email="items-mod-list-b@nua.com")
        created = req(client, "POST", "/api/modifiers", headers=biz_b_headers, json={"name": "B's Secret Modifier"})
        assert created.status_code == 200, created.text[:200]

        default_tenant = dict(owner_headers, **{"X-Tenant-Id": "default"})
        r = req(client, "GET", "/api/modifiers", headers=default_tenant)
        assert r.status_code == 200, r.text
        names = [m.get("name") for m in r.json()]
        assert "B's Secret Modifier" not in names
    finally:
        _cleanup_business(biz_b)


def test_update_and_delete_modifier_reject_another_businesss_modifier(client, owner_headers):
    biz_b = "items-tenant-biz-mod-mut"
    try:
        biz_b_headers = _make_business(client, owner_headers, biz_id=biz_b, email="items-mod-mut-b@nua.com")
        created = req(client, "POST", "/api/modifiers", headers=biz_b_headers, json={"name": "B's Modifier"})
        mod_id = created.json()["id"]

        default_tenant = dict(owner_headers, **{"X-Tenant-Id": "default"})
        r1 = req(client, "PUT", f"/api/modifiers/{mod_id}", headers=default_tenant, json={"name": "Hijacked"})
        assert r1.status_code == 404, r1.text
        r2 = req(client, "DELETE", f"/api/modifiers/{mod_id}", headers=default_tenant)
        assert r2.status_code == 404, r2.text

        from database import db
        still_there = _run(db.modifiers.find_one({"id": mod_id}))
        assert still_there is not None and still_there["name"] == "B's Modifier"
    finally:
        _cleanup_business(biz_b)


# ---------------------------------------------------------------- discounts


def test_get_discounts_never_returns_another_businesss_discount(client, owner_headers):
    biz_b = "items-tenant-biz-disc-list"
    try:
        biz_b_headers = _make_business(client, owner_headers, biz_id=biz_b, email="items-disc-list-b@nua.com")
        created = req(client, "POST", "/api/discounts", headers=biz_b_headers, json={"name": "B's Secret Discount"})
        assert created.status_code == 200, created.text[:200]

        default_tenant = dict(owner_headers, **{"X-Tenant-Id": "default"})
        r = req(client, "GET", "/api/discounts", headers=default_tenant)
        assert r.status_code == 200, r.text
        names = [d.get("name") for d in r.json()]
        assert "B's Secret Discount" not in names
    finally:
        _cleanup_business(biz_b)


def test_update_and_delete_discount_reject_another_businesss_discount(client, owner_headers):
    biz_b = "items-tenant-biz-disc-mut"
    try:
        biz_b_headers = _make_business(client, owner_headers, biz_id=biz_b, email="items-disc-mut-b@nua.com")
        created = req(client, "POST", "/api/discounts", headers=biz_b_headers, json={"name": "B's Discount"})
        disc_id = created.json()["id"]

        default_tenant = dict(owner_headers, **{"X-Tenant-Id": "default"})
        r1 = req(client, "PUT", f"/api/discounts/{disc_id}", headers=default_tenant, json={"name": "Hijacked"})
        assert r1.status_code == 404, r1.text
        r2 = req(client, "DELETE", f"/api/discounts/{disc_id}", headers=default_tenant)
        assert r2.status_code == 404, r2.text
    finally:
        _cleanup_business(biz_b)


# ------------------------------------------------------------- payment links


def test_get_payment_links_never_returns_another_businesss_link(client, owner_headers):
    biz_b = "items-tenant-biz-plink-list"
    try:
        biz_b_headers = _make_business(client, owner_headers, biz_id=biz_b, email="items-plink-list-b@nua.com")
        created = req(client, "POST", "/api/payment-links", headers=biz_b_headers, json={"productName": "B's Product"})
        assert created.status_code == 200, created.text[:200]

        default_tenant = dict(owner_headers, **{"X-Tenant-Id": "default"})
        r = req(client, "GET", "/api/payment-links", headers=default_tenant)
        assert r.status_code == 200, r.text
        names = [p.get("productName") for p in r.json()]
        assert "B's Product" not in names
    finally:
        _cleanup_business(biz_b)


def test_delete_payment_link_rejects_another_businesss_link(client, owner_headers):
    biz_b = "items-tenant-biz-plink-del"
    try:
        biz_b_headers = _make_business(client, owner_headers, biz_id=biz_b, email="items-plink-del-b@nua.com")
        created = req(client, "POST", "/api/payment-links", headers=biz_b_headers, json={"productName": "B's Item"})
        link_id = created.json()["id"]

        default_tenant = dict(owner_headers, **{"X-Tenant-Id": "default"})
        r = req(client, "DELETE", f"/api/payment-links/{link_id}", headers=default_tenant)
        assert r.status_code == 404, r.text
    finally:
        _cleanup_business(biz_b)


# ------------------------------------------------------------------ comp/void


def test_get_comp_voids_never_returns_another_businesss_record(client, owner_headers):
    biz_b = "items-tenant-biz-cv-list"
    try:
        biz_b_headers = _make_business(client, owner_headers, biz_id=biz_b, email="items-cv-list-b@nua.com")
        created = req(client, "POST", "/api/comp-void", headers=biz_b_headers, json={
            "type": "comp", "reason": "B's secret comp reason", "amount": 5})
        assert created.status_code == 200, created.text[:200]

        default_tenant = dict(owner_headers, **{"X-Tenant-Id": "default"})
        r = req(client, "GET", "/api/comp-void", headers=default_tenant)
        assert r.status_code == 200, r.text
        reasons = [c.get("reason") for c in r.json()]
        assert "B's secret comp reason" not in reasons
    finally:
        _cleanup_business(biz_b)


def test_owner_can_still_manage_their_own_items(client, owner_headers):
    tenant = dict(owner_headers, **{"X-Tenant-Id": "default"})
    cat = req(client, "POST", "/api/categories", headers=tenant, json={"name": "Own Managed Category"})
    assert cat.status_code == 200, cat.text[:200]
    cat_id = cat.json()["id"]
    assert req(client, "PUT", f"/api/categories/{cat_id}", headers=tenant, json={"name": "Renamed"}).status_code == 200
    assert req(client, "DELETE", f"/api/categories/{cat_id}", headers=tenant).status_code == 200

    mod = req(client, "POST", "/api/modifiers", headers=tenant, json={"name": "Own Modifier"})
    mod_id = mod.json()["id"]
    assert req(client, "PUT", f"/api/modifiers/{mod_id}", headers=tenant, json={"name": "Renamed Mod"}).status_code == 200
    assert req(client, "DELETE", f"/api/modifiers/{mod_id}", headers=tenant).status_code == 200

    disc = req(client, "POST", "/api/discounts", headers=tenant, json={"name": "Own Discount"})
    disc_id = disc.json()["id"]
    assert req(client, "PUT", f"/api/discounts/{disc_id}", headers=tenant, json={"name": "Renamed Disc"}).status_code == 200
    assert req(client, "DELETE", f"/api/discounts/{disc_id}", headers=tenant).status_code == 200


def test_discount_and_payment_link_mutations_refuse_a_doc_with_no_businessId(client, owner_headers):
    """update_discount/delete_discount/delete_payment_link have no shared-
    demo-data creation path the way categories/modifiers do (create_discount
    and create_payment_link always stamp a real businessId — verified by
    reading every insert site for these two collections), so these three
    were upgraded to tenant_owns_strict(): an untagged document is refused
    for a mutation (quarantined) rather than auto-owned by whoever asks."""
    from database import db
    tenant = dict(owner_headers, **{"X-Tenant-Id": "default"})

    untagged_disc_id = "DISC-UNTAGGED-TEST-1"
    _run(db.discounts.insert_one({"id": untagged_disc_id, "name": "Untagged Discount", "businessId": None}))
    try:
        r1 = req(client, "PUT", f"/api/discounts/{untagged_disc_id}", headers=tenant, json={"name": "Hijacked"})
        assert r1.status_code == 404, r1.text
        r2 = req(client, "DELETE", f"/api/discounts/{untagged_disc_id}", headers=tenant)
        assert r2.status_code == 404, r2.text
        still_there = _run(db.discounts.find_one({"id": untagged_disc_id}))
        assert still_there is not None and still_there["name"] == "Untagged Discount"
    finally:
        _run(db.discounts.delete_many({"id": untagged_disc_id}))

    untagged_link_id = "PLINK-UNTAGGED-TEST-1"
    _run(db.payment_links.insert_one({"id": untagged_link_id, "productName": "Untagged Link", "businessId": None}))
    try:
        r3 = req(client, "DELETE", f"/api/payment-links/{untagged_link_id}", headers=tenant)
        assert r3.status_code == 404, r3.text
        still_there = _run(db.payment_links.find_one({"id": untagged_link_id}))
        assert still_there is not None
    finally:
        _run(db.payment_links.delete_many({"id": untagged_link_id}))


# ----------------------------------------- category auto-seed / catalog seed
# Task #64 of the tenant-ownership release-closure pass: get_categories'
# auto-seed-on-empty and seed_catalog's name-matched upserts used to create
# (or reuse) categories/products/modifiers with NO businessId at all — the
# active hazard that blocked update_category/update_modifier from being
# converted to tenant_owns_strict in the first place (see this file's other
# tests, and middleware/actor_context.py's tenant_owns_strict docstring).


def test_get_categories_does_not_seed_anything_for_an_anonymous_caller_with_none_existing(client):
    from database import db
    _run(db.categories.delete_many({}))
    r = req(client, "GET", "/api/categories")
    assert r.status_code == 200, r.text
    assert r.json() == [], "an anonymous caller must never trigger creation of shared, untagged categories"
    count = _run(db.categories.count_documents({}))
    assert count == 0, "no categories should have been created as a side effect of an anonymous read"


def test_get_categories_seeds_defaults_scoped_to_the_authenticated_business(client, owner_headers):
    from database import db
    _run(db.categories.delete_many({}))
    try:
        r = req(client, "GET", "/api/categories", headers=owner_headers)
        assert r.status_code == 200, r.text
        seeded = r.json()
        assert len(seeded) == 5
        for cat in seeded:
            assert cat.get("businessId"), f"every auto-seeded category must be stamped with a real businessId: {cat}"
        stored = _run(db.categories.find({}, {"_id": 0}).to_list(20))
        assert all(c.get("businessId") for c in stored)
    finally:
        _run(db.categories.delete_many({}))


def test_two_businesses_auto_seeding_categories_get_their_own_independent_copies(client, owner_headers):
    from database import db
    other = _make_business(client, owner_headers, biz_id="items-seed-other-biz",
                            email="items-seed-other-owner@nua.com")
    _run(db.categories.delete_many({}))
    try:
        r1 = req(client, "GET", "/api/categories", headers=owner_headers).json()
        r2 = req(client, "GET", "/api/categories", headers=other).json()
        ids_1 = {c["id"] for c in r1}
        ids_2 = {c["id"] for c in r2}
        assert ids_1.isdisjoint(ids_2), (
            "two businesses auto-seeding at the same empty-catalog moment must get independent rows, "
            f"not share ids — got overlap {ids_1 & ids_2}"
        )
        biz_1 = {c["businessId"] for c in r1}
        biz_2 = {c["businessId"] for c in r2}
        assert None not in biz_1 and None not in biz_2, "every seeded category must carry a real businessId"
        assert biz_1 != biz_2, "the two businesses' seeded categories must be stamped with their own distinct businessId"
    finally:
        _run(db.categories.delete_many({}))
        _cleanup_business("items-seed-other-biz")


def test_seed_catalog_gives_two_businesses_their_own_independent_catalogs(client, owner_headers):
    """Before this fix, seed_catalog's upsert filters matched by name alone
    with no businessId — the second business to call it silently reused
    (never created its own copy of) the first business's rows."""
    from database import db
    other = _make_business(client, owner_headers, biz_id="items-seed-catalog-other-biz",
                            email="items-seed-catalog-other-owner@nua.com")
    _run(db.categories.delete_many({}))
    _run(db.products.delete_many({}))
    _run(db.modifiers.delete_many({}))
    try:
        first = req(client, "POST", "/api/seed/catalog", headers=owner_headers)
        assert first.status_code == 200, first.text
        second = req(client, "POST", "/api/seed/catalog", headers=other)
        assert second.status_code == 200, second.text
        second_body = second.json()
        assert second_body["categoriesAdded"] == second_body["categoriesTotal"], (
            "the second business must get its OWN fresh categories, not silently reuse the first "
            f"business's already-seeded rows: {second_body}"
        )
        assert second_body["productsAdded"] == second_body["productsTotal"]
        assert second_body["modifiersAdded"] == second_body["modifiersTotal"]

        owner_biz = _run(db.auth_users.find_one({"email": "owner@nua.com"}, {"_id": 0, "businessId": 1}))["businessId"]
        cat_count_owner = _run(db.categories.count_documents({"businessId": owner_biz}))
        cat_count_other = _run(db.categories.count_documents({"businessId": "items-seed-catalog-other-biz"}))
        assert cat_count_owner > 0 and cat_count_other > 0
        assert cat_count_owner == cat_count_other, "both businesses must end up with their own full, independent set"
    finally:
        _run(db.categories.delete_many({}))
        _run(db.products.delete_many({}))
        _run(db.modifiers.delete_many({}))
        _cleanup_business("items-seed-catalog-other-biz")


# ------------------------------- category/modifier mutation quarantine
# Now that get_categories/seed_catalog no longer create untagged data (the
# above), update_category/merge_categories/delete_category and
# update_modifier/delete_modifier were converted from tenant_owns to
# tenant_owns_strict. These mirror the existing quarantine tests for
# accounting.py/awards.py/discounts+payment-links: an untagged row (only
# reachable now as pre-fix legacy data) must be refused for every mutation,
# not auto-owned by whichever business asks first, and never deleted as a
# side effect of the refusal.


def test_category_mutations_refuse_a_doc_with_no_businessId(client, owner_headers):
    from database import db
    untagged_id = "CAT-QUARANTINE-TEST-1"
    _run(db.categories.insert_one({"id": untagged_id, "name": "Untagged Legacy Category", "businessId": None}))
    try:
        upd = req(client, "PUT", f"/api/categories/{untagged_id}", headers=owner_headers, json={"name": "Hijacked"})
        assert upd.status_code == 404, upd.text
        deL = req(client, "DELETE", f"/api/categories/{untagged_id}", headers=owner_headers)
        assert deL.status_code == 404, deL.text
        still_there = _run(db.categories.find_one({"id": untagged_id}))
        assert still_there is not None and still_there["name"] == "Untagged Legacy Category"
    finally:
        _run(db.categories.delete_many({"id": untagged_id}))


def test_merge_categories_refuses_an_untagged_source_or_target(client, owner_headers):
    from database import db
    untagged_id = "CAT-QUARANTINE-TEST-2"
    own_id = "CAT-QUARANTINE-OWNED"
    _run(db.categories.insert_one({"id": untagged_id, "name": "Untagged", "businessId": None}))
    _run(db.categories.insert_one({"id": own_id, "name": "Owned", "businessId": "default"}))
    try:
        r1 = req(client, "POST", f"/api/categories/{untagged_id}/merge/{own_id}", headers=owner_headers)
        assert r1.status_code == 404, r1.text
        r2 = req(client, "POST", f"/api/categories/{own_id}/merge/{untagged_id}", headers=owner_headers)
        assert r2.status_code == 404, r2.text
        assert _run(db.categories.find_one({"id": untagged_id})) is not None
        assert _run(db.categories.find_one({"id": own_id})) is not None
    finally:
        _run(db.categories.delete_many({"id": {"$in": [untagged_id, own_id]}}))


def test_modifier_mutations_refuse_a_doc_with_no_businessId(client, owner_headers):
    from database import db
    untagged_id = "MOD-QUARANTINE-TEST-1"
    _run(db.modifiers.insert_one({"id": untagged_id, "name": "Untagged Legacy Modifier", "businessId": None}))
    try:
        upd = req(client, "PUT", f"/api/modifiers/{untagged_id}", headers=owner_headers, json={"name": "Hijacked"})
        assert upd.status_code == 404, upd.text
        deL = req(client, "DELETE", f"/api/modifiers/{untagged_id}", headers=owner_headers)
        assert deL.status_code == 404, deL.text
        still_there = _run(db.modifiers.find_one({"id": untagged_id}))
        assert still_there is not None and still_there["name"] == "Untagged Legacy Modifier"
    finally:
        _run(db.modifiers.delete_many({"id": untagged_id}))
