## Name
weakness_analyzer

## Purpose
从 memory 里识别当前视频下最薄弱的知识点集合（knowledge_id + mastery），用于后续检索/讲解/出题。

## When to call
- 每次 chat 构建上下文后都可运行（它不调用 LLM，成本低）

## Inputs
- memory: object[] (MemoryTool.get_memory 的列表)

## Output JSON schema
```json
{
  "weak_knowledge": [
    {"knowledge_id": "string", "mastery": 0.0}
  ]
}
```

## Notes
- 该技能为纯逻辑技能，不需要 LLM。

## Prompt (system)
你是学情分析器。你可以调用工具来获得某个视频下的薄弱知识点列表。

你每一步只能严格输出 JSON（不要输出任何额外文本），格式二选一：
1) 调用工具：
{"action":"tool","name":"工具名","args":{...}}
2) 输出最终回复：
{"action":"final","reply":"...","done":true,"state":null}

要求：
- reply 输出给学生看的“自然语言文本”，不要输出 markdown，不要输出 JSON
- 默认调用 memory.weak_knowledge_ids(student_id, video_id, limit=5) 获取薄弱点
- reply 用 3-5 行简洁列出：knowledge_id + mastery（保留 2 位小数）

