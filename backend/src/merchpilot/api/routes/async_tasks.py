"""文件职责：查询异步任务状态，让页面可追踪 Celery 长任务。"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from merchpilot.api.dependencies import get_current_identity
from merchpilot.api.schemas import AsyncTaskStatusRead
from merchpilot.infrastructure.celery_app import celery_app
from merchpilot.infrastructure.database import get_db_session
from merchpilot.infrastructure.models import DataImportJob, PlanningProject, PlanningReport, PlanningRun
from merchpilot.ports.identity import Identity

router = APIRouter(prefix="/async-tasks", tags=["async-tasks"])
AsyncTaskResourceType = Literal["planning_run", "data_import", "planning_report"]

task_state_labels = {
    "PENDING": "排队中",
    "RECEIVED": "已接收",
    "STARTED": "执行中",
    "RETRY": "重试中",
    "SUCCESS": "已完成",
    "FAILURE": "失败",
    "REVOKED": "已撤销",
    "UNKNOWN": "状态未知",
}


def _normalize_task_ids(raw_task_ids: str) -> list[str]:
    """内部辅助函数`_normalize_task_ids`；拆分主流程并集中处理当前模块的边界条件。"""
    seen: set[str] = set()
    task_ids: list[str] = []
    for value in raw_task_ids.split(","):
        task_id = value.strip()
        if not task_id or task_id in seen:
            continue
        seen.add(task_id)
        task_ids.append(task_id)
    return task_ids[:50]


def _task_state(task_id: str) -> tuple[str, bool, bool]:
    """内部辅助函数`_task_state`；拆分主流程并集中处理当前模块的边界条件。"""
    try:
        state = str(celery_app.AsyncResult(task_id).state or "PENDING").upper()
    except Exception:
        state = "UNKNOWN"
    terminal = state in {"SUCCESS", "FAILURE", "REVOKED"}
    return state, terminal, terminal


async def _owned_task_resources(
    session: AsyncSession,
    identity: Identity,
    task_ids: Iterable[str],
) -> dict[str, tuple[AsyncTaskResourceType, str]]:
    """内部辅助函数`_owned_task_resources`；拆分主流程并集中处理当前模块的边界条件。"""
    requested_ids = list(task_ids)
    if not requested_ids:
        return {}

    resources: dict[str, tuple[AsyncTaskResourceType, str]] = {}
    run_rows = await session.execute(
        select(PlanningRun.celery_task_id, PlanningRun.id)
        .join(PlanningProject, PlanningProject.id == PlanningRun.project_id)
        .where(
            PlanningProject.tenant_id == identity.tenant_id,
            PlanningRun.celery_task_id.in_(requested_ids),
        )
    )
    resources.update({task_id: ("planning_run", resource_id) for task_id, resource_id in run_rows})

    import_rows = await session.execute(
        select(
            DataImportJob.celery_task_id,
            DataImportJob.index_celery_task_id,
            DataImportJob.id,
        ).where(
            DataImportJob.tenant_id == identity.tenant_id,
            (DataImportJob.celery_task_id.in_(requested_ids)
             | DataImportJob.index_celery_task_id.in_(requested_ids)),
        )
    )
    for task_id, index_task_id, resource_id in import_rows:
        if task_id in requested_ids:
            resources[task_id] = ("data_import", resource_id)
        if index_task_id in requested_ids:
            resources[index_task_id] = ("data_import", resource_id)

    report_rows = await session.execute(
        select(PlanningReport.celery_task_id, PlanningReport.id)
        .join(PlanningProject, PlanningProject.id == PlanningReport.project_id)
        .where(
            PlanningProject.tenant_id == identity.tenant_id,
            PlanningReport.celery_task_id.in_(requested_ids),
        )
    )
    resources.update({task_id: ("planning_report", resource_id) for task_id, resource_id in report_rows})
    return resources


@router.get("/status", response_model=list[AsyncTaskStatusRead])
async def get_async_task_status(
    task_ids: str = Query(default="", max_length=3_500),
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> list[AsyncTaskStatusRead]:
    """处理`GET /status`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    requested_ids = _normalize_task_ids(task_ids)
    resources = await _owned_task_resources(session, identity, requested_ids)
    owned_task_ids = [task_id for task_id in requested_ids if task_id in resources]
    states = await asyncio.gather(
        *(asyncio.to_thread(_task_state, task_id) for task_id in owned_task_ids)
    )
    statuses: list[AsyncTaskStatusRead] = []
    for task_id, (state, terminal, ready) in zip(owned_task_ids, states, strict=True):
        resource = resources[task_id]
        statuses.append(
            AsyncTaskStatusRead(
                task_id=task_id,
                state=state,
                state_label=task_state_labels.get(state, state),
                ready=ready,
                terminal=terminal,
                resource_type=resource[0],
                resource_id=resource[1],
            )
        )
    return statuses
