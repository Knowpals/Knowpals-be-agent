from __future__ import annotations

from kafka.producer import KafkaProducer

from app.message.message import ResultMessage


class ResultPublisher:
    """Kafka result sink; receives an already-built producer (injected)."""

    def __init__(self, producer_client: KafkaProducer, result_topic: str) -> None:
        self.producer_client = producer_client
        self.result_topic = result_topic

    def send(self, msg: ResultMessage) -> None:
        self.producer_client.send(self.result_topic, value=msg.data)
        self.producer_client.flush()
