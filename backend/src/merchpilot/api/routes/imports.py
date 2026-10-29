"""文件职责：提供数据导入、质量治理、重复审核和索引管理接口。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import and_, case, delete, func, literal, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import Subquery

from merchpilot.adapters.storage import get_object_storage_provider
from merchpilot.api.dependencies import get_current_identity, require_planner
from merchpilot.api.schemas import (
    DataCoverageRead,
    DataDuplicateGroupPage,
    DataDuplicateGroupPageSummary,
    DataDuplicateGroupRead,
    DataDuplicateGroupRecordPage,
    DataDuplicateGroupSummaryRead,
    DataDuplicateRecordRead,
    DataDuplicateReviewRead,
    DataDuplicateReviewUpsert,
    DataImportComparisonRead,
    DataImportPage,
    DataImportPageSummary,
    DataImportQualityImportRead,
    DataImportQualitySummary,
    DataImportRead,
    DataImportReindexRead,
    EvidenceQualityIssueSummaryItem,
    EvidenceQualityIssueSummaryRead,
    EvidenceQualityReviewRequest,
    EvidenceRecordPage,
    EvidenceRecordRead,
)
from merchpilot.core.config import get_settings
from merchpilot.core.ids import new_id
from merchpilot.core.logging import get_logger
from merchpilot.domain.enums import EvidenceIndexStatus, EvidenceQualityStatus, ImportStatus
from merchpilot.infrastructure.database import get_db_session
from merchpilot.infrastructure.milvus import MilvusVectorStore
from merchpilot.infrastructure.models import DataImportJob, EvidenceDuplicateReview, EvidenceRecord
from merchpilot.ports.identity import Identity
from merchpilot.services.audit import record_audit_event
from merchpilot.services.data_collection_template import (
    DATA_COLLECTION_SCHEMA_VERSION,
    DATA_COLLECTION_TEMPLATE_FILENAME,
    build_data_collection_template,
)
from merchpilot.services.import_analysis import (
    compare_import_records,
    duplicate_candidate_fingerprint,
    evidence_snapshot,
    find_duplicate_groups,
)
from merchpilot.services.import_quality import build_import_quality_report_bytes
from merchpilot.services.multimodal_import import is_supported_filename, source_type_for_filename
from merchpilot.services.tabular_import import safe_storage_filename
from merchpilot.workers.tasks import index_evidence_batch, process_tabular_import

router = APIRouter(prefix="/data-imports", tags=["data-imports"])
settings = get_settings()
logger = get_logger("data_imports")
allowed_suffixes = {".csv", ".xlsx", ".xlsm"}
duplicate_match_types = {"source_id", "content_hash"}


def _normalized_metadata_value(record_model: Any, path: str) -> ColumnElement[str | None]:
    """读取 JSONB 点路径中的文本值，并把空字符串和 JSON null 归一为空。"""
    expression = record_model.metadata_json
    for key in path.removeprefix("$.").split("."):
        expression = expression[key]
    raw_value = expression.as_string()
    return cast(ColumnElement[str | None], func.nullif(func.nullif(raw_value, ""), "null"))


def _duplicate_record_conditions(
    record_model: Any,
    tenant_id: str,
    match_type: str,
    match_value: str,
) -> list[ColumnElement[bool]]:
    """内部辅助函数`_duplicate_record_conditions`；拆分主流程并集中处理当前模块的边界条件。"""
    conditions: list[ColumnElement[bool]] = [record_model.tenant_id == tenant_id]
    if match_type == "source_id":
        conditions.extend(
            [
                _normalized_metadata_value(
                    record_model,
                    "$.normalized_row.source_id",
                ).is_not(None),
                record_model.source_id == match_value,
            ]
        )
    elif match_type == "content_hash":
        conditions.extend(
            [
                record_model.content_hash.is_not(None),
                record_model.content_hash != "",
                record_model.content_hash == match_value,
            ]
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid duplicate match type",
        )
    return conditions


def _duplicate_candidates_query(tenant_id: str) -> Subquery:
    """内部辅助函数`_duplicate_candidates_query`；拆分主流程并集中处理当前模块的边界条件。"""
    explicit_source_id = _normalized_metadata_value(
        EvidenceRecord,
        "$.normalized_row.source_id",
    )
    source_candidates = (
        select(
            literal("source_id").label("match_type"),
            EvidenceRecord.source_id.label("match_value"),
            func.count(EvidenceRecord.id).label("record_count"),
            func.count(func.distinct(EvidenceRecord.import_job_id)).label("import_count"),
        )
        .where(
            EvidenceRecord.tenant_id == tenant_id,
            explicit_source_id.is_not(None),
        )
        .group_by(EvidenceRecord.source_id)
        .having(func.count(EvidenceRecord.id) >= 2)
    )
    content_candidates = (
        select(
            literal("content_hash").label("match_type"),
            EvidenceRecord.content_hash.label("match_value"),
            func.count(EvidenceRecord.id).label("record_count"),
            func.count(func.distinct(EvidenceRecord.import_job_id)).label("import_count"),
        )
        .where(
            EvidenceRecord.tenant_id == tenant_id,
            EvidenceRecord.content_hash.is_not(None),
            EvidenceRecord.content_hash != "",
        )
        .group_by(EvidenceRecord.content_hash)
        .having(func.count(EvidenceRecord.id) >= 2)
    )
    return source_candidates.union_all(content_candidates).subquery()


def _active_duplicate_review_condition(
    candidates: Subquery,
    tenant_id: str,
) -> ColumnElement[bool]:
    """内部辅助函数`_active_duplicate_review_condition`；拆分主流程并集中处理当前模块的边界条件。"""
    check_record = aliased(EvidenceRecord)
    current_record_matches = or_(
        and_(
            candidates.c.match_type == "source_id",
            _normalized_metadata_value(
                check_record,
                "$.normalized_row.source_id",
            ).is_not(None),
            check_record.source_id == candidates.c.match_value,
        ),
        and_(
            candidates.c.match_type == "content_hash",
            check_record.content_hash == candidates.c.match_value,
        ),
    )
    missing_current_record = (
        select(check_record.id)
        .where(
            check_record.tenant_id == tenant_id,
            current_record_matches,
            ~EvidenceDuplicateReview.candidate_evidence_ids.contains(
                func.jsonb_build_array(check_record.id)
            ),
        )
        .correlate(candidates, EvidenceDuplicateReview)
        .exists()
    )
    return and_(
        EvidenceDuplicateReview.id.is_not(None),
        EvidenceDuplicateReview.candidate_evidence_ids.is_not(None),
        func.jsonb_array_length(EvidenceDuplicateReview.candidate_evidence_ids)
        == candidates.c.record_count,
        ~missing_current_record,
    )


async def _active_duplicate_review(
    session: AsyncSession,
    tenant_id: str,
    match_type: str,
    match_value: str,
    record_count: int,
) -> EvidenceDuplicateReview | None:
    """内部辅助函数`_active_duplicate_review`；拆分主流程并集中处理当前模块的边界条件。"""
    review = await session.scalar(
        select(EvidenceDuplicateReview).where(
            EvidenceDuplicateReview.tenant_id == tenant_id,
            EvidenceDuplicateReview.match_type == match_type,
            EvidenceDuplicateReview.match_value == match_value,
        )
    )
    if review is None:
        return None
    candidate_ids = review.candidate_evidence_ids
    if not isinstance(candidate_ids, list) or len(candidate_ids) != record_count:
        return None
    normalized_ids = [str(candidate_id) for candidate_id in candidate_ids if candidate_id]
    if len(normalized_ids) != record_count:
        return None
    if review.candidate_fingerprint != duplicate_candidate_fingerprint(normalized_ids):
        return None
    current_ids = list(
        await session.scalars(
            select(EvidenceRecord.id).where(
                *_duplicate_record_conditions(
                    EvidenceRecord,
                    tenant_id,
                    match_type,
                    match_value,
                )
            )
        )
    )
    return review if set(current_ids) == set(normalized_ids) else None


def _duplicate_record_payload(record: EvidenceRecord) -> DataDuplicateRecordRead:
    """内部辅助函数`_duplicate_record_payload`；拆分主流程并集中处理当前模块的边界条件。"""
    snapshot = evidence_snapshot(record)
    return DataDuplicateRecordRead(
        evidence_id=snapshot.evidence_id,
        source_id=snapshot.source_id,
        import_job_id=snapshot.import_job_id,
        source_name=snapshot.source_name,
        source_row=snapshot.source_row,
        quality_status=snapshot.quality_status,
        observed_at=record.observed_at,
        content_preview=snapshot.content_preview,
    )


async def _get_import_index_stats(
    session: AsyncSession,
    tenant_id: str,
    import_ids: list[str],
) -> dict[str, dict[str, int]]:
    """内部辅助函数`_get_import_index_stats`；拆分主流程并集中处理当前模块的边界条件。"""
    if not import_ids:
        return {}

    non_blocked = EvidenceRecord.quality_status != EvidenceQualityStatus.BLOCKED.value
    rows = (
        await session.execute(
            select(
                EvidenceRecord.import_job_id,
                func.coalesce(func.sum(case((non_blocked, 1), else_=0)), 0),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                non_blocked
                                & (EvidenceRecord.index_status == EvidenceIndexStatus.INDEXED.value),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                non_blocked
                                & EvidenceRecord.index_status.in_(
                                    [
                                        EvidenceIndexStatus.PENDING.value,
                                        EvidenceIndexStatus.INDEXING.value,
                                    ]
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                non_blocked
                                & (EvidenceRecord.index_status == EvidenceIndexStatus.FAILED.value),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
            )
            .where(
                EvidenceRecord.tenant_id == tenant_id,
                EvidenceRecord.import_job_id.in_(import_ids),
            )
            .group_by(EvidenceRecord.import_job_id)
        )
    ).all()
    return {
        row[0]: {
            "indexable_rows": int(row[1]),
            "indexed_rows": int(row[2]),
            "pending_index_rows": int(row[3]),
            "failed_index_rows": int(row[4]),
        }
        for row in rows
        if row[0] is not None
    }


def _data_import_payload(job: DataImportJob, stats: dict[str, int]) -> dict[str, object]:
    """内部辅助函数`_data_import_payload`；拆分主流程并集中处理当前模块的边界条件。"""
    indexable_rows = stats.get("indexable_rows", 0)
    indexed_rows = stats.get("indexed_rows", 0)
    pending_index_rows = stats.get("pending_index_rows", 0)
    failed_index_rows = stats.get("failed_index_rows", 0)
    if job.status == ImportStatus.COMPLETED.value and failed_index_rows > 0:
        retrieval_status = "failed"
    elif job.status in {ImportStatus.QUEUED.value, ImportStatus.PROCESSING.value} or pending_index_rows > 0:
        retrieval_status = "indexing"
    elif job.status == ImportStatus.COMPLETED.value and indexable_rows == 0:
        retrieval_status = "empty"
    elif job.status == ImportStatus.COMPLETED.value and indexed_rows == indexable_rows:
        retrieval_status = "ready"
    else:
        retrieval_status = "unavailable"

    payload = DataImportRead.model_validate(job).model_dump()
    payload.update(
        {
            "indexable_rows": indexable_rows,
            "indexed_rows": indexed_rows,
            "pending_index_rows": pending_index_rows,
            "failed_index_rows": failed_index_rows,
            "retrieval_status": retrieval_status,
            "retrieval_ready": retrieval_status == "ready",
        }
    )
    return payload


async def _create_file_import(
    file: UploadFile = File(...),
    *,
    tabular_only: bool,
    identity: Identity = Depends(require_planner),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    """保存上传文件并提交统一的解析任务。"""
    filename = safe_storage_filename(file.filename or "upload")
    suffix = Path(filename).suffix.lower()
    if not is_supported_filename(filename) or (tabular_only and suffix not in allowed_suffixes):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "仅支持 CSV、XLSX 和 XLSM 文件"
                if tabular_only
                else "支持 CSV、XLSX、XLSM、PDF、PPTX、DOCX 和常见图片文件"
            ),
        )

    content = await file.read(settings.max_import_file_bytes + 1)
    await file.close()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件不能为空")
    if len(content) > settings.max_import_file_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="上传文件超过大小限制",
        )

    import_id = new_id("import")
    storage_key = f"imports/{import_id}/{filename}"
    storage = get_object_storage_provider()
    await storage.put_object(
        storage_key,
        content,
        file.content_type or "application/octet-stream",
    )
    source_type = source_type_for_filename(filename)
    job = DataImportJob(
        id=import_id,
        tenant_id=identity.tenant_id,
        filename=filename,
        storage_key=storage_key,
        source_type=source_type,
        status=ImportStatus.QUEUED.value,
        created_by=identity.user_id,
    )
    try:
        session.add(job)
        record_audit_event(
            session,
            action="import.created",
            entity_type="data_import",
            entity_id=job.id,
            tenant_id=job.tenant_id,
            actor_id=job.created_by,
            detail={"filename": filename, "source_type": job.source_type},
        )
        await session.commit()
        await session.refresh(job)
    except Exception:
        await session.rollback()
        await storage.delete_object(storage_key)
        raise

    try:
        task = process_tabular_import.delay(job.id)
    except Exception as exc:
        job.status = ImportStatus.FAILED.value
        job.error_message = f"无法提交导入任务: {exc}"
        record_audit_event(
            session,
            action="import.dispatch_failed",
            entity_type="data_import",
            entity_id=job.id,
            tenant_id=job.tenant_id,
            actor_id="system",
            detail={"error": str(exc)},
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=job.error_message,
        ) from exc
    job.celery_task_id = task.id
    await session.commit()
    await session.refresh(job)
    stats = await _get_import_index_stats(session, identity.tenant_id, [job.id])
    return _data_import_payload(job, stats.get(job.id, {}))


@router.post("/tabular", response_model=DataImportRead, status_code=status.HTTP_202_ACCEPTED)
async def create_tabular_import(
    file: UploadFile = File(...),
    identity: Identity = Depends(require_planner),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    """兼容旧接口，仅接收 CSV/XLSX/XLSM。"""
    return await _create_file_import(
        file,
        tabular_only=True,
        identity=identity,
        session=session,
    )


@router.post("/files", response_model=DataImportRead, status_code=status.HTTP_202_ACCEPTED)
async def create_file_import(
    file: UploadFile = File(...),
    identity: Identity = Depends(require_planner),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    """接收表格、PDF、PPTX、DOCX 和图片，统一进入证据解析链路。"""
    return await _create_file_import(
        file,
        tabular_only=False,
        identity=identity,
        session=session,
    )


@router.get("/template")
async def download_data_collection_template(
) -> Response:
    """处理`GET /template`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    encoded_filename = quote(DATA_COLLECTION_TEMPLATE_FILENAME)
    return Response(
        content=build_data_collection_template(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            "X-Collection-Schema-Version": DATA_COLLECTION_SCHEMA_VERSION,
        },
    )


@router.get("/quality-summary", response_model=DataImportQualitySummary)
async def get_data_import_quality_summary(
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> DataImportQualitySummary:
    """处理`GET /quality-summary`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    import_metrics = (
        await session.execute(
            select(
                func.count(DataImportJob.id),
                func.coalesce(
                    func.sum(
                        case(
                            (DataImportJob.status == ImportStatus.COMPLETED.value, 1),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (DataImportJob.status == ImportStatus.FAILED.value, 1),
                            else_=0,
                        )
                    ),
                    0,
                ),
            ).where(DataImportJob.tenant_id == identity.tenant_id)
        )
    ).one()
    evidence_metrics = (
        await session.execute(
            select(
                func.count(EvidenceRecord.id),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                EvidenceRecord.quality_status == EvidenceQualityStatus.VERIFIED.value,
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                EvidenceRecord.quality_status == EvidenceQualityStatus.WARNING.value,
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                EvidenceRecord.quality_status == EvidenceQualityStatus.BLOCKED.value,
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                EvidenceRecord.index_status == EvidenceIndexStatus.INDEXED.value,
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                EvidenceRecord.index_status.in_(
                                    [
                                        EvidenceIndexStatus.PENDING.value,
                                        EvidenceIndexStatus.INDEXING.value,
                                    ]
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                (EvidenceRecord.index_status == EvidenceIndexStatus.FAILED.value)
                                & (EvidenceRecord.quality_status != EvidenceQualityStatus.BLOCKED.value),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
            ).where(EvidenceRecord.tenant_id == identity.tenant_id)
        )
    ).one()
    warning_count = func.sum(
        case(
            (EvidenceRecord.quality_status == EvidenceQualityStatus.WARNING.value, 1),
            else_=0,
        )
    )
    blocked_count = func.sum(
        case(
            (EvidenceRecord.quality_status == EvidenceQualityStatus.BLOCKED.value, 1),
            else_=0,
        )
    )
    failed_index_count = func.sum(
        case(
            (
                (EvidenceRecord.index_status == EvidenceIndexStatus.FAILED.value)
                & (EvidenceRecord.quality_status != EvidenceQualityStatus.BLOCKED.value),
                1,
            ),
            else_=0,
        )
    )
    problem_metrics = (
        select(
            EvidenceRecord.import_job_id.label("import_id"),
            warning_count.label("warning_records"),
            blocked_count.label("blocked_records"),
            failed_index_count.label("failed_index_records"),
        )
        .where(
            EvidenceRecord.tenant_id == identity.tenant_id,
            EvidenceRecord.import_job_id.is_not(None),
        )
        .group_by(EvidenceRecord.import_job_id)
        .having(or_(warning_count > 0, blocked_count > 0, failed_index_count > 0))
        .subquery()
    )
    problem_import_total = int(
        await session.scalar(select(func.count()).select_from(problem_metrics)) or 0
    )
    problem_import_rows = (
        await session.execute(
            select(
                DataImportJob.id,
                DataImportJob.filename,
                DataImportJob.created_at,
                problem_metrics.c.warning_records,
                problem_metrics.c.blocked_records,
                problem_metrics.c.failed_index_records,
            )
            .join(problem_metrics, problem_metrics.c.import_id == DataImportJob.id)
            .where(DataImportJob.tenant_id == identity.tenant_id)
            .order_by(
                (
                    problem_metrics.c.warning_records
                    + problem_metrics.c.blocked_records
                    + problem_metrics.c.failed_index_records
                ).desc(),
                DataImportJob.created_at.desc(),
                DataImportJob.id.desc(),
            )
            .limit(10)
        )
    ).all()
    problem_imports = [
        DataImportQualityImportRead(
            import_id=str(import_id),
            filename=str(filename),
            created_at=created_at,
            warning_records=int(warning_records or 0),
            blocked_records=int(blocked_records or 0),
            failed_index_records=int(failed_index_records or 0),
        )
        for (
            import_id,
            filename,
            created_at,
            warning_records,
            blocked_records,
            failed_index_records,
        ) in problem_import_rows
    ]
    return DataImportQualitySummary(
        total_imports=int(import_metrics[0] or 0),
        completed_imports=int(import_metrics[1] or 0),
        failed_imports=int(import_metrics[2] or 0),
        total_records=int(evidence_metrics[0] or 0),
        verified_records=int(evidence_metrics[1] or 0),
        warning_records=int(evidence_metrics[2] or 0),
        blocked_records=int(evidence_metrics[3] or 0),
        indexed_records=int(evidence_metrics[4] or 0),
        pending_index_records=int(evidence_metrics[5] or 0),
        failed_index_records=int(evidence_metrics[6] or 0),
        problem_import_total=problem_import_total,
        problem_imports=problem_imports,
    )


@router.get("/coverage", response_model=DataCoverageRead)
async def get_data_coverage(
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> DataCoverageRead:
    """处理`GET /coverage`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    tenant_condition = EvidenceRecord.tenant_id == identity.tenant_id
    normalized_source_id = _normalized_metadata_value(
        EvidenceRecord,
        "$.normalized_row.source_id",
    )
    metrics = (
        await session.execute(
            select(
                func.count(EvidenceRecord.id),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                EvidenceRecord.quality_status
                                == EvidenceQualityStatus.VERIFIED.value,
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(case((EvidenceRecord.observed_at.is_not(None), 1), else_=0)),
                    0,
                ),
                func.coalesce(
                    func.sum(case((normalized_source_id.is_not(None), 1), else_=0)),
                    0,
                ),
            ).where(tenant_condition)
        )
    ).one()

    async def dimension_counts(path: str, fallback: str) -> dict[str, int]:
        """实现`dimension_counts`接口辅助流程，供当前路由复用权限与状态判断。"""
        raw_value = _normalized_metadata_value(EvidenceRecord, path)
        label = func.coalesce(raw_value, fallback)
        rows = (
            await session.execute(
                select(label, func.count(EvidenceRecord.id))
                .where(tenant_condition)
                .group_by(label)
                .order_by(func.count(EvidenceRecord.id).desc(), label.asc())
                .limit(20)
            )
        ).all()
        return {str(value): int(count) for value, count in rows}

    total_records = int(metrics[0] or 0)
    verified_records = int(metrics[1] or 0)
    dated_records = int(metrics[2] or 0)
    source_id_records = int(metrics[3] or 0)
    return DataCoverageRead(
        total_records=total_records,
        verified_records=verified_records,
        dated_records=dated_records,
        source_id_records=source_id_records,
        date_coverage_rate=dated_records / total_records if total_records else 0.0,
        source_id_coverage_rate=source_id_records / total_records if total_records else 0.0,
        data_type_counts=await dimension_counts("$.normalized_row.data_type", "未分类"),
        category_counts=await dimension_counts("$.normalized_row.category", "未填写"),
        target_market_counts=await dimension_counts("$.normalized_row.target_market", "未填写"),
    )


@router.get("/duplicates/page", response_model=DataDuplicateGroupPage)
async def page_duplicate_evidence_groups(
    response: Response,
    review_status: str = Query(default="pending", alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=6, ge=1, le=50),
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> DataDuplicateGroupPage:
    """处理`GET /duplicates/page`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    if review_status not in {"pending", "reviewed", "all"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid duplicate review status",
        )
    candidates = _duplicate_candidates_query(identity.tenant_id)
    review_join = and_(
        EvidenceDuplicateReview.tenant_id == identity.tenant_id,
        EvidenceDuplicateReview.match_type == candidates.c.match_type,
        EvidenceDuplicateReview.match_value == candidates.c.match_value,
    )
    active_review = _active_duplicate_review_condition(candidates, identity.tenant_id)
    reviewed_total = int(
        await session.scalar(
            select(func.count())
            .select_from(candidates)
            .outerjoin(EvidenceDuplicateReview, review_join)
            .where(active_review)
        )
        or 0
    )
    all_total = int(await session.scalar(select(func.count()).select_from(candidates)) or 0)
    filtered_condition = None
    if review_status == "pending":
        filtered_condition = ~active_review
    elif review_status == "reviewed":
        filtered_condition = active_review

    total_query = (
        select(func.count())
        .select_from(candidates)
        .outerjoin(EvidenceDuplicateReview, review_join)
    )
    if filtered_condition is not None:
        total_query = total_query.where(filtered_condition)
    total = int(await session.scalar(total_query) or 0)

    item_query = (
        select(
            candidates.c.match_type,
            candidates.c.match_value,
            candidates.c.record_count,
            candidates.c.import_count,
            EvidenceDuplicateReview,
            active_review.label("has_active_review"),
        )
        .select_from(candidates)
        .outerjoin(EvidenceDuplicateReview, review_join)
    )
    if filtered_condition is not None:
        item_query = item_query.where(filtered_condition)
    rows = (
        await session.execute(
            item_query
            .order_by(
                candidates.c.record_count.desc(),
                candidates.c.match_type.asc(),
                candidates.c.match_value.asc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    items: list[DataDuplicateGroupSummaryRead] = []
    for match_type, match_value, record_count, import_count, review, has_active_review in rows:
        preview_records = list(
            await session.scalars(
                select(EvidenceRecord)
                .where(
                    *_duplicate_record_conditions(
                        EvidenceRecord,
                        identity.tenant_id,
                        str(match_type),
                        str(match_value),
                    )
                )
                .order_by(EvidenceRecord.id.asc())
                .limit(2)
            )
        )
        items.append(
            DataDuplicateGroupSummaryRead(
                match_type=str(match_type),
                match_value=str(match_value),
                record_count=int(record_count),
                import_count=int(import_count),
                records=[_duplicate_record_payload(record) for record in preview_records],
                review=DataDuplicateReviewRead.model_validate(review)
                if review is not None and has_active_review
                else None,
            )
        )

    response.headers["X-Total-Count"] = str(total)
    return DataDuplicateGroupPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        summary=DataDuplicateGroupPageSummary(
            total=all_total,
            pending=max(0, all_total - reviewed_total),
            reviewed=reviewed_total,
        ),
    )


@router.get("/duplicates/group", response_model=DataDuplicateGroupRecordPage)
async def get_duplicate_evidence_group(
    match_type: str = Query(),
    match_value: str = Query(min_length=1, max_length=512),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> DataDuplicateGroupRecordPage:
    """处理`GET /duplicates/group`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    if match_type not in duplicate_match_types:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid duplicate match type",
        )
    conditions = _duplicate_record_conditions(
        EvidenceRecord,
        identity.tenant_id,
        match_type,
        match_value,
    )
    record_count, import_count = (
        await session.execute(
            select(
                func.count(EvidenceRecord.id),
                func.count(func.distinct(EvidenceRecord.import_job_id)),
            ).where(*conditions)
        )
    ).one()
    normalized_record_count = int(record_count or 0)
    if normalized_record_count < 2:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="重复候选不存在或已不再满足重复条件",
        )
    records = list(
        await session.scalars(
            select(EvidenceRecord)
            .where(*conditions)
            .order_by(EvidenceRecord.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    review = await _active_duplicate_review(
        session,
        identity.tenant_id,
        match_type,
        match_value,
        normalized_record_count,
    )
    canonical_record: DataDuplicateRecordRead | None = None
    if review is not None and review.canonical_evidence_id:
        canonical = await session.scalar(
            select(EvidenceRecord).where(
                *conditions,
                EvidenceRecord.id == review.canonical_evidence_id,
            )
        )
        if canonical is not None:
            canonical_record = _duplicate_record_payload(canonical)
    return DataDuplicateGroupRecordPage(
        match_type=match_type,
        match_value=match_value,
        record_count=normalized_record_count,
        import_count=int(import_count or 0),
        items=[_duplicate_record_payload(record) for record in records],
        page=page,
        page_size=page_size,
        review=DataDuplicateReviewRead.model_validate(review) if review is not None else None,
        canonical_record=canonical_record,
    )


@router.get("/duplicates", response_model=list[DataDuplicateGroupRead])
async def list_duplicate_evidence_groups(
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> list[DataDuplicateGroupRead]:
    """处理`GET /duplicates`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    records = list(
        await session.scalars(select(EvidenceRecord).where(EvidenceRecord.tenant_id == identity.tenant_id))
    )
    reviews = list(
        await session.scalars(
            select(EvidenceDuplicateReview).where(
                EvidenceDuplicateReview.tenant_id == identity.tenant_id
            )
        )
    )
    reviews_by_match = {
        (review.match_type, review.match_value): review
        for review in reviews
    }
    return [
        DataDuplicateGroupRead.model_validate(
            {
                **item,
                "review": (
                    review
                    if (
                        review := reviews_by_match.get((item["match_type"], item["match_value"]))
                    )
                    and review.candidate_fingerprint == item["candidate_fingerprint"]
                    else None
                ),
            }
        )
        for item in find_duplicate_groups(records)
    ]


@router.put("/duplicates/review", response_model=DataDuplicateReviewRead)
async def review_duplicate_evidence_group(
    payload: DataDuplicateReviewUpsert,
    identity: Identity = Depends(require_planner),
    session: AsyncSession = Depends(get_db_session),
) -> EvidenceDuplicateReview:
    """处理`PUT /duplicates/review`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    if payload.match_type not in duplicate_match_types:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid duplicate match type",
        )
    records = list(
        await session.scalars(
            select(EvidenceRecord).where(
                *_duplicate_record_conditions(
                    EvidenceRecord,
                    identity.tenant_id,
                    payload.match_type,
                    payload.match_value,
                )
            )
        )
    )
    group = next(
        (
            item
            for item in find_duplicate_groups(records)
            if item["match_type"] == payload.match_type and item["match_value"] == payload.match_value
        ),
        None,
    )
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="重复候选不存在或已不再满足重复条件",
        )
    if (
        payload.canonical_evidence_id is not None
        and payload.canonical_evidence_id not in group["evidence_ids"]
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="所选主记录不属于当前重复候选组",
        )

    review = await session.scalar(
        select(EvidenceDuplicateReview)
        .where(
            EvidenceDuplicateReview.tenant_id == identity.tenant_id,
            EvidenceDuplicateReview.match_type == payload.match_type,
            EvidenceDuplicateReview.match_value == payload.match_value,
        )
        .with_for_update()
    )
    previous_decision = review.decision if review is not None else None
    reviewed_at = datetime.now(UTC)
    notes = payload.notes.strip() if payload.notes and payload.notes.strip() else None
    if review is None:
        review = EvidenceDuplicateReview(
            id=new_id("duplicate_review"),
            tenant_id=identity.tenant_id,
            match_type=payload.match_type,
            match_value=payload.match_value,
            candidate_fingerprint=group["candidate_fingerprint"],
            candidate_evidence_ids=group["evidence_ids"],
            decision=payload.decision.value,
            canonical_evidence_id=payload.canonical_evidence_id,
            notes=notes,
            reviewed_by=identity.user_id,
            reviewed_at=reviewed_at,
        )
        session.add(review)
    else:
        review.candidate_fingerprint = group["candidate_fingerprint"]
        review.candidate_evidence_ids = group["evidence_ids"]
        review.decision = payload.decision.value
        review.canonical_evidence_id = payload.canonical_evidence_id
        review.notes = notes
        review.reviewed_by = identity.user_id
        review.reviewed_at = reviewed_at

    record_audit_event(
        session,
        action="duplicate.reviewed",
        entity_type="evidence_duplicate_review",
        entity_id=review.id,
        tenant_id=identity.tenant_id,
        actor_id=identity.user_id,
        detail={
            "match_type": payload.match_type,
            "match_value": payload.match_value,
            "decision": payload.decision.value,
            "previous_decision": previous_decision,
            "canonical_evidence_id": payload.canonical_evidence_id,
            "record_count": group["record_count"],
            "candidate_fingerprint": group["candidate_fingerprint"],
        },
    )
    await session.commit()
    await session.refresh(review)
    return review


@router.get(
    "/{import_id}/compare/{target_import_id}",
    response_model=DataImportComparisonRead,
)
async def compare_data_imports(
    import_id: str,
    target_import_id: str,
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> DataImportComparisonRead:
    """处理该接口。

    执行身份、租户、参数和业务状态校验后返回类型化响应。
    """
    if import_id == target_import_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="基准批次和目标批次不能相同",
        )
    jobs = list(
        await session.scalars(
            select(DataImportJob).where(
                DataImportJob.id.in_([import_id, target_import_id]),
                DataImportJob.tenant_id == identity.tenant_id,
            )
        )
    )
    if {job.id for job in jobs} != {import_id, target_import_id}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据导入任务不存在")
    if any(job.status != ImportStatus.COMPLETED.value for job in jobs):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="仅已完成批次可以进行版本对比")
    records = list(
        await session.scalars(
            select(EvidenceRecord).where(
                EvidenceRecord.import_job_id.in_([import_id, target_import_id]),
                EvidenceRecord.tenant_id == identity.tenant_id,
            )
        )
    )
    comparison = compare_import_records(
        [record for record in records if record.import_job_id == import_id],
        [record for record in records if record.import_job_id == target_import_id],
    )
    return DataImportComparisonRead(
        base_import_id=import_id,
        target_import_id=target_import_id,
        **comparison,
    )


@router.get("", response_model=list[DataImportRead])
async def list_data_imports(
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, object]]:
    """处理`GET `接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    result = await session.scalars(
        select(DataImportJob)
        .where(DataImportJob.tenant_id == identity.tenant_id)
        .order_by(DataImportJob.created_at.desc())
    )
    jobs = list(result)
    stats = await _get_import_index_stats(session, identity.tenant_id, [job.id for job in jobs])
    return [_data_import_payload(job, stats.get(job.id, {})) for job in jobs]


@router.get("/page", response_model=DataImportPage)
async def page_data_imports(
    response: Response,
    import_status: str | None = Query(default=None, alias="status"),
    keyword: str | None = Query(default=None, min_length=1, max_length=255),
    import_id: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=5, ge=1, le=100),
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    """处理`GET /page`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    conditions = [DataImportJob.tenant_id == identity.tenant_id]
    if import_status is not None:
        valid_statuses = {item.value for item in ImportStatus}
        if import_status not in valid_statuses:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="无效的数据导入状态",
            )
        conditions.append(DataImportJob.status == import_status)
    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        conditions.append(
            or_(
                DataImportJob.id.ilike(pattern),
                DataImportJob.filename.ilike(pattern),
                DataImportJob.created_by.ilike(pattern),
            )
        )
    if import_id is not None:
        conditions.append(DataImportJob.id == import_id)

    total = int(
        await session.scalar(
            select(func.count(DataImportJob.id)).where(*conditions)
        )
        or 0
    )
    summary_rows = await session.execute(
        select(DataImportJob.status, func.count(DataImportJob.id))
        .where(DataImportJob.tenant_id == identity.tenant_id)
        .group_by(DataImportJob.status)
    )
    summary_counts = {str(job_status): int(count) for job_status, count in summary_rows}
    summary = DataImportPageSummary(
        total=sum(summary_counts.values()),
        queued=summary_counts.get(ImportStatus.QUEUED.value, 0),
        processing=summary_counts.get(ImportStatus.PROCESSING.value, 0),
        completed=summary_counts.get(ImportStatus.COMPLETED.value, 0),
        failed=summary_counts.get(ImportStatus.FAILED.value, 0),
    )
    result = await session.scalars(
        select(DataImportJob)
        .where(*conditions)
        .order_by(DataImportJob.created_at.desc(), DataImportJob.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    jobs = list(result)
    stats = await _get_import_index_stats(
        session,
        identity.tenant_id,
        [job.id for job in jobs],
    )
    response.headers["X-Total-Count"] = str(total)
    return {
        "items": [_data_import_payload(job, stats.get(job.id, {})) for job in jobs],
        "total": total,
        "page": page,
        "page_size": page_size,
        "summary": summary.model_dump(),
    }


@router.get("/{import_id}", response_model=DataImportRead)
async def get_data_import(
    import_id: str,
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    """处理`GET /{import_id}`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    job = await session.scalar(
        select(DataImportJob).where(
            DataImportJob.id == import_id,
            DataImportJob.tenant_id == identity.tenant_id,
        )
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据导入任务不存在")
    stats = await _get_import_index_stats(session, identity.tenant_id, [job.id])
    return _data_import_payload(job, stats.get(job.id, {}))


@router.post(
    "/{import_id}/retry",
    response_model=DataImportRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_data_import(
    import_id: str,
    identity: Identity = Depends(require_planner),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    """处理`POST /{import_id}/retry`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    job = await session.scalar(
        select(DataImportJob)
        .where(
            DataImportJob.id == import_id,
            DataImportJob.tenant_id == identity.tenant_id,
        )
        .with_for_update()
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据导入任务不存在")
    if job.status != ImportStatus.FAILED.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="仅失败批次可以重新解析")
    evidence_count = await session.scalar(
        select(func.count(EvidenceRecord.id)).where(EvidenceRecord.import_job_id == job.id)
    )
    if evidence_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该批次已存在证据记录，请使用索引重建或先撤回批次",
        )

    job.status = ImportStatus.QUEUED.value
    job.celery_task_id = None
    job.index_celery_task_id = None
    job.total_rows = 0
    job.valid_rows = 0
    job.invalid_rows = 0
    job.error_message = None
    job.completed_at = None
    record_audit_event(
        session,
        action="import.retry_queued",
        entity_type="data_import",
        entity_id=job.id,
        tenant_id=job.tenant_id,
        actor_id=identity.user_id,
    )
    await session.commit()
    await session.refresh(job)
    try:
        task = process_tabular_import.delay(job.id)
    except Exception as exc:
        job.status = ImportStatus.FAILED.value
        job.error_message = f"无法重新提交导入任务: {exc}"
        record_audit_event(
            session,
            action="import.dispatch_failed",
            entity_type="data_import",
            entity_id=job.id,
            tenant_id=job.tenant_id,
            actor_id=identity.user_id,
            detail={"error": str(exc), "operation": "retry"},
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=job.error_message,
        ) from exc
    job.celery_task_id = task.id
    await session.commit()
    await session.refresh(job)
    stats = await _get_import_index_stats(session, identity.tenant_id, [job.id])
    return _data_import_payload(job, stats.get(job.id, {}))


@router.post("/{import_id}/reindex", response_model=DataImportReindexRead)
async def reindex_data_import(
    import_id: str,
    identity: Identity = Depends(require_planner),
    session: AsyncSession = Depends(get_db_session),
) -> DataImportReindexRead:
    """处理`POST /{import_id}/reindex`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    job = await session.scalar(
        select(DataImportJob).where(
            DataImportJob.id == import_id,
            DataImportJob.tenant_id == identity.tenant_id,
        )
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据导入任务不存在")
    if job.status != ImportStatus.COMPLETED.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="仅已完成批次可以重建索引")
    evidence_ids = list(
        await session.scalars(
            select(EvidenceRecord.id).where(
                EvidenceRecord.import_job_id == job.id,
                EvidenceRecord.tenant_id == identity.tenant_id,
                EvidenceRecord.quality_status != EvidenceQualityStatus.BLOCKED.value,
                EvidenceRecord.index_status.in_(
                    [
                        EvidenceIndexStatus.PENDING.value,
                        EvidenceIndexStatus.INDEXING.value,
                        EvidenceIndexStatus.FAILED.value,
                    ]
                ),
            )
        )
    )
    if not evidence_ids:
        return DataImportReindexRead(import_id=job.id, queued_records=0, task_id=None)

    await session.execute(
        update(EvidenceRecord)
        .where(EvidenceRecord.id.in_(evidence_ids))
        .values(index_status=EvidenceIndexStatus.PENDING.value)
    )
    record_audit_event(
        session,
        action="import.reindex_queued",
        entity_type="data_import",
        entity_id=job.id,
        tenant_id=job.tenant_id,
        actor_id=identity.user_id,
        detail={"queued_records": len(evidence_ids)},
    )
    job.index_celery_task_id = None
    await session.commit()
    try:
        task = index_evidence_batch.delay(evidence_ids)
    except Exception as exc:
        await session.execute(
            update(EvidenceRecord)
            .where(EvidenceRecord.id.in_(evidence_ids))
            .values(index_status=EvidenceIndexStatus.FAILED.value)
        )
        record_audit_event(
            session,
            action="import.reindex_dispatch_failed",
            entity_type="data_import",
            entity_id=job.id,
            tenant_id=job.tenant_id,
            actor_id=identity.user_id,
            detail={"error": str(exc)},
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"无法提交索引重建任务: {exc}",
        ) from exc
    job.index_celery_task_id = task.id
    await session.commit()
    await session.refresh(job)
    return DataImportReindexRead(
        import_id=job.id,
        queued_records=len(evidence_ids),
        task_id=task.id,
    )


@router.patch(
    "/{import_id}/evidence/{evidence_id}/quality-review",
    response_model=EvidenceRecordRead,
)
async def review_import_evidence_quality(
    import_id: str,
    evidence_id: str,
    payload: EvidenceQualityReviewRequest,
    identity: Identity = Depends(require_planner),
    session: AsyncSession = Depends(get_db_session),
) -> EvidenceRecord:
    """处理该接口。

    执行身份、租户、参数和业务状态校验后返回类型化响应。
    """
    record = await session.scalar(
        select(EvidenceRecord)
        .where(
            EvidenceRecord.id == evidence_id,
            EvidenceRecord.import_job_id == import_id,
            EvidenceRecord.tenant_id == identity.tenant_id,
        )
        .with_for_update()
    )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="证据记录不存在")

    note = payload.note.strip() if payload.note else None
    if payload.action == "block" and not note:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="标记不可用必须填写处理说明",
        )

    previous_quality_status = record.quality_status
    previous_index_status = record.index_status
    needs_reindex = False
    if payload.action == "block":
        try:
            await asyncio.to_thread(MilvusVectorStore().delete, [record.id])
        except Exception as exc:
            logger.exception(
                "evidence_quality_block_vector_delete_failed",
                evidence_id=record.id,
                import_id=import_id,
                error=str(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Milvus 证据清理失败，请稍后重试",
            ) from exc
        record.quality_status = EvidenceQualityStatus.BLOCKED.value
        record.index_status = EvidenceIndexStatus.FAILED.value
    else:
        record.quality_status = EvidenceQualityStatus.VERIFIED.value
        if record.content.strip() and (
            previous_quality_status != EvidenceQualityStatus.VERIFIED.value
            or previous_index_status != EvidenceIndexStatus.INDEXED.value
        ):
            record.index_status = EvidenceIndexStatus.PENDING.value
            needs_reindex = True
        elif not record.content.strip():
            record.index_status = EvidenceIndexStatus.FAILED.value

    reviewed_at = datetime.now(UTC).isoformat()
    metadata = dict(record.metadata_json) if isinstance(record.metadata_json, dict) else {}
    metadata["quality_review"] = {
        "action": payload.action,
        "note": note,
        "reviewed_by": identity.user_id,
        "reviewed_at": reviewed_at,
        "previous_quality_status": previous_quality_status,
        "previous_index_status": previous_index_status,
    }
    record.metadata_json = metadata
    record_audit_event(
        session,
        action="evidence.quality_reviewed",
        entity_type="evidence_record",
        entity_id=record.id,
        tenant_id=identity.tenant_id,
        actor_id=identity.user_id,
        detail={
            "import_id": import_id,
            "review_action": payload.action,
            "note": note,
            "previous_quality_status": previous_quality_status,
            "previous_index_status": previous_index_status,
            "quality_status": record.quality_status,
            "index_status": record.index_status,
            "index_rebuild_requested": needs_reindex,
        },
    )
    await session.commit()

    if needs_reindex:
        try:
            job = await session.get(DataImportJob, import_id)
            if job is not None:
                job.index_celery_task_id = None
                await session.commit()
            task = index_evidence_batch.delay([record.id])
            job = await session.get(DataImportJob, import_id)
            if job is not None:
                job.index_celery_task_id = task.id
                await session.commit()
        except Exception as exc:
            await session.execute(
                update(EvidenceRecord)
                .where(EvidenceRecord.id == record.id)
                .values(index_status=EvidenceIndexStatus.FAILED.value)
            )
            record_audit_event(
                session,
                action="evidence.quality_review_index_dispatch_failed",
                entity_type="evidence_record",
                entity_id=record.id,
                tenant_id=identity.tenant_id,
                actor_id=identity.user_id,
                detail={"error": str(exc), "import_id": import_id},
            )
            await session.commit()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"无法提交证据索引任务: {exc}",
            ) from exc

    await session.refresh(record)
    return record


@router.get("/{import_id}/quality-report")
async def download_import_quality_report(
    import_id: str,
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """处理`GET /{import_id}/quality-report`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    job = await session.scalar(
        select(DataImportJob).where(
            DataImportJob.id == import_id,
            DataImportJob.tenant_id == identity.tenant_id,
        )
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据导入任务不存在")
    records = list(
        await session.scalars(
            select(EvidenceRecord)
            .where(
                EvidenceRecord.import_job_id == job.id,
                EvidenceRecord.tenant_id == identity.tenant_id,
                EvidenceRecord.quality_status != EvidenceQualityStatus.VERIFIED.value,
            )
            .order_by(EvidenceRecord.source_row)
            .limit(50_000)
        )
    )
    filename = f"{Path(job.filename).stem}_数据质量报告.xlsx"
    return Response(
        content=build_import_quality_report_bytes(job, records),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.delete("/{import_id}", status_code=status.HTTP_204_NO_CONTENT)
async def withdraw_data_import(
    import_id: str,
    identity: Identity = Depends(require_planner),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """处理`DELETE /{import_id}`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    job = await session.scalar(
        select(DataImportJob)
        .where(
            DataImportJob.id == import_id,
            DataImportJob.tenant_id == identity.tenant_id,
        )
        .with_for_update()
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据导入任务不存在")
    if job.status in {ImportStatus.QUEUED.value, ImportStatus.PROCESSING.value}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="执行中的导入批次不能撤回")

    indexing_count = await session.scalar(
        select(func.count(EvidenceRecord.id)).where(
            EvidenceRecord.import_job_id == job.id,
            EvidenceRecord.tenant_id == identity.tenant_id,
            EvidenceRecord.index_status.in_(
                [EvidenceIndexStatus.PENDING.value, EvidenceIndexStatus.INDEXING.value]
            ),
        )
    )
    if indexing_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Milvus 索引仍在处理中，请等待完成或先处理索引失败记录",
        )

    indexed_ids = list(
        await session.scalars(
            select(EvidenceRecord.id).where(
                EvidenceRecord.import_job_id == job.id,
                EvidenceRecord.tenant_id == identity.tenant_id,
                EvidenceRecord.index_status == EvidenceIndexStatus.INDEXED.value,
            )
        )
    )
    try:
        await asyncio.to_thread(MilvusVectorStore().delete, indexed_ids)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Milvus 证据清理失败，批次尚未撤回: {exc}",
        ) from exc

    storage_key = job.storage_key
    record_audit_event(
        session,
        action="import.withdrawn",
        entity_type="data_import",
        entity_id=job.id,
        tenant_id=job.tenant_id,
        actor_id=identity.user_id,
        detail={"filename": job.filename, "deleted_evidence": len(indexed_ids)},
    )
    await session.execute(
        delete(EvidenceRecord).where(
            EvidenceRecord.import_job_id == job.id,
            EvidenceRecord.tenant_id == identity.tenant_id,
        )
    )
    await session.delete(job)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        if indexed_ids:
            try:
                index_evidence_batch.delay(indexed_ids)
            except Exception:
                logger.exception("import_withdraw_recovery_dispatch_failed", import_id=import_id)
        raise

    try:
        await get_object_storage_provider().delete_object(storage_key)
    except OSError as exc:
        logger.warning(
            "import_source_cleanup_failed",
            import_id=import_id,
            storage_key=storage_key,
            error=str(exc),
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{import_id}/evidence/page", response_model=EvidenceRecordPage)
async def page_import_evidence(
    import_id: str,
    response: Response,
    quality_status: str | None = Query(default=None),
    index_status: str | None = Query(default=None),
    keyword: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    """处理`GET /{import_id}/evidence/page`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    job = await session.scalar(
        select(DataImportJob.id).where(
            DataImportJob.id == import_id,
            DataImportJob.tenant_id == identity.tenant_id,
        )
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据导入任务不存在")
    valid_quality_statuses = {item.value for item in EvidenceQualityStatus}
    if quality_status is not None and quality_status not in valid_quality_statuses:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="无效的数据质量状态")
    valid_index_statuses = {item.value for item in EvidenceIndexStatus}
    if index_status is not None and index_status not in valid_index_statuses:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="无效的索引状态")
    conditions = [
        EvidenceRecord.import_job_id == import_id,
        EvidenceRecord.tenant_id == identity.tenant_id,
    ]
    if quality_status is not None:
        conditions.append(EvidenceRecord.quality_status == quality_status)
    if index_status is not None:
        conditions.append(EvidenceRecord.index_status == index_status)
    normalized_keyword = keyword.strip() if keyword else ""
    if normalized_keyword:
        pattern = f"%{normalized_keyword}%"
        conditions.append(
            or_(
                EvidenceRecord.id.like(pattern),
                EvidenceRecord.content.like(pattern),
                EvidenceRecord.source_id.like(pattern),
                EvidenceRecord.source_name.like(pattern),
            )
        )
    total = int(await session.scalar(select(func.count(EvidenceRecord.id)).where(*conditions)) or 0)
    result = await session.scalars(
        select(EvidenceRecord)
        .where(*conditions)
        .order_by(EvidenceRecord.source_row, EvidenceRecord.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    response.headers["X-Total-Count"] = str(total)
    return {
        "items": list(result),
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{import_id}/evidence", response_model=list[EvidenceRecordRead])
async def list_import_evidence(
    import_id: str,
    quality_status: str | None = Query(default=None),
    index_status: str | None = Query(default=None),
    keyword: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=200, ge=1, le=500),
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> list[EvidenceRecord]:
    """处理`GET /{import_id}/evidence`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    job = await session.scalar(
        select(DataImportJob.id).where(
            DataImportJob.id == import_id,
            DataImportJob.tenant_id == identity.tenant_id,
        )
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据导入任务不存在")
    valid_quality_statuses = {item.value for item in EvidenceQualityStatus}
    if quality_status is not None and quality_status not in valid_quality_statuses:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="无效的数据质量状态")
    valid_index_statuses = {item.value for item in EvidenceIndexStatus}
    if index_status is not None and index_status not in valid_index_statuses:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="无效的索引状态")
    query = select(EvidenceRecord).where(
        EvidenceRecord.import_job_id == import_id,
        EvidenceRecord.tenant_id == identity.tenant_id,
    )
    if quality_status is not None:
        query = query.where(EvidenceRecord.quality_status == quality_status)
    if index_status is not None:
        query = query.where(EvidenceRecord.index_status == index_status)
    normalized_keyword = keyword.strip() if keyword else ""
    if normalized_keyword:
        pattern = f"%{normalized_keyword}%"
        query = query.where(
            or_(
                EvidenceRecord.id.like(pattern),
                EvidenceRecord.content.like(pattern),
                EvidenceRecord.source_id.like(pattern),
                EvidenceRecord.source_name.like(pattern),
            )
        )
    result = await session.scalars(
        query.order_by(EvidenceRecord.source_row).limit(limit)
    )
    return list(result)


@router.get(
    "/{import_id}/quality-issues-summary",
    response_model=EvidenceQualityIssueSummaryRead,
)
async def get_import_quality_issues_summary(
    import_id: str,
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> EvidenceQualityIssueSummaryRead:
    """处理该接口。

    执行身份、租户、参数和业务状态校验后返回类型化响应。
    """
    job = await session.scalar(
        select(DataImportJob.id).where(
            DataImportJob.id == import_id,
            DataImportJob.tenant_id == identity.tenant_id,
        )
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据导入任务不存在")
    rows = (
        await session.execute(
            select(
                EvidenceRecord.quality_status,
                EvidenceRecord.index_status,
                EvidenceRecord.metadata_json,
            ).where(
                EvidenceRecord.import_job_id == import_id,
                EvidenceRecord.tenant_id == identity.tenant_id,
            )
        )
    ).all()
    status_counts = {"verified": 0, "warning": 0, "blocked": 0}
    failed_index_records = 0
    issue_counts: dict[tuple[str, str, str, str], int] = {}
    for quality_value, index_value, metadata_json in rows:
        if quality_value in status_counts:
            status_counts[quality_value] += 1
        if index_value == EvidenceIndexStatus.FAILED.value:
            failed_index_records += 1
        metadata = metadata_json if isinstance(metadata_json, dict) else {}
        issues = metadata.get("quality_issues")
        if not isinstance(issues, list):
            continue
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            key = (
                str(issue.get("code") or "unknown"),
                str(issue.get("field") or "unknown"),
                str(issue.get("message") or "未提供问题说明"),
                str(issue.get("severity") or "warning"),
            )
            issue_counts[key] = issue_counts.get(key, 0) + 1
    return EvidenceQualityIssueSummaryRead(
        total_records=len(rows),
        verified_records=status_counts["verified"],
        warning_records=status_counts["warning"],
        blocked_records=status_counts["blocked"],
        failed_index_records=failed_index_records,
        issues=[
            EvidenceQualityIssueSummaryItem(
                code=code,
                field=field,
                message=message,
                severity=severity,
                count=count,
            )
            for (code, field, message, severity), count in sorted(
                issue_counts.items(), key=lambda item: (-item[1], item[0][0])
            )
        ],
    )
