from __future__ import annotations

import json
import threading
import time
from typing import Any, List

from redis import Redis

from app.model.llm import LLMModel
from app.memory.video_memory_store import VideoConceptMemoryStore


class LongTermMemoryBuilder:
    """LLM-based long-term summary builder (video + knowledge scoped)."""

    def __init__(self, *, r: Redis, llm: LLMModel, video_store: VideoConceptMemoryStore) -> None:
        self.r = r
        self.llm = llm
        self.video_store = video_store

    def should_build(self, *, student_id: str, video_id: str, knowledge_id: str, behavior: dict[str, Any]) -> bool:
        base = self.video_store._base_key(student_id, video_id, knowledge_id)
        stat_key = base + ":stats"
        stat = self.video_store._decode_hash(self.r.hgetall(stat_key))
        wrong = int(stat.get("wrong", 0))

        if wrong > 0 and wrong % 5 == 0:
            return True

        if behavior.get("type") == "question" and not behavior.get("is_correct"):
            recent = self.r.lrange(base + ":events", 0, 3)
            recent = [json.loads(e) for e in recent]
            wrong_cnt = sum(
                1 for e in recent
                if e.get("type") == "question" and not e.get("is_correct")
            )
            return wrong_cnt >= 3

        return False

    def trigger_build(self, *, student_id: str, video_id: str, knowledge_id: str) -> None:
        def run() -> None:
            try:
                self.build_long_term(student_id=student_id, video_id=video_id, knowledge_id=knowledge_id)
            except Exception as e:
                print(f"[LongTermMemoryBuilder] build_long_term failed: {e}")

        threading.Thread(target=run, daemon=True).start()

    def build_long_term(self, *, student_id: str, video_id: str, knowledge_id: str) -> str:
        base = self.video_store._base_key(student_id, video_id, knowledge_id)
        event_key = base + ":events"

        raw_events = self.r.lrange(event_key, 0, 20)
        events = [json.loads(e) for e in raw_events]

        wrong_cnt = sum(1 for e in events if e.get("type") == "question" and not e.get("is_correct"))
        if len(events) < 8 and wrong_cnt < 3:
            return ""

        selected_events = self._select_events(events)
        stats_str = self._format_stats(student_id, video_id, knowledge_id)
        events_str = self._format_events(selected_events)

        knowledge_name = self.r.get(f"knowpals:knowledge:{knowledge_id}")
        knowledge_name = knowledge_name.decode("utf-8") if knowledge_name else "未知知识点"

        system = (
            "你是一个专业的教育数据分析专家，擅长根据学生行为判断认知水平和学习问题。"
            "你的输出必须稳定、结构化、可用于程序处理。"
        )
        prompt = f"""
你是一个学习分析助手，请根据学生的学习行为分析其知识点掌握情况。

知识点：{knowledge_name}

【统计信息】
{stats_str}

【行为记录】
{events_str}

请你完成以下分析，并严格输出 JSON（不要输出任何额外内容）：

1. weakness：学生的主要薄弱点（数组）
2. behavior_pattern：学习行为特征（数组）
3. trend：学习趋势（improving / declining / stable）
4. summary：一句话总结

输出格式：
{{
  "weakness": [],
  "behavior_pattern": [],
  "trend": "",
  "summary": ""
}}
"""
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        resp = self.llm.think(msgs)
        resp = self._safe_parse(resp)

        zkey = self.video_store._mastery_zkey(student_id, video_id)
        mastery_score = self.r.zscore(zkey, knowledge_id)
        mastery = float(mastery_score) if mastery_score is not None else 0.0

        data = {"knowledge_id": knowledge_id, "video_id": video_id, "mastery": mastery, **resp, "updated_at": int(time.time())}

        long_key = f"mem:{student_id}:v:{video_id}:long:{knowledge_id}"
        self.r.set(long_key, json.dumps(data, ensure_ascii=False))
        self.r.expire(long_key, 86400 * 30)
        return json.dumps(data, ensure_ascii=False)

    def _format_stats(self, student_id: str, video_id: str, knowledge_id: str) -> str:
        key = self.video_store._base_key(student_id, video_id, knowledge_id) + ":stats"
        stat = self.video_store._decode_hash(self.r.hgetall(key))
        total = int(stat.get("total", 0))
        wrong = int(stat.get("wrong", 0))
        pause = int(stat.get("pause", 0))
        replay = int(stat.get("replay", 0))
        line = ""
        if total > 0:
            line += f"做题{total}次，错误率{(wrong / total) * 100:.0%}；"
        if pause > 0:
            line += f"暂停{pause}次；"
        if replay > 0:
            line += f"回放{replay}次；"
        return line

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

    def _safe_parse(self, text: str) -> dict[str, Any]:
        try:
            t = (text or "").strip()
            if t.startswith("```"):
                t = t.strip("```").replace("json", "").strip()
            obj = json.loads(t)
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {"weakness": [], "behavior_pattern": [], "trend": "stable", "summary": "LLM解析失败"}

