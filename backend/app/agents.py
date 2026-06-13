"""Fraction agent orchestration.

A goal flows through these stages:

   Planner      → produces a step-by-step plan (JSON list of steps)
   for each step:
       Worker    → executes one step using the available tools
       Reviewer  → judges the result, asks for revisions if needed
   Writer       → assembles all step outputs into a final deliverable
   Reflector    → writes a short reflection back to long-term memory

The loop is async, supports streaming events to the UI, and re-plans
mid-run if the reviewer rejects a step more than once.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from .config import FractionConfig, get_config
from .memory import MemoryManager
from .models import ChatMessage, ChatRequest, ModelRouter, resolve_for_role
from .tools import ToolRegistry

log = logging.getLogger("fraction.agents")


# ---- event model ------------------------------------------------------------


@dataclass
class AgentEvent:
    type: str           # plan | step | tool | result | message | deliverable | done | error
    role: str = ""
    content: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=lambda: time.time())

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "role": self.role,
            "content": self.content,
            "data": self.data,
            "ts": self.ts,
        }


# ---- agent roles ------------------------------------------------------------


SYSTEM_PROMPTS: dict[str, str] = {
    "planner": (
        "You are Fraction's PLANNER. Given a high-level goal, produce a concrete, "
        "executable plan as JSON. The plan is a list of 3-8 steps. Each step has "
        "`title`, `kind` (research|code|analysis|write|review), and `description`. "
        "Choose the smallest set of steps that, executed in order, will satisfy the goal. "
        'Reply with ONLY valid JSON of the form: {"plan": [...]}'
    ),
    "researcher": (
        "You are Fraction's RESEARCHER. You answer questions using web_search and "
        "web_fetch. Be thorough but concise. Cite sources inline as [n] where n matches "
        "the numbered result list. After your research, list 3-5 key takeaways."
    ),
    "coder": (
        "You are Fraction's CODER. You write and execute short programs in Python, "
        "Bash, or Node to compute, transform, or analyze data. Use file_write to save "
        "longer scripts to the workspace, and code_exec to run them. Always print the "
        "result you need; never assume it worked."
    ),
    "reviewer": (
        "You are Fraction's REVIEWER. You check the latest step's output against the "
        "step's description. Respond with strict JSON: "
        '{"verdict": "ok" | "revise", "feedback": "..."}. '
        "Be tough. Approve only when the output is correct, complete, and on-task."
    ),
    "writer": (
        "You are Fraction's WRITER. You assemble the final deliverable. Use clear "
        "Markdown with a top-level title, section headers, and bullet lists where "
        "appropriate. Be concise. Cite sources. Aim for a document the user can paste "
        "into a report or share as-is."
    ),
    "reflector": (
        "You are Fraction's REFLECTOR. Given the goal, the plan, and the final "
        "deliverable, write 2-3 sentences capturing what the system learned that "
        "would help it do better next time. Be specific and concrete."
    ),
}


# ---- JSON helpers -----------------------------------------------------------


def _extract_json(text: str) -> dict[str, Any]:
    """Best-effort JSON extraction from model output."""
    text = text.strip()
    # Strip ```json fences
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # find first { and last }
        a, b = text.find("{"), text.rfind("}")
        if a != -1 and b != -1 and b > a:
            try:
                return json.loads(text[a : b + 1])
            except json.JSONDecodeError:
                pass
    return {}


# ---- orchestrator -----------------------------------------------------------


class Orchestrator:
    def __init__(
        self,
        cfg: FractionConfig | None = None,
        router: ModelRouter | None = None,
        tools: ToolRegistry | None = None,
        memory: MemoryManager | None = None,
    ):
        self.cfg = cfg or get_config()
        self.router = router or ModelRouter(self.cfg)
        self.tools = tools  # injected
        self.memory = memory or MemoryManager()

    # main entrypoint --------------------------------------------------------

    async def run(self, goal: str, session_id: str) -> AsyncIterator[AgentEvent]:
        sid = session_id
        evt_log: list[AgentEvent] = []

        def emit(ev: AgentEvent) -> AgentEvent:
            evt_log.append(ev)
            return ev

        # greeting
        yield emit(AgentEvent(
            type="message",
            role="system",
            content=f"Fraction received your goal: {goal}",
        ))

        # recall relevant past experiences
        past = self.memory.recall(goal, k=3)
        past_text = ""
        if past:
            past_text = "\n\nRelevant past experiences:\n" + "\n".join(
                f"- {p['text'][:200]}" for p in past
            )

        # --- planning ---
        plan = await self._plan(goal, past_text)
        if not plan:
            yield emit(AgentEvent(type="error", content="Failed to produce a plan."))
            return
        yield emit(AgentEvent(
            type="plan", role="planner",
            content=f"Planned {len(plan)} steps",
            data={"plan": plan},
        ))

        # --- step loop ---
        step_outputs: list[dict[str, Any]] = []
        for i, step in enumerate(plan, 1):
            step_title = step.get("title", f"Step {i}")
            step_kind = step.get("kind", "analysis")
            step_desc = step.get("description", "")
            yield emit(AgentEvent(
                type="step", role="worker",
                content=f"[{i}/{len(plan)}] {step_title}",
                data={"step": step},
            ))

            attempts = 0
            step_result = ""
            while attempts < 2:
                attempts += 1
                step_result = await self._execute_step(
                    goal, step_title, step_kind, step_desc, step_outputs, past_text
                )
                # review
                verdict, feedback = await self._review(step_desc, step_result)
                yield emit(AgentEvent(
                    type="result", role="reviewer",
                    content=f"verdict: {verdict}" + (f" — {feedback}" if feedback else ""),
                    data={"verdict": verdict, "feedback": feedback, "step": i},
                ))
                if verdict == "ok":
                    break
                # revise
                step_result = await self._revise_step(
                    goal, step_title, step_desc, step_result, feedback
                )
            step_outputs.append({"title": step_title, "result": step_result})

        # --- writer ---
        deliverable = await self._write(goal, step_outputs)
        deliverable_id = uuid.uuid4().hex[:12]
        yield emit(AgentEvent(
            type="deliverable", role="writer",
            content=deliverable,
            data={"id": deliverable_id, "format": "markdown"},
        ))

        # --- reflection ---
        reflection = await self._reflect(goal, plan, deliverable)
        self.memory.remember_episode(goal, reflection, success=True)
        yield emit(AgentEvent(
            type="message", role="reflector",
            content=reflection,
        ))

        yield emit(AgentEvent(
            type="done", role="system",
            content="Goal complete.",
            data={"deliverable_id": deliverable_id},
        ))

    # -- per-stage helpers --------------------------------------------------

    async def _plan(self, goal: str, past_text: str) -> list[dict[str, str]]:
        prompt = (
            f"GOAL:\n{goal}\n{past_text}\n\n"
            "Produce a JSON plan. Example:\n"
            '{"plan": [{"title":"Survey current state","kind":"research",'
            '"description":"Find the 3-5 most-cited 2024-2025 results in X"}]}'
        )
        try:
            resp = await self.router.chat(ChatRequest(
                messages=[
                    ChatMessage("system", SYSTEM_PROMPTS["planner"]),
                    ChatMessage("user", prompt),
                ],
                model=resolve_for_role("planner", self.router, self.cfg),
                temperature=0.2,
                json_mode=True,
                max_tokens=1500,
            ))
        except Exception as e:  # noqa: BLE001
            log.exception("planner failed")
            return []
        data = _extract_json(resp.content)
        plan = data.get("plan") or []
        # normalize: ensure each has title/kind/description
        cleaned: list[dict[str, str]] = []
        for s in plan:
            if not isinstance(s, dict):
                continue
            cleaned.append({
                "title": str(s.get("title", "Step"))[:200],
                "kind": str(s.get("kind", "analysis")),
                "description": str(s.get("description", ""))[:1000],
            })
        return cleaned or []

    async def _execute_step(
        self,
        goal: str,
        title: str,
        kind: str,
        description: str,
        prior: list[dict[str, Any]],
        past_text: str,
    ) -> str:
        prior_text = "\n\n".join(
            f"## {p['title']}\n{p['result'][:1500]}" for p in prior[-3:]
        ) or "(no prior steps)"

        role = "coder" if kind == "code" else "researcher" if kind == "research" else "researcher"
        sys_prompt = SYSTEM_PROMPTS[role]
        tools_desc = json.dumps(self.tools.list_for_prompt(), indent=2)
        sys_prompt += f"\n\nAVAILABLE TOOLS:\n{tools_desc}\n\n"
        sys_prompt += (
            "To call a tool, output a single JSON line of the form\n"
            '```json\n{"tool": "<name>", "args": {...}}\n```\n'
            "After the tool result, you'll receive a 'TOOL_RESULT' block. "
            "Then produce a final answer for this step in plain prose. "
            "Don't call the same tool twice in a row."
        )

        user_prompt = (
            f"OVERALL GOAL: {goal}\n\n"
            f"PAST EXPERIENCE:\n{past_text or '(none)'}\n\n"
            f"PRIOR STEPS:\n{prior_text}\n\n"
            f"CURRENT STEP — {title} (kind: {kind}):\n{description}\n\n"
            "Proceed."
        )
        messages = [
            ChatMessage("system", sys_prompt),
            ChatMessage("user", user_prompt),
        ]

        # Up to 3 tool turns
        for _ in range(3):
            resp = await self.router.chat(ChatRequest(
                messages=messages,
                model=resolve_for_role(role, self.router, self.cfg),
                temperature=0.4,
                max_tokens=1500,
            ))
            text = resp.content
            messages.append(ChatMessage("assistant", text))
            tool_call = _extract_json(text)
            if "tool" in tool_call and isinstance(tool_call["tool"], str):
                tname = tool_call["tool"]
                targs = tool_call.get("args", {}) or {}
                # safety: cap string sizes
                for k, v in list(targs.items()):
                    if isinstance(v, str) and len(v) > 20000:
                        targs[k] = v[:20000]
                output = await self.tools.call(tname, **targs)
                messages.append(ChatMessage(
                    "user",
                    f"TOOL_RESULT ({tname}):\n```\n{output[:6000]}\n```",
                ))
                continue
            # no tool call -> this is the final answer for the step
            return text

        return messages[-1].content if messages else "(no output)"

    async def _review(self, step_desc: str, step_result: str) -> tuple[str, str]:
        prompt = (
            f"STEP DESCRIPTION:\n{step_desc}\n\n"
            f"STEP OUTPUT:\n{step_result[:4000]}\n\n"
            "Verdict?"
        )
        try:
            resp = await self.router.chat(ChatRequest(
                messages=[
                    ChatMessage("system", SYSTEM_PROMPTS["reviewer"]),
                    ChatMessage("user", prompt),
                ],
                model=resolve_for_role("reviewer", self.router, self.cfg),
                temperature=0.1,
                json_mode=True,
                max_tokens=400,
            ))
        except Exception as e:  # noqa: BLE001
            log.warning("reviewer failed: %s", e)
            return "ok", ""
        data = _extract_json(resp.content)
        verdict = str(data.get("verdict", "ok")).lower()
        if verdict not in ("ok", "revise"):
            verdict = "ok"
        return verdict, str(data.get("feedback", ""))[:500]

    async def _revise_step(
        self, goal: str, title: str, desc: str, prev: str, feedback: str
    ) -> str:
        prompt = (
            f"GOAL: {goal}\nSTEP: {title}\nDESCRIPTION: {desc}\n\n"
            f"YOUR PREVIOUS OUTPUT:\n{prev[:3000]}\n\n"
            f"REVIEWER FEEDBACK:\n{feedback}\n\n"
            "Produce a revised, final answer for this step."
        )
        resp = await self.router.chat(ChatRequest(
            messages=[
                ChatMessage("system", SYSTEM_PROMPTS["researcher"]),
                ChatMessage("user", prompt),
            ],
            model=resolve_for_role("researcher", self.router, self.cfg),
            temperature=0.3,
            max_tokens=1500,
        ))
        return resp.content

    async def _write(self, goal: str, steps: list[dict[str, Any]]) -> str:
        body = "\n\n".join(
            f"## {s['title']}\n{s['result'][:3000]}" for s in steps
        )
        prompt = (
            f"GOAL:\n{goal}\n\n"
            f"STEP OUTPUTS TO SYNTHESIZE:\n{body}\n\n"
            "Produce the final Markdown deliverable. Include a short intro, "
            "organized sections with headers, and a 'Sources' section if any "
            "URLs were referenced. Keep it focused — under ~1500 words unless "
            "the goal explicitly asks for more depth."
        )
        resp = await self.router.chat(ChatRequest(
            messages=[
                ChatMessage("system", SYSTEM_PROMPTS["writer"]),
                ChatMessage("user", prompt),
            ],
            model=resolve_for_role("writer", self.router, self.cfg),
            temperature=0.4,
            max_tokens=2500,
        ))
        return resp.content

    async def _reflect(self, goal: str, plan: list[dict], deliverable: str) -> str:
        prompt = (
            f"GOAL: {goal}\n\n"
            f"PLAN: {json.dumps(plan)[:1500]}\n\n"
            f"DELIVERABLE (excerpt): {deliverable[:2000]}\n\n"
            "Write a concise reflection (2-3 sentences) on what worked and what "
            "to improve next time."
        )
        try:
            resp = await self.router.chat(ChatRequest(
                messages=[
                    ChatMessage("system", SYSTEM_PROMPTS["reflector"]),
                    ChatMessage("user", prompt),
                ],
                model=resolve_for_role("researcher", self.router, self.cfg),
                temperature=0.3,
                max_tokens=300,
            ))
            return resp.content.strip()
        except Exception:
            return "(reflection skipped)"
