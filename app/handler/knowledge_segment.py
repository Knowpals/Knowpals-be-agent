import json
import hashlib
from typing import Any, List, Optional

from redis import Redis

from app.graph.subgraph_extractor import SubgraphExtractor
from app.handler.handler import StageHandler
from app.model.asr import ASRModel
from app.model.llm import LLMModel
from app.rag.rag import RagService

# 图谱节点类型中适合作为知识概念的集合
_KNOWLEDGE_NODE_TYPES = frozenset({
    "Subject", "Module", "Topic", "Concept",
    "Algorithm", "Formula", "Theorem", "Prerequisite",
    "Experiment",
})


class KnowledgeSegmentStage(StageHandler):
    def __init__(
        self,
        asr_model: ASRModel,
        llm_model: LLMModel,
        redis: Redis,
        rag: RagService,
        graph_matcher: Optional[SubgraphExtractor] = None,
    ):
        self.asr_model = asr_model
        self.llm_model = llm_model
        self.redis = redis
        self.rag = rag
        self.graph_matcher = graph_matcher

    def run(self, payload: dict[str, Any]) -> Any:
        # 1) ASR
        asr_result = self.asr_model.transcribe(payload)
        sentences = asr_result["sentences"]
        if not sentences:
            return {"concepts": [], "segments": [], "subgraph": {"nodes": [], "edges": [], "metadata": {"node_count": 0, "edge_count": 0, "seed_ids": []}}, "duration_ms": 0}

        video_id = str(payload.get("video_id", "") or "")

        # 2) LLM 为句子分段，得到 (title, content, sentence_indices)
        concepts_raw = self._segment_sentences(sentences)

        # 3) 将每段匹配到大图谱，构建 concepts + segments
        concepts, segments = self._build_from_graph(sentences, concepts_raw, video_id)

        # 4) 存入 RAG + Redis
        self._store_to_rag(concepts, segments, video_id)

        # 5) 从大图谱中提取关联的小子图
        subgraph = self._build_subgraph(concepts)

        return {
            "concepts": concepts,
            "segments": segments,
            "subgraph": subgraph,
            "duration_ms": asr_result["duration_ms"],
        }

    # ── step 2: LLM 句子分段 ───────────────────────────────────

    def _segment_sentences(self, sentences: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Use LLM to group sentences into segments, returning topic titles."""
        indexed = [
            {"idx": i, "text": s["text"]}
            for i, s in enumerate(sentences)
        ]

        prompt = [
            {
                "role": "system",
                "content": """
                你是一个教学内容分析专家。

                请将句子划分为多个知识片段，并提取每个片段的关键主题词。

                【核心规则】
                1. 必须覆盖所有句子（从第0句到最后一句，不能遗漏任何一句）
                2. 不允许丢弃任何句子
                3. 如果某些句子（如故事、引入）不包含知识点：
                   → 必须合并到后面的知识点片段中
                   如果结尾有（例如互动提问等）不包括知识点的内容：
                   ->必须合并到前一个知识点片段中

                【分段要求】
                4. 每个片段最终必须包含一个知识点
                5. 每个句子必须属于某一个片段
                6. 至少分成2段
                7. 每段的句子之间不能重复

                【特殊规则】
                8. 总结句（如"总结一下""你学会了吗"）必须单独成段
                9. 开头引入必须并入第一个知识点片段

                输出JSON：
                [
                  {
                    "title": "该片段的核心知识点名称（简洁，2-8字）",
                    "content": "该知识点的简要定义或总结（10-30字）",
                    "sentence_indices": [0,1,2]
                  }
                ]

                不要解释
                """,
            },
            {
                "role": "user",
                "content": json.dumps(indexed, ensure_ascii=False),
            },
        ]

        result = self.llm_model.think(prompt)
        try:
            return json.loads(result)
        except Exception as e:
            raise e

    # ── step 3: 匹配图谱 + 构建输出 ────────────────────────────

    def _build_from_graph(
        self,
        sentences: list[dict[str, Any]],
        concepts_raw: list[dict[str, Any]],
        video_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        concepts: list[dict[str, Any]] = []
        segments: list[dict[str, Any]] = []
        used_titles: set[str] = set()

        for c in concepts_raw:
            indices = sorted(set(c.get("sentence_indices", [])))
            if not indices:
                continue

            title = c.get("title", "").strip()
            if not title:
                continue

            # 匹配图谱节点
            graph_node_id, graph_label, graph_content = self._resolve_graph_node(title)

            # 去重：相同 graph 节点或极相似标题只保留一个
            dedup_key = graph_node_id or title[:5]
            if dedup_key in used_titles:
                if segments:
                    last_seg = segments[-1]
                    last_seg["text"] += "".join(sentences[idx]["text"] for idx in indices)
                    last_seg["end_ms"] = sentences[indices[-1]]["end_ms"]
                continue
            used_titles.add(dedup_key)

            concept_id = graph_node_id or gen_id("knowledge", title)

            segment_text = "".join(sentences[idx]["text"] for idx in indices)
            segment_id = gen_id("seg", segment_text)

            concepts.append({
                "concept_id": concept_id,
                "title": graph_label or title,
                "content": graph_content or c.get("content", "") or segment_text[:200],
                "graph_node_id": graph_node_id or "",
            })
            self.redis.set(f"knowpals:knowledge:{concept_id}", graph_label or title)
            self.redis.set(f"knowpals:knowledge_content:{concept_id}", graph_content or c.get("content", ""))

            segments.append({
                "segment_id": segment_id,
                "concept_id": concept_id,
                "text": segment_text,
                "start_ms": sentences[indices[0]]["start_ms"],
                "end_ms": sentences[indices[-1]]["end_ms"],
            })

        return concepts, segments

    def _resolve_graph_node(self, title: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """Match a segment title to a knowledge-graph node.

        Returns (node_id, label, description) or (None, None, None).
        Only accepts node types in ``_KNOWLEDGE_NODE_TYPES`` (Topic, Concept, etc.)
        to avoid matching generic titles to Resource or Question nodes.
        """
        if not self.graph_matcher:
            return None, None, None

        matches = self.graph_matcher.match_knowledge_to_nodes(title, top_k=5)
        for m in matches:
            if m["score"] < 0.4:
                break
            node = m.get("node") or {}
            if node.get("type") in _KNOWLEDGE_NODE_TYPES:
                return (
                    m["node_id"],
                    node.get("label"),
                    node.get("description"),
                )
        return None, None, None

    def _build_subgraph(self, concepts: list[dict[str, Any]]) -> dict[str, Any]:
        """Extract a small subgraph from the knowledge graph around matched nodes."""
        if not self.graph_matcher:
            return {"nodes": [], "edges": [], "metadata": {"node_count": 0, "edge_count": 0, "seed_ids": []}}

        seed_ids = [
            c["graph_node_id"]
            for c in concepts
            if c.get("graph_node_id")
        ]
        if not seed_ids:
            return {"nodes": [], "edges": [], "metadata": {"node_count": 0, "edge_count": 0, "seed_ids": []}}

        try:
            return self.graph_matcher.graph.extract_subgraph(seed_ids, max_hops=1)
        except Exception:
            return {"nodes": [], "edges": [], "metadata": {"node_count": 0, "edge_count": 0, "seed_ids": seed_ids}}

    # ── step 4: 持久化 ─────────────────────────────────────────

    def _store_to_rag(
        self,
        concepts: list[dict[str, Any]],
        segments: list[dict[str, Any]],
        video_id: str,
    ) -> None:
        concepts_meta_map: dict[str, list[dict[str, Any]]] = {}
        for s in segments:
            concepts_meta_map.setdefault(s["concept_id"], []).append({
                "segment_id": s["segment_id"],
                "start_ms": s["start_ms"],
                "end_ms": s["end_ms"],
            })

        for c in concepts:
            content = (c.get("content") or "").strip()
            if not content:
                continue
            self.rag.add_doc(
                "knowledge",
                content,
                c["concept_id"],
                video_id=video_id,
                concept_title=c.get("title", ""),
                graph_node_id=c.get("graph_node_id", ""),
                segment_spans=concepts_meta_map.get(c["concept_id"], []),
            )
        for s in segments:
            self.rag.add_doc(
                "segment",
                s["text"],
                s["concept_id"],
                video_id=video_id,
                segment_id=s.get("segment_id", ""),
                start_ms=s.get("start_ms", 0),
                end_ms=s.get("end_ms", 0),
            )


def gen_id(prefix: str, content: str) -> str:
    md5 = hashlib.md5(content.encode("utf-8")).hexdigest()
    return f"{prefix}_{md5}"