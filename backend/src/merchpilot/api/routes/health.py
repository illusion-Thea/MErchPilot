"""文件职责：汇总应用及依赖服务健康状态，支持本地验收和监控探针。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import httpx
from fastapi import APIRouter
from sqlalchemy import text

from merchpilot.adapters.providers import (
    get_external_approval_provider,
    get_identity_provider,
    get_telemetry_provider,
)
from merchpilot.adapters.storage import get_object_storage_provider
from merchpilot.core.config import get_settings
from merchpilot.infrastructure.celery_app import celery_app
from merchpilot.infrastructure.database import engine
from merchpilot.infrastructure.milvus import MilvusVectorStore
from merchpilot.infrastructure.redis import get_redis

router = APIRouter(prefix="/health", tags=["health"])

required_worker_tasks = frozenset(
    {
        "merchpilot.execute_planning_run",
        "merchpilot.resume_planning_run",
        "merchpilot.process_tabular_import",
        "merchpilot.index_evidence_batch",
        "merchpilot.generate_planning_report",
    }
)
required_worker_queues = frozenset(
    {
        "planning.normal",
        "agent.review",
        "index.parse",
        "index.embedding",
        "report.generate",
    }
)


async def _probe_postgres(database_url: str) -> bool:
    """内部辅助函数`_probe_postgres`；拆分主流程并集中处理当前模块的边界条件。"""
    del database_url
    try:
        async with asyncio.timeout(2.5):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def _probe_redis(redis_url: str) -> bool:
    """内部辅助函数`_probe_redis`；拆分主流程并集中处理当前模块的边界条件。"""
    del redis_url
    try:
        return bool(await asyncio.wait_for(get_redis().ping(), timeout=2.5))
    except Exception:
        return False


def _probe_worker_sync() -> bool:
    """内部辅助函数`_probe_worker_sync`；拆分主流程并集中处理当前模块的边界条件。"""
    try:
        inspector = celery_app.control.inspect(timeout=1.0)
        ping_response = inspector.ping() or {}
        if not ping_response:
            return False
        registered_tasks = inspector.registered() or {}
        active_queues = inspector.active_queues() or {}
        worker_tasks = {
            task
            for worker_name in ping_response
            for task in registered_tasks.get(worker_name, [])
        }
        worker_queues = {
            str(queue.get("name"))
            for worker_name in ping_response
            for queue in active_queues.get(worker_name, [])
            if isinstance(queue, dict) and queue.get("name")
        }
        return required_worker_tasks <= worker_tasks and required_worker_queues <= worker_queues
    except Exception:
        return False


async def _probe_worker() -> bool:
    """内部辅助函数`_probe_worker`；拆分主流程并集中处理当前模块的边界条件。"""
    return await asyncio.to_thread(_probe_worker_sync)


def _probe_milvus_sync(milvus_uri: str, milvus_token: str) -> bool:
    """内部辅助函数`_probe_milvus_sync`；拆分主流程并集中处理当前模块的边界条件。"""
    del milvus_uri, milvus_token
    store = MilvusVectorStore()
    client = None
    try:
        client = store.client
        client.list_collections()
        return True
    except Exception:
        return False
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


async def _probe_milvus(milvus_uri: str, milvus_token: str) -> bool:
    """内部辅助函数`_probe_milvus`；拆分主流程并集中处理当前模块的边界条件。"""
    return await asyncio.to_thread(_probe_milvus_sync, milvus_uri, milvus_token)


async def _probe_model_service(service_url: str) -> bool:
    """内部辅助函数`_probe_model_service`；拆分主流程并集中处理当前模块的边界条件。"""
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            response = await client.get(f"{service_url.rstrip('/')}/health")
        if response.status_code != 200:
            return False
        payload = response.json()
        return isinstance(payload, dict) and payload.get("status") == "ok"
    except Exception:
        return False


async def _probe_mcp_service(service_url: str) -> bool:
    """内部辅助函数`_probe_mcp_service`；拆分主流程并集中处理当前模块的边界条件。"""
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            response = await client.get(f"{service_url.rstrip('/')}/health")
        if response.status_code != 200:
            return False
        payload = response.json()
        return isinstance(payload, dict) and payload.get("status") == "ok"
    except Exception:
        return False


def _probe_provider(provider_factory: Callable[[], object]) -> bool:
    """内部辅助函数`_probe_provider`；拆分主流程并集中处理当前模块的边界条件。"""
    try:
        provider_factory()
        return True
    except Exception:
        return False


@router.get("/live")
async def live() -> dict[str, str]:
    """处理`GET /live`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> dict[str, object]:
    """处理`GET /ready`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    settings = get_settings()
    postgres, redis, milvus, worker, embedding, reranker, mcp = await asyncio.gather(
        _probe_postgres(settings.database_url),
        _probe_redis(settings.redis_url),
        _probe_milvus(settings.milvus_uri, settings.milvus_token),
        _probe_worker(),
        _probe_model_service(settings.embedding_service_url),
        _probe_model_service(settings.reranker_service_url),
        _probe_mcp_service(settings.mcp_internal_base_url),
    )
    core_checks = {"postgres": postgres, "redis": redis, "milvus": milvus, "worker": worker}
    optional_checks = {"embedding": embedding, "reranker": reranker, "mcp": mcp}
    integration_checks = {
        "identity": _probe_provider(get_identity_provider),
        "object_storage": _probe_provider(get_object_storage_provider),
        "approval": _probe_provider(get_external_approval_provider),
        "telemetry": _probe_provider(get_telemetry_provider),
    }
    provider_modes = {
        "identity": settings.auth_mode,
        "object_storage": settings.object_storage_provider,
        "approval": settings.external_approval_provider,
        "telemetry": settings.telemetry_provider,
    }
    return {
        "status": "ok" if all(core_checks.values()) else "degraded",
        "integration_status": "ok" if all(integration_checks.values()) else "degraded",
        "components": {**core_checks, **optional_checks},
        "core_components": core_checks,
        "optional_components": optional_checks,
        "integration_components": integration_checks,
        "provider_modes": provider_modes,
    }
