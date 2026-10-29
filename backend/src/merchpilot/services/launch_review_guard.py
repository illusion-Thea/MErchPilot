"""文件职责：集中校验上市评审提交、领取、决定与最终上市确认规则。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from merchpilot.services.idempotency import idempotency_payload_hash


def launch_review_fingerprint(
    *,
    initiative_id: str,
    project_id: str,
    run_id: str,
    selected_product_id: str,
    initiative_status: str,
    owner_id: str | None,
    target_launch_date: date | str | None,
    budget: float | None,
    notes: str | None,
    milestones: list[dict[str, Any]],
    readiness: dict[str, Any],
    pilot_summary: dict[str, Any],
    pending_review: dict[str, Any] | None,
) -> str:
    """实现`launch_review_fingerprint`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    return idempotency_payload_hash(
        {
            "initiative_id": initiative_id,
            "project_id": project_id,
            "run_id": run_id,
            "selected_product_id": selected_product_id,
            "initiative_status": initiative_status,
            "owner_id": owner_id,
            "target_launch_date": (
                target_launch_date.isoformat()
                if isinstance(target_launch_date, (date, datetime))
                else target_launch_date
            ),
            "budget": budget,
            "notes": notes,
            "milestones": milestones,
            "readiness": readiness,
            "pilot_summary": pilot_summary,
            "pending_review": pending_review,
        }
    )
