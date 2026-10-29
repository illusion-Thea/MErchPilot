"""文件职责：从PostgreSQL一键重建Milvus Dense+BM25混合证据索引。"""

from __future__ import annotations

import asyncio
import json

from merchpilot.infrastructure.database import engine
from merchpilot.infrastructure.model_clients import close_model_service_clients
from merchpilot.services.evidence_indexing import rebuild_hybrid_evidence_index


async def _main() -> None:
    """执行索引重建并释放数据库及模型客户端资源。"""
    try:
        result = await rebuild_hybrid_evidence_index()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        await close_model_service_clients()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
