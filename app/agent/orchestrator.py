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

    def _llm_choose_skills(self, *, text: str, ctx: dict[str, Any], video_id: str) -> dict[str, Any]:
        """Let LLM decide which skills to run and which knowledge_id is being discussed."""
        catalog = [
            {"name": s.name, "description": s.description, "when_to_call": s.when_to_call}
            for s in self._skill_catalog
        ]
        candidates = ctx.get("knowledge_ids", []) or []
        selector_payload = {
            "student_question": text,
            "video_id": video_id,
            "context_summary": {
                "weak_memory": (ctx.get("memory") or [])[:3],
                "rag_types": [d.get("type") for d in (ctx.get("rag_docs") or [])[:6]],
            },
            "knowledge_id_candidates": candidates + ["unknown"],
            "available_skills": catalog,
            "output_schema": {"skills": ["skill_name"], "knowledge_id": "string", "reason": "string"},
        }
        msgs = [
            {
                "role": "system",
                "content": (
                    "你是技能编排器。根据学生问题与上下文，从可用技能中选择要触发的技能列表。"
                    "只在确实相关时触发技能（如果没有可以不选,选也不用全选）。并选择一个 knowledge_id（从候选里选）。"
                    "严格输出 JSON：{skills:[...], knowledge_id:\"...\", reason:\"...\"}，不要输出任何额外内容。"
                ),
            },
            {"role": "user", "content": json.dumps(selector_payload, ensure_ascii=False)},
        ]
        raw = (self.llm.think(msgs) or "").strip()
        if raw.startswith("```"):
            raw = raw.strip("```").replace("json", "").strip()
        try:
            obj = json.loads(raw)
        except Exception:
            obj = {"skills": [], "knowledge_id": "unknown", "reason": raw}
        # sanitize
        skills = obj.get("skills", [])
        if not isinstance(skills, list):
            skills = []
        obj["skills"] = [s for s in skills if isinstance(s, str) and s in self._skill_by_name]
        kid = obj.get("knowledge_id")
        if kid not in candidates and kid != "unknown":
            obj["knowledge_id"] = "unknown"
        return obj

    def _run_skill(self, *, skill_name: str, skill_input: dict[str, Any]) -> str:
        spec = self._skill_by_name.get(skill_name)
        if spec is None:
            return ""
        msgs = [
            {"role": "system", "content": spec.system_prompt},
            {"role": "user", "content": json.dumps(skill_input, ensure_ascii=False)},
        ]
        return self.llm.think(msgs) or ""

    @staticmethod
    def _safe_json(text: str) -> dict[str, Any]:
        t = (text or "").strip()
        if t.startswith("```"):
            t = t.strip("```").replace("json", "").strip()
        try:
            obj = json.loads(t)
            return obj if isinstance(obj, dict) else {"value": obj}
        except Exception:
            return {"raw": text}

    @staticmethod
    def _render_followup_quiz(obj: dict[str, Any]) -> str:
        quiz = obj.get("quiz") if isinstance(obj.get("quiz"), dict) else {}
        if not quiz:
            return ""
        qtype = str(quiz.get("type", "") or "")
        q = str(quiz.get("question", "") or "")
        options = quiz.get("options") or []
        lines = []
        if q:
            lines.append(f"练习题（{qtype}）: {q}".strip())
        if isinstance(options, list) and options:
            lines.extend([str(x) for x in options[:4]])
        return "\n".join(lines).strip()

    def chat(self, *, student_id: str, text: str, video_id: str | None = None, knowledge_id: str | None = None) -> ChatResult:
        # Chat is student-global; but we may still focus on a video if provided.
        vid = (video_id or "").strip() or (self.memory.latest_video_id(student_id) or "unknown")

        ctx = self.context_builder.build(student_id, text, video_id=vid, knowledge_id=knowledge_id, topk_knowledge=3)
        vid2 = ctx.get("video_id", vid)

        # Let LLM choose which SKILLs to run and which knowledge_id this question is about
        plan = self._llm_choose_skills(text=text, ctx=ctx, video_id=vid2)
        chosen_skills: list[str] = plan.get("skills", [])
        inferred_kid: str = plan.get("knowledge_id", "unknown")

        # Run selected skills
        skill_outputs: dict[str, Any] = {}
        # deterministic weakness analyzer output
        weak = []
        for m in (ctx.get("memory") or []):
            kid = m.get("knowledge_id")
            mastery = float(m.get("mastery", 0.0) or 0.0)
            if kid:
                weak.append({"knowledge_id": kid, "mastery": mastery})
        weak.sort(key=lambda x: x["mastery"])
        skill_outputs["weakness_analyzer"] = {"weak_knowledge": weak[:5]}

        # Special: guided_dialog is stateful multi-turn, driven by SKILL.md prompts
        if "guided_dialog" in chosen_skills and "guided_dialog" in self._skill_by_name:
            spec = self._skill_by_name["guided_dialog"]
            res = self._runtime.run_stateful(
                student_id=student_id,
                spec=spec,
                start_input={
                    "student_question": text,
                    "video_id": vid2,
                    "knowledge_id_candidates": ctx.get("knowledge_ids", []) + ["unknown"],
                    "memory": ctx.get("memory", []),
                    "rag_docs": (ctx.get("rag_docs") or [])[:6],
                },
                continue_input={"student_answer": text},
                ttl_seconds=600,
            )
            # render guided reply directly; do not run other skills if guided_dialog is active
            reply = res.reply.strip()
            self.memory.add_chat_turn(student_id=student_id, role="student", text=text, video_id=vid2)
            self.memory.add_chat_turn(student_id=student_id, role="assistant", text=reply, video_id=vid2)
            kid = "unknown"
            if res.state and isinstance(res.state, dict):
                kid = str(res.state.get("knowledge_id", "unknown") or "unknown")
            self.memory.write(student_id, {"type": "chat", "knowledge_id": kid, "video_id": vid2, "text": text, "intent": "chat"})
            return ChatResult(reply=reply, context=ctx.get("context", ""), video_id=vid2)

        for s in chosen_skills:
            if s == "wrong_answer_explain":
                skill_outputs[s] = self._safe_json(self._run_skill(
                    skill_name=s,
                    skill_input={
                        "student_question": text,
                        "video_id": vid2,
                        "memory": ctx.get("memory", []),
                        "rag_knowledge": [d for d in (ctx.get("rag_docs") or []) if d.get("type") == "knowledge"][:4],
                    },
                ))
            elif s == "followup_quiz":
                skill_outputs[s] = self._safe_json(self._run_skill(
                    skill_name=s,
                    skill_input={
                        "student_id": student_id,
                        "video_id": vid2,
                        "target_knowledge_ids": ctx.get("knowledge_ids", [])[:2],
                        "evidences": [
                            {"knowledge_id": kid, "docs": self.rag.search("练习", kid, "question", 2)}
                            for kid in (ctx.get("knowledge_ids", [])[:2])
                        ],
                    },
                ))

        # Render to plain text for chat UI (no JSON)
        parts: list[str] = []

        gt = skill_outputs.get("guided_thinking") if isinstance(skill_outputs.get("guided_thinking"), dict) else None
        if gt:
            qs = gt.get("guided_questions") if isinstance(gt.get("guided_questions"), list) else []
            exp = str(gt.get("key_explanation", "") or "")
            if qs:
                parts.append("我先问你两个小问题，帮助你自己推出来：")
                for i, q in enumerate(qs[:2], start=1):
                    parts.append(f"{i}. {str(q)}")
            if exp:
                parts.append(f"关键解释：{exp}")

        we = skill_outputs.get("wrong_answer_explain") if isinstance(skill_outputs.get("wrong_answer_explain"), dict) else None
        if we:
            explain = str(we.get("explain", "") or "")
            cause = str(we.get("mistake_cause", "") or "")
            steps = we.get("fix_steps") if isinstance(we.get("fix_steps"), list) else []
            if explain:
                parts.append(explain)
            if cause:
                parts.append(f"错因：{cause}")
            if steps:
                parts.append("纠正步骤：")
                for i, s in enumerate(steps[:3], start=1):
                    parts.append(f"{i}. {str(s)}")

        fq = skill_outputs.get("followup_quiz") if isinstance(skill_outputs.get("followup_quiz"), dict) else None
        if fq:
            quiz_txt = self._render_followup_quiz(fq)
            if quiz_txt:
                parts.append(quiz_txt)
                parts.append("你先做这题，告诉我你的答案（只回复选项字母/答案即可）。")

        # If no skills produced usable text, fallback to a normal assistant answer (still plain text)
        if not parts:
            msgs = [
                {"role": "system", "content": "你是个性化学习助手。请结合上下文简洁回答学生问题。"},
                {"role": "user", "content": ctx.get("context", "")},
            ]
            reply = self.llm.think(msgs)
        else:
            reply = "\n".join([p for p in parts if p.strip()]).strip()

        # Write chat memory AFTER reply, using inferred knowledge_id (video scoped)
        self.memory.add_chat_turn(student_id=student_id, role="student", text=text, video_id=vid2)
        self.memory.add_chat_turn(student_id=student_id, role="assistant", text=reply, video_id=vid2)
        self.memory.write(
            student_id,
            {
                "type": "chat",
                "knowledge_id": inferred_kid if inferred_kid else "unknown",
                "video_id": vid2,
                "text": text,
                "intent": "chat",
            },
        )
        return ChatResult(reply=reply, context=ctx["context"], video_id=ctx.get("video_id", vid))

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
            # recommend segments from rag (best-effort)
            segs = self.rag.search("讲解", kid, "segment", 3)
            rec_seg_ids = []
            for s in segs:
                md = s.get("metadata") or {}
                sid = md.get("segment_id")
                if sid:
                    rec_seg_ids.append(str(sid))
            # build item (use long_term json if present)
            try:
                lt = json.loads(mem.get("long_term", "{}") or "{}")
            except Exception:
                lt = {}
            items.append(
                {
                    "knowledge_id": kid,
                    "mastery": float(mastery),
                    "summary": str(lt.get("summary", "")),
                    "weakness": lt.get("weakness", []) if isinstance(lt.get("weakness", []), list) else [],
                    "behavior_pattern": lt.get("behavior_pattern", []) if isinstance(lt.get("behavior_pattern", []), list) else [],
                    "trend": str(lt.get("trend", "")),
                    "recommended_segments": rec_seg_ids,
                }
            )

        overall_prompt = {
            "student_id": student_id,
            "video_id": video_id,
            "items": items,
            "instruction": "请总结该学生看完本视频后的整体薄弱点与学习建议（1-3条），输出纯文本。",
        }
        msgs = [
            {"role": "system", "content": "你是学习报告助手。输出简洁、可执行的建议。"},
            {"role": "user", "content": json.dumps(overall_prompt, ensure_ascii=False)},
        ]
        overall = self.llm.think(msgs)
        return {"video_id": video_id, "items": items, "overall_summary": overall}

