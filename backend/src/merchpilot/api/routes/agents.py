"""文件职责：提供规划 Mesh 执行节点目录，方便前端展示、审计和项目学习。"""

from __future__ import annotations

from fastapi import APIRouter

from merchpilot.agents.catalog import AgentDefinition, get_agent_catalog

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/catalog", response_model=list[AgentDefinition])
async def get_catalog() -> list[AgentDefinition]:
    """返回当前 Mesh 的节点类型、职责、Prompt 版本和业务边界。"""
    return get_agent_catalog()
