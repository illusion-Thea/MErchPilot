"""文件职责：校验选品验证状态变化及进入商品立项的硬性门禁。"""

from __future__ import annotations

from typing import Any

from merchpilot.services.idempotency import idempotency_payload_hash


def validation_review_fingerprint(
    *,
    project_id: str,
    run_id: str,
    run_status: str,
    candidate_id: str,
    validation_plan: dict[str, Any],
) -> str:
    """实现`validation_review_fingerprint`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    reviewed_plan = {
        key: value for key, value in validation_plan.items() if key != "review_token"
    }
    return idempotency_payload_hash(
        {
            "project_id": project_id,
            "run_id": run_id,
            "run_status": run_status,
            "candidate_id": candidate_id,
            "validation_plan": reviewed_plan,
        }
    )
