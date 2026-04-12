from __future__ import annotations

from typing import Any, Mapping

from app.handler.handler import StageHandler

class StageDispatcher:
    def __init__(self, handlers: Mapping[int, StageHandler]) -> None:
        self._handlers = dict(handlers)

    def dispatch(self, stage: int, payload: dict[str, Any]) -> Any:
        handler = self._handlers.get(stage)
        if handler is None:
            raise ValueError(f"Unknown stage: {stage}")
        return handler.run(payload)



