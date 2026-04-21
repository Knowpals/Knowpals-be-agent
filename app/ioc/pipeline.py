from __future__ import annotations

from kafka import KafkaConsumer, KafkaProducer

from app.cache.cache import EventCache
from app.dispatch.dispatcher import StageDispatcher
from app.worker.consumer import PipelineWorker
from app.worker.producer import ResultPublisher


def build_pipeline_worker(
        cache:EventCache,
        consumer:KafkaConsumer,
        publisher:ResultPublisher,
        dispatcher:StageDispatcher,
) -> PipelineWorker:

    return PipelineWorker(
        consumer_client=consumer,
        event_cache=cache,
        result_publisher=publisher,
        dispatcher=dispatcher,
    )
