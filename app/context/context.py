from typing import Dict, Any
from typing import Optional, List, Tuple

class ContextBuilder:

    def __init__(self, memory_tool, rag_service):
        self.memory = memory_tool
        self.rag = rag_service


    def build(
        self,
        student_id: str,
        user_input: str,
        *,
        video_id: Optional[str] = None,
        knowledge_id: Optional[str] = None,
        topk_knowledge: int = 3,
        need: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        返回结构化上下文
        """

        # 0) 若不指定 video_id，则默认使用最近学习的视频（不做跨视频 knowledge 聚合）
        if not video_id:
            try:
                video_id = self.memory.latest_video_id(student_id)
            except Exception:
                video_id = None
        need = need or {}
        need_chat = bool(need.get("chat", True))
        need_memory = bool(need.get("memory", False))
        need_rag = bool(need.get("rag", False))
        rag_types = need.get("rag_types") or ["knowledge"]
        if not isinstance(rag_types, list):
            rag_types = ["knowledge"]

        chat_turns = []
        if need_chat:
            try:
                chat_turns = self.memory.get_chat_turns(student_id=student_id, limit=int(need.get("chat_limit", 4) or 4))
            except Exception:
                chat_turns = []

        knowledge_ids: List[str] = []
        if need_memory or need_rag:
            knowledge_ids = self._select_knowledge_ids(
                student_id=student_id,
                video_id=video_id,
                knowledge_id=knowledge_id,
                topk=topk_knowledge,
            )
        elif knowledge_id:
            knowledge_ids = [knowledge_id]

        # 2) 批量拉 memory（按 video）
        mem_items: List[Dict[str, Any]] = []
        if need_memory and video_id:
            for kid in knowledge_ids:
                mem_items.append(self.memory.get_memory(student_id, kid, video_id))

        rag_docs = []
        if need_rag and knowledge_ids and video_id:
            rag_docs = self._retrieve_multi(query=user_input, knowledge_ids=knowledge_ids, mem_items=mem_items, video_id=video_id)

        knowledge_docs, question_docs, segment_docs = self._split_docs(rag_docs)
        if "knowledge" not in rag_types:
            knowledge_docs = []
        if "question" not in rag_types:
            question_docs = []
        if "segment" not in rag_types:
            segment_docs = []

        # 拼接 context
        context = self._build_prompt(
            user_input,
            mem_items if need_memory else [],
            chat_turns if need_chat else [],
            knowledge_docs,
            question_docs,
            segment_docs,
        )

        return {
            "context": context,
            "memory": mem_items,
            "chat_turns": chat_turns,
            "knowledge_ids": knowledge_ids,
            "video_id": video_id or "",
            "rag_docs": rag_docs
        }

    def _select_knowledge_ids(
        self,
        *,
        student_id: str,
        video_id: Optional[str],
        knowledge_id: Optional[str],
        topk: int,
    ) -> List[str]:
        """
        实际 agent 里，不应该只依赖单个 knowledge_id。
        - 若调用方明确传 knowledge_id：优先把它放在首位，再补齐薄弱点 TopK。
        - 若传 video_id：取该视频的薄弱点榜（按 mastery:z 低分）。
        - 若不传 video_id：build() 会先推断最近视频，再按该视频检索（不做跨视频聚合）。
        """
        k = max(1, min(int(topk), 20))
        ids: List[str] = []

        if knowledge_id:
            ids.append(knowledge_id)

        try:
            if video_id:
                weak = self.memory.weak_knowledge_ids(student_id, video_id, limit=k)
            else:
                weak = []
        except Exception:
            weak = []

        for kid, _score in weak:
            if kid and kid not in ids:
                ids.append(kid)
            if len(ids) >= k:
                break

        return ids[:k]

    # 检索策略（核心）：对多个 knowledge_id 做检索
    def _retrieve_multi(self, query: str, knowledge_ids: List[str], mem_items: List[Dict[str, Any]], video_id: Optional[str]):
        results = []

        # 给每个 knowledge 一个 budget，避免 topk 太大时上下文爆炸
        per_k = max(1, min(3, 12 // max(1, len(knowledge_ids))))

        for kid, mem in zip(knowledge_ids, mem_items):
            mastery = float(mem.get("mastery", 0.5) or 0.5)

            if mastery < 0.5:
                results += self.rag.search(query, kid, "knowledge", per_k)
                results += self.rag.search(query, kid, "question", per_k)
                # 视频场景下优先 segment（用于推荐播放点）
                if video_id:
                    results += self.rag.search(query, kid, "segment", 1)
            else:
                results += self.rag.search(query, kid, "knowledge", max(1, per_k - 1))
                results += self.rag.search(query, kid, "question", 1)
                if video_id:
                    results += self.rag.search(query, kid, "segment", 1)

        return results

    # ========================
    # 分类
    # ========================
    def _split_docs(self, docs):
        knowledge_docs = []
        question_docs = []
        segment_docs = []

        for d in docs:
            if d["type"] == "knowledge":
                knowledge_docs.append(d["content"])
            elif d["type"] == "question":
                question_docs.append(d["content"])
            elif d["type"] == "segment":
                segment_docs.append(d["content"])

        return knowledge_docs, question_docs, segment_docs

    # ========================
    # 拼 prompt（关键）
    # ========================
    def _build_prompt(
        self,
        user_input,
        mem_items,
        chat_turns,
        knowledge_docs,
        question_docs,
        segment_docs
    ):

        def join_block(title, items):
            if not items:
                return ""
            return f"\n【{title}】\n" + "\n".join(items[:5])

        def join_memory(mem_list: List[Dict[str, Any]]) -> str:
            blocks: List[str] = []
            for m in mem_list[:5]:
                kid = m.get("knowledge_id", "")
                vid = m.get("video_id", "")
                mastery = m.get("mastery", 0.0)
                ktitle = ""
                kcontent = ""
                try:
                    if kid:
                        t = self.memory.r.get(f"knowpals:knowledge:{kid}")
                        c = self.memory.r.get(f"knowpals:knowledge_content:{kid}")
                        if isinstance(t, (bytes, bytearray)):
                            ktitle = t.decode("utf-8", errors="ignore")
                        elif isinstance(t, str):
                            ktitle = t
                        if isinstance(c, (bytes, bytearray)):
                            kcontent = c.decode("utf-8", errors="ignore")
                        elif isinstance(c, str):
                            kcontent = c
                except Exception:
                    pass
                lt = m.get("long_term", "{}")
                st = m.get("short_term", "")
                blocks.append(
                    (
                        f"知识点:{kid}（{ktitle}） video:{vid} mastery:{mastery}\n"
                        f"知识点内容:{kcontent}\n"
                        f"长期:{lt}\n短期:{st}"
                    ).strip()
                )
            return "\n\n".join(blocks).strip()

        def join_chat(turns: List[Dict[str, Any]]) -> str:
            if not turns:
                return ""
            lines = []
            for t in turns[-8:]:
                role = t.get("role", "")
                text = t.get("text", "")
                if role and text:
                    lines.append(f"{role}: {text}")
            return "\n".join(lines).strip()

        prompt = f"""
        你是一个智能学习助手，需要根据学生情况进行个性化教学。
        
        【对话历史（最近）】
        {join_chat(chat_turns)}

        【学生记忆（多知识点聚合）】
        {join_memory(mem_items)}
        
        {join_block("相关知识讲解", knowledge_docs)}
        {join_block("相关练习题", question_docs)}
        {join_block("相关视频讲解", segment_docs)}
        
        请基于以上信息回答学生问题，并做到：
        1. 针对学生薄弱点
        2. 给出清晰讲解
        3. 必要时给出例子或题目
        
        学生问题：
        {user_input}
        """

        return prompt.strip()