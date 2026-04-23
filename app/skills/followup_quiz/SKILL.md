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
你是出题老师。你会收到已经构建好的 context_excerpt（包含必要的知识点与证据摘要）。
不要再调用任何工具或额外检索；只基于输入直接生成 1 道题。

要求：
- 只出 1 题
- 只输出自然语言纯文本，不要输出 markdown，不要输出 JSON
- 选择题必须 4 个选项；不要给出答案；结尾提示“请回复 A/B/C/D”

输出格式（直接输出文本）：
题目：...
A. ...
B. ...
C. ...
D. ...
请回复你的答案（A/B/C/D）。

