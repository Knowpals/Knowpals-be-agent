from __future__ import annotations

import redis
from redis import Redis

from app.config.loader import AppConfig


def new_redis_client(cfg: AppConfig) -> Redis:
    return redis.Redis(
        host=cfg.redis.host,
        password=cfg.redis.password,
        port=cfg.redis.port,
        db=cfg.redis.db,
    )
