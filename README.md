PythonWorker项目结构：
```text
knowpals-be-agent/
├── app/
│   ├── main.py                # 启动入口
│
│   ├── config/
│   │   └── settings.py        # 配置（Kafka / Redis）
│
│   ├── infra/
│   │   ├── kafka.py           # Kafka 封装
│   │   └── redis_client.py    # Redis 幂等
│
│   ├── model/
│   │   └── message.py         # Task / Result 定义
│
│   ├── worker/
│   │   ├── consumer.py        # Kafka 消费入口（核心）
│   │   └── producer.py        # 发送结果
│
│   ├── pipeline/
│   │   └── dispatcher.py      # Stage 分发器（核心）
│
│   ├── handlers/              # 各阶段逻辑（核心）
│   │   ├── asr.py
│   │   ├── segment.py
│   │   ├── concept.py
│   │   ├── align.py
│   │   └── quiz.py
│
│   └── utils/
│       └── logger.py
│
└── requirements.txt
```

go发送到kafka的任务消息：
```json
{
  "job_id": "uuid",
  "stage": "stage",
  "payload": "payload",
  "retry": 0
}
```

python处理完后发送给kafka的消息：
```json
{
  ""
}
```

asr返回原始结构：
```json
"properties": {
        "audio_format": "aac",
        "channels": [
            0,
            1
        ],
        "original_sampling_rate": 44100,
        "original_duration_in_milliseconds": 79271
    },
    "transcripts": [
        {
            "channel_id": 0,
            "content_duration_in_milliseconds": 72160,
            "text": "也许我们小时候都曾经打碎过桌上的杯子，每当这时候，妈妈就出现了，暴躁的怒喊着：“谁干的？”如果你是一个狡猾的孩子，你一定回答过：“哦，妈咪，是地板！”啊，于是你被胖揍了一顿。不过，你从来没有考虑过你回答的科学性吗？我们来慢镜头重放一下：一秒前，杯子正在落地；一秒后，杯子就碎了。中间的这一秒，杯子和地板来了个亲密接触 啊！哦，真的是地板！地板给了杯子一个力。什么是力？力就是一个物体对另一个物体的作用。手拉弓、脚踩球、挖掘机挖土、地球吸引月亮、磁铁吸引铁钉，这都是力，都是一个物体对另 一个物体的作用。我们把手、脚、挖掘机、地球、磁铁这类力的发出者叫做施力物体，而弓、球、土、月亮、铁钉这类力的承受者叫做受力物体。施力物体与受力物体二者缺一不可。力的英 文单词为FORCE，所以符号为F。为了纪念伟大的物理学家艾萨克·牛顿先生，所以力的单位为牛顿，简称牛，符号为N。F等于一牛，表示力的大小为一牛。那一牛是多大？就是托起两个鸡蛋所花费的力。总结一下，力是一个物体对另一个物体的作用，符号为F，单位为牛。你学会了吗？May the force be with you，呼呼。",
            "sentences": [
                {
                    "begin_time": 1240,
                    "end_time": 7480,
                    "text": "也许我们小时候都曾经打碎过桌上的杯子，每当这时候，妈妈就出现了，暴躁的怒喊着：“谁干的？",
                    "sentence_id": 1,
                    "words": [
                        {
                            "begin_time": 1240,
                            "end_time": 1560,
                            "text": "也许",
                            "punctuation": ""
                        },
                        {
                            "begin_time": 1560,
                            "end_time": 1720,
                            "text": "我们",
                            "punctuation": ""
                        },
                        {
                            "begin_time": 1720,
                            "end_time": 2120,
                            "text": "小时候",
                            "punctuation": ""
                        },
                        {
                            "begin_time": 2120,
                            "end_time": 2280,
                            "text": "都",
                            "punctuation": ""
                        },
                        {
                            "begin_time": 2280,
                            "end_time": 2560,
                            "text": "曾经",
                            "punctuation": ""
                        },
                        {
                            "begin_time": 2560,
                            "end_time": 2640,
                            "text": "打",
                            "punctuation": ""
                        },
                        {
                            "begin_time": 2640,
                            "end_time": 2800,
                            "text": "碎",
                            "punctuation": ""
                        },
                        {
                            "begin_time": 2800,
                            "end_time": 2960,
                            "text": "过",
                            "punctuation": ""
                        },
                        {
                            "begin_time": 2960,
                            "end_time": 3080,
                            "text": "桌",
                            "punctuation": ""
                        },
                        {
                            "begin_time": 3080,
                            "end_time": 3320,
                            "text": "上的",
                            "punctuation": ""
                        },
                        {
                            "begin_time": 3320,
                            "end_time": 3680,
                            "text": "杯子",
                            "punctuation": "，"
                        },
                        {
                            "begin_time": 3800,
                            "end_time": 4120,
                            "text": "每当",
                            "punctuation": ""
                        },
                        {
                            "begin_time": 4120,
                            "end_time": 4480,
                            "text": "这时候",
                            "punctuation": "，"
                        },
                        {
                            "begin_time": 4560,
                            "end_time": 4840,
                            "text": "妈妈",
                            "punctuation": ""
                        },
                        {
                            "begin_time": 4840,
                            "end_time": 4960,
                            "text": "就",
                            "punctuation": ""
                        },
                        {
                            "begin_time": 4960,
                            "end_time": 5400,
                            "text": "出现了",
                            "punctuation": "，"
                        },
                        {
                            "begin_time": 5560,
                            "end_time": 5760,
                            "text": "暴",
                            "punctuation": ""
                        },
                        {
                            "begin_time": 5760,
                            "end_time": 5880,
                            "text": "躁",
                            "punctuation": ""
                        },
                        {
                            "begin_time": 5880,
                            "end_time": 6000,
                            "text": "的",
                            "punctuation": ""
                        },
                        {
                            "begin_time": 6000,
                            "end_time": 6160,
                            "text": "怒",
                            "punctuation": ""
                        },
                        {
                            "begin_time": 6160,
                            "end_time": 6320,
                            "text": "喊",
                            "punctuation": ""
                        },
                        {
                            "begin_time": 6320,
                            "end_time": 6440,
                            "text": "着",
                            "punctuation": ""
                        },
                        {
                            "begin_time": 6440,
                            "end_time": 6560,
                            "text": "：",
                            "punctuation": ""
                        },
                        {
                            "begin_time": 6560,
                            "end_time": 6680,
                            "text": "“",
                            "punctuation": ""
                        },
                        {
                            "begin_time": 6680,
                            "end_time": 6960,
                            "text": "谁",
                            "punctuation": ""
                        },
                        {
                            "begin_time": 6960,
                            "end_time": 7240,
                            "text": "干",
                            "punctuation": ""
                        },
                        {
                            "begin_time": 7240,
                            "end_time": 7480,
                            "text": "的",
                            "punctuation": "？"
                        }
                    ]
                },
        }
]
```