from __future__ import annotations

import json
import time
from typing import Any

from redis import Redis


class ChatMemoryStore:
    """Student-global chat history storage (recent turns)."""

    def __init__(self, r: Redis) -> None:
        self.r = r

    def _turns_key(self, student_id: str) -> str:
        return f"mem:{student_id}:chat:turns"

    def add_turn(self, *, student_id: str, role: str, text: str, video_id: str = "") -> None:
        key = self._turns_key(student_id)
        item = json.dumps(
            {"role": role, "text": text, "video_id": video_id or "", "ts": int(time.time())},
            ensure_ascii=False,
        )
        self.r.lpush(key, item)
        self.r.ltrim(key, 0, 20)
        self.r.expire(key, 86400 * 2)

    def get_turns(self, *, student_id: str, limit: int = 8) -> list[dict[str, Any]]:
        key = self._turns_key(student_id)
        raw = self.r.lrange(key, 0, max(0, int(limit)) - 1)
        out: list[dict[str, Any]] = []
        for item in raw[::-1]:  # oldest first
            s = item.decode("utf-8") if isinstance(item, (bytes, bytearray)) else str(item)
            try:
                obj = json.loads(s)
                if isinstance(obj, dict):
                    out.append(obj)
            except json.JSONDecodeError:
                continue
        return out

