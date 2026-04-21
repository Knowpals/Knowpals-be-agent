from __future__ import annotations

import sys
from pathlib import Path

from app.cache.cache import EventCache
from app.ioc.dispatcher import build_default_dispatcher
from app.ioc.kafka_clients import new_consumer, new_producer
from app.ioc.milvus import new_milvus_collection
from app.model.asr import ASRModel
from app.model.embedding import EmbeddingModel
from app.rag.chunker import TextChunker
from app.rag.rag import RagService
from app.server.register import GrpcServer
from app.worker.producer import ResultPublisher

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.config.loader import load_config
from app.ioc.pipeline import build_pipeline_worker
from app.ioc.redis import new_redis_client
from app.memory.memory import MemoryTool
from app.model.llm import LLMModel
from app.server.memory_servicer import MemoryGrpcServicer
from app.server.agent_servicer import AgentGrpcServicer
from app.agent.orchestrator import LearningAgent


def main() -> None:
    cfg = load_config()

    redis_client = new_redis_client(cfg)
    llm_model = LLMModel(cfg)
    embedding_model = EmbeddingModel(cfg)
    asr_model = ASRModel(cfg)
    consumer=new_consumer(cfg)
    producer=new_producer(cfg)
    collection=new_milvus_collection(cfg)
    chunker=TextChunker()

    rag = RagService(collection,embedding_model,chunker)
    cache=EventCache(redis_client)
    publisher=ResultPublisher(producer,"result")
    dispatcher=build_default_dispatcher(asr_model,llm_model,redis_client,rag)
    memory_tool = MemoryTool(redis_client, llm_model)

    # start one grpc server for all services
    server = GrpcServer(cfg)
    memory_grpc_server=MemoryGrpcServicer(memory_tool)
    memory_grpc_server.register(server.server)

    agent = LearningAgent(memory=memory_tool, rag=rag, llm=llm_model)
    agent_grpc = AgentGrpcServicer(agent)
    agent_grpc.register(server.server)

    server.start()

    build_pipeline_worker(cache,consumer,publisher,dispatcher).run()


if __name__ == "__main__":
    main()
