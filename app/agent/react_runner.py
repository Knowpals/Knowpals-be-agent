from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.agent.tool_registry import ToolRegistry
from app.model.llm import LLMModel
from app.skills.skill_loader import SkillSpec
from app.skills.skill_runtime import SkillRuntime


@dataclass
class ReActResult:
    reply: str
    trace: list[dict[str, Any]]


class ReActRunner:
    """
    Minimal ReAct loop (JSON protocol) that can:
    - call tools from ToolRegistry
    - call skills (SKILL.md) via SkillRuntime.run_tool_driven
    """

    def __init__(
        self,
        *,
        llm: LLMModel,
        tools: ToolRegistry,
        runtime: SkillRuntime,
        skill_by_name: dict[str, SkillSpec],
        max_steps: int = 3,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.runtime = runtime
        self.skill_by_name = skill_by_name
        self.max_steps = max_steps

    @staticmethod
    def _safe_json(text: str) -> dict[str, Any] | None:
        """
        Best-effort JSON object parser.
        Returns dict on success, None on failure (so caller can retry).
        """
        t = (text or "").strip()
        if not t:
            return None
        if t.startswith("```"):
            t = t.strip("```").replace("json", "").strip()
        # 1) direct parse
        try:
            obj = json.loads(t)
            return obj if isinstance(obj, dict) else None
        except Exception:
            pass
        # 2) extract first balanced {...} object (handles extra trailing braces)
        start = t.find("{")
        if start == -1:
            return None
        in_str = False
        esc = False
        depth = 0
        end_idx = None
        for i in range(start, len(t)):
            ch = t[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            else:
                if ch == '"':
                    in_str = True
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end_idx = i
                        break
        if end_idx is not None:
            candidate = t[start : end_idx + 1]
            try:
                obj = json.loads(candidate)
                return obj if isinstance(obj, dict) else None
            except Exception:
                return None
        return None

    def run(self, *, agent_input: dict[str, Any]) -> ReActResult:
        # We keep chain-of-thought private: model may include "thought" field in JSON,
        # but we never return it to user; only keep in trace.
        # Keep these compact to avoid bloating the system prompt.
        tool_list = [{"name": t["name"], "description": t["description"]} for t in self.tools.list()]
        skill_list = [{"name": s.name, "description": s.description} for s in self.skill_by_name.values()]

        allowed_tool_names = [t["name"] for t in self.tools.list()]
        allowed_skill_names = sorted(self.skill_by_name.keys())

        sys = (
            "你是一个真正的 ReAct 学习助理。你会基于观察(Observation)进行推理并决定下一步行动(Action)。\n"
            "停止/防重复硬规则（非常重要）：\n"
            "- 每一步在决定 action 前，先做 Stop Check：如果你已经有足够信息可以回答，就必须输出 final 结束。\n"
            "- 除非上一次 action 明确失败（Observation.error 存在），否则不要重复调用同一个 action（尤其不要重复 chat.get_turns）。\n"
            "- 不要为了“补上下文”反复调用工具；context_excerpt 已包含关键上下文。\n"
            "技能调用门槛（硬规则）：\n"
            "- wrong_answer_explain 只允许在“错题/选错/为什么错/解析/我的答案不对”等场景调用；"
            "如果学生只是说“我不理解某个概念”，必须直接 final 用正常讲解回答，禁止调用 wrong_answer_explain。\n"
            "- followup_quiz 只在学生明确要练习/出题/测一测，或你刚完成讲解后用于巩固时调用；不要在一开始强行出题。\n"
            "你必须严格输出 JSON（不要输出任何额外文本）。每一步只能二选一：\n"
            '1) 继续行动：{"thought":"...","action":{"type":"tool"|"skill","name":"...","args":{...}}}\n'
            '2) 结束：{"final":"给学生的最终回复文本"}\n'
            "重要：final 必须是自然语言纯文本，不要输出 markdown，不要输出 JSON。\n"
            "你可以多步调用：例如先解释错因（skill:wrong_answer_explain），再出题巩固（skill:followup_quiz）。\n"
            f"硬约束：action.type 只能是 tool 或 skill；action.name 必须从白名单中选。\n"
            f"tool 白名单：{json.dumps(allowed_tool_names, ensure_ascii=False)}\n"
            f"skill 白名单：{json.dumps(allowed_skill_names, ensure_ascii=False)}\n"
            "示例：\n"
            '{"thought":"需要讲解错因","action":{"type":"skill","name":"wrong_answer_explain","args":{"student_id":"...","video_id":"...","student_question":"..."}}}\n'
            '{"final":"（概念讲解）力是物体间的相互作用……（用通俗例子解释）……你可以用一句话说说你觉得“推门”的力来自哪里吗？"}\n'
            f"可用 tools: {json.dumps(tool_list, ensure_ascii=False)}\n"
            f"可用 skills: {json.dumps(skill_list, ensure_ascii=False)}\n"
        )

        trace: list[dict[str, Any]] = []
        observation: Any = {"start": True}
        actions_taken = 0
        must_finalize_next = False
        finalize_nag_count = 0
        last_good_reply: str | None = None
        msgs: list[dict[str, Any]] = [
            {"role": "system", "content": sys},
            {"role": "user", "content": json.dumps({"input": agent_input}, ensure_ascii=False)},
        ]

        for _ in range(self.max_steps):
            if observation is not None:
                msgs.append({"role": "assistant", "content": json.dumps({"observation": observation}, ensure_ascii=False)})
                observation = None

            raw = (self.llm.think(msgs) or "").strip()
            step = self._safe_json(raw)
            if step is None:
                trace.append({"raw": raw, "parsed": None})
                observation = {
                    "error": "json_parse_error",
                    "hint": "请严格输出单个 JSON 对象，不要多余括号/文本",
                    "raw": raw[:500],
                }
                continue
            trace.append({"raw": raw, "parsed": step})

            if "final" in step:
                return ReActResult(reply=str(step.get("final") or "").strip(), trace=trace)

            if must_finalize_next:
                finalize_nag_count += 1
                if last_good_reply:
                    return ReActResult(reply=last_good_reply, trace=trace)
                if finalize_nag_count >= 2:
                    # Hard fallback: produce a final answer directly from context_excerpt.
                    ctx = str(agent_input.get("context_excerpt", "") or "")
                    q = str(agent_input.get("student_text", "") or "")
                    final = self.llm.think(
                        [
                            {"role": "system", "content": "你是学习助手。请基于上下文直接回答学生问题。输出纯文本。"},
                            {"role": "user", "content": f"问题：{q}\n\n上下文：\n{ctx}"},
                        ]
                    ) or ""
                    return ReActResult(reply=final.strip() or "error", trace=trace)
                observation = {
                    "error": "must_finalize_now",
                    "hint": "你上一轮已经执行过 action。下一步必须输出 {\"final\":\"...\"} 结束，不要再输出 action。",
                }
                continue

            action = step.get("action")
            if not isinstance(action, dict):
                observation = {"error": "missing action"}
                continue

            a_type = str(action.get("type", "") or "")
            a_name = str(action.get("name", "") or "")
            a_args = action.get("args")
            if not isinstance(a_args, dict):
                a_args = {}

            actions_taken += 1
            # Strong budget: allow at most 2 actions total, then force final.
            if actions_taken >= 2:
                must_finalize_next = True

            if a_type == "tool":
                try:
                    result = self.tools.call(name=a_name, args=a_args)
                    observation = {"tool": a_name, "result": result}
                except Exception as e:
                    observation = {"tool": a_name, "error": str(e)}
                must_finalize_next = True
                continue

            if a_type == "skill":
                spec = self.skill_by_name.get(a_name)
                if not spec:
                    observation = {"skill": a_name, "error": "unknown skill"}
                    continue
                try:
                    # stateless: skill is only a prompt template; no internal tool calls.
                    text = self.runtime.run_stateless(spec=spec, skill_input=a_args)
                    observation = {"skill": a_name, "reply": text}
                    if isinstance(text, str) and text.strip():
                        last_good_reply = text.strip()
                except Exception as e:
                    observation = {"skill": a_name, "error": str(e)}
                must_finalize_next = True
                continue

            observation = {"error": f"unknown action type: {a_type}"}

        return ReActResult(reply="error", trace=trace)

