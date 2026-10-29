"""文件职责：集中校验规划审批的领取、决定、幂等和状态转换规则。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from merchpilot.services.idempotency import idempotency_payload_hash


def _canonical_due_at(value: datetime | str | None) -> str | None:
    """把数据库时间和 API 时间统一为可复现的 UTC 字符串。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if value.endswith("Z"):
        return value
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    normalized = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


def approval_review_fingerprint(
    *,
    task_id: str,
    project_id: str,
    run_id: str,
    approval_type: str,
    checkpoint_ref: str,
    status: str,
    assignee_id: str | None,
    due_at: datetime | str | None,
    summary: dict[str, Any],
) -> str:
    """实现`approval_review_fingerprint`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    return idempotency_payload_hash(
        {
            "task_id": task_id,
            "project_id": project_id,
            "run_id": run_id,
            "approval_type": approval_type,
            "checkpoint_ref": checkpoint_ref,
            "status": status,
            "assignee_id": assignee_id,
            "due_at": _canonical_due_at(due_at),
            "summary": summary,
        }
    )
