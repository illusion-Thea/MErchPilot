"""文件职责：写入不可变业务审计事件，并生成稳定的排序序列。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from merchpilot.api.dependencies import require_admin
from merchpilot.api.schemas import AuditEventRead
from merchpilot.infrastructure.database import get_db_session
from merchpilot.infrastructure.models import AuditEvent
from merchpilot.ports.identity import Identity

router = APIRouter(prefix="/audit-events", tags=["audit-events"])


@router.get("", response_model=list[AuditEventRead])
async def list_audit_events(
    response: Response,
    project_id: str | None = None,
    entity_type: str | None = None,
    action: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100_000),
    identity: Identity = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> list[AuditEvent]:
    """处理`GET `接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    conditions = [AuditEvent.tenant_id == identity.tenant_id]
    if project_id is not None:
        conditions.append(AuditEvent.project_id == project_id)
    if entity_type is not None:
        conditions.append(AuditEvent.entity_type == entity_type)
    if action is not None:
        conditions.append(AuditEvent.action == action)
    total = await session.scalar(select(func.count(AuditEvent.id)).where(*conditions))
    response.headers["X-Total-Count"] = str(int(total or 0))
    result = await session.scalars(
        select(AuditEvent)
        .where(*conditions)
        .order_by(AuditEvent.sequence_no.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result)
