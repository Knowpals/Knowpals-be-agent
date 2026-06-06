import os
from typing import Optional

from redis import Redis

from app.dispatch.dispatcher import StageDispatcher
from app.graph.graph_loader import KnowledgeGraph
from app.graph.subgraph_extractor import GraphNodeIndexer, SubgraphExtractor
from app.handler.knowledge_segment import KnowledgeSegmentStage
from app.handler.quiz import QuizStage
from app.model.asr import ASRModel
from app.model.llm import LLMModel
from app.rag.rag import RagService

_graph: Optional[KnowledgeGraph] = None
_matcher: Optional[SubgraphExtractor] = None


def _get_graph_matcher() -> Optional[SubgraphExtractor]:
    global _graph, _matcher
    if _matcher is not None:
        return _matcher

    graph_path = os.getenv("GRAPH_DATA_PATH", "app/graph_data.json")
    if not os.path.exists(graph_path):
        return None

    try:
        _graph = KnowledgeGraph(graph_path)
        _graph.load()
        _matcher = SubgraphExtractor(_graph)
    except Exception:
        _matcher = None
    return _matcher


def _ensure_graph_indexed(matcher: Optional[SubgraphExtractor], rag: RagService) -> None:
    """Index graph nodes into Milvus once — skip if already present."""
    if matcher is None:
        return

    # Wire up rag so the matching pipeline can use embedding search (step 5)
    matcher.rag = rag

    try:
        indexer = GraphNodeIndexer(matcher.graph, rag)
        result = indexer.ensure_indexed()
        if result.get("status") == "indexed":
            print(f"[graph] 图谱节点已索引: {result['count']} 个")
        else:
            print(f"[graph] 图谱节点已存在，跳过索引")
    except Exception as e:
        print(f"[graph] 图谱索引跳过（{e}）")


def build_default_dispatcher(
    asr_model: ASRModel,
    llm_model: LLMModel,
    redis: Redis,
    rag: RagService,
) -> StageDispatcher:
    matcher = _get_graph_matcher()
    _ensure_graph_indexed(matcher, rag)

    return StageDispatcher(
        {
            "knowledge": KnowledgeSegmentStage(
                asr_model, llm_model, redis, rag,
                graph_matcher=matcher,
            ),
            "quiz": QuizStage(llm_model, rag),
        }
    )
