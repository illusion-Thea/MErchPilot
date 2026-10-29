"""文件职责：维护跨入口写操作幂等账本，防止重试造成重复业务事实。"""

from __future__ import annotations

import hashlib
import json
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from merchpilot.core.ids import new_id
from merchpilot.infrastructure.models import IdempotencyRecord


def idempotency_payload_hash(payload: dict[str, Any]) -> str:
    """实现`idempotency_payload_hash`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def find_idempotency_record(
    session: AsyncSession,
    *,
    tenant_id: str,
    actor_id: str,
    operation: str,
    idempotency_key: str,
) -> IdempotencyRecord | None:
    """实现`find_idempotency_record`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    return cast(
        IdempotencyRecord | None,
        await session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.tenant_id == tenant_id,
                IdempotencyRecord.actor_id == actor_id,
                IdempotencyRecord.operation == operation,
                IdempotencyRecord.idempotency_key == idempotency_key,
            )
        )
    )


def build_idempotency_record(
    *,
    tenant_id: str,
    actor_id: str,
    operation: str,
    idempotency_key: str,
    payload_hash: str,
    client_name: str,
    resource_type: str,
    resource_id: str,
    response_snapshot: dict[str, Any],
) -> IdempotencyRecord:
    """实现`build_idempotency_record`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    return IdempotencyRecord(
        id=new_id("idempotency"),
        tenant_id=tenant_id,
        actor_id=actor_id,
        operation=operation,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        client_name=client_name,
        resource_type=resource_type,
        resource_id=resource_id,
        response_snapshot=response_snapshot,
    )
