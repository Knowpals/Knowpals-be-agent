from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.memory.memory import MemoryTool
from app.rag.rag import RagService


ToolFn = Callable[[dict[str, Any]], Any]


@dataclass
class Tool:
    name: str
    description: str
    schema: dict[str, Any]
    fn: ToolFn


class ToolRegistry:
    def __init__(self, *, memory: MemoryTool, rag: RagService) -> None:
        self.memory = memory
        self.rag = rag
        self._tools: dict[str, Tool] = {}
        self._register_defaults()

    def _register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def list(self) -> list[dict[str, Any]]:
        return [
            {"name": t.name, "description": t.description, "schema": t.schema}
            for t in self._tools.values()
        ]

    def call(self, *, name: str, args: dict[str, Any]) -> Any:
        if name not in self._tools:
            raise KeyError(f"unknown tool: {name}")
        return self._tools[name].fn(args)

    def _register_defaults(self) -> None:
        # Keep tool surface minimal. Read-only chat/memory is assembled by ContextBuilder.
        # RAG can be queried on-demand by the agent.
        self._register(
            Tool(
                name="rag.search",
                description="Search RAG docs by query and optional filters.",
                schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "doc_type": {"type": "string", "enum": ["segment", "knowledge", "question"]},
                        "limit": {"type": "integer"},
                        "knowledge_id": {"type": "string"},
                    },
                    "required": ["query", "doc_type", "limit"],
                },
                fn=lambda a: self.rag.search(a["query"], a.get("knowledge_id"), a["doc_type"], int(a["limit"])),
            )
        )
        self._register(
            Tool(
                name="memory.write",
                description="Write a behavior event to memory (video-scoped).",
                schema={
                    "type": "object",
                    "properties": {
                        "student_id": {"type": "string"},
                        "behavior": {"type": "object"},
                    },
                    "required": ["student_id", "behavior"],
                },
                fn=lambda a: self.memory.write(a["student_id"], a["behavior"]),
            )
        )

