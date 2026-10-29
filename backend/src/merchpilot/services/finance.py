"""文件职责：计算成本、毛利、盈亏平衡和财务门禁指标。"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")
MONEY_QUANTUM = Decimal("0.01")
RATE_QUANTUM = Decimal("0.0001")


def _to_decimal(value: object) -> Decimal | None:
    """内部辅助函数`_to_decimal`；拆分主流程并集中处理当前模块的边界条件。"""
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _append_once(items: list[str], value: str) -> None:
    """内部辅助函数`_append_once`；拆分主流程并集中处理当前模块的边界条件。"""
    if value not in items:
        items.append(value)


def _money_field(
    constraints: Mapping[str, Any],
    key: str,
    invalid_fields: list[str],
    *,
    positive: bool = False,
) -> Decimal | None:
    """内部辅助函数`_money_field`；拆分主流程并集中处理当前模块的边界条件。"""
    raw = constraints.get(key)
    if raw is None or raw == "":
        return None
    value = _to_decimal(raw)
    if value is None or value < ZERO or (positive and value <= ZERO):
        _append_once(invalid_fields, key)
        return None
    return value


def _rate_field(
    constraints: Mapping[str, Any],
    key: str,
    invalid_fields: list[str],
    *,
    default: Decimal = ZERO,
) -> Decimal:
    """内部辅助函数`_rate_field`；拆分主流程并集中处理当前模块的边界条件。"""
    raw = constraints.get(key)
    if raw is None or raw == "":
        return default
    value = _to_decimal(raw)
    if value is None or value < ZERO or value > HUNDRED:
        _append_once(invalid_fields, key)
        return default
    if value > ONE:
        value /= HUNDRED
    return value


def _selling_price(
    constraints: Mapping[str, Any],
    invalid_fields: list[str],
) -> tuple[Decimal | None, str | None]:
    """内部辅助函数`_selling_price`；拆分主流程并集中处理当前模块的边界条件。"""
    for key in ("selling_price", "unit_price"):
        if key in constraints:
            value = _money_field(constraints, key, invalid_fields, positive=True)
            return value, key if value is not None else None

    raw_range = constraints.get("price_range")
    if raw_range is None:
        return None, None
    minimum_raw: object | None = None
    maximum_raw: object | None = None
    if isinstance(raw_range, Mapping):
        minimum_raw = raw_range.get("min")
        maximum_raw = raw_range.get("max")
    elif isinstance(raw_range, (list, tuple)) and len(raw_range) == 2:
        minimum_raw, maximum_raw = raw_range
    else:
        _append_once(invalid_fields, "price_range")
        return None, None

    minimum = _to_decimal(minimum_raw)
    maximum = _to_decimal(maximum_raw)
    if (
        minimum is None
        or maximum is None
        or minimum <= ZERO
        or maximum <= ZERO
        or maximum < minimum
    ):
        _append_once(invalid_fields, "price_range")
        return None, None
    return (minimum + maximum) / Decimal("2"), "price_range_midpoint"


def _number(value: Decimal | None, quantum: Decimal = MONEY_QUANTUM) -> float | None:
    """内部辅助函数`_number`；拆分主流程并集中处理当前模块的边界条件。"""
    if value is None:
        return None
    return float(value.quantize(quantum, rounding=ROUND_HALF_UP))


def _apply_metric_defaults(
    constraints: Mapping[str, Any],
    metrics: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """内部辅助函数`_apply_metric_defaults`；拆分主流程并集中处理当前模块的边界条件。"""
    effective = dict(constraints)
    input_sources: dict[str, str] = {}
    for key in constraints:
        input_sources[str(key)] = "project_constraints"

    suggestions = metrics.get("suggested_finance_inputs") if isinstance(metrics, Mapping) else None
    if not isinstance(suggestions, Mapping):
        return effective, input_sources

    aliases = {
        "selling_price": ("selling_price", "unit_price", "price_range"),
        "unit_cost": ("unit_cost",),
        "logistics_cost": ("logistics_cost",),
        "forecast_units": ("forecast_units",),
    }
    for field, constraint_keys in aliases.items():
        if any(constraints.get(key) not in (None, "") for key in constraint_keys):
            continue
        suggestion = suggestions.get(field)
        if not isinstance(suggestion, Mapping) or suggestion.get("value") in (None, ""):
            continue
        effective[field] = suggestion["value"]
        input_sources[field] = "evidence_metrics"
    return effective, input_sources


def calculate_financials(
    constraints: Mapping[str, Any],
    metrics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """实现`calculate_financials`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    effective_constraints, input_sources = _apply_metric_defaults(constraints, metrics)
    invalid_fields: list[str] = []
    missing_fields: list[str] = []
    selling_price, price_source = _selling_price(effective_constraints, invalid_fields)
    unit_cost = _money_field(effective_constraints, "unit_cost", invalid_fields)
    logistics_cost = _money_field(effective_constraints, "logistics_cost", invalid_fields) or ZERO
    fixed_cost = _money_field(effective_constraints, "fixed_cost", invalid_fields) or ZERO
    platform_fee_rate = _rate_field(effective_constraints, "platform_fee_rate", invalid_fields)
    tax_rate = _rate_field(effective_constraints, "tax_rate", invalid_fields)
    marketing_rate = _rate_field(effective_constraints, "marketing_rate", invalid_fields)
    target_margin_value = _rate_field(
        effective_constraints,
        "target_margin",
        invalid_fields,
        default=Decimal("-1"),
    )
    target_margin: Decimal | None = target_margin_value if target_margin_value >= ZERO else None

    forecast_units_decimal = _money_field(
        effective_constraints,
        "forecast_units",
        invalid_fields,
        positive=True,
    )
    forecast_units: int | None = None
    if forecast_units_decimal is not None:
        integral_units = forecast_units_decimal.to_integral_value()
        if forecast_units_decimal != integral_units:
            _append_once(invalid_fields, "forecast_units")
        else:
            forecast_units = int(integral_units)

    if selling_price is None:
        missing_fields.append("selling_price")
    if unit_cost is None:
        missing_fields.append("unit_cost")

    variable_rate_total = platform_fee_rate + tax_rate + marketing_rate
    variable_cost_per_unit: Decimal | None = None
    contribution_margin_per_unit: Decimal | None = None
    margin_rate: Decimal | None = None
    break_even_units: int | None = None
    estimated_revenue: Decimal | None = None
    estimated_profit: Decimal | None = None
    passed_target_margin: bool | None = None
    margin_gap: Decimal | None = None

    if selling_price is not None and unit_cost is not None:
        variable_cost_per_unit = (
            unit_cost + logistics_cost + selling_price * variable_rate_total
        )
        contribution_margin_per_unit = selling_price - variable_cost_per_unit
        margin_rate = contribution_margin_per_unit / selling_price
        if contribution_margin_per_unit > ZERO:
            break_even_units = int(
                (fixed_cost / contribution_margin_per_unit).to_integral_value(
                    rounding=ROUND_CEILING
                )
            )
        if forecast_units is not None:
            estimated_revenue = selling_price * forecast_units
            estimated_profit = contribution_margin_per_unit * forecast_units - fixed_cost
        if target_margin is not None:
            passed_target_margin = margin_rate >= target_margin
            margin_gap = margin_rate - target_margin

    if invalid_fields:
        finance_status = "invalid_constraints"
    elif missing_fields:
        finance_status = "requires_cost_data"
    elif contribution_margin_per_unit is not None and contribution_margin_per_unit <= ZERO:
        finance_status = "unviable"
    else:
        finance_status = "ready"

    return {
        "status": finance_status,
        "currency": str(effective_constraints.get("currency") or "CNY"),
        "selling_price": _number(selling_price),
        "price_source": price_source,
        "unit_cost": _number(unit_cost),
        "logistics_cost": _number(logistics_cost),
        "fixed_cost": _number(fixed_cost),
        "platform_fee_rate": _number(platform_fee_rate, RATE_QUANTUM),
        "tax_rate": _number(tax_rate, RATE_QUANTUM),
        "marketing_rate": _number(marketing_rate, RATE_QUANTUM),
        "variable_rate_total": _number(variable_rate_total, RATE_QUANTUM),
        "variable_cost_per_unit": _number(variable_cost_per_unit),
        "contribution_margin_per_unit": _number(contribution_margin_per_unit),
        "margin_rate": _number(margin_rate, RATE_QUANTUM),
        "target_margin": _number(target_margin, RATE_QUANTUM),
        "passed_target_margin": passed_target_margin,
        "margin_gap": _number(margin_gap, RATE_QUANTUM),
        "forecast_units": forecast_units,
        "estimated_revenue": _number(estimated_revenue),
        "estimated_profit": _number(estimated_profit),
        "break_even_units": break_even_units,
        "missing_fields": missing_fields,
        "invalid_fields": invalid_fields,
        "input_sources": input_sources,
        "data_backed_fields": sorted(
            field for field, source in input_sources.items() if source == "evidence_metrics"
        ),
        "metrics_record_count": (
            int(metrics.get("record_count") or 0) if isinstance(metrics, Mapping) else 0
        ),
    }


def calculate_candidate_financials(
    candidate: Mapping[str, Any],
    constraints: Mapping[str, Any],
    metrics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """实现`calculate_candidate_financials`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    effective_constraints = dict(constraints)
    applied_fields: list[str] = []
    price_reference = candidate.get("price_reference")
    suggested_price = (
        price_reference.get("suggested_price")
        if isinstance(price_reference, Mapping)
        else None
    )
    if (
        not any(
            constraints.get(key) not in (None, "")
            for key in ("selling_price", "unit_price", "price_range")
        )
        and suggested_price not in (None, "")
    ):
        effective_constraints["selling_price"] = suggested_price
        applied_fields.append("selling_price")
    unit_cost_reference = candidate.get("unit_cost_reference")
    if constraints.get("unit_cost") in (None, "") and unit_cost_reference not in (None, ""):
        effective_constraints["unit_cost"] = unit_cost_reference
        applied_fields.append("unit_cost")

    result = calculate_financials(effective_constraints, metrics)
    input_sources = dict(result.get("input_sources") or {})
    for field in applied_fields:
        input_sources[field] = "candidate_reference"
    result["input_sources"] = input_sources
    result["data_backed_fields"] = sorted(
        field
        for field, source in input_sources.items()
        if source in {"evidence_metrics", "candidate_reference"}
    )
    result["candidate_backed_fields"] = sorted(applied_fields)
    result["scenario_type"] = "candidate"
    result["candidate_id"] = candidate.get("id")
    result["candidate_name"] = candidate.get("name")
    result["candidate_evidence_ids"] = [
        str(item)
        for item in candidate.get("evidence_ids", [])
        if item
    ] if isinstance(candidate.get("evidence_ids"), list) else []
    if "selling_price" in applied_fields:
        result["price_source"] = "candidate_price_reference"
    return result
