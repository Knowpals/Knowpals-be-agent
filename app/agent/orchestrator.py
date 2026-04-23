from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.context.context import ContextBuilder
from app.memory.memory import MemoryTool
from app.model.llm import LLMModel
from app.rag.rag import RagService
from pathlib import Path

from app.skills.skill_loader import SkillSpec, load_skill_catalog
from app.skills.skill_runtime import SkillRuntime
from app.agent.tool_registry import ToolRegistry
from app.agent.chat_memory_writer import ChatMemoryWriteInput, write_chat_turns
from app.agent.react_runner import ReActRunner


@dataclass
class ChatResult:
    reply: str
    context: str
    video_id: str


class LearningAgent:
    """
    A thin orchestrator over ContextBuilder + LLM + Memory.
    Skills are implemented as prompt templates + tool calls via Memory/RAG.
    """

    def __init__(self, *, memory: MemoryTool, rag: RagService, llm: LLMModel) -> None:
        self.memory = memory
        self.rag = rag
        self.llm = llm
        self.context_builder = ContextBuilder(memory, rag)
        self._skills_root = Path(__file__).resolve().parent.parent / "skills"
        self._skill_catalog: list[SkillSpec] = load_skill_catalog(self._skills_root)
        self._skill_by_name: dict[str, SkillSpec] = {s.name: s for s in self._skill_catalog}
        self._runtime = SkillRuntime(llm=llm, memory=memory)
        self._tools = ToolRegistry(memory=memory, rag=rag)
        self._react = ReActRunner(
            llm=llm,
            tools=self._tools,
            runtime=self._runtime,
            skill_by_name=self._skill_by_name,
            max_steps=6,
        )

    def chat(self, *, student_id: str, text: str, video_id: str | None = None, knowledge_id: str | None = None) -> ChatResult:
        # Chat is student-global; but we may still focus on a video if provided.
        vid = (video_id or "").strip() or (self.memory.latest_video_id(student_id) or "unknown")

        # Always include chat turns + short/long memory.
        # RAG is queried on-demand by the ReAct agent via rag.search tool.
        ctx = self.context_builder.build(
            student_id,
            text,
            video_id=vid,
            knowledge_id=knowledge_id,
            topk_knowledge=3,
            need={"chat": True, "chat_limit": 4, "memory": True, "rag": False, "rag_types": []},
        )
        vid2 = ctx.get("video_id", vid)

        agent_input = {
            "student_id": student_id,
            "video_id": vid2,
            "student_text": text,
            "knowledge_id_candidates": ctx.get("knowledge_ids", []) + ["unknown"],
            # keep context short to avoid token overflow; the agent should use tools to fetch more.
            "context_excerpt": (ctx.get("context", "") or "")[:500],
        }
        reply = self._react.run(agent_input=agent_input).reply
        write_chat_turns(
            self.memory,
            ChatMemoryWriteInput(student_id=student_id, video_id=vid2, user_text=text, assistant_text=reply),
        )
        return ChatResult(reply=reply, context=ctx.get("context", ""), video_id=vid2)

    def generate_quiz(self, *, student_id: str, video_id: str, num_questions: int = 5) -> list[dict[str, Any]]:
        # select weak knowledge ids in this video
        weak = self.memory.weak_knowledge_ids(student_id, video_id, limit=max(1, min(10, num_questions)))
        knowledge_ids = [kid for kid, _ in weak] or []
        if not knowledge_ids:
            return []

        # prepare evidence from rag (knowledge + questions) for each knowledge
        evidences: list[dict[str, Any]] = []
        for kid in knowledge_ids:
            docs = []
            docs += self.rag.search("核心概念", kid, "knowledge", 2)
            docs += self.rag.search("典型练习", kid, "question", 2)
            evidences.append({"knowledge_id": kid, "docs": docs})

        prompt = {
            "student_id": student_id,
            "video_id": video_id,
            "weak_knowledge_ids": knowledge_ids,
            "num_questions": max(1, min(int(num_questions), 20)),
            "evidences": evidences,
            "output_schema": {
                "quizzes": [
                    {
                        "knowledge_id": "string",
                        "type": "choice|fill|judge",
                        "question": "string",
                        "options": ["A..", "B..", "C..", "D.."],
                        "answer": "A|B|C|D|短答案|对/错",
                        "analysis": "string",
                        "difficulty": "easy|medium|hard",
                    }
                ]
            },
        }

        msgs = [
            {
                "role": "system",
                "content": (
                    "你是出题老师。请为学生生成个性化练习题，优先覆盖薄弱知识点。"
                    "严格输出 JSON：{ \"quizzes\": [ ... ] }，不要输出任何其他内容。"
                    "请注意，如果是选择题choice类型，输出的答案必须是A|B|C|D，不能字母和选项夹杂在一起"
                ),
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ]
        raw = self.llm.think(msgs)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.strip("```").replace("json", "").strip()
        try:
            obj = json.loads(raw)
            quizzes = obj.get("quizzes", [])
            if isinstance(quizzes, list):
                return quizzes
        except Exception:
            pass
        return []

    def generate_report(self, *, student_id: str, video_id: str, topk: int = 5) -> dict[str, Any]:
        weak = self.memory.weak_knowledge_ids(student_id, video_id, limit=max(1, min(int(topk), 20)))
        items: list[dict[str, Any]] = []
        for kid, mastery in weak:
            mem = self.memory.get_memory(student_id, kid, video_id)
            # recommend segments from rag (jumpable refs)
            segs = self.rag.search("讲解", kid, "segment", 3)
            rec_segments: list[dict[str, Any]] = []
            contents: list[str] = []
            for s in segs:
                md = s.get("metadata") or {}
                seg_id = str(md.get("segment_id") or "")
                if seg_id:
                    rec_segments.append(
                        {
                            "video_id": str(md.get("video_id") or video_id),
                            "segment_id": seg_id,
                            "start_ms": int(md.get("start_ms") or 0),
                            "end_ms": int(md.get("end_ms") or 0),
                        }
                    )
                c = s.get("content")
                if isinstance(c, str) and c.strip():
                    contents.append(c.strip())
            # build item (use long_term json if present)
            try:
                lt = json.loads(mem.get("long_term", "{}") or "{}")
            except Exception:
                lt = {}
            items.append(
                {
                    "knowledge_id": kid,
                    "content":"\n".join(contents),
                    "mastery": float(mastery),
                    "short_term": mem["short_term"],
                    "summary": str(lt.get("summary", "")),
                    "weakness": lt.get("weakness", []) if isinstance(lt.get("weakness", []), list) else [],
                    "behavior_pattern": lt.get("behavior_pattern", []) if isinstance(lt.get("behavior_pattern", []), list) else [],
                    "trend": str(lt.get("trend", "")),
                    "recommended_segments": rec_segments,
                }
            )

        overall_prompt = {
            "student_id": student_id,
            "video_id": video_id,
            "items": items,
            "instruction": """
                           请结合提供的所有数据，生成该学生观看本视频后的详细学情报告，需严格覆盖以下所有内容，分点描述（每个核心维度作为一个大点，不拆分过多小点），内容详实、分析深入，不遗漏任何数据
                           注意：不要出现任何id的内容，只输出id所对应的内容，返回结果不要暴露任何一个id给用户
                           1. 学生整体学习概况（结合所有薄弱知识点，总结整体掌握水平）；
                           2. 薄弱知识点详细分析（每个薄弱知识点对应：知识点具体内容、学生当前掌握程度描述、该知识点关联的视频片段说明、学生在该知识点上的短期记忆情况分析）；
                           3. 错因深度分析（结合知识点内容、学生掌握程度和短期记忆，分析学生薄弱的核心原因，不笼统，贴合具体知识点）；
                           4. 针对性学习建议（结合每个薄弱知识点的特点、关联视频片段、短期记忆情况，给出可落地、有针对性的建议，建议需对应薄弱点，不泛泛而谈）
                           报告整体逻辑连贯，语言专业、简洁，输出纯文本，无需任何多余格式
                           """,
        }
        msgs = [
            {"role": "system", "content": "你是学习报告助手。输出简洁、可执行的建议。"},
            {"role": "user", "content": json.dumps(overall_prompt, ensure_ascii=False)},
        ]
        overall = self.llm.think(msgs)
        return {"video_id": video_id, "items": items, "overall_summary": overall}

