"""文件职责：把检索证据和项目约束组合为可评分的候选商品概念。"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any, SupportsFloat, SupportsIndex, cast

from merchpilot.services.finance import calculate_candidate_financials

TAG_SPLIT_PATTERN = re.compile(r"[;；,，、/]+")


def _record(value: object) -> dict[str, Any]:
    """内部辅助函数`_record`；拆分主流程并集中处理当前模块的边界条件。"""
    return value if isinstance(value, dict) else {}


def _string_list(value: object) -> list[str]:
    """内部辅助函数`_string_list`；拆分主流程并集中处理当前模块的边界条件。"""
    if isinstance(value, list):
        values = value
    elif value is None:
        values = []
    else:
        values = TAG_SPLIT_PATTERN.split(str(value))
    return [str(item).strip() for item in values if str(item).strip()]


def _number(value: object) -> float | None:
    """内部辅助函数`_number`；拆分主流程并集中处理当前模块的边界条件。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(cast(str | SupportsFloat | SupportsIndex, value))
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _hit_rows(outputs: Mapping[str, Any]) -> list[dict[str, Any]]:
    """内部辅助函数`_hit_rows`；拆分主流程并集中处理当前模块的边界条件。"""
    rows: list[dict[str, Any]] = []
    for topic in ("market", "competitor", "user_insight"):
        result = _record(outputs.get(topic))
        hits = result.get("hits")
        if not isinstance(hits, list):
            continue
        for hit_value in hits:
            hit = _record(hit_value)
            metadata = _record(hit.get("metadata"))
            normalized = metadata.get("normalized_row")
            row = dict(normalized) if isinstance(normalized, dict) else {}
            row.setdefault("product_name", metadata.get("product_name"))
            row.setdefault("brand", metadata.get("brand"))
            row.setdefault("category", hit.get("category"))
            row.setdefault("target_market", hit.get("target_market"))
            row.setdefault("price", metadata.get("price"))
            row.setdefault("selling_points", metadata.get("selling_points"))
            row.setdefault("pain_points", metadata.get("pain_points"))
            row.setdefault("demand_tags", metadata.get("demand_tags"))
            row["topic"] = topic
            row["evidence_id"] = str(hit.get("id") or "")
            rows.append(row)
    return rows


def _top_terms(rows: Sequence[dict[str, Any]], fields: Sequence[str], limit: int = 8) -> list[str]:
    """内部辅助函数`_top_terms`；拆分主流程并集中处理当前模块的边界条件。"""
    counter: Counter[str] = Counter()
    for row in rows:
        for field in fields:
            for item in _string_list(row.get(field)):
                counter[item] += 1
    return [item for item, _ in counter.most_common(limit)]


def _unique_ids(rows: Sequence[dict[str, Any]], topics: Sequence[str] | None = None) -> list[str]:
    """内部辅助函数`_unique_ids`；拆分主流程并集中处理当前模块的边界条件。"""
    allowed = set(topics) if topics else None
    return sorted(
        {
            str(row["evidence_id"])
            for row in rows
            if row.get("evidence_id") and (allowed is None or row.get("topic") in allowed)
        }
    )


def _price_reference(metrics: Mapping[str, Any], strategy: str) -> dict[str, Any]:
    """内部辅助函数`_price_reference`；拆分主流程并集中处理当前模块的边界条件。"""
    stats = _record(metrics.get("price"))
    price = _number(stats.get(strategy)) or _number(stats.get("median"))
    if price is None:
        return {"suggested_price": None, "basis": "暂无价格数据"}
    return {
        "suggested_price": round(price, 2),
        "range_min": _number(stats.get("min")),
        "range_max": _number(stats.get("max")),
        "basis": f"同品类价格{strategy}",
    }


def _candidate_risks(metrics: Mapping[str, Any]) -> list[str]:
    """内部辅助函数`_candidate_risks`；拆分主流程并集中处理当前模块的边界条件。"""
    coverage = _record(metrics.get("coverage"))
    risks = ["功能、规格和样品仍需供应链与用户验证"]
    if not coverage.get("market_trend"):
        risks.append("缺少市场趋势数据")
    if not coverage.get("competitor"):
        risks.append("缺少竞品数据")
    if not coverage.get("supplier"):
        risks.append("缺少供应商候选数据")
    return risks


def _term_key(value: object) -> str:
    """内部辅助函数`_term_key`；拆分主流程并集中处理当前模块的边界条件。"""
    return str(value).strip().casefold().replace("化", "")


def _candidate_scorecard(
    evidence_ids: Sequence[str],
    evidence_features: Sequence[str],
    pain_points: Sequence[str],
    hypotheses: Sequence[str],
    financial_scenario: Mapping[str, Any],
    metrics: Mapping[str, Any],
) -> dict[str, Any]:
    """内部辅助函数`_candidate_scorecard`；拆分主流程并集中处理当前模块的边界条件。"""
    observed_terms = {
        _term_key(item)
        for item in (*evidence_features, *pain_points)
        if str(item).strip()
    }
    matched_hypotheses = [
        item for item in hypotheses if _term_key(item) in observed_terms
    ]
    evidence_volume_score = round(min(len(evidence_ids) / 10, 1) * 20)
    hypothesis_match_score = round(
        min(len(matched_hypotheses) / max(len(hypotheses), 1), 1) * 20
    )
    evidence_score = evidence_volume_score + hypothesis_match_score

    margin_rate = _number(financial_scenario.get("margin_rate"))
    target_margin = _number(financial_scenario.get("target_margin")) or 0.4
    commercial_score = 0
    commercial_reason = "缺少价格或成本数据"
    if margin_rate is not None:
        commercial_score = round(min(max(margin_rate / target_margin, 0), 1) * 35)
        commercial_reason = f"参考毛利率 {margin_rate:.1%}，目标 {target_margin:.1%}"

    coverage = _record(metrics.get("coverage"))
    coverage_dimensions = ("market_trend", "competitor", "user_reviews", "supplier", "cost")
    covered_dimensions = sum(bool(coverage.get(key)) for key in coverage_dimensions)
    readiness_score = round(covered_dimensions / len(coverage_dimensions) * 25)
    readiness_reason = f"已覆盖 {covered_dimensions}/{len(coverage_dimensions)} 类关键数据"
    total_score = min(evidence_score + commercial_score + readiness_score, 100)
    score_status = "ready" if commercial_score > 0 and covered_dimensions >= 4 else "partial"
    return {
        "total_score": total_score,
        "status": score_status,
        "breakdown": {
            "evidence_fit": {
                "score": evidence_score,
                "max_score": 40,
                "reason": f"命中 {len(matched_hypotheses)}/{len(hypotheses)} 项候选特征",
            },
            "commercial": {
                "score": commercial_score,
                "max_score": 35,
                "reason": commercial_reason,
            },
            "readiness": {
                "score": readiness_score,
                "max_score": 25,
                "reason": readiness_reason,
            },
        },
        "matched_hypotheses": matched_hypotheses,
        "margin_rate": round(margin_rate, 4) if margin_rate is not None else None,
        "requires_validation": score_status != "ready",
    }


def _coverage_ready(value: object) -> bool:
    """内部辅助函数`_coverage_ready`；拆分主流程并集中处理当前模块的边界条件。"""
    if isinstance(value, bool):
        return value
    number = _number(value)
    if number is not None:
        return number > 0
    return bool(str(value).strip()) if value is not None else False


def _candidate_validation_plan(
    candidate: Mapping[str, Any],
    financial_scenario: Mapping[str, Any],
    metrics: Mapping[str, Any],
) -> dict[str, Any]:
    """内部辅助函数`_candidate_validation_plan`；拆分主流程并集中处理当前模块的边界条件。"""
    evidence_ids = _string_list(candidate.get("evidence_ids"))
    evidence_features = _string_list(candidate.get("evidence_features"))
    pain_points = _string_list(candidate.get("pain_points_addressed"))
    hypotheses = _string_list(candidate.get("feature_hypotheses"))
    specification_suggestions = _string_list(candidate.get("specification_suggestions"))
    coverage = _record(metrics.get("coverage"))
    financial_status = str(financial_scenario.get("status") or "")
    missing_finance_fields = _string_list(financial_scenario.get("missing_fields"))
    invalid_finance_fields = _string_list(financial_scenario.get("invalid_fields"))

    demand_status = (
        "ready"
        if evidence_ids and (evidence_features or pain_points)
        else "blocked"
        if not evidence_ids
        else "pending"
    )
    specification_confirmed = (
        candidate.get("specification_confirmed") is True
        or candidate.get("specification_status") == "confirmed"
    )
    specification_status = "ready" if specification_confirmed else "pending"
    if financial_status in {"invalid_constraints", "unviable"}:
        commercial_status = "blocked"
    elif financial_status == "ready" and financial_scenario.get("passed_target_margin") is not False:
        commercial_status = "ready"
    else:
        commercial_status = "pending"
    supply_status = "ready" if _coverage_ready(coverage.get("supplier")) else "pending"

    gates: list[dict[str, Any]] = [
        {
            "id": "demand_fit",
            "label": "需求匹配",
            "status": demand_status,
            "owner": "商品经理",
            "criteria": (
                "已有竞品或用户证据支撑核心特征与痛点"
                if demand_status == "ready"
                else "补充竞品、用户证据并确认核心痛点优先级"
            ),
            "evidence_ids": evidence_ids,
            "materials": [],
        },
        {
            "id": "specification",
            "label": "规格与样品",
            "status": specification_status,
            "owner": "研发/供应链",
            "criteria": (
                "核心功能、材质、尺寸和关键参数已确认并完成样品测试"
                if specification_status == "ready"
                else "确认核心功能与规格边界，完成样品和小批量测试"
            ),
            "checklist": specification_suggestions or hypotheses,
            "materials": [],
        },
        {
            "id": "commercial",
            "label": "财务可行",
            "status": commercial_status,
            "owner": "财务",
            "criteria": (
                "候选售价、成本和毛利测算已通过"
                if commercial_status == "ready"
                else "补齐售价、单位成本和销量假设"
                if missing_finance_fields
                else "修正财务参数或成本结构，确保贡献毛利为正"
            ),
            "missing_fields": missing_finance_fields,
            "invalid_fields": invalid_finance_fields,
            "materials": [],
        },
        {
            "id": "supply",
            "label": "供应交付",
            "status": supply_status,
            "owner": "采购/供应链",
            "criteria": (
                "已有供应商候选数据"
                if supply_status == "ready"
                else "补齐供应商、MOQ、交期和质量认证信息"
            ),
            "materials": [],
        },
    ]
    completed_gates = sum(gate["status"] == "ready" for gate in gates)
    total_gates = len(gates)
    blocked_gates = sum(gate["status"] == "blocked" for gate in gates)
    if completed_gates == total_gates:
        status = "ready"
        status_label = "可进入小批量验证"
    elif completed_gates == 0 and blocked_gates > 0:
        status = "blocked"
        status_label = "存在阻塞项"
    else:
        status = "partial"
        status_label = "部分具备，需补齐验证"

    next_actions = [
        gate["criteria"]
        for gate in gates
        if gate["status"] != "ready"
    ]
    if not next_actions:
        next_actions = ["进入小批量试销，记录转化、退货和复购指标"]
    return {
        "status": status,
        "status_label": status_label,
        "completed_gates": completed_gates,
        "total_gates": total_gates,
        "completion_rate": round(completed_gates / total_gates * 100),
        "gates": gates,
        "next_actions": next_actions,
        "requires_validation": status != "ready",
    }


def apply_candidate_validation_updates(
    validation_plan: Mapping[str, Any],
    updates: Sequence[Mapping[str, Any]],
    *,
    actor_id: str,
    updated_at: str,
) -> dict[str, Any]:
    """实现`apply_candidate_validation_updates`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    plan = dict(validation_plan)
    gates = [dict(item) for item in plan.get("gates", []) if isinstance(item, Mapping)]
    updates_by_id = {
        str(item.get("gate_id") or "").strip(): item
        for item in updates
        if str(item.get("gate_id") or "").strip()
    }
    for gate in gates:
        gate_id = str(gate.get("id") or "")
        update = updates_by_id.get(gate_id)
        if update is None:
            continue
        gate["status"] = str(update.get("status") or gate.get("status") or "pending")
        gate["note"] = str(update.get("note") or "").strip()
        gate["updated_by"] = actor_id
        gate["updated_at"] = updated_at

    completed_gates = sum(gate.get("status") == "ready" for gate in gates)
    blocked_gates = sum(gate.get("status") == "blocked" for gate in gates)
    total_gates = len(gates)
    if completed_gates == total_gates and total_gates > 0:
        status = "ready"
        status_label = "可进入小批量验证"
    elif completed_gates == 0 and blocked_gates > 0:
        status = "blocked"
        status_label = "存在阻塞项"
    else:
        status = "partial"
        status_label = "部分具备，需补齐验证"

    next_actions = [
        str(gate.get("criteria") or gate.get("label") or "补充验证")
        for gate in gates
        if gate.get("status") != "ready"
    ]
    if not next_actions:
        next_actions = ["进入小批量试销，记录转化、退货和复购指标"]
    plan.update(
        {
            "status": status,
            "status_label": status_label,
            "completed_gates": completed_gates,
            "total_gates": total_gates,
            "completion_rate": round(completed_gates / total_gates * 100) if total_gates else 0,
            "gates": gates,
            "next_actions": next_actions,
            "requires_validation": status != "ready",
            "last_updated_by": actor_id,
            "last_updated_at": updated_at,
        }
    )
    return plan


def build_candidate_concepts(
    requirement: Mapping[str, Any],
    outputs: Mapping[str, Any],
    metrics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """实现`build_candidate_concepts`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    planning_metrics = metrics if isinstance(metrics, Mapping) else {}
    rows = _hit_rows(outputs)
    category = str(requirement.get("category") or "商品")
    target_market = str(requirement.get("target_market") or "目标市场待明确")
    constraints = _record(requirement.get("constraints"))
    target_user = str(constraints.get("target_user") or "目标用户待明确")
    evidence_ids = _unique_ids(rows)
    evidence_features = _top_terms(rows, ("selling_points", "demand_tags"))
    pain_points = _top_terms(rows, ("pain_points",))
    competitor_ids = _unique_ids(rows, ("competitor",))
    insight_ids = _unique_ids(rows, ("user_insight",))
    shared_risks = _candidate_risks(planning_metrics)
    strategies = (
        ("轻量通勤款", "便携、易清洁和日常高频使用", "p25", ("轻量化", "防漏", "易清洗")),
        ("智能温控款", "温度管理和智能体验", "median", ("温显", "保温", "提醒")),
        ("高性价比基础款", "核心功能和成本控制", "p25", ("耐用", "防漏", "核心功能")),
    )
    confidence = "high" if len(evidence_ids) >= 12 else "medium" if len(evidence_ids) >= 5 else "low"
    candidates: list[dict[str, Any]] = []
    for index, (suffix, focus, price_strategy, hypotheses) in enumerate(strategies, start=1):
        candidate_evidence_ids = sorted(set(competitor_ids[:4] + insight_ids[:4])) or evidence_ids[:8]
        price_reference = _price_reference(planning_metrics, price_strategy)
        candidate: dict[str, Any] = {
            "id": f"concept-{index}",
            "name": f"{category}{suffix}",
            "positioning": f"面向{target_user}、覆盖{target_market}的{focus}方案",
            "target_user": target_user,
            "evidence_features": evidence_features[:5],
            "pain_points_addressed": pain_points[:5],
            "feature_hypotheses": list(hypotheses),
            "specification_suggestions": [
                "容量、材质、尺寸和核心参数需结合供应商能力确认",
                "上市前通过样品和小批量测试验证用户反馈",
            ],
            "price_reference": price_reference,
            "unit_cost_reference": _record(
                _record(planning_metrics.get("suggested_finance_inputs")).get("unit_cost")
            ).get("value"),
            "differentiation_hypothesis": f"以{focus}作为差异化主线，当前属于基于证据的候选假设",
            "risks": shared_risks,
            "confidence": confidence,
            "evidence_ids": candidate_evidence_ids,
            "requires_validation": True,
        }
        candidate["financial_scenario"] = calculate_candidate_financials(
            candidate,
            constraints,
            planning_metrics,
        )
        candidate["scorecard"] = _candidate_scorecard(
            candidate_evidence_ids,
            evidence_features,
            pain_points,
            hypotheses,
            candidate["financial_scenario"],
            planning_metrics,
        )
        candidate["validation_plan"] = _candidate_validation_plan(
            candidate,
            candidate["financial_scenario"],
            planning_metrics,
        )
        candidate["requires_validation"] = candidate["validation_plan"]["requires_validation"]
        candidates.append(candidate)

    recommended_candidate = max(
        candidates,
        key=lambda item: _number(_record(item.get("scorecard")).get("total_score")) or 0,
    )
    for candidate in candidates:
        candidate["recommendation"] = (
            "优先验证" if candidate["id"] == recommended_candidate["id"] else "备选验证"
        )

    primary = candidates[0]
    return {
        "name": primary["name"],
        "positioning": primary["positioning"],
        "target_market": target_market,
        "target_user": target_user,
        "revision": 1,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "recommended_candidate_id": recommended_candidate["id"],
        "recommended_candidate_name": recommended_candidate["name"],
        "selected_candidate_id": None,
        "selected_candidate": None,
        "selection_status": "pending",
        "evidence_ids": evidence_ids,
        "generation_mode": "evidence_template",
        "requires_validation": True,
        "data_basis": {
            "record_count": int(planning_metrics.get("record_count") or 0),
            "coverage": dict(_record(planning_metrics.get("coverage"))),
        },
    }


def finalize_candidate_concepts(
    requirement: Mapping[str, Any],
    outputs: Mapping[str, Any],
    drafts: Sequence[Mapping[str, Any]],
    metrics: Mapping[str, Any] | None = None,
    *,
    generation_mode: str,
    generation_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """将模型候选草案收敛为经过财务、评分和验证规则处理的正式方案。"""
    planning_metrics = metrics if isinstance(metrics, Mapping) else {}
    rows = _hit_rows(outputs)
    category = str(requirement.get("category") or "商品")
    target_market = str(requirement.get("target_market") or "目标市场待明确")
    constraints = _record(requirement.get("constraints"))
    target_user = str(constraints.get("target_user") or "目标用户待明确")
    available_evidence_ids = set(_unique_ids(rows))
    shared_risks = _candidate_risks(planning_metrics)
    candidates: list[dict[str, Any]] = []

    for index, raw_draft in enumerate(drafts, start=1):
        draft = _record(raw_draft)
        invalid_evidence_ids = [
            evidence_id
            for evidence_id in _string_list(draft.get("evidence_ids"))
            if evidence_id not in available_evidence_ids
        ]
        evidence_ids = [
            evidence_id
            for evidence_id in _string_list(draft.get("evidence_ids"))
            if evidence_id in available_evidence_ids
        ]
        candidate: dict[str, Any] = {
            # 用流程内稳定 ID 替换模型自定义 ID，避免后续选择、审批和修订引用漂移。
            "id": f"concept-{index}",
            "source_draft_id": str(draft.get("id") or ""),
            "name": str(draft.get("name") or f"{category}候选方案{index}"),
            "positioning": str(
                draft.get("positioning")
                or f"面向{target_user}、覆盖{target_market}的候选商品方案"
            ),
            "target_user": str(draft.get("target_user") or target_user),
            "evidence_features": _string_list(draft.get("evidence_features"))[:8],
            "pain_points_addressed": _string_list(draft.get("pain_points_addressed"))[:8],
            "feature_hypotheses": _string_list(draft.get("feature_hypotheses"))[:8],
            "specification_suggestions": _string_list(draft.get("specification_suggestions"))[:8],
            "assumptions": _string_list(draft.get("assumptions"))[:8],
            "validation_items": _string_list(draft.get("validation_items"))[:8],
            "price_reference": _record(draft.get("price_reference")),
            "unit_cost_reference": _number(draft.get("unit_cost_reference")),
            "differentiation_hypothesis": str(
                draft.get("differentiation_hypothesis") or "基于现有证据形成的差异化假设"
            ),
            "risks": list(dict.fromkeys(shared_risks + _string_list(draft.get("risks")))),
            "confidence": str(draft.get("confidence") or "medium"),
            # 模型没有提供有效证据时保持为空，由审查节点明确暴露证据不足，不能静默借用全局证据。
            "evidence_ids": evidence_ids,
            "requires_validation": True,
            "commercial_source": "deterministic_finance_service",
            "model_evidence_ids_rejected": invalid_evidence_ids,
            "evidence_completeness": "supported" if evidence_ids else "unsupported",
        }
        # 模型只能提出概念假设，售价和成本必须由确定性财务规则计算，避免幻觉污染商业决策。
        candidate["price_reference"] = _price_reference(planning_metrics, "median")
        candidate["unit_cost_reference"] = _record(
            _record(planning_metrics.get("suggested_finance_inputs")).get("unit_cost")
        ).get("value")
        candidate["financial_scenario"] = calculate_candidate_financials(
            candidate,
            constraints,
            planning_metrics,
        )
        candidate["scorecard"] = _candidate_scorecard(
            candidate["evidence_ids"],
            candidate["evidence_features"],
            candidate["pain_points_addressed"],
            candidate["feature_hypotheses"],
            candidate["financial_scenario"],
            planning_metrics,
        )
        candidate["validation_plan"] = _candidate_validation_plan(
            candidate,
            candidate["financial_scenario"],
            planning_metrics,
        )
        candidate["requires_validation"] = candidate["validation_plan"]["requires_validation"]
        candidates.append(candidate)

    if not candidates:
        return build_candidate_concepts(requirement, outputs, planning_metrics)

    recommended_candidate = max(
        candidates,
        key=lambda item: _number(_record(item.get("scorecard")).get("total_score")) or 0,
    )
    for candidate in candidates:
        candidate["recommendation"] = (
            "优先验证" if candidate["id"] == recommended_candidate["id"] else "备选验证"
        )

    primary = candidates[0]
    return {
        "name": primary["name"],
        "positioning": primary["positioning"],
        "target_market": target_market,
        "target_user": target_user,
        "revision": 1,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "recommended_candidate_id": recommended_candidate["id"],
        "recommended_candidate_name": recommended_candidate["name"],
        "selected_candidate_id": None,
        "selected_candidate": None,
        "selection_status": "pending",
        "evidence_ids": sorted(available_evidence_ids),
        "generation_mode": generation_mode,
        "generation": dict(generation_metadata or {}),
        "evidence_audit": dict(
            _record(generation_metadata).get("evidence_audit") or {}
        ),
        "requires_validation": True,
        "data_basis": {
            "record_count": int(planning_metrics.get("record_count") or 0),
            "coverage": dict(_record(planning_metrics.get("coverage"))),
        },
    }


def resolve_candidate_concept(
    concept: Mapping[str, Any],
    candidate_id: object,
) -> dict[str, Any] | None:
    """实现`resolve_candidate_concept`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    normalized_id = str(candidate_id or "").strip()
    if not normalized_id:
        return None
    candidates = concept.get("candidates")
    if not isinstance(candidates, list):
        return None
    for item in candidates:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("id") or "").strip() == normalized_id:
            return dict(item)
    return None


def apply_candidate_selection(
    concept: Mapping[str, Any],
    candidate_id: object,
    selection_status: str,
) -> dict[str, Any]:
    """实现`apply_candidate_selection`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    selected = resolve_candidate_concept(concept, candidate_id)
    if selected is None:
        return dict(concept)
    return {
        **dict(concept),
        "selected_candidate_id": str(selected["id"]),
        "selected_candidate": selected,
        "selection_status": selection_status,
    }
