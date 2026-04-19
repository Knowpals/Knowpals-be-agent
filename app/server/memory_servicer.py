from __future__ import annotations

import os
from concurrent import futures
from typing import Any

import grpc

from app.grpc.gen import memory_pb2
from app.grpc.gen import memory_pb2_grpc
from app.memory.memory import MemoryTool


class MemoryGrpcServicer(memory_pb2_grpc.MemoryServiceServicer):
    """memory.MemoryService：Go 只调用 Write；长期记忆在 MemoryTool.write 内部触发。"""

    def __init__(self, memory: MemoryTool) -> None:
        self._memory = memory

    def _event_to_behavior(self, pb_event: memory_pb2.Event) -> tuple[str, dict[str, Any]]:
        student_id = (pb_event.student_id or "").strip()
        knowledge_id = (pb_event.knowledge_id or "").strip()
        if not student_id or not knowledge_id:
            raise ValueError("student_id and knowledge_id are required")

        kt = pb_event.event_type
        behavior: dict[str, Any] = {
            "knowledge_id": knowledge_id,
            "video_id": pb_event.video_id or "",
            "segment_id": pb_event.segment_id or "",
        }

        if kt == memory_pb2.EventType.QUESTION:
            if pb_event.WhichOneof("detail") != "question":
                raise ValueError("QUESTION event must carry question detail")
            q = pb_event.question
            behavior["type"] = "question"
            behavior["question_id"] = q.question_id
            behavior["is_correct"] = q.is_correct
            behavior["content"] = q.content
            behavior["user_answer"] = q.user_answer
            behavior["right_answer"] = q.right_answer
        elif kt == memory_pb2.EventType.PAUSE:
            behavior["type"] = "pause"
        elif kt == memory_pb2.EventType.REPLAY:
            behavior["type"] = "replay"
        elif kt == memory_pb2.EventType.CHAT:
            if pb_event.WhichOneof("detail") != "chat":
                raise ValueError("CHAT event must carry chat detail")
            c = pb_event.chat
            behavior["type"] = "chat"
            behavior["text"] = c.text or ""
            behavior["intent"] = c.intent or ""
        else:
            raise ValueError(f"unsupported event_type: {kt}")

        return student_id, behavior

    def Write(self, request: memory_pb2.WriteRequest, context: grpc.ServicerContext):
        try:
            sid, behavior = self._event_to_behavior(request.event)
            self._memory.write(sid, behavior)
            return memory_pb2.WriteResponse(success=True)
        except ValueError as e:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        except Exception as e:
            context.abort(grpc.StatusCode.INTERNAL, str(e))

    def create_server(self) -> grpc.Server:
        """创建并注册 MemoryService，尚未 start。"""
        workers = int(os.getenv("GRPC_WORKERS", "16"))
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=workers))
        memory_pb2_grpc.add_MemoryServiceServicer_to_server(self, server)
        port = int(os.getenv("GRPC_PORT", "50051"))
        listen = f"[::]:{port}"
        server.add_insecure_port(listen)
        return server

    def start_server(self) -> grpc.Server:
        """启动 gRPC（非阻塞）：适合与 Kafka worker 同进程运行。"""
        server = self.create_server()
        server.start()
        port = int(os.getenv("GRPC_PORT", "50051"))
        print(f"gRPC MemoryService listening on [::]:{port}")
        return server
