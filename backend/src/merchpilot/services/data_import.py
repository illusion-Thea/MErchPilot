"""文件职责：协调上传文件解析、校验、落库和异步索引任务。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from merchpilot.adapters.storage import get_object_storage_provider
from merchpilot.domain.enums import EvidenceIndexStatus, EvidenceQualityStatus, ImportStatus
from merchpilot.infrastructure.database import async_session_factory
from merchpilot.infrastructure.models import DataImportJob, EvidenceRecord
from merchpilot.services.audit import record_audit_event
from merchpilot.services.multimodal_import import extract_multimodal_evidence
from merchpilot.services.tabular_import import build_evidence_drafts, read_tabular_content


async def process_import_job(import_id: str) -> dict[str, Any]:
    """按导入类型解析文件，并统一写入可追溯证据记录。"""
    storage = get_object_storage_provider()
    async with async_session_factory() as session:
        job = await session.get(DataImportJob, import_id)
        if job is None:
            raise ValueError(f"data import job not found: {import_id}")
        job.status = ImportStatus.PROCESSING.value
        job.error_message = None
        record_audit_event(
            session,
            action="import.processing",
            entity_type="data_import",
            entity_id=job.id,
            tenant_id=job.tenant_id,
            actor_id="system",
        )
        await session.commit()

        try:
            content = await storage.get_object(job.storage_key)
            if job.source_type == "tabular":
                frame = read_tabular_content(content, job.filename)
                drafts = build_evidence_drafts(
                    frame,
                    source_name=job.filename,
                    import_job_id=job.id,
                )
                extraction_summary: dict[str, Any] = {
                    "extraction": "tabular",
                    "model": None,
                }
            else:
                drafts, extraction_summary = await extract_multimodal_evidence(
                    content,
                    job.filename,
                    import_job_id=job.id,
                )
            draft_ids = [item.id for item in drafts]
            existing_ids = (
                set(
                    await session.scalars(
                        select(EvidenceRecord.id).where(EvidenceRecord.id.in_(draft_ids))
                    )
                )
                if draft_ids
                else set()
            )
            records = [
                EvidenceRecord(
                    id=draft.id,
                    tenant_id=job.tenant_id,
                    import_job_id=job.id,
                    source_type=job.source_type,
                    source_name=draft.source_name,
                    source_row=draft.source_row,
                    source_id=draft.source_id,
                    content=draft.content,
                    metadata_json=draft.metadata,
                    content_hash=draft.content_hash,
                    quality_status=draft.quality_status,
                    index_status=EvidenceIndexStatus.PENDING.value,
                    observed_at=draft.observed_at,
                )
                for draft in drafts
                if draft.id not in existing_ids
            ]
            session.add_all(records)
            job.total_rows = len(drafts)
            job.valid_rows = sum(
                item.quality_status != EvidenceQualityStatus.BLOCKED.value for item in drafts
            )
            job.invalid_rows = job.total_rows - job.valid_rows
            job.status = ImportStatus.COMPLETED.value
            job.completed_at = datetime.now(UTC)
            record_audit_event(
                session,
                action="import.completed",
                entity_type="data_import",
                entity_id=job.id,
                tenant_id=job.tenant_id,
                actor_id="system",
                detail={
                    "total_rows": job.total_rows,
                    "valid_rows": job.valid_rows,
                    "invalid_rows": job.invalid_rows,
                    "extraction": extraction_summary,
                },
            )
            await session.commit()
            return {
                "import_id": import_id,
                "total_rows": job.total_rows,
                "valid_rows": job.valid_rows,
                "invalid_rows": job.invalid_rows,
                "evidence_ids": draft_ids,
                "extraction": extraction_summary,
            }
        except Exception as exc:
            await session.rollback()
            job = await session.get(DataImportJob, import_id)
            if job is None:
                raise
            job.status = ImportStatus.FAILED.value
            job.error_message = str(exc)
            record_audit_event(
                session,
                action="import.failed",
                entity_type="data_import",
                entity_id=job.id,
                tenant_id=job.tenant_id,
                actor_id="system",
                detail={"error": str(exc)},
            )
            await session.commit()
            raise


async def process_tabular_import_job(import_id: str) -> dict[str, Any]:
    """兼容旧调用方；实际任务已支持表格、文档、幻灯片和图片。"""
    return await process_import_job(import_id)
