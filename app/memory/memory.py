from typing import Any, List

import json
import threading
import time

from redis import Redis

from app.model.llm import LLMModel

class MemoryTool:

    def __init__(self, r: Redis,llm:LLMModel):
        self.r = r
        self.llm = llm

    @staticmethod
    def _decode_hash(h: dict[Any, Any]) -> dict[str, str]:
        out: dict[str, str] = {}
        for k, v in h.items():
            kk = k.decode("utf-8") if isinstance(k, (bytes, bytearray)) else str(k)
            vv = v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else str(v)
            out[kk] = vv
        return out

    def _base_key(self, student_id, knowledge_id):
        return f"mem:{student_id}:{knowledge_id}"

    def _mastery_zkey(self, student_id: str) -> str:
        """按学生维度：member=knowledge_id，score=综合掌握度 [0,1]（答题+暂停+回放），越高越强。"""
        return f"mem:{student_id}:mastery:z"

    def _composite_mastery_score(self, stat: dict[str, str]) -> float | None:
        """
        综合记分：错题(用正确率)、暂停、回放都参与。
        - 有做题：以正确率为基底，暂停/回放占「总互动」比例越高分越低。
        - 仅暂停/回放：无答题时用中性基底 0.55，再由行为占比拉低。
        """
        total = int(stat.get("total", 0))
        correct = int(stat.get("correct", 0))
        pause = int(stat.get("pause", 0))
        replay = int(stat.get("replay", 0))

        activity = total + pause + replay
        if activity <= 0:
            return None

        if total > 0:
            acc = correct / total
        else:
            acc = 0.55

        pause_share = pause / activity
        replay_share = replay / activity

        # 答题质量为主；暂停、回放占比反映卡顿/反复看，压低掌握度（权重可调）
        raw = acc * (1.0 - 0.45 * pause_share - 0.35 * replay_share)
        return max(0.0, min(1.0, raw))

    def _refresh_knowledge_mastery_score(self, student_id: str, knowledge_id: str) -> None:
        """根据 mem:{sid}:{kid}:stats 刷新该 knowledge 在全局排行 ZSET 中的得分。"""
        stat_key = self._base_key(student_id, knowledge_id) + ":stats"
        stat = self._decode_hash(self.r.hgetall(stat_key))
        zkey = self._mastery_zkey(student_id)

        mastery = self._composite_mastery_score(stat)
        if mastery is None:
            self.r.zrem(zkey, knowledge_id)
            return

        self.r.zadd(zkey, {knowledge_id: mastery})
        self.r.expire(zkey, 86400 * 30)

    def weak_knowledge_ids(self, student_id: str, limit: int = 20) -> list[tuple[str, float]]:
        """
        按综合掌握度从低到高返回 (knowledge_id, score)，便于直接挑薄弱知识点。
        Redis: ZRANGE mem:{sid}:mastery:z 0 limit-1 WITHSCORES
        """
        zkey = self._mastery_zkey(student_id)
        lim = max(1, min(int(limit), 500))
        pairs = self.r.zrange(zkey, 0, lim - 1, withscores=True)
        out: list[tuple[str, float]] = []
        for mid, score in pairs:
            kid = mid.decode("utf-8") if isinstance(mid, (bytes, bytearray)) else str(mid)
            out.append((kid, float(score)))
        return out

    #写短期记忆
    def write(self, student_id, behavior: dict[str, Any]):
        behavior["ts"] = int(time.time())
        knowledge_id=behavior["knowledge_id"]

        base = self._base_key(student_id, knowledge_id)

        #存入短期工作记忆（原始行为）
        event_key = base + ":events"
        self.r.lpush(event_key, json.dumps(behavior))
        self.r.ltrim(event_key, 0, 200)
        self.r.expire(event_key, 86400 * 2)

        #存入知识点掌握程度的聚合分数
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

        self._refresh_knowledge_mastery_score(student_id, knowledge_id)

        #判断是否需要触发长期记忆更新（Python 侧异步构建，不阻塞写路径）
        if self._should_build(student_id, knowledge_id, behavior):
            self._trigger_build(student_id, knowledge_id)

    def _trigger_build(self, student_id: str, knowledge_id: str) -> None:
        """长期记忆异步构建；避免阻塞 gRPC Write。"""
        def run() -> None:
            try:
                self.build_long_term(student_id, knowledge_id)
            except Exception as e:
                print(f"[MemoryTool] build_long_term failed: {e}")

        threading.Thread(target=run, daemon=True).start()

    def _should_build(self, student_id, knowledge_id, behavior):
        base = self._base_key(student_id, knowledge_id)
        stat_key = base + ":stats"

        # 1. 读统计（与 write() 写入的 Hash 一致）
        stat = self._decode_hash(self.r.hgetall(stat_key))
        wrong = int(stat.get("wrong", 0))

        # 2. 条件1：每错5题触发一次
        if wrong > 0 and wrong % 5 == 0:
            return True

        # 3. 条件2：连续错误（关键）
        if behavior["type"] == "question" and not behavior.get("is_correct"):
            recent = self.r.lrange(base + ":events", 0, 3)
            recent = [json.loads(e) for e in recent]

            wrong_cnt = sum(
                1 for e in recent
                if e["type"] == "question" and not e.get("is_correct")
            )

            if wrong_cnt >= 3:
                return True

        return False

    def build_long_term(self, student_id, knowledge_id)->str:
        base = self._base_key(student_id, knowledge_id)

        event_key = base + ":events"

        raw_events = self.r.lrange(event_key, 0, 20)
        events = [json.loads(e) for e in raw_events]

        wrong_cnt = sum(1 for e in events if e["type"] == "question" and not e.get("is_correct"))
        if len(events) < 8 and wrong_cnt < 3:
            return ""

        #选关键事件
        selected_events = self._select_events(events)

        stats_str = self._format_stats(student_id, knowledge_id)
        events_str = self._format_events(selected_events)

        # 获取当前知识点的内容
        knowledge_name = self.r.get(f"knowpals:knowledge:{knowledge_id}")
        if knowledge_name:
            knowledge_name = knowledge_name.decode("utf-8")
        else:
            knowledge_name = "未知知识点"

        # 2. 构造 prompt
        system="""
        你是一个专业的教育数据分析专家，
        擅长根据学生行为判断认知水平和学习问题。
        你的输出必须稳定、结构化、可用于程序处理。
        """
        prompt = f"""
        你是一个学习分析助手，请根据学生的学习行为分析其知识点掌握情况。
        
        知识点：{knowledge_name}
        
        【统计信息】
        {stats_str}
    
        【行为记录】
        {events_str}
    
        请你完成以下分析，并严格输出 JSON（不要输出任何额外内容）：
    
        1. mastery：0-1之间的小数
        2. weakness：学生的主要薄弱点（数组）
        3. behavior_pattern：学习行为特征（数组）
        4. trend：学习趋势（improving / declining / stable）
        5. summary：一句话总结
    
        输出格式：
        {{
          "mastery": 0.0,
          "weakness": [],
          "behavior_pattern": [],
          "trend": "",
          "summary": ""
        }}
        """

        msgs=[
            {
                "role":"system",
                "content":system,
            },
            {
                "role":"user",
                "content":prompt
            }
        ]
        resp = self.llm.think(msgs)
        resp=self._safe_parse(resp)

        data = {
            "knowledge_id": knowledge_id,
            **resp,
            "updated_at": int(time.time())
        }

        #将长期记忆回写redis
        long_key = f"mem:{student_id}:long:{knowledge_id}"
        self.r.set(long_key, json.dumps(data))
        self.r.expire(long_key, 86400 * 30)

        return json.dumps(data)

    def get_memory(self, student_id, knowledge_id):
        base = self._base_key(student_id, knowledge_id)

        #长期记忆
        long_key = f"mem:{student_id}:long:{knowledge_id}"
        long_term = self.r.get(long_key)

        if long_term:
            long_term = long_term.decode()
        else:
            long_term = "{}"

        #短期记忆（取最近）
        event_key = base + ":events"
        raw_events = self.r.lrange(event_key, 0, 5)

        events = [json.loads(e) for e in raw_events]
        selected = self._select_events(events)

        short_term = self._format_events(selected)

        return {
            "long_term": long_term,
            "short_term": short_term
        }

    #选择关键性事件（错题+聊天）
    def _select_events(self, events):
        wrong_q = []
        chats = []

        for e in events:
            if e["type"] == "question" and not e.get("is_correct"):
                wrong_q.append(e)
            elif e["type"] == "chat":
                chats.append(e)

        #控制token数量
        selected = wrong_q[:3] + chats[:2]

        return selected if selected else events[:5]


    def _format_stats(self, student_id,knowledge_id):
        key=self._base_key(student_id,knowledge_id)+":stats"
        stat = self._decode_hash(self.r.hgetall(key))
        total = int(stat.get("total", 0))
        wrong = int(stat.get("wrong", 0))
        pause = int(stat.get("pause", 0))
        replay = int(stat.get("replay", 0))

        line = ""
        if total > 0:
            line += f"做题{stat['total']}次，错误率{(wrong / total)*100:.0%}；"
        if pause > 0:
            line += f"暂停{stat['pause']}次；"
        if replay > 0:
            line += f"回放{stat['replay']}次；"

        return line


    def _format_events(self,events:List[dict[str,Any]])->str:
        lines = []
        pause_count = 0
        replay_count = 0
        for e in events:
            if e["type"] == "question":
                if e["is_correct"]:
                    continue
                line=f"题目内容：{e['content']}"
                line+=f"学生错误答案：{e['user_answer']}"
                line+=f"正确答案：{e['right_answer']}"
                lines.append(line)
            elif e["type"] == "chat":
                line=f"用户对话内容：{e['text']}"
                lines.append(line)
            elif e["type"] == "pause" :
                pause_count += 1
            elif e["type"] == "replay" :
                replay_count += 1

        if pause_count > 0:
            lines.append(f"暂停次数：{pause_count}")
        if replay_count > 0:
            lines.append(f"回放次数：{replay_count}")

        return "\n".join(lines)

    def _safe_parse(self, text: str):
        try:
            text = text.strip()

            # 去掉 ```json 包裹
            if text.startswith("```"):
                text = text.strip("```").replace("json", "").strip()

            return json.loads(text)
        except:
            return {
                "mastery": 0.0,
                "weakness": [],
                "behavior_pattern": [],
                "trend": "stable",
                "summary": "LLM解析失败"
            }

