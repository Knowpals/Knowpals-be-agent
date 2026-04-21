from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

_CONFIG_DIR = Path(__file__).resolve().parent
_DEFAULT_CONFIG = _CONFIG_DIR / "./config.yaml"


@dataclass
class KafkaConfig:
    bootstrap_servers: list[str]
    task_topic: str
    result_topic: str
    group_id: str


@dataclass
class RedisConfig:
    host: str
    port: int
    db: int
    password: str


@dataclass
class DashscopeConfig:
    base_http_api_url: str
    api_key: str


@dataclass
class OpenaiConfig:
    api_key: str
    base_url: str
    model: str
    timeout: int


@dataclass
class MilvusConfig:
    host: str
    port: str
    collection: str


@dataclass
class GrpcConfig:
    port: int


@dataclass
class AppConfig:
    kafka: KafkaConfig
    redis: RedisConfig
    dashscope: DashscopeConfig
    openai: OpenaiConfig
    milvus: MilvusConfig
    grpc: GrpcConfig


def load_config() -> AppConfig:
    env_path = os.getenv("CONFIG_PATH")

    if env_path:
        path = Path(env_path)
    else:
        path = _DEFAULT_CONFIG

    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    k, r, d, o, m, g = (
        data["kafka"],
        data["redis"],
        data["dashscope"],
        data["openai"],
        data["milvus"],
        data["grpc"],
    )
    return AppConfig(
        kafka=KafkaConfig(
            bootstrap_servers=k["bootstrap_servers"],
            task_topic=k["task_topic"],
            result_topic=k["result_topic"],
            group_id=str(k["group_id"]),
        ),
        redis=RedisConfig(**r),
        dashscope=DashscopeConfig(**d),
        openai=OpenaiConfig(**o),
        milvus=MilvusConfig(**m),
        grpc=GrpcConfig(**g),
    )
