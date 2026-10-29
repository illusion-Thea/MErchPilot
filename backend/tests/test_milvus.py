"""文件职责：验证 milvus 相关规则、边界与回归行为。"""

from typing import Any

from merchpilot.core.config import Settings
from merchpilot.infrastructure.milvus import (
    MilvusVectorStore,
    build_evidence_filter,
    escape_milvus_string,
)


def test_escape_milvus_string() -> None:
    """验证“escape milvus string”场景，确保业务规则、权限和异常边界保持稳定。"""
    assert escape_milvus_string('华东"重点\\市场') == '华东\\"重点\\\\市场'


def test_build_evidence_filter_includes_tenant_and_dimensions() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    expression = build_evidence_filter(
        tenant_id="tenant-a",
        category="水杯",
        target_market="中国",
    )

    assert 'tenant_id == "tenant-a"' in expression
    assert 'quality_status != "blocked"' in expression
    assert 'category == "水杯"' in expression
    assert 'target_market == "中国"' in expression


def test_vector_store_deletes_evidence_by_primary_key() -> None:
    """验证“vector store deletes evidence by primary key”场景，确保业务规则、权限和异常边界保持稳定。"""
    class FakeClient:
        """提供`FakeClient`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
        deleted_ids: list[str] = []

        def has_collection(self, *, collection_name: str) -> bool:
            """辅助构造`has collection`测试数据或依赖，减少用例中的重复准备代码。"""
            assert collection_name
            return True

        def delete(self, *, collection_name: str, ids: list[str]) -> dict[str, int]:
            """辅助构造`delete`测试数据或依赖，减少用例中的重复准备代码。"""
            assert collection_name
            self.deleted_ids = ids
            return {"delete_count": len(ids)}

    client = FakeClient()
    store = MilvusVectorStore(client=client)

    result = store.delete(["evidence-1", "evidence-2"])

    assert result == {"delete_count": 2}
    assert client.deleted_ids == ["evidence-1", "evidence-2"]


def test_vector_store_uses_weighted_dense_sparse_hybrid_search() -> None:
    """验证Dense与BM25 Sparse按照配置权重融合。"""
    class FakeClient:
        """记录混合检索请求，返回单条融合结果。"""

        requests: list[Any] = []
        ranker: Any = None

        def has_collection(self, *, collection_name: str) -> bool:
            assert collection_name == "hybrid-test"
            return True

        def hybrid_search(self, **kwargs: Any) -> list[list[dict[str, Any]]]:
            self.requests = kwargs["reqs"]
            self.ranker = kwargs["ranker"]
            return [[{
                "id": "evidence-1",
                "distance": 0.88,
                "entity": {
                    "evidence_id": "evidence-1",
                    "content": "316L不锈钢保温杯",
                    "quality_status": "verified",
                    "metadata_json": {},
                },
            }]]

    client = FakeClient()
    settings = Settings(
        _env_file=None,
        milvus_collection_name="hybrid-test",
        milvus_dense_weight=0.7,
        milvus_sparse_weight=0.3,
    )
    store = MilvusVectorStore(settings=settings, client=client)

    hits = store.search(
        [0.1, 0.2, 0.3],
        query="316L 保温杯",
        tenant_id="tenant-a",
        top_k=5,
    )

    assert [request.anns_field for request in client.requests] == ["vector", "sparse_vector"]
    assert client.requests[1].data == ["316L 保温杯"]
    assert client.ranker.dict()["params"]["weights"] == [0.7, 0.3]
    assert hits[0]["retrieval_mode"] == "hybrid_weighted"
    assert hits[0]["hybrid_score"] == 0.88


def test_vector_store_falls_back_to_dense_when_hybrid_search_fails() -> None:
    """验证混合检索不可用时返回可观察的Dense降级结果。"""
    class FakeClient:
        """模拟混合检索失败和Dense检索成功。"""

        def has_collection(self, *, collection_name: str) -> bool:
            assert collection_name == "hybrid-test"
            return True

        def hybrid_search(self, **kwargs: Any) -> list[list[dict[str, Any]]]:
            del kwargs
            raise RuntimeError("BM25 unavailable")

        def search(self, **kwargs: Any) -> list[list[dict[str, Any]]]:
            assert kwargs["anns_field"] == "vector"
            return [[{
                "id": "evidence-1",
                "distance": 0.72,
                "entity": {
                    "evidence_id": "evidence-1",
                    "content": "通勤保温杯",
                    "quality_status": "verified",
                    "metadata_json": {},
                },
            }]]

    store = MilvusVectorStore(
        settings=Settings(_env_file=None, milvus_collection_name="hybrid-test"),
        client=FakeClient(),
    )

    hits = store.search([0.1, 0.2, 0.3], query="保温杯", tenant_id="tenant-a")

    assert hits[0]["retrieval_mode"] == "dense_fallback"
    assert hits[0]["vector_score"] == 0.72
