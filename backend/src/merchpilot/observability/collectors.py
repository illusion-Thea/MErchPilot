"""文件职责：在 Prometheus 抓取前刷新 Redis 队列和 Celery Worker 指标。"""

from __future__ import annotations

import asyncio

from redis.asyncio import Redis

from merchpilot.core.config import get_settings
from merchpilot.infrastructure.celery_app import celery_app
from merchpilot.observability.metrics import celery_queue_depth, celery_workers

MONITORED_QUEUES = (
    "planning.high",
    "planning.normal",
    "planning.low",
    "agent.research",
    "agent.concept",
    "agent.supplier",
    "agent.finance",
    "agent.scoring",
    "agent.review",
    "index.parse",
    "index.embedding",
    "index.milvus",
    "report.generate",
    "notification.send",
    "maintenance",
)


def _worker_count() -> int:
    """返回当前可响应 Celery ping 的 Worker 数量。"""
    try:
        return len(celery_app.control.inspect(timeout=0.5).ping() or {})
    except Exception:
        return 0


async def refresh_runtime_metrics() -> None:
    """以短超时刷新队列长度和在线 Worker 数，监控失败不影响业务接口。"""
    settings = get_settings()
    redis = Redis.from_url(settings.celery_broker_url, decode_responses=True)
    try:
        async with asyncio.timeout(0.5):
            lengths = await asyncio.gather(*(redis.llen(queue) for queue in MONITORED_QUEUES))
        for queue, length in zip(MONITORED_QUEUES, lengths, strict=True):
            celery_queue_depth.labels(queue=queue).set(int(length))
    except Exception:
        pass
    finally:
        await redis.aclose()
    celery_workers.set(await asyncio.to_thread(_worker_count))
