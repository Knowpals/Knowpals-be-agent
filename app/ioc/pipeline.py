"""
Composition root: construct the object graph in one place (similar to Go fx/wire main).

Callers (e.g. main) only depend on this module + AppConfig, not on low-level clients.
"""

from __future__ import annotations

from app.cache.cache import EventCache
from app.config.loader import AppConfig
from app.dispatch.dispatcher import StageDispatcher
from app.ioc.dispatcher import build_default_dispatcher

from app.ioc.kafka_clients import new_consumer, new_producer
from app.ioc.redis import new_redis_client
from app.worker.consumer import PipelineWorker
from app.worker.producer import ResultPublisher


def build_pipeline_worker(cfg: AppConfig) -> PipelineWorker:
    redis_client = new_redis_client(cfg)
    cache = EventCache(redis_client)
    consumer = new_consumer(cfg)
    producer = new_producer(cfg)
    publisher = ResultPublisher(producer, cfg.kafka.result_topic)
    dispatcher: StageDispatcher = build_default_dispatcher(cfg)
    return PipelineWorker(
        consumer_client=consumer,
        event_cache=cache,
        result_publisher=publisher,
        dispatcher=dispatcher,
    )
