"""文件职责：验证 evidence indexing 相关规则、边界与回归行为。"""

import pytest

from merchpilot.domain.enums import EvidenceIndexStatus, EvidenceQualityStatus
from merchpilot.infrastructure.models import EvidenceRecord
from merchpilot.services.evidence_indexing import (
    _batches,
    _partition_index_candidates,
    _resolve_indexed_batch,
)


def test_batches_split_large_index_jobs_without_losing_order() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    items = list(range(1000))

    batches = _batches(items, 128)

    assert [len(batch) for batch in batches] == [128, 128, 128, 128, 128, 128, 128, 104]
    assert [item for batch in batches for item in batch] == items


def test_batches_reject_non_positive_size() -> None:
    """验证“batches reject non positive size”场景，确保业务规则、权限和异常边界保持稳定。"""
    with pytest.raises(ValueError, match="batch size must be positive"):
        _batches([1], 0)


def test_resolve_indexed_batch_does_not_restore_blocked_records() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    valid_record = EvidenceRecord(
        id="evidence-valid",
        tenant_id="tenant-a",
        source_name="test.xlsx",
        source_row=2,
        source_id="valid",
        content="valid content",
        content_hash="hash-valid",
        quality_status=EvidenceQualityStatus.VERIFIED.value,
        index_status=EvidenceIndexStatus.INDEXING.value,
    )
    blocked_record = EvidenceRecord(
        id="evidence-blocked",
        tenant_id="tenant-a",
        source_name="test.xlsx",
        source_row=3,
        source_id="blocked",
        content="blocked content",
        content_hash="hash-blocked",
        quality_status=EvidenceQualityStatus.BLOCKED.value,
        index_status=EvidenceIndexStatus.FAILED.value,
    )
    already_indexed_record = EvidenceRecord(
        id="evidence-indexed",
        tenant_id="tenant-a",
        source_name="test.xlsx",
        source_row=4,
        source_id="indexed",
        content="already indexed content",
        content_hash="hash-indexed",
        quality_status=EvidenceQualityStatus.VERIFIED.value,
        index_status=EvidenceIndexStatus.INDEXED.value,
    )

    indexed, stale_ids = _resolve_indexed_batch(
        ["evidence-valid", "evidence-blocked", "evidence-indexed", "evidence-deleted"],
        [valid_record, blocked_record, already_indexed_record],
    )

    assert [record.id for record in indexed] == ["evidence-valid", "evidence-indexed"]
    assert stale_ids == ["evidence-blocked", "evidence-deleted"]


def test_partition_index_candidates_retries_stale_vector_cleanup() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    pending_record = EvidenceRecord(
        id="evidence-pending",
        tenant_id="tenant-a",
        source_name="test.xlsx",
        source_row=2,
        source_id="pending",
        content="pending content",
        content_hash="hash-pending",
        quality_status=EvidenceQualityStatus.VERIFIED.value,
        index_status=EvidenceIndexStatus.PENDING.value,
    )
    indexed_record = EvidenceRecord(
        id="evidence-indexed",
        tenant_id="tenant-a",
        source_name="test.xlsx",
        source_row=3,
        source_id="indexed",
        content="indexed content",
        content_hash="hash-indexed",
        quality_status=EvidenceQualityStatus.VERIFIED.value,
        index_status=EvidenceIndexStatus.INDEXED.value,
    )
    blocked_record = EvidenceRecord(
        id="evidence-blocked",
        tenant_id="tenant-a",
        source_name="test.xlsx",
        source_row=4,
        source_id="blocked",
        content="blocked content",
        content_hash="hash-blocked",
        quality_status=EvidenceQualityStatus.BLOCKED.value,
        index_status=EvidenceIndexStatus.FAILED.value,
    )

    indexable, cleanup_ids = _partition_index_candidates(
        ["evidence-pending", "evidence-indexed", "evidence-blocked", "evidence-deleted"],
        [pending_record, indexed_record, blocked_record],
    )

    assert [record.id for record in indexable] == ["evidence-pending"]
    assert cleanup_ids == ["evidence-blocked", "evidence-deleted"]


def test_partition_index_candidates_force_reindexes_existing_records() -> None:
    """验证混合集合迁移时可以强制重建已经索引的证据。"""
    indexed_record = EvidenceRecord(
        id="evidence-indexed",
        tenant_id="tenant-a",
        source_name="test.xlsx",
        source_row=3,
        source_id="indexed",
        content="indexed content",
        content_hash="hash-indexed",
        quality_status=EvidenceQualityStatus.VERIFIED.value,
        index_status=EvidenceIndexStatus.INDEXED.value,
    )

    indexable, cleanup_ids = _partition_index_candidates(
        ["evidence-indexed"],
        [indexed_record],
        force=True,
    )

    assert [record.id for record in indexable] == ["evidence-indexed"]
    assert cleanup_ids == []
