from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.config.loader import load_config
from app.ioc.pipeline import build_pipeline_worker
from app.ioc.redis import new_redis_client
from app.memory.memory import MemoryTool
from app.model.llm import LLMModel
from app.server.memory_servicer import MemoryGrpcServicer


def main() -> None:
    cfg = load_config()

    redis_client = new_redis_client(cfg)
    llm_model = LLMModel(cfg)
    memory_tool = MemoryTool(redis_client, llm_model)

    MemoryGrpcServicer(memory_tool).start_server()
    build_pipeline_worker(cfg).run()


if __name__ == "__main__":
    main()
