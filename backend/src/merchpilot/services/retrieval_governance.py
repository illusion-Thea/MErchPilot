"""文件职责：过滤撤回、重复和不可见证据，确保检索只使用当前可信事实。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from merchpilot.domain.enums import DuplicateReviewDecision
from merchpilot.infrastructure.database import async_session_factory
from merchpilot.infrastructure.models import EvidenceDuplicateReview

MATCH_TYPE_PRIORITY = {"source_id": 2, "content_hash": 1}


@dataclass(frozen=True, slots=True)
class RetrievalGovernanceResult:
    """`RetrievalGovernanceResult` 封装可复用业务规则，避免接口层重复实现相同判断。"""
    hits: list[dict[str, Any]]
    canonical_evidence_ids: list[str]
    suppressed_evidence_ids: list[str]
    applied_review_ids: list[str]
    conflicting_review_ids: list[str]


def empty_governance_result(hits: list[dict[str, Any]]) -> RetrievalGovernanceResult:
    """实现`empty_governance_result`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    return RetrievalGovernanceResult(
        hits=hits,
        canonical_evidence_ids=[],
        suppressed_evidence_ids=[],
        applied_review_ids=[],
        conflicting_review_ids=[],
    )


def _candidate_ids(review: EvidenceDuplicateReview) -> set[str]:
    """内部辅助函数`_candidate_ids`；拆分主流程并集中处理当前模块的边界条件。"""
    values = review.candidate_evidence_ids
    if not isinstance(values, list):
        return set()
    candidate_ids = {str(value) for value in values if value}
    fingerprint = hashlib.sha256("\x1f".join(sorted(candidate_ids)).encode()).hexdigest()
    if not review.candidate_fingerprint or review.candidate_fingerprint != fingerprint:
        return set()
    return candidate_ids


def apply_duplicate_review_policy(
    hits: list[dict[str, Any]],
    reviews: list[EvidenceDuplicateReview],
) -> RetrievalGovernanceResult:
    """实现`apply_duplicate_review_policy`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    hit_ids = {str(hit.get("id")) for hit in hits if hit.get("id")}
    if len(hit_ids) < 2:
        return empty_governance_result(hits)

    active_reviews = [
        review
        for review in reviews
        if review.decision == DuplicateReviewDecision.SELECT_CANONICAL.value
        and review.canonical_evidence_id
    ]
    active_reviews.sort(
        key=lambda review: (
            MATCH_TYPE_PRIORITY.get(review.match_type, 0),
            review.reviewed_at.isoformat(),
            review.id,
        ),
        reverse=True,
    )

    protected_ids: set[str] = set()
    suppressed_ids: set[str] = set()
    applied_review_ids: list[str] = []
    conflicting_review_ids: list[str] = []
    canonical_reviews: dict[str, list[str]] = {}

    for review in active_reviews:
        canonical_id = str(review.canonical_evidence_id)
        candidate_ids = _candidate_ids(review)
        matching_ids = candidate_ids & hit_ids
        if canonical_id not in matching_ids:
            continue
        if canonical_id in suppressed_ids or (matching_ids & protected_ids) - {canonical_id}:
            conflicting_review_ids.append(review.id)
            continue

        protected_ids.add(canonical_id)
        suppressed_ids.update(matching_ids - protected_ids)
        applied_review_ids.append(review.id)
        canonical_reviews.setdefault(canonical_id, []).append(review.id)

    if not applied_review_ids:
        return RetrievalGovernanceResult(
            hits=hits,
            canonical_evidence_ids=[],
            suppressed_evidence_ids=[],
            applied_review_ids=[],
            conflicting_review_ids=conflicting_review_ids,
        )

    governed_hits: list[dict[str, Any]] = []
    for hit in hits:
        evidence_id = str(hit.get("id"))
        if evidence_id in suppressed_ids:
            continue
        if evidence_id not in canonical_reviews:
            governed_hits.append(hit)
            continue
        governed_hits.append(
            {
                **hit,
                "governance": {
                    "is_canonical": True,
                    "duplicate_review_ids": canonical_reviews[evidence_id],
                },
            }
        )

    return RetrievalGovernanceResult(
        hits=governed_hits,
        canonical_evidence_ids=sorted(canonical_reviews),
        suppressed_evidence_ids=sorted(suppressed_ids),
        applied_review_ids=applied_review_ids,
        conflicting_review_ids=conflicting_review_ids,
    )


class EvidenceGovernanceResolver:
    """`EvidenceGovernanceResolver` 封装可复用业务规则，避免接口层重复实现相同判断。"""
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
    ) -> None:
        """初始化`EvidenceGovernanceResolver`所需依赖和默认状态。"""
        self.session_factory = session_factory

    async def resolve(
        self,
        hits: list[dict[str, Any]],
        *,
        tenant_id: str,
    ) -> RetrievalGovernanceResult:
        """实现`resolve`业务规则；根据类型化输入返回可复用、可解释的结果。"""
        if len(hits) < 2:
            return empty_governance_result(hits)
        async with self.session_factory() as session:
            reviews = list(
                await session.scalars(
                    select(EvidenceDuplicateReview).where(
                        EvidenceDuplicateReview.tenant_id == tenant_id,
                        EvidenceDuplicateReview.decision
                        == DuplicateReviewDecision.SELECT_CANONICAL.value,
                        EvidenceDuplicateReview.canonical_evidence_id.is_not(None),
                    )
                )
            )
        return apply_duplicate_review_policy(hits, reviews)
