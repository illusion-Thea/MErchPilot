"""文件职责：评估 MOQ、交期、评级等供应链约束和风险。"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any


def _positive_integer(value: object) -> int | None:
    """内部辅助函数`_positive_integer`；拆分主流程并集中处理当前模块的边界条件。"""
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite() or parsed <= 0 or parsed != parsed.to_integral_value():
        return None
    return int(parsed)


def _non_negative_number(value: object) -> float | None:
    """内部辅助函数`_non_negative_number`；拆分主流程并集中处理当前模块的边界条件。"""
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite() or parsed < 0:
        return None
    return float(parsed)


def _resolve_supplier_candidate(
    constraints: Mapping[str, Any],
    metrics: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """内部辅助函数`_resolve_supplier_candidate`；拆分主流程并集中处理当前模块的边界条件。"""
    effective = dict(constraints)
    candidates = metrics.get("supplier_candidates") if isinstance(metrics, Mapping) else None
    if not isinstance(candidates, list):
        return effective, {"mode": "manual", "candidate_count": 0, "evidence_ids": []}

    requested = str(constraints.get("supplier_name") or "").strip()
    normalized_requested = requested.casefold()
    exact = next(
        (
            candidate
            for candidate in candidates
            if isinstance(candidate, Mapping)
            and str(candidate.get("supplier_name") or "").strip().casefold() == normalized_requested
        ),
        None,
    )
    selected = exact or (candidates[0] if not requested and candidates else None)
    if not isinstance(selected, Mapping):
        return effective, {"mode": "manual", "candidate_count": len(candidates), "evidence_ids": []}

    for field in ("supplier_name", "moq", "lead_time_days"):
        if effective.get(field) in (None, "") and selected.get(field) not in (None, ""):
            effective[field] = selected[field]
    mode = "matched" if exact else "recommended"
    return effective, {
        "mode": mode,
        "candidate_count": len(candidates),
        "evidence_ids": [str(selected.get("evidence_id"))] if selected.get("evidence_id") else [],
        "selected_supplier": selected.get("supplier_name"),
        "candidate_suppliers": [
            dict(candidate) for candidate in candidates[:5] if isinstance(candidate, Mapping)
        ],
    }


def evaluate_supplier_constraints(
    constraints: Mapping[str, Any],
    metrics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """实现`evaluate_supplier_constraints`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    effective_constraints, resolution = _resolve_supplier_candidate(constraints, metrics)
    supplier_name_raw = effective_constraints.get("supplier_name")
    supplier_name = (
        supplier_name_raw.strip()
        if isinstance(supplier_name_raw, str) and supplier_name_raw.strip()
        else None
    )
    moq = _positive_integer(effective_constraints.get("moq"))
    lead_time_days = _positive_integer(effective_constraints.get("lead_time_days"))
    invalid_fields: list[str] = []
    if effective_constraints.get("moq") not in (None, "") and moq is None:
        invalid_fields.append("moq")
    if effective_constraints.get("lead_time_days") not in (None, "") and lead_time_days is None:
        invalid_fields.append("lead_time_days")

    missing_fields = [
        field
        for field, value in (
            ("supplier_name", supplier_name),
            ("moq", moq),
            ("lead_time_days", lead_time_days),
        )
        if value is None
    ]
    supplied_required_fields = 3 - len(missing_fields)
    if supplied_required_fields == 0 and not invalid_fields:
        supplier_status = "requires_supplier_data"
    elif missing_fields or invalid_fields:
        supplier_status = "partial"
    else:
        supplier_status = "ready"

    certifications_raw = effective_constraints.get("certifications")
    certifications = (
        [item.strip() for item in certifications_raw if isinstance(item, str) and item.strip()]
        if isinstance(certifications_raw, list)
        else []
    )
    risk_flags: list[str] = []
    forecast_units = _positive_integer(effective_constraints.get("forecast_units"))
    if moq is not None and forecast_units is not None and moq > forecast_units:
        risk_flags.append("moq_exceeds_forecast_units")
    max_lead_time_days = _positive_integer(effective_constraints.get("max_lead_time_days"))
    if lead_time_days is not None:
        if max_lead_time_days is not None and lead_time_days > max_lead_time_days:
            risk_flags.append("lead_time_exceeds_limit")
        elif max_lead_time_days is None and lead_time_days > 60:
            risk_flags.append("long_lead_time")
    supplier_rating = _non_negative_number(effective_constraints.get("supplier_rating"))
    if supplier_rating is not None and supplier_rating < 3:
        risk_flags.append("low_supplier_rating")
    if effective_constraints.get("sample_passed") is False:
        risk_flags.append("sample_not_approved")

    high_risk_flags = {"lead_time_exceeds_limit", "sample_not_approved"}
    if any(flag in high_risk_flags for flag in risk_flags):
        risk_level = "high"
    elif risk_flags:
        risk_level = "medium"
    elif supplier_status == "ready":
        risk_level = "low"
    else:
        risk_level = "unknown"

    return {
        "status": supplier_status,
        "supplier_name": supplier_name,
        "moq": moq,
        "lead_time_days": lead_time_days,
        "max_lead_time_days": max_lead_time_days,
        "certifications": certifications,
        "supplier_rating": supplier_rating,
        "sample_passed": effective_constraints.get("sample_passed"),
        "risk_level": risk_level,
        "risk_flags": risk_flags,
        "missing_fields": missing_fields,
        "invalid_fields": invalid_fields,
        "resolution": resolution,
        "data_backed": resolution["mode"] in {"matched", "recommended"},
    }
