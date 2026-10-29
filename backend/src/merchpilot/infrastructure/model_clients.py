"""文件职责：封装向量与重排模型服务客户端，统一超时和失败处理。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import lru_cache

import httpx

from merchpilot.core.config import get_settings

_MODEL_REQUEST_RETRY_DELAYS = (0.5, 1.0, 2.0)


def _is_retryable_model_error(exc: Exception) -> bool:
    """判断模型服务异常是否适合通过重建连接后重试。"""
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {429, 502, 503, 504}
    return False


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    """`EmbeddingResult` 封装基础设施资源及其连接、错误和生命周期管理。"""
    model: str
    dimensions: int
    vectors: list[list[float]]


class EmbeddingServiceClient:
    """`EmbeddingServiceClient` 封装基础设施资源及其连接、错误和生命周期管理。"""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._loop: object | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """在当前事件循环内复用连接池，跨事件循环时安全重建客户端。"""
        settings = get_settings()
        loop = asyncio.get_running_loop()
        if self._client is not None and self._loop is loop:
            return self._client
        if self._client is not None:
            await self._client.aclose()
        self._loop = loop
        self._client = httpx.AsyncClient(
            base_url=settings.embedding_service_url,
            timeout=settings.model_service_timeout_seconds,
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
        )
        return self._client

    async def aclose(self) -> None:
        """关闭当前客户端连接池。"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            self._loop = None

    async def embed_texts(self, texts: list[str]) -> EmbeddingResult:
        """实现`embed_texts`基础设施操作；统一资源访问、异常和生命周期语义。"""
        if not texts:
            raise ValueError("embedding texts cannot be empty")
        for attempt in range(len(_MODEL_REQUEST_RETRY_DELAYS) + 1):
            try:
                client = await self._get_client()
                response = await client.post("/v1/embeddings", json={"texts": texts})
                response.raise_for_status()
                payload = response.json()
                vectors = payload.get("vectors")
                if not isinstance(vectors, list) or len(vectors) != len(texts):
                    raise RuntimeError("embedding service returned an invalid vector count")
                dimensions = int(payload.get("dimensions") or 0)
                if any(len(vector) != dimensions for vector in vectors):
                    raise RuntimeError("embedding service returned inconsistent vector dimensions")
                return EmbeddingResult(
                    model=str(payload.get("model") or "unknown"),
                    dimensions=dimensions,
                    vectors=vectors,
                )
            except Exception as exc:
                if not _is_retryable_model_error(exc) or attempt >= len(_MODEL_REQUEST_RETRY_DELAYS):
                    raise
                await self.aclose()
                await asyncio.sleep(_MODEL_REQUEST_RETRY_DELAYS[attempt])
        raise RuntimeError("embedding service request exhausted retries")


class RerankerServiceClient:
    """`RerankerServiceClient` 封装基础设施资源及其连接、错误和生命周期管理。"""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._loop: object | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """在当前事件循环内复用连接池，跨事件循环时安全重建客户端。"""
        settings = get_settings()
        loop = asyncio.get_running_loop()
        if self._client is not None and self._loop is loop:
            return self._client
        if self._client is not None:
            await self._client.aclose()
        self._loop = loop
        self._client = httpx.AsyncClient(
            base_url=settings.reranker_service_url,
            timeout=settings.model_service_timeout_seconds,
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
        )
        return self._client

    async def aclose(self) -> None:
        """关闭当前客户端连接池。"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            self._loop = None

    async def rerank(
        self,
        query: str,
        documents: list[dict[str, str]],
        *,
        top_n: int,
    ) -> list[dict[str, object]]:
        """实现`rerank`基础设施操作；统一资源访问、异常和生命周期语义。"""
        if not documents:
            return []
        client = await self._get_client()
        response = await client.post(
            "/v1/rerank",
            json={"query": query, "documents": documents, "top_n": top_n},
        )
        response.raise_for_status()
        results = response.json().get("results")
        if not isinstance(results, list):
            raise RuntimeError("reranker service returned invalid results")
        return results


@lru_cache(maxsize=1)
def get_embedding_service_client() -> EmbeddingServiceClient:
    """返回当前进程共享的向量模型 HTTP 连接池。"""
    return EmbeddingServiceClient()


@lru_cache(maxsize=1)
def get_reranker_service_client() -> RerankerServiceClient:
    """返回当前进程共享的重排模型 HTTP 连接池。"""
    return RerankerServiceClient()


async def close_model_service_clients() -> None:
    """关闭当前进程已经创建的模型服务 HTTP 连接池。"""
    if get_embedding_service_client.cache_info().currsize:
        await get_embedding_service_client().aclose()
        get_embedding_service_client.cache_clear()
    if get_reranker_service_client.cache_info().currsize:
        await get_reranker_service_client().aclose()
        get_reranker_service_client.cache_clear()
