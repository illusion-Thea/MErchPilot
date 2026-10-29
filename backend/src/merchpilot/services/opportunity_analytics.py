"""文件职责：从规划运行产出提炼机会指标和可视化分析数据。"""

from __future__ import annotations

from typing import Any


def _record(value: object) -> dict[str, Any]:
    """内部辅助函数`_record`；拆分主流程并集中处理当前模块的边界条件。"""
    return value if isinstance(value, dict) else {}


def _number(value: object) -> float | None:
    """内部辅助函数`_number`；拆分主流程并集中处理当前模块的边界条件。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def extract_opportunity_metrics(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """实现`extract_opportunity_metrics`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    outputs = _record((snapshot or {}).get("outputs"))
    scorecard = _record(outputs.get("scorecard"))
    finance = _record(outputs.get("finance"))
    supplier = _record(outputs.get("supplier"))
    score_value = _number(scorecard.get("score"))
    evidence_value = _number(scorecard.get("evidence_count"))
    return {
        "score": int(score_value) if score_value is not None else None,
        "score_status": (
            str(scorecard["status"]) if isinstance(scorecard.get("status"), str) else None
        ),
        "evidence_count": int(evidence_value) if evidence_value is not None else 0,
        "margin_rate": _number(finance.get("margin_rate")),
        "supplier_risk": (
            str(supplier["risk_level"])
            if isinstance(supplier.get("risk_level"), str)
            else None
        ),
        "score_breakdown": _record(scorecard.get("breakdown")),
    }
