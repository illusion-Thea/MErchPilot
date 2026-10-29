"""文件职责：管理 Milvus 混合集合、Dense/BM25 Sparse 检索及可用性检查。"""

from __future__ import annotations

from typing import Any, cast

from pymilvus import (
    AnnSearchRequest,
    DataType,
    Function,
    FunctionType,
    MilvusClient,
    WeightedRanker,
)

from merchpilot.core.config import Settings, get_settings


def escape_milvus_string(value: str) -> str:
    """转义Milvus过滤表达式中的字符串字面量。"""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_evidence_filter(
    *,
    tenant_id: str,
    category: str | None = None,
    target_market: str | None = None,
) -> str:
    """构造租户、证据质量和业务维度强过滤表达式。"""
    clauses = [
        f'tenant_id == "{escape_milvus_string(tenant_id)}"',
        'quality_status != "blocked"',
    ]
    if category:
        clauses.append(f'category == "{escape_milvus_string(category)}"')
    if target_market:
        clauses.append(f'target_market == "{escape_milvus_string(target_market)}"')
    return " and ".join(clauses)


class MilvusVectorStore:
    """封装证据混合索引、加权召回和兼容降级。"""

    def __init__(
        self,
        settings: Settings | None = None,
        client: MilvusClient | None = None,
    ) -> None:
        """初始化Milvus连接依赖和类型化配置。"""
        self.settings = settings or get_settings()
        self._client = client

    @property
    def client(self) -> MilvusClient:
        """惰性创建Milvus客户端，避免导入阶段建立外部连接。"""
        if self._client is None:
            self._client = MilvusClient(
                uri=self.settings.milvus_uri,
                token=self.settings.milvus_token,
                timeout=self.settings.retrieval_timeout_seconds,
            )
        return self._client

    def ensure_collection(self) -> None:
        """创建支持Dense、BM25 Sparse和中文分词的证据集合。"""
        collection_name = self.settings.milvus_collection_name
        if self.client.has_collection(collection_name=collection_name):
            return

        schema = self.client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field(
            field_name="id",
            datatype=DataType.VARCHAR,
            is_primary=True,
            max_length=64,
        )
        schema.add_field(
            field_name="vector",
            datatype=DataType.FLOAT_VECTOR,
            dim=self.settings.embedding_dimension,
        )
        schema.add_field(field_name="sparse_vector", datatype=DataType.SPARSE_FLOAT_VECTOR)
        schema.add_field(field_name="evidence_id", datatype=DataType.VARCHAR, max_length=64)
        schema.add_field(field_name="tenant_id", datatype=DataType.VARCHAR, max_length=64)
        schema.add_field(field_name="source_name", datatype=DataType.VARCHAR, max_length=255)
        schema.add_field(field_name="category", datatype=DataType.VARCHAR, max_length=128)
        schema.add_field(field_name="target_market", datatype=DataType.VARCHAR, max_length=128)
        schema.add_field(field_name="quality_status", datatype=DataType.VARCHAR, max_length=32)
        schema.add_field(
            field_name="content",
            datatype=DataType.VARCHAR,
            max_length=65_535,
            enable_analyzer=True,
            analyzer_params={
                "tokenizer": "jieba",
            },
        )
        schema.add_field(field_name="metadata_json", datatype=DataType.JSON)
        schema.add_function(
            Function(
                name="content_bm25",
                function_type=FunctionType.BM25,
                input_field_names=["content"],
                output_field_names=["sparse_vector"],
            )
        )

        index_params = self.client.prepare_index_params()
        index_params.add_index(
            field_name="vector",
            index_type="AUTOINDEX",
            metric_type="COSINE",
        )
        index_params.add_index(
            field_name="sparse_vector",
            index_type="AUTOINDEX",
            metric_type="BM25",
        )
        try:
            self.client.create_collection(
                collection_name=collection_name,
                schema=schema,
                index_params=index_params,
            )
        except Exception:
            if not self.client.has_collection(collection_name=collection_name):
                raise
        self.client.load_collection(collection_name=collection_name)

    def upsert(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """写入Dense向量与原文，Sparse向量由Milvus BM25 Function自动生成。"""
        if not rows:
            return {"upsert_count": 0}
        self.ensure_collection()
        return cast(
            dict[str, Any],
            self.client.upsert(
                collection_name=self.settings.milvus_collection_name,
                data=rows,
            ),
        )

    def delete(self, evidence_ids: list[str]) -> dict[str, Any]:
        """按证据主键删除混合索引记录。"""
        if not evidence_ids:
            return {"delete_count": 0}
        collection_name = self.settings.milvus_collection_name
        if not self.client.has_collection(collection_name=collection_name):
            return {"delete_count": 0}
        return cast(
            dict[str, Any],
            self.client.delete(
                collection_name=collection_name,
                ids=evidence_ids,
            ),
        )

    def search(
        self,
        vector: list[float],
        *,
        query: str | None = None,
        tenant_id: str,
        category: str | None = None,
        target_market: str | None = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """优先执行Dense+BM25加权召回，异常时安全降级为Dense召回。"""
        self.ensure_collection()
        filter_expression = build_evidence_filter(
            tenant_id=tenant_id,
            category=category,
            target_market=target_market,
        )
        if self.settings.milvus_hybrid_search_enabled and query:
            try:
                return self._hybrid_search(
                    vector,
                    query=query,
                    filter_expression=filter_expression,
                    top_k=top_k,
                )
            except Exception:
                return self._dense_search(
                    vector,
                    filter_expression=filter_expression,
                    top_k=top_k,
                    retrieval_mode="dense_fallback",
                )
        return self._dense_search(
            vector,
            filter_expression=filter_expression,
            top_k=top_k,
            retrieval_mode="dense",
        )

    def _hybrid_search(
        self,
        vector: list[float],
        *,
        query: str,
        filter_expression: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        """使用WeightedRanker融合语义召回和BM25关键词召回。"""
        dense_request = AnnSearchRequest(
            data=[vector],
            anns_field="vector",
            param={"metric_type": "COSINE", "params": {}},
            limit=top_k,
            filter=filter_expression,
        )
        sparse_request = AnnSearchRequest(
            data=[query],
            anns_field="sparse_vector",
            param={"metric_type": "BM25", "params": {}},
            limit=top_k,
            filter=filter_expression,
        )
        results = self.client.hybrid_search(
            collection_name=self.settings.milvus_collection_name,
            reqs=[dense_request, sparse_request],
            ranker=WeightedRanker(
                self.settings.milvus_dense_weight,
                self.settings.milvus_sparse_weight,
            ),
            limit=top_k,
            output_fields=self._output_fields(),
        )
        return self._format_hits(results, retrieval_mode="hybrid_weighted")

    def _dense_search(
        self,
        vector: list[float],
        *,
        filter_expression: str,
        top_k: int,
        retrieval_mode: str,
    ) -> list[dict[str, Any]]:
        """执行兼容模式下的Dense余弦向量召回。"""
        results = self.client.search(
            collection_name=self.settings.milvus_collection_name,
            data=[vector],
            anns_field="vector",
            filter=filter_expression,
            limit=top_k,
            output_fields=self._output_fields(),
            search_params={"metric_type": "COSINE", "params": {}},
        )
        return self._format_hits(results, retrieval_mode=retrieval_mode)

    @staticmethod
    def _output_fields() -> list[str]:
        """返回Dense与Sparse召回共用的证据字段。"""
        return [
            "evidence_id",
            "source_name",
            "category",
            "target_market",
            "quality_status",
            "content",
            "metadata_json",
        ]

    @staticmethod
    def _format_hits(
        results: list[list[dict[str, Any]]],
        *,
        retrieval_mode: str,
    ) -> list[dict[str, Any]]:
        """统一Milvus Dense和Hybrid查询返回的数据结构。"""
        hits: list[dict[str, Any]] = []
        for hit in results[0] if results else []:
            entity = hit.get("entity") or {}
            evidence_id = str(entity.get("evidence_id") or hit.get("id"))
            retrieval_score = float(hit.get("distance", hit.get("score", 0.0)))
            item = {
                "id": evidence_id,
                "score": retrieval_score,
                "retrieval_mode": retrieval_mode,
                "source_name": entity.get("source_name"),
                "category": entity.get("category"),
                "target_market": entity.get("target_market"),
                "quality_status": entity.get("quality_status"),
                "content": entity.get("content", ""),
                "metadata": entity.get("metadata_json") or {},
            }
            if retrieval_mode == "hybrid_weighted":
                item["hybrid_score"] = retrieval_score
            else:
                item["vector_score"] = retrieval_score
            hits.append(item)
        return hits
