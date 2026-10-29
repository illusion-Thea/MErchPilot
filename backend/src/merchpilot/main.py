"""文件职责：创建 FastAPI 应用，管理数据库、缓存、企业适配器与服务生命周期。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response

from merchpilot.adapters.providers import (
    get_external_approval_provider,
    get_identity_provider,
    get_telemetry_provider,
)
from merchpilot.adapters.storage import get_object_storage_provider
from merchpilot.api.router import api_router
from merchpilot.core.config import get_settings
from merchpilot.core.logging import configure_logging, get_logger
from merchpilot.infrastructure.database import engine
from merchpilot.infrastructure.model_clients import close_model_service_clients
from merchpilot.infrastructure.redis import get_redis
from merchpilot.observability.collectors import refresh_runtime_metrics
from merchpilot.observability.metrics import http_request_duration_seconds, http_requests_total
from merchpilot.observability.prometheus import render_metrics

settings = get_settings()
configure_logging()
logger = get_logger("api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """管理应用启动与关闭期间的数据库、Redis、Milvus和企业适配器生命周期。"""
    del app
    try:
        get_identity_provider()
        get_external_approval_provider()
        get_telemetry_provider()
        get_object_storage_provider()
        if settings.object_storage_provider.strip().lower() == "local":
            settings.local_storage_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("local_storage_unavailable", path=str(settings.local_storage_path), error=str(exc))
    logger.info("application_started", environment=settings.app_env)
    yield
    await close_model_service_clients()
    await engine.dispose()
    if get_redis.cache_info().currsize:
        await get_redis().aclose()
        get_redis.cache_clear()
    logger.info("application_stopped")


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    debug=settings.app_debug,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count"],
)


@app.middleware("http")
async def observe_http_request(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """记录低基数 HTTP 指标，供 Prometheus 分析吞吐、错误率和延迟。"""
    started = perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        route_path = getattr(route, "path", request.url.path)
        http_requests_total.labels(
            method=request.method,
            path=route_path,
            status=str(status_code),
        ).inc()
        http_request_duration_seconds.labels(
            method=request.method,
            path=route_path,
        ).observe(perf_counter() - started)


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """刷新依赖服务指标并输出 Prometheus 文本格式。"""
    await refresh_runtime_metrics()
    payload, content_type = render_metrics()
    return Response(payload, media_type=content_type)


app.include_router(api_router)


@app.get("/")
async def root() -> dict[str, str]:
    """实现`root`流程；输入、输出和异常语义由类型标注及调用方约束。"""
    return {"name": settings.app_name, "docs": "/docs", "health": "/health/live"}
