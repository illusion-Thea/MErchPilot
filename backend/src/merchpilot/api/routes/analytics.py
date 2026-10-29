"""文件职责：提供仪表盘、通知、机会分析和同项目闭环台账查询。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import and_, case, false, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from merchpilot.api.dependencies import get_current_identity
from merchpilot.api.schemas import (
    ApprovalTaskRead,
    DashboardSnapshot,
    NotificationEntityReference,
    NotificationSnapshot,
    OpportunityPage,
    OpportunitySummary,
    PlanningProjectRead,
    ProductInitiativeRead,
    ProductLaunchReviewRead,
    ProjectLifecyclePage,
    ProjectLifecyclePageSummary,
    ProjectLifecycleRead,
    ProjectLifecycleStageRead,
    SelectedProductRead,
)
from merchpilot.domain.enums import ApprovalStatus, ProjectStatus
from merchpilot.infrastructure.database import get_db_session
from merchpilot.infrastructure.models import (
    ApprovalTask,
    DataImportJob,
    EvidenceRecord,
    PlanningProject,
    PlanningRun,
    ProductInitiative,
    ProductLaunchReview,
    SelectedProduct,
)
from merchpilot.ports.identity import Identity
from merchpilot.services.opportunity_analytics import extract_opportunity_metrics
from merchpilot.services.project_lifecycle import derive_project_lifecycle

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _initiative_attention_condition() -> ColumnElement[bool]:
    """内部辅助函数`_initiative_attention_condition`；拆分主流程并集中处理当前模块的边界条件。"""
    blocked_milestone = ProductInitiative.milestones.contains([{"status": "blocked"}])
    overdue_milestone = text(
        "EXISTS ("
        "SELECT 1 FROM jsonb_array_elements(product_initiatives.milestones) AS milestone(value) "
        "WHERE milestone.value ->> 'status' <> 'completed' "
        "AND NULLIF(milestone.value ->> 'due_date', '') IS NOT NULL "
        "AND (milestone.value ->> 'due_date')::date < CURRENT_DATE"
        ")"
    )
    return or_(
        ProductInitiative.status == "launch_ready",
        blocked_milestone,
        (ProductInitiative.status == "in_progress") & overdue_milestone,
    )


def _launch_review_read(review: ProductLaunchReview, initiative_name: str) -> ProductLaunchReviewRead:
    """内部辅助函数`_launch_review_read`；拆分主流程并集中处理当前模块的边界条件。"""
    return ProductLaunchReviewRead.model_validate({
        "id": review.id,
        "tenant_id": review.tenant_id,
        "initiative_id": review.initiative_id,
        "initiative_name": initiative_name,
        "status": review.status,
        "submission_note": review.submission_note,
        "decision_note": review.decision_note,
        "readiness_snapshot": review.readiness_snapshot,
        "submitted_by": review.submitted_by,
        "submitted_at": review.submitted_at,
        "decided_by": review.decided_by,
        "decided_at": review.decided_at,
        "created_at": review.created_at,
        "updated_at": review.updated_at,
    })


def _entity_reference(entity_id: str, label: str) -> NotificationEntityReference:
    """内部辅助函数`_entity_reference`；拆分主流程并集中处理当前模块的边界条件。"""
    return NotificationEntityReference(id=entity_id, label=label)


def _opportunity_summary(
    project: PlanningProject,
    run: PlanningRun | None,
) -> OpportunitySummary:
    """内部辅助函数`_opportunity_summary`；拆分主流程并集中处理当前模块的边界条件。"""
    metrics = extract_opportunity_metrics(run.result_snapshot if run is not None else None)
    return OpportunitySummary(
        project_id=project.id,
        project_name=project.name,
        category=project.category,
        target_market=project.target_market,
        project_status=project.status,
        run_id=run.id if run is not None else None,
        run_status=run.status if run is not None else None,
        updated_at=run.updated_at if run is not None else project.updated_at,
        **metrics,
    )


@router.get("/notifications", response_model=NotificationSnapshot)
async def get_notification_snapshot(
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> NotificationSnapshot:
    """聚合需要当前用户处理的数据质量、审批、选品和立项提醒。"""
    tenant_id = identity.tenant_id
    now = datetime.now(UTC)
    can_approve = bool({"admin", "approver"}.intersection(identity.roles))
    actionable_approval_conditions = [
        PlanningProject.tenant_id == tenant_id,
        ApprovalTask.status == ApprovalStatus.PENDING.value,
    ]
    if "admin" not in identity.roles:
        actionable_approval_conditions.append(
            or_(
                ApprovalTask.assignee_id.is_(None),
                ApprovalTask.assignee_id == identity.user_id,
            )
            if can_approve
            else false()
        )
    overdue_approval_conditions = [
        *actionable_approval_conditions,
        ApprovalTask.due_at.is_not(None),
        ApprovalTask.due_at < now,
    ]
    active_approval_conditions = [
        *actionable_approval_conditions,
        or_(ApprovalTask.due_at.is_(None), ApprovalTask.due_at >= now),
    ]
    actionable_approval_count = int(
        await session.scalar(
            select(func.count(ApprovalTask.id))
            .join(PlanningProject, PlanningProject.id == ApprovalTask.project_id)
            .where(*actionable_approval_conditions)
        )
        or 0
    )
    overdue_actionable_approval_count = int(
        await session.scalar(
            select(func.count(ApprovalTask.id))
            .join(PlanningProject, PlanningProject.id == ApprovalTask.project_id)
            .where(*overdue_approval_conditions)
        )
        or 0
    )
    latest_actionable_approval = await session.scalar(
        select(ApprovalTask)
        .join(PlanningProject, PlanningProject.id == ApprovalTask.project_id)
        .where(*active_approval_conditions)
        .order_by(ApprovalTask.created_at.desc(), ApprovalTask.id.desc())
        .limit(1)
    )
    latest_overdue_approval = await session.scalar(
        select(ApprovalTask)
        .join(PlanningProject, PlanningProject.id == ApprovalTask.project_id)
        .where(*overdue_approval_conditions)
        .order_by(ApprovalTask.due_at.asc(), ApprovalTask.created_at.desc())
        .limit(1)
    )

    pending_launch_review_count = int(
        await session.scalar(
            select(func.count(ProductLaunchReview.id))
            .join(ProductInitiative, ProductInitiative.id == ProductLaunchReview.initiative_id)
            .where(
                ProductLaunchReview.tenant_id == tenant_id,
                ProductInitiative.tenant_id == tenant_id,
                ProductLaunchReview.status == "pending",
            )
        )
        or 0
    )
    latest_launch_review_row = await session.execute(
        select(ProductLaunchReview, ProductInitiative.name)
        .join(ProductInitiative, ProductInitiative.id == ProductLaunchReview.initiative_id)
        .where(
            ProductLaunchReview.tenant_id == tenant_id,
            ProductInitiative.tenant_id == tenant_id,
            ProductLaunchReview.status == "pending",
        )
        .order_by(ProductLaunchReview.created_at.desc(), ProductLaunchReview.id.desc())
        .limit(1)
    )
    latest_launch_review = None
    latest_launch_review_record = latest_launch_review_row.first()
    if latest_launch_review_record is not None:
        review, initiative_name = latest_launch_review_record
        latest_launch_review = _launch_review_read(review, str(initiative_name))

    async def selection_summary(selection_status: str) -> tuple[int, NotificationEntityReference | None]:
        """实现`selection_summary`接口辅助流程，供当前路由复用权限与状态判断。"""
        conditions = [
            SelectedProduct.tenant_id == tenant_id,
            SelectedProduct.status == selection_status,
        ]
        count = int(
            await session.scalar(select(func.count(SelectedProduct.id)).where(*conditions)) or 0
        )
        record = await session.scalar(
            select(SelectedProduct)
            .where(*conditions)
            .order_by(SelectedProduct.selected_at.desc(), SelectedProduct.id.desc())
            .limit(1)
        )
        return count, _entity_reference(record.id, record.name) if record is not None else None

    async def project_summary(project_status: str) -> tuple[int, NotificationEntityReference | None]:
        """实现`project_summary`接口辅助流程，供当前路由复用权限与状态判断。"""
        conditions = [
            PlanningProject.tenant_id == tenant_id,
            PlanningProject.archived_at.is_(None),
            PlanningProject.status == project_status,
        ]
        count = int(
            await session.scalar(select(func.count(PlanningProject.id)).where(*conditions)) or 0
        )
        record = await session.scalar(
            select(PlanningProject)
            .where(*conditions)
            .order_by(PlanningProject.updated_at.desc(), PlanningProject.id.desc())
            .limit(1)
        )
        return count, _entity_reference(record.id, record.name) if record is not None else None

    new_selection_count, latest_new_selection = await selection_summary("selected")
    ready_selection_count, latest_ready_selection = await selection_summary("ready")
    failed_project_count, latest_failed_project = await project_summary(ProjectStatus.FAILED.value)
    cancelled_project_count, latest_cancelled_project = await project_summary(
        ProjectStatus.CANCELLED.value
    )
    awaiting_approval_project_count, latest_awaiting_approval_project = await project_summary(
        ProjectStatus.APPROVAL_REQUIRED.value
    )

    failed_import_conditions = [
        DataImportJob.tenant_id == tenant_id,
        DataImportJob.status == "failed",
    ]
    failed_import_count = int(
        await session.scalar(select(func.count(DataImportJob.id)).where(*failed_import_conditions))
        or 0
    )
    latest_failed_import_record = await session.scalar(
        select(DataImportJob)
        .where(*failed_import_conditions)
        .order_by(DataImportJob.created_at.desc(), DataImportJob.id.desc())
        .limit(1)
    )
    invalid_import_conditions = [
        DataImportJob.tenant_id == tenant_id,
        DataImportJob.status == "completed",
        DataImportJob.invalid_rows > 0,
    ]
    invalid_import_count, invalid_import_rows = (
        await session.execute(
            select(
                func.count(DataImportJob.id),
                func.coalesce(func.sum(DataImportJob.invalid_rows), 0),
            ).where(*invalid_import_conditions)
        )
    ).one()
    latest_invalid_import_record = await session.scalar(
        select(DataImportJob)
        .where(*invalid_import_conditions)
        .order_by(DataImportJob.created_at.desc(), DataImportJob.id.desc())
        .limit(1)
    )
    pending_index_import_row = (
        await session.execute(
            select(DataImportJob.id, DataImportJob.filename)
            .join(EvidenceRecord, EvidenceRecord.import_job_id == DataImportJob.id)
            .where(
                DataImportJob.tenant_id == tenant_id,
                EvidenceRecord.tenant_id == tenant_id,
                EvidenceRecord.index_status.in_(("pending", "indexing")),
            )
            .group_by(DataImportJob.id, DataImportJob.filename, DataImportJob.updated_at)
            .order_by(func.count(EvidenceRecord.id).desc(), DataImportJob.updated_at.desc())
            .limit(1)
        )
    ).first()

    return NotificationSnapshot(
        actionable_approval_count=actionable_approval_count,
        overdue_actionable_approval_count=overdue_actionable_approval_count,
        latest_actionable_approval=ApprovalTaskRead.model_validate(latest_actionable_approval)
        if latest_actionable_approval is not None
        else None,
        latest_overdue_approval=ApprovalTaskRead.model_validate(latest_overdue_approval)
        if latest_overdue_approval is not None
        else None,
        pending_launch_review_count=pending_launch_review_count,
        latest_launch_review=latest_launch_review,
        new_selection_count=new_selection_count,
        latest_new_selection=latest_new_selection,
        ready_selection_count=ready_selection_count,
        latest_ready_selection=latest_ready_selection,
        failed_project_count=failed_project_count,
        latest_failed_project=latest_failed_project,
        cancelled_project_count=cancelled_project_count,
        latest_cancelled_project=latest_cancelled_project,
        awaiting_approval_project_count=awaiting_approval_project_count,
        latest_awaiting_approval_project=latest_awaiting_approval_project,
        failed_import_count=failed_import_count,
        latest_failed_import=_entity_reference(
            latest_failed_import_record.id,
            latest_failed_import_record.filename,
        )
        if latest_failed_import_record is not None
        else None,
        invalid_import_count=int(invalid_import_count),
        invalid_import_rows=int(invalid_import_rows),
        latest_invalid_import=_entity_reference(
            latest_invalid_import_record.id,
            latest_invalid_import_record.filename,
        )
        if latest_invalid_import_record is not None
        else None,
        pending_index_import=_entity_reference(
            str(pending_index_import_row[0]),
            str(pending_index_import_row[1]),
        )
        if pending_index_import_row is not None
        else None,
    )


@router.get("/dashboard", response_model=DashboardSnapshot)
async def get_dashboard_snapshot(
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> DashboardSnapshot:
    """聚合同一租户的核心业务指标和最新记录，为首页提供一致快照。"""
    tenant_id = identity.tenant_id
    tenant_project_conditions = [
        PlanningProject.tenant_id == tenant_id,
        PlanningProject.archived_at.is_(None),
    ]
    latest_project = await session.scalar(
        select(PlanningProject)
        .where(*tenant_project_conditions)
        .order_by(PlanningProject.updated_at.desc(), PlanningProject.id.desc())
        .limit(1)
    )
    project_status_rows = await session.execute(
        select(PlanningProject.status, func.count(PlanningProject.id))
        .where(*tenant_project_conditions)
        .group_by(PlanningProject.status)
    )
    project_status_counts = {str(project_status): int(count) for project_status, count in project_status_rows}
    project_total = sum(project_status_counts.values())
    active_project_total = sum(
        project_status_counts.get(project_status.value, 0)
        for project_status in (
            ProjectStatus.RUNNING,
            ProjectStatus.APPROVAL_REQUIRED,
        )
    ) + project_status_counts.get("queued", 0)
    completed_project_total = project_status_counts.get(ProjectStatus.COMPLETED.value, 0)

    latest_opportunity = None
    latest_run = None
    if latest_project is not None:
        latest_run = await session.scalar(
            select(PlanningRun)
            .where(PlanningRun.project_id == latest_project.id)
            .order_by(PlanningRun.created_at.desc(), PlanningRun.id.desc())
            .limit(1)
        )
        if latest_run is not None:
            latest_opportunity = OpportunitySummary(
                project_id=latest_project.id,
                project_name=latest_project.name,
                category=latest_project.category,
                target_market=latest_project.target_market,
                project_status=latest_project.status,
                run_id=latest_run.id,
                run_status=latest_run.status,
                updated_at=latest_run.updated_at,
                **extract_opportunity_metrics(latest_run.result_snapshot),
            )

    latest_selection = None
    latest_ready_selection = await session.scalar(
        select(SelectedProduct)
        .where(
            SelectedProduct.tenant_id == tenant_id,
            SelectedProduct.status == "ready",
        )
        .order_by(SelectedProduct.updated_at.desc(), SelectedProduct.id.desc())
        .limit(1)
    )
    latest_pending_selection = await session.scalar(
        select(SelectedProduct)
        .where(
            SelectedProduct.tenant_id == tenant_id,
            SelectedProduct.status.in_(("selected", "validating")),
            (SelectedProduct.validation_status != "ready") | SelectedProduct.validation_status.is_(None),
        )
        .order_by(SelectedProduct.updated_at.desc(), SelectedProduct.id.desc())
        .limit(1)
    )
    if latest_project is not None:
        selection_query = select(SelectedProduct).where(
            SelectedProduct.tenant_id == tenant_id,
            SelectedProduct.project_id == latest_project.id,
        )
        latest_selection = await session.scalar(
            selection_query.order_by(SelectedProduct.updated_at.desc(), SelectedProduct.id.desc()).limit(1)
        )

    selection_status_rows = await session.execute(
        select(
            SelectedProduct.status,
            SelectedProduct.validation_status,
            func.count(SelectedProduct.id),
        )
        .where(SelectedProduct.tenant_id == tenant_id)
        .group_by(SelectedProduct.status, SelectedProduct.validation_status)
    )
    selected_product_total = 0
    selected_product_validating = 0
    selected_product_ready = 0
    for product_status, validation_status, count in selection_status_rows:
        normalized_count = int(count)
        selected_product_total += normalized_count
        if str(product_status) in {"selected", "validating"} and validation_status != "ready":
            selected_product_validating += normalized_count
        if str(product_status) == "ready":
            selected_product_ready += normalized_count

    latest_initiative = None
    if latest_selection is not None:
        latest_initiative = await session.scalar(
            select(ProductInitiative)
            .where(
                ProductInitiative.tenant_id == tenant_id,
                ProductInitiative.selected_product_id == latest_selection.id,
            )
            .order_by(ProductInitiative.updated_at.desc(), ProductInitiative.id.desc())
            .limit(1)
        )
    elif latest_project is not None:
        latest_initiative = await session.scalar(
            select(ProductInitiative)
            .where(
                ProductInitiative.tenant_id == tenant_id,
                ProductInitiative.project_id == latest_project.id,
            )
            .order_by(ProductInitiative.updated_at.desc(), ProductInitiative.id.desc())
            .limit(1)
        )
    attention_initiative = await session.scalar(
        select(ProductInitiative)
        .where(ProductInitiative.tenant_id == tenant_id, _initiative_attention_condition())
        .order_by(ProductInitiative.updated_at.desc(), ProductInitiative.id.desc())
        .limit(1)
    )
    progress_initiative = await session.scalar(
        select(ProductInitiative)
        .where(
            ProductInitiative.tenant_id == tenant_id,
            ProductInitiative.status.in_(("in_progress", "launch_ready")),
        )
        .order_by(ProductInitiative.updated_at.desc(), ProductInitiative.id.desc())
        .limit(1)
    )
    active_initiative_total = int(
        await session.scalar(
            select(func.count(ProductInitiative.id)).where(
                ProductInitiative.tenant_id == tenant_id,
                ProductInitiative.status.in_(("in_progress", "launch_ready")),
            )
        )
        or 0
    )

    pending_approval_conditions = [
        ApprovalTask.status == ApprovalStatus.PENDING.value,
        PlanningProject.tenant_id == tenant_id,
    ]
    pending_approval_count = int(
        await session.scalar(
            select(func.count(ApprovalTask.id))
            .join(PlanningProject, PlanningProject.id == ApprovalTask.project_id)
            .where(*pending_approval_conditions)
        )
        or 0
    )
    latest_approval = await session.scalar(
        select(ApprovalTask)
        .join(PlanningProject, PlanningProject.id == ApprovalTask.project_id)
        .where(*pending_approval_conditions)
        .order_by(ApprovalTask.created_at.desc(), ApprovalTask.id.desc())
        .limit(1)
    )

    pending_launch_review_count = int(
        await session.scalar(
            select(func.count(ProductLaunchReview.id))
            .join(ProductInitiative, ProductInitiative.id == ProductLaunchReview.initiative_id)
            .where(
                ProductLaunchReview.tenant_id == tenant_id,
                ProductInitiative.tenant_id == tenant_id,
                ProductLaunchReview.status == "pending",
            )
        )
        or 0
    )
    latest_launch_review_row = await session.execute(
        select(ProductLaunchReview, ProductInitiative.name)
        .join(ProductInitiative, ProductInitiative.id == ProductLaunchReview.initiative_id)
        .where(
            ProductLaunchReview.tenant_id == tenant_id,
            ProductInitiative.tenant_id == tenant_id,
            ProductLaunchReview.status == "pending",
        )
        .order_by(ProductLaunchReview.created_at.desc(), ProductLaunchReview.id.desc())
        .limit(1)
    )
    latest_launch_review = None
    latest_launch_review_record = latest_launch_review_row.first()
    if latest_launch_review_record is not None:
        review, initiative_name = latest_launch_review_record
        latest_launch_review = _launch_review_read(review, str(initiative_name))

    pending_index_import_id = None
    pending_index_row = await session.execute(
        select(DataImportJob.id)
        .join(EvidenceRecord, EvidenceRecord.import_job_id == DataImportJob.id)
        .where(
            DataImportJob.tenant_id == tenant_id,
            EvidenceRecord.tenant_id == tenant_id,
            EvidenceRecord.index_status.in_(("pending", "indexing")),
        )
        .group_by(DataImportJob.id)
        .order_by(func.count(EvidenceRecord.id).desc(), DataImportJob.updated_at.desc())
        .limit(1)
    )
    pending_index_import_id = pending_index_row.scalar_one_or_none()

    return DashboardSnapshot(
        latest_project=(
            PlanningProjectRead.model_validate(latest_project)
            if latest_project is not None
            else None
        ),
        latest_opportunity=latest_opportunity,
        latest_selection=SelectedProductRead.model_validate(latest_selection)
        if latest_selection is not None
        else None,
        latest_ready_selection=SelectedProductRead.model_validate(latest_ready_selection)
        if latest_ready_selection is not None
        else None,
        latest_pending_selection=SelectedProductRead.model_validate(latest_pending_selection)
        if latest_pending_selection is not None
        else None,
        latest_initiative=ProductInitiativeRead.model_validate(latest_initiative)
        if latest_initiative is not None
        else None,
        attention_initiative=ProductInitiativeRead.model_validate(attention_initiative)
        if attention_initiative is not None
        else None,
        progress_initiative=ProductInitiativeRead.model_validate(progress_initiative)
        if progress_initiative is not None
        else None,
        latest_approval=ApprovalTaskRead.model_validate(latest_approval)
        if latest_approval is not None
        else None,
        latest_launch_review=latest_launch_review,
        pending_approval_count=pending_approval_count,
        pending_launch_review_count=pending_launch_review_count,
        project_total=project_total,
        active_project_total=active_project_total,
        completed_project_total=completed_project_total,
        selected_product_total=selected_product_total,
        selected_product_validating=selected_product_validating,
        selected_product_ready=selected_product_ready,
        active_initiative_total=active_initiative_total,
        pending_index_import_id=str(pending_index_import_id) if pending_index_import_id else None,
    )


@router.get("/opportunities/page", response_model=OpportunityPage)
async def page_opportunities(
    response: Response,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=12, ge=1, le=50),
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> OpportunityPage:
    """处理`GET /opportunities/page`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    latest_run_id = (
        select(PlanningRun.id)
        .where(PlanningRun.project_id == PlanningProject.id)
        .order_by(PlanningRun.created_at.desc(), PlanningRun.id.desc())
        .limit(1)
        .correlate(PlanningProject)
        .scalar_subquery()
    )
    project_conditions = [
        PlanningProject.tenant_id == identity.tenant_id,
        PlanningProject.archived_at.is_(None),
    ]
    total = int(
        await session.scalar(select(func.count(PlanningProject.id)).where(*project_conditions))
        or 0
    )
    rows = (
        await session.execute(
            select(PlanningProject, PlanningRun)
            .outerjoin(PlanningRun, PlanningRun.id == latest_run_id)
            .where(*project_conditions)
            .order_by(PlanningProject.updated_at.desc(), PlanningProject.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    response.headers["X-Total-Count"] = str(total)
    return OpportunityPage(
        items=[_opportunity_summary(project, run) for project, run in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/project-lifecycles/page", response_model=ProjectLifecyclePage)
async def page_project_lifecycles(
    response: Response,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=6, ge=1, le=50),
    project_id: str | None = Query(default=None, max_length=64),
    keyword: str | None = Query(default=None, max_length=128),
    sort: Literal["priority", "updated"] = Query(default="priority"),
    status: Literal["all", "blocked", "waiting_human", "active", "complete"] = Query(
        default="all"
    ),
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> ProjectLifecyclePage:
    """按租户、项目、关键词、状态和优先级分页返回同项目闭环台账及汇总。"""
    latest_run_id = (
        select(PlanningRun.id)
        .where(PlanningRun.project_id == PlanningProject.id)
        .order_by(
            PlanningRun.revision_no.desc(),
            PlanningRun.created_at.desc(),
            PlanningRun.id.desc(),
        )
        .limit(1)
        .correlate(PlanningProject)
        .scalar_subquery()
    )
    base_conditions = [
        PlanningProject.tenant_id == identity.tenant_id,
        PlanningProject.archived_at.is_(None),
    ]
    if project_id:
        base_conditions.append(PlanningProject.id == project_id)
    normalized_keyword = (keyword or "").strip()
    if normalized_keyword:
        keyword_pattern = f"%{normalized_keyword}%"
        base_conditions.append(
            or_(
                PlanningProject.name.like(keyword_pattern),
                PlanningProject.category.like(keyword_pattern),
                PlanningProject.target_market.like(keyword_pattern),
            )
        )

    latest_approval_status = (
        select(ApprovalTask.status)
        .where(ApprovalTask.run_id == latest_run_id)
        .order_by(ApprovalTask.updated_at.desc(), ApprovalTask.id.desc())
        .limit(1)
        .correlate(PlanningProject)
        .scalar_subquery()
    )
    latest_selection_id = (
        select(SelectedProduct.id)
        .where(
            SelectedProduct.tenant_id == identity.tenant_id,
            SelectedProduct.run_id == latest_run_id,
        )
        .order_by(SelectedProduct.updated_at.desc(), SelectedProduct.id.desc())
        .limit(1)
        .correlate(PlanningProject)
        .scalar_subquery()
    )
    latest_selection_status = (
        select(SelectedProduct.status)
        .where(SelectedProduct.id == latest_selection_id)
        .correlate(PlanningProject)
        .scalar_subquery()
    )
    latest_validation_status = (
        select(SelectedProduct.validation_status)
        .where(SelectedProduct.id == latest_selection_id)
        .correlate(PlanningProject)
        .scalar_subquery()
    )
    latest_initiative_id = (
        select(ProductInitiative.id)
        .where(
            ProductInitiative.tenant_id == identity.tenant_id,
            ProductInitiative.project_id == PlanningProject.id,
            ProductInitiative.run_id == latest_run_id,
        )
        .order_by(ProductInitiative.updated_at.desc(), ProductInitiative.id.desc())
        .limit(1)
        .correlate(PlanningProject)
        .scalar_subquery()
    )
    latest_initiative_status = (
        select(ProductInitiative.status)
        .where(ProductInitiative.id == latest_initiative_id)
        .correlate(PlanningProject)
        .scalar_subquery()
    )
    latest_initiative_milestones = (
        select(ProductInitiative.milestones)
        .where(ProductInitiative.id == latest_initiative_id)
        .correlate(PlanningProject)
        .scalar_subquery()
    )
    latest_review_status = (
        select(ProductLaunchReview.status)
        .where(
            ProductLaunchReview.tenant_id == identity.tenant_id,
            ProductLaunchReview.initiative_id == latest_initiative_id,
        )
        .order_by(ProductLaunchReview.updated_at.desc(), ProductLaunchReview.id.desc())
        .limit(1)
        .correlate(PlanningProject)
        .scalar_subquery()
    )
    selection_exists = latest_selection_id.is_not(None)
    initiative_exists = latest_initiative_id.is_not(None)
    launched = latest_initiative_status == "launched"
    lifecycle_blocked = or_(
        PlanningProject.status.in_(("failed", "cancelled")),
        and_(PlanningRun.status.in_(("failed", "cancelled")), ~selection_exists),
        and_(
            latest_approval_status.in_(("rejected", "revision_required", "cancelled")),
            ~selection_exists,
        ),
        and_(
            or_(
                latest_validation_status == "blocked",
                latest_selection_status.in_(("paused", "cancelled")),
            ),
            ~initiative_exists,
        ),
        latest_initiative_status.in_(("paused", "cancelled")),
        and_(
            latest_initiative_milestones.contains([{"status": "blocked"}]),
            ~launched,
        ),
        and_(latest_review_status.in_(("rejected", "revision_required")), ~launched),
    )
    lifecycle_waiting_for_human = or_(
        and_(latest_approval_status == "pending", ~selection_exists),
        and_(latest_review_status == "pending", ~launched),
    )
    lifecycle_priority = case(
        (lifecycle_blocked, 0),
        (lifecycle_waiting_for_human, 1),
        (launched, 3),
        else_=2,
    )
    lifecycle_bucket = lifecycle_priority.label("lifecycle_bucket")
    lifecycle_buckets = (
        select(PlanningProject.id.label("project_id"), lifecycle_bucket)
        .outerjoin(PlanningRun, PlanningRun.id == latest_run_id)
        .where(*base_conditions)
        .subquery()
    )
    summary_row = (
        await session.execute(
            select(
                func.count(lifecycle_buckets.c.project_id),
                func.sum(case((lifecycle_buckets.c.lifecycle_bucket == 0, 1), else_=0)),
                func.sum(case((lifecycle_buckets.c.lifecycle_bucket == 1, 1), else_=0)),
                func.sum(case((lifecycle_buckets.c.lifecycle_bucket == 2, 1), else_=0)),
                func.sum(case((lifecycle_buckets.c.lifecycle_bucket == 3, 1), else_=0)),
            )
        )
    ).one()
    summary = ProjectLifecyclePageSummary(
        total=int(summary_row[0] or 0),
        blocked=int(summary_row[1] or 0),
        waiting_human=int(summary_row[2] or 0),
        active=int(summary_row[3] or 0),
        complete=int(summary_row[4] or 0),
    )
    conditions = [*base_conditions]
    if status != "all":
        bucket_value = {
            "blocked": 0,
            "waiting_human": 1,
            "active": 2,
            "complete": 3,
        }[status]
        conditions.append(lifecycle_priority == bucket_value)
    lifecycle_order = (
        (lifecycle_priority.asc(), PlanningProject.updated_at.desc(), PlanningProject.id.desc())
        if sort == "priority"
        else (PlanningProject.updated_at.desc(), PlanningProject.id.desc())
    )

    total = int(
        await session.scalar(
            select(func.count(PlanningProject.id))
            .outerjoin(PlanningRun, PlanningRun.id == latest_run_id)
            .where(*conditions)
        )
        or 0
    )
    project_rows = (
        await session.execute(
            select(PlanningProject, PlanningRun)
            .outerjoin(PlanningRun, PlanningRun.id == latest_run_id)
            .where(*conditions)
            .order_by(*lifecycle_order)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    run_ids = [run.id for _, run in project_rows if run is not None]
    approvals_by_run: dict[str, ApprovalTask] = {}
    selections_by_run: dict[str, SelectedProduct] = {}
    if run_ids:
        approval_rows = (
            await session.scalars(
                select(ApprovalTask)
                .where(ApprovalTask.run_id.in_(run_ids))
                .order_by(ApprovalTask.updated_at.desc(), ApprovalTask.id.desc())
            )
        ).all()
        for approval in approval_rows:
            approvals_by_run.setdefault(approval.run_id, approval)

        selection_rows = (
            await session.scalars(
                select(SelectedProduct)
                .where(
                    SelectedProduct.tenant_id == identity.tenant_id,
                    SelectedProduct.run_id.in_(run_ids),
                )
                .order_by(SelectedProduct.updated_at.desc(), SelectedProduct.id.desc())
            )
        ).all()
        for selection in selection_rows:
            selections_by_run.setdefault(selection.run_id, selection)

    selected_product_ids = [selection.id for selection in selections_by_run.values()]
    initiatives_by_selection: dict[str, ProductInitiative] = {}
    if selected_product_ids:
        initiative_rows = (
            await session.scalars(
                select(ProductInitiative)
                .where(
                    ProductInitiative.tenant_id == identity.tenant_id,
                    ProductInitiative.selected_product_id.in_(selected_product_ids),
                )
                .order_by(ProductInitiative.updated_at.desc(), ProductInitiative.id.desc())
            )
        ).all()
        for initiative in initiative_rows:
            initiatives_by_selection.setdefault(initiative.selected_product_id, initiative)

    initiative_ids = [initiative.id for initiative in initiatives_by_selection.values()]
    reviews_by_initiative: dict[str, ProductLaunchReview] = {}
    if initiative_ids:
        review_rows = (
            await session.scalars(
                select(ProductLaunchReview)
                .where(
                    ProductLaunchReview.tenant_id == identity.tenant_id,
                    ProductLaunchReview.initiative_id.in_(initiative_ids),
                )
                .order_by(ProductLaunchReview.updated_at.desc(), ProductLaunchReview.id.desc())
            )
        ).all()
        for review in review_rows:
            reviews_by_initiative.setdefault(review.initiative_id, review)

    items: list[ProjectLifecycleRead] = []
    for project, run in project_rows:
        current_approval = approvals_by_run.get(run.id) if run is not None else None
        current_selection = selections_by_run.get(run.id) if run is not None else None
        current_initiative = (
            initiatives_by_selection.get(current_selection.id)
            if current_selection is not None
            else None
        )
        current_review = (
            reviews_by_initiative.get(current_initiative.id)
            if current_initiative is not None
            else None
        )
        milestones = (
            [dict(item) for item in current_initiative.milestones if isinstance(item, dict)]
            if current_initiative is not None
            else []
        )
        state = derive_project_lifecycle(
            project_id=project.id,
            project_status=project.status,
            run_id=run.id if run is not None else None,
            run_status=run.status if run is not None else None,
            run_error_message=run.error_message if run is not None else None,
            approval_task_id=current_approval.id if current_approval is not None else None,
            approval_status=current_approval.status if current_approval is not None else None,
            selected_product_id=current_selection.id if current_selection is not None else None,
            selected_product_status=(
                current_selection.status if current_selection is not None else None
            ),
            validation_status=(
                current_selection.validation_status if current_selection is not None else None
            ),
            initiative_id=current_initiative.id if current_initiative is not None else None,
            initiative_status=(
                current_initiative.status if current_initiative is not None else None
            ),
            milestones=milestones,
            launch_review_id=current_review.id if current_review is not None else None,
            launch_review_status=current_review.status if current_review is not None else None,
        )
        updated_at = max(
            item.updated_at
            for item in (
                project,
                run,
                current_approval,
                current_selection,
                current_initiative,
                current_review,
            )
            if item is not None
        )
        items.append(
            ProjectLifecycleRead(
                project_id=project.id,
                project_name=project.name,
                category=project.category,
                target_market=project.target_market,
                project_status=project.status,
                run_id=run.id if run is not None else None,
                run_status=run.status if run is not None else None,
                approval_task_id=(
                    current_approval.id if current_approval is not None else None
                ),
                approval_status=(
                    current_approval.status if current_approval is not None else None
                ),
                selected_product_id=(
                    current_selection.id if current_selection is not None else None
                ),
                selected_product_name=(
                    current_selection.name if current_selection is not None else None
                ),
                selected_product_status=(
                    current_selection.status if current_selection is not None else None
                ),
                validation_status=(
                    current_selection.validation_status
                    if current_selection is not None
                    else None
                ),
                initiative_id=(
                    current_initiative.id if current_initiative is not None else None
                ),
                initiative_status=(
                    current_initiative.status if current_initiative is not None else None
                ),
                launch_review_id=current_review.id if current_review is not None else None,
                launch_review_status=(
                    current_review.status if current_review is not None else None
                ),
                current_milestone_id=state.current_milestone_id,
                current_milestone_label=state.current_milestone_label,
                current_milestone_status=state.current_milestone_status,
                stage=state.stage,
                stage_label=state.stage_label,
                progress_percent=state.progress_percent,
                health=state.health,
                blockers=list(state.blockers),
                next_action_label=state.next_action_label,
                next_action_type=state.next_action_type,
                next_action_id=state.next_action_id,
                stages=[
                    ProjectLifecycleStageRead(
                        key=stage.key,
                        label=stage.label,
                        status=stage.status,
                        detail=stage.detail,
                        entity_id=stage.entity_id,
                    )
                    for stage in state.stages
                ],
                updated_at=updated_at,
            )
        )

    response.headers["X-Total-Count"] = str(total)
    return ProjectLifecyclePage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        summary=summary,
    )


@router.get("/opportunities", response_model=list[OpportunitySummary])
async def list_opportunities(
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> list[OpportunitySummary]:
    """处理`GET /opportunities`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    latest_run_id = (
        select(PlanningRun.id)
        .where(PlanningRun.project_id == PlanningProject.id)
        .order_by(PlanningRun.created_at.desc(), PlanningRun.id.desc())
        .limit(1)
        .correlate(PlanningProject)
        .scalar_subquery()
    )
    rows = (
        await session.execute(
            select(PlanningProject, PlanningRun)
            .outerjoin(PlanningRun, PlanningRun.id == latest_run_id)
            .where(
                PlanningProject.tenant_id == identity.tenant_id,
                PlanningProject.archived_at.is_(None),
            )
            .order_by(PlanningProject.updated_at.desc(), PlanningProject.id.desc())
        )
    ).all()
    return [_opportunity_summary(project, run) for project, run in rows]
