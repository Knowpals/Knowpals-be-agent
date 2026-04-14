from __future__ import annotations

import json

from kafka.consumer import KafkaConsumer
from kafka.producer import KafkaProducer

from app.config.loader import AppConfig


def new_consumer(cfg: AppConfig) -> KafkaConsumer:
    """Build task-topic consumer (kafka-python uses bootstrap_servers, not a shared Java-style client)."""
    return KafkaConsumer(
        cfg.kafka.task_topic,
        bootstrap_servers=cfg.kafka.bootstrap_servers,
        group_id=cfg.kafka.group_id,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        enable_auto_commit=True,
    )


def new_producer(cfg: AppConfig) -> KafkaProducer:
    return KafkaProducer(
        bootstrap_servers=cfg.kafka.bootstrap_servers,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )
