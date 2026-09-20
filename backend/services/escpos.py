"""Render a station docket as ESC/POS bytes and push it to a thermal printer.

The docket *content* has been right for a while; the transport was a browser
print dialog, which is fine for a demo and useless on a service line. This
turns a queued print job into the byte stream an 80mm thermal printer actually
speaks, and sends it over the network (ESC/POS raw, port 9100 — what Epson
TM-series, Star and most clones expose).

Kept deliberately dependency-free: ESC/POS is a handful of control codes, and
adding a driver library for this would be more surface than the codes are.

Printers that aren't reachable fall back to the browser path — a station
without a configured IP still prints the way it does today.
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

ESC = b"\x1b"
GS = b"\x1d"

INIT = ESC + b"@"
BOLD_ON = ESC + b"E\x01"
BOLD_OFF = ESC + b"E\x00"
ALIGN_LEFT = ESC + b"a\x00"
ALIGN_CENTER = ESC + b"a\x01"
# GS ! n — width in the high nibble, height in the low nibble.
SIZE_NORMAL = GS + b"!\x00"
SIZE_DOUBLE = GS + b"!\x11"
SIZE_TALL = GS + b"!\x01"
CUT = GS + b"V\x42\x00"        # partial cut, feed first
FEED_3 = b"\n\n\n"

# Known-device presets. These are the settings that differ in practice, and
# guessing them costs a roll of paper per attempt — so they're named rather
# than rediscovered per venue.
DEVICE_PROFILES = {
    "epson-tm-80":   {"width": 48, "codepage": "cp437", "cut": "partial",
                      "label": "Epson TM-series, 80mm"},
    "epson-tm-58":   {"width": 32, "codepage": "cp437", "cut": "partial",
                      "label": "Epson TM-series, 58mm"},
    "star-tsp-80":   {"width": 48, "codepage": "cp437", "cut": "full",
                      "label": "Star TSP-series, 80mm"},
    "generic-80":    {"width": 48, "codepage": "cp437", "cut": "legacy",
                      "label": "Generic/clone 80mm (older cut command)"},
    "generic-58":    {"width": 32, "codepage": "cp437", "cut": "legacy",
                      "label": "Generic/clone 58mm"},
    "euro-80":       {"width": 48, "codepage": "cp850", "cut": "partial",
                      "label": "80mm, Western European codepage"},
}

DEFAULT_PORT = 9100
DEFAULT_WIDTH = 48             # characters per line at font A on 80mm
DEFAULT_CODEPAGE = "cp437"     # near-universal default on thermal printers

# Cut behaviour is the most manufacturer-specific part of ESC/POS: some
# clones ignore GS V, others only honour the older ESC i / ESC m.
CUT_STYLES = {
    "partial": GS + b"V\x42\x00",
    "full":    GS + b"V\x41\x00",
    "legacy":  ESC + b"i",          # older Epson / many clones
    "none":    b"",
}


def _line(char: str = "-", width: int = DEFAULT_WIDTH, codepage: str = DEFAULT_CODEPAGE) -> bytes:
    return (char * width).encode(codepage, "replace") + b"\n"


def _text(s: str, codepage: str = DEFAULT_CODEPAGE) -> bytes:
    """Encode for the printer's codepage.

    Anything outside it (— … é) is replaced rather than corrupting the byte
    stream — a mangled character is a cosmetic problem, a desynced stream
    means the rest of the ticket prints as garbage.
    """
    try:
        return str(s).encode(codepage, "replace")
    except LookupError:
        return str(s).encode(DEFAULT_CODEPAGE, "replace")


def _wrap(text: str, width: int, indent: int = 0) -> List[str]:
    words, lines, cur = str(text).split(), [], ""
    pad = " " * indent
    for w in words:
        candidate = f"{cur} {w}".strip()
        if len(candidate) + (indent if lines else 0) > width:
            lines.append((pad if lines else "") + cur)
            cur = w
        else:
            cur = candidate
    if cur:
        lines.append((pad if lines else "") + cur)
    return lines or [""]


def _station_label(printer: str) -> str:
    import re
    return re.sub(r"\s*(printer|station)\s*$", "", str(printer or ""),
                  flags=re.IGNORECASE).strip().upper() or "KITCHEN"


def render(job: Dict[str, Any], width: int = DEFAULT_WIDTH,
           codepage: str = DEFAULT_CODEPAGE, cut: str = "partial",
           footer_in_person: bool = True, footer_online: bool = True,
           padding_lines: int = 3) -> bytes:
    """A print job -> ESC/POS byte stream, mirroring the on-screen docket.

    `width`, `codepage` and `cut` are per-device because they genuinely vary:
    58mm paper is 32 characters not 48, non-Latin markets need a different
    codepage, and cut command support is the least consistent part of the
    spec across manufacturers.

    `footer_in_person`/`footer_online` gate a trailing "printed by" line
    identifying the device/profile that sent the ticket — some kitchens want
    a bare ticket, others rely on it to trace a mis-routed docket, and the
    preference often differs for dine-in versus online orders on the same
    printer. `padding_lines` is how much blank feed happens before the cut,
    since a short-throat cutter needs more clearance than a long one.
    """
    _t = lambda x: _text(x, codepage)
    _l = lambda ch="-": _line(ch, width, codepage)
    out = bytearray()
    out += INIT

    # Station banner — the biggest thing on the ticket, because a cook reads
    # it from arm's length across a hot line.
    out += ALIGN_CENTER + SIZE_DOUBLE + BOLD_ON
    out += _t(_station_label(job.get("printer"))) + b"\n"
    out += BOLD_OFF + SIZE_NORMAL

    if job.get("voidDocket"):
        out += SIZE_TALL + BOLD_ON + _t("*** VOID ***") + b"\n" + BOLD_OFF + SIZE_NORMAL
    elif job.get("courseLabel"):
        out += SIZE_TALL + BOLD_ON + _t(f"FIRE: {job['courseLabel']}") + b"\n"
        out += BOLD_OFF + SIZE_NORMAL

    out += ALIGN_LEFT + _l("=")
    table = job.get("tableNumber")
    header = f"TABLE {table}" if table else str(job.get("orderId") or "")
    out += BOLD_ON + _t(header.ljust(width - 6)) + _t(f"P{job.get('priority', 2)}") + b"\n" + BOLD_OFF
    if table and job.get("orderId"):
        out += _t(str(job["orderId"])) + b"\n"
    out += _l("=")

    # Own section first — that's what this station cooks.
    sections = job.get("orderSections") or [{"printer": job.get("printer"), "items": job.get("items") or []}]
    own = _station_label(job.get("printer"))
    own_items = next((s["items"] for s in sections if _station_label(s.get("printer")) == own),
                     job.get("items") or [])
    out += _render_items(own_items, width, dim=False, codepage=codepage)

    others = [s for s in sections if _station_label(s.get("printer")) != own]
    if others:
        out += _l("-")
        out += ALIGN_CENTER + _t("- ALSO ON THIS ORDER -") + b"\n" + ALIGN_LEFT
        for s in others:
            out += BOLD_ON + _t(_station_label(s.get("printer"))) + b"\n" + BOLD_OFF
            out += _render_items(s.get("items") or [], width, dim=True, codepage=codepage)

    stations = job.get("orderStations") or [job.get("printer")]
    out += _l("-")
    out += _t("SECTIONS: ") + _t(" | ".join(_station_label(p) for p in stations)) + b"\n"

    order_type = str(job.get("orderType") or "dine_in")
    is_online = order_type not in ("dine_in", "takeaway")
    show_footer = footer_online if is_online else footer_in_person
    if show_footer:
        out += _l("-")
        out += _t(f"Printed by: {job.get('printer', '')} | {order_type}") + b"\n"

    out += (b"\n" * max(0, padding_lines)) + CUT_STYLES.get(cut, CUT_STYLES["partial"])
    return bytes(out)


def _render_items(items: List[dict], width: int, dim: bool,
                  codepage: str = DEFAULT_CODEPAGE) -> bytes:
    _t = lambda x: _text(x, codepage)
    out = bytearray()
    # Course above category, same order as the screen docket.
    by_course: Dict[Any, List[dict]] = {}
    for it in items or []:
        by_course.setdefault(it.get("course"), []).append(it)
    ordered = sorted(by_course.items(), key=lambda kv: (kv[0] is None, kv[0] or 0))

    for course, rows in ordered:
        if course is not None and len(ordered) > 1:
            label = rows[0].get("courseLabel") or f"COURSE {course}"
            out += BOLD_ON + _t(f"-- {str(label).upper()} --") + b"\n" + BOLD_OFF
        seen_cat = None
        for it in rows:
            cat = (it.get("category") or "Other").upper()
            if cat != seen_cat:
                seen_cat = cat
                out += _t(cat) + b"\n"
            qty = f"{it.get('quantity', 1)}x "
            seat = f"[S{it['seat']}] " if it.get("seat") else ""
            name = f"{seat}{it.get('productName') or it.get('name') or ''}"
            lines = _wrap(name, width - len(qty))
            if not dim:
                out += BOLD_ON
            out += _t(qty + lines[0]) + b"\n"
            for extra in lines[1:]:
                out += _t(" " * len(qty) + extra) + b"\n"
            if not dim:
                out += BOLD_OFF
            # Allergens are the one thing on a docket that has to be
            # impossible to skim past, so they get their own bold line rather
            # than being folded in with the notes.
            allergens = it.get("allergens") or []
            if allergens:
                for al in _wrap("!! " + ", ".join(str(a).upper() for a in allergens), width - 2):
                    out += BOLD_ON + _t("  " + al) + b"\n" + BOLD_OFF
            diet = it.get("dietary") or []
            if diet:
                for dl in _wrap("(" + ", ".join(str(d) for d in diet) + ")", width - 2):
                    out += _t("  " + dl) + b"\n"
            if it.get("notes"):
                for nl in _wrap(f"> {it['notes']}", width - 2):
                    out += _t("  " + nl) + b"\n"
    return bytes(out)


async def send(host: str, payload: bytes, port: int = DEFAULT_PORT,
               timeout: float = 5.0) -> Dict[str, Any]:
    """Push bytes to a network thermal printer (raw ESC/POS, usually :9100)."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout)
    except (OSError, asyncio.TimeoutError) as e:
        return {"ok": False, "error": f"could not reach {host}:{port} — {e}"}
    try:
        writer.write(payload)
        await asyncio.wait_for(writer.drain(), timeout=timeout)
        return {"ok": True, "bytes": len(payload), "host": host, "port": port}
    except (OSError, asyncio.TimeoutError) as e:
        return {"ok": False, "error": f"write failed to {host}:{port} — {e}"}
    finally:
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), timeout=timeout)
        except (OSError, asyncio.TimeoutError):
            pass


# How many bytes each control sequence occupies, including its parameters.
# Needed because the parameter bytes are often printable ASCII (ESC "E" 0x01),
# so filtering on "is this byte printable" leaves them behind and makes every
# measured line look wider than it prints.
_ESC_LEN = {b"@": 2, b"E": 3, b"a": 3, b"i": 2, b"m": 2, b"d": 3, b"!": 3, b"t": 3}
_GS_LEN = {b"!": 3, b"V": 4, b"B": 3}


def strip_control(payload: bytes) -> bytes:
    """Remove ESC/GS sequences, leaving only what actually prints."""
    out = bytearray()
    i = 0
    n = len(payload)
    while i < n:
        byte = payload[i:i + 1]
        if byte == ESC and i + 1 < n:
            i += _ESC_LEN.get(payload[i + 1:i + 2], 2)
            continue
        if byte == GS and i + 1 < n:
            i += _GS_LEN.get(payload[i + 1:i + 2], 3)
            continue
        if payload[i] >= 0x20 or payload[i] == 0x0A:
            out += byte
        i += 1
    return bytes(out)


def describe(payload: bytes) -> Dict[str, Any]:
    """Explain a byte stream in terms a human can check.

    Nothing here has been near a physical printer, so the useful thing is to
    make the stream inspectable: which control codes it contains, how wide the
    longest line is, and whether anything failed to encode. A dry run against
    this is how a wrong width or codepage gets caught before it wastes a roll
    of paper.
    """
    codes = []
    for name, seq in (("init", INIT), ("bold-on", BOLD_ON), ("center", ALIGN_CENTER),
                      ("double-size", SIZE_DOUBLE), ("tall", SIZE_TALL)):
        if seq in payload:
            codes.append(name)
    cut = next((n for n, seq in CUT_STYLES.items() if seq and payload.endswith(seq)), None)

    text = strip_control(payload)
    lines = [ln for ln in text.split(b"\n")]
    longest = max((len(ln) for ln in lines), default=0)
    return {
        "bytes": len(payload),
        "controlCodes": codes,
        "cutStyle": cut,
        "lines": len(lines),
        "longestLine": longest,
        # A '?' is what `errors="replace"` leaves behind — the signal that the
        # configured codepage couldn't represent something.
        "unencodableChars": text.count(b"?"),
        "preview": text.decode("ascii", "replace"),
    }


async def ping(host: str, port: int = DEFAULT_PORT, timeout: float = 3.0) -> Dict[str, Any]:
    """Can we open a socket to this printer right now?

    A station printer that's off or out of paper fails silently per job, one
    docket at a time, in the middle of service. This is the pre-service check
    that turns that into something you find out about at 4pm.
    """
    import time
    started = time.monotonic()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout)
    except (OSError, asyncio.TimeoutError) as e:
        return {"reachable": False, "error": str(e), "host": host, "port": port}
    writer.close()
    try:
        await asyncio.wait_for(writer.wait_closed(), timeout=timeout)
    except (OSError, asyncio.TimeoutError):
        pass
    return {"reachable": True, "host": host, "port": port,
            "latencyMs": round((time.monotonic() - started) * 1000, 1)}


def self_test(printer_name: str, width: int = DEFAULT_WIDTH,
              codepage: str = DEFAULT_CODEPAGE, cut: str = "partial") -> bytes:
    """A one-page test print that proves the settings are right.

    Prints the character ruler at the configured width, an accented string to
    show whether the codepage is correct, and ends with the configured cut —
    so a wrong width or codepage is visible on the paper rather than guessed.
    """
    out = bytearray(INIT)
    out += ALIGN_CENTER + SIZE_DOUBLE + BOLD_ON
    out += _text(_station_label(printer_name), codepage) + b"\n"
    out += BOLD_OFF + SIZE_NORMAL + ALIGN_LEFT
    out += _line("=", width, codepage)
    out += _text(f"NUA printer test - {width} cols, {codepage}", codepage) + b"\n"
    out += _line("-", width, codepage)
    # Ruler: if this wraps, the width setting is too wide for the paper.
    ruler = "".join(str(i % 10) for i in range(1, width + 1))
    out += _text(ruler, codepage) + b"\n"
    out += _text("Accents: Creme Brulee / Cafe / Rose", codepage) + b"\n"
    out += _text("Codepage: Crème Brûlée / Café / Rosé", codepage) + b"\n"
    out += _line("-", width, codepage)
    out += BOLD_ON + _text("BOLD SAMPLE", codepage) + b"\n" + BOLD_OFF
    out += SIZE_TALL + _text("TALL SAMPLE", codepage) + b"\n" + SIZE_NORMAL
    out += _line("=", width, codepage)
    out += _text(f"cut style: {cut}", codepage) + b"\n"
    out += FEED_3 + CUT_STYLES.get(cut, CUT_STYLES["partial"])
    return bytes(out)


async def printer_target(printer_name: str, business_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Look up a configured network address for a station printer."""
    from database import db
    from middleware.actor_context import tenant_scope_filter
    row = await db.printer_targets.find_one(
        {"printer": printer_name, **tenant_scope_filter(business_id)}, {"_id": 0})
    if row and row.get("host"):
        return row
    return None
