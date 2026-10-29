"""文件职责：提供规划审批任务的分页、领取、决定和审计接口。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from merchpilot.api.dependencies import get_current_identity, require_admin, require_approver
from merchpilot.api.schemas import (
    ApprovalAssignment,
    ApprovalDecision,
    ApprovalDecisionRequest,
    ApprovalTaskPage,
    ApprovalTaskPageSummary,
    ApprovalTaskRead,
)
from merchpilot.domain.enums import ApprovalStatus, RunStatus
from merchpilot.infrastructure.database import get_db_session
from merchpilot.infrastructure.models import ApprovalTask, PlanningProject, PlanningRun
from merchpilot.ports.identity import Identity
from merchpilot.services.approval_guard import approval_review_fingerprint
from merchpilot.services.audit import record_audit_event
from merchpilot.services.concepts import resolve_candidate_concept
from merchpilot.services.idempotency import (
    build_idempotency_record,
    find_idempotency_record,
    idempotency_payload_hash,
)
from merchpilot.workers.tasks import resume_planning_run

router = APIRouter(prefix="/approval-tasks", tags=["approval-tasks"])
approval_page_statuses = {"pending", "overdue", "processed", "all"}
due_soon_milliseconds = 4 * 60 * 60 * 1_000
approval_confirmation_by_action = {
    ApprovalStatus.APPROVED.value: "APPROVE_PLANNING",
    ApprovalStatus.REJECTED.value: "REJECT_PLANNING",
    ApprovalStatus.REVISION_REQUIRED.value: "REQUEST_PLANNING_REVISION",
}
mcp_revision_constraint_fields = {
    "target_margin",
    "selling_price",
    "unit_cost",
    "supplier_name",
    "moq",
    "lead_time_days",
}


def _is_admin(identity: Identity) -> bool:
    """内部辅助函数`_is_admin`；拆分主流程并集中处理当前模块的边界条件。"""
    return "admin" in identity.roles


def _decision_payload_hash(payload: ApprovalDecision | ApprovalDecisionRequest) -> str:
    """内部辅助函数`_decision_payload_hash`；拆分主流程并集中处理当前模块的边界条件。"""
    serialized = json.dumps(
        payload.model_dump(mode="json", exclude={"confirmation", "review_token"}),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _canonical_decision(
    approval: ApprovalTask, payload: ApprovalDecisionRequest
) -> dict[str, object]:
    """内部辅助函数`_canonical_decision`；拆分主流程并集中处理当前模块的边界条件。"""
    decision = payload.model_dump(mode="json", exclude={"confirmation", "review_token"})
    changes = decision.get("changes")
    if not isinstance(changes, dict):
        return decision
    candidate_id = changes.get("selected_candidate_id")
    if candidate_id is None:
        return decision
    summary = approval.summary if isinstance(approval.summary, dict) else {}
    outputs = summary.get("outputs")
    outputs = outputs if isinstance(outputs, dict) else {}
    concept = outputs.get("concept")
    concept = concept if isinstance(concept, dict) else {}
    selected = resolve_candidate_concept(concept, candidate_id)
    if selected is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="所选候选商品方案不存在或已失效",
        )
    normalized_changes = dict(changes)
    normalized_changes["selected_candidate_id"] = selected["id"]
    normalized_changes["selected_candidate_name"] = selected.get("name")
    decision["changes"] = normalized_changes
    return decision


def _validate_mcp_decision(payload: ApprovalDecisionRequest) -> None:
    """内部辅助函数`_validate_mcp_decision`；拆分主流程并集中处理当前模块的边界条件。"""
    changes = payload.changes
    if payload.action == ApprovalStatus.REJECTED.value:
        if changes:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="FastMCP 驳回决定不能携带候选方案或约束变更",
            )
        if not payload.comment.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="FastMCP 驳回决定必须填写审批意见",
            )
        return

    allowed_change_fields = {"selected_candidate_id"}
    if payload.action == ApprovalStatus.REVISION_REQUIRED.value:
        allowed_change_fields.add("constraints")
        if not payload.comment.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="FastMCP 要求修订时必须填写审批意见",
            )
    unexpected_fields = set(changes) - allowed_change_fields
    if unexpected_fields:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"FastMCP 审批不允许修改字段: {', '.join(sorted(unexpected_fields))}",
        )
    candidate_id = changes.get("selected_candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="FastMCP 通过或要求修订时必须选择候选商品方案",
        )
    if payload.action != ApprovalStatus.REVISION_REQUIRED.value:
        return

    constraints = changes.get("constraints", {})
    if not isinstance(constraints, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="FastMCP 修订约束必须使用对象结构",
        )
    unexpected_constraints = set(constraints) - mcp_revision_constraint_fields
    if unexpected_constraints:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"FastMCP 不允许修改约束: {', '.join(sorted(unexpected_constraints))}",
        )
    target_margin = constraints.get("target_margin")
    if target_margin is not None and (
        isinstance(target_margin, bool)
        or not isinstance(target_margin, (int, float))
        or not 0 <= target_margin <= 1
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="目标毛利率必须在 0 到 1 之间",
        )
    for field_name, allow_zero in (("selling_price", False), ("unit_cost", True)):
        value = constraints.get(field_name)
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or value < 0
            or (not allow_zero and value == 0)
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{field_name} 必须是有效的非负业务数值",
            )
    supplier_name = constraints.get("supplier_name")
    if supplier_name is not None and (
        not isinstance(supplier_name, str)
        or not supplier_name.strip()
        or len(supplier_name) > 255
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="供应商名称必须是 1 到 255 个字符",
        )
    for field_name in ("moq", "lead_time_days"):
        value = constraints.get(field_name)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 1
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{field_name} 必须是大于等于 1 的整数",
            )


@router.get("", response_model=list[ApprovalTaskRead])
async def list_approval_tasks(
    task_status: str | None = Query(default=None, alias="status"),
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> list[ApprovalTask]:
    """处理`GET `接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    query = (
        select(ApprovalTask)
        .join(PlanningProject, PlanningProject.id == ApprovalTask.project_id)
        .where(PlanningProject.tenant_id == identity.tenant_id)
    )
    if task_status is not None:
        try:
            normalized_status = ApprovalStatus(task_status).value
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid approval status",
            ) from exc
        query = query.where(ApprovalTask.status == normalized_status)
    result = await session.scalars(query.order_by(ApprovalTask.created_at.desc()))
    return list(result)


@router.get("/page", response_model=ApprovalTaskPage)
async def page_approval_tasks(
    response: Response,
    task_status: str = Query(default="pending", alias="status"),
    assignee: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    task_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=5, ge=1, le=100),
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    """处理`GET /page`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    if task_status not in approval_page_statuses:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid approval page status",
        )
    if assignee not in {None, "all", "mine", "unassigned"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid approval assignee filter",
        )

    tenant_conditions = [PlanningProject.tenant_id == identity.tenant_id]
    summary_conditions = list(tenant_conditions)
    conditions = list(tenant_conditions)
    if task_status == "pending":
        conditions.append(ApprovalTask.status == ApprovalStatus.PENDING.value)
    elif task_status == "overdue":
        conditions.extend(
            [
                ApprovalTask.status == ApprovalStatus.PENDING.value,
                ApprovalTask.due_at.is_not(None),
                ApprovalTask.due_at < datetime.now(UTC),
            ]
        )
    elif task_status == "processed":
        conditions.append(ApprovalTask.status != ApprovalStatus.PENDING.value)
    if assignee == "mine":
        conditions.extend(
            [
                ApprovalTask.status == ApprovalStatus.PENDING.value,
                ApprovalTask.assignee_id == identity.user_id,
            ]
        )
    elif assignee == "unassigned":
        conditions.extend(
            [
                ApprovalTask.status == ApprovalStatus.PENDING.value,
                ApprovalTask.assignee_id.is_(None),
            ]
        )
    if project_id and project_id != "all":
        conditions.append(ApprovalTask.project_id == project_id)
        summary_conditions.append(ApprovalTask.project_id == project_id)
    if task_id:
        conditions.append(ApprovalTask.id == task_id)

    total = int(
        await session.scalar(
            select(func.count(ApprovalTask.id))
            .join(PlanningProject, PlanningProject.id == ApprovalTask.project_id)
            .where(*conditions)
        )
        or 0
    )
    status_rows = await session.execute(
        select(ApprovalTask.status, func.count(ApprovalTask.id))
        .join(PlanningProject, PlanningProject.id == ApprovalTask.project_id)
        .where(*summary_conditions)
        .group_by(ApprovalTask.status)
    )
    status_counts = {str(task_status_value): int(count) for task_status_value, count in status_rows}
    now = datetime.now(UTC)
    overdue = int(
        await session.scalar(
            select(func.count(ApprovalTask.id))
            .join(PlanningProject, PlanningProject.id == ApprovalTask.project_id)
            .where(
                *summary_conditions,
                ApprovalTask.status == ApprovalStatus.PENDING.value,
                ApprovalTask.due_at.is_not(None),
                ApprovalTask.due_at < now,
            )
        )
        or 0
    )
    due_soon = int(
        await session.scalar(
            select(func.count(ApprovalTask.id))
            .join(PlanningProject, PlanningProject.id == ApprovalTask.project_id)
            .where(
                *summary_conditions,
                ApprovalTask.status == ApprovalStatus.PENDING.value,
                ApprovalTask.due_at >= now,
                ApprovalTask.due_at <= now + timedelta(milliseconds=due_soon_milliseconds),
            )
        )
        or 0
    )
    mine_pending = int(
        await session.scalar(
            select(func.count(ApprovalTask.id))
            .join(PlanningProject, PlanningProject.id == ApprovalTask.project_id)
            .where(
                *summary_conditions,
                ApprovalTask.status == ApprovalStatus.PENDING.value,
                ApprovalTask.assignee_id == identity.user_id,
            )
        )
        or 0
    )
    unassigned_pending = int(
        await session.scalar(
            select(func.count(ApprovalTask.id))
            .join(PlanningProject, PlanningProject.id == ApprovalTask.project_id)
            .where(
                *summary_conditions,
                ApprovalTask.status == ApprovalStatus.PENDING.value,
                ApprovalTask.assignee_id.is_(None),
            )
        )
        or 0
    )
    processed = sum(
        count
        for task_status_value, count in status_counts.items()
        if task_status_value != ApprovalStatus.PENDING.value
    )
    project_rows = await session.execute(
        select(PlanningProject.id, PlanningProject.name)
        .join(ApprovalTask, ApprovalTask.project_id == PlanningProject.id)
        .where(*tenant_conditions)
        .distinct()
        .order_by(PlanningProject.name, PlanningProject.id)
    )
    result = await session.scalars(
        select(ApprovalTask)
        .join(PlanningProject, PlanningProject.id == ApprovalTask.project_id)
        .where(*conditions)
        .order_by(ApprovalTask.created_at.desc(), ApprovalTask.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    response.headers["X-Total-Count"] = str(total)
    return {
        "items": list(result),
        "total": total,
        "page": page,
        "page_size": page_size,
        "summary": ApprovalTaskPageSummary(
            total=sum(status_counts.values()),
            pending=status_counts.get(ApprovalStatus.PENDING.value, 0),
            approved=status_counts.get(ApprovalStatus.APPROVED.value, 0),
            rejected=status_counts.get(ApprovalStatus.REJECTED.value, 0),
            revision_required=status_counts.get(ApprovalStatus.REVISION_REQUIRED.value, 0),
            cancelled=status_counts.get(ApprovalStatus.CANCELLED.value, 0),
            processed=processed,
            overdue=overdue,
            due_soon=due_soon,
            mine_pending=mine_pending,
            unassigned_pending=unassigned_pending,
        ).model_dump(),
        "project_options": [
            {"value": str(project_id), "label": str(project_name)}
            for project_id, project_name in project_rows
        ],
    }


@router.get("/{task_id}", response_model=ApprovalTaskRead)
async def get_approval_task(
    task_id: str,
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> ApprovalTask:
    """处理`GET /{task_id}`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    approval = await session.scalar(
        select(ApprovalTask)
        .join(PlanningProject, PlanningProject.id == ApprovalTask.project_id)
        .where(
            ApprovalTask.id == task_id,
            PlanningProject.tenant_id == identity.tenant_id,
        )
    )
    if approval is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="approval task not found")
    return approval


@router.post("/{task_id}/claim", response_model=ApprovalTaskRead)
async def claim_approval_task(
    task_id: str,
    response: Response,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ] = None,
    client_name: str | None = Header(
        default=None,
        alias="X-MerchPilot-Client",
        max_length=64,
    ),
    identity: Identity = Depends(require_approver),
    session: AsyncSession = Depends(get_db_session),
) -> ApprovalTask:
    """处理`POST /{task_id}/claim`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    request_key = idempotency_key.strip() if idempotency_key else None
    request_client = client_name.strip().lower() if client_name and client_name.strip() else "web"
    if idempotency_key is not None and (request_key is None or len(request_key) < 8):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="审批认领请求标识去除空格后至少需要 8 个字符",
        )
    if request_client == "fastmcp" and request_key is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="FastMCP 认领审批任务必须提供幂等请求标识",
        )
    operation = "approval_task.claim"
    payload_hash = idempotency_payload_hash({"task_id": task_id})

    async def replayed_claim() -> ApprovalTask | None:
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
            or existing.resource_type != "approval_task"
            or existing.resource_id != task_id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="同一审批认领请求标识不能用于不同任务",
            )
        replayed = await session.scalar(
            select(ApprovalTask)
            .join(PlanningProject, PlanningProject.id == ApprovalTask.project_id)
            .where(
                ApprovalTask.id == task_id,
                PlanningProject.tenant_id == identity.tenant_id,
            )
        )
        if replayed is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="幂等请求关联的审批任务不存在，请使用新的请求标识",
            )
        response.headers["Idempotency-Replayed"] = "true"
        response.status_code = status.HTTP_200_OK
        return replayed

    replayed = await replayed_claim()
    if replayed is not None:
        return replayed
    approval = await session.scalar(
        select(ApprovalTask)
        .join(PlanningProject, PlanningProject.id == ApprovalTask.project_id)
        .where(
            ApprovalTask.id == task_id,
            PlanningProject.tenant_id == identity.tenant_id,
        )
        .with_for_update()
    )
    if approval is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="approval task not found")
    replayed = await replayed_claim()
    if replayed is not None:
        return replayed
    if approval.status != ApprovalStatus.PENDING.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="审批任务已处理，不能领取")
    if approval.assignee_id is not None:
        if approval.assignee_id == identity.user_id:
            if request_key:
                session.add(
                    build_idempotency_record(
                        tenant_id=identity.tenant_id,
                        actor_id=identity.user_id,
                        operation=operation,
                        idempotency_key=request_key,
                        payload_hash=payload_hash,
                        client_name=request_client,
                        resource_type="approval_task",
                        resource_id=approval.id,
                        response_snapshot={
                            "task_id": approval.id,
                            "status": approval.status,
                            "assignee_id": approval.assignee_id,
                        },
                    )
                )
                try:
                    await session.commit()
                except IntegrityError as exc:
                    await session.rollback()
                    replayed = await replayed_claim()
                    if replayed is not None:
                        return replayed
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="审批认领请求发生并发冲突，请使用新的请求标识重试",
                    ) from exc
                response.headers["Idempotency-Replayed"] = "false"
            return approval
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"审批任务已由 {approval.assignee_id} 领取",
        )
    approval.assignee_id = identity.user_id
    record_audit_event(
        session,
        action="approval.claimed",
        entity_type="approval_task",
        entity_id=approval.id,
        project_id=approval.project_id,
        tenant_id=identity.tenant_id,
        actor_id=identity.user_id,
        detail={
            "run_id": approval.run_id,
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
                resource_type="approval_task",
                resource_id=approval.id,
                response_snapshot={
                    "task_id": approval.id,
                    "status": approval.status,
                    "assignee_id": approval.assignee_id,
                },
            )
        )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        replayed = await replayed_claim()
        if replayed is not None:
            return replayed
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="审批认领请求发生并发冲突，请使用新的请求标识重试",
        ) from exc
    await session.refresh(approval)
    response.headers["Idempotency-Replayed"] = "false"
    return approval


@router.post("/{task_id}/release", response_model=ApprovalTaskRead)
async def release_approval_task(
    task_id: str,
    identity: Identity = Depends(require_approver),
    session: AsyncSession = Depends(get_db_session),
) -> ApprovalTask:
    """处理`POST /{task_id}/release`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    approval = await session.scalar(
        select(ApprovalTask)
        .join(PlanningProject, PlanningProject.id == ApprovalTask.project_id)
        .where(
            ApprovalTask.id == task_id,
            PlanningProject.tenant_id == identity.tenant_id,
        )
        .with_for_update()
    )
    if approval is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="approval task not found")
    if approval.status != ApprovalStatus.PENDING.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="审批任务已处理，不能释放")
    if approval.assignee_id is None:
        return approval
    if approval.assignee_id != identity.user_id and not _is_admin(identity):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能释放自己领取的审批任务")
    previous_assignee_id = approval.assignee_id
    approval.assignee_id = None
    record_audit_event(
        session,
        action="approval.released",
        entity_type="approval_task",
        entity_id=approval.id,
        project_id=approval.project_id,
        tenant_id=identity.tenant_id,
        actor_id=identity.user_id,
        detail={"run_id": approval.run_id, "previous_assignee_id": previous_assignee_id},
    )
    await session.commit()
    await session.refresh(approval)
    return approval


@router.post("/{task_id}/assign", response_model=ApprovalTaskRead)
async def assign_approval_task(
    task_id: str,
    payload: ApprovalAssignment,
    identity: Identity = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> ApprovalTask:
    """处理`POST /{task_id}/assign`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    approval = await session.scalar(
        select(ApprovalTask)
        .join(PlanningProject, PlanningProject.id == ApprovalTask.project_id)
        .where(
            ApprovalTask.id == task_id,
            PlanningProject.tenant_id == identity.tenant_id,
        )
        .with_for_update()
    )
    if approval is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="approval task not found")
    if approval.status != ApprovalStatus.PENDING.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="审批任务已处理，不能转派")
    assignee_id = payload.assignee_id.strip()
    if not assignee_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="处理人不能为空",
        )
    if approval.assignee_id == assignee_id:
        return approval
    previous_assignee_id = approval.assignee_id
    approval.assignee_id = assignee_id
    record_audit_event(
        session,
        action="approval.assigned",
        entity_type="approval_task",
        entity_id=approval.id,
        project_id=approval.project_id,
        tenant_id=identity.tenant_id,
        actor_id=identity.user_id,
        detail={
            "run_id": approval.run_id,
            "previous_assignee_id": previous_assignee_id,
            "assignee_id": assignee_id,
        },
    )
    await session.commit()
    await session.refresh(approval)
    return approval


@router.post("/{task_id}/decision", response_model=ApprovalTaskRead)
async def decide_approval_task(
    task_id: str,
    response: Response,
    payload: ApprovalDecisionRequest,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ] = None,
    client_name: str | None = Header(
        default=None,
        alias="X-MerchPilot-Client",
        max_length=64,
    ),
    identity: Identity = Depends(require_approver),
    session: AsyncSession = Depends(get_db_session),
) -> ApprovalTask:
    """处理`POST /{task_id}/decision`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    request_id = idempotency_key.strip() if idempotency_key else None
    request_client = client_name.strip().lower() if client_name and client_name.strip() else "web"
    if idempotency_key is not None and (request_id is None or len(request_id) < 8):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="审批请求标识去除空格后至少需要 8 个字符",
        )
    if request_client == "fastmcp" and (
        request_id is None
        or payload.confirmation != approval_confirmation_by_action.get(payload.action)
        or payload.review_token is None
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="FastMCP 提交审批必须提供幂等请求标识、与决定一致的确认词和当前任务复核令牌",
        )
    if request_client == "fastmcp":
        _validate_mcp_decision(payload)
    approval = await session.scalar(
        select(ApprovalTask)
        .join(PlanningProject, PlanningProject.id == ApprovalTask.project_id)
        .where(
            ApprovalTask.id == task_id,
            PlanningProject.tenant_id == identity.tenant_id,
        )
        .with_for_update()
    )
    if approval is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="approval task not found")
    payload_hash = _decision_payload_hash(payload)
    decision_payload = _canonical_decision(approval, payload)
    if request_id and approval.decision_request_id == request_id:
        if approval.decision_payload_hash != payload_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="同一审批请求标识不能提交不同的审批内容",
            )
        response.headers["Idempotency-Replayed"] = "true"
        response.status_code = status.HTTP_200_OK
        return approval
    if approval.status != ApprovalStatus.PENDING.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="approval task is already decided")
    if request_client == "fastmcp":
        if approval.assignee_id != identity.user_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="FastMCP 提交审批前必须由当前审批人先领取任务",
            )
        current_review_token = approval_review_fingerprint(
            task_id=approval.id,
            project_id=approval.project_id,
            run_id=approval.run_id,
            approval_type=approval.approval_type,
            checkpoint_ref=approval.checkpoint_ref,
            status=approval.status,
            assignee_id=approval.assignee_id,
            due_at=approval.due_at,
            summary=approval.summary if isinstance(approval.summary, dict) else {},
        )
        if payload.review_token != current_review_token:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="审批任务已发生变化，请重新读取并复核最新任务后再提交决定",
            )
    if (
        approval.assignee_id is not None
        and approval.assignee_id != identity.user_id
        and not _is_admin(identity)
    ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="审批任务已由其他处理人领取")
    run = await session.scalar(
        select(PlanningRun).where(PlanningRun.id == approval.run_id).with_for_update()
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="审批关联的规划任务不存在",
        )
    if run.status != RunStatus.APPROVAL_REQUIRED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="规划任务当前不处于待审批状态",
        )
    previous_assignee_id = approval.assignee_id
    if approval.assignee_id is None:
        approval.assignee_id = identity.user_id
    approval.status = payload.action
    approval.decision = decision_payload
    approval.decision_request_id = request_id
    approval.decision_payload_hash = payload_hash
    approval.decided_by = identity.user_id
    approval.decided_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(approval)
    try:
        resume_planning_run.delay(run.id, run.thread_id, decision_payload)
    except Exception as exc:
        approval.status = ApprovalStatus.PENDING.value
        approval.decision = None
        approval.decision_request_id = None
        approval.decision_payload_hash = None
        approval.assignee_id = previous_assignee_id
        approval.decided_by = None
        approval.decided_at = None
        record_audit_event(
            session,
            action="approval.dispatch_failed",
            entity_type="approval_task",
            entity_id=approval.id,
            project_id=approval.project_id,
            tenant_id=identity.tenant_id,
            actor_id=identity.user_id,
            detail={
                "run_id": run.id,
                "client": request_client,
                "decision_request_id": request_id,
                "error": str(exc),
            },
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="任务队列暂不可用，审批决定未提交",
        ) from exc
    decision_changes = decision_payload.get("changes")
    record_audit_event(
        session,
        action=f"approval.{payload.action}",
        entity_type="approval_task",
        entity_id=approval.id,
        project_id=approval.project_id,
        tenant_id=identity.tenant_id,
        actor_id=identity.user_id,
        detail={
            "run_id": run.id,
            "comment": payload.comment,
            "changed_fields": sorted(decision_changes) if isinstance(decision_changes, dict) else [],
            "decision_request_id": request_id,
            "assignee_id": approval.assignee_id,
            "client": request_client,
            "review_token": payload.review_token,
        },
    )
    await session.commit()
    response.headers["Idempotency-Replayed"] = "false"
    return approval
