from app.config.loader import AppConfig
from app.dispatch.dispatcher import StageDispatcher
from app.handler.knowledge_segment import KnowledgeSegmentStage
from app.handler.quiz import QuizStage
from app.model.asr import ASRModel
from app.model.llm import LLMModel


def build_default_dispatcher(config: AppConfig) -> StageDispatcher:
    asr_model = ASRModel(config)
    llm_model = LLMModel(config)
    return StageDispatcher(
        {
            1: KnowledgeSegmentStage(asr_model, llm_model),
            2: QuizStage(llm_model)
        }
    )
