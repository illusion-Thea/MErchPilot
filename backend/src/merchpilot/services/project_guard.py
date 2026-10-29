"""文件职责：校验规划项目启动、修订、恢复和归档等生命周期门禁。"""

from __future__ import annotations

from typing import Any

from merchpilot.services.idempotency import idempotency_payload_hash


def project_configuration_fingerprint(
    *,
    name: str,
    category: str,
    target_market: str,
    constraints: dict[str, Any],
) -> str:
    """实现`project_configuration_fingerprint`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    return idempotency_payload_hash(
        {
            "name": name,
            "category": category,
            "target_market": target_market,
            "constraints": constraints,
        }
    )
