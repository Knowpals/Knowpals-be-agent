from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

_CONFIG_DIR = Path(__file__).resolve().parent
_DEFAULT_CONFIG = _CONFIG_DIR / "config.yaml"


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
class AppConfig:
    kafka: KafkaConfig
    redis: RedisConfig
    dashscope: DashscopeConfig
    openai: OpenaiConfig


def load_config(config_path: str | Path | None = None) -> AppConfig:
    path = Path(config_path) if config_path is not None else _DEFAULT_CONFIG
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    k, r, d ,o= data["kafka"], data["redis"], data["dashscope"],data["openai"]
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
    )

