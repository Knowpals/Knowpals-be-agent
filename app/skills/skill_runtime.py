from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.memory.memory import MemoryTool
from app.model.llm import LLMModel
from app.skills.skill_loader import SkillSpec
from app.agent.tool_registry import ToolRegistry


@dataclass
class SkillRunResult:
    reply: str
    done: bool
    state: dict[str, Any] | None
    raw: str


class SkillRuntime:
    """Execute SKILL.md-defined skills, with optional multi-turn state."""

    def __init__(self, *, llm: LLMModel, memory: MemoryTool) -> None:
        self.llm = llm
        self.memory = memory

    @staticmethod
    def _safe_json(text: str) -> dict[str, Any] | None:
        """
        Best-effort JSON object parser.
        Returns dict on success, None on failure (so caller can retry).
        """
        t = (text or "").strip()
        if not t:
            return None
        if t.startswith("```"):
            t = t.strip("```").replace("json", "").strip()
        # 1) direct parse
        try:
            obj = json.loads(t)
            return obj if isinstance(obj, dict) else None
        except Exception:
            pass
        # 2) extract first balanced {...} object (handles extra trailing braces)
        start = t.find("{")
        if start == -1:
            return None
        in_str = False
        esc = False
        depth = 0
        end_idx = None
        for i in range(start, len(t)):
            ch = t[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            else:
                if ch == '"':
                    in_str = True
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end_idx = i
                        break
        if end_idx is not None:
            candidate = t[start: end_idx + 1]
            try:
                obj = json.loads(candidate)
                return obj if isinstance(obj, dict) else None
            except Exception:
                return None
        return None

    def run_stateless(self, *, spec: SkillSpec, skill_input: dict[str, Any]) -> str:
        prompt = spec.system_prompt or spec.start_prompt or ""
        raw = self.llm.think(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(skill_input, ensure_ascii=False)},
            ]
        )
        return raw or ""

    def run_tool_driven(
        self,
        *,
        spec: SkillSpec,
        tool_registry: ToolRegistry,
        skill_input: dict[str, Any],
        max_steps: int = 6,
    ) -> SkillRunResult:
        """
        Tool-driven execution loop.
        The model must output JSON with one of:
        - {"action":"tool","name":"tool.name","args":{...}}
        - {"action":"final","reply":"...","state":{...}|null,"done":true|false}
        """
        prompt = spec.system_prompt or spec.start_prompt or ""
        tools = tool_registry.list()
        msgs: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    f"{prompt}\n\n"
                    "你可以调用工具。每一步严格输出 JSON，不要输出额外文本。\n"
                    "如果要调用工具：{\"action\":\"tool\",\"name\":\"...\",\"args\":{...}}\n"
                    "如果要结束：{\"action\":\"final\",\"reply\":\"...\",\"done\":true|false,\"state\":{...}|null}\n"
                    f"可用工具：{json.dumps(tools, ensure_ascii=False)}"
                ),
            },
            {"role": "user", "content": json.dumps(skill_input, ensure_ascii=False)},
        ]

        last_raw = ""
        for _ in range(max_steps):
            raw = (self.llm.think(msgs) or "").strip()
            last_raw = raw
            obj = self._safe_json(raw)
            action = obj.get("action")
            if action == "tool":
                name = str(obj.get("name", "") or "")
                args = obj.get("args")
                if not isinstance(args, dict):
                    args = {}
                try:
                    result = tool_registry.call(name=name, args=args)
                    msgs.append({"role": "assistant", "content": raw})
                    # NOTE: don't use role="tool" (requires tool_call_id in OpenAI); use user observation instead.
                    msgs.append({"role": "user", "content": json.dumps({"observation": {"tool": name, "result": result}}, ensure_ascii=False)})
                    continue
                except Exception as e:
                    msgs.append({"role": "assistant", "content": raw})
                    msgs.append({"role": "user", "content": json.dumps({"observation": {"tool": name, "error": str(e)}}, ensure_ascii=False)})
                    continue
            if action == "final":
                reply = str(obj.get("reply", "") or "")
                done = bool(obj.get("done", True))
                state = obj.get("state") if isinstance(obj.get("state"), dict) else None
                return SkillRunResult(reply=reply, done=done, state=state, raw=raw)

        return SkillRunResult(reply="error", done=True, state=None, raw=last_raw)

    def run_stateful(
        self,
        *,
        student_id: str,
        spec: SkillSpec,
        start_input: dict[str, Any],
        continue_input: dict[str, Any],
        ttl_seconds: int = 600,
    ) -> SkillRunResult:
        skill_name = spec.name
        state = self.memory.get_skill_state(student_id=student_id, skill_name=skill_name)

        if state:
            # Continue
            payload = dict(continue_input)
            payload["state"] = state
            raw = self.llm.think(
                [
                    {"role": "system", "content": spec.continue_prompt or spec.system_prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ]
            ) or ""
            obj = self._safe_json(raw)
            reply = str(obj.get("reply", "") or "")
            done = bool(obj.get("done", False))
            new_state = obj.get("state") if isinstance(obj.get("state"), dict) else None
            if done:
                self.memory.clear_skill_state(student_id=student_id, skill_name=skill_name)
            else:
                self.memory.set_skill_state(student_id=student_id, skill_name=skill_name, state=new_state or state, ttl_seconds=ttl_seconds)
            return SkillRunResult(reply=reply, done=done, state=new_state, raw=raw)

        # Start new
        raw = self.llm.think(
            [
                {"role": "system", "content": spec.start_prompt or spec.system_prompt},
                {"role": "user", "content": json.dumps(start_input, ensure_ascii=False)},
            ]
        ) or ""
        obj = self._safe_json(raw)
        reply = str(obj.get("reply", "") or "")
        done = bool(obj.get("done", False))
        new_state = obj.get("state") if isinstance(obj.get("state"), dict) else None
        if not done and new_state:
            self.memory.set_skill_state(student_id=student_id, skill_name=skill_name, state=new_state, ttl_seconds=ttl_seconds)
        return SkillRunResult(reply=reply, done=done, state=new_state, raw=raw)

