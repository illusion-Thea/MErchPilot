"""文件职责：提供证据语义检索和检索诊断接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from merchpilot.api.dependencies import get_current_identity
from merchpilot.api.schemas import RetrievalSearchRead, RetrievalSearchRequest
from merchpilot.ports.identity import Identity
from merchpilot.services.retrieval import get_evidence_retriever

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


@router.post("/search", response_model=RetrievalSearchRead)
async def search_evidence(
    payload: RetrievalSearchRequest,
    identity: Identity = Depends(get_current_identity),
) -> RetrievalSearchRead:
    """处理`POST /search`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    query = payload.query.strip()
    if len(query) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="检索问题至少需要 2 个有效字符",
        )
    result = await get_evidence_retriever().search(
        query,
        tenant_id=identity.tenant_id,
        category=payload.category.strip() if payload.category else None,
        target_market=payload.target_market.strip() if payload.target_market else None,
        top_k=payload.top_k,
    )
    result["hits"] = [
        {
            "evidence_id": hit.get("id"),
            **{key: value for key, value in hit.items() if key != "id"},
        }
        for hit in result["hits"]
    ]
    return RetrievalSearchRead.model_validate(result)
