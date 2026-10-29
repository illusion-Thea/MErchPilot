"""文件职责：评估研究证据覆盖度、触发补充检索并识别可疑数据冲突。"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

TOPIC_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "market": ("sales", "price", "yoy_rate", "mom_rate"),
    "competitor": ("product_name", "brand", "price", "selling_points"),
    "user_insight": ("content", "pain_points", "demand_tags", "rating"),
}

TOPIC_FOLLOW_UP_INTENTS = {
    "market": "补充市场规模、销量趋势、价格带和同比环比数据",
    "competitor": "补充竞品品牌、产品卖点、定价和销量数据",
    "user_insight": "补充用户评价、痛点、需求标签和评分数据",
}


def _record(value: object) -> dict[str, Any]:
    """将未知对象收敛为字典，避免治理逻辑被脏数据中断。"""
    return value if isinstance(value, dict) else {}


def _hits(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    """提取检索结果中的结构化命中记录。"""
    raw_hits = result.get("hits")
    if not isinstance(raw_hits, list):
        return []
    return [_record(hit) for hit in raw_hits if isinstance(hit, Mapping)]


def _normalized_row(hit: Mapping[str, Any]) -> dict[str, Any]:
    """提取证据导入阶段保存的标准化行。"""
    metadata = _record(hit.get("metadata"))
    normalized = metadata.get("normalized_row")
    return dict(normalized) if isinstance(normalized, Mapping) else {}


def _field_value(hit: Mapping[str, Any], field: str) -> object:
    """按标准化行、元数据和命中字段的优先级读取值。"""
    row = _normalized_row(hit)
    if field in row and row[field] not in (None, ""):
        return row[field]
    metadata = _record(hit.get("metadata"))
    if field in metadata and metadata[field] not in (None, ""):
        return metadata[field]
    return hit.get(field)


def _has_value(hit: Mapping[str, Any], field: str) -> bool:
    """判断一条证据是否覆盖指定字段。"""
    value = _field_value(hit, field)
    if isinstance(value, list):
        return any(str(item).strip() for item in value)
    return value is not None and bool(str(value).strip())


def _quality_counts(hits: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """统计证据质量状态，供研究结果解释和页面展示使用。"""
    counts: dict[str, int] = defaultdict(int)
    for hit in hits:
        quality = str(hit.get("quality_status") or "unknown")
        counts[quality] += 1
    return dict(sorted(counts.items()))


def assess_research_result(topic: str, result: Mapping[str, Any]) -> dict[str, Any]:
    """评估单个研究主题的数据覆盖度，并给出是否需要补充检索的判断。"""
    hits = _hits(result)
    required_fields = TOPIC_REQUIRED_FIELDS.get(topic, ())
    evidence_ids = sorted(
        {
            str(hit.get("id"))
            for hit in hits
            if hit.get("id")
        }
    )
    field_coverage = {
        field: sum(1 for hit in hits if _has_value(hit, field))
        for field in required_fields
    }
    possible_fields = len(hits) * len(required_fields)
    covered_fields = sum(field_coverage.values())
    coverage_rate = round(covered_fields / possible_fields * 100) if possible_fields else 0
    usable_count = len(evidence_ids)
    result_status = str(result.get("status") or "degraded")
    needs_follow_up = result_status != "ready" or usable_count < 3 or coverage_rate < 50
    status = "ready" if not needs_follow_up else "partial"
    return {
        "topic": topic,
        "status": status,
        "retrieval_status": result_status,
        "evidence_count": usable_count,
        "evidence_ids": evidence_ids,
        "required_fields": list(required_fields),
        "field_coverage": field_coverage,
        "coverage_rate": coverage_rate,
        "quality_counts": _quality_counts(hits),
        "needs_follow_up": needs_follow_up,
        "follow_up_intent": TOPIC_FOLLOW_UP_INTENTS.get(topic, "补充该主题证据"),
        "reason": (
            "证据覆盖度满足当前研究主题的最低要求"
            if not needs_follow_up
            else "证据数量或关键字段覆盖不足，建议补充采集或检索"
        ),
    }


def merge_research_results(
    primary: Mapping[str, Any],
    supplement: Mapping[str, Any],
) -> dict[str, Any]:
    """合并主检索和补充检索结果，按证据 ID 或内容去重。"""
    merged_hits: dict[str, dict[str, Any]] = {}
    for result in (primary, supplement):
        for hit in _hits(result):
            key = str(hit.get("id") or hit.get("content") or "").strip()
            if not key:
                continue
            existing = merged_hits.get(key)
            if existing is None or float(hit.get("score") or 0) > float(existing.get("score") or 0):
                merged_hits[key] = dict(hit)
    primary_governance = _record(primary.get("governance"))
    supplement_governance = _record(supplement.get("governance"))
    governance: dict[str, list[str]] = {}
    for key in {
        "canonical_evidence_ids",
        "suppressed_evidence_ids",
        "applied_review_ids",
        "conflicting_review_ids",
    }:
        governance[key] = sorted(
            {
                str(item)
                for value in (primary_governance.get(key), supplement_governance.get(key))
                if isinstance(value, list)
                for item in value
                if item
            }
        )
    hits = sorted(
        merged_hits.values(),
        key=lambda item: float(item.get("score") or 0),
        reverse=True,
    )
    status = (
        "ready"
        if any(str(item.get("status")) == "ready" for item in (primary, supplement))
        else "degraded"
    )
    reasons = [
        str(item.get("reason"))
        for item in (primary, supplement)
        if item.get("reason")
    ]
    return {
        "status": status,
        "query": str(primary.get("query") or supplement.get("query") or ""),
        "queries": [
            str(item.get("query"))
            for item in (primary, supplement)
            if item.get("query")
        ],
        "evidence_ids": [str(hit["id"]) for hit in hits if hit.get("id")],
        "hits": hits,
        "governance": governance,
        "retrieval_rounds": 2,
        "reason": "；".join(dict.fromkeys(reasons)) or None,
    }


def _number(value: object) -> float | None:
    """将数值字段安全转换为浮点数。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        if not isinstance(value, (str, int, float)):
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _entity_key(hit: Mapping[str, Any]) -> str | None:
    """提取可用于横向比较的商品或品牌实体键。"""
    product_name = str(_field_value(hit, "product_name") or "").strip().lower()
    brand = str(_field_value(hit, "brand") or "").strip().lower()
    category = str(_field_value(hit, "category") or hit.get("category") or "").strip().lower()
    if product_name:
        return f"product:{product_name}"
    if brand and category:
        return f"brand:{brand}:{category}"
    return None


def detect_evidence_conflicts(topic_results: Mapping[str, Any]) -> list[dict[str, Any]]:
    """识别同一实体的价格、评分和销量等关键指标的明显口径差异。"""
    buckets: dict[tuple[str, str], list[tuple[float, str]]] = defaultdict(list)
    for raw_result in topic_results.values():
        result = _record(raw_result)
        for hit in _hits(result):
            entity = _entity_key(hit)
            if entity is None:
                continue
            evidence_id = str(hit.get("id") or "")
            for field in ("price", "rating", "sales", "yoy_rate", "mom_rate"):
                value = _number(_field_value(hit, field))
                if value is not None:
                    buckets[(entity, field)].append((value, evidence_id))

    conflicts: list[dict[str, Any]] = []
    thresholds = {"price": 0.25, "rating": 1.0, "sales": 0.5, "yoy_rate": 0.15, "mom_rate": 0.15}
    for (entity, field), values in buckets.items():
        if len(values) < 2:
            continue
        numbers = [value for value, _ in values]
        maximum = max(numbers)
        minimum = min(numbers)
        baseline = max(abs(minimum), 1.0)
        difference = (maximum - minimum) / baseline
        exceeds = (
            abs(maximum - minimum) > thresholds[field]
            if field == "rating"
            else difference > thresholds[field]
        )
        if not exceeds:
            continue
        conflicts.append(
            {
                "type": "metric_disagreement",
                "severity": "warning",
                "entity": entity,
                "field": field,
                "values": [value for value, _ in values],
                "evidence_ids": sorted({evidence_id for _, evidence_id in values if evidence_id}),
                "reason": f"同一实体的{field}存在明显差异，可能存在时间、规格或统计口径不同",
            }
        )
    return conflicts


def build_research_synthesis(outputs: Mapping[str, Any]) -> dict[str, Any]:
    """汇总三个研究主题的覆盖度、冲突和补充行动。"""
    topic_results = {
        topic: _record(outputs.get(topic))
        for topic in ("market", "competitor", "user_insight")
    }
    assessments = {
        topic: assess_research_result(topic, result)
        for topic, result in topic_results.items()
    }
    conflicts = detect_evidence_conflicts(topic_results)
    follow_up_actions = [
        f"{assessment['follow_up_intent']}（{topic}覆盖度 {assessment['coverage_rate']}%）"
        for topic, assessment in assessments.items()
        if assessment["needs_follow_up"]
    ]
    if conflicts:
        follow_up_actions.append("核对冲突证据的观察时间、规格口径和来源优先级")
    evidence_ids = sorted(
        {
            evidence_id
            for assessment in assessments.values()
            for evidence_id in assessment["evidence_ids"]
        }
    )
    needs_follow_up = bool(follow_up_actions)
    status = "ready" if not needs_follow_up and not conflicts else "partial"
    return {
        "status": status,
        "topic_assessments": assessments,
        "coverage": {
            topic: assessment["coverage_rate"]
            for topic, assessment in assessments.items()
        },
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
        "needs_follow_up": needs_follow_up,
        "follow_up_actions": follow_up_actions,
        "evidence_ids": evidence_ids,
        "summary": (
            "三类研究证据覆盖度满足初步方案生成要求"
            if status == "ready"
            else "研究结果可以支持初步方案，但仍存在覆盖不足或口径冲突"
        ),
    }
