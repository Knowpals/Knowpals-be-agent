from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional

from app.graph.graph_loader import KnowledgeGraph
from app.model.embedding import EmbeddingModel
from app.rag.rag import RagService

_DELIM = re.compile(r"[与和及、,，;；+＋&＆]")


class GraphNodeIndexer:
    """Index graph nodes into Milvus for semantic search.

    ``ensure_indexed()`` checks Milvus first and only embeds+inserts when the
    ``graph_node`` type is empty — safe to call on every startup.
    """

    def __init__(self, graph: KnowledgeGraph, rag: RagService):
        self.graph = graph
        self.rag = rag
        self.embedding = rag.embedding

    def ensure_indexed(self, batch_size: int = 50) -> Dict[str, Any]:
        """Index all graph nodes if not already present in Milvus."""
        if self._already_indexed():
            return {"status": "skipped", "reason": "already indexed"}

        return self._do_index_all(batch_size)

    def _already_indexed(self) -> bool:
        """Return True if at least one graph_node doc exists in Milvus."""
        try:
            results = self.rag.collection.query(
                expr='type == "graph_node"',
                output_fields=["knowledge_id"],
                limit=1,
            )
            return len(results) > 0
        except Exception:
            return False

    def _do_index_all(self, batch_size: int) -> Dict[str, Any]:
        """Batch-embed all graph nodes and insert via ``insert_docs``."""
        nodes = list(self.graph.nodes.values())
        indexed = 0

        for i in range(0, len(nodes), batch_size):
            batch = nodes[i : i + batch_size]
            texts = [
                f"{n.get('label', '')}: {n.get('description', '')}"
                for n in batch
            ]
            embeddings = self.embedding.encode_batch(texts)

            docs = []
            for n, emb in zip(batch, embeddings):
                docs.append({
                    "id": str(uuid.uuid4()),
                    "type": "graph_node",
                    "knowledge_id": n["node_id"],
                    "content": texts[len(docs)],
                    "embedding": emb,
                    "metadata": {
                        "node_label": n.get("label", ""),
                        "node_type": n.get("type", ""),
                        "domain": n.get("domain", ""),
                        "level": n.get("level", ""),
                    },
                })

            self.rag.insert_docs(docs)
            indexed += len(batch)

        return {"status": "indexed", "count": indexed, "total": len(nodes)}


class SubgraphExtractor:
    """Match video knowledge points to graph nodes and extract a subgraph.

    The matching pipeline (tried in order):
      1. Exact label match
      2. Alias match
      3. Fuzzy text match (label/description contains query)
      4. Token-split match (for compound titles like "欧拉法与梯形法")
      5. Embedding similarity search via Milvus (fallback)
    """

    def __init__(
        self,
        knowledge_graph: KnowledgeGraph,
        rag_service: Optional[RagService] = None,
    ):
        self.graph = knowledge_graph
        self.rag = rag_service

    def match_knowledge_to_nodes(
        self, title: str, content: str = "", top_k: int = 3
    ) -> List[Dict[str, Any]]:
        """Return ranked graph node matches for a video knowledge point."""
        # 1) Exact label
        nid = self.graph.find_by_label(title)
        if nid:
            return [
                {
                    "node_id": nid,
                    "score": 1.0,
                    "method": "exact",
                    "node": self.graph.get_node(nid),
                }
            ]

        # 2) Alias
        nid = self.graph.find_by_alias(title)
        if nid:
            return [
                {
                    "node_id": nid,
                    "score": 0.95,
                    "method": "alias",
                    "node": self.graph.get_node(nid),
                }
            ]

        # 3) Fuzzy text
        fuzzy = self.graph.search_by_text(title)
        if fuzzy and fuzzy[0][1] >= 0.8:
            nid = fuzzy[0][0]
            return [
                {
                    "node_id": nid,
                    "score": fuzzy[0][1],
                    "method": "fuzzy",
                    "node": self.graph.get_node(nid),
                }
            ]

        # 4) Token-split: compound titles like "欧拉法与梯形法"
        tokens = [t.strip() for t in _DELIM.split(title) if t.strip()]
        if len(tokens) >= 2:
            token_matches: list[tuple[str, float]] = []
            for tok in tokens:
                nid = self.graph.find_by_label(tok)
                if nid:
                    token_matches.append((nid, 1.0))
                    continue
                nid = self.graph.find_by_alias(tok)
                if nid:
                    token_matches.append((nid, 0.95))
                    continue
                f = self.graph.search_by_text(tok)
                if f:
                    token_matches.append((f[0][0], f[0][1]))
            if token_matches:
                # Deduplicate and return best per token, aggregated by node
                by_node: dict[str, list[float]] = {}
                for nid, sc in token_matches:
                    by_node.setdefault(nid, []).append(sc)
                result = []
                for nid, scores in by_node.items():
                    result.append(
                        {
                            "node_id": nid,
                            "score": sum(scores) / len(scores),
                            "method": "token_split",
                            "node": self.graph.get_node(nid),
                        }
                    )
                result.sort(key=lambda x: -x["score"])
                return result[:top_k]

        # 5) Embedding search via Milvus
        if self.rag:
            try:
                query_text = f"{title} {content}" if content else title
                results = self.rag.search(
                    query=query_text, doc_type="graph_node", top_k=top_k
                )
                matches = []
                for r in results:
                    node = self.graph.get_node(r["knowledge_id"])
                    if node:
                        matches.append(
                            {
                                "node_id": r["knowledge_id"],
                                "score": r["score"],
                                "method": "embedding",
                                "node": node,
                            }
                        )
                if matches:
                    return matches
            except Exception:
                pass

        # 6) Fallback to plain fuzzy
        return [
            {
                "node_id": nid,
                "score": s,
                "method": "fuzzy",
                "node": self.graph.get_node(nid),
            }
            for nid, s in fuzzy[:top_k]
        ] if fuzzy else []

    def extract_for_video(
        self,
        knowledge_points: List[Dict[str, str]],
        max_hops: int = 2,
        top_k_per_point: int = 2,
        node_types: Optional[set[str]] = None,
        relations: Optional[set[str]] = None,
    ) -> Dict[str, Any]:
        """Build a subgraph around the video's matched knowledge points.

        *knowledge_points*: ``[{"knowledge_id": …, "title": …, "content": …}]``
          typically loaded from Redis (``knowpals:knowledge:{kid}``).
        """
        seed_ids: list[str] = []
        match_details: list[dict[str, Any]] = []

        for kp in knowledge_points:
            title = kp.get("title", "")
            content = kp.get("content", "")
            matches = self.match_knowledge_to_nodes(title, content, top_k_per_point)
            for m in matches:
                seed_ids.append(m["node_id"])
                match_details.append(
                    {
                        "knowledge_title": title,
                        "graph_node_id": m["node_id"],
                        "score": m["score"],
                        "method": m["method"],
                    }
                )

        seed_ids = list(dict.fromkeys(seed_ids))  # deduplicate, preserve order

        subgraph = self.graph.extract_subgraph(
            seed_ids, max_hops=max_hops, node_types=node_types, relations=relations
        )
        subgraph["match_details"] = match_details
        return subgraph
