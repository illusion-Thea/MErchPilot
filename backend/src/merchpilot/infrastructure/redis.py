"""文件职责：管理 Redis 客户端、运行快照和缓存连接生命周期。"""

from __future__ import annotations

from functools import lru_cache
from typing import cast

from redis.asyncio import Redis

from merchpilot.core.config import get_settings


@lru_cache(maxsize=1)
def get_redis() -> Redis:
    """实现`get_redis`基础设施操作；统一资源访问、异常和生命周期语义。"""
    return cast(Redis, Redis.from_url(get_settings().redis_url, decode_responses=True))
