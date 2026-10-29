"""文件职责：分析导入批次结构、字段覆盖和可用于规划的业务维度。"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from merchpilot.infrastructure.models import EvidenceRecord


@dataclass(frozen=True, slots=True)
class EvidenceSnapshot:
    """`EvidenceSnapshot` 封装可复用业务规则，避免接口层重复实现相同判断。"""
    evidence_id: str
    import_job_id: str | None
    source_id: str
    has_explicit_source_id: bool
    content_hash: str
    quality_status: str
    data_type: str | None
    category: str | None
    target_market: str | None
    observed_at: str | None
    source_name: str
    source_row: int
    content_preview: str


def _normalized_row(record: EvidenceRecord) -> dict[str, Any]:
    """内部辅助函数`_normalized_row`；拆分主流程并集中处理当前模块的边界条件。"""
    value = (record.metadata_json or {}).get("normalized_row")
    return value if isinstance(value, dict) else {}


def evidence_snapshot(record: EvidenceRecord) -> EvidenceSnapshot:
    """实现`evidence_snapshot`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    normalized = _normalized_row(record)
    normalized_source_id = normalized.get("source_id")
    return EvidenceSnapshot(
        evidence_id=record.id,
        import_job_id=record.import_job_id,
        source_id=record.source_id,
        has_explicit_source_id=bool(normalized_source_id),
        content_hash=record.content_hash,
        quality_status=record.quality_status,
        data_type=str(normalized.get("data_type")) if normalized.get("data_type") else None,
        category=str(normalized.get("category")) if normalized.get("category") else None,
        target_market=(str(normalized.get("target_market")) if normalized.get("target_market") else None),
        observed_at=record.observed_at.isoformat() if record.observed_at else None,
        source_name=record.source_name,
        source_row=record.source_row,
        content_preview=" ".join(record.content.split())[:160],
    )


def analyze_coverage(records: list[EvidenceRecord]) -> dict[str, Any]:
    """实现`analyze_coverage`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    snapshots = [evidence_snapshot(record) for record in records]
    data_type_counts = Counter(item.data_type or "未分类" for item in snapshots)
    category_counts = Counter(item.category or "未填写" for item in snapshots)
    market_counts = Counter(item.target_market or "未填写" for item in snapshots)
    dated_records = sum(item.observed_at is not None for item in snapshots)
    source_id_records = sum(item.has_explicit_source_id for item in snapshots)
    verified_records = sum(item.quality_status == "verified" for item in snapshots)
    total = len(snapshots)
    return {
        "total_records": total,
        "verified_records": verified_records,
        "dated_records": dated_records,
        "source_id_records": source_id_records,
        "date_coverage_rate": dated_records / total if total else 0.0,
        "source_id_coverage_rate": source_id_records / total if total else 0.0,
        "data_type_counts": dict(sorted(data_type_counts.items())),
        "category_counts": dict(category_counts.most_common(20)),
        "target_market_counts": dict(market_counts.most_common(20)),
    }


def duplicate_candidate_fingerprint(evidence_ids: list[str] | tuple[str, ...]) -> str:
    """实现`duplicate_candidate_fingerprint`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    normalized_ids = sorted(str(evidence_id) for evidence_id in evidence_ids)
    return hashlib.sha256("\x1f".join(normalized_ids).encode()).hexdigest()


def find_duplicate_groups(records: list[EvidenceRecord]) -> list[dict[str, Any]]:
    """实现`find_duplicate_groups`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    snapshots = [evidence_snapshot(record) for record in records]
    source_groups: dict[str, list[EvidenceSnapshot]] = defaultdict(list)
    content_groups: dict[str, list[EvidenceSnapshot]] = defaultdict(list)
    for snapshot in snapshots:
        if snapshot.has_explicit_source_id:
            source_groups[snapshot.source_id].append(snapshot)
        if snapshot.content_hash:
            content_groups[snapshot.content_hash].append(snapshot)

    groups: list[dict[str, Any]] = []
    for match_type, candidates in (
        ("source_id", source_groups),
        ("content_hash", content_groups),
    ):
        for match_value, items in candidates.items():
            if len(items) < 2:
                continue
            evidence_ids = tuple(sorted(item.evidence_id for item in items))
            candidate_fingerprint = duplicate_candidate_fingerprint(evidence_ids)
            record_summaries = [
                {
                    "evidence_id": item.evidence_id,
                    "source_id": item.source_id,
                    "import_job_id": item.import_job_id,
                    "source_name": item.source_name,
                    "source_row": item.source_row,
                    "quality_status": item.quality_status,
                    "observed_at": item.observed_at,
                    "content_preview": item.content_preview,
                }
                for item in sorted(items, key=lambda item: item.evidence_id)
            ]
            groups.append(
                {
                    "match_type": match_type,
                    "match_value": match_value,
                    "record_count": len(items),
                    "import_count": len(
                        {item.import_job_id for item in items if item.import_job_id is not None}
                    ),
                    "evidence_ids": list(evidence_ids),
                    "candidate_fingerprint": candidate_fingerprint,
                    "import_job_ids": sorted(
                        {item.import_job_id for item in items if item.import_job_id is not None}
                    ),
                    "source_ids": sorted({item.source_id for item in items}),
                    "records": record_summaries,
                }
            )
    return sorted(
        groups,
        key=lambda item: (-int(item["record_count"]), str(item["match_type"]), str(item["match_value"])),
    )


def compare_import_records(
    base_records: list[EvidenceRecord],
    target_records: list[EvidenceRecord],
) -> dict[str, Any]:
    """实现`compare_import_records`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    base_snapshots = [evidence_snapshot(record) for record in base_records]
    target_snapshots = [evidence_snapshot(record) for record in target_records]
    base_by_source = {item.source_id: item for item in base_snapshots if item.has_explicit_source_id}
    target_by_source = {item.source_id: item for item in target_snapshots if item.has_explicit_source_id}
    base_ids = set(base_by_source)
    target_ids = set(target_by_source)
    added_ids = sorted(target_ids - base_ids)
    removed_ids = sorted(base_ids - target_ids)
    shared_ids = base_ids & target_ids
    changed_ids = sorted(
        source_id
        for source_id in shared_ids
        if base_by_source[source_id].content_hash != target_by_source[source_id].content_hash
    )
    unchanged_ids = sorted(shared_ids - set(changed_ids))
    return {
        "base_records": len(base_records),
        "target_records": len(target_records),
        "base_unkeyed_count": sum(not item.has_explicit_source_id for item in base_snapshots),
        "target_unkeyed_count": sum(not item.has_explicit_source_id for item in target_snapshots),
        "added_count": len(added_ids),
        "removed_count": len(removed_ids),
        "changed_count": len(changed_ids),
        "unchanged_count": len(unchanged_ids),
        "added_source_ids": added_ids[:200],
        "removed_source_ids": removed_ids[:200],
        "changed_source_ids": changed_ids[:200],
        "unchanged_source_ids": unchanged_ids[:200],
        "base_coverage": analyze_coverage(base_records),
        "target_coverage": analyze_coverage(target_records),
    }
