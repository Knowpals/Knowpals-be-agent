from __future__ import annotations

from typing import Any, List

import json

from redis import Redis

from app.model.llm import LLMModel
from app.memory.chat_store import ChatMemoryStore
from app.memory.long_term_builder import LongTermMemoryBuilder
from app.memory.skill_state_store import SkillStateStore
from app.memory.video_memory_store import VideoConceptMemoryStore


class MemoryTool:
    """
    Facade that aggregates smaller memory stores:
    - VideoConceptMemoryStore: events/stats/mastery/get_memory per video+knowledge
    - ChatMemoryStore: student-global chat turns
    - SkillStateStore: per-skill state for stateful skills
    - LongTermMemoryBuilder: LLM-based long-term summary builder
    """

    def __init__(self, r: Redis, llm: LLMModel):
        self.r = r
        self.llm = llm
        self.video = VideoConceptMemoryStore(r)
        self.chat = ChatMemoryStore(r)
        self.skill_state = SkillStateStore(r)
        self.long_term = LongTermMemoryBuilder(r=r, llm=llm, video_store=self.video)

    # ---- video concept memory ----
    def write(self, student_id: str, behavior: dict[str, Any]) -> None:
        self.video.write_event(student_id=student_id, behavior=behavior)
        vid = (behavior.get("video_id") or "").strip() or "unknown"
        kid = behavior.get("knowledge_id") or "unknown"
        if self.long_term.should_build(student_id=student_id, video_id=vid, knowledge_id=kid, behavior=behavior):
            self.long_term.trigger_build(student_id=student_id, video_id=vid, knowledge_id=kid)

    def weak_knowledge_ids(self, student_id: str, video_id: str, limit: int = 20) -> list[tuple[str, float]]:
        return self.video.weak_knowledge_ids(student_id=student_id, video_id=video_id, limit=limit)

    def latest_video_id(self, student_id: str) -> str | None:
        return self.video.latest_video_id(student_id=student_id)

    def get_memory(self, student_id: str, knowledge_id: str, video_id: str) -> dict[str, Any]:
        mem = self.video.get_memory(student_id=student_id, video_id=video_id, knowledge_id=knowledge_id)
        # keep existing shape expected by ContextBuilder
        selected = self._select_events(mem.get("events") or [])
        mem["short_term"] = self._format_events(selected)
        mem.pop("events", None)
        return mem

    # ---- chat turns (global) ----
    def add_chat_turn(self, *, student_id: str, role: str, text: str, video_id: str = "") -> None:
        self.chat.add_turn(student_id=student_id, role=role, text=text, video_id=video_id)

    def get_chat_turns(self, *, student_id: str, limit: int = 8) -> list[dict[str, Any]]:
        return self.chat.get_turns(student_id=student_id, limit=limit)

    # ---- skill state ----
    def get_skill_state(self, *, student_id: str, skill_name: str) -> dict[str, Any] | None:
        return self.skill_state.get(student_id=student_id, skill_name=skill_name)

    def set_skill_state(self, *, student_id: str, skill_name: str, state: dict[str, Any], ttl_seconds: int = 600) -> None:
        self.skill_state.set(student_id=student_id, skill_name=skill_name, state=state, ttl_seconds=ttl_seconds)

    def clear_skill_state(self, *, student_id: str, skill_name: str) -> None:
        self.skill_state.clear(student_id=student_id, skill_name=skill_name)

    # ---- helpers for formatting short-term ----
    def _select_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        wrong_q = [e for e in events if e.get("type") == "question" and not e.get("is_correct")]
        chats = [e for e in events if e.get("type") == "chat"]
        selected = wrong_q[:3] + chats[:2]
        return selected if selected else events[:5]

    def _format_events(self, events: List[dict[str, Any]]) -> str:
        lines = []
        pause_count = 0
        replay_count = 0
        for e in events:
            if e.get("type") == "question":
                if e.get("is_correct"):
                    continue
                line = f"题目内容：{e.get('content','')}"
                line += f" 学生错误答案：{e.get('user_answer','')}"
                line += f" 正确答案：{e.get('right_answer','')}"
                lines.append(line)
            elif e.get("type") == "chat":
                lines.append(f"用户对话内容：{e.get('text','')}")
            elif e.get("type") == "pause":
                pause_count += 1
            elif e.get("type") == "replay":
                replay_count += 1
        if pause_count > 0:
            lines.append(f"暂停次数：{pause_count}")
        if replay_count > 0:
            lines.append(f"回放次数：{replay_count}")
        return "\n".join(lines)

