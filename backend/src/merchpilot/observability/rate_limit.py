"""文件职责：通过 Redis 原子计数实现跨 API 进程和容器的限流。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, cast

from redis.exceptions import RedisError

from merchpilot.core.config import get_settings
from merchpilot.infrastructure.redis import get_redis
from merchpilot.observability.metrics import rate_limit_rejections_total


class RateLimitExceeded(RuntimeError):
    """表示当前身份在时间窗口内超过请求额度。"""

    def __init__(self, retry_after: int, scope: str) -> None:
        self.retry_after = max(1, retry_after)
        self.scope = scope
        super().__init__("rate limit exceeded")


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    """保存一次限流检查的计数和剩余额度。"""

    allowed: bool
    remaining: int
    retry_after: int


_INCREMENT_SCRIPT = """
local user_current = redis.call('INCR', KEYS[1])
if user_current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local tenant_current = redis.call('INCR', KEYS[2])
if tenant_current == 1 then
  redis.call('EXPIRE', KEYS[2], ARGV[1])
end
local user_ttl = redis.call('TTL', KEYS[1])
local tenant_ttl = redis.call('TTL', KEYS[2])
return {user_current, user_ttl, tenant_current, tenant_ttl}
"""


async def check_rate_limit(*, tenant_id: str, user_id: str, scope: str = "api") -> RateLimitResult:
    """按租户和用户执行 Redis 原子窗口计数；Redis 故障时遵循 fail-open 配置。"""
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return RateLimitResult(True, settings.rate_limit_requests, settings.rate_limit_window_seconds)
    user_key = (
        f"{settings.redis_key_prefix}:ratelimit:{scope}:"
        f"{tenant_id}:{user_id}:{settings.rate_limit_window_seconds}"
    )
    tenant_key = (
        f"{settings.redis_key_prefix}:ratelimit:{scope}:tenant:"
        f"{tenant_id}:{settings.rate_limit_window_seconds}"
    )
    try:
        redis_client = cast(Any, get_redis())
        async with asyncio.timeout(0.25):
            user_current, user_ttl, tenant_current, tenant_ttl = await redis_client.eval(
                _INCREMENT_SCRIPT,
                2,
                user_key,
                tenant_key,
                str(settings.rate_limit_window_seconds),
            )
    except (RedisError, TimeoutError):
        if settings.rate_limit_fail_open:
            return RateLimitResult(True, settings.rate_limit_requests, settings.rate_limit_window_seconds)
        raise
    user_value = int(user_current)
    tenant_value = int(tenant_current)
    if user_value > settings.rate_limit_requests:
        rate_limit_rejections_total.labels(scope="user").inc()
        raise RateLimitExceeded(int(user_ttl), "user")
    if tenant_value > settings.rate_limit_tenant_requests:
        rate_limit_rejections_total.labels(scope="tenant").inc()
        raise RateLimitExceeded(int(tenant_ttl), "tenant")
    return RateLimitResult(
        True,
        min(
            settings.rate_limit_requests - user_value,
            settings.rate_limit_tenant_requests - tenant_value,
        ),
        max(1, min(int(user_ttl), int(tenant_ttl))),
    )
