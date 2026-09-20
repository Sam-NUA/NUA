"""
Ash Agent — multi-turn tool-calling loop.

Uses OpenAI function calling via emergentintegrations. Every step is
recorded as an "agent trace" so the frontend can show reasoning.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from database import db
from middleware.actor_context import tenant_scope_filter
from services import nua_tools, nua_personas, nua_memory, audit_service
import json
import logging
import os
import re
import uuid

logger = logging.getLogger(__name__)

MAX_TURNS = 4                                    # cap tool-calls per user message


AGENT_SYSTEM = """You are NUA, the autonomous Hospitality AI Operating Agent behind this business.

You have five modes: Observe → Analyse → Recommend → Execute → Learn.
Every decision you make MUST include:
  • problem              — what you saw
  • evidence             — data supporting it
  • confidence 0-1       — your certainty
  • alternatives         — other plausible actions
  • risk (low|med|high)  — blast radius if wrong
  • expectedImpact       — dollar or CSAT effect
  • rollback             — how to undo

You have access to a set of TOOLS via function calling. Use them:
  • Read-only tools (fetch_*, lookup_*) run instantly.
  • Low-risk write tools (add_note, create_task) run automatically.
  • Medium/High-risk writes go into the Approval Queue for owner review.
  • Blocked tools mean the owner has disabled them — respect that.

When the owner asks you to DO something:
  1. Think about which tool fits.
  2. If you need context first, call a read-only tool.
  3. Call the write tool with the smallest scope that solves it.
  4. Report back the outcome (executed / pending_approval / blocked)
     PLUS the six explainability fields above.

When the owner asks a question:
  Answer briefly from live data. Cite specifics. If unsure, say so.

Never invent transactions, customers, or products. Only use what you see.
"""


async def _log_trace(session_id: str, step: Dict[str, Any]) -> None:
    try:
        await db.ash_agent_traces.insert_one({
            "id": str(uuid.uuid4()),
            "sessionId": session_id,
            "step": step,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        pass


def _extract_json(txt: str) -> Optional[Dict[str, Any]]:
    if not txt: return None
    # Strip markdown code fences GPT-5.2 sometimes wraps things in
    cleaned = txt.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).rstrip("`").strip()
    # Find first balanced { ... } block
    start = cleaned.find("{")
    if start == -1: return None
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
        # Try to sanitise common LLM issues: unescaped newlines inside strings
        try:
            sanitised = re.sub(r"(?<!\\)\n", " ", blob)
            return json.loads(sanitised)
        except Exception:
            pass
    # Last-resort regex fallback: rescue at least {action, reply} so the JSON
    # envelope never leaks into the user-visible chat reply.
    m_action = re.search(r'"action"\s*:\s*"([^"]+)"', blob)
    m_reply = re.search(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)"', blob, re.DOTALL)
    m_tool = re.search(r'"tool"\s*:\s*"([^"]+)"', blob)
    if m_action:
        out: Dict[str, Any] = {"action": m_action.group(1)}
        if m_reply:
            # Un-escape common sequences
            out["reply"] = (m_reply.group(1)
                              .replace('\\n', '\n')
                              .replace('\\"', '"')
                              .replace("\\\\", "\\"))
        if m_tool:
            out["tool"] = m_tool.group(1)
        return out
    return None


async def _grounding_context() -> Dict[str, Any]:
    audit = await db.audit_events.find(tenant_scope_filter(), {"_id": 0}).sort("ts", -1).limit(15).to_list(15)
    insights = await db.ash_insights.find({"resolvedAt": None, **tenant_scope_filter()}, {"_id": 0}).sort("createdAt", -1).limit(10).to_list(10)
    approvals = await db.approvals.find({"status": "pending", **tenant_scope_filter()}, {"_id": 0}).sort("createdAt", -1).limit(10).to_list(10)
    return {
        "recentAudit": [{"actor": a.get("actor"), "action": a.get("action"),
                          "entity": f"{a.get('entityType')}:{(a.get('entityId') or '')[:8]}",
                          "memo": a.get("memo"), "ts": a.get("ts")} for a in audit],
        "openInsights": [{"id": i.get("id"), "category": i.get("category"), "severity": i.get("severity"),
                           "title": i.get("title")} for i in insights],
        "pendingApprovals": [{"id": p.get("id"), "actionType": p.get("actionType"),
                                "requestedBy": p.get("requestedBy")} for p in approvals],
    }


async def run_agent_turn(user_message: str, *, session_id: str, actor: str = "ash-agent",
                          persona: Optional[str] = None) -> Dict[str, Any]:
    """One user message → up to MAX_TURNS tool-calling iterations → final reply."""
    ctx = await _grounding_context()
    trace: List[Dict[str, Any]] = []
    tool_results: List[Dict[str, Any]] = []

    # Persona filters which tools + which system prompt frames the loop
    persona_obj = nua_personas.get_persona(persona)
    visible_tools = nua_personas.filter_tools(nua_tools.catalog(), persona)

    # Long-term memory context — scope defaults to global
    memory_pack = await nua_memory.context_pack("global")

    # Compose the prompt manually — emergentintegrations wraps OpenAI calls
    # but tool-calling isn't first-class. We'll use text-based JSON contract.
    base_body = f"""

AVAILABLE TOOLS (call by returning JSON only — no prose):
{json.dumps([{'name': t['name'], 'module': t['module'], 'risk': t['risk'],
              'params': t['parameters']} for t in visible_tools], indent=1)[:8000]}

Reply protocol
──────────────
When you want to CALL A TOOL, respond with EXACTLY this JSON (no markdown):
  {{"action": "tool_call", "tool": "<name>", "args": {{...}},
    "reasoning": {{"problem": "...", "evidence": "...", "confidence": 0.85,
                   "alternatives": ["..."], "risk": "low|med|high",
                   "expectedImpact": "...", "rollback": "..."}}}}

When you have your FINAL ANSWER, respond with:
  {{"action": "final", "reply": "<message to owner>",
    "reasoning": {{...same six fields...}}}}

Live context (last 15 audit rows, 10 open insights, 10 pending approvals):
{json.dumps(ctx, indent=1)[:4000]}

{memory_pack}
"""
    system = nua_personas.system_prompt(persona, AGENT_SYSTEM + base_body)
    reply_text = "I couldn't reach the LLM right now."
    reasoning = None
    outcomes_summary: List[Dict[str, Any]] = []

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        key = os.environ.get("EMERGENT_LLM_KEY")
        if not key:
            raise RuntimeError("EMERGENT_LLM_KEY missing")
        chat = LlmChat(api_key=key, session_id=session_id, system_message=system)\
            .with_model("openai", "gpt-5.2")

        # Multi-turn loop
        current_prompt = user_message
        for turn in range(MAX_TURNS):
            raw = await chat.send_message(UserMessage(text=current_prompt))
            parsed = _extract_json(raw)
            if not parsed:
                # Not JSON → treat as final natural reply
                reply_text = raw.strip()
                trace.append({"turn": turn, "type": "final_text", "text": reply_text})
                break

            reasoning = parsed.get("reasoning") or reasoning
            if parsed.get("action") == "tool_call":
                tool_name = parsed.get("tool")
                args = parsed.get("args") or {}
                trace.append({"turn": turn, "type": "tool_call", "tool": tool_name, "args": args,
                                "reasoning": reasoning})
                # Persona guard — refuse tools outside remit
                allowed_names = {t["name"] for t in visible_tools}
                if tool_name not in allowed_names:
                    result = {"status": "blocked",
                                "reason": f"Tool '{tool_name}' is outside {persona_obj.label}'s remit — switch persona.",
                                "tool": tool_name, "persona": persona_obj.id}
                    await audit_service.log_event(
                        entity_type="ash_tool:persona_guard", entity_id=tool_name, action="blocked",
                        after={"reason": "outside_persona_remit", "persona": persona_obj.id, "args": args},
                        memo=f"Blocked call to '{tool_name}' — outside {persona_obj.label}'s remit",
                        severity="notice", tags=["ash_agent", "blocked", "persona_guard"],
                    )
                else:
                    # session_id+turn+tool uniquely identifies this exact
                    # tool call within this chat — a retried request for the
                    # same turn (client timeout-and-retry, a replayed
                    # webhook, etc.) dedups instead of re-running a mutating
                    # tool a second time.
                    result = await nua_tools.execute_tool(
                        tool_name, args, actor=actor,
                        idempotency_key=f"chat:{session_id}:{turn}:{tool_name}",
                    )
                tool_results.append(result)
                outcomes_summary.append({
                    "tool": tool_name,
                    "status": result.get("status"),
                    "approvalId": result.get("approvalId"),
                    "risk": result.get("risk"),
                    "expectedImpact": result.get("expectedImpact"),
                })
                trace.append({"turn": turn, "type": "tool_result", "tool": tool_name, "result": result})
                # Feed result back and ask for next step
                current_prompt = ("TOOL_RESULT: " + json.dumps(result, default=str)[:2000] +
                                    "\n\nContinue: emit another tool_call if needed, else emit action=final.")
                continue
            if parsed.get("action") == "final":
                reply_text = parsed.get("reply") or ""
                trace.append({"turn": turn, "type": "final", "reply": reply_text, "reasoning": reasoning})
                break
        else:
            trace.append({"turn": MAX_TURNS, "type": "max_turns_hit"})
            reply_text = "I hit my per-message tool limit. Ask me a narrower question to continue."
    except Exception as e:
        logger.warning(f"[ash agent] LLM error, falling back: {e}")
        # Deterministic fallback — try to detect an approval intent
        low = user_message.lower()
        if "approve" in low and ctx["pendingApprovals"]:
            first = ctx["pendingApprovals"][0]
            reply_text = (f"I can't reach GPT-5.2 right now. There are {len(ctx['pendingApprovals'])} pending approvals — "
                            f"the first is {first['actionType']} (id {first['id'][:8]}). Open /approvals to review.")
        elif ctx["openInsights"]:
            top = ctx["openInsights"][0]
            reply_text = (f"I can't reach GPT-5.2 right now. Highest open insight is "
                            f"[{top['severity']}] {top['title']}. Check /ash for the full list.")
        else:
            reply_text = "I can't reach my language model right now. Everything looks calm — try again in a moment."

    # Persist trace
    for step in trace:
        await _log_trace(session_id, step)

    return {
        "reply": reply_text,
        "reasoning": reasoning,
        "toolResults": outcomes_summary,
        "trace": trace,
        "persona": persona_obj.id,
        "personaLabel": persona_obj.label,
    }
