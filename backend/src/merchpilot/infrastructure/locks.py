"""文件职责：提供跨 API、Worker 和容器实例的 Redis 分布式锁。"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

from redis.exceptions import RedisError

from merchpilot.core.config import get_settings
from merchpilot.infrastructure.redis import get_redis


class DistributedLockUnavailable(RuntimeError):
    """表示锁无法在限定时间内获取。"""


class DistributedLockBusy(RuntimeError):
    """表示锁已由另一个请求或任务持有。"""


_RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


class RedisDistributedLock:
    """使用唯一令牌安全释放的 Redis 锁，避免误删其他持有者的锁。"""

    def __init__(self, key: str, *, ttl_seconds: int, blocking_timeout: float = 0.5) -> None:
        self.key = key
        self.ttl_seconds = ttl_seconds
        self.blocking_timeout = blocking_timeout
        self.token = uuid.uuid4().hex
        self._held = False

    async def acquire(self) -> bool:
        """在阻塞超时内尝试获取锁。"""
        deadline = asyncio.get_running_loop().time() + self.blocking_timeout
        while True:
            try:
                acquired = await get_redis().set(
                    self.key,
                    self.token,
                    nx=True,
                    ex=self.ttl_seconds,
                )
            except (RedisError, RuntimeError) as exc:
                # redis-py async pools can also surface an event-loop binding error
                # when a cached client is reused across test/worker loops; treat it
                # as infrastructure unavailability so fail-open policy is honored.
                raise DistributedLockUnavailable("Redis lock service unavailable") from exc
            if acquired:
                self._held = True
                return True
            if asyncio.get_running_loop().time() >= deadline:
                return False
            await asyncio.sleep(0.05)

    async def release(self) -> None:
        """仅释放仍由当前持有者创建的锁。"""
        if not self._held:
            return
        try:
            redis_client = cast(Any, get_redis())
            await redis_client.eval(_RELEASE_SCRIPT, 1, self.key, self.token)
        except (RedisError, RuntimeError):
            pass
        finally:
            self._held = False


@asynccontextmanager
async def distributed_lock(
    key: str,
    *,
    ttl_seconds: int | None = None,
    blocking_timeout: float = 0.5,
) -> AsyncIterator[RedisDistributedLock]:
    """获取并自动释放分布式锁；获取失败时抛出明确异常。"""
    settings = get_settings()
    lock = RedisDistributedLock(
        key,
        ttl_seconds=ttl_seconds or settings.redis_lock_timeout_seconds,
        blocking_timeout=blocking_timeout,
    )
    if not await lock.acquire():
        raise DistributedLockBusy(f"lock busy: {key}")
    try:
        yield lock
    finally:
        await lock.release()
