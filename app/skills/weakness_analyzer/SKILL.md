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

