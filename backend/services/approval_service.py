"""
Approval Queue — high-risk automated actions land here first.

Policy config via env
─────────────────────
AI_APPROVAL_MODE       thresholds | strict | off      (default: thresholds)
AI_APPROVE_PO_ABOVE    dollar amount                  (default: 500)
AI_APPROVE_REFUND_ABOVE                              (default: 100)
AI_APPROVE_TIER_DOWNGRADES  1|0                       (default: 1)

Usage
─────
`await enqueue_or_execute(action_type, params, execute_fn, actor="ash")`

If the policy requires approval, we insert a pending Approval and return
`{status: "pending_approval", approvalId: ..., autoExecuted: False}`.
Otherwise `execute_fn(params)` is awaited and the outcome returned.
"""
from __future__ import annotations
from typing import Callable, Awaitable, Dict, Any, Optional
from datetime import datetime, timezone
from database import db
from services import audit_service
import os
import uuid
import logging

logger = logging.getLogger(__name__)


def _env_float(k: str, default: float) -> float:
    try:
        return float(os.environ.get(k, default))
    except Exception:
        return default


def _mode() -> str:
    return (os.environ.get("AI_APPROVAL_MODE") or "thresholds").lower()


def requires_approval(action_type: str, params: Dict[str, Any]) -> bool:
    mode = _mode()
    if mode == "off":
        return False
    if mode == "strict":
        return True
    # thresholds mode
    if action_type == "create_purchase_order":
        # sum quantities × unit-cost proxy — fall back on `total` or `estimatedCost`
        est = float(params.get("estimatedCost") or params.get("total") or 0)
        if est == 0 and params.get("quantity"):
            est = float(params["quantity"]) * float(params.get("unitCost") or 25)
        return est > _env_float("AI_APPROVE_PO_ABOVE", 500)
    if action_type in ("issue_refund", "refund", "auto_refund"):
        return float(params.get("amount") or 0) > _env_float("AI_APPROVE_REFUND_ABOVE", 100)
    if action_type == "upgrade_vip_tier":
        # downgrades always need approval
        tier_order = {"Bronze": 0, "Silver": 1, "Gold": 2, "Platinum": 3, "VIP": 4}
        prev = params.get("previousTier"); new = params.get("tier")
        if prev and new and tier_order.get(new, 0) < tier_order.get(prev, 0):
            return bool(int(_env_float("AI_APPROVE_TIER_DOWNGRADES", 1)))
    if action_type == "apply_discount":
        return float(params.get("discount") or 0) > 25.0     # any >25% needs approval
    if action_type == "post_journal":
        total = sum(float(l.get("debit") or 0) for l in (params.get("lines") or []))
        return total > 2000.0
    return False


async def enqueue_approval(*, action_type: str, params: Dict[str, Any],
                           requested_by: str = "system",
                           source: str = "rules_engine",
                           source_ref: Optional[str] = None,
                           context: Optional[Dict[str, Any]] = None,
                           business_id: Optional[str] = None) -> Dict[str, Any]:
    # None of the current callers (nua.py's marketing-approval route,
    # nua_tools.py's agent-tool gate, rules_engine.py's rule-action gate)
    # pass business_id explicitly — every one of them runs inside a request
    # that has an actor context, so this defaults to that the same way
    # notification_service.send() does, rather than requiring each call
    # site to be updated individually.
    if business_id is None:
        from middleware.actor_context import get_actor_context
        business_id = get_actor_context().get("businessId")
    doc = {
        "id": str(uuid.uuid4()),
        "actionType": action_type,
        "params": params,
        "requestedBy": requested_by,
        "source": source,
        "sourceRef": source_ref,
        "context": context or {},
        "status": "pending",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "resolvedAt": None,
        "resolvedBy": None,
        "resolution": None,
        "outcome": None,
        "businessId": business_id,
    }
    await db.approvals.insert_one(dict(doc))
    await audit_service.log_event(
        entity_type="approval",
        entity_id=doc["id"],
        action="created",
        after=doc,
        memo=f"Approval requested for {action_type}",
        severity="notice",
    )
    return doc


async def enqueue_or_execute(
    *, action_type: str,
    params: Dict[str, Any],
    execute_fn: Callable[[Dict[str, Any]], Awaitable[Any]],
    source: str = "rules_engine",
    source_ref: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    requested_by: str = "system",
) -> Dict[str, Any]:
    if requires_approval(action_type, params):
        appr = await enqueue_approval(
            action_type=action_type, params=params,
            requested_by=requested_by, source=source,
            source_ref=source_ref, context=context,
        )
        return {"status": "pending_approval", "approvalId": appr["id"], "autoExecuted": False}
    outcome = await execute_fn(params)
    return {"status": "executed", "autoExecuted": True, "outcome": outcome}


async def approve(approval_id: str, *, actor: str, execute_fn: Callable[[Dict[str, Any]], Awaitable[Any]]) -> Dict[str, Any]:
    appr = await db.approvals.find_one({"id": approval_id}, {"_id": 0})
    if not appr:
        raise ValueError("Approval not found")
    if appr["status"] != "pending":
        raise ValueError(f"Approval already {appr['status']}")
    try:
        outcome = await execute_fn(appr["params"])
    except Exception as e:
        outcome = {"error": str(e)}
    upd = {
        "status": "approved",
        "resolvedAt": datetime.now(timezone.utc).isoformat(),
        "resolvedBy": actor,
        "outcome": outcome,
    }
    await db.approvals.update_one({"id": approval_id}, {"$set": upd})
    doc = {**appr, **upd}
    await audit_service.log_event(
        entity_type="approval", entity_id=approval_id,
        action="updated", before=appr, after=doc,
        memo="Approval approved & executed", severity="notice",
    )
    if appr.get("source") == "ash_agent":
        try:
            from services import nua_trust  # lazy: nua_tools -> approval_service, avoid the cycle
            await nua_trust.record_decision(appr["actionType"], "approved", approval_id,
                                             business_id=appr.get("businessId"))
        except Exception:
            logger.warning(f"[trust] record_decision failed for {approval_id}", exc_info=True)
    return doc


async def reject(approval_id: str, *, actor: str, reason: Optional[str] = None) -> Dict[str, Any]:
    appr = await db.approvals.find_one({"id": approval_id}, {"_id": 0})
    if not appr:
        raise ValueError("Approval not found")
    if appr["status"] != "pending":
        raise ValueError(f"Approval already {appr['status']}")
    upd = {
        "status": "rejected",
        "resolvedAt": datetime.now(timezone.utc).isoformat(),
        "resolvedBy": actor,
        "resolution": reason,
    }
    await db.approvals.update_one({"id": approval_id}, {"$set": upd})
    doc = {**appr, **upd}
    await audit_service.log_event(
        entity_type="approval", entity_id=approval_id,
        action="updated", before=appr, after=doc,
        memo=f"Approval rejected: {reason}", severity="warning",
    )
    if appr.get("source") == "ash_agent":
        try:
            from services import nua_trust
            await nua_trust.record_decision(appr["actionType"], "rejected", approval_id,
                                             business_id=appr.get("businessId"))
        except Exception:
            logger.warning(f"[trust] record_decision failed for {approval_id}", exc_info=True)
    return doc
