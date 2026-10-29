"""文件职责：创建 FastAPI 应用，管理数据库、缓存、企业适配器与服务生命周期。"""

from __future__ import annotations

import asyncio
from typing import TypedDict

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from starlette.responses import Response

from merchpilot.core.config import get_settings
from merchpilot.model_service.runtime import (
    get_embedding_model,
    get_reranker_model,
    resolve_device,
    resolve_model_dtype,
)
from merchpilot.observability.prometheus import render_metrics
from merchpilot.observability.resilience import ModelCircuitOpen, ModelServiceBusy, ModelServiceGuard

settings = get_settings()
app = FastAPI(title="MerchPilot Model Service", version="0.1.0")
embedding_guard = ModelServiceGuard("embedding")
reranker_guard = ModelServiceGuard("reranker")


class EmbeddingRequest(BaseModel):
    """`EmbeddingRequest` 封装本模块相关状态和行为，对调用方提供清晰边界。"""
    texts: list[str] = Field(min_length=1, max_length=256)


class EmbeddingResponse(BaseModel):
    """`EmbeddingResponse` 封装本模块相关状态和行为，对调用方提供清晰边界。"""
    model: str
    dimensions: int
    vectors: list[list[float]]


class RerankItem(BaseModel):
    """`RerankItem` 封装本模块相关状态和行为，对调用方提供清晰边界。"""
    id: str
    text: str


class RerankRequest(BaseModel):
    """`RerankRequest` 封装本模块相关状态和行为，对调用方提供清晰边界。"""
    query: str
    documents: list[RerankItem] = Field(min_length=1, max_length=100)
    top_n: int = Field(default=10, ge=1, le=100)


class RerankResult(TypedDict):
    """`RerankResult` 封装本模块相关状态和行为，对调用方提供清晰边界。"""
    id: str
    score: float
    text: str


@app.get("/health")
async def health() -> dict[str, object]:
    """实现`health`流程；输入、输出和异常语义由类型标注及调用方约束。"""
    role = settings.model_service_role
    paths = {
        "embedding": settings.embedding_model_path.exists(),
        "reranker": settings.reranker_model_path.exists(),
    }
    required = [role] if role in paths else list(paths)
    device = resolve_device()
    return {
        "status": "ok" if all(paths[item] for item in required) else "degraded",
        "role": role,
        "device": device,
        "dtype": str(resolve_model_dtype(device)).removeprefix("torch."),
        "cpu_threads": settings.model_cpu_threads,
        "models": paths,
    }


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """输出当前模型实例的 Prometheus 指标。"""
    payload, content_type = render_metrics()
    return Response(payload, media_type=content_type)


@app.post("/v1/embeddings", response_model=EmbeddingResponse)
async def create_embeddings(payload: EmbeddingRequest) -> EmbeddingResponse:
    """实现`create_embeddings`流程；输入、输出和异常语义由类型标注及调用方约束。"""
    if settings.model_service_role not in {"all", "embedding"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="embedding endpoint disabled")
    try:
        async with embedding_guard.slot():
            vectors = await asyncio.to_thread(get_embedding_model().embed_documents, payload.texts)
    except (ModelServiceBusy, ModelCircuitOpen) as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    dimensions = len(vectors[0]) if vectors else 0
    return EmbeddingResponse(
        model=settings.embedding_model_version,
        dimensions=dimensions,
        vectors=vectors,
    )


@app.post("/v1/rerank")
async def rerank(payload: RerankRequest) -> dict[str, object]:
    """实现`rerank`流程；输入、输出和异常语义由类型标注及调用方约束。"""
    if settings.model_service_role not in {"all", "reranker"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="reranker endpoint disabled")
    pairs = [(payload.query, item.text) for item in payload.documents]
    try:
        async with reranker_guard.slot():
            scores = await asyncio.to_thread(get_reranker_model().predict, pairs)
    except (ModelServiceBusy, ModelCircuitOpen) as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    ranked: list[RerankResult] = sorted(
        [
            {"id": item.id, "score": float(score), "text": item.text}
            for item, score in zip(payload.documents, scores, strict=True)
        ],
        key=lambda item: item["score"],
        reverse=True,
    )
    return {"model": settings.reranker_model_version, "results": ranked[: payload.top_n]}
