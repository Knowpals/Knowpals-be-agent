from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.memory.memory import MemoryTool
from app.model.llm import LLMModel
from app.skills.skill_loader import SkillSpec


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
    def _safe_json(text: str) -> dict[str, Any]:
        t = (text or "").strip()
        if t.startswith("```"):
            t = t.strip("```").replace("json", "").strip()
        try:
            obj = json.loads(t)
            return obj if isinstance(obj, dict) else {"value": obj}
        except Exception:
            return {"raw": text}

    def run_stateless(self, *, spec: SkillSpec, skill_input: dict[str, Any]) -> str:
        prompt = spec.system_prompt or spec.start_prompt or ""
        raw = self.llm.think(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(skill_input, ensure_ascii=False)},
            ]
        )
        return raw or ""

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

