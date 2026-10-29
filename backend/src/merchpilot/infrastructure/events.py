"""文件职责：发布与读取 Agent 运行事件，支撑 WebSocket 实时进度和历史恢复。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import orjson

from merchpilot.core.config import get_settings
from merchpilot.infrastructure.redis import get_redis


def run_event_stream(run_id: str) -> str:
    """实现`run_event_stream`基础设施操作；统一资源访问、异常和生命周期语义。"""
    settings = get_settings()
    return f"{settings.redis_key_prefix}:run:{run_id}:events"


async def publish_run_event(run_id: str, event_type: str, payload: dict[str, Any]) -> str:
    """实现`publish_run_event`基础设施操作；统一资源访问、异常和生命周期语义。"""
    redis = get_redis()
    event_id = await redis.xadd(
        run_event_stream(run_id),
        {
            "event_type": event_type,
            "payload": orjson.dumps(payload).decode("utf-8"),
            "occurred_at": datetime.now(UTC).isoformat(),
        },
        maxlen=get_settings().run_event_stream_maxlen,
        approximate=True,
    )
    return str(event_id)


def decode_run_event(event_id: str, event: dict[str, Any]) -> dict[str, Any]:
    """实现`decode_run_event`基础设施操作；统一资源访问、异常和生命周期语义。"""
    raw_payload = event.get("payload", "{}")
    try:
        payload = orjson.loads(raw_payload)
    except (orjson.JSONDecodeError, TypeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return {
        "event_id": event_id,
        "event_type": str(event.get("event_type") or "unknown"),
        "occurred_at": event.get("occurred_at"),
        "payload": payload,
    }


async def list_run_events(run_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
    """实现`list_run_events`基础设施操作；统一资源访问、异常和生命周期语义。"""
    redis = get_redis()
    rows = await redis.xrevrange(
        run_event_stream(run_id),
        max="+",
        min="-",
        count=limit,
    )
    return [
        decode_run_event(str(event_id), event)
        for event_id, event in reversed(rows)
    ]


async def run_event_gap(run_id: str, last_event_id: str) -> bool:
    """判断客户端断点是否早于 Redis Stream 当前保留的最早事件。"""
    redis = get_redis()
    first = await redis.xrange(run_event_stream(run_id), min="-", max="+", count=1)
    if not first or last_event_id in {"0-0", ""}:
        return False
    first_id = str(first[0][0])

    def event_key(value: str) -> tuple[int, int]:
        """按 Redis Stream 的毫秒时间和序号比较 ID，避免字符串排序误判。"""
        try:
            timestamp, sequence = value.split("-", 1)
            return int(timestamp), int(sequence)
        except (ValueError, AttributeError):
            return 0, 0

    return event_key(last_event_id) < event_key(first_id)
