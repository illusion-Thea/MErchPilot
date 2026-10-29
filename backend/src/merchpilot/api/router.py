"""文件职责：提供轻量 Agent 消息路由与跳数保护，避免循环调用。"""

from __future__ import annotations

from fastapi import APIRouter

from merchpilot.api.routes import (
    agents,
    analytics,
    approvals,
    async_tasks,
    audit,
    demo_workspace,
    health,
    identity,
    imports,
    mcp_integration,
    product_initiatives,
    projects,
    reports,
    retrieval,
    selected_products,
    websocket,
)
from merchpilot.core.config import get_settings

settings = get_settings()
api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(async_tasks.router, prefix=settings.api_prefix)
api_router.include_router(identity.router, prefix=settings.api_prefix)
api_router.include_router(demo_workspace.router, prefix=settings.api_prefix)
api_router.include_router(projects.router, prefix=settings.api_prefix)
api_router.include_router(reports.router, prefix=settings.api_prefix)
api_router.include_router(approvals.router, prefix=settings.api_prefix)
api_router.include_router(selected_products.router, prefix=settings.api_prefix)
api_router.include_router(product_initiatives.router, prefix=settings.api_prefix)
api_router.include_router(analytics.router, prefix=settings.api_prefix)
api_router.include_router(agents.router, prefix=settings.api_prefix)
api_router.include_router(audit.router, prefix=settings.api_prefix)
api_router.include_router(imports.router, prefix=settings.api_prefix)
api_router.include_router(retrieval.router, prefix=settings.api_prefix)
api_router.include_router(mcp_integration.router, prefix=settings.api_prefix)
api_router.include_router(websocket.router)
