"""文件职责：写入不可变业务审计事件，并生成稳定的排序序列。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from merchpilot.adapters.providers import get_telemetry_provider
from merchpilot.core.ids import new_id
from merchpilot.core.logging import get_logger
from merchpilot.infrastructure.models import AuditEvent

logger = get_logger("audit")


def record_audit_event(
    session: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    project_id: str | None = None,
    tenant_id: str = "default",
    actor_id: str = "system",
    detail: dict[str, Any] | None = None,
) -> AuditEvent:
    """实现`record_audit_event`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    event = AuditEvent(
        id=new_id("audit"),
        tenant_id=tenant_id,
        project_id=project_id,
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        detail=detail or {},
    )
    session.add(event)
    try:
        get_telemetry_provider().emit_event(
            action,
            {
                "audit_id": event.id,
                "tenant_id": tenant_id,
                "actor_id": actor_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "project_id": project_id,
                "detail_keys": sorted(detail or {}),
            },
        )
    except Exception as exc:
        logger.warning(
            "audit_telemetry_emit_failed",
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            error=str(exc),
        )
    return event
