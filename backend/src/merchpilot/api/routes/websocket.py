"""文件职责：通过 WebSocket 推送 Agent 增量事件，并支持断线后状态续接。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from merchpilot.api.dependencies import authenticate_credential
from merchpilot.core.config import get_settings
from merchpilot.infrastructure.database import async_session_factory
from merchpilot.infrastructure.events import decode_run_event, run_event_gap, run_event_stream
from merchpilot.infrastructure.models import PlanningProject, PlanningRun
from merchpilot.infrastructure.redis import get_redis

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/runs/{run_id}")
async def run_events(websocket: WebSocket, run_id: str) -> None:
    """实现`run_events`接口辅助流程，供当前路由复用权限与状态判断。"""
    settings = get_settings()
    redis = get_redis()
    try:
        identity = await authenticate_credential(websocket.query_params.get("access_token", ""))
    except Exception:
        await websocket.close(code=4401, reason="unauthorized")
        return
    async with async_session_factory() as session:
        permitted_run = await session.scalar(
            select(PlanningRun.id)
            .join(PlanningProject, PlanningProject.id == PlanningRun.project_id)
            .where(
                PlanningRun.id == run_id,
                PlanningProject.tenant_id == identity.tenant_id,
            )
        )
    if permitted_run is None:
        await websocket.close(code=4404, reason="planning run not found")
        return
    await websocket.accept()
    await websocket.send_json({"event_type": "connection.ready", "run_id": run_id})
    last_event_id = websocket.query_params.get("last_event_id", "0-0")
    try:
        if await run_event_gap(run_id, last_event_id):
            await websocket.send_json(
                {
                    "event_type": "events.gap",
                    "run_id": run_id,
                    "reason": "requested event history is no longer retained; reload the run snapshot",
                }
            )
            last_event_id = "$"
        while True:
            rows = await redis.xread(
                {run_event_stream(run_id): last_event_id},
                block=settings.websocket_stream_block_ms,
                count=50,
            )
            if not rows:
                await websocket.send_json({"event_type": "heartbeat", "run_id": run_id})
                continue
            for _, events in rows:
                for event_id, event in events:
                    last_event_id = event_id
                    await websocket.send_json(decode_run_event(event_id, event))
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
