## Name
followup_quiz

## Purpose
在“讲解错题”或“讲解知识点”之后给 1 道跟进练习题，检验学生是否真的理解。

## When to call
- 学生主动要求：来道题/练习/出题/测一测
- 或者刚完成讲解（guided_thinking 或 wrong_answer_explain 已触发），且 mastery<0.6

## Inputs
- student_id: string
- video_id: string
- target_knowledge_ids: string[]
- evidences: object[] (RAG 证据)

## Output JSON schema
```json
{
  "quiz": {
    "knowledge_id": "string",
    "type": "choice|fill|judge",
    "question": "string",
    "options": ["string"],
    "answer": "string",
    "analysis": "string",
    "difficulty": "easy|medium|hard"
  }
}
```

## Constraints
- 只出 1 题
- 不要输出 markdown
- 选择题必须 4 个选项，答案必须是 A/B/C/D

## Prompt (system)
你是出题老师。根据目标知识点与证据，为学生出 1 道能检验理解的题（不要照抄原文）。严格输出 JSON：{quiz:{...}}，不要输出任何额外内容。

