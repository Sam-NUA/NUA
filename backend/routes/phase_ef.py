"""Phase E + F — Deeper Ash autonomy + Nomni-gap features.

E: auto-publish roster (within budget), auto-confirm SMS queue, auto-VIP tagging,
voice intents 'void last item' / 'raise espresso 50 cents'
F: AI Phone Agent, auto-PO generation, live menu A/B testing, guest 'your usual'
"""
from fastapi import APIRouter, HTTPException, Request, Response, Depends
from deps import get_user, require_owner, require_owner_or_manager
from database import db
from middleware.actor_context import tenant_scope_filter, tenant_owns, tenant_owns_strict
from datetime import datetime, timezone
from typing import Optional, Any
from collections import Counter, defaultdict
import uuid
import os
import json

router = APIRouter()


# =============================================================================
# CONFIG — owner-controlled thresholds for Ash autonomy
# =============================================================================
DEFAULT_AUTONOMY = {
    "autoPublishRoster": False,
    "autoPublishBudgetCap": 5000.0,
    "autoConfirmSMS": True,
    "autoVipThresholdSpend": 500.0,
    "autoVipThresholdVisits": 10,
    "autoReorderThreshold": 5,
    "abTestingEnabled": True,
}


async def _get_autonomy_config(business_id=None) -> dict:
    """Was a single global `{"id": "default"}` document shared by every
    business on the deployment; see services/tenant_settings.py."""
    from services.tenant_settings import get_scoped_singleton
    cfg = await get_scoped_singleton(db.agent_autonomy, {"id": "default"}, business_id)
    return cfg or {"id": "default", **DEFAULT_AUTONOMY}


@router.get("/agent/autonomy")
async def get_autonomy(user: dict = Depends(get_user)):
    return await _get_autonomy_config(user.get("businessId"))


@router.put("/agent/autonomy")
async def update_autonomy(data: dict, user: dict = Depends(require_owner)):
    from services.tenant_settings import set_scoped_singleton
    update = {k: v for k, v in data.items() if k in DEFAULT_AUTONOMY}
    await set_scoped_singleton(db.agent_autonomy, {"id": "default"}, update, user.get("businessId"))
    return {"updated": update}


# =============================================================================
# E1 — AUTO-VIP TAGGING
# =============================================================================
async def auto_tag_vips(business_id: str = None):
    cfg = await _get_autonomy_config(business_id)
    promoted = []
    customers = await db.customers.find(tenant_scope_filter(business_id), {"_id": 0}).to_list(5000)
    for c in customers:
        spend = float(c.get("totalSpent", 0) or 0)
        visits = int(c.get("visits", 0) or 0)
        current_tier = c.get("membershipTier", "Bronze")
        if spend >= cfg.get("autoVipThresholdSpend", 500) and visits >= cfg.get("autoVipThresholdVisits", 10):
            if current_tier != "VIP":
                await db.customers.update_one({**tenant_scope_filter(business_id), "id": c["id"]}, {"$set": {"membershipTier": "VIP", "vipPromotedAt": datetime.now(timezone.utc).isoformat()}})
                promoted.append({"id": c["id"], "name": c.get("name"), "from": current_tier})
    return promoted


# =============================================================================
# E2 — AUTO-CONFIRM SMS QUEUE
# =============================================================================
@router.get("/comms/sms-queue")
async def get_sms_queue(user: dict = Depends(require_owner_or_manager)):
    q = await db.sms_queue.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}).sort("createdAt", -1).to_list(200)
    return q


async def queue_sms(to: str, name: str, body: str, kind: str = "manual", business_id: str = None):
    msg = {
        "id": f"SMS-{str(uuid.uuid4())[:8].upper()}",
        "to": to, "name": name, "body": body, "kind": kind,
        "status": "queued",  # will be 'sent' after Twilio integration
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "businessId": business_id,
    }
    await db.sms_queue.insert_one(msg)
    msg.pop("_id", None)
    return msg


@router.post("/comms/auto-confirm/{reservation_id}")
async def auto_confirm_reservation(reservation_id: str, user: dict = Depends(get_user)):
    res = await db.reservations.find_one({"$and": [{"id": reservation_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not res or not tenant_owns_strict(res.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Reservation not found")
    phone = res.get("guestPhone") or res.get("phone") or res.get("customerPhone") or ""
    if not phone:
        raise HTTPException(status_code=400, detail="No phone on reservation")
    name = res.get("guestName") or res.get("customerName") or "guest"
    body = (f"Hi {name}, your booking for {res.get('partySize','?')} on "
            f"{res.get('date','?')} at {res.get('time','?')} is confirmed at NUA. Reply C to cancel.")
    msg = await queue_sms(phone, name, body, "reservation_confirm", business_id=user.get("businessId"))
    await db.reservations.update_one({"$and": [{"id": reservation_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": {"confirmationSent": True, "confirmationAt": msg["createdAt"]}})
    return msg


# =============================================================================
# E3 — VOICE COMMAND ROUTER EXTENSIONS (void last item, raise price)
# =============================================================================
@router.post("/agent/voice-extended")
async def voice_extended(data: dict, user: dict = Depends(get_user)):
    """Extended voice routing for commands the basic router doesn't handle.
    Specifically: 'void last item', 'raise espresso 50 cents', '86 the croissant'."""
    text = (data.get("text") or "").lower().strip()
    if not text:
        raise HTTPException(status_code=400, detail="text required")

    import re
    # Pattern 1: "void last item" / "remove last"
    if re.search(r"\b(void|remove|delete)\s+(the\s+)?last\s+(item|product|line)?\b", text):
        return {"intent": "void_last_item", "instruction": {"action": "void_last_item"}}

    # Pattern 2: "raise espresso by 50 cents" / "drop latte 1 dollar"
    # Try cents/dollars suffix FIRST so "50 cents" doesn't match plain "$50"
    m = re.search(r"\b(raise|drop|lower|increase|reduce)\s+(.+?)\s+(?:by\s+)?(\d+(?:\.\d{1,2})?\s*cents?|\d+(?:\.\d{1,2})?\s*dollars?|\$\d+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\b", text)
    if m:
        direction = 1 if m.group(1) in ("raise", "increase") else -1
        product_name = m.group(2).strip()
        amount_str = m.group(3).strip()
        # Parse amount
        amount_str_lower = amount_str.lower().replace("$", "").strip()
        nums = re.findall(r"\d+(?:\.\d+)?", amount_str_lower)
        if not nums:
            return {"intent": "price_change", "error": "Could not parse amount"}
        n = float(nums[0])
        if "cent" in amount_str_lower:
            amount = n / 100
        elif "dollar" in amount_str_lower or amount_str.startswith("$"):
            amount = n
        else:
            # Plain number — if integer < 10 assume dollars, otherwise cents
            amount = n if n < 100 else n / 100
        delta = direction * amount
        # Find product — scoped to the caller's own business, so a voice
        # command can never reprice another business's product of the
        # same name.
        biz_scope = tenant_scope_filter(user.get("businessId"))
        product = await db.products.find_one(
            {"name": {"$regex": f"^{product_name}", "$options": "i"}, **biz_scope}, {"_id": 0})
        if not product:
            return {"intent": "price_change", "error": f"Product '{product_name}' not found"}
        new_price = max(0.01, round(float(product.get("price", 0)) + delta, 2))
        if user["role"] in ("owner", "manager"):
            await db.products.update_one({"id": product["id"]}, {"$set": {"price": new_price, "lastPriceChange": {"by": user["id"], "delta": delta, "at": datetime.now(timezone.utc).isoformat(), "reason": "voice command"}}})
            await db.agent_decisions.insert_one({
                "id": f"AGT-{str(uuid.uuid4())[:8].upper()}",
                "actionType": "price_change",
                "summary": f"Price of {product['name']} changed by ${delta:+.2f} → ${new_price:.2f}",
                "payload": {"productId": product["id"], "delta": delta, "newPrice": new_price, "by": "voice"},
                "status": "executed",
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "businessId": user.get("businessId"),
            })
            return {"intent": "price_change", "productId": product["id"], "productName": product["name"], "oldPrice": product["price"], "newPrice": new_price}
        return {"intent": "price_change", "error": "Owner/Manager only"}

    # Pattern 3: "86 the croissant" — mark out-of-stock
    m = re.search(r"\b86\s+(the\s+)?(.+?)$", text)
    if m:
        product_name = m.group(2).strip().rstrip("s")
        product = await db.products.find_one(
            {"name": {"$regex": f"^{product_name}", "$options": "i"}, **tenant_scope_filter(user.get("businessId"))},
            {"_id": 0})
        if product and user["role"] in ("owner", "manager"):
            await db.products.update_one({"id": product["id"]}, {"$set": {"stock": 0, "eightySixed": True, "eightySixedAt": datetime.now(timezone.utc).isoformat()}})
            return {"intent": "eighty_six", "productId": product["id"], "productName": product["name"]}

    return {"intent": "unknown", "transcript": text}


# =============================================================================
# E4 — AUTO-PUBLISH ROSTER (within budget cap)
# =============================================================================
@router.post("/agent/auto-publish-roster")
async def auto_publish_roster(data: dict, request: Request, user: dict = Depends(require_owner_or_manager)):
    cfg = await _get_autonomy_config(user.get("businessId"))
    if not cfg.get("autoPublishRoster", False):
        raise HTTPException(status_code=400, detail="Auto-publish roster disabled in autonomy config")

    week_start = data.get("weekStart")
    # Generate via existing auto_roster
    from routes.v15_features import auto_roster
    proposal = await auto_roster({"weekStart": week_start}, request)
    shifts = proposal.get("suggestions", []) if isinstance(proposal, dict) else []
    # Estimate cost — scoped to this business's own staff, so budget-cap
    # math is never contaminated by another business's pay rates.
    staff_pay = {s["id"]: s.get("payRate", 0) for s in
                 await db.auth_users.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}).to_list(500)}
    cost = 0.0
    for s in shifts:
        start = list(map(int, s.get("startTime", "0:0").split(":")))
        end = list(map(int, s.get("endTime", "0:0").split(":")))
        hours = max((end[0] + end[1] / 60) - (start[0] + start[1] / 60), 0)
        cost += hours * float(staff_pay.get(s.get("staffId"), 0))

    cap = float(cfg.get("autoPublishBudgetCap", 5000))
    if cost > cap:
        return {"published": False, "reason": f"Estimated cost ${cost:.2f} exceeds cap ${cap:.2f}", "estimatedCost": cost}

    # Commit
    for s in shifts:
        shift = {**s, "id": f"SHIFT-{str(uuid.uuid4())[:8].upper()}", "createdAt": datetime.now(timezone.utc).isoformat(),
                 "autoPublished": True, "businessId": user.get("businessId")}
        shift.pop("aiGenerated", None)
        await db.roster_shifts.insert_one(shift)
    await db.agent_decisions.insert_one({
        "id": f"AGT-{str(uuid.uuid4())[:8].upper()}",
        "actionType": "roster_auto_published",
        "summary": f"Auto-published {len(shifts)} shifts (cost ${cost:.2f} within ${cap:.2f} cap)",
        "payload": {"shiftCount": len(shifts), "cost": cost},
        "status": "executed",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "businessId": user.get("businessId"),
    })
    return {"published": True, "shifts": len(shifts), "estimatedCost": cost}


# =============================================================================
# F1 — AI PHONE AGENT (inbound voice agent)
# =============================================================================
def _match_product_by_name(products: list, name: str) -> Optional[dict]:
    """Best-effort match of a spoken item name against this business's own
    catalogue — exact (case-insensitive) match first, then a substring
    match either direction ("latte" matches "Iced Latte" and vice versa).
    Returns None rather than guessing when nothing reasonable matches."""
    n = name.strip().lower()
    if not n:
        return None
    for p in products:
        if (p.get("name") or "").strip().lower() == n:
            return p
    for p in products:
        pn = (p.get("name") or "").strip().lower()
        if pn and (n in pn or pn in n):
            return p
    return None



@router.get("/phone-agent/calls")
async def get_calls(user: dict = Depends(require_owner_or_manager)):
    calls = await db.phone_calls.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}).sort("startedAt", -1).to_list(200)
    return calls


@router.post("/phone-agent/simulate")
async def simulate_call(data: dict, user: dict = Depends(get_user)):
    """Simulate an inbound call. Sends transcript to LLM, returns intent + actions taken."""
    caller = data.get("caller", "Unknown")
    transcript = data.get("transcript", "").strip()
    if not transcript:
        raise HTTPException(status_code=400, detail="transcript required")
    call = {
        "id": f"CALL-{str(uuid.uuid4())[:8].upper()}",
        "caller": caller, "transcript": transcript,
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "businessId": user.get("businessId"),
    }

    # Resolve the caller ID against the CRM before doing anything else, so a
    # regular is recognised on pickup — the agent can greet them by name, and
    # any booking it takes lands on their existing profile instead of creating
    # a nameless duplicate. Digit-normalized, so the caller ID format doesn't
    # have to match how the number was saved.
    known_guest = None
    try:
        from services.guest_intel import lookup as guest_lookup
        found = await guest_lookup(phone=caller, limit=1, with_intel=True,
                                    business_id=user.get("businessId"))
        known_guest = found[0] if found else None
    except Exception:
        known_guest = None
    if known_guest:
        call["customerId"] = known_guest["customerId"]
        call["guestName"] = known_guest["name"]
        call["knownGuest"] = known_guest

    # Classify with LLM
    # Explicit annotation: a bare dict literal mixing a str value with an
    # empty list infers the list's element type as Sequence[str] (mypy
    # treats str itself as Sequence[str] and joins the two), which then
    # rejects every later .append(<dict>) call below as attr-defined.
    intent_result: dict[str, Any] = {"intent": "unknown", "actions": []}
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        # Give the agent the caller's history so it doesn't ask a regular for
        # details the restaurant already knows.
        guest_context = ""
        if known_guest:
            bits = [f"The caller is {known_guest['name']}, a returning guest."]
            if known_guest.get("lastVisit", {}) and known_guest["lastVisit"].get("date"):
                bits.append(f"Last visited {known_guest['lastVisit']['date']}.")
            if known_guest.get("topItems"):
                bits.append("Usually orders: " + ", ".join(i["name"] for i in known_guest["topItems"][:3]) + ".")
            if known_guest.get("frequentRequests"):
                bits.append("Usual request: " + known_guest["frequentRequests"][0]["request"] + ".")
            for p in known_guest.get("standingPreferences", []):
                if p["type"] == "allergy":
                    bits.append(f"ALLERGY: {p['value']}.")
            bits.append("Use their name; default the booking name to it unless they give another.")
            guest_context = " " + " ".join(bits)
        # Venue-local date, not the server's — see services/venue_time.py.
        # A guest saying "today"/"tomorrow" means relative to the
        # restaurant's own clock, not wherever this process happens to run.
        from services.venue_time import venue_now_for_business
        venue_today = (await venue_now_for_business(user.get("businessId"))).date().isoformat()
        chat = LlmChat(
            api_key=os.environ.get("EMERGENT_LLM_KEY"),
            session_id=f"phone-{call['id']}",
            system_message=(
                "You are an AI phone agent for NUA restaurant. Given a caller transcript, return STRICT JSON: "
                '{"intent":"reservation|order|inquiry|other","details":{"partySize":2,"date":"YYYY-MM-DD","time":"19:00","name":"...","items":[{"name":"...","qty":1}],"question":"..."}}. '
                "Only fill details that match. Today is " + venue_today
                + guest_context
            ),
        )
        chat.with_model("openai", "gpt-5.2")
        resp = await chat.send_message(UserMessage(text=transcript))
        try:
            parsed = json.loads(resp.strip().strip("`").strip())
        except Exception:
            import re
            m = re.search(r"\{.*\}", resp, re.DOTALL)
            parsed = json.loads(m.group(0)) if m else {"intent": "unknown"}
        intent_result["intent"] = parsed.get("intent", "unknown")
        details = parsed.get("details", {})

        # Take action based on intent
        if parsed.get("intent") == "reservation" and details.get("date"):
            # Same booking-rules engine routes/voice_inbound.py's real
            # inbound calls and every web/staff booking go through —
            # capacity, blackout dates, booking window, party-size tiers —
            # instead of a bare insert_one that skipped all of it. Found
            # during the Trust Release final readiness audit: this was the
            # one other place (besides the real inbound-call webhook) that
            # created a reservation with none of those checks.
            from services.booking_rules_engine import (
                validate_and_enrich_booking, BookingRuleViolation, capacity_lock)
            from services.cancellation_policy import snapshot_cutoff_hours
            party_size = int(details.get("partySize", 2) or 2)
            booking_time = details.get("time", "19:00")
            enrichment = None
            r = None
            try:
                async with capacity_lock(user.get("businessId"), details["date"]):
                    enrichment = await validate_and_enrich_booking(
                        date=details["date"], time=booking_time, party_size=party_size,
                        source="phone", business_id=user.get("businessId"),
                    )
                    r = {
                        "id": f"RES-{str(uuid.uuid4())[:8].upper()}",
                        # A recognised caller keeps their CRM name even if the
                        # transcript never spelled it out.
                        "guestName": details.get("name") or (known_guest or {}).get("name") or caller,
                        "guestPhone": caller,
                        "partySize": party_size,
                        "date": details["date"],
                        "time": booking_time,
                        "status": "confirmed",
                        "source": "ai_phone_agent",
                        "createdAt": datetime.now(timezone.utc).isoformat(),
                        "businessId": user.get("businessId"),
                        "cancellationCutoffHours": await snapshot_cutoff_hours(user.get("businessId")),
                        **enrichment,
                    }
                    if known_guest:
                        # Link it to the profile so this booking joins their history.
                        r["customerId"] = known_guest["customerId"]
                        r["guestEmail"] = known_guest.get("email") or None
                        await db.customers.update_one(
                            {**tenant_scope_filter(user.get("businessId")), "id": known_guest["customerId"]},
                            {"$push": {"reservationIds": r["id"]}},
                        )
                    await db.reservations.insert_one(r)
            except BookingRuleViolation as e:
                intent_result["actions"].append({"action": "reservation_rejected", "reason": str(e)})
                r = None
            except TimeoutError as e:
                intent_result["actions"].append({"action": "reservation_rejected", "reason": str(e)})
                r = None
            if r is not None:
                intent_result["actions"].append({
                    "action": "reservation_created", "id": r["id"],
                    "customerId": r.get("customerId"),
                    "recognisedGuest": bool(known_guest),
                })
                # Auto-confirm SMS
                await queue_sms(caller, r["guestName"], f"Booking confirmed: {r['date']} at {r['time']} for {r['partySize']} at NUA.",
                                 "phone_agent", business_id=user.get("businessId"))
        elif parsed.get("intent") == "order":
            # Previously this only appended a logged {"action":
            # "order_drafted", "items": [...]} entry — no real order was
            # ever created, regardless of the UI copy implying the phone
            # agent drafts real orders from live calls. Match each spoken
            # item name against this business's own real catalogue and,
            # for whatever matches, actually send it to the kitchen —
            # same mechanism a kiosk or accepted online order uses
            # (services/channel_orders.create_ticket), so a phone-in order
            # shows up on the KDS like any other. Unmatched items are
            # reported, never silently dropped or guessed at.
            raw_items = details.get("items", [])
            business_id = user.get("businessId")
            catalogue = await db.products.find(
                {"$and": [tenant_scope_filter(business_id), {"active": {"$ne": False}}]},
                {"_id": 0, "id": 1, "name": 1, "price": 1},
            ).to_list(2000)
            matched, unmatched = [], []
            for raw in raw_items:
                name = (raw.get("name") or "").strip()
                if not name:
                    continue
                qty = int(raw.get("qty") or 1)
                prod = _match_product_by_name(catalogue, name)
                if prod:
                    matched.append({
                        "productId": prod["id"], "productName": prod["name"],
                        "quantity": qty, "price": prod.get("price", 0), "modifiers": [],
                    })
                else:
                    unmatched.append(name)
            ticket = None
            if matched:
                from services import channel_orders
                ticket = await channel_orders.create_ticket(
                    matched, order_type="takeaway", source="phone_agent",
                    guest_name=details.get("name") or (known_guest or {}).get("name") or caller,
                    external_id=call["id"], actor="AI Phone Agent",
                    business_id=business_id,
                )
            intent_result["actions"].append({
                "action": "order_created" if ticket else "order_drafted",
                "items": matched, "unmatchedItems": unmatched,
                "kitchenOrderId": (ticket or {}).get("id"),
            })
        elif parsed.get("intent") == "inquiry":
            intent_result["actions"].append({"action": "inquiry_logged", "question": details.get("question", "")})
        intent_result["details"] = details
    except Exception as e:
        intent_result["error"] = str(e)[:200]

    call.update(intent_result)
    call["endedAt"] = datetime.now(timezone.utc).isoformat()
    await db.phone_calls.insert_one(call)
    call.pop("_id", None)
    return call


# =============================================================================
# F2 — AUTO PO GENERATION
# =============================================================================
@router.get("/purchase-orders")
async def get_pos_list(user: dict = Depends(require_owner_or_manager)):
    pos = await db.purchase_orders.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}).sort("createdAt", -1).to_list(200)
    return pos


@router.post("/purchase-orders/generate")
async def generate_po(user: dict = Depends(require_owner_or_manager)):
    """Auto-generate purchase orders from low-stock products grouped by supplier."""
    cfg = await _get_autonomy_config(user.get("businessId"))
    threshold = int(cfg.get("autoReorderThreshold", 5))
    low = await db.products.find(
        {"stock": {"$lte": threshold}, "active": {"$ne": False}, **tenant_scope_filter(user.get("businessId"))},
        {"_id": 0}).to_list(500)

    # Group by supplier (fallback "Default Supplier")
    by_supplier = defaultdict(list)
    for p in low:
        sup = p.get("supplier") or "Default Supplier"
        # Reorder qty = (reorderLevel or 50) - stock
        target = int(p.get("reorderLevel", 50))
        qty = max(target - int(p.get("stock", 0)), 1)
        by_supplier[sup].append({"productId": p["id"], "productName": p["name"],
                                  "category": p.get("category") or "Uncategorised",
                                  "currentStock": p.get("stock", 0), "orderQty": qty,
                                  "unitCost": p.get("cost", 0)})

    pos_list = []
    for sup, items in by_supplier.items():
        total = sum((i["orderQty"] * float(i["unitCost"] or 0)) for i in items)
        po = {
            "id": f"PO-{str(uuid.uuid4())[:8].upper()}",
            "supplier": sup,
            "items": items,
            "totalCost": round(total, 2),
            "status": "draft",
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "createdBy": user["id"],
            "businessId": user.get("businessId"),
        }
        await db.purchase_orders.insert_one(po)
        po.pop("_id", None)
        pos_list.append(po)
    if pos_list:
        await db.agent_decisions.insert_one({
            "id": f"AGT-{str(uuid.uuid4())[:8].upper()}",
            "actionType": "po_generated",
            "summary": f"Auto-generated {len(pos_list)} purchase orders for {len(low)} low-stock items",
            "payload": {"supplierCount": len(pos_list), "itemCount": len(low)},
            "status": "executed",
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "businessId": user.get("businessId"),
        })
    return {"created": len(pos_list), "purchaseOrders": pos_list}


async def _resolve_supplier_email(po: dict) -> Optional[dict]:
    """POs land in this collection with two different shapes depending on
    which path created them — analytics.py's strict-model POST stamps a
    real supplierId, phase_ef's own auto-generate only ever had a raw
    supplier NAME string. Try the id first, fall back to a name match, so
    "send" works for a PO regardless of which flow created it."""
    biz_scope = tenant_scope_filter(po.get("businessId"))
    supplier_id = po.get("supplierId")
    if supplier_id:
        supplier = await db.suppliers.find_one({"id": supplier_id, **biz_scope}, {"_id": 0})
        if supplier:
            return supplier
    supplier_name = po.get("supplier") or po.get("supplierName")
    if supplier_name:
        return await db.suppliers.find_one({"name": supplier_name, **biz_scope}, {"_id": 0})
    return None


def _po_email_body(po: dict) -> str:
    lines = [f"Purchase order {po.get('id')}", ""]
    for item in po.get("items", []):
        qty = item.get("orderQty") or item.get("quantity") or 0
        name = item.get("productName") or item.get("name") or "Item"
        lines.append(f"  {qty} x {name}")
    if po.get("notes"):
        lines.append("")
        lines.append(f"Notes: {po['notes']}")
    return "\n".join(lines)


@router.post("/purchase-orders/{po_id}/{action}")
async def update_po(po_id: str, action: str, user: dict = Depends(require_owner_or_manager)):
    if action not in ("approve", "send", "receive", "cancel"):
        raise HTTPException(status_code=400, detail="Invalid action")
    guard = await db.purchase_orders.find_one({"$and": [{"id": po_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "id": 1, "businessId": 1})
    if guard is None or not tenant_owns(guard.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="PO not found")
    status_map = {"approve": "approved", "send": "sent", "receive": "received", "cancel": "cancelled"}
    update = {"status": status_map[action], f"{action}dAt": datetime.now(timezone.utc).isoformat()}

    email_result = None
    if action == "send":
        # "send" used to just flip a status flag — nothing was ever actually
        # communicated to the supplier, so a PO marked "sent" was a false
        # signal a human still had to remember to call or email it in
        # themselves. This is the actual last mile: attempt a real email,
        # and record the real outcome (delivered / not_configured / no
        # supplier on file) instead of a status flip that implies more than
        # what happened.
        existing = await db.purchase_orders.find_one({"$and": [{"id": po_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
        if not existing:
            raise HTTPException(status_code=404, detail="PO not found")
        supplier = await _resolve_supplier_email(existing)
        if supplier and supplier.get("email"):
            from utils.notifications import send_email
            email_result = await send_email(
                supplier["email"], f"Purchase order {po_id}", _po_email_body(existing))
        else:
            email_result = {"channel": "email", "delivered": False, "reason": "no_supplier_email_on_file"}
        update["emailResult"] = email_result

    po = await db.purchase_orders.find_one_and_update({"$and": [{"id": po_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": update}, return_document=True)
    if not po:
        raise HTTPException(status_code=404, detail="PO not found")
    # On receive: increment stock
    if action == "receive":
        for item in po.get("items", []):
            await db.products.update_one({"id": item["productId"]}, {"$inc": {"stock": item.get("orderQty", 0)}})
    po.pop("_id", None)
    return po


@router.patch("/purchase-orders/{po_id}")
async def edit_po(po_id: str, data: dict, user: dict = Depends(require_owner)):
    """Owner-only edit of a PO's line items (quantities, unit costs, adding
    or dropping a line) before it's gone out to the supplier — auto-generated
    quantities are a starting point, not always what the owner actually
    wants to order. Locked once the PO has been sent, received, or
    cancelled: at that point the supplier (or the stock ledger, on receive)
    has already acted on the original numbers, so editing in place would
    silently disagree with what actually happened."""
    po = await db.purchase_orders.find_one({"$and": [{"id": po_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not po or not tenant_owns(po.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="PO not found")
    if po["status"] not in ("draft", "approved"):
        raise HTTPException(status_code=409, detail=f"Can't edit a PO that's already {po['status']}")

    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=400, detail="items must be a non-empty list")

    cleaned = []
    for it in items:
        qty = int(it.get("orderQty") or 0)
        cost = float(it.get("unitCost") or 0)
        if qty <= 0:
            raise HTTPException(status_code=400, detail=f"orderQty must be positive for {it.get('productName', 'an item')}")
        if cost < 0:
            raise HTTPException(status_code=400, detail=f"unitCost can't be negative for {it.get('productName', 'an item')}")
        cleaned.append({
            "productId": it.get("productId"), "productName": it.get("productName") or "Item",
            "category": it.get("category") or "Uncategorised",
            "currentStock": it.get("currentStock", 0), "orderQty": qty, "unitCost": cost,
        })
    total = round(sum(i["orderQty"] * i["unitCost"] for i in cleaned), 2)

    update = {"items": cleaned, "totalCost": total,
              "editedAt": datetime.now(timezone.utc).isoformat(), "editedBy": user["id"]}
    updated = await db.purchase_orders.find_one_and_update(
        {"$and": [{"id": po_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": update}, return_document=True)
    updated.pop("_id", None)
    return updated


@router.get("/purchase-orders/{po_id}/pdf")
async def po_pdf(po_id: str, user: dict = Depends(require_owner_or_manager)):
    """Category-grouped order sheet — a supplier rep (or whoever's packing
    the van) works off one category at a time, not a flat alphabetical
    dump, so items are grouped and subtotalled by category with the grand
    total at the end. Tolerates both PO item shapes this collection holds
    (see _resolve_supplier_email above) — auto-generated items use
    orderQty/productName, the legacy analytics.py POST path uses
    quantity/name."""
    from routes.finalize import _pdf_from_lines
    po = await db.purchase_orders.find_one({"$and": [{"id": po_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not po or not tenant_owns(po.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="PO not found")

    by_category = defaultdict(list)
    for it in po.get("items", []):
        by_category[it.get("category") or "Uncategorised"].append(it)

    lines = []
    for cat in sorted(by_category.keys()):
        items = by_category[cat]
        lines.append(f"— {cat} —")
        cat_total = 0.0
        for it in items:
            qty = it.get("orderQty") or it.get("quantity") or 0
            name = it.get("productName") or it.get("name") or "Item"
            cost = float(it.get("unitCost") or it.get("price") or 0)
            line_total = qty * cost
            cat_total += line_total
            lines.append(f"   {name:<35s} {qty:>4}x @ ${cost:>7.2f}  =  ${line_total:>8.2f}")
        lines.append(f"   Subtotal: ${cat_total:.2f}")
        lines.append("")

    supplier_label = po.get("supplier") or po.get("supplierName") or ""
    pdf = _pdf_from_lines(
        f"Purchase Order · {supplier_label}", lines,
        meta={"PO #": po["id"], "Status": po.get("status", "draft"),
              "Total": f"${po.get('totalCost', 0):.2f}"},
    )
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{po["id"]}.pdf"'})


# =============================================================================
# F3 — LIVE MENU A/B TESTING
# =============================================================================
@router.get("/ab-tests")
async def get_ab_tests(user: dict = Depends(require_owner_or_manager)):
    tests = await db.ab_tests.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}).sort("createdAt", -1).to_list(100)
    return tests


@router.post("/ab-tests")
async def create_ab_test(data: dict, user: dict = Depends(require_owner_or_manager)):
    test = {
        "id": f"AB-{str(uuid.uuid4())[:8].upper()}",
        "productId": data.get("productId"),
        "variantA": data.get("variantA", {}),  # { name, price, description }
        "variantB": data.get("variantB", {}),
        "metric": data.get("metric", "conversions"),  # conversions | revenue | aov
        "status": "running",
        "exposures": {"A": 0, "B": 0},
        "conversions": {"A": 0, "B": 0},
        "revenue": {"A": 0.0, "B": 0.0},
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "businessId": user.get("businessId"),
    }
    await db.ab_tests.insert_one(test)
    test.pop("_id", None)
    return test


@router.post("/ab-tests/{test_id}/exposure")
async def record_exposure(test_id: str, data: dict):
    """Public-facing endpoint — table-side QR / public menu calls this."""
    variant = data.get("variant", "A")
    if variant not in ("A", "B"):
        raise HTTPException(status_code=400, detail="variant must be A or B")
    await db.ab_tests.update_one({"id": test_id}, {"$inc": {f"exposures.{variant}": 1}})
    return {"recorded": True}


@router.post("/ab-tests/{test_id}/conversion")
async def record_conversion(test_id: str, data: dict):
    """Called when a customer adds the variant to cart / purchases."""
    variant = data.get("variant", "A")
    revenue = float(data.get("revenue", 0) or 0)
    if variant not in ("A", "B"):
        raise HTTPException(status_code=400, detail="variant must be A or B")
    await db.ab_tests.update_one({"id": test_id}, {"$inc": {f"conversions.{variant}": 1, f"revenue.{variant}": revenue}})
    return {"recorded": True}


@router.post("/ab-tests/{test_id}/conclude")
async def conclude_test(test_id: str, user: dict = Depends(require_owner_or_manager)):
    test = await db.ab_tests.find_one({"$and": [{"id": test_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not test or not tenant_owns_strict(test.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Not found")
    # Winner = higher conversion rate
    ea, eb = max(test["exposures"]["A"], 1), max(test["exposures"]["B"], 1)
    ca, cb = test["conversions"]["A"], test["conversions"]["B"]
    rate_a, rate_b = ca / ea, cb / eb
    winner = "A" if rate_a >= rate_b else "B"
    await db.ab_tests.update_one({"$and": [{"id": test_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": {"status": "concluded", "winner": winner, "concludedAt": datetime.now(timezone.utc).isoformat()}})
    return {"winner": winner, "rates": {"A": rate_a, "B": rate_b}}


# =============================================================================
# F4 — GUEST PREDICTIVE "YOUR USUAL"
# =============================================================================
@router.get("/customers/{customer_id}/your-usual")
async def your_usual(customer_id: str, user: dict = Depends(get_user)):
    biz_scope = tenant_scope_filter(user.get("businessId"))
    # Find customer's most-frequent items from transactions
    tx = await db.transactions.find(
        {"customerId": customer_id, **biz_scope}, {"_id": 0, "items": 1, "createdAt": 1}
    ).sort("createdAt", -1).limit(20).to_list(20)
    if not tx:
        return {"items": [], "reason": "no purchase history"}
    counter = Counter()
    for t in tx:
        for it in t.get("items", []):
            pid = it.get("productId")
            if not pid: continue
            counter[pid] += int(it.get("quantity", 1))
    top_ids = [pid for pid, _ in counter.most_common(3)]
    products = []
    for pid in top_ids:
        p = await db.products.find_one({"id": pid, **biz_scope}, {"_id": 0})
        if p:
            products.append({"id": pid, "name": p.get("name"), "price": p.get("price"), "image": p.get("image"), "category": p.get("category"), "frequency": counter[pid]})
    return {"items": products, "basedOn": len(tx), "reason": f"Most-frequent items from last {len(tx)} orders"}


# =============================================================================
# Hook into Ash agent tick — add E+F autonomous rules
# =============================================================================
@router.post("/agent/tick-extended")
async def tick_extended(request: Request, user: dict = Depends(require_owner_or_manager)):
    """Runs Phase E + F autonomous decisions in addition to base tick."""
    cfg = await _get_autonomy_config(user.get("businessId"))
    biz = user.get("businessId")
    biz_scope = tenant_scope_filter(biz)
    out = {"decisions": []}

    # 1. Auto-VIP tagging
    promoted = await auto_tag_vips(biz)
    if promoted:
        d = {
            "id": f"AGT-{str(uuid.uuid4())[:8].upper()}",
            "actionType": "vip_promoted",
            "summary": f"Auto-promoted {len(promoted)} customers to VIP",
            "payload": {"promoted": promoted},
            "status": "executed",
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "businessId": biz,
        }
        await db.agent_decisions.insert_one(d)
        out["decisions"].append({**d})

    # 2. Auto-confirm SMS for pending reservations
    if cfg.get("autoConfirmSMS", True):
        pending = await db.reservations.find(
            {"confirmationSent": {"$ne": True}, "phone": {"$exists": True, "$ne": ""}, **biz_scope},
            {"_id": 0}).to_list(50)
        for r in pending:
            try:
                # A plain dict standing in for the user object — this runs
                # as a background tick, not a real HTTP call, so there's no
                # request to derive one from (the previous code passed the
                # raw Request object here, which auto_confirm_reservation
                # never actually used until this pass added a businessId
                # check to it).
                await auto_confirm_reservation(r["id"], {"businessId": biz})
            except Exception:
                pass
        if pending:
            d = {
                "id": f"AGT-{str(uuid.uuid4())[:8].upper()}",
                "actionType": "sms_auto_confirmed",
                "summary": f"Queued {len(pending)} reservation confirmation SMS",
                "payload": {"count": len(pending)},
                "status": "executed",
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "businessId": biz,
            }
            await db.agent_decisions.insert_one(d)
            out["decisions"].append({**d})

    # 3. Auto-PO generation when many low-stock items
    threshold = int(cfg.get("autoReorderThreshold", 5))
    low_count = await db.products.count_documents({"stock": {"$lte": threshold}, "active": {"$ne": False}, **biz_scope})
    if low_count >= 3:  # auto-generate when 3+ low
        try:
            r = await generate_po(user)
            out["decisions"].append({"actionType": "po_generated", "summary": f"Auto-generated {r['created']} POs for {low_count} low-stock items"})
        except Exception:
            pass

    return out
