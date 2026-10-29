"""验证限流、分布式锁和模型服务隔离等并发控制。"""

import asyncio

import pytest

import merchpilot.infrastructure.locks as locks_module
import merchpilot.observability.rate_limit as rate_limit_module
import merchpilot.observability.resilience as resilience_module
from merchpilot.infrastructure.locks import DistributedLockBusy, distributed_lock
from merchpilot.observability.rate_limit import RateLimitExceeded, check_rate_limit
from merchpilot.observability.resilience import ModelCircuitOpen, ModelServiceBusy, ModelServiceGuard


class FakeRateLimitSettings:
    rate_limit_enabled = True
    rate_limit_requests = 2
    rate_limit_tenant_requests = 10
    rate_limit_window_seconds = 60
    rate_limit_fail_open = False
    redis_key_prefix = "test"


class FakeRateLimitRedis:
    def __init__(self, result: list[int]) -> None:
        self.result = result

    async def eval(self, *args: object) -> list[int]:
        del args
        return self.result


class FakeLockSettings:
    redis_lock_timeout_seconds = 30


class FakeLockRedis:
    def __init__(self, acquired: bool) -> None:
        self.acquired = acquired
        self.released = False

    async def set(self, *args: object, **kwargs: object) -> bool:
        del args, kwargs
        return self.acquired

    async def eval(self, *args: object) -> int:
        del args
        self.released = True
        return 1


class FakeGuardSettings:
    model_service_max_concurrency = 1
    model_service_queue_timeout_seconds = 0.01
    model_service_failure_threshold = 2
    model_service_circuit_open_seconds = 0.2


@pytest.mark.asyncio
async def test_rate_limit_rejects_user_when_window_is_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    """用户超过窗口额度时返回可重试的限流异常。"""
    monkeypatch.setattr(rate_limit_module, "get_settings", lambda: FakeRateLimitSettings())
    monkeypatch.setattr(
        rate_limit_module,
        "get_redis",
        lambda: FakeRateLimitRedis([3, 41, 1, 41]),
    )

    with pytest.raises(RateLimitExceeded) as error:
        await check_rate_limit(tenant_id="tenant", user_id="user")

    assert error.value.scope == "user"
    assert error.value.retry_after == 41


@pytest.mark.asyncio
async def test_distributed_lock_releases_only_after_successful_acquire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """锁竞争失败不会误执行释放，成功持有后会释放令牌。"""
    monkeypatch.setattr(locks_module, "get_settings", lambda: FakeLockSettings())
    redis = FakeLockRedis(acquired=True)
    monkeypatch.setattr(locks_module, "get_redis", lambda: redis)

    async with distributed_lock("test:lock"):
        assert not redis.released
    assert redis.released

    busy_redis = FakeLockRedis(acquired=False)
    monkeypatch.setattr(locks_module, "get_redis", lambda: busy_redis)
    with pytest.raises(DistributedLockBusy):
        async with distributed_lock("test:busy", blocking_timeout=0):
            raise AssertionError("busy lock must not enter context")
    assert not busy_redis.released


@pytest.mark.asyncio
async def test_model_guard_isolates_bulkhead_and_opens_circuit(monkeypatch: pytest.MonkeyPatch) -> None:
    """并发超限快速失败，连续执行失败后进入熔断窗口。"""
    monkeypatch.setattr(resilience_module, "get_settings", lambda: FakeGuardSettings())
    guard = ModelServiceGuard("test")

    async def hold_slot() -> None:
        async with guard.slot():
            await asyncio.sleep(0.05)

    first = asyncio.create_task(hold_slot())
    await asyncio.sleep(0)
    with pytest.raises(ModelServiceBusy):
        async with guard.slot():
            pass
    await first

    for _ in range(2):
        with pytest.raises(RuntimeError):
            async with guard.slot():
                raise RuntimeError("model failure")
    with pytest.raises(ModelCircuitOpen):
        async with guard.slot():
            pass
