from __future__ import annotations

import json
import time
from typing import Any

from redis import Redis


class VideoConceptMemoryStore:
    """Video-scoped (student_id, video_id, knowledge_id) events/stats/mastery storage."""

    def __init__(self, r: Redis) -> None:
        self.r = r

    @staticmethod
    def _decode_hash(h: dict[Any, Any]) -> dict[str, str]:
        out: dict[str, str] = {}
        for k, v in h.items():
            kk = k.decode("utf-8") if isinstance(k, (bytes, bytearray)) else str(k)
            vv = v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else str(v)
            out[kk] = vv
        return out

    def _base_key(self, student_id: str, video_id: str, knowledge_id: str) -> str:
        if not video_id:
            raise ValueError("video_id is required for memory storage")
        return f"mem:{student_id}:v:{video_id}:{knowledge_id}"

    def _mastery_zkey(self, student_id: str, video_id: str) -> str:
        if not video_id:
            raise ValueError("video_id is required for mastery zset")
        return f"mem:{student_id}:v:{video_id}:mastery:z"

    def _composite_mastery_score(self, stat: dict[str, str]) -> float | None:
        total = int(stat.get("total", 0))
        correct = int(stat.get("correct", 0))
        pause = int(stat.get("pause", 0))
        replay = int(stat.get("replay", 0))

        activity = total + pause + replay
        if activity <= 0:
            return None

        acc = (correct / total) if total > 0 else 0.55
        pause_share = pause / activity
        replay_share = replay / activity
        raw = acc * (1.0 - 0.45 * pause_share - 0.35 * replay_share)
        return max(0.0, min(1.0, raw))

    def refresh_mastery(self, *, student_id: str, video_id: str, knowledge_id: str) -> None:
        stat_key = self._base_key(student_id, video_id, knowledge_id) + ":stats"
        stat = self._decode_hash(self.r.hgetall(stat_key))
        zkey = self._mastery_zkey(student_id, video_id)
        mastery = self._composite_mastery_score(stat)
        if mastery is None:
            self.r.zrem(zkey, knowledge_id)
            return
        self.r.zadd(zkey, {knowledge_id: mastery})

    def weak_knowledge_ids(self, *, student_id: str, video_id: str, limit: int = 20) -> list[tuple[str, float]]:
        zkey = self._mastery_zkey(student_id, video_id)
        lim = max(1, min(int(limit), 500))
        pairs = self.r.zrange(zkey, 0, lim - 1, withscores=True)
        out: list[tuple[str, float]] = []
        for mid, score in pairs:
            kid = mid.decode("utf-8") if isinstance(mid, (bytes, bytearray)) else str(mid)
            out.append((kid, float(score)))
        return out

    def latest_video_id(self, *, student_id: str) -> str | None:
        best_vid: str | None = None
        best_ts = -1
        for ekey in self.r.scan_iter(f"mem:{student_id}:v:*:*:events"):
            k = ekey.decode("utf-8") if isinstance(ekey, (bytes, bytearray)) else str(ekey)
            item = self.r.lindex(k, 0)
            if not item:
                continue
            s = item.decode("utf-8") if isinstance(item, (bytes, bytearray)) else str(item)
            try:
                e = json.loads(s)
            except json.JSONDecodeError:
                continue
            ts = int(e.get("ts", 0) or 0)
            vid = (e.get("video_id") or "").strip()
            if vid and ts >= best_ts:
                best_ts = ts
                best_vid = vid
        return best_vid

    def write_event(self, *, student_id: str, behavior: dict[str, Any]) -> None:
        behavior["ts"] = int(time.time())
        knowledge_id = behavior["knowledge_id"]
        video_id = (behavior.get("video_id") or "").strip() or "unknown"
        base = self._base_key(student_id, video_id, knowledge_id)

        event_key = base + ":events"
        self.r.lpush(event_key, json.dumps(behavior, ensure_ascii=False))
        self.r.ltrim(event_key, 0, 200)
        self.r.expire(event_key, 86400 * 2)

        stat_key = base + ":stats"
        t = behavior["type"]
        if t == "question":
            self.r.hincrby(stat_key, "total", 1)
            if behavior.get("is_correct"):
                self.r.hincrby(stat_key, "correct", 1)
            else:
                self.r.hincrby(stat_key, "wrong", 1)
        elif t == "pause":
            self.r.hincrby(stat_key, "pause", 1)
        elif t == "replay":
            self.r.hincrby(stat_key, "replay", 1)
        self.r.expire(stat_key, 86400 * 7)

        self.refresh_mastery(student_id=student_id, video_id=video_id, knowledge_id=knowledge_id)

    def get_memory(self, *, student_id: str, video_id: str, knowledge_id: str) -> dict[str, Any]:
        base = self._base_key(student_id, video_id, knowledge_id)
        zkey = self._mastery_zkey(student_id, video_id)
        mastery_score = self.r.zscore(zkey, knowledge_id)
        mastery = float(mastery_score) if mastery_score is not None else 0.0

        long_key = f"mem:{student_id}:v:{video_id}:long:{knowledge_id}"
        long_term = self.r.get(long_key)
        long_term = long_term.decode() if long_term else "{}"

        event_key = base + ":events"
        raw_events = self.r.lrange(event_key, 0, 5)
        events = [json.loads(e) for e in raw_events]

        # lightweight formatting (keep behavior-based formatting in facade if needed)
        return {
            "mastery": mastery,
            "video_id": video_id,
            "knowledge_id": knowledge_id,
            "long_term": long_term,
            "events": events,
        }

