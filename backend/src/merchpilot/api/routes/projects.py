"""文件职责：管理规划项目、Agent 运行、版本、证据与报告入口。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from merchpilot.adapters.storage import get_object_storage_provider
from merchpilot.api.dependencies import (
    acquire_project_run_lock,
    get_current_identity,
    require_planner,
)
from merchpilot.api.schemas import (
    PlanningProjectCreate,
    PlanningProjectPage,
    PlanningProjectPageSummary,
    PlanningProjectRead,
    PlanningProjectUpdate,
    PlanningRunDetail,
    PlanningRunEvidencePage,
    PlanningRunEvidenceRead,
    PlanningRunPage,
    PlanningRunPageSummary,
    PlanningRunRead,
    PlanningRunStartRequest,
    PlanningValidationPlanRequest,
    RunEventRead,
)
from merchpilot.core.config import get_settings
from merchpilot.core.ids import new_id
from merchpilot.domain.enums import ProjectStatus, RunStatus
from merchpilot.infrastructure.database import get_db_session
from merchpilot.infrastructure.events import list_run_events, publish_run_event
from merchpilot.infrastructure.models import EvidenceRecord, PlanningProject, PlanningRun
from merchpilot.ports.identity import Identity
from merchpilot.services.audit import record_audit_event
from merchpilot.services.concepts import apply_candidate_validation_updates
from merchpilot.services.idempotency import (
    build_idempotency_record,
    find_idempotency_record,
    idempotency_payload_hash,
)
from merchpilot.services.planning_evidence import (
    extract_planning_evidence_references,
    resolve_planning_evidence,
    resolve_planning_evidence_references,
)
from merchpilot.services.project_guard import project_configuration_fingerprint
from merchpilot.services.selection_registry import sync_selected_product_validation
from merchpilot.services.tabular_import import safe_storage_filename
from merchpilot.services.validation_guard import validation_review_fingerprint
from merchpilot.services.validation_materials import (
    add_validation_material,
    find_validation_material,
    remove_validation_material,
    validation_gate_exists,
)
from merchpilot.workers.tasks import execute_planning_run

router = APIRouter(prefix="/planning-projects", tags=["planning-projects"])
settings = get_settings()
project_statuses = {item.value for item in ProjectStatus} | {"queued"}
allowed_validation_material_suffixes = {
    ".csv",
    ".doc",
    ".docx",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".txt",
    ".xls",
    ".xlsx",
    ".zip",
}


async def _ensure_project_writable(session: AsyncSession, project_id: str) -> None:
    """内部辅助函数`_ensure_project_writable`；拆分主流程并集中处理当前模块的边界条件。"""
    project = await session.get(PlanningProject, project_id)
    if project is not None and project.archived_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="已归档项目为只读，请先恢复项目",
        )


@router.post("", response_model=PlanningProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: PlanningProjectCreate,
    response: Response,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
    ),
    client_name: str | None = Header(
        default=None,
        alias="X-MerchPilot-Client",
        max_length=64,
    ),
    identity: Identity = Depends(require_planner),
    session: AsyncSession = Depends(get_db_session),
) -> PlanningProject:
    """处理`POST `接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    request_key = idempotency_key.strip() if idempotency_key else None
    request_client = client_name.strip().lower() if client_name and client_name.strip() else "web"
    if idempotency_key is not None and (request_key is None or len(request_key) < 8):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="项目创建请求标识去除空格后至少需要 8 个字符",
        )
    payload_snapshot = payload.model_dump(mode="json")
    payload_hash = idempotency_payload_hash(payload_snapshot)
    operation = "planning_project.create"
    if request_key:
        existing = await find_idempotency_record(
            session,
            tenant_id=identity.tenant_id,
            actor_id=identity.user_id,
            operation=operation,
            idempotency_key=request_key,
        )
        if existing is not None:
            if existing.payload_hash != payload_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="同一项目创建请求标识不能提交不同的项目内容",
                )
            existing_project = cast(
                PlanningProject | None,
                await session.scalar(
                    select(PlanningProject).where(
                        PlanningProject.id == existing.resource_id,
                        PlanningProject.tenant_id == identity.tenant_id,
                    )
                ),
            )
            if existing_project is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="幂等请求关联的规划项目不存在，请使用新的请求标识",
                )
            response.headers["Idempotency-Replayed"] = "true"
            response.status_code = status.HTTP_200_OK
            return existing_project
    project = PlanningProject(
        id=new_id("project"),
        tenant_id=identity.tenant_id,
        name=payload.name,
        category=payload.category,
        target_market=payload.target_market,
        constraints=payload.constraints,
        created_by=identity.user_id,
    )
    session.add(project)
    await session.flush()
    record_audit_event(
        session,
        action="project.created",
        entity_type="planning_project",
        entity_id=project.id,
        project_id=project.id,
        tenant_id=project.tenant_id,
        actor_id=identity.user_id,
        detail={
            "name": project.name,
            "category": project.category,
            "target_market": project.target_market,
            "client": request_client,
            "idempotency_key": request_key,
        },
    )
    if request_key:
        session.add(
            build_idempotency_record(
                tenant_id=identity.tenant_id,
                actor_id=identity.user_id,
                operation=operation,
                idempotency_key=request_key,
                payload_hash=payload_hash,
                client_name=request_client,
                resource_type="planning_project",
                resource_id=project.id,
                response_snapshot={
                    "project_id": project.id,
                    "status": project.status,
                    "name": project.name,
                },
            )
        )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if not request_key:
            raise
        existing = await find_idempotency_record(
            session,
            tenant_id=identity.tenant_id,
            actor_id=identity.user_id,
            operation=operation,
            idempotency_key=request_key,
        )
        if existing is None or existing.payload_hash != payload_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="项目创建请求发生并发冲突，请使用新的请求标识重试",
            ) from exc
        replayed_project = cast(
            PlanningProject | None,
            await session.scalar(
                select(PlanningProject).where(
                    PlanningProject.id == existing.resource_id,
                    PlanningProject.tenant_id == identity.tenant_id,
                )
            ),
        )
        if replayed_project is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="幂等请求关联的规划项目不存在，请使用新的请求标识",
            ) from exc
        response.headers["Idempotency-Replayed"] = "true"
        response.status_code = status.HTTP_200_OK
        return replayed_project
    await session.refresh(project)
    response.headers["Idempotency-Replayed"] = "false"
    return project


@router.get("", response_model=list[PlanningProjectRead])
async def list_projects(
    include_archived: bool = Query(default=False),
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> list[PlanningProject]:
    """处理`GET `接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    query = select(PlanningProject).where(PlanningProject.tenant_id == identity.tenant_id)
    if not include_archived:
        query = query.where(PlanningProject.archived_at.is_(None))
    result = await session.scalars(query.order_by(PlanningProject.created_at.desc()))
    return list(result)


@router.get("/page", response_model=PlanningProjectPage)
async def page_projects(
    response: Response,
    archived_only: bool = Query(default=False),
    project_status: str | None = Query(default=None, alias="status"),
    keyword: str | None = Query(default=None, min_length=1, max_length=255),
    project_id: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=8, ge=1, le=100),
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    """处理`GET /page`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    view_conditions = [PlanningProject.tenant_id == identity.tenant_id]
    if archived_only:
        view_conditions.append(PlanningProject.archived_at.is_not(None))
    else:
        view_conditions.append(PlanningProject.archived_at.is_(None))

    if project_status is not None:
        if project_status not in project_statuses:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid planning project status",
            )
        view_conditions.append(PlanningProject.status == project_status)

    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        view_conditions.append(
            or_(
                PlanningProject.id.ilike(pattern),
                PlanningProject.name.ilike(pattern),
                PlanningProject.category.ilike(pattern),
                PlanningProject.target_market.ilike(pattern),
            )
        )
    if project_id is not None:
        view_conditions.append(PlanningProject.id == project_id)

    total = int(
        await session.scalar(
            select(func.count(PlanningProject.id)).where(*view_conditions)
        )
        or 0
    )

    summary_conditions = [PlanningProject.tenant_id == identity.tenant_id]
    if archived_only:
        summary_conditions.append(PlanningProject.archived_at.is_not(None))
    else:
        summary_conditions.append(PlanningProject.archived_at.is_(None))
    summary_rows = await session.execute(
        select(PlanningProject.status, func.count(PlanningProject.id))
        .where(*summary_conditions)
        .group_by(PlanningProject.status)
    )
    summary_counts = {str(project_status): int(count) for project_status, count in summary_rows}
    summary = PlanningProjectPageSummary(
        total=sum(summary_counts.values()),
        draft=summary_counts.get(ProjectStatus.DRAFT.value, 0),
        queued=summary_counts.get("queued", 0),
        running=summary_counts.get(ProjectStatus.RUNNING.value, 0),
        approval_required=summary_counts.get(ProjectStatus.APPROVAL_REQUIRED.value, 0),
        completed=summary_counts.get(ProjectStatus.COMPLETED.value, 0),
        failed=summary_counts.get(ProjectStatus.FAILED.value, 0),
        cancelled=summary_counts.get(ProjectStatus.CANCELLED.value, 0),
    )
    result = await session.scalars(
        select(PlanningProject)
        .where(*view_conditions)
        .order_by(PlanningProject.updated_at.desc(), PlanningProject.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    response.headers["X-Total-Count"] = str(total)
    return {
        "items": list(result),
        "total": total,
        "page": page,
        "page_size": page_size,
        "summary": summary.model_dump(),
    }


@router.get("/{project_id}", response_model=PlanningProjectRead)
async def get_project(
    project_id: str,
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> PlanningProject:
    """处理`GET /{project_id}`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    project = await session.scalar(
        select(PlanningProject).where(
            PlanningProject.id == project_id,
            PlanningProject.tenant_id == identity.tenant_id,
        )
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="planning project not found")
    return project


@router.post("/{project_id}/archive", response_model=PlanningProjectRead)
async def archive_project(
    project_id: str,
    identity: Identity = Depends(require_planner),
    session: AsyncSession = Depends(get_db_session),
) -> PlanningProject:
    """处理`POST /{project_id}/archive`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    project = await session.scalar(
        select(PlanningProject)
        .where(
            PlanningProject.id == project_id,
            PlanningProject.tenant_id == identity.tenant_id,
        )
        .with_for_update()
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="planning project not found")
    if project.archived_at is not None:
        return project
    active_run = await session.scalar(
        select(PlanningRun.id)
        .where(
            PlanningRun.project_id == project_id,
            PlanningRun.status.in_(
                [
                    RunStatus.QUEUED.value,
                    RunStatus.RUNNING.value,
                    RunStatus.APPROVAL_REQUIRED.value,
                ]
            ),
        )
        .limit(1)
    )
    if active_run is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="进行中或待审批的项目不能归档",
        )
    project.archived_at = datetime.now(UTC)
    project.archived_by = identity.user_id
    record_audit_event(
        session,
        action="project.archived",
        entity_type="planning_project",
        entity_id=project.id,
        project_id=project.id,
        tenant_id=project.tenant_id,
        actor_id=identity.user_id,
        detail={"status": project.status},
    )
    await session.commit()
    await session.refresh(project)
    return project


@router.post("/{project_id}/restore", response_model=PlanningProjectRead)
async def restore_project(
    project_id: str,
    identity: Identity = Depends(require_planner),
    session: AsyncSession = Depends(get_db_session),
) -> PlanningProject:
    """处理`POST /{project_id}/restore`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    project = await session.scalar(
        select(PlanningProject)
        .where(
            PlanningProject.id == project_id,
            PlanningProject.tenant_id == identity.tenant_id,
        )
        .with_for_update()
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="planning project not found")
    if project.archived_at is None:
        return project
    archived_at = project.archived_at.isoformat()
    archived_by = project.archived_by
    project.archived_at = None
    project.archived_by = None
    record_audit_event(
        session,
        action="project.restored",
        entity_type="planning_project",
        entity_id=project.id,
        project_id=project.id,
        tenant_id=project.tenant_id,
        actor_id=identity.user_id,
        detail={"archived_at": archived_at, "archived_by": archived_by},
    )
    await session.commit()
    await session.refresh(project)
    return project


@router.patch("/{project_id}", response_model=PlanningProjectRead)
async def update_project(
    project_id: str,
    payload: PlanningProjectUpdate,
    identity: Identity = Depends(require_planner),
    session: AsyncSession = Depends(get_db_session),
) -> PlanningProject:
    """处理`PATCH /{project_id}`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    project = await session.scalar(
        select(PlanningProject)
        .where(
            PlanningProject.id == project_id,
            PlanningProject.tenant_id == identity.tenant_id,
        )
        .with_for_update()
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="planning project not found")
    if project.archived_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="已归档项目不能修改参数，请先恢复项目",
        )
    active_run = await session.scalar(
        select(PlanningRun.id)
        .where(
            PlanningRun.project_id == project_id,
            PlanningRun.status.in_(
                [
                    RunStatus.QUEUED.value,
                    RunStatus.RUNNING.value,
                    RunStatus.APPROVAL_REQUIRED.value,
                ]
            ),
        )
        .limit(1)
    )
    if active_run is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="进行中或待审批的项目不能修改参数",
        )

    updates = payload.model_dump(exclude_unset=True)
    changed_fields: list[str] = []
    for field in ("name", "category", "target_market", "constraints"):
        if field not in updates:
            continue
        value = updates[field]
        if value is not None and getattr(project, field) != value:
            setattr(project, field, value)
            changed_fields.append(field)
    if changed_fields:
        project.status = ProjectStatus.DRAFT.value
        record_audit_event(
            session,
            action="project.updated",
            entity_type="planning_project",
            entity_id=project.id,
            project_id=project.id,
            tenant_id=project.tenant_id,
            actor_id=identity.user_id,
            detail={"changed_fields": changed_fields},
        )
        await session.commit()
        await session.refresh(project)
    return project


@router.post("/{project_id}/runs", response_model=PlanningRunRead, status_code=status.HTTP_202_ACCEPTED)
async def start_project_run(
    project_id: str,
    response: Response,
    payload: PlanningRunStartRequest | None = None,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
    ),
    client_name: str | None = Header(
        default=None,
        alias="X-MerchPilot-Client",
        max_length=64,
    ),
    identity: Identity = Depends(require_planner),
    _project_lock: None = Depends(acquire_project_run_lock),
    session: AsyncSession = Depends(get_db_session),
) -> PlanningRun:
    """校验配置指纹、确认词和幂等键后，原子创建Agent运行并派发Celery任务。"""
    request_key = idempotency_key.strip() if idempotency_key else None
    request_client = client_name.strip().lower() if client_name and client_name.strip() else "web"
    if idempotency_key is not None and (request_key is None or len(request_key) < 8):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="规划启动请求标识去除空格后至少需要 8 个字符",
        )
    # FastMCP 调用更容易被客户端自动重试，因此写操作强制要求幂等键、确认词和最新复核令牌。
    if request_client == "fastmcp" and request_key is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="FastMCP 启动规划必须提供幂等请求标识",
        )
    if request_client == "fastmcp" and (
        payload is None
        or payload.confirmation != "START_AGENT_ANALYSIS"
        or payload.review_token is None
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="FastMCP 启动规划需要明确确认词和当前项目复核令牌",
        )
    operation = "planning_run.start"
    request_snapshot = {
        "project_id": project_id,
        "confirmation": payload.confirmation if payload else None,
        "review_token": payload.review_token if payload else None,
    }
    payload_hash = idempotency_payload_hash(request_snapshot)

    async def replayed_run() -> PlanningRun | None:
        """返回同一幂等请求的既有结果，避免客户端重试重复创建业务事实。"""
        if request_key is None:
            return None
        existing = await find_idempotency_record(
            session,
            tenant_id=identity.tenant_id,
            actor_id=identity.user_id,
            operation=operation,
            idempotency_key=request_key,
        )
        if existing is None:
            return None
        if existing.payload_hash != payload_hash or existing.resource_type != "planning_run":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="同一规划启动请求标识不能提交不同的项目或确认内容",
            )
        run = await session.scalar(
            select(PlanningRun)
            .join(PlanningProject, PlanningProject.id == PlanningRun.project_id)
            .where(
                PlanningRun.id == existing.resource_id,
                PlanningRun.project_id == project_id,
                PlanningProject.tenant_id == identity.tenant_id,
            )
        )
        if run is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="幂等请求关联的规划运行不存在，请使用新的请求标识",
            )
        response.headers["Idempotency-Replayed"] = "true"
        response.status_code = status.HTTP_200_OK
        return run

    existing_run = await replayed_run()
    if existing_run is not None:
        return existing_run
    # 行锁把“检查进行中任务”和“创建新运行”放在同一并发边界内，防止重复启动。
    project = await session.scalar(
        select(PlanningProject)
        .where(
            PlanningProject.id == project_id,
            PlanningProject.tenant_id == identity.tenant_id,
        )
        .with_for_update()
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="planning project not found")
    if project.archived_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="已归档项目不能启动规划，请先恢复项目",
        )
    existing_run = await replayed_run()
    if existing_run is not None:
        return existing_run
    if request_client == "fastmcp" and project.status != ProjectStatus.DRAFT.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="FastMCP 只允许启动已人工复核且仍处于草稿状态的规划项目",
        )
    # 复核令牌是项目关键配置的指纹；参数变化后旧确认自动失效，避免按过期配置启动 Agent。
    if payload and payload.review_token:
        current_review_token = project_configuration_fingerprint(
            name=project.name,
            category=project.category,
            target_market=project.target_market,
            constraints=project.constraints,
        )
        if payload.review_token != current_review_token:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="规划项目已发生变化，请重新读取并复核最新参数后再启动",
            )

    active_run = await session.scalar(
        select(PlanningRun)
        .where(
            PlanningRun.project_id == project_id,
            PlanningRun.status.in_(
                [
                    RunStatus.QUEUED.value,
                    RunStatus.RUNNING.value,
                    RunStatus.APPROVAL_REQUIRED.value,
                ]
            ),
        )
        .order_by(PlanningRun.created_at.desc())
        .limit(1)
    )
    if active_run is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该项目已有进行中或待审批的规划任务",
        )

    run_id = new_id("run")
    thread_id = new_id("thread")
    input_snapshot = {
        "project_id": project.id,
        "tenant_id": project.tenant_id,
        "requested_by": identity.user_id,
        "name": project.name,
        "category": project.category,
        "target_market": project.target_market,
        "constraints": project.constraints,
    }
    run = PlanningRun(
        id=run_id,
        project_id=project.id,
        thread_id=thread_id,
        status=RunStatus.QUEUED.value,
        input_snapshot=input_snapshot,
    )
    session.add(run)
    project.status = ProjectStatus.RUNNING.value
    record_audit_event(
        session,
        action="run.queued",
        entity_type="planning_run",
        entity_id=run.id,
        project_id=project.id,
        tenant_id=project.tenant_id,
        actor_id=identity.user_id,
        detail={
            "thread_id": thread_id,
            "client": request_client,
            "idempotency_key": request_key,
            "review_token": payload.review_token if payload else None,
        },
    )
    if request_key:
        session.add(
            build_idempotency_record(
                tenant_id=identity.tenant_id,
                actor_id=identity.user_id,
                operation=operation,
                idempotency_key=request_key,
                payload_hash=payload_hash,
                client_name=request_client,
                resource_type="planning_run",
                resource_id=run.id,
                response_snapshot={
                    "run_id": run.id,
                    "project_id": project.id,
                    "status": run.status,
                    "thread_id": thread_id,
                },
            )
        )
    # 运行、项目状态、审计和幂等账本必须一次提交，任一失败都不能留下半条业务事实。
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        existing_run = await replayed_run()
        if existing_run is not None:
            return existing_run
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="规划启动请求发生并发冲突，请使用新的请求标识重试",
        ) from exc

    # 数据库提交成功后才派发 Celery；派发失败会回写运行失败，页面可明确提示并允许重试。
    try:
        task = execute_planning_run.delay(run_id, thread_id, input_snapshot)
    except Exception as exc:
        run.status = RunStatus.FAILED.value
        project.status = ProjectStatus.DRAFT.value
        run.error_message = f"无法提交 Celery 任务: {exc}"
        record_audit_event(
            session,
            action="run.dispatch_failed",
            entity_type="planning_run",
            entity_id=run.id,
            project_id=project.id,
            tenant_id=project.tenant_id,
            actor_id="system",
            detail={"error": str(exc)},
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="任务队列暂不可用",
        ) from exc
    run.celery_task_id = task.id
    await session.commit()
    await session.refresh(run)
    response.headers["Idempotency-Replayed"] = "false"
    return run


@router.post(
    "/{project_id}/runs/{run_id}/retry",
    response_model=PlanningRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_project_run(
    project_id: str,
    run_id: str,
    identity: Identity = Depends(require_planner),
    session: AsyncSession = Depends(get_db_session),
) -> PlanningRun:
    """处理该接口。

    执行身份、租户、参数和业务状态校验后返回类型化响应。
    """
    run = await session.scalar(
        select(PlanningRun)
        .join(PlanningProject, PlanningProject.id == PlanningRun.project_id)
        .where(
            PlanningRun.id == run_id,
            PlanningRun.project_id == project_id,
            PlanningProject.tenant_id == identity.tenant_id,
        )
        .with_for_update()
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="planning run not found")
    if run.status != RunStatus.FAILED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="仅失败的规划任务可以恢复执行",
        )
    project = await session.get(PlanningProject, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="planning project not found")
    if project.archived_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="已归档项目不能恢复任务，请先恢复项目",
        )
    active_run = await session.scalar(
        select(PlanningRun.id)
        .where(
            PlanningRun.project_id == project_id,
            PlanningRun.id != run_id,
            PlanningRun.status.in_(
                [
                    RunStatus.QUEUED.value,
                    RunStatus.RUNNING.value,
                    RunStatus.APPROVAL_REQUIRED.value,
                ]
            ),
        )
        .limit(1)
    )
    if active_run is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该项目已有进行中或待审批的规划任务",
        )

    execution = dict(run.execution_snapshot or {})
    recovery_count = int(execution.get("recovery_count") or 0) + 1
    execution["recovery_count"] = recovery_count
    execution["last_recovery_requested_at"] = datetime.now(UTC).isoformat()
    run.execution_snapshot = execution
    run.status = RunStatus.QUEUED.value
    run.error_message = None
    run.completed_at = None
    project.status = ProjectStatus.RUNNING.value
    record_audit_event(
        session,
        action="run.retry_queued",
        entity_type="planning_run",
        entity_id=run.id,
        project_id=project.id,
        tenant_id=project.tenant_id,
        actor_id=identity.user_id,
        detail={"thread_id": run.thread_id, "recovery_count": recovery_count},
    )
    await session.commit()

    try:
        task = execute_planning_run.delay(run.id, run.thread_id, run.input_snapshot, True)
    except Exception as exc:
        run.status = RunStatus.FAILED.value
        project.status = ProjectStatus.FAILED.value
        run.error_message = f"无法提交恢复任务: {exc}"
        record_audit_event(
            session,
            action="run.retry_dispatch_failed",
            entity_type="planning_run",
            entity_id=run.id,
            project_id=project.id,
            tenant_id=project.tenant_id,
            actor_id="system",
            detail={"error": str(exc), "recovery_count": recovery_count},
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="任务队列暂不可用",
        ) from exc
    run.celery_task_id = task.id
    await session.commit()
    await session.refresh(run)
    return run


@router.get("/{project_id}/runs", response_model=list[PlanningRunRead])
async def list_project_runs(
    project_id: str,
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> list[PlanningRun]:
    """处理`GET /{project_id}/runs`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    project = await session.scalar(
        select(PlanningProject.id).where(
            PlanningProject.id == project_id,
            PlanningProject.tenant_id == identity.tenant_id,
        )
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="planning project not found")
    result = await session.scalars(
        select(PlanningRun)
        .where(PlanningRun.project_id == project_id)
        .order_by(PlanningRun.created_at.desc())
    )
    return list(result)


@router.get("/{project_id}/runs/page", response_model=PlanningRunPage)
async def page_project_runs(
    project_id: str,
    response: Response,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=5, ge=1, le=100),
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    """处理`GET /{project_id}/runs/page`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    project = await session.scalar(
        select(PlanningProject.id).where(
            PlanningProject.id == project_id,
            PlanningProject.tenant_id == identity.tenant_id,
        )
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="planning project not found")

    total = int(
        await session.scalar(
            select(func.count(PlanningRun.id)).where(PlanningRun.project_id == project_id)
        )
        or 0
    )
    status_rows = await session.execute(
        select(PlanningRun.status, func.count(PlanningRun.id))
        .where(PlanningRun.project_id == project_id)
        .group_by(PlanningRun.status)
    )
    status_counts = {str(run_status): int(count) for run_status, count in status_rows}
    summary = PlanningRunPageSummary(
        total=total,
        queued=status_counts.get(RunStatus.QUEUED.value, 0),
        running=status_counts.get(RunStatus.RUNNING.value, 0),
        approval_required=status_counts.get(RunStatus.APPROVAL_REQUIRED.value, 0),
        completed=status_counts.get(RunStatus.COMPLETED.value, 0),
        failed=status_counts.get(RunStatus.FAILED.value, 0),
        cancelled=status_counts.get(RunStatus.CANCELLED.value, 0),
        superseded=status_counts.get(RunStatus.SUPERSEDED.value, 0),
        active=sum(
            status_counts.get(run_status.value, 0)
            for run_status in (
                RunStatus.QUEUED,
                RunStatus.RUNNING,
                RunStatus.APPROVAL_REQUIRED,
            )
        ),
    )
    result = await session.scalars(
        select(PlanningRun)
        .where(PlanningRun.project_id == project_id)
        .order_by(
            PlanningRun.created_at.desc(),
            PlanningRun.revision_no.desc(),
            PlanningRun.id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    response.headers["X-Total-Count"] = str(total)
    return {
        "items": list(result),
        "total": total,
        "page": page,
        "page_size": page_size,
        "summary": summary.model_dump(),
    }


@router.get("/{project_id}/runs/{run_id}", response_model=PlanningRunDetail)
async def get_project_run(
    project_id: str,
    run_id: str,
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> PlanningRun:
    """处理`GET /{project_id}/runs/{run_id}`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    run = await session.scalar(
        select(PlanningRun)
        .join(PlanningProject, PlanningProject.id == PlanningRun.project_id)
        .where(
            PlanningRun.id == run_id,
            PlanningRun.project_id == project_id,
            PlanningProject.tenant_id == identity.tenant_id,
        )
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="planning run not found")
    return run


@router.patch(
    "/{project_id}/runs/{run_id}/validation-plan",
    response_model=PlanningRunDetail,
)
async def update_run_validation_plan(
    project_id: str,
    run_id: str,
    payload: PlanningValidationPlanRequest,
    response: Response,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
    ),
    client_name: str | None = Header(
        default=None,
        alias="X-MerchPilot-Client",
        max_length=64,
    ),
    identity: Identity = Depends(require_planner),
    session: AsyncSession = Depends(get_db_session),
) -> PlanningRun:
    """处理该接口。

    执行身份、租户、参数和业务状态校验后返回类型化响应。
    """
    request_key = idempotency_key.strip() if idempotency_key else None
    request_client = client_name.strip().lower() if client_name and client_name.strip() else "web"
    if idempotency_key is not None and (request_key is None or len(request_key) < 8):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="验证门禁请求标识去除空格后至少需要 8 个字符",
        )
    payload_snapshot = payload.model_dump(
        mode="json",
        exclude={"confirmation", "review_token"},
    )
    payload_hash = idempotency_payload_hash(payload_snapshot)
    operation = "planning_validation.update"

    async def replayed_update() -> PlanningRun | None:
        """返回同一幂等请求的既有结果，避免客户端重试重复创建业务事实。"""
        if request_key is None:
            return None
        existing = await find_idempotency_record(
            session,
            tenant_id=identity.tenant_id,
            actor_id=identity.user_id,
            operation=operation,
            idempotency_key=request_key,
        )
        if existing is None:
            return None
        if (
            existing.payload_hash != payload_hash
            or existing.resource_type != "planning_run"
            or existing.resource_id != run_id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="同一验证门禁请求标识不能提交不同的更新内容",
            )
        replayed = await session.scalar(
            select(PlanningRun)
            .join(PlanningProject, PlanningProject.id == PlanningRun.project_id)
            .where(
                PlanningRun.id == run_id,
                PlanningRun.project_id == project_id,
                PlanningProject.tenant_id == identity.tenant_id,
            )
        )
        if replayed is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="幂等请求关联的规划运行不存在，请使用新的请求标识",
            )
        response.headers["Idempotency-Replayed"] = "true"
        response.status_code = status.HTTP_200_OK
        return replayed

    if request_client == "fastmcp":
        if request_key is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="FastMCP 更新验证门禁必须提供幂等请求标识",
            )
        if len(payload.gates) != 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="FastMCP 每次只能更新一个验证门禁",
            )
        gate_update = payload.gates[0]
        expected_confirmation = {
            "ready": "MARK_VALIDATION_READY",
            "blocked": "MARK_VALIDATION_BLOCKED",
            "pending": "RESET_VALIDATION_PENDING",
        }[gate_update.status]
        if payload.confirmation != expected_confirmation:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="验证门禁确认词必须与目标状态一致",
            )
        if payload.review_token is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="FastMCP 更新验证门禁必须提供最新复核令牌",
            )
        if not gate_update.note.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="FastMCP 更新验证门禁必须填写复核说明",
            )

    replayed = await replayed_update()
    if replayed is not None:
        return replayed
    run = await session.scalar(
        select(PlanningRun)
        .join(PlanningProject, PlanningProject.id == PlanningRun.project_id)
        .where(
            PlanningRun.id == run_id,
            PlanningRun.project_id == project_id,
            PlanningProject.tenant_id == identity.tenant_id,
        )
        .with_for_update()
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="planning run not found")
    replayed = await replayed_update()
    if replayed is not None:
        return replayed
    await _ensure_project_writable(session, project_id)

    snapshot = dict(run.result_snapshot or {})
    outputs = snapshot.get("outputs")
    outputs = dict(outputs) if isinstance(outputs, dict) else {}
    concept = outputs.get("concept")
    concept = dict(concept) if isinstance(concept, dict) else {}
    candidates = concept.get("candidates")
    candidates = list(candidates) if isinstance(candidates, list) else []
    candidate_id = str(payload.candidate_id).strip()
    candidate_index = next(
        (
            index
            for index, item in enumerate(candidates)
            if isinstance(item, dict) and str(item.get("id") or "").strip() == candidate_id
        ),
        None,
    )
    if candidate_index is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="候选商品方案不存在或已失效",
        )

    candidate = dict(candidates[candidate_index])
    validation_plan = candidate.get("validation_plan")
    validation_plan = dict(validation_plan) if isinstance(validation_plan, dict) else {}
    gates = validation_plan.get("gates")
    gate_rows = gates if isinstance(gates, list) else []
    valid_gate_ids = {
        str(item.get("id") or "").strip()
        for item in gate_rows
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    submitted_gate_ids = {item.gate_id.strip() for item in payload.gates}
    unknown_gate_ids = sorted(submitted_gate_ids - valid_gate_ids)
    if not valid_gate_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前运行没有可更新的落地验证清单",
        )
    if unknown_gate_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"验证门槛不存在: {', '.join(unknown_gate_ids)}",
        )
    if request_client == "fastmcp":
        if run.status not in {RunStatus.APPROVAL_REQUIRED.value, RunStatus.COMPLETED.value}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="FastMCP 只能更新待审批或已完成运行的验证门禁",
            )
        selected_candidate_id = str(concept.get("selected_candidate_id") or "").strip()
        if selected_candidate_id != candidate_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="FastMCP 只能更新当前已选候选方案的验证门禁",
            )
        current_review_token = validation_review_fingerprint(
            project_id=project_id,
            run_id=run.id,
            run_status=run.status,
            candidate_id=candidate_id,
            validation_plan=validation_plan,
        )
        if payload.review_token != current_review_token:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="验证清单已发生变化，请重新读取并复核最新状态后再更新",
            )

    for gate_update in payload.gates:
        if gate_update.status != "ready":
            continue
        target_gate = next(
            (
                item
                for item in gate_rows
                if isinstance(item, dict)
                and str(item.get("id") or "").strip() == gate_update.gate_id.strip()
            ),
            None,
        )
        materials = target_gate.get("materials") if isinstance(target_gate, dict) else None
        has_available_material = isinstance(materials, list) and any(
            isinstance(material, dict)
            and bool(str(material.get("storage_key") or "").strip())
            and material.get("source_missing") is not True
            for material in materials
        )
        if not has_available_material:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="标记验证通过前必须先由人工上传可用验证材料",
            )

    updated_at = datetime.now(UTC).isoformat()
    updated_plan = apply_candidate_validation_updates(
        validation_plan,
        [item.model_dump() for item in payload.gates],
        actor_id=identity.user_id,
        updated_at=updated_at,
    )
    candidate["validation_plan"] = updated_plan
    candidate["requires_validation"] = updated_plan["requires_validation"]
    candidates[candidate_index] = candidate
    concept["candidates"] = candidates
    if concept.get("selected_candidate_id") == candidate_id:
        concept["selected_candidate"] = candidate
    outputs["concept"] = concept
    snapshot["outputs"] = outputs
    run.result_snapshot = snapshot
    await sync_selected_product_validation(
        session,
        run_id=run.id,
        candidate_id=candidate_id,
        validation_plan=updated_plan,
        actor_id=identity.user_id,
    )
    record_audit_event(
        session,
        action="planning_validation.updated",
        entity_type="planning_run",
        entity_id=run.id,
        project_id=project_id,
        tenant_id=identity.tenant_id,
        actor_id=identity.user_id,
        detail={
            "candidate_id": candidate_id,
            "candidate_name": candidate.get("name"),
            "gate_ids": sorted(submitted_gate_ids),
            "validation_status": updated_plan.get("status"),
            "completion_rate": updated_plan.get("completion_rate"),
            "client": request_client,
            "idempotency_key": request_key,
            "review_token": payload.review_token,
        },
    )
    if request_key:
        session.add(
            build_idempotency_record(
                tenant_id=identity.tenant_id,
                actor_id=identity.user_id,
                operation=operation,
                idempotency_key=request_key,
                payload_hash=payload_hash,
                client_name=request_client,
                resource_type="planning_run",
                resource_id=run.id,
                response_snapshot={
                    "project_id": project_id,
                    "run_id": run.id,
                    "candidate_id": candidate_id,
                    "gate_ids": sorted(submitted_gate_ids),
                    "validation_status": updated_plan.get("status"),
                },
            )
        )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        replayed = await replayed_update()
        if replayed is not None:
            return replayed
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="验证门禁更新发生并发冲突，请使用新的请求标识重试",
        ) from exc
    await session.refresh(run)
    try:
        await publish_run_event(
            run.id,
            "planning.validation.updated",
            {
                "candidate_id": candidate_id,
                "candidate_name": candidate.get("name"),
                "validation_status": updated_plan.get("status"),
                "completion_rate": updated_plan.get("completion_rate"),
                "updated_by": identity.user_id,
            },
        )
    except Exception:
        pass
    response.headers["Idempotency-Replayed"] = "false"
    return run


@router.post(
    "/{project_id}/runs/{run_id}/validation-materials",
    response_model=PlanningRunDetail,
    status_code=status.HTTP_201_CREATED,
)
async def upload_validation_material(
    project_id: str,
    run_id: str,
    candidate_id: str = Form(..., min_length=1, max_length=64),
    gate_id: str = Form(..., min_length=1, max_length=64),
    note: str = Form(default="", max_length=2_000),
    file: UploadFile = File(...),
    identity: Identity = Depends(require_planner),
    session: AsyncSession = Depends(get_db_session),
) -> PlanningRun:
    """处理该接口。

    执行身份、租户、参数和业务状态校验后返回类型化响应。
    """
    filename = safe_storage_filename(file.filename or "validation-material")
    suffix = Path(filename).suffix.lower()
    if suffix not in allowed_validation_material_suffixes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证材料仅支持 PDF、Office、图片、文本、CSV 和 ZIP 文件",
        )
    max_material_bytes = min(settings.max_import_file_bytes, 20_971_520)
    content = await file.read(max_material_bytes + 1)
    await file.close()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证材料不能为空")
    if len(content) > max_material_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="验证材料超过 20 MB 限制",
        )

    run = await session.scalar(
        select(PlanningRun)
        .join(PlanningProject, PlanningProject.id == PlanningRun.project_id)
        .where(
            PlanningRun.id == run_id,
            PlanningRun.project_id == project_id,
            PlanningProject.tenant_id == identity.tenant_id,
        )
        .with_for_update()
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="planning run not found")
    await _ensure_project_writable(session, project_id)
    snapshot = dict(run.result_snapshot or {})
    if not validation_gate_exists(snapshot, candidate_id, gate_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="候选商品方案或验证门不存在",
        )

    material_id = new_id("material")
    storage_key = (
        f"validation-materials/{project_id}/{run_id}/{candidate_id}/{gate_id}/"
        f"{material_id}-{filename}"
    )
    storage = get_object_storage_provider()
    material = {
        "id": material_id,
        "candidate_id": candidate_id,
        "gate_id": gate_id,
        "filename": filename,
        "content_type": file.content_type or "application/octet-stream",
        "size": len(content),
        "note": note.strip(),
        "storage_key": storage_key,
        "download_path": (
            f"/api/v1/planning-projects/{project_id}/runs/{run_id}/"
            f"validation-materials/{material_id}/download"
        ),
        "uploaded_by": identity.user_id,
        "uploaded_at": datetime.now(UTC).isoformat(),
    }
    updated_snapshot = add_validation_material(snapshot, candidate_id, gate_id, material)
    if updated_snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="验证材料关联失败",
        )
    try:
        await storage.put_object(storage_key, content, str(material["content_type"]))
        run.result_snapshot = updated_snapshot
        record_audit_event(
            session,
            action="planning_validation.material_uploaded",
            entity_type="planning_run",
            entity_id=run.id,
            project_id=project_id,
            tenant_id=identity.tenant_id,
            actor_id=identity.user_id,
            detail={
                "candidate_id": candidate_id,
                "gate_id": gate_id,
                "material_id": material_id,
                "filename": filename,
                "size": len(content),
            },
        )
        await session.commit()
        await session.refresh(run)
    except Exception:
        await session.rollback()
        await storage.delete_object(storage_key)
        raise
    try:
        await publish_run_event(
            run.id,
            "planning.validation.material_uploaded",
            {
                "candidate_id": candidate_id,
                "gate_id": gate_id,
                "material_id": material_id,
                "filename": filename,
                "uploaded_by": identity.user_id,
            },
        )
    except Exception:
        pass
    return run


@router.delete(
    "/{project_id}/runs/{run_id}/validation-materials/{material_id}",
    response_model=PlanningRunDetail,
)
async def delete_validation_material(
    project_id: str,
    run_id: str,
    material_id: str,
    identity: Identity = Depends(require_planner),
    session: AsyncSession = Depends(get_db_session),
) -> PlanningRun:
    """
    处理`DELETE
    /{project_id}/runs/{run_id}/validation-materials/{material_id}`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。
    """
    run = await session.scalar(
        select(PlanningRun)
        .join(PlanningProject, PlanningProject.id == PlanningRun.project_id)
        .where(
            PlanningRun.id == run_id,
            PlanningRun.project_id == project_id,
            PlanningProject.tenant_id == identity.tenant_id,
        )
        .with_for_update()
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="planning run not found")
    await _ensure_project_writable(session, project_id)
    snapshot = dict(run.result_snapshot or {})
    material = find_validation_material(snapshot, material_id)
    if material is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="验证材料不存在")
    removed = remove_validation_material(snapshot, material_id)
    if removed is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="验证材料不存在")
    updated_snapshot, _ = removed
    run.result_snapshot = updated_snapshot
    record_audit_event(
        session,
        action="planning_validation.material_deleted",
        entity_type="planning_run",
        entity_id=run.id,
        project_id=project_id,
        tenant_id=identity.tenant_id,
        actor_id=identity.user_id,
        detail={
            "candidate_id": material.get("candidate_id"),
            "gate_id": material.get("gate_id"),
            "material_id": material_id,
            "filename": material.get("filename"),
        },
    )
    await session.commit()
    await session.refresh(run)
    storage_key = material.get("storage_key")
    if isinstance(storage_key, str) and storage_key:
        await get_object_storage_provider().delete_object(storage_key)
    try:
        await publish_run_event(
            run.id,
            "planning.validation.material_deleted",
            {
                "material_id": material_id,
                "filename": material.get("filename"),
                "deleted_by": identity.user_id,
            },
        )
    except Exception:
        pass
    return run


@router.get(
    "/{project_id}/runs/{run_id}/validation-materials/{material_id}/download",
)
async def download_validation_material(
    project_id: str,
    run_id: str,
    material_id: str,
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """处理该接口。

    执行身份、租户、参数和业务状态校验后返回类型化响应。
    """
    run = await session.scalar(
        select(PlanningRun)
        .join(PlanningProject, PlanningProject.id == PlanningRun.project_id)
        .where(
            PlanningRun.id == run_id,
            PlanningRun.project_id == project_id,
            PlanningProject.tenant_id == identity.tenant_id,
        )
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="planning run not found")
    material = find_validation_material(dict(run.result_snapshot or {}), material_id)
    if material is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="验证材料不存在")
    storage_key = material.get("storage_key")
    if not isinstance(storage_key, str) or not storage_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="验证材料路径不存在")
    try:
        content = await get_object_storage_provider().get_object(storage_key)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="验证材料文件不存在") from exc
    return Response(
        content=content,
        media_type=str(material.get("content_type") or "application/octet-stream"),
        headers={
            "Content-Disposition": (
                "attachment; filename*=UTF-8''"
                f"{quote(str(material.get('filename') or 'validation-material'))}"
            )
        },
    )


@router.get(
    "/{project_id}/runs/{run_id}/events",
    response_model=list[RunEventRead],
)
async def list_project_run_events(
    project_id: str,
    run_id: str,
    limit: int = Query(default=200, ge=1, le=500),
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, object]]:
    """处理该接口。

    执行身份、租户、参数和业务状态校验后返回类型化响应。
    """
    run = await session.scalar(
        select(PlanningRun.id)
        .join(PlanningProject, PlanningProject.id == PlanningRun.project_id)
        .where(
            PlanningRun.id == run_id,
            PlanningRun.project_id == project_id,
            PlanningProject.tenant_id == identity.tenant_id,
        )
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="planning run not found")
    return await list_run_events(run_id, limit=limit)


@router.get(
    "/{project_id}/runs/{run_id}/evidence/page",
    response_model=PlanningRunEvidencePage,
)
async def page_project_run_evidence(
    project_id: str,
    run_id: str,
    response: Response,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=8, ge=1, le=100),
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    """处理该接口。

    执行身份、租户、参数和业务状态校验后返回类型化响应。
    """
    run = await session.scalar(
        select(PlanningRun)
        .join(PlanningProject, PlanningProject.id == PlanningRun.project_id)
        .where(
            PlanningRun.id == run_id,
            PlanningRun.project_id == project_id,
            PlanningProject.tenant_id == identity.tenant_id,
        )
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="planning run not found")
    references = extract_planning_evidence_references(run.result_snapshot)
    total = len(references)
    evidence_ids = [reference["evidence_id"] for reference in references]
    available_total = (
        int(
            await session.scalar(
                select(func.count(EvidenceRecord.id)).where(
                    EvidenceRecord.id.in_(evidence_ids),
                    EvidenceRecord.tenant_id == identity.tenant_id,
                )
            )
            or 0
        )
        if evidence_ids
        else 0
    )
    page_references = references[(page - 1) * page_size : page * page_size]
    page_evidence_ids = [reference["evidence_id"] for reference in page_references]
    records = (
        list(
            await session.scalars(
                select(EvidenceRecord).where(
                    EvidenceRecord.id.in_(page_evidence_ids),
                    EvidenceRecord.tenant_id == identity.tenant_id,
                )
            )
        )
        if page_evidence_ids
        else []
    )
    items = [
        PlanningRunEvidenceRead.model_validate(item)
        for item in resolve_planning_evidence_references(page_references, records)
    ]
    response.headers["X-Total-Count"] = str(total)
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "unavailable_total": max(0, total - available_total),
    }


@router.get(
    "/{project_id}/runs/{run_id}/evidence",
    response_model=list[PlanningRunEvidenceRead],
)
async def list_project_run_evidence(
    project_id: str,
    run_id: str,
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> list[PlanningRunEvidenceRead]:
    """处理该接口。

    执行身份、租户、参数和业务状态校验后返回类型化响应。
    """
    run = await session.scalar(
        select(PlanningRun)
        .join(PlanningProject, PlanningProject.id == PlanningRun.project_id)
        .where(
            PlanningRun.id == run_id,
            PlanningRun.project_id == project_id,
            PlanningProject.tenant_id == identity.tenant_id,
        )
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="planning run not found")
    references = extract_planning_evidence_references(run.result_snapshot)
    evidence_ids = [reference["evidence_id"] for reference in references]
    records = (
        list(
            await session.scalars(
                select(EvidenceRecord).where(
                    EvidenceRecord.id.in_(evidence_ids),
                    EvidenceRecord.tenant_id == identity.tenant_id,
                )
            )
        )
        if evidence_ids
        else []
    )
    return [
        PlanningRunEvidenceRead.model_validate(item)
        for item in resolve_planning_evidence(run.result_snapshot, records)
    ]
