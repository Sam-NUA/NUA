"""
Approval Queue routes.
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
from database import db
from deps import get_user, require_owner_or_manager
from middleware.actor_context import tenant_scope_filter, tenant_owns_strict
from services import approval_service, rules_engine as re_svc

router = APIRouter(prefix="/approvals")


@router.get("")
async def list_approvals(status: Optional[str] = None, limit: int = 100, user: dict = Depends(get_user)):
    q = {"status": status} if status else {}
    q.update(tenant_scope_filter(user.get("businessId")))
    return await db.approvals.find(q, {"_id": 0}).sort("createdAt", -1).limit(limit).to_list(limit)


@router.get("/pending/count")
async def pending_count(user: dict = Depends(get_user)):
    q = {"status": "pending", **tenant_scope_filter(user.get("businessId"))}
    return {"count": await db.approvals.count_documents(q)}


@router.get("/{aid}")
async def get_approval(aid: str, user: dict = Depends(get_user)):
    doc = await db.approvals.find_one({"$and": [{"id": aid}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not doc or not tenant_owns_strict(doc.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "Approval not found")
    return doc


async def _execute_action(params: dict, action_type: str, rule_id: Optional[str] = None,
                           source: Optional[str] = None, business_id: Optional[str] = None) -> dict:
    """Look up a rule action (rules engine) or an NUA agent tool and execute it.

    Agent-tool approvals (source="ash_agent") are dispatched to nua_tools.TOOLS
    first — action_type is the tool name in that case, e.g. "issue_voucher".
    Everything else goes through the rules-engine ACTION_LIBRARY as before.
    Gated on source rather than name collision: a couple of names (issue_voucher,
    mark_dish_86) exist in both registries with slightly different param shapes,
    so we only redirect when we know the approval actually came from the agent.
    """
    if source == "ash_agent":
        from services import nua_tools, audit_service
        tool = nua_tools.TOOLS.get(action_type)
        if not tool:
            return {"error": f"Unknown agent tool: {action_type}"}
        # An approval can sit in the queue for a while before someone acts
        # on it — re-check the kill switch and the tool's current
        # permission at the moment of execution, not just at the moment it
        # was queued. Without this, an owner disabling a tool (or engaging
        # the global kill switch) after an approval was already enqueued
        # would not actually stop it from running once approved.
        kill_switch = await nua_tools.get_kill_switch()
        if kill_switch["enabled"]:
            await audit_service.log_event(
                entity_type=f"ash_tool:{tool.module}", entity_id=action_type, action="blocked",
                after={"reason": "kill_switch_engaged", "args": params}, memo=f"Blocked approved execution of '{action_type}' — Ash is globally paused",
                severity="warning", tags=["ash_agent", "blocked", "kill_switch"],
            )
            return {"error": "Ash is globally paused; this approved action was not executed", "blocked": True}
        perm = await nua_tools.resolve_permission(action_type)
        if perm == "disabled":
            await audit_service.log_event(
                entity_type=f"ash_tool:{tool.module}", entity_id=action_type, action="blocked",
                after={"reason": "disabled_by_policy", "args": params}, memo=f"Blocked approved execution of '{action_type}' — tool has since been disabled",
                severity="notice", tags=["ash_agent", "blocked", f"risk_{tool.risk}"],
            )
            return {"error": f"Tool '{action_type}' has since been disabled; this approved action was not executed", "blocked": True}
        return await tool.execute(params)
    if action_type == "marketing.launch_campaign":
        from routes.v25_suite import create_and_send_campaign_from_approval
        return await create_and_send_campaign_from_approval(params, created_by=source or "ash",
                                                              business_id=business_id)
    action_meta = re_svc.ACTION_LIBRARY.get(action_type)
    if not action_meta:
        return {"error": f"Unknown action {action_type}"}
    # Best-effort rule context for the handler
    rule = {"id": rule_id or "approval-exec", "name": "manual approval execute"}
    if rule_id:
        found = await db.rules.find_one({"id": rule_id}, {"_id": 0})
        if found:
            rule = found
    event = {"id": "approval", "type": "approval.executed", "payload": params}
    return await action_meta["fn"](rule, event, params)


@router.post("/{aid}/approve")
async def approve(aid: str, user: dict = Depends(require_owner_or_manager)):
    doc = await db.approvals.find_one({"$and": [{"id": aid}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not doc or not tenant_owns_strict(doc.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "Approval not found")

    async def exec_fn(params):
        return await _execute_action(params, doc["actionType"], doc.get("sourceRef"), doc.get("source"),
                                      business_id=doc.get("businessId"))

    try:
        return await approval_service.approve(aid, actor=user["email"], execute_fn=exec_fn)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{aid}/reject")
async def reject(aid: str, body: dict, user: dict = Depends(require_owner_or_manager)):
    doc = await db.approvals.find_one({"$and": [{"id": aid}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not doc or not tenant_owns_strict(doc.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "Approval not found")
    try:
        return await approval_service.reject(aid, actor=user["email"], reason=body.get("reason"))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/config/policy")
async def policy(_: dict = Depends(get_user)):
    import os
    return {
        "mode": os.environ.get("AI_APPROVAL_MODE", "thresholds"),
        "poAbove": float(os.environ.get("AI_APPROVE_PO_ABOVE", 500)),
        "refundAbove": float(os.environ.get("AI_APPROVE_REFUND_ABOVE", 100)),
        "tierDowngradesAlwaysApprove": bool(int(os.environ.get("AI_APPROVE_TIER_DOWNGRADES", 1))),
    }
