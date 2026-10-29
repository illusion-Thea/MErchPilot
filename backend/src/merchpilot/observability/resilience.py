"""文件职责：提供模型服务的舱壁、超时排队和熔断器。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import monotonic, perf_counter
from weakref import WeakKeyDictionary

from merchpilot.core.config import get_settings
from merchpilot.observability.metrics import (
    model_bulkhead_rejections_total,
    model_circuit_open_total,
    model_request_duration_seconds,
    model_requests_total,
)


class ModelServiceBusy(RuntimeError):
    """模型服务达到舱壁并发上限。"""


class ModelCircuitOpen(RuntimeError):
    """模型服务连续失败后进入熔断窗口。"""


@dataclass
class _GuardState:
    """绑定到当前事件循环的舱壁和熔断状态。"""

    semaphore: asyncio.Semaphore
    state_lock: asyncio.Lock
    failure_count: int = 0
    open_until: float = 0.0


class ModelServiceGuard:
    """单进程模型服务保护器；多副本场景由每个模型服务实例分别隔离资源。"""

    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self._states: WeakKeyDictionary[asyncio.AbstractEventLoop, _GuardState] = WeakKeyDictionary()

    def _state(self) -> _GuardState:
        """为当前事件循环惰性创建隔离状态，兼容 API 和 Celery 的多事件循环。"""
        loop = asyncio.get_running_loop()
        state = self._states.get(loop)
        if state is None:
            settings = get_settings()
            state = _GuardState(
                semaphore=asyncio.Semaphore(settings.model_service_max_concurrency),
                state_lock=asyncio.Lock(),
            )
            self._states[loop] = state
        return state

    async def _enter(self) -> None:
        settings = get_settings()
        state = self._state()
        async with state.state_lock:
            if monotonic() < state.open_until:
                model_circuit_open_total.labels(service=self.service_name).inc()
                raise ModelCircuitOpen(f"{self.service_name} circuit is open")
        try:
            await asyncio.wait_for(
                state.semaphore.acquire(),
                timeout=settings.model_service_queue_timeout_seconds,
            )
        except TimeoutError as exc:
            model_bulkhead_rejections_total.labels(service=self.service_name).inc()
            raise ModelServiceBusy(f"{self.service_name} is busy") from exc

    async def _leave(self, succeeded: bool) -> None:
        settings = get_settings()
        state = self._state()
        state.semaphore.release()
        async with state.state_lock:
            if succeeded:
                state.failure_count = 0
                state.open_until = 0.0
            else:
                state.failure_count += 1
                if state.failure_count >= settings.model_service_failure_threshold:
                    state.open_until = monotonic() + settings.model_service_circuit_open_seconds

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        """申请一次模型服务执行槽，并记录成功、失败和耗时。"""
        await self._enter()
        started = perf_counter()
        succeeded = False
        try:
            yield
            succeeded = True
            model_requests_total.labels(service=self.service_name, state="success").inc()
        except Exception:
            model_requests_total.labels(service=self.service_name, state="failure").inc()
            raise
        finally:
            model_request_duration_seconds.labels(service=self.service_name).observe(
                perf_counter() - started
            )
            await self._leave(succeeded)
