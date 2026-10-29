"""文件职责：验证 retrieval governance 相关规则、边界与回归行为。"""

import hashlib
from datetime import UTC, datetime

from merchpilot.infrastructure.models import EvidenceDuplicateReview
from merchpilot.services.retrieval_governance import apply_duplicate_review_policy


def review(
    review_id: str,
    match_type: str,
    canonical_id: str,
    candidate_ids: list[str],
    *,
    fingerprint: str | None = None,
) -> EvidenceDuplicateReview:
    """辅助构造`review`测试数据或依赖，减少用例中的重复准备代码。"""
    sorted_ids = sorted(candidate_ids)
    return EvidenceDuplicateReview(
        id=review_id,
        tenant_id="default",
        match_type=match_type,
        match_value=f"match-{review_id}",
        candidate_fingerprint=fingerprint
        or hashlib.sha256("\x1f".join(sorted_ids).encode()).hexdigest(),
        candidate_evidence_ids=sorted_ids,
        decision="select_canonical",
        canonical_evidence_id=canonical_id,
        notes=None,
        reviewed_by="planner",
        reviewed_at=datetime(2026, 8, 22, tzinfo=UTC),
    )


def test_canonical_hit_suppresses_reviewed_alternatives() -> None:
    """验证“canonical hit suppresses reviewed alternatives”场景，确保业务规则、权限和异常边界保持稳定。"""
    hits = [
        {
            "id": "canonical",
            "score": 0.7,
            "content": "相同内容",
            "quality_status": "warning",
        },
        {
            "id": "alternative",
            "score": 0.9,
            "content": "相同内容",
            "quality_status": "verified",
        },
        {"id": "other", "score": 0.8, "content": "其他内容", "quality_status": "verified"},
    ]

    result = apply_duplicate_review_policy(
        hits,
        [review("review-1", "source_id", "canonical", ["canonical", "alternative"])],
    )

    assert [hit["id"] for hit in result.hits] == ["canonical", "other"]
    assert result.canonical_evidence_ids == ["canonical"]
    assert result.suppressed_evidence_ids == ["alternative"]
    assert result.hits[0]["governance"]["is_canonical"] is True


def test_alternative_is_kept_when_canonical_was_not_recalled() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    hits = [
        {"id": "alternative", "score": 0.9, "content": "候选内容"},
        {"id": "other", "score": 0.8, "content": "其他内容"},
    ]

    result = apply_duplicate_review_policy(
        hits,
        [review("review-1", "source_id", "canonical", ["canonical", "alternative"])],
    )

    assert result.hits == hits
    assert result.suppressed_evidence_ids == []


def test_source_id_review_wins_when_reviews_select_conflicting_canonicals() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    hits = [
        {"id": "source-canonical", "score": 0.8, "content": "版本 A"},
        {"id": "content-canonical", "score": 0.9, "content": "版本 B"},
    ]
    reviews = [
        review(
            "content-review",
            "content_hash",
            "content-canonical",
            ["source-canonical", "content-canonical"],
        ),
        review(
            "source-review",
            "source_id",
            "source-canonical",
            ["source-canonical", "content-canonical"],
        ),
    ]

    result = apply_duplicate_review_policy(hits, reviews)

    assert [hit["id"] for hit in result.hits] == ["source-canonical"]
    assert result.applied_review_ids == ["source-review"]
    assert result.conflicting_review_ids == ["content-review"]


def test_review_with_invalid_candidate_fingerprint_is_ignored() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    hits = [
        {"id": "canonical", "score": 0.8, "content": "版本 A"},
        {"id": "alternative", "score": 0.9, "content": "版本 B"},
    ]

    result = apply_duplicate_review_policy(
        hits,
        [
            review(
                "review-1",
                "source_id",
                "canonical",
                ["canonical", "alternative"],
                fingerprint="invalid",
            )
        ],
    )

    assert result.hits == hits
    assert result.applied_review_ids == []
