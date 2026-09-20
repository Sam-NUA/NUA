"""Kitchen docket printing: a job should print at most once, no matter how
many staff devices are connected to the business, and it should follow the
printer profile (printer_targets) rather than any particular client's say-so.

Also locks in the docket layout the printer profile is responsible for:
this station's own section first, grouped by category, with any other
station's items ("ALSO ON THIS ORDER") dimmed underneath.
"""
import asyncio

from conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _set_target(printer, **kw):
    from database import db
    doc = {"printer": printer, "host": "10.0.0.50", "port": 9100, "enabled": True,
           "businessId": "default", **kw}
    _run(db.printer_targets.update_one(
        {"printer": printer, "businessId": "default"}, {"$set": doc}, upsert=True))
    return doc


def _clear_target(printer):
    from database import db
    _run(db.printer_targets.delete_one({"printer": printer, "businessId": "default"}))


def _clear_jobs(order_id):
    from database import db
    _run(db.print_jobs.delete_many({"orderId": order_id}))


# ------------------------------------------------------- auto-print on queue

def test_auto_print_sends_exactly_once_when_a_target_is_configured(monkeypatch):
    import services.escpos as escpos
    from services import print_routing

    calls = []
    async def fake_send(host, payload, port=9100, timeout=5.0):
        calls.append((host, port))
        return {"ok": True, "bytes": len(payload)}
    monkeypatch.setattr(escpos, "send", fake_send)

    _set_target("Kitchen Printer")
    try:
        records = _run(print_routing.route_and_queue(
            [{"productName": "Burger", "category": "Mains", "quantity": 1}],
            order_id="ORD-AUTOPRINT-1", business_id="default"))
        assert len(records) == 1
        assert len(calls) == 1, "expected exactly one send to the physical printer"

        from database import db
        job = _run(db.print_jobs.find_one({"id": records[0]["id"]}, {"_id": 0}))
        assert job["status"] == "printed"
        assert job["printedVia"] == "escpos://10.0.0.50:9100"
    finally:
        _clear_target("Kitchen Printer")
        _clear_jobs("ORD-AUTOPRINT-1")


def test_auto_print_does_nothing_when_no_target_is_configured(monkeypatch):
    import services.escpos as escpos
    from services import print_routing

    calls = []
    async def fake_send(host, payload, port=9100, timeout=5.0):
        calls.append(1)
        return {"ok": True}
    monkeypatch.setattr(escpos, "send", fake_send)

    _clear_target("Kitchen Printer")  # make sure none lingers from another test
    try:
        records = _run(print_routing.route_and_queue(
            [{"productName": "Burger", "category": "Mains", "quantity": 1}],
            order_id="ORD-NOTARGET-1", business_id="default"))
        assert len(calls) == 0
        from database import db
        job = _run(db.print_jobs.find_one({"id": records[0]["id"]}, {"_id": 0}))
        assert job["status"] == "queued"
    finally:
        _clear_jobs("ORD-NOTARGET-1")


def test_auto_print_releases_the_claim_when_the_printer_is_unreachable(monkeypatch):
    import services.escpos as escpos
    from services import print_routing

    async def fake_send(host, payload, port=9100, timeout=5.0):
        return {"ok": False, "error": "could not reach 10.0.0.50:9100"}
    monkeypatch.setattr(escpos, "send", fake_send)

    _set_target("Kitchen Printer")
    try:
        records = _run(print_routing.route_and_queue(
            [{"productName": "Burger", "category": "Mains", "quantity": 1}],
            order_id="ORD-UNREACHABLE-1", business_id="default"))
        from database import db
        job = _run(db.print_jobs.find_one({"id": records[0]["id"]}, {"_id": 0}))
        # Not stuck in "printing" — back to "queued" so it's retryable.
        assert job["status"] == "queued"
        assert "could not reach" in job["lastError"]
    finally:
        _clear_target("Kitchen Printer")
        _clear_jobs("ORD-UNREACHABLE-1")


def test_a_job_disabled_at_the_printer_profile_does_not_auto_print(monkeypatch):
    import services.escpos as escpos
    from services import print_routing

    calls = []
    async def fake_send(host, payload, port=9100, timeout=5.0):
        calls.append(1)
        return {"ok": True}
    monkeypatch.setattr(escpos, "send", fake_send)

    _set_target("Kitchen Printer", enabled=False)
    try:
        records = _run(print_routing.route_and_queue(
            [{"productName": "Burger", "category": "Mains", "quantity": 1}],
            order_id="ORD-DISABLED-1", business_id="default"))
        assert len(calls) == 0
        from database import db
        job = _run(db.print_jobs.find_one({"id": records[0]["id"]}, {"_id": 0}))
        assert job["status"] == "queued"
    finally:
        _clear_target("Kitchen Printer")
        _clear_jobs("ORD-DISABLED-1")


# --------------------------------------------- "many devices" can't double-print

def test_a_second_device_clicking_print_after_auto_print_gets_refused(client, owner_headers, monkeypatch):
    """The scenario in the bug report: an order auto-prints once at
    creation (device A did nothing but check out), then a second device
    (device B) also has this ticket on screen and taps Print. It must not
    produce a second copy."""
    import services.escpos as escpos
    from services import print_routing

    calls = []
    async def fake_send(host, payload, port=9100, timeout=5.0):
        calls.append(1)
        return {"ok": True}
    monkeypatch.setattr(escpos, "send", fake_send)

    _set_target("Kitchen Printer")
    try:
        records = _run(print_routing.route_and_queue(
            [{"productName": "Burger", "category": "Mains", "quantity": 1}],
            order_id="ORD-MULTIDEVICE-1", business_id="default"))
        assert len(calls) == 1  # auto-print at creation

        job_id = records[0]["id"]
        r = req(client, "POST", f"/api/print-jobs/{job_id}/escpos", headers=owner_headers, json={})
        assert r.status_code == 200
        body = r.json()
        assert body["sent"] is False
        assert "already printed" in body["reason"]
        assert len(calls) == 1, "a second device's print tap must not trigger a second send"
    finally:
        _clear_target("Kitchen Printer")
        _clear_jobs("ORD-MULTIDEVICE-1")


def test_force_allows_a_deliberate_reprint(client, owner_headers, monkeypatch):
    import services.escpos as escpos
    from services import print_routing

    calls = []
    async def fake_send(host, payload, port=9100, timeout=5.0):
        calls.append(1)
        return {"ok": True}
    monkeypatch.setattr(escpos, "send", fake_send)

    _set_target("Kitchen Printer")
    try:
        records = _run(print_routing.route_and_queue(
            [{"productName": "Burger", "category": "Mains", "quantity": 1}],
            order_id="ORD-FORCE-1", business_id="default"))
        assert len(calls) == 1

        job_id = records[0]["id"]
        r = req(client, "POST", f"/api/print-jobs/{job_id}/escpos", headers=owner_headers, json={"force": True})
        assert r.status_code == 200
        assert r.json()["sent"] is True
        assert len(calls) == 2, "an explicit force reprint is a deliberate second copy, not a bug"
    finally:
        _clear_target("Kitchen Printer")
        _clear_jobs("ORD-FORCE-1")


def test_manual_print_requires_auth(anon):
    r = req(anon, "POST", "/api/print-jobs/PRINT-NOPE/escpos", json={})
    assert r.status_code == 401


def test_manual_print_404s_for_an_unknown_job(client, owner_headers):
    r = req(client, "POST", "/api/print-jobs/PRINT-DOES-NOT-EXIST/escpos", headers=owner_headers, json={})
    assert r.status_code == 404


# ------------------------------------------------------- category/section layout

def test_escpos_render_puts_own_section_first_then_others_dimmed_below():
    from services import escpos

    job = {
        "printer": "Kitchen Printer",
        "orderId": "ORD-LAYOUT-1", "tableNumber": "12", "priority": 2,
        "orderStations": ["Kitchen Printer", "Bar Printer"],
        "orderSections": [
            {"printer": "Kitchen Printer", "items": [
                {"productName": "Burger", "category": "Mains", "quantity": 1},
                {"productName": "Fries", "category": "Sides", "quantity": 1},
            ]},
            {"printer": "Bar Printer", "items": [
                {"productName": "Coke", "category": "Beverages", "quantity": 2},
            ]},
        ],
        "items": [],
    }
    payload = escpos.render(job)
    preview = escpos.describe(payload)["preview"]

    kitchen_pos = preview.index("KITCHEN")
    mains_pos = preview.index("MAINS")
    also_pos = preview.index("ALSO ON THIS ORDER")
    bar_pos = preview.index("BAR")
    beverages_pos = preview.index("BEVERAGES")

    # Own station banner, then its own category section, before the
    # "also on this order" marker, before the other station's section.
    assert kitchen_pos < mains_pos < also_pos < bar_pos < beverages_pos


def test_escpos_render_groups_items_by_category_within_a_section():
    from services import escpos

    job = {
        "printer": "Kitchen Printer",
        "orderId": "ORD-LAYOUT-2",
        "orderSections": [{"printer": "Kitchen Printer", "items": [
            {"productName": "Burger", "category": "Mains", "quantity": 1},
            {"productName": "Steak", "category": "Mains", "quantity": 1},
            {"productName": "Ice Cream", "category": "Desserts", "quantity": 1},
        ]}],
        "items": [],
    }
    preview = escpos.describe(escpos.render(job))["preview"]
    # A category header should not repeat for consecutive same-category
    # items — only once per contiguous run.
    assert preview.count("MAINS") == 1
    assert preview.index("MAINS") < preview.index("Burger")
    assert preview.index("Burger") < preview.index("Steak")
    assert preview.index("Steak") < preview.index("DESSERTS") < preview.index("Ice Cream")
