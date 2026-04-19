"""进程内服务编排：gRPC、后续可扩展 HTTP 等。"""

from app.server.memory_servicer import MemoryGrpcServicer

__all__ = ["MemoryGrpcServicer"]
