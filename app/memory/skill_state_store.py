from __future__ import annotations

import json
from typing import Any

from redis import Redis


class SkillStateStore:
    """Per-student per-skill state storage for stateful SKILL.md runtimes."""

    def __init__(self, r: Redis) -> None:
        self.r = r

    def _key(self, student_id: str, skill_name: str) -> str:
        return f"mem:{student_id}:skill_state:{skill_name}"

    def get(self, *, student_id: str, skill_name: str) -> dict[str, Any] | None:
        raw = self.r.get(self._key(student_id, skill_name))
        if not raw:
            return None
        s = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
        try:
            obj = json.loads(s)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None

    def set(self, *, student_id: str, skill_name: str, state: dict[str, Any], ttl_seconds: int = 600) -> None:
        self.r.set(self._key(student_id, skill_name), json.dumps(state, ensure_ascii=False), ex=int(ttl_seconds))

    def clear(self, *, student_id: str, skill_name: str) -> None:
        self.r.delete(self._key(student_id, skill_name))

