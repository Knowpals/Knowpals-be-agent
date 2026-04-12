from __future__ import annotations

from kafka import KafkaConsumer

from app.cache.cache import EventCache
from app.dispatch.dispatcher import StageDispatcher
from app.message.message import ResultMessage, TaskMessage
from app.worker.producer import ResultPublisher


class PipelineWorker:

    def __init__(
        self,
        *,
        consumer_client: KafkaConsumer,
        event_cache: EventCache,
        result_publisher: ResultPublisher,
        dispatcher: StageDispatcher,
    ) -> None:
        self.consumer_client = consumer_client
        self.event_cache = event_cache
        self.result_publisher = result_publisher
        self.dispatcher = dispatcher

    def run(self) -> None:
        for msg in self.consumer_client:
            task = TaskMessage(msg.value)

            if self.event_cache.is_done(task.job_id, task.stage):
                continue

            try:
                result = self.dispatcher.dispatch(task.stage, task.payload)
                self.result_publisher.send(
                    ResultMessage(
                        job_id=task.job_id,
                        stage=task.stage,
                        status="success",
                        result=result,
                    )
                )
                self.event_cache.mark_done(task.job_id, task.stage)
            except Exception as e:
                self.result_publisher.send(
                    ResultMessage(
                        job_id=task.job_id,
                        stage=task.stage,
                        status="failed",
                        error=str(e),
                    )
                )
