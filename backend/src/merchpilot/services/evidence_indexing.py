"""文件职责：把可用证据批量向量化并同步至 Milvus，记录索引状态。"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select

from merchpilot.core.config import get_settings
from merchpilot.domain.enums import EvidenceIndexStatus, EvidenceQualityStatus
from merchpilot.infrastructure.database import async_session_factory
from merchpilot.infrastructure.milvus import MilvusVectorStore
from merchpilot.infrastructure.model_clients import get_embedding_service_client
from merchpilot.infrastructure.models import EvidenceRecord


def _truncate_utf8(value: str, max_bytes: int) -> str:
    """内部辅助函数`_truncate_utf8`；拆分主流程并集中处理当前模块的边界条件。"""
    return value.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")


def _milvus_row(record: EvidenceRecord, vector: list[float]) -> dict[str, Any]:
    """内部辅助函数`_milvus_row`；拆分主流程并集中处理当前模块的边界条件。"""
    metadata = record.metadata_json or {}
    return {
        "id": record.id,
        "vector": vector,
        "evidence_id": record.id,
        "tenant_id": record.tenant_id,
        "source_name": _truncate_utf8(record.source_name, 255),
        "category": _truncate_utf8(str(metadata.get("category") or ""), 128),
        "target_market": _truncate_utf8(str(metadata.get("target_market") or ""), 128),
        "quality_status": record.quality_status,
        "content": _truncate_utf8(record.content, 65_535),
        "metadata_json": metadata,
    }


def _batches[BatchItem](items: list[BatchItem], batch_size: int) -> list[list[BatchItem]]:
    """内部辅助函数`_batches`；拆分主流程并集中处理当前模块的边界条件。"""
    if batch_size < 1:
        raise ValueError("batch size must be positive")
    return [items[start : start + batch_size] for start in range(0, len(items), batch_size)]


def _partition_index_candidates(
    evidence_ids: list[str],
    records: list[EvidenceRecord],
    *,
    force: bool = False,
) -> tuple[list[EvidenceRecord], list[str]]:
    """内部辅助函数`_partition_index_candidates`；拆分主流程并集中处理当前模块的边界条件。"""
    records_by_id = {record.id: record for record in records}
    indexable: list[EvidenceRecord] = []
    cleanup_ids: list[str] = []
    for evidence_id in evidence_ids:
        record = records_by_id.get(evidence_id)
        if (
            record is None
            or record.quality_status == EvidenceQualityStatus.BLOCKED.value
            or not record.content.strip()
        ):
            cleanup_ids.append(evidence_id)
        elif force or record.index_status != EvidenceIndexStatus.INDEXED.value:
            indexable.append(record)
    return indexable, cleanup_ids


def _resolve_indexed_batch(
    batch_ids: list[str],
    records: list[EvidenceRecord],
) -> tuple[list[EvidenceRecord], list[str]]:
    """内部辅助函数`_resolve_indexed_batch`；拆分主流程并集中处理当前模块的边界条件。"""
    records_by_id = {record.id: record for record in records}
    indexed_records: list[EvidenceRecord] = []
    stale_ids: list[str] = []
    for evidence_id in batch_ids:
        record = records_by_id.get(evidence_id)
        if (
            record is None
            or record.quality_status == EvidenceQualityStatus.BLOCKED.value
            or record.index_status
            not in {EvidenceIndexStatus.INDEXING.value, EvidenceIndexStatus.INDEXED.value}
        ):
            stale_ids.append(evidence_id)
        else:
            indexed_records.append(record)
    return indexed_records, stale_ids


async def index_evidence_records(
    evidence_ids: list[str],
    *,
    force: bool = False,
) -> dict[str, Any]:
    """批量向量化可检索证据并写入Milvus，同时回写每条记录的索引结果。"""
    if not evidence_ids:
        return {"indexed": 0, "skipped": 0}
    evidence_ids = list(dict.fromkeys(evidence_ids))

    async with async_session_factory() as session:
        result = await session.scalars(
            select(EvidenceRecord).where(EvidenceRecord.id.in_(evidence_ids))
        )
        records = list(result)
        indexable, cleanup_ids = _partition_index_candidates(
            evidence_ids,
            records,
            force=force,
        )
        indexable_ids = {record.id for record in indexable}
        skipped = len(evidence_ids) - len(indexable)
        for record in records:
            if record.id in indexable_ids:
                record.index_status = EvidenceIndexStatus.INDEXING.value
            elif (
                record.quality_status == EvidenceQualityStatus.BLOCKED.value
                or not record.content.strip()
            ):
                record.index_status = EvidenceIndexStatus.FAILED.value
        await session.commit()

        settings = get_settings()
        vector_store = MilvusVectorStore(settings=settings)
        if cleanup_ids:
            await asyncio.to_thread(vector_store.delete, cleanup_ids)
        if not indexable:
            return {"indexed": 0, "skipped": skipped}

        embedding_client = get_embedding_service_client()
        indexed = 0
        failed = 0
        model_version: str | None = None
        batch_errors: list[Exception] = []
        for batch in _batches(indexable, settings.embedding_batch_size):
            batch_ids = [record.id for record in batch]
            try:
                embedding = await embedding_client.embed_texts([record.content for record in batch])
                if embedding.dimensions != settings.embedding_dimension:
                    raise RuntimeError(
                        "embedding dimension mismatch: "
                        f"expected {settings.embedding_dimension}, got {embedding.dimensions}"
                    )
                rows = [
                    _milvus_row(record, vector)
                    for record, vector in zip(batch, embedding.vectors, strict=True)
                ]
                await asyncio.to_thread(vector_store.upsert, rows)
            except Exception as exc:
                await session.rollback()
                failed_records = list(
                    await session.scalars(
                        select(EvidenceRecord)
                        .where(EvidenceRecord.id.in_(batch_ids))
                        .with_for_update()
                    )
                )
                records_to_fail = [
                    record
                    for record in failed_records
                    if record.quality_status != EvidenceQualityStatus.BLOCKED.value
                    and record.index_status == EvidenceIndexStatus.INDEXING.value
                ]
                for record in records_to_fail:
                    record.index_status = EvidenceIndexStatus.FAILED.value
                await session.commit()
                failed_count = len(records_to_fail)
                failed += failed_count
                if failed_count:
                    batch_errors.append(exc)
                continue

            indexed_records = list(
                await session.scalars(
                    select(EvidenceRecord)
                    .where(EvidenceRecord.id.in_(batch_ids))
                    .with_for_update()
                )
            )
            valid_records, stale_ids = _resolve_indexed_batch(batch_ids, indexed_records)
            for record in valid_records:
                record.index_status = EvidenceIndexStatus.INDEXED.value
                record.embedding_model_version = embedding.model
            await session.commit()
            if stale_ids:
                await asyncio.to_thread(vector_store.delete, stale_ids)
            indexed += len(valid_records)
            model_version = embedding.model

        if batch_errors:
            raise batch_errors[0]

        return {
            "indexed": indexed,
            "failed": failed,
            "skipped": skipped,
            "model": model_version,
        }


async def rebuild_hybrid_evidence_index() -> dict[str, Any]:
    """从PostgreSQL重建全部可用证据到当前Milvus混合集合。"""
    async with async_session_factory() as session:
        evidence_ids = list(
            await session.scalars(
                select(EvidenceRecord.id).where(
                    EvidenceRecord.quality_status != EvidenceQualityStatus.BLOCKED.value,
                    EvidenceRecord.content != "",
                )
            )
        )
    result = await index_evidence_records(evidence_ids, force=True)
    return {
        **result,
        "collection": get_settings().milvus_collection_name,
        "retrieval_mode": "dense_bm25_weighted_cross_encoder",
    }
