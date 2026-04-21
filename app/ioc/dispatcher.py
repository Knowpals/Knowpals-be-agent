from redis import Redis

from app.dispatch.dispatcher import StageDispatcher
from app.handler.knowledge_segment import KnowledgeSegmentStage
from app.handler.quiz import QuizStage
from app.model.asr import ASRModel
from app.model.llm import LLMModel
from app.rag.rag import RagService


def build_default_dispatcher(asr_model:ASRModel,llm_model:LLMModel,redis:Redis,rag:RagService) -> StageDispatcher:
    return StageDispatcher(
        {
            "knowledge": KnowledgeSegmentStage(asr_model, llm_model,redis,rag),
            "quiz": QuizStage(llm_model,rag)
        }
    )
