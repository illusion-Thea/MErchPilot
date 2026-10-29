"""文件职责：组合 Milvus 召回、证据治理和重排，返回可解释的检索结果。"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select

from merchpilot.domain.enums import EvidenceIndexStatus, EvidenceQualityStatus
from merchpilot.infrastructure.database import async_session_factory
from merchpilot.infrastructure.milvus import MilvusVectorStore
from merchpilot.infrastructure.model_clients import (
    EmbeddingServiceClient,
    RerankerServiceClient,
    get_embedding_service_client,
    get_reranker_service_client,
)
from merchpilot.infrastructure.models import EvidenceRecord
from merchpilot.services.retrieval_governance import (
    EvidenceGovernanceResolver,
    RetrievalGovernanceResult,
    empty_governance_result,
)

QUALITY_PRIORITY = {"verified": 2, "warning": 1, "blocked": 0}
RetrievableIdsResolver = Callable[[list[str], str], Awaitable[set[str]]]
RetrievableEvidenceContextResolver = Callable[
    [list[str], str],
    Awaitable[dict[str, dict[str, Any]]],
]


def _deduplicate_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """内部辅助函数`_deduplicate_hits`；拆分主流程并集中处理当前模块的边界条件。"""
    unique: dict[str, dict[str, Any]] = {}
    for hit in hits:
        content = re.sub(r"\s+", " ", str(hit.get("content") or "")).strip().lower()
        key = content or str(hit.get("id"))
        existing = unique.get(key)
        if existing is None:
            unique[key] = hit
            continue
        hit_quality = QUALITY_PRIORITY.get(str(hit.get("quality_status") or ""), -1)
        existing_quality = QUALITY_PRIORITY.get(
            str(existing.get("quality_status") or ""),
            -1,
        )
        if hit_quality > existing_quality or (
            hit_quality == existing_quality
            and float(hit.get("score") or 0.0) > float(existing.get("score") or 0.0)
        ):
            unique[key] = hit
    return list(unique.values())


class EvidenceRetriever:
    """`EvidenceRetriever` 封装可复用业务规则，避免接口层重复实现相同判断。"""
    def __init__(
        self,
        embedding_client: EmbeddingServiceClient | None = None,
        reranker_client: RerankerServiceClient | None = None,
        vector_store: MilvusVectorStore | None = None,
        governance_resolver: EvidenceGovernanceResolver | None = None,
        retrievable_ids_resolver: RetrievableIdsResolver | None = None,
        retrievable_context_resolver: RetrievableEvidenceContextResolver | None = None,
    ) -> None:
        """初始化`EvidenceRetriever`所需依赖和默认状态。"""
        self.embedding_client = embedding_client or get_embedding_service_client()
        self.reranker_client = reranker_client or get_reranker_service_client()
        self.vector_store = vector_store or MilvusVectorStore()
        self.governance_resolver = governance_resolver or EvidenceGovernanceResolver()
        self.retrievable_ids_resolver = retrievable_ids_resolver
        self.retrievable_context_resolver = retrievable_context_resolver

    async def search(
        self,
        query: str,
        *,
        tenant_id: str = "default",
        category: str | None = None,
        target_market: str | None = None,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """执行向量召回、证据可见性治理和重排，返回可解释的语义检索结果。"""
        try:
            embedding = await self.embedding_client.embed_texts([query])
            hits = await asyncio.to_thread(
                self.vector_store.search,
                embedding.vectors[0],
                query=query,
                tenant_id=tenant_id,
                category=category,
                target_market=target_market,
                top_k=min(max(top_k * 5, top_k), 100),
            )
        except Exception:
            return {
                "status": "degraded",
                "reason": "model service unavailable (embedding or vector retrieval service unavailable)",
                "error_code": "RETRIEVAL_SERVICE_UNAVAILABLE",
                "query": query,
                "evidence_ids": [],
                "hits": [],
                "governance": {
                    "canonical_evidence_ids": [],
                    "suppressed_evidence_ids": [],
                    "applied_review_ids": [],
                    "conflicting_review_ids": [],
                },
            }

        state_reason = None
        retrievable_context: dict[str, dict[str, Any]] = {}
        if self.retrievable_context_resolver is not None or self.retrievable_ids_resolver is not None:
            vector_hit_count = len(hits)
            try:
                evidence_ids = [str(hit.get("id")) for hit in hits if hit.get("id")]
                if self.retrievable_context_resolver is not None:
                    retrievable_context = await self.retrievable_context_resolver(
                        evidence_ids,
                        tenant_id,
                    )
                    retrievable_ids = set(retrievable_context)
                else:
                    ids_resolver = self.retrievable_ids_resolver
                    if ids_resolver is None:
                        raise RuntimeError("retrievable evidence resolver is unavailable")
                    retrievable_ids = await ids_resolver(evidence_ids, tenant_id)
            except Exception:
                return {
                    "status": "degraded",
                    "reason": "evidence availability state unavailable",
                    "error_code": "EVIDENCE_STATE_UNAVAILABLE",
                    "query": query,
                    "evidence_ids": [],
                    "hits": [],
                    "governance": {
                        "canonical_evidence_ids": [],
                        "suppressed_evidence_ids": [],
                        "applied_review_ids": [],
                        "conflicting_review_ids": [],
                    },
                }
            hits = [hit for hit in hits if str(hit.get("id")) in retrievable_ids]
            for hit in hits:
                context = retrievable_context.get(str(hit.get("id")))
                if context:
                    hit.update(context)
            if vector_hit_count > 0 and not hits:
                state_reason = "no currently retrievable evidence"
            elif len(hits) < vector_hit_count:
                state_reason = "some vector hits are no longer retrievable"

        governance_reason = None
        governance = empty_governance_result(hits)
        try:
            governance = await self.governance_resolver.resolve(hits, tenant_id=tenant_id)
        except Exception:
            governance_reason = "postgres governance unavailable (duplicate governance unavailable)"
        hits = _deduplicate_hits(governance.hits)

        if not hits:
            return {
                "status": "partial" if state_reason or governance_reason else "ready",
                "reason": _append_reason(state_reason, governance_reason),
                "query": query,
                "evidence_ids": [],
                "hits": [],
                "governance": _governance_payload(governance),
            }

        status = "partial" if state_reason or governance_reason else "ready"
        reason = _append_reason(state_reason, governance_reason)
        if any(hit.get("retrieval_mode") == "dense_fallback" for hit in hits):
            status = "partial"
            reason = _append_reason(reason, "hybrid retrieval unavailable; dense fallback used")
        try:
            reranked = await self.reranker_client.rerank(
                query,
                [{"id": hit["id"], "text": str(hit["content"])} for hit in hits],
                top_n=top_k,
            )
            hit_by_id = {hit["id"]: hit for hit in hits}
            ranked_hits = []
            for result in reranked:
                evidence_id = str(result["id"])
                if evidence_id not in hit_by_id:
                    continue
                rerank_score = result.get("score")
                if not isinstance(rerank_score, int | float | str):
                    continue
                hit = {**hit_by_id[evidence_id]}
                if not hit.get("retrieval_mode"):
                    hit["retrieval_mode"] = "dense"
                    hit["vector_score"] = hit["score"]
                hit["score"] = float(rerank_score)
                ranked_hits.append(hit)
            if ranked_hits:
                hits = ranked_hits
            else:
                status = "partial"
                reason = _append_reason(reason, "reranker returned no matching evidence")
                hits = hits[:top_k]
        except Exception:
            status = "partial"
            reason = _append_reason(reason, "reranker unavailable")
            hits = hits[:top_k]

        return {
            "status": status,
            "reason": reason,
            "query": query,
            "evidence_ids": [hit["id"] for hit in hits],
            "hits": hits,
            "governance": _governance_payload(governance),
        }


def _append_reason(current: str | None, addition: str | None) -> str | None:
    """内部辅助函数`_append_reason`；拆分主流程并集中处理当前模块的边界条件。"""
    if not current:
        return addition
    if not addition:
        return current
    return f"{current}; {addition}"


def _governance_payload(governance: RetrievalGovernanceResult) -> dict[str, list[str]]:
    """内部辅助函数`_governance_payload`；拆分主流程并集中处理当前模块的边界条件。"""
    return {
        "canonical_evidence_ids": governance.canonical_evidence_ids,
        "suppressed_evidence_ids": governance.suppressed_evidence_ids,
        "applied_review_ids": governance.applied_review_ids,
        "conflicting_review_ids": governance.conflicting_review_ids,
    }


def get_evidence_retriever() -> EvidenceRetriever:
    """实现`get_evidence_retriever`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    return EvidenceRetriever(retrievable_context_resolver=resolve_retrievable_evidence_context)


async def resolve_retrievable_evidence_ids(
    evidence_ids: list[str],
    tenant_id: str,
) -> set[str]:
    """实现`resolve_retrievable_evidence_ids`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    return set(await resolve_retrievable_evidence_context(evidence_ids, tenant_id))


async def resolve_retrievable_evidence_context(
    evidence_ids: list[str],
    tenant_id: str,
) -> dict[str, dict[str, Any]]:
    """实现`resolve_retrievable_evidence_context`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    if not evidence_ids:
        return {}
    async with async_session_factory() as session:
        records = list(
            await session.scalars(
                select(EvidenceRecord).where(
                EvidenceRecord.tenant_id == tenant_id,
                EvidenceRecord.id.in_(evidence_ids),
                EvidenceRecord.quality_status != EvidenceQualityStatus.BLOCKED.value,
                EvidenceRecord.index_status == EvidenceIndexStatus.INDEXED.value,
                )
            )
        )
    return {
        record.id: {
            "import_job_id": record.import_job_id,
            "source_name": record.source_name,
            "source_row": record.source_row,
            "source_id": record.source_id,
            "source_url": _source_url(record.metadata_json),
            "observed_at": record.observed_at,
        }
        for record in records
    }


def _source_url(metadata: Any) -> str | None:
    """内部辅助函数`_source_url`；拆分主流程并集中处理当前模块的边界条件。"""
    if not isinstance(metadata, dict):
        return None
    direct_url = metadata.get("source_url")
    if direct_url:
        return _safe_source_url(str(direct_url))
    normalized_row = metadata.get("normalized_row")
    if isinstance(normalized_row, dict) and normalized_row.get("source_url"):
        return _safe_source_url(str(normalized_row["source_url"]))
    return None


def _safe_source_url(value: str) -> str | None:
    """内部辅助函数`_safe_source_url`；拆分主流程并集中处理当前模块的边界条件。"""
    normalized = value.strip()
    parsed = urlparse(normalized)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    return normalized
