"""文件职责：验证 planning evidence 相关规则、边界与回归行为。"""

from datetime import UTC, datetime

from merchpilot.infrastructure.models import EvidenceRecord
from merchpilot.services.planning_evidence import (
    extract_planning_evidence_references,
    resolve_planning_evidence,
    resolve_planning_evidence_references,
)


def test_resolve_planning_evidence_combines_topics_and_current_lineage() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    snapshot = {
        "outputs": {
            "market": {
                "hits": [
                    {
                        "id": "evidence-1",
                        "source_name": "snapshot.xlsx",
                        "score": 0.91,
                        "vector_score": 0.72,
                        "content": "运行时证据摘要",
                        "governance": {
                            "is_canonical": True,
                            "duplicate_review_ids": ["review-1"],
                        },
                    }
                ]
            },
            "competitor": {
                "hits": [
                    {
                        "id": "evidence-1",
                        "source_name": "snapshot.xlsx",
                        "score": 0.88,
                        "content": "运行时证据摘要",
                    }
                ]
            },
        }
    }
    record = EvidenceRecord(
        id="evidence-1",
        tenant_id="default",
        source_type="tabular",
        source_name="current.xlsx",
        source_row=18,
        source_id="source-1",
        content="当前证据正文",
        metadata_json={"normalized_row": {"category": "保温杯"}},
        content_hash="hash-1",
        quality_status="verified",
        index_status="indexed",
        observed_at=datetime(2026, 8, 20, tzinfo=UTC),
    )

    resolved = resolve_planning_evidence(snapshot, [record])

    assert len(resolved) == 1
    assert resolved[0]["topics"] == ["市场", "竞品"]
    assert resolved[0]["source_name"] == "current.xlsx"
    assert resolved[0]["source_row"] == 18
    assert resolved[0]["retrieval_score"] == 0.91
    assert resolved[0]["is_canonical"] is True
    assert resolved[0]["duplicate_review_ids"] == ["review-1"]
    assert resolved[0]["available"] is True


def test_resolve_planning_evidence_uses_snapshot_after_record_withdrawal() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    snapshot = {
        "outputs": {
            "user_insight": {
                "hits": [
                    {
                        "id": "withdrawn-evidence",
                        "source_name": "withdrawn.xlsx",
                        "score": 0.83,
                        "content": "历史用户洞察摘要",
                        "metadata": {"channel": "天猫"},
                    }
                ]
            }
        }
    }

    resolved = resolve_planning_evidence(snapshot, [])

    assert resolved[0]["available"] is False
    assert resolved[0]["source_name"] == "withdrawn.xlsx"
    assert resolved[0]["content"] == "历史用户洞察摘要"
    assert resolved[0]["topics"] == ["用户洞察"]


def test_resolve_planning_evidence_references_preserves_page_order() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    snapshot = {
        "outputs": {
            "market": {
                "hits": [
                    {"id": "evidence-1", "content": "第一条"},
                    {"id": "evidence-2", "content": "第二条"},
                    {"id": "evidence-3", "content": "第三条"},
                ]
            }
        }
    }
    references = extract_planning_evidence_references(snapshot)

    resolved = resolve_planning_evidence_references(references[1:3], [])

    assert [item["evidence_id"] for item in resolved] == ["evidence-2", "evidence-3"]
    assert all(item["available"] is False for item in resolved)
