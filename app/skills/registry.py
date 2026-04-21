from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

from app.skills.base import Skill, SkillContext, SkillResult


@dataclass
class SkillRegistry:
    skills: List[Skill]

    def run(self, ctx: SkillContext) -> list[SkillResult]:
        out: list[SkillResult] = []
        for s in self.skills:
            try:
                if s.should_run(ctx):
                    out.append(s.run(ctx))
            except Exception as e:
                out.append(SkillResult(name=getattr(s, "name", s.__class__.__name__), triggered=False, payload={"error": str(e)}))
        return out

