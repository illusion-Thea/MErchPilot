"""文件职责：验证 import analysis 相关规则、边界与回归行为。"""

from datetime import UTC, datetime

from merchpilot.infrastructure.models import EvidenceRecord
from merchpilot.services.import_analysis import (
    analyze_coverage,
    compare_import_records,
    find_duplicate_groups,
)


def record(
    evidence_id: str,
    import_id: str,
    source_id: str,
    content_hash: str,
    *,
    data_type: str = "竞品",
    category: str = "智能保温杯",
    market: str = "中国",
    quality: str = "verified",
) -> EvidenceRecord:
    """辅助构造`record`测试数据或依赖，减少用例中的重复准备代码。"""
    return EvidenceRecord(
        id=evidence_id,
        tenant_id="default",
        import_job_id=import_id,
        source_type="tabular",
        source_name=f"{import_id}.xlsx",
        source_row=2,
        source_id=source_id,
        content=f"content-{evidence_id}",
        metadata_json={
            "normalized_row": {
                "data_type": data_type,
                "category": category,
                "target_market": market,
                "source_id": source_id,
            }
        },
        content_hash=content_hash,
        quality_status=quality,
        index_status="indexed",
        observed_at=datetime(2026, 8, 20, tzinfo=UTC),
    )


def test_coverage_counts_business_dimensions() -> None:
    """验证“coverage counts business dimensions”场景，确保业务规则、权限和异常边界保持稳定。"""
    coverage = analyze_coverage(
        [
            record("evidence-1", "import-1", "source-1", "hash-1"),
            record(
                "evidence-2",
                "import-1",
                "source-2",
                "hash-2",
                data_type="用户评论",
                quality="warning",
            ),
        ]
    )

    assert coverage["total_records"] == 2
    assert coverage["verified_records"] == 1
    assert coverage["date_coverage_rate"] == 1.0
    assert coverage["data_type_counts"] == {"用户评论": 1, "竞品": 1}


def test_duplicate_groups_detect_source_and_content_duplicates() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    groups = find_duplicate_groups(
        [
            record("evidence-1", "import-1", "source-1", "hash-1"),
            record("evidence-2", "import-2", "source-1", "hash-2"),
            record("evidence-3", "import-3", "source-3", "hash-1"),
        ]
    )

    assert {(item["match_type"], item["record_count"]) for item in groups} == {
        ("source_id", 2),
        ("content_hash", 2),
    }
    source_group = next(item for item in groups if item["match_type"] == "source_id")
    assert len(source_group["candidate_fingerprint"]) == 64
    assert source_group["records"] == [
        {
            "evidence_id": "evidence-1",
            "source_id": "source-1",
            "import_job_id": "import-1",
            "source_name": "import-1.xlsx",
            "source_row": 2,
            "quality_status": "verified",
            "observed_at": "2026-08-20T00:00:00+00:00",
            "content_preview": "content-evidence-1",
        },
        {
            "evidence_id": "evidence-2",
            "source_id": "source-1",
            "import_job_id": "import-2",
            "source_name": "import-2.xlsx",
            "source_row": 2,
            "quality_status": "verified",
            "observed_at": "2026-08-20T00:00:00+00:00",
            "content_preview": "content-evidence-2",
        },
    ]


def test_exact_duplicate_is_visible_as_source_and_content_match() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    groups = find_duplicate_groups(
        [
            record("evidence-1", "import-1", "source-1", "hash-1"),
            record("evidence-2", "import-2", "source-1", "hash-1"),
        ]
    )

    assert {item["match_type"] for item in groups} == {"source_id", "content_hash"}


def test_compare_import_records_reports_added_removed_changed_and_unchanged() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    comparison = compare_import_records(
        [
            record("base-1", "base", "source-1", "hash-1"),
            record("base-2", "base", "source-2", "hash-2"),
            record("base-3", "base", "source-3", "hash-3"),
        ],
        [
            record("target-1", "target", "source-1", "hash-1"),
            record("target-2", "target", "source-2", "hash-2-new"),
            record("target-4", "target", "source-4", "hash-4"),
        ],
    )

    assert comparison["added_source_ids"] == ["source-4"]
    assert comparison["removed_source_ids"] == ["source-3"]
    assert comparison["changed_source_ids"] == ["source-2"]
    assert comparison["unchanged_source_ids"] == ["source-1"]
    assert comparison["base_unkeyed_count"] == 0
    assert comparison["target_unkeyed_count"] == 0


def test_generated_source_ids_do_not_create_false_duplicates_or_version_matches() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    base = record("base-1", "base", "base.xlsx:2", "hash-1")
    target = record("target-1", "target", "target.xlsx:2", "hash-2")
    base.metadata_json = {"normalized_row": {"content": "base"}}
    target.metadata_json = {"normalized_row": {"content": "target"}}

    assert find_duplicate_groups([base, target]) == []
    comparison = compare_import_records([base], [target])
    assert comparison["added_count"] == 0
    assert comparison["removed_count"] == 0
    assert comparison["base_unkeyed_count"] == 1
    assert comparison["target_unkeyed_count"] == 1
