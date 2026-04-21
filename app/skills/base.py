from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class SkillContext:
    student_id: str
    text: str
    video_id: str
    knowledge_id: str | None
    built_context: dict[str, Any]  # output of ContextBuilder.build


@dataclass
class SkillResult:
    name: str
    triggered: bool
    payload: dict[str, Any]


class Skill(Protocol):
    name: str

    def should_run(self, ctx: SkillContext) -> bool: ...

    def run(self, ctx: SkillContext) -> SkillResult: ...

