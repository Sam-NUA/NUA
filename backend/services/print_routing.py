"""Route order items to station printers and queue the dockets.

Lifted out of routes/gamification.py so two callers can share it: the POS
sending a whole order, and a course being fired (which prints only that
course's items, at the moment the server fires it — which is what a station
actually wants).

Item dicts may carry `course`, `courseLabel` and `seat`; they're passed
straight through onto the job so the docket can print them.
"""
import copy
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import db
from middleware.actor_context import tenant_scope_filter

DEFAULT_PRINT_ROUTING: Dict[str, Any] = {
    "enabled": True,
    "routes": [
        {"category": "Beverages", "printer": "Bar Printer", "priority": 1},
        {"category": "Alcohol", "printer": "Bar Printer", "priority": 1},
        {"category": "Beer", "printer": "Bar Printer", "priority": 1},
        {"category": "Wine — Red", "printer": "Bar Printer", "priority": 1},
        {"category": "Wine — White", "printer": "Bar Printer", "priority": 1},
        {"category": "Wine — Sparkling", "printer": "Bar Printer", "priority": 1},
        {"category": "Wine — Rosé", "printer": "Bar Printer", "priority": 1},
        {"category": "Cocktails", "printer": "Bar Printer", "priority": 1},
        {"category": "Spirits — Whisky", "printer": "Bar Printer", "priority": 1},
        {"category": "Spirits — Gin", "printer": "Bar Printer", "priority": 1},
        {"category": "Spirits — Vodka", "printer": "Bar Printer", "priority": 1},
        {"category": "Spirits — Rum", "printer": "Bar Printer", "priority": 1},
        {"category": "Spirits — Tequila", "printer": "Bar Printer", "priority": 1},
        {"category": "Liqueurs", "printer": "Bar Printer", "priority": 1},
        {"category": "Non-Alcoholic", "printer": "Bar Printer", "priority": 1},
        {"category": "Coffee & Tea", "printer": "Bar Printer", "priority": 1},
        {"category": "Food", "printer": "Kitchen Printer", "priority": 2},
        {"category": "Mains", "printer": "Kitchen Printer", "priority": 2},
        {"category": "Appetizers", "printer": "Kitchen Printer", "priority": 1},
        {"category": "Bakery", "printer": "Kitchen Printer", "priority": 3},
        {"category": "Desserts", "printer": "Kitchen Printer", "priority": 3},
        {"category": "Pizza", "printer": "Pizza Station", "priority": 1},
    ],
    # Category groups (from the categories collection) used when no explicit
    # category route matches — so a newly added drink category still goes to
    # the bar instead of quietly landing on the kitchen printer.
    "groupRoutes": [
        {"group": "Alcohol", "printer": "Bar Printer", "priority": 1},
        {"group": "Drinks", "printer": "Bar Printer", "priority": 1},
    ],
    "defaultPrinter": "Kitchen Printer",
    "defaultPriority": 2,
}


async def load_config(business_id: Optional[str] = None) -> Dict[str, Any]:
    """Defaults `business_id` from the request's actor context (same
    pattern as notification_service.send()/rules_engine.emit_event()) so
    the many existing callers here don't each need editing — this used to
    be one config shared by every business on the deployment; see
    services/tenant_settings.py."""
    from services.tenant_settings import get_setting
    value = await get_setting("print_routing", business_id)
    cfg = copy.deepcopy(value) if value else copy.deepcopy(DEFAULT_PRINT_ROUTING)
    routes = cfg.get("routes")
    if isinstance(routes, dict):
        cfg["routes"] = [
            {"category": cat.title(), "printer": prn, "priority": 2}
            for cat, prn in routes.items() if isinstance(prn, str)
        ]
    elif routes is None or not isinstance(routes, list):
        cfg["routes"] = DEFAULT_PRINT_ROUTING["routes"]
    cfg.setdefault("enabled", True)
    cfg.setdefault("groupRoutes", DEFAULT_PRINT_ROUTING["groupRoutes"])
    cfg.setdefault("defaultPrinter", DEFAULT_PRINT_ROUTING["defaultPrinter"])
    cfg.setdefault("defaultPriority", DEFAULT_PRINT_ROUTING["defaultPriority"])
    return cfg


async def stations_for(items: List[dict]) -> List[str]:
    """Which station printers a set of items would route to, without printing.

    The KDS station filter needs this on the ticket itself: dockets carry
    stations, but they're created per fired course, so a ticket's full station
    list can't be read off them — and a bar screen filtering on a field the
    ticket doesn't have silently shows everything.
    """
    config = await load_config()
    routes = config.get("routes", [])
    group_routes = config.get("groupRoutes") or DEFAULT_PRINT_ROUTING["groupRoutes"]
    default_printer = config.get("defaultPrinter", "Kitchen Printer")
    cat_docs = await db.categories.find(tenant_scope_filter(), {"_id": 0, "name": 1, "group": 1}).to_list(500)
    cat_group = {c.get("name", "").lower(): (c.get("group") or "") for c in cat_docs}

    out: List[str] = []
    for item in items or []:
        cat = (item.get("category") or "")
        route = next((r for r in routes if str(r.get("category", "")).lower() == cat.lower()), None)
        if route:
            printer = route["printer"]
        else:
            grp = cat_group.get(cat.lower(), "")
            g = next((r for r in group_routes if str(r.get("group", "")).lower() == grp.lower()), None) if grp else None
            printer = g["printer"] if g else default_printer
        if printer not in out:
            out.append(printer)
    return out


async def route_and_queue(items: List[dict], order_id: Optional[str] = None,
                          table_number: Optional[str] = None,
                          extra: Optional[Dict[str, Any]] = None,
                          business_id: Optional[str] = None) -> List[dict]:
    """Split items across station printers and queue one docket per station.

    Every docket carries the full section list and per-section detail, so each
    station prints the whole order — its own dishes first, then what else is
    going out with them and from where.
    """
    order_id = order_id or f"ORD-{str(uuid.uuid4())[:8].upper()}"
    scope = tenant_scope_filter(business_id)
    resolved_business_id = scope["businessId"]
    config = await load_config(resolved_business_id)
    routes = config.get("routes", [])
    group_routes = config.get("groupRoutes") or DEFAULT_PRINT_ROUTING["groupRoutes"]
    default_printer = config.get("defaultPrinter", "Kitchen Printer")
    default_priority = config.get("defaultPriority", 2)

    cat_docs = await db.categories.find(scope, {"_id": 0, "name": 1, "group": 1}).to_list(500)
    cat_group = {c.get("name", "").lower(): (c.get("group") or "") for c in cat_docs}

    def _route_for(cat: str):
        route = next((r for r in routes if str(r.get("category", "")).lower() == cat.lower()), None)
        if route:
            return route["printer"], route.get("priority", default_priority)
        grp = cat_group.get(cat.lower(), "")
        if grp:
            g = next((r for r in group_routes if str(r.get("group", "")).lower() == grp.lower()), None)
            if g:
                return g["printer"], g.get("priority", default_priority)
        return default_printer, default_priority

    printer_jobs: Dict[str, dict] = {}
    for item in items:
        printer_name, priority = _route_for(item.get("category", "") or "")
        if printer_name not in printer_jobs:
            printer_jobs[printer_name] = {"printer": printer_name, "items": [], "priority": priority}
        printer_jobs[printer_name]["items"].append(item)
        printer_jobs[printer_name]["priority"] = min(printer_jobs[printer_name]["priority"], priority)

    # Keep same-course dishes together, and same-category dishes adjacent
    # inside a course, so the docket reads the way the station works.
    for job in printer_jobs.values():
        seen: List[str] = []
        for it in job["items"]:
            c = (it.get("category") or "").lower()
            if c not in seen:
                seen.append(c)
        job["items"].sort(key=lambda it: (int(it.get("course") or 1),
                                          seen.index((it.get("category") or "").lower())))

    jobs = sorted(printer_jobs.values(), key=lambda x: x["priority"])
    order_stations = [j["printer"] for j in jobs]
    order_sections = [{"printer": j["printer"], "items": j["items"]} for j in jobs]

    records = []
    for job in jobs:
        record = {
            "id": f"PRINT-{str(uuid.uuid4())[:8].upper()}",
            "orderId": order_id, "tableNumber": table_number,
            "printer": job["printer"], "priority": job["priority"],
            "items": job["items"], "status": "queued",
            "orderStations": order_stations,
            "orderSections": order_sections,
            "businessId": resolved_business_id,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            **(extra or {}),
        }
        await db.print_jobs.insert_one(record)
        record.pop("_id", None)
        await _auto_print(record)
        records.append(record)
    return records


async def _auto_print(record: dict) -> None:
    """Send a freshly-queued job straight to its configured network printer.

    This is what keeps a docket to exactly one copy no matter how many
    staff devices are logged into the business: the print happens here,
    once, server-side, at the moment the job is created — not by every
    connected device independently noticing a shared queue and racing to
    send it. Print behavior is entirely a function of the printer_targets
    document (the "printer profile") for this station: no target
    configured, or disabled, means no auto-print — the job just stays
    queued for a manual retry/browser-print fallback instead of guessing.

    Atomically claims the job (status must still be "queued") before
    rendering, so a concurrent manual reprint via the /escpos endpoint
    can't double-send the same ticket.
    """
    from services import escpos
    scope = tenant_scope_filter(record.get("businessId"))
    target = await escpos.printer_target(record["printer"], record.get("businessId"))
    if not target or not target.get("enabled", True):
        return

    claimed = await db.print_jobs.find_one_and_update(
        {"id": record["id"], "status": "queued", **scope},
        {"$set": {"status": "printing"}}, return_document=True,
    )
    if not claimed:
        return  # Already claimed/printed elsewhere between insert and here.

    payload = escpos.render(
        claimed,
        width=target.get("width") or escpos.DEFAULT_WIDTH,
        codepage=target.get("codepage") or escpos.DEFAULT_CODEPAGE,
        cut=target.get("cut") or "partial",
        footer_in_person=target.get("footerInPerson", True),
        footer_online=target.get("footerOnline", True),
        padding_lines=target.get("paddingLines", 3),
    )
    result = await escpos.send(target["host"], payload, port=target.get("port", 9100))
    if result.get("ok"):
        await db.print_jobs.update_one(
            {"id": record["id"], **scope},
            {"$set": {"status": "printed", "printedAt": datetime.now(timezone.utc).isoformat(),
                      "printedVia": f"escpos://{target['host']}:{target.get('port', 9100)}"}},
        )
    else:
        # Couldn't reach the printer — release the claim so this shows back
        # up as "queued" (visible in the print-routing queue, retryable via
        # /escpos) instead of stuck in "printing" forever.
        await db.print_jobs.update_one(
            {"id": record["id"], **scope},
            {"$set": {"status": "queued", "lastError": result.get("error")}})
