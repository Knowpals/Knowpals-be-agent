import json
from typing import Any

from app.handler.handler import StageHandler
from app.model.llm import LLMModel


class QuizStage(StageHandler):
    def __init__(self,llm_model:LLMModel):
        self.llm_model=llm_model

    def run(self, payload: dict[str, Any]) -> Any:
        segments = payload["segments"]
        concepts = payload["concepts"]

        concept_map = {c["concept_id"]: c for c in concepts}
        quizzes = []

        for seg in segments:
            concept = concept_map.get(seg["concept_id"], {})

            q = self.generate_question(seg, concept)

            if q:
                q["question_id"] = f"q_{seg['segment_id']}_{len(quizzes) + 1}"
                q["segment_id"] = seg["segment_id"]
                q["concept_id"] = concept["concept_id"]

                quizzes.append(q)

        return {"quizzes": quizzes}

    def generate_question(self,segment:dict,concept:dict)->dict[str, Any]:
        prompt = [
            {
                "role": "system",
                "content": """
                你是一个优秀的出题老师。
                你需要根据教学内容生成题目，题型有三种：
                ---
                【题型说明】
                1. choice（选择题）
                - 4个选项A/B/C/D（选项前面必须是ABCD，而不是字符串）
                - 只有一个正确答案(A|B|C|D而不是正确选项的字符串)
                - 适合考概念理解
        
                2. fill（填空题）
                - 问题中有一个空
                - answer是一个短答案
                - 不需要options
                - 适合考记忆
        
                3. judge（判断题）
                - 判断对错
                - answer只能是 "对" 或 "错"
                - 不需要options
                ---
                【要求】
                1. 每个segment生成1题
                2. 必须是choice,fill,judge三种题型中的一种
                3. 不允许重复问句
                4. 不要照抄原文
                5. 题目必须考察理解，而不是复述
                6. 难度：easy / medium / hard
                7. 如果此分段的知识点包含“总结”,出的题请包括这个视频中的全部知识点
                8. 需要输出此题所考察的知识点id
                ---
                【输出格式】
                返回JSON：
                
                {
                  "type": "",
                  "question": "",
                  "options": [],
                  "answer": "",
                  "analysis": "",
                  "difficulty": "easy|medium|hard",
                  "concept_id": "c1"
                }
                
                ---
                注意：
                - fill题没有 options
                - judge题 answer只能是 “对” 或 “错”
                """
            },
            {
                "role": "user",
                "content": json.dumps({
                    "concept_title": concept.get("title", ""),
                    "concept_content": concept.get("content", ""),
                    "segment_text": segment["text"]
                }, ensure_ascii=False)
            }
        ]

        result = self.llm_model.think(prompt)
        try:
            return json.loads(result)
        except Exception as e:
            raise e

