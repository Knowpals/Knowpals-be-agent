import json
from typing import Any, List

from redis import Redis

from app.handler.handler import StageHandler
from app.model.asr import ASRModel
from app.model.llm import LLMModel

import hashlib

from app.rag.rag import RagService


class KnowledgeSegmentStage(StageHandler):
    def __init__(self,asr_model:ASRModel,llm_model:LLMModel,redis:Redis,rag:RagService):
        self.asr_model=asr_model
        self.llm_model=llm_model
        self.redis=redis
        self.rag=rag

    def run(self, payload: dict[str, Any]) -> Any:
        #asr
        asr_result=self.asr_model.transcribe(payload)
        sentences=asr_result["sentences"]
        if not sentences:
            return {
                "concepts": [],
                "segments": [],
                "duration_ms": 0
            }

        #llm抽取 concept+sentence mapping
        concepts_raw=self.extract_concepts(sentences)
        #构建concepts + segments
        concepts, segments = self.build_output(sentences, concepts_raw)

        #存入rag
        video_id = str(payload.get("video_id", "") or "")
        concepts_meta_map: dict[str, List[dict[str, Any]]] = {}
        for s in segments:
            concepts_meta_map.setdefault(s["concept_id"], []).append({
                "segment_id": s["segment_id"],
                "start_ms": s["start_ms"],
                "end_ms": s["end_ms"],
            })
        for _,c in enumerate(concepts):
            self.rag.add_doc(
                "knowledge",
                c["content"],
                c["concept_id"],
                video_id=video_id,
                concept_title=c.get("title", ""),
                segment_spans=concepts_meta_map.get(c["concept_id"], []),
            )
        for _,s in enumerate(segments):
            self.rag.add_doc(
                "segment",
                s["text"],
                s["concept_id"],
                video_id=video_id,
                segment_id=s.get("segment_id", ""),
                start_ms=s.get("start_ms", 0),
                end_ms=s.get("end_ms", 0),
            )

        return{
            "concepts": concepts,
            "segments": segments,
            "duration_ms": asr_result["duration_ms"]
        }

    def extract_concepts(self, sentences):
        indexed = [
            {"idx": i, "text": s["text"]}
            for i, s in enumerate(sentences)
        ]

        prompt = [
            {
                "role": "system",
                "content": """
                你是一个教学内容分析专家。
                
                请将句子划分为多个知识点，并提取知识点内容。
                
                【核心规则】
                1. 必须覆盖所有句子（从第0句到最后一句，不能遗漏任何一句），且不可以重复
                2. 不允许丢弃任何句子
                3. 如果某些句子（如故事、引入）不包含知识点：
                   → 必须合并到后面的知识点片段中
                   如果结尾有（例如互动提问等）不包括知识点的内容：
                   ->必须合并到前一个知识点片段中，不要作为一个单独知识点
                
                【分段要求】
                4. 每个片段最终必须包含一个知识点
                5. 每个句子必须属于某一个片段
                6. 至少分成2段
                7. 每段的句子之间不能重复！！
                
                【特殊规则】
                7. 总结句（如“总结一下”“你学会了吗”）必须单独成段
                8. 开头引入必须并入第一个知识点片段

                输出JSON：
                [
                  {
                    "title": "知识点名称",
                    "content": "知识点简要定义或总结",
                    "sentence_indices": [0,1,2]
                  }
                ]
                
                不要解释
                """
            },
            {
                "role": "user",
                "content": json.dumps(indexed, ensure_ascii=False)
            }
        ]

        result = self.llm_model.think(prompt)
        try:
            return json.loads(result)
        except Exception as e:
            raise e

    def build_output(self, sentences, concepts_raw):
        concepts = []
        segments = []

        for i, c in enumerate(concepts_raw):
            indices = sorted(set(c.get("sentence_indices", [])))
            if not indices:
                continue

            concept_id = gen_id("knowledge",c.get("title"))
            segment_text = "".join(sentences[idx]["text"] for idx in indices)
            segment_id = gen_id("seg", segment_text)

            concepts.append({
                "concept_id": concept_id,
                "title": c.get("title", ""),
                "content": c.get("content", ""),
            })
            # Store knowledge meta for context building (avoid "only kid" prompts).
            self.redis.set(f"knowpals:knowledge:{concept_id}", c.get("title", ""))
            self.redis.set(f"knowpals:knowledge_content:{concept_id}", c.get("content", ""))

            segments.append({
                "segment_id": segment_id,
                "concept_id": concept_id,
                "text": "".join(sentences[idx]["text"] for idx in indices),
                "start_ms": sentences[indices[0]]["start_ms"],
                "end_ms": sentences[indices[-1]]["end_ms"],
            })

        return concepts, segments


def gen_id(prefix:str,content:str) -> str:
    md5=hashlib.md5(content.encode("utf-8")).hexdigest()
    return f"{prefix}_{md5}"