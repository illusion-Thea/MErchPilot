"""文件职责：提供规划报告生成、状态查询和文件下载接口。"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from merchpilot.adapters.storage import get_object_storage_provider
from merchpilot.api.dependencies import get_current_identity, require_planner
from merchpilot.api.schemas import PlanningReportPage, PlanningReportRead
from merchpilot.core.ids import new_id
from merchpilot.domain.enums import ReportStatus
from merchpilot.infrastructure.database import get_db_session
from merchpilot.infrastructure.models import PlanningProject, PlanningReport, PlanningRun
from merchpilot.ports.identity import Identity
from merchpilot.services.audit import record_audit_event
from merchpilot.workers.tasks import generate_planning_report

router = APIRouter(tags=["planning-reports"])


@router.post(
    "/planning-projects/{project_id}/runs/{run_id}/reports",
    response_model=PlanningReportRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_planning_report(
    project_id: str,
    run_id: str,
    identity: Identity = Depends(require_planner),
    session: AsyncSession = Depends(get_db_session),
) -> PlanningReport:
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
    if run.result_snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="规划任务尚无可导出的结果快照",
        )
    project = await session.scalar(
        select(PlanningProject).where(
            PlanningProject.id == project_id,
            PlanningProject.tenant_id == identity.tenant_id,
        )
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="planning project not found")
    existing = await session.scalar(
        select(PlanningReport)
        .where(
            PlanningReport.run_id == run_id,
            PlanningReport.status.in_([ReportStatus.QUEUED.value, ReportStatus.PROCESSING.value]),
        )
        .order_by(PlanningReport.created_at.desc())
        .limit(1)
    )
    if existing is not None:
        return existing

    report = PlanningReport(
        id=new_id("report"),
        project_id=project_id,
        run_id=run_id,
        format="xlsx",
        status=ReportStatus.QUEUED.value,
        created_by=identity.user_id,
    )
    session.add(report)
    record_audit_event(
        session,
        action="report.queued",
        entity_type="planning_report",
        entity_id=report.id,
        project_id=project.id,
        tenant_id=project.tenant_id,
        actor_id=identity.user_id,
        detail={"run_id": run.id, "format": report.format},
    )
    await session.commit()
    await session.refresh(report)
    try:
        task = generate_planning_report.delay(report.id)
    except Exception as exc:
        report.status = ReportStatus.FAILED.value
        report.error_message = f"无法提交报告生成任务: {exc}"
        record_audit_event(
            session,
            action="report.dispatch_failed",
            entity_type="planning_report",
            entity_id=report.id,
            project_id=project.id,
            tenant_id=project.tenant_id,
            actor_id="system",
            detail={"error": str(exc)},
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="报告生成队列暂不可用",
        ) from exc
    report.celery_task_id = task.id
    await session.commit()
    await session.refresh(report)
    return report


@router.get(
    "/planning-projects/{project_id}/runs/{run_id}/reports",
    response_model=list[PlanningReportRead],
)
async def list_planning_reports(
    project_id: str,
    run_id: str,
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> list[PlanningReport]:
    """处理该接口。

    执行身份、租户、参数和业务状态校验后返回类型化响应。
    """
    run_exists = await session.scalar(
        select(PlanningRun.id)
        .join(PlanningProject, PlanningProject.id == PlanningRun.project_id)
        .where(
            PlanningRun.id == run_id,
            PlanningRun.project_id == project_id,
            PlanningProject.tenant_id == identity.tenant_id,
        )
    )
    if run_exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="planning run not found")
    reports = await session.scalars(
        select(PlanningReport)
        .where(
            PlanningReport.project_id == project_id,
            PlanningReport.run_id == run_id,
        )
        .order_by(PlanningReport.created_at.desc())
    )
    return list(reports.all())


@router.get(
    "/planning-projects/{project_id}/runs/{run_id}/reports/page",
    response_model=PlanningReportPage,
)
async def page_planning_reports(
    project_id: str,
    run_id: str,
    response: Response,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=5, ge=1, le=100),
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    """处理该接口。

    执行身份、租户、参数和业务状态校验后返回类型化响应。
    """
    run_exists = await session.scalar(
        select(PlanningRun.id)
        .join(PlanningProject, PlanningProject.id == PlanningRun.project_id)
        .where(
            PlanningRun.id == run_id,
            PlanningRun.project_id == project_id,
            PlanningProject.tenant_id == identity.tenant_id,
        )
    )
    if run_exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="planning run not found")
    conditions = [
        PlanningReport.project_id == project_id,
        PlanningReport.run_id == run_id,
    ]
    total = int(await session.scalar(select(func.count(PlanningReport.id)).where(*conditions)) or 0)
    reports = await session.scalars(
        select(PlanningReport)
        .where(*conditions)
        .order_by(PlanningReport.created_at.desc(), PlanningReport.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    response.headers["X-Total-Count"] = str(total)
    return {
        "items": list(reports),
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/planning-reports/{report_id}", response_model=PlanningReportRead)
async def get_planning_report(
    report_id: str,
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> PlanningReport:
    """处理`GET /planning-reports/{report_id}`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    report = await session.scalar(
        select(PlanningReport)
        .join(PlanningProject, PlanningProject.id == PlanningReport.project_id)
        .where(
            PlanningReport.id == report_id,
            PlanningProject.tenant_id == identity.tenant_id,
        )
    )
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="planning report not found")
    return report


@router.get("/planning-reports/{report_id}/download")
async def download_planning_report(
    report_id: str,
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """处理该接口。

    执行身份、租户、参数和业务状态校验后返回类型化响应。
    """
    report = await session.scalar(
        select(PlanningReport)
        .join(PlanningProject, PlanningProject.id == PlanningReport.project_id)
        .where(
            PlanningReport.id == report_id,
            PlanningProject.tenant_id == identity.tenant_id,
        )
    )
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="planning report not found")
    if report.status != ReportStatus.COMPLETED.value or report.storage_key is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="规划报告尚未生成完成")
    project = await session.scalar(
        select(PlanningProject).where(
            PlanningProject.id == report.project_id,
            PlanningProject.tenant_id == identity.tenant_id,
        )
    )
    try:
        content = await get_object_storage_provider().get_object(report.storage_key)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="规划报告文件不存在") from exc
    filename = f"{project.name if project is not None else report.project_id}_商品规划报告.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )
