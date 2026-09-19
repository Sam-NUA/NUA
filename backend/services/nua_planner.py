"""
Ash Planner — turns a goal into a multi-step, tool-backed plan.

A `plan` is a persisted, owner-approvable sequence of tool_call steps.
Ash proposes them; the owner (or an autonomous persona) executes step-by-step,
each step still respecting the tool-permission gate (auto | approval | disabled).

Lifecycle
─────────
draft → proposed → approved (whole) OR per-step approve/reject → executing → completed
                → rejected

Design decisions
────────────────
• Steps are stored inline on the plan (not a separate collection) so a plan
  is atomic and easy to reason about.
• Approving a plan doesn't fire everything — it walks steps sequentially,
  routing each one through nua_tools.execute_tool which itself may enqueue
  to /approvals if the tool's permission is 'approval'.
• Rejection is terminal.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from database import db
from middleware.actor_context import get_actor_context, tenant_owns_strict
from services import nua_tools, nua_personas, audit_service
import json
import logging
import os
import uuid
import re
from middleware.actor_context import tenant_scope_filter

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


PLANNER_SYSTEM = """You are Ash's Planning Engine.

Given the owner's GOAL, propose a SHORT (2-6 step) plan of tool calls from the
available catalog. Each step must be executable — you MUST pick tools that
exist. Each step has:
  • tool       — the exact tool name from the catalog
  • args       — the arguments dictionary
  • rationale  — one sentence WHY this step

Order steps causally (read → decide → write). Prefer to open a plan with a
READ-ONLY tool (fetch_*, lookup_*) so the plan is grounded in real data before
proposing writes.

Reply with a SINGLE JSON object (no markdown fences, no prose):
{
  "goal": "<restated goal>",
  "rationale": "<one paragraph explaining the strategy>",
  "expectedOutcome": "<what success looks like>",
  "risk": "low|medium|high",
  "steps": [
    { "tool": "<name>", "args": { ... }, "rationale": "..." },
    ...
  ]
}
"""


async def _grounding_data() -> Dict[str, Any]:
    """Small snapshot of live state to inform the plan."""
    open_insights = await db.ash_insights.find(
        {"resolvedAt": None}, {"_id": 0}
    ).sort("createdAt", -1).limit(15).to_list(15)
    pending_approvals = await db.approvals.count_documents({"status": "pending"})
    return {
        "openInsights": [
            {"category": i.get("category"), "severity": i.get("severity"),
             "title": i.get("title"), "body": (i.get("body") or "")[:200]}
            for i in open_insights
        ],
        "pendingApprovals": pending_approvals,
    }


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Best-effort JSON extraction — tolerates markdown fences + unescaped newlines."""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).rstrip("`").strip()
    start = cleaned.find("{")
    if start == -1:
        return None
    depth = 0
    end = -1
    in_str = False
    escape = False
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end == -1:
        return None
    blob = cleaned[start:end + 1]
    try:
        return json.loads(blob)
    except Exception:
        try:
            return json.loads(re.sub(r"(?<!\\)\n", " ", blob))
        except Exception:
            return None


async def generate_plan(goal: str, *, actor: str, persona: Optional[str] = None) -> Dict[str, Any]:
    """Ask GPT-5.2 to propose a plan for the goal. Persist as draft."""
    persona_obj = nua_personas.get_persona(persona)
    visible_tools = nua_personas.filter_tools(nua_tools.catalog(), persona)
    ctx = await _grounding_data()

    prompt = f"""GOAL: {goal}

PERSONA: {persona_obj.label} — focus: {persona_obj.focus}

AVAILABLE TOOLS:
{json.dumps([{'name': t['name'], 'module': t['module'], 'risk': t['risk'],
              'params': t['parameters']} for t in visible_tools], indent=1)[:6000]}

LIVE CONTEXT:
{json.dumps(ctx, indent=1)[:3000]}

Propose the plan now (JSON only)."""

    parsed: Optional[Dict[str, Any]] = None
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        key = os.environ.get("EMERGENT_LLM_KEY")
        if not key:
            raise RuntimeError("EMERGENT_LLM_KEY missing")
        chat = LlmChat(api_key=key, session_id=f"ash-plan-{uuid.uuid4()}", system_message=PLANNER_SYSTEM)\
            .with_model("openai", "gpt-5.2")
        raw = await chat.send_message(UserMessage(text=prompt))
        parsed = _extract_json_object(raw)
    except Exception as e:
        logger.warning(f"[planner] LLM error, falling back to deterministic: {e}")

    if not parsed or not isinstance(parsed.get("steps"), list):
        # Deterministic fallback — a stub plan that at least surfaces the goal
        parsed = {
            "goal": goal,
            "rationale": "LLM unavailable — recording goal as an inspectable stub. Owner should refine or regenerate.",
            "expectedOutcome": "Goal captured for later planning.",
            "risk": "low",
            "steps": [
                {"tool": "fetch_open_insights", "args": {},
                 "rationale": "Review current insights before deciding next moves."},
            ],
        }

    # Validate every step points at a real tool the persona can invoke
    allowed = {t["name"] for t in visible_tools}
    valid_steps: List[Dict[str, Any]] = []
    for s in parsed.get("steps") or []:
        name = s.get("tool")
        if not name or name not in allowed:
            valid_steps.append({**s, "status": "invalid",
                                  "error": f"tool not permitted for {persona_obj.label}"})
            continue
        valid_steps.append({
            "tool": name,
            "args": s.get("args") or {},
            "rationale": s.get("rationale") or "",
            "status": "pending",
            "outcome": None,
            "approvalId": None,
        })

    plan = {
        "id": str(uuid.uuid4()),
        "goal": parsed.get("goal") or goal,
        "rationale": parsed.get("rationale") or "",
        "expectedOutcome": parsed.get("expectedOutcome") or "",
        "risk": parsed.get("risk") or "medium",
        "persona": persona_obj.id,
        "personaLabel": persona_obj.label,
        "steps": valid_steps,
        "status": "proposed",
        "createdBy": actor,
        "createdAt": _now(),
        "updatedAt": _now(),
        "businessId": get_actor_context().get("businessId"),
    }
    await db.ash_plans.insert_one(dict(plan))
    try:
        await audit_service.log_event(
            entity_type="ash_plan", entity_id=plan["id"],
            action="proposed",
            after={"goal": plan["goal"], "steps": len(valid_steps), "risk": plan["risk"]},
            memo=f"Ash proposed a {len(valid_steps)}-step plan",
            severity="notice", tags=["ash_planner", persona_obj.id],
        )
    except Exception:
        pass
    return plan


async def _execute_step(plan_id: str, idx: int, *, actor: str) -> Dict[str, Any]:
    """Run one step through the tool permission gate."""
    plan = await db.ash_plans.find_one({"$and": [{"id": plan_id}, tenant_scope_filter(get_actor_context().get("businessId"))]}, {"_id": 0})
    if not plan or not tenant_owns_strict(plan.get("businessId"), get_actor_context().get("businessId")):
        return {"error": "plan not found"}
    if idx < 0 or idx >= len(plan["steps"]):
        return {"error": "step out of range"}
    step = plan["steps"][idx]
    if step["status"] not in ("pending", "approved"):
        return {"error": f"step already {step['status']}"}
    # plan_id+idx also guards against a race between two near-simultaneous
    # calls to execute the same step (the status check above only catches
    # a *second*, later call — not one that reads "pending" before the
    # first call's own status update has committed).
    outcome = await nua_tools.execute_tool(step["tool"], step.get("args") or {}, actor=actor,
                                             idempotency_key=f"plan:{plan_id}:{idx}:{step['tool']}")
    new_status = ("pending_approval" if outcome.get("status") == "pending_approval"
                  else ("blocked" if outcome.get("status") == "blocked"
                        else ("executed" if outcome.get("status") == "executed" else "error")))
    approval_id = outcome.get("approvalId")
    plan["steps"][idx].update({
        "status": new_status,
        "outcome": outcome,
        "approvalId": approval_id,
        "executedAt": _now(),
    })
    # Roll up plan status
    statuses = [s["status"] for s in plan["steps"]]
    if any(s == "error" for s in statuses):
        plan["status"] = "partial_failed"
    elif all(s in ("executed", "blocked") for s in statuses):
        plan["status"] = "completed"
    elif any(s == "pending_approval" for s in statuses):
        plan["status"] = "awaiting_approvals"
    else:
        plan["status"] = "executing"
    plan["updatedAt"] = _now()
    await db.ash_plans.update_one({"$and": [{"id": plan_id}, tenant_scope_filter(get_actor_context().get("businessId"))]}, {"$set": plan})
    return outcome


async def approve_plan(plan_id: str, *, actor: str) -> Dict[str, Any]:
    """Walk every pending step. Each may execute directly, enqueue an approval, or be blocked."""
    plan = await db.ash_plans.find_one({"$and": [{"id": plan_id}, tenant_scope_filter(get_actor_context().get("businessId"))]}, {"_id": 0})
    if not plan or not tenant_owns_strict(plan.get("businessId"), get_actor_context().get("businessId")):
        return {"error": "plan not found"}
    if plan["status"] in ("completed", "rejected"):
        return {"error": f"plan already {plan['status']}"}
    outcomes = []
    for idx, step in enumerate(plan["steps"]):
        if step["status"] not in ("pending", "approved"):
            outcomes.append({"idx": idx, "skipped": step["status"]})
            continue
        outcome = await _execute_step(plan_id, idx, actor=actor)
        outcomes.append({"idx": idx, "outcome": outcome})
    updated = await db.ash_plans.find_one({"$and": [{"id": plan_id}, tenant_scope_filter(get_actor_context().get("businessId"))]}, {"_id": 0})
    try:
        await audit_service.log_event(
            entity_type="ash_plan", entity_id=plan_id,
            action="approved",
            after={"status": updated["status"], "outcomes": len(outcomes)},
            memo=f"Ash plan approved & walked ({updated['status']})",
            severity="notice", tags=["ash_planner"],
        )
    except Exception:
        pass
    return {"plan": updated, "walk": outcomes}


async def reject_plan(plan_id: str, *, actor: str, reason: Optional[str] = None) -> Dict[str, Any]:
    existing = await db.ash_plans.find_one({"$and": [{"id": plan_id}, tenant_scope_filter(get_actor_context().get("businessId"))]}, {"_id": 0, "id": 1, "businessId": 1})
    if existing is None or not tenant_owns_strict(existing.get("businessId"), get_actor_context().get("businessId")):
        return {"error": "plan not found"}
    r = await db.ash_plans.update_one(
        {"$and": [{"id": plan_id}, tenant_scope_filter(get_actor_context().get("businessId"))]},
        {"$set": {"status": "rejected", "rejectedBy": actor,
                    "rejectedAt": _now(), "rejectionReason": reason}},
    )
    if r.matched_count == 0:
        return {"error": "plan not found"}
    try:
        await audit_service.log_event(
            entity_type="ash_plan", entity_id=plan_id,
            action="rejected",
            after={"reason": reason},
            memo=f"Ash plan rejected by {actor}",
            severity="notice", tags=["ash_planner"],
        )
    except Exception:
        pass
    return await db.ash_plans.find_one({"$and": [{"id": plan_id}, tenant_scope_filter(get_actor_context().get("businessId"))]}, {"_id": 0})


async def approve_step(plan_id: str, idx: int, *, actor: str) -> Dict[str, Any]:
    return await _execute_step(plan_id, idx, actor=actor)


async def reject_step(plan_id: str, idx: int, *, actor: str, reason: Optional[str] = None) -> Dict[str, Any]:
    plan = await db.ash_plans.find_one({"$and": [{"id": plan_id}, tenant_scope_filter(get_actor_context().get("businessId"))]}, {"_id": 0})
    if not plan or not tenant_owns_strict(plan.get("businessId"), get_actor_context().get("businessId")):
        return {"error": "plan not found"}
    if idx < 0 or idx >= len(plan["steps"]):
        return {"error": "step out of range"}
    plan["steps"][idx].update({
        "status": "rejected",
        "rejectedBy": actor,
        "rejectedAt": _now(),
        "rejectionReason": reason,
    })
    statuses = [s["status"] for s in plan["steps"]]
    if all(s in ("rejected", "blocked") for s in statuses):
        plan["status"] = "rejected"
    plan["updatedAt"] = _now()
    await db.ash_plans.update_one({"$and": [{"id": plan_id}, tenant_scope_filter(get_actor_context().get("businessId"))]}, {"$set": plan})
    return plan


# ═════════════════════════════════════════════════════════════════════════
# Plan Simulation — dry-run any plan without side effects
# ═════════════════════════════════════════════════════════════════════════
_READ_ONLY_PREFIXES = ("fetch_", "lookup_", "generate_", "run_ash_scan")


def _is_read_only(tool_name: str) -> bool:
    return any(tool_name.startswith(p) or tool_name == p.rstrip("_")
               for p in _READ_ONLY_PREFIXES)


async def simulate_plan(plan_id: str, *, actor: str) -> Dict[str, Any]:
    """Dry-run a plan.
    • Read-only steps ARE executed (so grounding data is real).
    • Write steps are DESCRIBED — no db mutation, no approvals enqueued.
    • The LLM writes a projected-outcome narrative.
    """
    plan = await db.ash_plans.find_one({"$and": [{"id": plan_id}, tenant_scope_filter(get_actor_context().get("businessId"))]}, {"_id": 0})
    if not plan or not tenant_owns_strict(plan.get("businessId"), get_actor_context().get("businessId")):
        return {"error": "plan not found"}
    tool_map = {t.name: t for t in nua_tools.TOOLS.values()}
    simulated_steps: List[Dict[str, Any]] = []

    for step in plan["steps"]:
        name = step["tool"]
        args = step.get("args") or {}
        tool = tool_map.get(name)
        if not tool:
            simulated_steps.append({**step, "simStatus": "unknown_tool"})
            continue
        if _is_read_only(name):
            try:
                outcome = await tool.execute(args)
                simulated_steps.append({**step, "simStatus": "read",
                                         "simOutcome": outcome})
            except Exception as e:
                simulated_steps.append({**step, "simStatus": "read_error",
                                         "simOutcome": {"error": str(e)}})
        else:
            simulated_steps.append({
                **step, "simStatus": "would_write",
                "simOutcome": {
                    "description": f"WOULD invoke {name} with {args}",
                    "risk": tool.risk,
                    "impact": tool.expected_impact,
                    "permission": tool.default_permission,
                    "sideEffect": tool.label,
                },
            })

    # LLM narrative — one call summarising outcomes
    narrative = None
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        key = os.environ.get("EMERGENT_LLM_KEY")
        if key:
            chat = LlmChat(api_key=key, session_id=f"ash-sim-{uuid.uuid4()}",
                            system_message="You are Ash's Simulator. Given a proposed plan and simulated outcomes, write 3-5 sentences describing what likely happens if the owner approves. Be concrete about revenue/cost/CSAT and flag any risks.")\
                .with_model("openai", "gpt-5.2")
            prompt = json.dumps({
                "goal": plan["goal"],
                "expectedOutcome": plan.get("expectedOutcome"),
                "steps": simulated_steps,
            }, default=str)[:5000]
            narrative = await chat.send_message(UserMessage(text=prompt))
    except Exception as e:
        logger.warning(f"[planner sim] LLM narrative fallback: {e}")

    if not narrative:
        writes = sum(1 for s in simulated_steps if s.get("simStatus") == "would_write")
        reads = sum(1 for s in simulated_steps if s.get("simStatus") == "read")
        narrative = (f"Simulation complete: {reads} read-only steps executed, "
                     f"{writes} write steps would fire but were not applied. "
                     f"Approve to run for real, or reject.")
    return {
        "planId": plan_id,
        "narrative": narrative,
        "simulatedSteps": simulated_steps,
        "simulatedAt": _now(),
        "simulatedBy": actor,
    }
