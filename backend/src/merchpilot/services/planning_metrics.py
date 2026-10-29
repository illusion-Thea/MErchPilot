"""文件职责：从可信数据证据聚合规划所需的市场、价格和经营指标。"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from statistics import median
from typing import Any, SupportsFloat, SupportsIndex, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from merchpilot.domain.enums import EvidenceQualityStatus
from merchpilot.infrastructure.models import EvidenceRecord

TAG_SPLIT_PATTERN = re.compile(r"[;；,，、/]+")


def _record_row(record: EvidenceRecord) -> dict[str, Any]:
    """内部辅助函数`_record_row`；拆分主流程并集中处理当前模块的边界条件。"""
    metadata = record.metadata_json if isinstance(record.metadata_json, dict) else {}
    normalized = metadata.get("normalized_row")
    row = dict(normalized) if isinstance(normalized, dict) else {}
    row.setdefault("category", metadata.get("category"))
    row.setdefault("target_market", metadata.get("target_market"))
    row.setdefault("supplier", metadata.get("supplier"))
    row["evidence_id"] = record.id
    row["source_id"] = record.source_id
    row["quality_status"] = record.quality_status
    return row


def _number(value: object) -> float | None:
    """内部辅助函数`_number`；拆分主流程并集中处理当前模块的边界条件。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(cast(str | SupportsFloat | SupportsIndex, value))
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in {float("inf"), float("-inf")} else None


def _stats(values: Sequence[float]) -> dict[str, float | int | None]:
    """内部辅助函数`_stats`；拆分主流程并集中处理当前模块的边界条件。"""
    if not values:
        return {
            "count": 0,
            "min": None,
            "max": None,
            "average": None,
            "median": None,
            "p25": None,
            "p75": None,
        }
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min": ordered[0],
        "max": ordered[-1],
        "average": round(sum(ordered) / len(ordered), 4),
        "median": float(median(ordered)),
        "p25": ordered[round((len(ordered) - 1) * 0.25)],
        "p75": ordered[round((len(ordered) - 1) * 0.75)],
    }


def _field_values(rows: Sequence[dict[str, Any]], field: str) -> list[float]:
    """内部辅助函数`_field_values`；拆分主流程并集中处理当前模块的边界条件。"""
    return [number for row in rows if (number := _number(row.get(field))) is not None]


def _terms(rows: Sequence[dict[str, Any]], field: str, limit: int = 10) -> list[dict[str, Any]]:
    """内部辅助函数`_terms`；拆分主流程并集中处理当前模块的边界条件。"""
    counter: Counter[str] = Counter()
    for row in rows:
        value = row.get(field)
        if isinstance(value, list):
            values = value
        elif value is None:
            values = []
        else:
            values = TAG_SPLIT_PATTERN.split(str(value))
        for item in values:
            normalized = str(item).strip()
            if normalized:
                counter[normalized] += 1
    return [{"label": label, "count": count} for label, count in counter.most_common(limit)]


def _suggested_input(
    rows: Sequence[dict[str, Any]],
    field: str,
    preferred_types: Sequence[str],
) -> dict[str, Any] | None:
    """内部辅助函数`_suggested_input`；拆分主流程并集中处理当前模块的边界条件。"""
    for data_type in preferred_types:
        candidates = [row for row in rows if row.get("data_type") == data_type]
        values = _field_values(candidates, field)
        if values:
            return {
                "value": float(median(values)),
                "source": data_type,
                "sample_count": len(values),
                "evidence_ids": [
                    str(row["evidence_id"])
                    for row in candidates
                    if row.get(field) is not None
                ][:20],
            }
    values = _field_values(rows, field)
    if not values:
        return None
    return {
        "value": float(median(values)),
        "source": "同品类结构化数据",
        "sample_count": len(values),
        "evidence_ids": [str(row["evidence_id"]) for row in rows if row.get(field) is not None][:20],
    }


def _supplier_candidates(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """内部辅助函数`_supplier_candidates`；拆分主流程并集中处理当前模块的边界条件。"""
    candidates_by_name: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("data_type") != "供应商" and not row.get("supplier"):
            continue
        name = str(row.get("supplier") or row.get("product_name") or "").strip()
        if not name:
            continue
        candidate = {
            "supplier_name": name,
            "cost": _number(row.get("cost")),
            "moq": _number(row.get("moq")),
            "lead_time_days": _number(row.get("lead_time_days")),
            "supplier_rating": _number(row.get("supplier_rating") or row.get("rating")),
            "certifications": row.get("certifications") or [],
            "evidence_id": str(row["evidence_id"]),
            "source_id": str(row["source_id"]),
        }
        completeness = sum(
            candidate[field] is not None
            for field in ("cost", "moq", "lead_time_days", "supplier_rating")
        )
        candidate["completeness_score"] = completeness
        existing = candidates_by_name.get(name)
        if existing is None or completeness > int(existing["completeness_score"]):
            candidates_by_name[name] = candidate
    return sorted(
        candidates_by_name.values(),
        key=lambda item: (-int(item["completeness_score"]), item["supplier_name"]),
    )[:20]


def build_planning_metrics(
    records: Sequence[EvidenceRecord],
    *,
    category: str | None,
    target_market: str | None,
) -> dict[str, Any]:
    """实现`build_planning_metrics`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    rows = []
    for record in records:
        if record.quality_status == EvidenceQualityStatus.BLOCKED.value:
            continue
        row = _record_row(record)
        if category and str(row.get("category") or "").strip() != category:
            continue
        if target_market and str(row.get("target_market") or "").strip() != target_market:
            continue
        rows.append(row)

    type_counts = Counter(str(row.get("data_type") or "未分类") for row in rows)
    review_rows = [row for row in rows if row.get("data_type") == "用户评论"]
    competitor_rows = [row for row in rows if row.get("data_type") == "竞品"]
    own_product_rows = [row for row in rows if row.get("data_type") == "自有商品"]
    trend_rows = [row for row in rows if row.get("data_type") == "市场趋势"]
    cost_rows = [row for row in rows if row.get("data_type") == "成本费用"]

    coverage = {
        "market_trend": len(trend_rows),
        "competitor": len(competitor_rows),
        "user_reviews": len(review_rows),
        "own_products": len(own_product_rows),
        "supplier": len(_supplier_candidates(rows)),
        "cost": len(cost_rows),
    }
    suggested_finance_inputs = {
        "selling_price": _suggested_input(rows, "price", ("自有商品", "竞品", "成本费用")),
        "unit_cost": _suggested_input(rows, "cost", ("成本费用", "自有商品", "竞品")),
        "logistics_cost": _suggested_input(rows, "logistics_cost", ("成本费用", "自有商品")),
        "forecast_units": _suggested_input(rows, "forecast_sales", ("成本费用", "自有商品")),
    }
    return {
        "status": "ready" if rows else "partial",
        "category": category,
        "target_market": target_market,
        "record_count": len(rows),
        "data_type_counts": dict(type_counts),
        "coverage": coverage,
        "price": _stats(_field_values(rows, "price")),
        "competitor_price": _stats(_field_values(competitor_rows, "price")),
        "own_product_price": _stats(_field_values(own_product_rows, "price")),
        "sales": _stats(_field_values(rows, "sales")),
        "inventory": _stats(_field_values(rows, "inventory")),
        "trend": {
            "yoy_rate": _stats(_field_values(trend_rows, "yoy_rate")),
            "mom_rate": _stats(_field_values(trend_rows, "mom_rate")),
        },
        "reviews": {
            "count": len(review_rows),
            "rating": _stats(_field_values(review_rows, "rating")),
            "pain_points": _terms(review_rows, "pain_points"),
            "demand_tags": _terms(review_rows, "demand_tags"),
        },
        "supplier_candidates": _supplier_candidates(rows),
        "suggested_finance_inputs": suggested_finance_inputs,
        "evidence_ids": [str(row["evidence_id"]) for row in rows[:100]],
    }


async def collect_planning_metrics(
    session: AsyncSession,
    *,
    tenant_id: str,
    category: str | None,
    target_market: str | None,
) -> dict[str, Any]:
    """实现`collect_planning_metrics`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    records = list(
        await session.scalars(
            select(EvidenceRecord)
            .where(
                EvidenceRecord.tenant_id == tenant_id,
                EvidenceRecord.quality_status != EvidenceQualityStatus.BLOCKED.value,
            )
            .order_by(EvidenceRecord.observed_at.desc(), EvidenceRecord.created_at.desc())
            .limit(50_000)
        )
    )
    return build_planning_metrics(records, category=category, target_market=target_market)
