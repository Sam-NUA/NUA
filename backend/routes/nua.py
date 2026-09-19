"""
NUA — the autonomous operating layer endpoints (formerly `ash`).

Native prefix: /api/nua/*.  /api/ash/* still works via NuaAliasMiddleware
in server.py for backwards-compatibility.
"""
import logging
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
from database import db
from deps import get_user, require_owner_or_manager, require_owner, require_permission
from middleware.actor_context import tenant_scope_filter, tenant_owns_strict
from services import nua_intelligence

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/nua")


@router.get("/insights")
async def list_insights(
    category: Optional[str] = None,
    severity: Optional[str] = None,
    include_resolved: bool = False,
    limit: int = 200,
    user: dict = Depends(require_owner_or_manager),
):
    q = tenant_scope_filter(user.get("businessId"))
    if category: q["category"] = category
    if severity: q["severity"] = severity
    if not include_resolved:
        q["resolvedAt"] = None
    rows = await db.ash_insights.find(q, {"_id": 0}).sort("createdAt", -1).limit(limit).to_list(limit)
    return rows


@router.get("/insights/summary")
async def insights_summary(user: dict = Depends(require_owner_or_manager)):
    """Grouped counts for the dashboard."""
    pipeline = [
        {"$match": {"resolvedAt": None, **tenant_scope_filter(user.get("businessId"))}},
        {"$group": {"_id": {"category": "$category", "severity": "$severity"}, "count": {"$sum": 1}}},
    ]
    rows = await db.ash_insights.aggregate(pipeline).to_list(200)
    by_cat = {}
    for r in rows:
        c = r["_id"]["category"]; s = r["_id"]["severity"]
        by_cat.setdefault(c, {"info": 0, "notice": 0, "warning": 0, "high": 0})
        by_cat[c][s] = by_cat[c].get(s, 0) + r["count"]
    total = sum(sum(v.values()) for v in by_cat.values())
    high = sum(v.get("high", 0) for v in by_cat.values())
    warning = sum(v.get("warning", 0) for v in by_cat.values())
    return {"total": total, "high": high, "warning": warning, "byCategory": by_cat}


@router.post("/run")
async def run(include_summary: bool = False, user: dict = Depends(require_owner_or_manager)):
    """Manually trigger a full Ash pass — normally run on a cadence."""
    return await nua_intelligence.run_all_insights(include_summary=include_summary, business_id=user.get("businessId"))


@router.post("/insights/{iid}/dismiss")
async def dismiss_insight(iid: str, user: dict = Depends(require_owner_or_manager)):
    from datetime import datetime, timezone
    existing = await db.ash_insights.find_one({"$and": [{"id": iid}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "id": 1, "businessId": 1})
    if existing is None or not tenant_owns_strict(existing.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "Insight not found")
    r = await db.ash_insights.update_one({"$and": [{"id": iid}, tenant_scope_filter(user.get("businessId"))]}, {"$set": {"resolvedAt": datetime.now(timezone.utc).isoformat(), "resolvedBy": "manual"}})
    if r.matched_count == 0:
        raise HTTPException(404, "Insight not found")
    return {"dismissed": True}


@router.get("/capabilities")
async def capabilities(_: dict = Depends(get_user)):
    """Enumerate what Ash watches for — used by the intro dashboard card."""
    return {
        "capabilities": [
            {"key": "staffing",         "label": "Predict staffing shortages"},
            {"key": "theft",            "label": "Detect theft"},
            {"key": "fraud",            "label": "Detect fraud"},
            {"key": "pricing",          "label": "Recommend pricing"},
            {"key": "promotion",        "label": "Suggest promotions"},
            {"key": "waste",            "label": "Predict food waste"},
            {"key": "labour",           "label": "Detect unusual labour costs"},
            {"key": "menu",             "label": "Detect menu underperformance"},
            {"key": "weather",          "label": "Forecast weather impact"},
            {"key": "demand",           "label": "Forecast public holiday demand"},
            {"key": "purchasing",       "label": "Recommend purchasing"},
            {"key": "roster",           "label": "Recommend roster changes"},
            {"key": "burnout",          "label": "Predict staff burnout"},
            {"key": "churn",            "label": "Predict customer churn"},
            {"key": "menu_engineering", "label": "Recommend menu engineering"},
            {"key": "summary",          "label": "Auto-write weekly business summary"},
        ],
    }


# ═════════════════════════════════════════════════════════════════════════
# Scheduler + Digest
# ═════════════════════════════════════════════════════════════════════════
from services import nua_scheduler


@router.get("/scheduler/status")
async def scheduler_status(_: dict = Depends(get_user)):
    return await nua_scheduler.digest_status()


@router.post("/scheduler/digest-now")
async def force_digest(_: dict = Depends(require_owner_or_manager)):
    return await nua_scheduler.force_digest_now()


# ═════════════════════════════════════════════════════════════════════════
# Ash Chat — GPT-5.2 grounded on audit events + open insights
# ═════════════════════════════════════════════════════════════════════════
import os
import uuid as _uuid
from datetime import datetime, timezone


@router.post("/chat")
async def chat(body: dict, user: dict = Depends(require_permission("ash"))):
    """Conversational surface. Grounded on live audit events + Ash insights.

    Body: { message, sessionId?, context? }
    """
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "message is required")
    session_id = body.get("sessionId") or f"ash-chat-{_uuid.uuid4()}"

    # ── Pull grounding context (small enough to fit in a single prompt) ──
    biz_scope = tenant_scope_filter(user.get("businessId"))
    recent_audit = await db.audit_events.find(biz_scope, {"_id": 0}).sort("ts", -1).limit(30).to_list(30)
    open_insights = await db.ash_insights.find(
        {"resolvedAt": None, **biz_scope}, {"_id": 0}).sort("createdAt", -1).limit(20).to_list(20)
    pending_approvals = await db.approvals.count_documents({"status": "pending", **biz_scope})
    kpis_txn = await db.transactions.count_documents(biz_scope)

    system_prompt = f"""You are Ash, NUA's autonomous hospitality operating layer.

You have READ-ONLY access to the last 30 audit events and 20 open insights, provided below.
Answer the owner's question briefly and precisely. Cite specifics from the data when relevant.
If they ask "who changed X" or "what happened yesterday", scan the audit log for actor / entity / time.
If they ask "what should I do next", pick the highest-severity open insight and recommend its first recommendedAction.
Never invent transactions, staff, or customers not present in the data.
If the data doesn't contain the answer, say so honestly and suggest what to check.

Total transactions in system: {kpis_txn}. Pending approvals: {pending_approvals}.

RECENT AUDIT EVENTS (newest first):
{[{"ts": e.get("ts"), "actor": e.get("actor"), "action": e.get("action"),
   "entity": f"{e.get('entityType')}:{(e.get('entityId') or '')[:8]}",
   "memo": e.get("memo")} for e in recent_audit]}

OPEN INSIGHTS:
{[{"category": i.get("category"), "severity": i.get("severity"),
   "title": i.get("title"), "actions": [a.get("type") for a in (i.get("recommendedActions") or [])]}
  for i in open_insights]}
"""
    reply = None
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        key = os.environ.get("EMERGENT_LLM_KEY")
        if key:
            chat_client = LlmChat(api_key=key, session_id=session_id, system_message=system_prompt)\
                .with_model("openai", "gpt-5.2")
            reply = await chat_client.send_message(UserMessage(text=message))
    except Exception as e:
        logger.warning(f"[ash chat] LLM fell back: {e}")

    if not reply:
        # Deterministic fallback — surface the top open insight
        if open_insights:
            top = open_insights[0]
            reply = (f"I couldn't reach the LLM, but the top open insight is: "
                     f"[{top['severity']}] {top['title']} — {top['body']}. "
                     f"There are {pending_approvals} pending approvals waiting for you.")
        else:
            reply = ("I couldn't reach the LLM right now, and there are no open Ash insights. "
                     "Everything looks calm — check /finance for KPIs or /approvals for anything waiting on you.")

    doc = {
        "id": str(_uuid.uuid4()),
        "sessionId": session_id,
        "actor": user.get("email"),
        "message": message,
        "reply": reply,
        "context": {"auditRows": len(recent_audit), "openInsights": len(open_insights), "pendingApprovals": pending_approvals},
        "ts": datetime.now(timezone.utc).isoformat(),
        "businessId": user.get("businessId"),
    }
    try:
        await db.ash_chat_log.insert_one(dict(doc))
    except Exception:
        pass
    return {"sessionId": session_id, "reply": reply, "context": doc["context"]}


@router.get("/chat/history/{session_id}")
async def chat_history(session_id: str, limit: int = 40, user: dict = Depends(require_permission("ash"))):
    q = {"sessionId": session_id, **tenant_scope_filter(user.get("businessId"))}
    rows = await db.ash_chat_log.find(q, {"_id": 0}).sort("ts", 1).limit(limit).to_list(limit)
    return rows


# ═════════════════════════════════════════════════════════════════════════
# Ash v3.0 — Tool-calling Agent, Health Score, Daily Briefing, Permissions
# ═════════════════════════════════════════════════════════════════════════
from services import nua_tools, nua_agent, health_score, nua_briefing, nua_personas, nua_planner, nua_memory
from services import approval_service
import json


# ─── Memory ───────────────────────────────────────────────────────────────
@router.get("/memory")
async def list_memory(scope: Optional[str] = None, kind: Optional[str] = None,
                        limit: int = 100, _: dict = Depends(get_user)):
    return await nua_memory.list_memories(scope=scope, kind=kind, limit=limit)


@router.get("/memory/scopes")
async def memory_scopes(_: dict = Depends(get_user)):
    return await nua_memory.scope_counts()


@router.post("/memory")
async def create_memory(body: dict, user: dict = Depends(require_owner_or_manager)):
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "text is required")
    return await nua_memory.remember(
        text=text,
        scope=body.get("scope", "global"),
        kind=body.get("kind", "fact"),
        confidence=float(body.get("confidence") or 1.0),
        source="owner",
        tags=body.get("tags") or [],
        actor=user.get("email"),
    )


@router.delete("/memory/{memory_id}")
async def delete_memory(memory_id: str, user: dict = Depends(require_owner_or_manager)):
    ok = await nua_memory.forget(memory_id, actor=user.get("email"))
    if not ok:
        raise HTTPException(404, "memory not found")
    return {"deleted": True}


@router.get("/personas")
async def list_personas(_: dict = Depends(get_user)):
    """List available Ash personas — used by the persona picker in Ash Chat."""
    return nua_personas.catalog()


# ─── Planning Engine ──────────────────────────────────────────────────────
@router.post("/plans/generate")
async def generate_plan(body: dict, user: dict = Depends(require_owner_or_manager)):
    goal = (body.get("goal") or "").strip()
    if not goal:
        raise HTTPException(400, "goal is required")
    return await nua_planner.generate_plan(
        goal, actor=user.get("email") or "owner", persona=body.get("persona"),
    )


@router.get("/plans")
async def list_plans(status: Optional[str] = None, limit: int = 50, user: dict = Depends(get_user)):
    q: dict = tenant_scope_filter(user.get("businessId"))
    if status: q["status"] = status
    rows = await db.ash_plans.find(q, {"_id": 0}).sort("createdAt", -1).limit(limit).to_list(limit)
    return rows


@router.get("/plans/{plan_id}")
async def get_plan(plan_id: str, user: dict = Depends(get_user)):
    plan = await db.ash_plans.find_one({"$and": [{"id": plan_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not plan or not tenant_owns_strict(plan.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "plan not found")
    return plan


@router.post("/plans/{plan_id}/simulate")
async def simulate_plan(plan_id: str, user: dict = Depends(require_owner_or_manager)):
    """Dry-run — describes writes without executing them."""
    return await nua_planner.simulate_plan(plan_id, actor=user.get("email") or "owner")


@router.post("/plans/{plan_id}/approve")
async def approve_plan(plan_id: str, user: dict = Depends(require_owner_or_manager)):
    return await nua_planner.approve_plan(plan_id, actor=user.get("email") or "owner")


@router.post("/plans/{plan_id}/reject")
async def reject_plan(plan_id: str, body: dict, user: dict = Depends(require_owner_or_manager)):
    return await nua_planner.reject_plan(
        plan_id, actor=user.get("email") or "owner", reason=body.get("reason"),
    )


@router.post("/plans/{plan_id}/steps/{idx}/approve")
async def approve_step(plan_id: str, idx: int, user: dict = Depends(require_owner_or_manager)):
    return await nua_planner.approve_step(plan_id, idx, actor=user.get("email") or "owner")


@router.post("/plans/{plan_id}/steps/{idx}/reject")
async def reject_step(plan_id: str, idx: int, body: dict, user: dict = Depends(require_owner_or_manager)):
    return await nua_planner.reject_step(
        plan_id, idx, actor=user.get("email") or "owner", reason=body.get("reason"),
    )


# ═════════════════════════════════════════════════════════════════════════
# NUA Marketing — autonomous campaign draft → Approvals
# ═════════════════════════════════════════════════════════════════════════
@router.post("/marketing/draft-campaign")
async def draft_campaign(body: dict, user: dict = Depends(require_owner_or_manager)):
    """Have NUA Marketing draft a campaign end-to-end (segment, channel,
    copy, offer, dates) and enqueue it in the Approval Queue. The owner
    reviews the payload and clicks Approve to fire it — nothing goes out
    without human sign-off."""
    goal = (body.get("goal") or "").strip() or "Improve engagement over the next 14 days"
    context = body.get("context") or {}

    # ── Gather grounding data ──
    biz_scope = tenant_scope_filter(user.get("businessId"))
    try:
        churning = await db.customers.count_documents({**tenant_scope_filter(user.get("businessId")), "visits": {"$gte": 3}, **biz_scope})
    except Exception:
        churning = 0
    try:
        slow_products = await db.products.find(
            {"stock": {"$gt": 0}, **biz_scope}, {"_id": 0, "name": 1, "stock": 1, "category": 1},
        ).sort("stock", -1).limit(5).to_list(5)
    except Exception:
        slow_products = []

    prompt = (
        "You are NUA Marketing. Draft ONE campaign as strict JSON (no markdown).\n"
        f"GOAL: {goal}\n"
        f"AT-RISK COHORT: ~{churning} regulars\n"
        f"SLOW INVENTORY: {json.dumps(slow_products)[:600]}\n"
        f"EXTRA CONTEXT: {json.dumps(context)[:400]}\n\n"
        "Fields required in your JSON:\n"
        "  name, objective, segment (visits>=X or lapsed_30d etc.),\n"
        "  channel (sms|email|push|mixed), offer (voucher amount + label),\n"
        "  copy: {subject?, sms?, email?}, startDate (ISO), endDate (ISO),\n"
        "  expectedReach, expectedRedemption, expectedRevenue, risk (low|med|high),\n"
        "  reasoning (why this campaign now)."
    )

    parsed: Optional[dict] = None
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        import os as _os
        key = _os.environ.get("EMERGENT_LLM_KEY")
        if key:
            chat = LlmChat(api_key=key,
                            session_id=f"ash-marketing-{_uuid.uuid4()}",
                            system_message="You are NUA Marketing — a CMO who ships campaigns.")\
                .with_model("openai", "gpt-5.2")
            raw = await chat.send_message(UserMessage(text=prompt))
            parsed = nua_agent._extract_json(raw)
    except Exception:
        parsed = None

    if not parsed:
        # Deterministic fallback — never fail the endpoint
        parsed = {
            "name": "Autumn Regulars Warm-Up",
            "objective": goal,
            "segment": "visits>=3 AND lapsed_30d",
            "channel": "sms",
            "offer": {"type": "voucher", "value": 15, "label": "$15 comeback voucher"},
            "copy": {"sms": "We miss you at NUA. Here's $15 on your next visit — this weekend only."},
            "startDate": datetime.now(timezone.utc).isoformat(),
            "endDate": datetime.now(timezone.utc).isoformat(),
            "expectedReach": max(1, churning),
            "expectedRedemption": max(1, churning // 5),
            "expectedRevenue": max(1, churning // 5) * 40,
            "risk": "low",
            "reasoning": "LLM unavailable — deterministic warm-up template.",
        }

    # Enqueue in Approvals for owner sign-off
    approval = await approval_service.enqueue_approval(
        action_type="marketing.launch_campaign",
        params=parsed,
        requested_by=user.get("email") or "ash-marketing",
        source="ash_marketing",
        context={
            "confidence": 0.75,
            "reasoning": {
                "problem": "Retention decay in the regulars cohort.",
                "evidence": f"~{churning} regulars, slow inventory: {[p.get('name') for p in slow_products]}",
                "alternatives": ["Do nothing", "Broader push", "Per-tier tailored offers"],
                "risk": parsed.get("risk", "low"),
                "expectedImpact": f"${parsed.get('expectedRevenue', 0)} incremental revenue",
                "rollback": "Cancel the campaign before endDate; unclaimed vouchers auto-expire.",
            },
        },
    )

    try:
        from services import notification_service as ns
        await ns.send(role="owner", kind="marketing", severity="notice",
                        title=f"NUA drafted campaign: {parsed.get('name')}",
                        body=f"Expected ${parsed.get('expectedRevenue', 0)} revenue · risk {parsed.get('risk')}",
                        link="/approvals",
                        data={"approvalId": approval.get("id")})
    except Exception:
        pass

    return {"approval": approval, "campaign": parsed}


@router.post("/agent")
async def agent(body: dict, user: dict = Depends(require_permission("ash"))):
    """The Ash v3 tool-calling agent. Accepts { message, sessionId?, persona? } and may
    invoke up to 4 tool-calls before returning a final reply.
    """
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "message is required")
    session_id = body.get("sessionId") or f"ash-agent-{_uuid.uuid4()}"
    persona = body.get("persona")

    result = await nua_agent.run_agent_turn(
        message, session_id=session_id,
        actor=user.get("email") or "ash-agent",
        persona=persona,
    )

    doc = {
        "id": str(_uuid.uuid4()),
        "sessionId": session_id,
        "actor": user.get("email"),
        "persona": result.get("persona"),
        "message": message,
        "reply": result["reply"],
        "reasoning": result.get("reasoning"),
        "toolResults": result.get("toolResults"),
        "trace": result.get("trace"),
        "ts": datetime.now(timezone.utc).isoformat(),
        "businessId": user.get("businessId"),
    }
    try:
        await db.ash_agent_log.insert_one(dict(doc))
    except Exception:
        pass
    return {"sessionId": session_id, **result}


@router.get("/tools")
async def tool_catalog(user: dict = Depends(get_user)):
    """Enumerate available agent tools with current effective permissions."""
    from services import nua_trust
    catalog = nua_tools.catalog()
    overrides = {c["toolName"]: c for c in await db.ash_tool_config.find(
        tenant_scope_filter(user.get("businessId")), {"_id": 0}).to_list(200)}
    trust_settings = await nua_trust.get_settings()
    for t in catalog:
        cfg = overrides.get(t["name"]) or {}
        t["effectivePermission"] = cfg.get("permission") or t["defaultPermission"]
        t["promotedBy"] = cfg.get("promotedBy")
        trust = cfg.get("trust") or {}
        t["trust"] = {
            "consecutiveApproved": trust.get("consecutiveApproved", 0),
            "minStreak": trust_settings["minStreak"],
            "eligibleSince": trust.get("eligibleSince"),
            "totalApproved": trust.get("totalApproved", 0),
            "totalRejected": trust.get("totalRejected", 0),
        } if t["risk"] in ("low", "medium") else None
    return catalog


@router.post("/tools/{tool_name}/execute")
async def execute_tool(tool_name: str, body: dict, user: dict = Depends(require_owner_or_manager)):
    """Manual tool invocation with permission enforcement. Accepts an
    optional idempotencyKey so a retried/duplicated request doesn't run a
    mutating tool twice."""
    return await nua_tools.execute_tool(tool_name, body.get("args") or {}, actor=user.get("email"),
                                          idempotency_key=body.get("idempotencyKey"))


@router.put("/tools/{tool_name}/permission")
async def set_tool_permission(tool_name: str, body: dict, user: dict = Depends(require_owner_or_manager)):
    """Owner sets per-tool permission — 'auto' | 'approval' | 'disabled'."""
    perm = (body.get("permission") or "").lower()
    if perm not in ("auto", "approval", "disabled"):
        raise HTTPException(400, "permission must be auto|approval|disabled")
    tool = nua_tools.TOOLS.get(tool_name)
    if not tool:
        raise HTTPException(404, "Unknown tool")
    if perm == "auto" and tool.risk in nua_tools.HIGH_RISK_TIERS:
        raise HTTPException(400, f"'{tool_name}' is risk={tool.risk} — high/critical-risk tools can never be "
                                  f"set to auto-execute, regardless of who requests it")
    biz = user.get("businessId")
    await db.ash_tool_config.update_one(
        {"toolName": tool_name, **tenant_scope_filter(biz)},
        {"$set": {"toolName": tool_name, "permission": perm, "businessId": biz,
                    "updatedAt": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return {"toolName": tool_name, "permission": perm}


@router.get("/kill-switch")
async def get_kill_switch(_: dict = Depends(get_user)):
    """Current state of the global Ash kill switch."""
    return await nua_tools.get_kill_switch()


@router.post("/kill-switch")
async def set_kill_switch(body: dict, user: dict = Depends(require_owner)):
    """Owner-only: halt (or resume) every mutating/auto Ash tool execution
    across every entry point — chat, planner, direct API, and approved
    queue items — until explicitly released. Every toggle is audited."""
    enabled = bool(body.get("enabled"))
    return await nua_tools.set_kill_switch(enabled, actor=user.get("email") or "owner", reason=body.get("reason"))


# ═════════════════════════════════════════════════════════════════════════
# Graduated Trust — tools earn their way from approval-gated to auto
# ═════════════════════════════════════════════════════════════════════════
from services import nua_trust


@router.get("/trust/suggestions")
async def trust_suggestions(_: dict = Depends(get_user)):
    """Tools currently eligible for promotion but not yet promoted."""
    return await nua_trust.list_suggestions(_.get("businessId"))


@router.get("/trust/settings")
async def get_trust_settings(_: dict = Depends(get_user)):
    return await nua_trust.get_settings(_.get("businessId"))


@router.post("/trust/settings")
async def save_trust_settings(body: dict, _: dict = Depends(require_owner)):
    return await nua_trust.save_settings(body, _.get("businessId"))


@router.get("/tools/{tool_name}/trust")
async def tool_trust(tool_name: str, _: dict = Depends(get_user)):
    return await nua_trust.get_tool_trust(tool_name, _.get("businessId"))


@router.post("/tools/{tool_name}/promote")
async def promote_tool(tool_name: str, user: dict = Depends(require_owner)):
    """Owner-only: confirm a suggested promotion to auto. Promoting to full
    autonomy is a bigger call than the routine owner-or-manager permission
    toggle, so this is intentionally gated tighter."""
    try:
        return await nua_trust.promote(tool_name, actor=user.get("email") or "owner",
                                        business_id=user.get("businessId"))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/tools/auto-executions")
async def auto_executions(limit: int = 50, _: dict = Depends(get_user)):
    """Shadow-audit review feed: recent auto-tier tool calls, newest first,
    so an owner can spot-check what NUA ran unsupervised."""
    return await nua_trust.list_recent_executions(limit=min(max(limit, 1), 200), business_id=_.get("businessId"))


@router.post("/tools/executions/{audit_id}/flag")
async def flag_execution(audit_id: str, body: dict, user: dict = Depends(require_owner)):
    """Owner-only: flag one auto-executed action as wrong. Instantly demotes
    the tool back to approval-gated (see nua_trust.demote) and, if the tool
    exposes a rollback and the caller asked for one, attempts to undo it."""
    reason = (body or {}).get("reason")
    row = await db.audit_events.find_one({"$and": [{"id": audit_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not row or not tenant_owns_strict(row.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "Execution not found")
    tool_name = row.get("entityId")
    tool = nua_tools.TOOLS.get(tool_name)
    if not tool:
        raise HTTPException(400, "Not a recognized NUA tool execution")

    await db.audit_events.update_one(
        {"$and": [{"id": audit_id}, tenant_scope_filter(user.get("businessId"))]},
        {"$set": {"flagged": True, "flaggedBy": user.get("email"),
                  "flaggedAt": datetime.now(timezone.utc).isoformat(), "flagReason": reason}},
    )
    result = await nua_trust.demote(
        tool_name, actor=user.get("email") or "owner",
        reason=reason or "Flagged as wrong from the auto-execution review feed",
        business_id=user.get("businessId"),
    )

    undo = None
    if body.get("undo"):
        outcome = (row.get("after") or {}).get("outcome")
        if tool.rollback and outcome and not (isinstance(outcome, dict) and outcome.get("error")):
            try:
                await tool.rollback(outcome)
                undo = {"undone": True}
            except Exception as e:
                undo = {"undone": False, "error": str(e)}
        else:
            undo = {"undone": False, "error": "No rollback available for this action"}

    return {**result, "auditId": audit_id, "undo": undo}


@router.get("/health-score")
async def get_health_score(user: dict = Depends(require_owner_or_manager)):
    # Owner/manager only — the payload carries gross and net margin.
    # POST /briefing/regenerate below was already gated this way; these read
    # endpoints were simply missed, which let any authenticated account (a
    # cashier or kitchen login) pull the venue's margins straight from the API.
    return await health_score.compute_health(business_id=user.get("businessId"))


@router.get("/briefing")
async def get_briefing(force: bool = False, user: dict = Depends(require_owner_or_manager)):
    """Return today's briefing — cached in db.ash_briefings, regenerate if force=true.

    Owner/manager only: the narrative quotes revenue, forecast and margin.
    """
    today = datetime.now(timezone.utc).date().isoformat()
    biz = user.get("businessId")
    if not force:
        existing = await db.ash_briefings.find_one({"date": today, "businessId": biz}, {"_id": 0})
        if existing:
            return existing
    return await nua_briefing.generate_briefing(business_id=biz)


@router.post("/briefing/regenerate")
async def regenerate_briefing(user: dict = Depends(require_owner_or_manager)):
    return await nua_briefing.generate_briefing(business_id=user.get("businessId"))


@router.get("/agent/trace/{session_id}")
async def get_agent_trace(session_id: str, limit: int = 50, user: dict = Depends(require_permission("ash"))):
    q = {"sessionId": session_id, **tenant_scope_filter(user.get("businessId"))}
    rows = await db.ash_agent_traces.find(q, {"_id": 0}).sort("ts", 1).limit(limit).to_list(limit)
    return rows
