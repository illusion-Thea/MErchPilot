"""文件职责：依据证据、财务和供应链结果生成可解释机会评分卡。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _number(value: object) -> float | None:
    """内部辅助函数`_number`；拆分主流程并集中处理当前模块的边界条件。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _filled(value: object) -> bool:
    """内部辅助函数`_filled`；拆分主流程并集中处理当前模块的边界条件。"""
    if value is None or value == "":
        return False
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return True


def build_scorecard(
    evidence_ids: Sequence[str],
    finance: Mapping[str, Any],
    supplier: Mapping[str, Any],
    constraints: Mapping[str, Any],
    metrics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """实现`build_scorecard`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    unique_evidence_ids = sorted({item for item in evidence_ids if item})
    evidence_count = len(unique_evidence_ids)
    evidence_score = round(min(evidence_count / 5, 1) * 30)

    finance_status = str(finance.get("status") or "requires_cost_data")
    finance_score = 0
    margin_rate = _number(finance.get("margin_rate"))
    target_margin = _number(finance.get("target_margin"))
    if finance_status == "ready" and margin_rate is not None:
        finance_score = 15
        benchmark = target_margin if target_margin is not None and target_margin > 0 else 0.4
        finance_score += round(min(max(margin_rate / benchmark, 0), 1) * 20)

    supplier_status = str(supplier.get("status") or "requires_supplier_data")
    risk_flags_raw = supplier.get("risk_flags")
    risk_flags = (
        [str(item) for item in risk_flags_raw if item]
        if isinstance(risk_flags_raw, list)
        else []
    )
    if supplier_status == "ready":
        supplier_score = max(20 - len(risk_flags) * 4, 8)
    elif supplier_status == "partial":
        missing_fields = supplier.get("missing_fields")
        missing_count = len(missing_fields) if isinstance(missing_fields, list) else 3
        supplier_score = max(round((3 - min(missing_count, 3)) / 3 * 12), 0)
    else:
        supplier_score = 0

    completeness_checks = [
        _filled(constraints.get("target_user")),
        target_margin is not None,
        finance.get("selling_price") is not None,
        finance.get("unit_cost") is not None,
        _filled(supplier.get("supplier_name")),
        supplier.get("moq") is not None,
        supplier.get("lead_time_days") is not None,
    ]
    completed_fields = sum(completeness_checks)
    completeness_score = round(completed_fields / len(completeness_checks) * 15)

    total_score = min(evidence_score + finance_score + supplier_score + completeness_score, 100)
    blockers: list[str] = []
    warnings: list[str] = []
    if evidence_count == 0:
        blockers.append("缺少可追溯的市场、竞品或用户证据")
    if finance_status == "requires_cost_data":
        blockers.append("缺少售价或单位成本，无法完成财务测算")
    elif finance_status == "invalid_constraints":
        blockers.append("财务参数存在无效值")
    elif finance_status == "unviable":
        blockers.append("单位贡献毛利不为正")
    if supplier_status == "requires_supplier_data":
        warnings.append("尚未提供供应商、MOQ 和交期信息")
    elif supplier_status == "partial":
        warnings.append("供应商信息不完整")
    if risk_flags:
        warnings.append(f"供应商存在 {len(risk_flags)} 项风险提示")

    coverage = metrics.get("coverage") if isinstance(metrics, Mapping) else None
    if isinstance(coverage, Mapping):
        missing_dimensions = [
            label
            for key, label in (
                ("market_trend", "市场趋势"),
                ("competitor", "竞品"),
                ("user_reviews", "用户评论"),
            )
            if not coverage.get(key)
        ]
        if missing_dimensions:
            warnings.append(f"结构化数据缺少：{'、'.join(missing_dimensions)}")

    if blockers:
        score_status = "blocked"
        reason = "；".join(blockers)
    elif finance_status != "ready" or supplier_status != "ready" or risk_flags:
        score_status = "partial"
        reason = "；".join(warnings) or "关键业务信息仍待补全"
    else:
        score_status = "ready"
        reason = "证据、财务和供应商信息已满足初步决策条件"

    return {
        "score": total_score,
        "status": score_status,
        "reason": reason,
        "evidence_count": evidence_count,
        "evidence_ids": unique_evidence_ids,
        "breakdown": {
            "evidence": {"score": evidence_score, "max_score": 30},
            "finance": {"score": finance_score, "max_score": 35},
            "supplier": {"score": supplier_score, "max_score": 20},
            "completeness": {"score": completeness_score, "max_score": 15},
        },
        "data_coverage": dict(coverage) if isinstance(coverage, Mapping) else {},
        "metrics_record_count": (
            int(metrics.get("record_count") or 0) if isinstance(metrics, Mapping) else 0
        ),
        "blockers": blockers,
        "warnings": warnings,
    }
