"""文件职责：把 Agent 运行检查点持久化到 Redis，支持刷新恢复和失败续跑。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import orjson

from merchpilot.core.config import get_settings
from merchpilot.infrastructure.redis import get_redis


class RedisCheckpointStore:
    """`RedisCheckpointStore` 封装基础设施资源及其连接、错误和生命周期管理。"""
    def __init__(self) -> None:
        """初始化`RedisCheckpointStore`所需依赖和默认状态。"""
        self.settings = get_settings()
        self.redis = get_redis()

    def _latest_key(self, thread_id: str) -> str:
        """内部辅助函数`_latest_key`；拆分主流程并集中处理当前模块的边界条件。"""
        return f"{self.settings.redis_key_prefix}:checkpoint:{thread_id}:latest"

    def _version_key(self, thread_id: str) -> str:
        """内部辅助函数`_version_key`；拆分主流程并集中处理当前模块的边界条件。"""
        return f"{self.settings.redis_key_prefix}:checkpoint:{thread_id}:version"

    def _checkpoint_key(self, thread_id: str, version: int) -> str:
        """内部辅助函数`_checkpoint_key`；拆分主流程并集中处理当前模块的边界条件。"""
        return f"{self.settings.redis_key_prefix}:checkpoint:{thread_id}:{version}"

    async def save(self, thread_id: str, state: dict[str, Any]) -> str:
        """实现`save`基础设施操作；统一资源访问、异常和生命周期语义。"""
        version = int(await self.redis.incr(self._version_key(thread_id)))
        checkpoint_ref = self._checkpoint_key(thread_id, version)
        payload = {
            "thread_id": thread_id,
            "version": version,
            "saved_at": datetime.now(UTC).isoformat(),
            "state": state,
        }
        async with self.redis.pipeline(transaction=True) as pipe:
            ttl = self.settings.checkpoint_ttl_seconds
            pipe.set(checkpoint_ref, orjson.dumps(payload), ex=ttl)
            pipe.set(self._latest_key(thread_id), checkpoint_ref, ex=ttl)
            pipe.expire(self._version_key(thread_id), ttl)
            # 只保留最近若干版本，避免长时间运行导致 Redis 无限增长。
            if version > self.settings.checkpoint_history_limit:
                old_version = version - self.settings.checkpoint_history_limit
                pipe.delete(self._checkpoint_key(thread_id, old_version))
            await pipe.execute()
        return checkpoint_ref

    async def load_latest(self, thread_id: str) -> dict[str, Any] | None:
        """实现`load_latest`基础设施操作；统一资源访问、异常和生命周期语义。"""
        checkpoint_ref = await self.redis.get(self._latest_key(thread_id))
        if not checkpoint_ref:
            return None
        payload = await self.redis.get(checkpoint_ref)
        if not payload:
            return None
        decoded = orjson.loads(payload)
        if not isinstance(decoded, dict):
            raise RuntimeError("invalid checkpoint payload")
        return cast(dict[str, Any], decoded)
