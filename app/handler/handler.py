from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class StageHandler(ABC):
    @abstractmethod
    def run(self, payload: dict[str, Any]) -> Any:
        """Execute pipeline stage logic for the given payload."""
