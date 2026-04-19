文件结构：
```text
knowpals-be-agent/
├── app/
│   ├── main.py
│   ├── cache/
│   │   └── cache.py
│   ├── config/
│   │   ├── loader.py
│   │   └── config/
│   │       └── config.yaml
│   ├── dispatch/
│   │   └── dispatcher.py
│   ├── handler/
│   │   ├── handler.py
│   │   ├── knowledge_segment.py
│   │   ├── quiz.py
│   │   └── summarize_profile.py          # 新增：Go触发(len>3)后的总结写MySQL
│   ├── ioc/
│   │   ├── dispatcher.py
│   │   ├── kafka_clients.py
│   │   ├── pipeline.py
│   │   └── redis.py
│   ├── message/
│   │   └── message.py
│   ├── model/
│   │   ├── asr.py
│   │   └── llm.py
│   ├── worker/
│   │   ├── consumer.py
│   │   └── producer.py
│   │
│   ├── agent/                            # 新增：编排层（功能1/2/3入口）
│   │   ├── orchestrator.py               # 统一编排：quiz/report/chat
│   │   ├── context_builder.py            # 拼上下文：Redis短期+MySQL长期+RAG片段
│   │   └── policies.py                   # 冷却/限次/TopK/降级策略
│   │
│   ├── memory/                           # 新增：分层记忆访问层
│   │   ├── short_term_store.py           # Redis短期记忆：key=(student_id,knowledge_id)
│   │   ├── long_term_store.py            # MySQL长期画像：读写学生画像
│   │   └── schemas.py                    # 统一Pydantic/TypedDict的入参出参schema
│   │
│   ├── rag/                              # 新增：RAG 检索层（Milvus + embedding）
│   │   ├── milvus_client.py              # collection创建/连接/upsert/search
│   │   ├── collections.py                # collection schema：segments / student_memories
│   │   ├── embedding.py                  # embedding client（OpenAI/DashScope）
│   │   └── retriever.py                  # 封装按knowledge_id检索segments、按student检索记忆
│   │
│   ├── integrations/                     # 新增：外部依赖适配（避免散落各处）
│   │   ├── mysql/
│   │   │   ├── engine.py                 # 连接池/engine（或原生驱动封装）
│   │   │   └── repos.py                  # repo实现（student_profile、weakness、mistake_pattern）
│   │   ├── milvus/
│   │   │   └── index_admin.py            # 初始化索引/检查collection（启动时可选）
│   │   └── redis/
│   │       └── keys.py                   # Redis key规范集中管理
│   │
│   ├── skills/                           # 新增：你要的3类SKILL（契约+实现）
│   │   ├── guided_thinking/
│   │   │   ├── SKILL.md                  # 引导性思考SKILL
│   │   │   └── impl.py
│   │   ├── wrong_answer_explain/
│   │   │   ├── SKILL.md                  # 讲解错题SKILL
│   │   │   └── impl.py
│   │   ├── study_recommend/
│   │   │   ├── SKILL.md                  # 推荐学习SKILL（输出segment_ids）
│   │   │   └── impl.py
│   │   ├── personalized_quiz/
│   │   │   ├── SKILL.md                  # 个性化出题SKILL
│   │   │   └── impl.py
│   │   └── learning_report/
│   │       ├── SKILL.md                  # 学习报告SKILL
│   │       └── impl.py
│   │
│   └── utils/
│       ├── ids.py                        # 统一segment_id/knowledge_id/trigger_id生成规则（可选）
│       └── json.py                       # json安全解析/校验（可选）
│
├── proto/                                # 新增：可选（若未来上gRPC），先放协议草案也行
│   └── README.md
│
├── db/                                   # 新增：MySQL DDL / migration（不影响现有代码）
│   ├── ddl/
│   │   ├── student_profile.sql
│   │   └── student_mistake_patterns.sql
│   └── README.md
│
└── docs/                                 # 新增：设计说明（不改代码）
    ├── memory_arch.md
    ├── milvus_schema.md
    └── skills_contract.md
```