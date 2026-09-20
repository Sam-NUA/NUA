"""
Universal notification service.

Everything downstream (Loyalty earn events, Kitchen fire/ready pings,
Ash campaign proposals, approvals) writes through `send()`.

Delivery today
──────────────
• In-app bell — `db.notifications` fanned out by (email | role | topic).
• (Wire-ready) SMS / email — call `notify_out` which is a shim over the
  abstraction in utils/notifications.py; if credentials are absent it
  logs and no-ops, so the pipeline is always safe to call.

Model
─────
{ id, recipient: {email?, role?, topic?}, kind, title, body, link,
  data, severity, readAt, createdAt }

kind vocabulary  (keep small — the UI colours from this)
  loyalty | kitchen | approval | marketing | ash | referral | system
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from database import db
from services.retention import notification_expiry
import uuid
import logging

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def send(
    *,
    kind: str,
    title: str,
    body: str = "",
    email: Optional[str] = None,
    role: Optional[str] = None,
    topic: Optional[str] = None,
    link: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
    severity: str = "info",
    business_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Fan out ONE notification. At least one of email/role/topic is required
    so we always know who should see it. `role` = 'owner' | 'manager' |
    'cashier' | 'server' | 'kitchen'; `topic` for pub-sub-style channels
    like 'kitchen.station.grill'.

    business_id scopes a role/topic broadcast to one business — without it,
    a role broadcast ("all owners", "all cashiers") is not tied to any
    business at all, so every caller across the whole deployment sharing
    that role sees it. Every current caller sends this from inside a
    request that has an actor context (the request's own JWT), so this
    defaults to that rather than requiring every call site to be updated
    to pass it explicitly — falls back to None (unscoped, same as the old
    behavior) only if there's genuinely no actor context available."""
    if not any([email, role, topic]):
        raise ValueError("notification requires email, role, or topic")
    if business_id is None and (role or topic):
        from middleware.actor_context import get_actor_context
        business_id = get_actor_context().get("businessId")
    doc = {
        "id": str(uuid.uuid4()),
        "recipient": {"email": email, "role": role, "topic": topic},
        "kind": kind,
        "title": title,
        "body": body,
        "link": link,
        "data": data or {},
        "severity": severity,
        "readAt": None,
        "createdAt": _now(),
        "businessId": business_id,
        # 90 days by default (services/retention.py) — long enough to look
        # back on a season, not a permanent record.
        "expiresAt": notification_expiry(),
    }
    await db.notifications.insert_one(dict(doc))
    return doc


def _role_topic_scope(business_id: Optional[str]) -> Dict[str, Any]:
    """A role/topic-broadcast notification is only relevant to the caller's
    own business — this matches this business's tagged broadcasts plus any
    untagged ones (predating this fix, or genuinely business-agnostic
    system notices sent with no actor context), same backward-compat shape
    tenant_scope_filter uses elsewhere."""
    if not business_id:
        return {}
    return {"$or": [{"businessId": business_id}, {"businessId": None}, {"businessId": {"$exists": False}}]}


async def list_for(email: str, role: Optional[str] = None,
                    unread_only: bool = False, limit: int = 50,
                    business_id: Optional[str] = None) -> List[Dict[str, Any]]:
    scope = _role_topic_scope(business_id)
    conditions = [{"recipient.email": email}]
    if role:
        conditions.append({"recipient.role": role, **scope})
    # Owners are super-users — they see notifications routed to any role
    # so a marketing-scoped alert still lands on the owner's dashboard when
    # there's no dedicated marketing user account.
    if role == "owner":
        conditions.append({"recipient.role": {"$in": ["marketing", "manager", "server", "kitchen"]}, **scope})
    q: Dict[str, Any] = {"$or": conditions}
    if unread_only:
        q["readAt"] = None
    return await db.notifications.find(q, {"_id": 0}).sort("createdAt", -1).limit(limit).to_list(limit)


async def mark_read(notification_id: str, email: str) -> bool:
    r = await db.notifications.update_one(
        {"id": notification_id, "$or": [{"recipient.email": email},
                                          {"recipient.email": None}]},
        {"$set": {"readAt": _now()}},
    )
    return r.matched_count > 0


async def mark_all_read(email: str, role: Optional[str] = None,
                         business_id: Optional[str] = None) -> int:
    scope = _role_topic_scope(business_id)
    conditions = [{"recipient.email": email}]
    if role:
        conditions.append({"recipient.role": role, **scope})
    r = await db.notifications.update_many(
        {"$or": conditions, "readAt": None},
        {"$set": {"readAt": _now()}},
    )
    return r.modified_count


async def unread_count(email: str, role: Optional[str] = None,
                        business_id: Optional[str] = None) -> int:
    scope = _role_topic_scope(business_id)
    conditions = [{"recipient.email": email}]
    if role:
        conditions.append({"recipient.role": role, **scope})
    if role == "owner":
        conditions.append({"recipient.role": {"$in": ["marketing", "manager", "server", "kitchen"]}, **scope})
    return await db.notifications.count_documents({"$or": conditions, "readAt": None})
