"""Follow-ups to the segment builder shipped earlier this round: a saved
segment could be created and deleted but never renamed/edited, the preview
only ever showed a 20-row sample with no way to see the full matching
list, and "spent > $X" only ever meant lifetime total — no way to ask
"spent > $X in the last 90 days", which is what most win-back/reactivation
campaigns actually mean.
"""
from conftest import req


def test_a_saved_segment_can_be_renamed_and_have_its_rules_edited(client, owner_headers):
    created = req(client, "POST", "/api/marketing/segments", headers=owner_headers,
                  json={"name": "Old Name", "rules": {"minSpend": 100}})
    assert created.status_code == 200, created.text[:200]
    segment_id = created.json()["id"]

    updated = req(client, "PUT", f"/api/marketing/segments/{segment_id}", headers=owner_headers,
                  json={"name": "Big Spenders (renamed)", "rules": {"minSpend": 200}})
    assert updated.status_code == 200, updated.text[:200]
    assert updated.json()["name"] == "Big Spenders (renamed)"
    assert updated.json()["rules"]["minSpend"] == 200

    listed = req(client, "GET", "/api/marketing/segments", headers=owner_headers).json()
    row = next(s for s in listed if s["id"] == segment_id)
    assert row["name"] == "Big Spenders (renamed)"


def test_updating_a_missing_segment_is_a_404(client, owner_headers):
    r = req(client, "PUT", "/api/marketing/segments/SEG-NOPE", headers=owner_headers, json={"name": "x"})
    assert r.status_code == 404


def test_full_segment_customer_list_goes_beyond_the_20_row_preview(client, owner_headers):
    tenant = dict(owner_headers, **{"X-Tenant-Id": "segment-full-list-test"})
    for i in range(25):
        req(client, "POST", "/api/customers", headers=tenant, json={
            "name": f"Bulk Segment Customer {i}", "email": f"bulkseg{i}@nua.com",
            "phone": "0400000000"})
    # totalSpent isn't settable via POST /customers, so drive it through the
    # segment rule instead: minVisits=0 matches everyone just created (and
    # possibly other fixtures) — the point here is the *count* returned
    # exceeds the old hardcoded 20-row cap, not an exact total.
    seg = req(client, "POST", "/api/marketing/segments", headers=tenant,
              json={"name": "Everyone", "rules": {"minVisits": 0}})
    segment_id = seg.json()["id"]

    full = req(client, "GET", f"/api/marketing/segments/{segment_id}/customers", headers=tenant)
    assert full.status_code == 200, full.text[:200]
    assert full.json()["count"] >= 25
    assert len(full.json()["customers"]) >= 25


def test_spend_in_last_n_days_only_counts_transactions_inside_the_window(client, owner_headers):
    tenant = dict(owner_headers, **{"X-Tenant-Id": "spend-window-test"})
    recent = req(client, "POST", "/api/customers", headers=tenant, json={
        "name": "Recent Big Spender", "email": "recentbig@nua.com", "phone": "0400111111"})
    recent_id = recent.json()["id"]
    low = req(client, "POST", "/api/customers", headers=tenant, json={
        "name": "Recent Small Spender", "email": "recentsmall@nua.com", "phone": "0400222222"})
    low_id = low.json()["id"]

    # Recent big spender: one $600 sale right now — inside any reasonable window.
    sale = req(client, "POST", "/api/transactions", headers=tenant, json={
        "items": [{"productId": "no-such-product", "productName": "Big ticket item", "quantity": 1, "price": 600}],
        "paymentMethod": "cash", "location": "Main", "cashier": "Test Cashier", "customerId": recent_id})
    assert sale.status_code == 200, sale.text[:200]

    # Recent small spender: one $5 sale — same window, doesn't clear the bar.
    req(client, "POST", "/api/transactions", headers=tenant, json={
        "items": [{"productId": "no-such-product", "productName": "Cheap item", "quantity": 1, "price": 5}],
        "paymentMethod": "cash", "location": "Main", "cashier": "Test Cashier", "customerId": low_id})

    # /segments/preview's "sample" field is capped to 20 rows, and this
    # suite's shared test DB accumulates customers across the whole session
    # — by now there are comfortably more than 20 "default"-business
    # customers, so the two just-created here can fall outside the visible
    # sample even though they correctly match the query. Save the segment
    # and read its full (uncapped) customer list instead, the same way
    # test_full_segment_customer_list_goes_beyond_the_20_row_preview above
    # already does for exactly this reason.
    saved = req(client, "POST", "/api/marketing/segments", headers=tenant,
                json={"name": "Spend Window Test", "rules": {"spendInLastDays": 90, "minSpendInWindow": 500}})
    assert saved.status_code == 200, saved.text[:200]
    segment_id = saved.json()["id"]

    full = req(client, "GET", f"/api/marketing/segments/{segment_id}/customers", headers=tenant)
    assert full.status_code == 200, full.text[:200]
    emails = {c["email"] for c in full.json()["customers"]}
    assert "recentbig@nua.com" in emails
    assert "recentsmall@nua.com" not in emails
