"""文件职责：验证 retrieval 相关规则、边界与回归行为。"""

from merchpilot.infrastructure.model_clients import EmbeddingResult
from merchpilot.services.retrieval import EvidenceRetriever, _source_url
from merchpilot.services.retrieval_governance import empty_governance_result


class StubEmbeddingClient:
    """提供`StubEmbeddingClient`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
    async def embed_texts(self, texts: list[str]) -> EmbeddingResult:
        """辅助构造`embed texts`测试数据或依赖，减少用例中的重复准备代码。"""
        assert texts == ["中国 水杯 市场趋势"]
        return EmbeddingResult(model="test", dimensions=3, vectors=[[0.1, 0.2, 0.3]])


class StubVectorStore:
    """提供`StubVectorStore`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
    def search(self, vector: list[float], **kwargs: object) -> list[dict[str, object]]:
        """辅助构造`search`测试数据或依赖，减少用例中的重复准备代码。"""
        assert vector == [0.1, 0.2, 0.3]
        assert kwargs["tenant_id"] == "default"
        assert kwargs["query"] == "中国 水杯 市场趋势"
        return [
            {
                "id": "evidence-1",
                "score": 0.7,
                "hybrid_score": 0.7,
                "retrieval_mode": "hybrid_weighted",
                "content": "市场增长",
                "metadata": {},
            },
            {
                "id": "evidence-2",
                "score": 0.8,
                "hybrid_score": 0.8,
                "retrieval_mode": "hybrid_weighted",
                "content": "价格带变化",
                "metadata": {},
            },
        ]


class StubRerankerClient:
    """提供`StubRerankerClient`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
    async def rerank(
        self,
        query: str,
        documents: list[dict[str, str]],
        *,
        top_n: int,
    ) -> list[dict[str, object]]:
        """辅助构造`rerank`测试数据或依赖，减少用例中的重复准备代码。"""
        assert query == "中国 水杯 市场趋势"
        assert top_n == 1
        assert len(documents) == 2
        return [{"id": "evidence-2", "score": 0.95, "text": "价格带变化"}]


class DenseFallbackVectorStore:
    """返回可观察的Dense降级结果。"""

    def search(self, vector: list[float], **kwargs: object) -> list[dict[str, object]]:
        del vector, kwargs
        return [
            {
                "id": "evidence-1",
                "score": 0.7,
                "vector_score": 0.7,
                "retrieval_mode": "dense_fallback",
                "content": "市场增长",
                "metadata": {},
            },
            {
                "id": "evidence-2",
                "score": 0.8,
                "vector_score": 0.8,
                "retrieval_mode": "dense_fallback",
                "content": "价格带变化",
                "metadata": {},
            },
        ]


class PassthroughGovernanceResolver:
    """提供`PassthroughGovernanceResolver`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
    async def resolve(
        self,
        hits: list[dict[str, object]],
        *,
        tenant_id: str,
    ):
        """辅助构造`resolve`测试数据或依赖，减少用例中的重复准备代码。"""
        assert tenant_id == "default"
        return empty_governance_result(hits)


class FailingGovernanceResolver:
    """提供`FailingGovernanceResolver`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
    async def resolve(
        self,
        hits: list[dict[str, object]],
        *,
        tenant_id: str,
    ):
        """辅助构造`resolve`测试数据或依赖，减少用例中的重复准备代码。"""
        del hits, tenant_id
        raise ConnectionError("postgres governance unavailable")


class FailingEmbeddingClient:
    """提供`FailingEmbeddingClient`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
    async def embed_texts(self, texts: list[str]) -> EmbeddingResult:
        """辅助构造`embed texts`测试数据或依赖，减少用例中的重复准备代码。"""
        del texts
        raise ConnectionError("model service unavailable")


class CurrentStateFilteringResolver:
    """提供`CurrentStateFilteringResolver`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
    async def __call__(self, evidence_ids: list[str], tenant_id: str) -> set[str]:
        """辅助构造`call`测试数据或依赖，减少用例中的重复准备代码。"""
        assert tenant_id == "default"
        assert evidence_ids == ["evidence-1", "evidence-2"]
        return {"evidence-2"}


class CurrentContextFilteringResolver:
    """提供`CurrentContextFilteringResolver`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
    async def __call__(self, evidence_ids: list[str], tenant_id: str) -> dict[str, dict[str, object]]:
        """辅助构造`call`测试数据或依赖，减少用例中的重复准备代码。"""
        assert tenant_id == "default"
        assert evidence_ids == ["evidence-1", "evidence-2"]
        return {
            "evidence-2": {
                "import_job_id": "import-2",
                "source_name": "market.xlsx",
                "source_row": 8,
                "source_id": "source-2",
                "source_url": "https://example.com/source-2",
            }
        }


class SingleHitRerankerClient:
    """提供`SingleHitRerankerClient`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
    async def rerank(
        self,
        query: str,
        documents: list[dict[str, str]],
        *,
        top_n: int,
    ) -> list[dict[str, object]]:
        """辅助构造`rerank`测试数据或依赖，减少用例中的重复准备代码。"""
        assert query == "中国 水杯 市场趋势"
        assert top_n == 1
        assert [document["id"] for document in documents] == ["evidence-2"]
        return [{"id": "evidence-2", "score": 0.95, "text": documents[0]["text"]}]


class DuplicateVectorStore:
    """提供`DuplicateVectorStore`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
    def search(self, vector: list[float], **kwargs: object) -> list[dict[str, object]]:
        """辅助构造`search`测试数据或依赖，减少用例中的重复准备代码。"""
        del vector, kwargs
        return [
            {
                "id": "warning-copy",
                "score": 0.9,
                "content": "通勤保温杯支持温度显示",
                "quality_status": "warning",
                "metadata": {},
            },
            {
                "id": "verified-copy",
                "score": 0.8,
                "content": "通勤保温杯支持温度显示",
                "quality_status": "verified",
                "metadata": {},
            },
            {
                "id": "other",
                "score": 0.7,
                "content": "学生保温杯关注轻量和价格",
                "quality_status": "verified",
                "metadata": {},
            },
        ]


class DedupingRerankerClient:
    """提供`DedupingRerankerClient`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
    async def rerank(
        self,
        query: str,
        documents: list[dict[str, str]],
        *,
        top_n: int,
    ) -> list[dict[str, object]]:
        """辅助构造`rerank`测试数据或依赖，减少用例中的重复准备代码。"""
        del query, top_n
        assert [document["id"] for document in documents] == ["verified-copy", "other"]
        return [{"id": "verified-copy", "score": 0.99, "text": documents[0]["text"]}]


async def test_retrieval_reranks_vector_hits() -> None:
    """验证“retrieval reranks vector hits”场景，确保业务规则、权限和异常边界保持稳定。"""
    retriever = EvidenceRetriever(
        embedding_client=StubEmbeddingClient(),
        reranker_client=StubRerankerClient(),
        vector_store=StubVectorStore(),
        governance_resolver=PassthroughGovernanceResolver(),
    )

    result = await retriever.search("中国 水杯 市场趋势", top_k=1)

    assert result["status"] == "ready"
    assert result["evidence_ids"] == ["evidence-2"]
    assert result["hits"][0]["score"] == 0.95
    assert result["hits"][0]["hybrid_score"] == 0.8
    assert result["hits"][0]["retrieval_mode"] == "hybrid_weighted"


async def test_retrieval_degrades_when_embedding_service_is_unavailable() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    retriever = EvidenceRetriever(embedding_client=FailingEmbeddingClient())

    result = await retriever.search("中国 水杯 市场趋势")

    assert result["status"] == "degraded"
    assert result["evidence_ids"] == []
    assert "model service unavailable" in result["reason"]


async def test_retrieval_reports_dense_fallback_as_partial() -> None:
    """验证混合召回降级后仍执行Cross-Encoder并暴露降级原因。"""
    retriever = EvidenceRetriever(
        embedding_client=StubEmbeddingClient(),
        reranker_client=StubRerankerClient(),
        vector_store=DenseFallbackVectorStore(),
        governance_resolver=PassthroughGovernanceResolver(),
    )

    result = await retriever.search("中国 水杯 市场趋势", top_k=1)

    assert result["status"] == "partial"
    assert "dense fallback used" in result["reason"]
    assert result["hits"][0]["retrieval_mode"] == "dense_fallback"


async def test_retrieval_filters_stale_vector_hits_by_current_postgres_state() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    retriever = EvidenceRetriever(
        embedding_client=StubEmbeddingClient(),
        reranker_client=SingleHitRerankerClient(),
        vector_store=StubVectorStore(),
        governance_resolver=PassthroughGovernanceResolver(),
        retrievable_ids_resolver=CurrentStateFilteringResolver(),
    )

    result = await retriever.search("中国 水杯 市场趋势", top_k=1)

    assert result["status"] == "partial"
    assert result["evidence_ids"] == ["evidence-2"]
    assert result["hits"][0]["id"] == "evidence-2"


async def test_retrieval_adds_authoritative_source_context() -> None:
    """验证“retrieval adds authoritative source context”场景，确保业务规则、权限和异常边界保持稳定。"""
    retriever = EvidenceRetriever(
        embedding_client=StubEmbeddingClient(),
        reranker_client=SingleHitRerankerClient(),
        vector_store=StubVectorStore(),
        governance_resolver=PassthroughGovernanceResolver(),
        retrievable_context_resolver=CurrentContextFilteringResolver(),
    )

    result = await retriever.search("中国 水杯 市场趋势", top_k=1)

    assert result["hits"][0]["source_name"] == "market.xlsx"
    assert result["hits"][0]["import_job_id"] == "import-2"
    assert result["hits"][0]["source_row"] == 8
    assert result["hits"][0]["source_id"] == "source-2"
    assert result["hits"][0]["source_url"] == "https://example.com/source-2"


async def test_retrieval_drops_unsafe_source_urls() -> None:
    """验证“retrieval drops unsafe source urls”场景，确保业务规则、权限和异常边界保持稳定。"""
    assert _source_url({"source_url": "javascript:alert(1)"}) is None
    assert _source_url({"source_url": "https://example.com/source"}) == "https://example.com/source"


async def test_retrieval_reports_stale_vector_hits_as_partial() -> None:
    """验证“retrieval reports stale vector hits as partial”场景，确保业务规则、权限和异常边界保持稳定。"""
    async def no_retrievable_evidence(evidence_ids: list[str], tenant_id: str) -> set[str]:
        """辅助构造`no retrievable evidence`测试数据或依赖，减少用例中的重复准备代码。"""
        del evidence_ids, tenant_id
        return set()

    retriever = EvidenceRetriever(
        embedding_client=StubEmbeddingClient(),
        vector_store=StubVectorStore(),
        governance_resolver=PassthroughGovernanceResolver(),
        retrievable_ids_resolver=no_retrievable_evidence,
    )

    result = await retriever.search("中国 水杯 市场趋势")

    assert result["status"] == "partial"
    assert result["hits"] == []
    assert result["reason"] == "no currently retrievable evidence"


async def test_retrieval_deduplicates_content_and_prefers_verified_evidence() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    retriever = EvidenceRetriever(
        embedding_client=StubEmbeddingClient(),
        reranker_client=DedupingRerankerClient(),
        vector_store=DuplicateVectorStore(),
        governance_resolver=PassthroughGovernanceResolver(),
    )

    result = await retriever.search("中国 水杯 市场趋势", top_k=1)

    assert result["status"] == "ready"
    assert result["evidence_ids"] == ["verified-copy"]
    assert result["hits"][0]["quality_status"] == "verified"


async def test_retrieval_continues_when_duplicate_governance_is_unavailable() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    retriever = EvidenceRetriever(
        embedding_client=StubEmbeddingClient(),
        reranker_client=StubRerankerClient(),
        vector_store=StubVectorStore(),
        governance_resolver=FailingGovernanceResolver(),
    )

    result = await retriever.search("中国 水杯 市场趋势", top_k=1)

    assert result["status"] == "partial"
    assert result["evidence_ids"] == ["evidence-2"]
    assert "postgres governance unavailable" in result["reason"]
