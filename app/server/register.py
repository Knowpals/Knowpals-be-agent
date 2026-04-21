from concurrent import futures

import grpc

from app.config.loader import AppConfig


class GrpcServer:
    def __init__(self,cfg:AppConfig):
        self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        self.port=cfg.grpc.port


    def start(self):
        self.server.add_insecure_port(f"[::]:{self.port}")
        self.server.start()
        print(f"gRPC listening on [::]:{self.port}")