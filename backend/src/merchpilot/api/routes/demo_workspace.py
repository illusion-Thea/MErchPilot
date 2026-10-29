"""文件职责：仅在本地开发身份下提供演示工作区的查询和幂等初始化。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from merchpilot.api.dependencies import get_current_identity, require_admin
from merchpilot.api.schemas import LocalDemoWorkspaceRead
from merchpilot.core.config import get_settings
from merchpilot.infrastructure.database import get_db_session
from merchpilot.infrastructure.models import DataImportJob
from merchpilot.ports.identity import Identity
from merchpilot.services.demo_workspace import (
    demo_evidence_ids,
    demo_import_id,
    ensure_demo_workspace,
    get_demo_workspace,
    mark_demo_index_dispatch_failed,
    mark_demo_index_dispatched,
    prepare_demo_evidence_indexing,
)
from merchpilot.workers.tasks import index_evidence_batch

router = APIRouter(prefix="/demo-workspace", tags=["demo-workspace"])


def _ensure_local_demo_enabled() -> None:
    """阻止演示初始化能力进入企业或生产身份模式。"""
    settings = get_settings()
    if (
        not settings.demo_workspace_enabled
        or settings.auth_mode.strip().lower() != "local"
        or settings.app_env.strip().lower() not in {"dev", "development", "local"}
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="演示工作区未启用")


@router.get("", response_model=LocalDemoWorkspaceRead | None)
async def read_demo_workspace(
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> LocalDemoWorkspaceRead | None:
    """查询当前租户是否已经具备完整演示工作区。"""
    _ensure_local_demo_enabled()
    return await get_demo_workspace(session, identity)


@router.post("", response_model=LocalDemoWorkspaceRead)
async def create_demo_workspace(
    identity: Identity = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> LocalDemoWorkspaceRead:
    """幂等创建当前租户演示数据，并异步写入现有 Milvus 索引。"""
    _ensure_local_demo_enabled()
    initialized_workspace = await ensure_demo_workspace(session, identity)
    await prepare_demo_evidence_indexing(session, identity.tenant_id)
    refreshed_workspace = await get_demo_workspace(session, identity) or initialized_workspace
    workspace = refreshed_workspace.model_copy(
        update={
            "created": initialized_workspace.created,
            "message": initialized_workspace.message,
        }
    )
    job = await session.get(DataImportJob, demo_import_id(identity.tenant_id))
    if workspace.index_status == "indexed":
        return workspace
    if (
        workspace.index_status == "indexing"
        and job is not None
        and job.index_celery_task_id
    ):
        return workspace.model_copy(update={"index_task_id": job.index_celery_task_id})
    evidence_ids = demo_evidence_ids(identity.tenant_id)
    index_task_id: str | None = None
    try:
        task = index_evidence_batch.delay(evidence_ids)
        index_task_id = task.id
        await mark_demo_index_dispatched(session, identity.tenant_id, index_task_id)
    except Exception as exc:
        # 初始化本身已成功时不回滚业务演示数据；页面会明确提示索引任务可稍后重试。
        await mark_demo_index_dispatch_failed(session, identity.tenant_id, str(exc))
        failed_workspace = await get_demo_workspace(session, identity) or workspace
        return failed_workspace.model_copy(
            update={
                "created": workspace.created,
                "message": f"{workspace.message} Milvus 索引任务暂未提交：{exc}",
            }
        )
    indexed_workspace = await get_demo_workspace(session, identity) or workspace
    return indexed_workspace.model_copy(
        update={
            "created": workspace.created,
            "index_task_id": index_task_id,
            "message": workspace.message,
        }
    )
