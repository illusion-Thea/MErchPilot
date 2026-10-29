"""文件职责：执行各 LLM Agent 的 Prompt、结构化解析和确定性降级。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ValidationError

from merchpilot.agents.contracts import (
    ConceptDraftSet,
    CriticReview,
    NarrativeOutput,
    RequirementAnalysis,
    ResearchPlan,
)
from merchpilot.agents.prompts import (
    PROMPT_VERSION,
    build_concept_prompt,
    build_critic_prompt,
    build_narrative_prompt,
    build_requirement_prompt,
    build_research_planning_prompt,
)
from merchpilot.llm.gateway import get_chat_model, guarded_model_invoke


def _record(value: object) -> dict[str, Any]:
    """内部辅助函数`_record`；拆分主流程并集中处理当前模块的边界条件。"""
    return value if isinstance(value, dict) else {}


def _model_metadata(model: Any) -> dict[str, Any]:
    """提取模型信息，便于前端展示本次结果是否由模型生成。"""
    return {
        "provider": "dashscope",
        "model": getattr(model, "model_name", None),
        "prompt_version": PROMPT_VERSION,
    }


def _string_list(value: object) -> list[str]:
    """内部辅助函数`_string_list`；拆分主流程并集中处理当前模块的边界条件。"""
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _research_evidence_ids(outputs: Mapping[str, Any]) -> set[str]:
    """统一提取研究节点的证据 ID，兼容检索结果的两种存储形态。"""
    evidence_ids: set[str] = set()
    for topic in ("market", "competitor", "user_insight"):
        result = _record(outputs.get(topic))
        evidence_ids.update(
            str(item)
            for item in result.get("evidence_ids", [])
            if item
        )
        hits = result.get("hits")
        if isinstance(hits, list):
            evidence_ids.update(
                str(hit.get("id"))
                for hit in hits
                if isinstance(hit, dict)
                if hit.get("id")
            )
    return evidence_ids


def _fallback_narrative(outputs: dict[str, Any], request: dict[str, Any], reason: str) -> dict[str, Any]:
    """内部辅助函数`_fallback_narrative`；拆分主流程并集中处理当前模块的边界条件。"""
    category = str(request.get("category") or "商品")
    target_market = str(request.get("target_market") or "目标市场")
    scorecard = _record(outputs.get("scorecard"))
    finance = _record(outputs.get("finance"))
    supplier = _record(outputs.get("supplier"))
    score = scorecard.get("score")
    margin_rate = finance.get("margin_rate")
    risk_level = str(supplier.get("risk_level") or "待评估")
    score_text = f"机会分 {score:.0f} 分" if isinstance(score, int | float) else "机会分待评估"
    margin_text = (
        f"预计毛利率 {margin_rate * 100:.1f}%"
        if isinstance(margin_rate, int | float)
        else "预计毛利率待评估"
    )
    risks = []
    if risk_level not in {"low", "低"}:
        risks.append(f"供应风险为 {risk_level}，需要补充供应商资质和交期验证。")
    warnings = _string_list(scorecard.get("warnings"))
    risks.extend(warnings[:3])
    if not risks:
        risks.append("建议在审批前补充样品测试、供应商资质和小批量验证结果。")
    return {
        "status": "degraded",
        "provider": "deterministic",
        "model": None,
        "prompt_version": PROMPT_VERSION,
        "summary": (
            f"{category}在{target_market}具备初步规划条件，"
            f"当前{score_text}、{margin_text}，建议进入人工审批和样品验证。"
        ),
        "recommendations": [
            f"围绕{category}的核心使用场景优化功能和卖点，先以现有证据验证目标用户需求。",
            "在确认售价、成本和目标毛利率后，优先安排供应商样品与小批量测试。",
            "审批通过后保留本次证据和参数快照，作为后续方案迭代基线。",
        ],
        "risks": risks,
        "evidence_ids": sorted(
            {
                str(evidence_id)
                for topic in ("market", "competitor", "user_insight")
                for evidence_id in _record(outputs.get(topic)).get("evidence_ids", [])
                if evidence_id
            }
        ),
        "reason": reason,
    }


def _response_text(response: Any) -> str:
    """内部辅助函数`_response_text`；拆分主流程并集中处理当前模块的边界条件。"""
    content = getattr(response, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return str(content)


def _parse_json_object(text: str) -> dict[str, Any]:
    """内部辅助函数`_parse_json_object`；拆分主流程并集中处理当前模块的边界条件。"""
    normalized = text.strip()
    if normalized.startswith("```"):
        normalized = normalized.removeprefix("```").removeprefix("json").removesuffix("```").strip()
    value = json.loads(normalized)
    if not isinstance(value, dict):
        raise ValueError("LLM response must be a JSON object")
    return value


async def _invoke_contract(
    model: Any,
    prompt: str,
    contract: type[BaseModel],
) -> BaseModel:
    """调用模型并用 Pydantic 契约拒绝缺字段或错误类型的响应。"""
    response = await guarded_model_invoke(model, prompt)
    parsed = _parse_json_object(_response_text(response))
    try:
        return contract.model_validate(parsed)
    except ValidationError as exc:
        raise ValueError(f"LLM response does not match {contract.__name__}: {exc}") from exc


def _evidence_for_llm(outputs: Mapping[str, Any], limit_per_topic: int = 5) -> list[dict[str, Any]]:
    """整理模型允许引用的证据，避免把整份原始数据无边界塞进上下文。"""
    evidence: list[dict[str, Any]] = []
    for topic in ("market", "competitor", "user_insight"):
        result = _record(outputs.get(topic))
        hits = result.get("hits")
        if not isinstance(hits, list):
            continue
        for hit in hits[:limit_per_topic]:
            record = _record(hit)
            metadata = _record(record.get("metadata"))
            normalized_row = _record(metadata.get("normalized_row"))
            evidence.append(
                {
                    "topic": topic,
                    "evidence_id": str(record.get("id") or ""),
                    "content": str(record.get("content") or "")[:2_000],
                    "metadata": {
                        key: value
                        for key, value in {
                            **normalized_row,
                            "product_name": metadata.get("product_name"),
                            "brand": metadata.get("brand"),
                            "price": metadata.get("price"),
                            "rating": metadata.get("rating"),
                            "sales": metadata.get("sales"),
                            "selling_points": metadata.get("selling_points"),
                            "pain_points": metadata.get("pain_points"),
                        }.items()
                        if value not in (None, "", [])
                    },
                }
            )
    return evidence


def _deterministic_critic_guard(outputs: Mapping[str, Any]) -> list[dict[str, Any]]:
    """独立检查候选方案，防止 LLM 的自评结果绕过证据和商业规则。"""
    concept = _record(outputs.get("concept"))
    candidates = concept.get("candidates")
    candidate_items = candidates if isinstance(candidates, list) else []
    allowed_evidence_ids = _research_evidence_ids(outputs)
    findings: list[dict[str, Any]] = []
    for candidate in candidate_items:
        if not isinstance(candidate, dict):
            continue
        candidate_id = str(candidate.get("id") or "global")
        evidence_ids = {str(item) for item in candidate.get("evidence_ids", []) if item}
        if not evidence_ids:
            findings.append(
                {
                    "candidate_id": candidate_id,
                    "severity": "blocker",
                    "issue": "候选方案没有关联任何有效研究证据",
                    "evidence_ids": [],
                    "recommendation": "补充可追溯证据，或将方案明确标记为待验证假设",
                }
            )
        invalid_ids = sorted(evidence_ids - allowed_evidence_ids)
        if invalid_ids:
            findings.append(
                {
                    "candidate_id": candidate_id,
                    "severity": "blocker",
                    "issue": "候选方案引用了当前研究结果中不存在的证据 ID",
                    "evidence_ids": invalid_ids,
                    "recommendation": "删除无效引用或补充对应原始证据",
                }
            )
        if not candidate.get("feature_hypotheses"):
            findings.append(
                {
                    "candidate_id": candidate_id,
                    "severity": "warning",
                    "issue": "候选方案缺少明确的功能假设",
                    "evidence_ids": sorted(evidence_ids),
                    "recommendation": "补充可打样、可测试的功能和规格假设",
                }
            )
    research_synthesis = _record(outputs.get("research_synthesis"))
    if research_synthesis.get("conflict_count", 0):
        findings.append(
            {
                "candidate_id": "global",
                "severity": "warning",
                "issue": "研究证据存在口径冲突，当前结论不应视为已确认事实",
                "evidence_ids": [
                    str(item)
                    for item in research_synthesis.get("evidence_ids", [])
                    if item
                ],
                "recommendation": "核对观察时间、规格和统计口径后再确定商品方案",
            }
        )
    return findings


def _fallback_requirement(request: Mapping[str, Any], reason: str) -> dict[str, Any]:
    """模型不可用时保留原始需求，不让整个商品规划流程中断。"""
    constraints = _record(request.get("constraints"))
    return {
        "category": str(request.get("category") or "商品"),
        "target_market": str(request.get("target_market") or "目标市场待明确"),
        "target_user": str(constraints.get("target_user") or "目标用户待明确"),
        "constraints": dict(constraints),
        "core_constraints": [f"{key}: {value}" for key, value in constraints.items()],
        "success_metrics": [],
        "clarifying_questions": ["请补充目标用户、价格区间和目标毛利率"]
        if not constraints
        else [],
        "assumptions": ["本次需求理解使用原始业务请求，尚未经过模型澄清"],
        "generation": {
            "status": "degraded",
            "provider": "deterministic",
            "model": None,
            "prompt_version": PROMPT_VERSION,
            "reason": reason,
        },
    }


async def generate_requirement_analysis(request: dict[str, Any]) -> dict[str, Any]:
    """执行需求理解 Agent，并在模型不可用时返回可解释的降级结果。"""
    try:
        model = get_chat_model()
    except Exception as exc:
        return _fallback_requirement(request, str(exc))
    try:
        result = await _invoke_contract(model, build_requirement_prompt(request), RequirementAnalysis)
        request_constraints = _record(request.get("constraints"))
        return {
            **result.model_dump(mode="json"),
            "category": result.category or str(request.get("category") or "商品"),
            "target_market": result.target_market
            or str(request.get("target_market") or "目标市场待明确"),
            "target_user": result.target_user
            or str(request_constraints.get("target_user") or "目标用户待明确"),
            "constraints": {**request_constraints, **result.constraints},
            "generation": {"status": "ready", **_model_metadata(model), "reason": None},
        }
    except Exception as exc:
        return _fallback_requirement(request, f"LLM generation failed: {exc}")


def _fallback_research_plan(
    request: Mapping[str, Any],
    requirement: Mapping[str, Any],
    reason: str,
) -> dict[str, Any]:
    """为本地无模型环境提供稳定的三路研究查询。"""
    category = str(requirement.get("category") or request.get("category") or "商品")
    target_market = str(
        requirement.get("target_market") or request.get("target_market") or "目标市场"
    )
    return {
        "market_query": f"{target_market} {category} 市场规模 增长趋势 销量 价格带",
        "competitor_query": f"{target_market} {category} 竞品 品牌 产品卖点 定价 销量",
        "user_insight_query": f"{target_market} {category} 目标用户 需求 痛点 评价 使用场景",
        "strategy": {
            "market": "市场规模、增长和价格带优先",
            "competitor": "竞品实体、卖点和价格横向对比",
            "user_insight": "用户痛点、评价和使用场景提取",
        },
        "follow_up_queries": {},
        "evidence_requirements": {
            "market": ["sales", "price", "yoy_rate", "mom_rate"],
            "competitor": ["product_name", "brand", "price", "selling_points"],
            "user_insight": ["content", "pain_points", "demand_tags", "rating"],
        },
        "rationale": "使用默认查询模板保证研究链路可执行",
        "generation": {
            "status": "degraded",
            "provider": "deterministic",
            "model": None,
            "prompt_version": PROMPT_VERSION,
            "reason": reason,
        },
    }


async def generate_research_plan(
    request: dict[str, Any],
    requirement: dict[str, Any],
) -> dict[str, Any]:
    """执行研究规划 Agent，选择三路检索策略并声明证据字段要求。"""
    try:
        model = get_chat_model()
    except Exception as exc:
        return _fallback_research_plan(request, requirement, str(exc))
    try:
        result = await _invoke_contract(
            model,
            build_research_planning_prompt(request, requirement),
            ResearchPlan,
        )
        return {
            **result.model_dump(mode="json"),
            "generation": {"status": "ready", **_model_metadata(model), "reason": None},
        }
    except Exception as exc:
        return _fallback_research_plan(request, requirement, f"LLM generation failed: {exc}")


async def generate_concept_drafts(
    outputs: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    """执行商品概念生成 Agent，只返回经过契约校验的模型草案。"""
    evidence = _evidence_for_llm(outputs)
    try:
        model = get_chat_model()
    except Exception as exc:
        return {
            "status": "degraded",
            "drafts": [],
            "rationale": "模型不可用，交由确定性概念规则生成候选方案",
            "evidence_audit": {
                "allowed_evidence_ids": [
                    str(item.get("evidence_id"))
                    for item in evidence
                    if item.get("evidence_id")
                ],
                "invalid_evidence_by_candidate": {},
                "invalid_reference_count": 0,
            },
            "generation": {
                "status": "degraded",
                "provider": "deterministic",
                "model": None,
                "prompt_version": PROMPT_VERSION,
                "reason": str(exc),
            },
        }
    try:
        requirement = _record(outputs.get("requirement"))
        synthesis = _record(outputs.get("research_synthesis"))
        result = await _invoke_contract(
            model,
            build_concept_prompt(request, requirement, synthesis, evidence),
            ConceptDraftSet,
        )
        allowed_evidence_ids = {
            str(item.get("evidence_id"))
            for item in evidence
            if item.get("evidence_id")
        }
        invalid_evidence_by_candidate = {
            f"concept-{index}": sorted(
                {
                    evidence_id
                    for evidence_id in item.evidence_ids
                    if evidence_id not in allowed_evidence_ids
                }
            )
            for index, item in enumerate(result.candidates, start=1)
            if any(
                evidence_id not in allowed_evidence_ids
                for evidence_id in item.evidence_ids
            )
        }
        return {
            "status": "ready" if result.candidates else "partial",
            "drafts": [item.model_dump(mode="json") for item in result.candidates],
            "rationale": result.rationale,
            "evidence_audit": {
                "allowed_evidence_ids": sorted(allowed_evidence_ids),
                "invalid_evidence_by_candidate": invalid_evidence_by_candidate,
                "invalid_reference_count": sum(
                    len(item) for item in invalid_evidence_by_candidate.values()
                ),
            },
            "generation": {**_model_metadata(model), "status": "ready", "reason": None},
        }
    except Exception as exc:
        return {
            "status": "degraded",
            "drafts": [],
            "rationale": "模型输出未通过契约校验，交由确定性概念规则生成候选方案",
            "evidence_audit": {
                "allowed_evidence_ids": [
                    str(item.get("evidence_id"))
                    for item in evidence
                    if item.get("evidence_id")
                ],
                "invalid_evidence_by_candidate": {},
                "invalid_reference_count": 0,
            },
            "generation": {
                "status": "degraded",
                "provider": "deterministic",
                "model": getattr(model, "model_name", None),
                "prompt_version": PROMPT_VERSION,
                "reason": f"LLM generation failed: {exc}",
            },
        }


def _fallback_critic(outputs: Mapping[str, Any], reason: str) -> dict[str, Any]:
    """无模型时按确定性商业结果执行最小方案审查。"""
    concept = _record(outputs.get("concept"))
    finance = _record(outputs.get("finance"))
    supplier = _record(outputs.get("supplier"))
    scorecard = _record(outputs.get("scorecard"))
    findings: list[dict[str, Any]] = []
    findings.extend(_deterministic_critic_guard(outputs))
    if finance.get("status") in {"blocked", "invalid"}:
        findings.append(
            {
                "candidate_id": "global",
                "severity": "blocker",
                "issue": "财务测算未通过，不能直接进入审批",
                "evidence_ids": [],
                "recommendation": "补齐售价、单位成本和销量假设后重新测算",
            }
        )
    if supplier.get("risk_level") not in {None, "low", "低"}:
        findings.append(
            {
                "candidate_id": "global",
                "severity": "warning",
                "issue": f"供应链风险为 {supplier.get('risk_level')}，供应能力仍需验证",
                "evidence_ids": [],
                "recommendation": "补充供应商资质、MOQ、交期和样品测试结果",
            }
        )
    if scorecard.get("status") not in {None, "ready"}:
        findings.append(
            {
                "candidate_id": "global",
                "severity": "warning",
                "issue": "综合评分尚未达到可直接推进的状态",
                "evidence_ids": [],
                "recommendation": "优先补齐证据覆盖和商业参数",
            }
        )
    blockers = sum(item["severity"] == "blocker" for item in findings)
    return {
        "status": "blocked" if blockers else "partial" if findings else "ready",
        "summary": "确定性审查发现需要处理的问题" if findings else "确定性规则未发现阻塞问题",
        "findings": findings,
        "recommended_candidate_id": concept.get("recommended_candidate_id"),
        "required_revisions": [item["recommendation"] for item in findings],
        "generation": {
            "status": "degraded",
            "provider": "deterministic",
            "model": None,
            "prompt_version": PROMPT_VERSION,
            "reason": reason,
        },
    }


def _audit_critic_evidence(
    outputs: Mapping[str, Any],
    review: CriticReview,
) -> dict[str, Any]:
    """校验审查 Agent 引用的证据，防止审查结果本身出现不可追溯引用。"""
    allowed_evidence_ids = _research_evidence_ids(outputs)
    invalid_by_finding: dict[str, list[str]] = {}
    for index, finding in enumerate(review.findings, start=1):
        invalid_ids = sorted(
            {
                evidence_id
                for evidence_id in finding.evidence_ids
                if evidence_id not in allowed_evidence_ids
            }
        )
        if invalid_ids:
            invalid_by_finding[f"finding-{index}"] = invalid_ids
    return {
        "allowed_evidence_ids": sorted(allowed_evidence_ids),
        "invalid_evidence_by_finding": invalid_by_finding,
        "invalid_reference_count": sum(
            len(item) for item in invalid_by_finding.values()
        ),
    }


async def review_candidate_concepts(
    outputs: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    """执行方案审查 Agent，并在模型不可用时保留确定性审查结果。"""
    try:
        model = get_chat_model()
    except Exception as exc:
        return _fallback_critic(outputs, str(exc))
    try:
        result = await _invoke_contract(
            model,
            build_critic_prompt(
                request,
                _record(outputs.get("research_synthesis")),
                _record(outputs.get("concept")),
                _record(outputs.get("finance")),
                _record(outputs.get("supplier")),
                _record(outputs.get("scorecard")),
            ),
            CriticReview,
        )
        evidence_audit = _audit_critic_evidence(outputs, result)
        invalid_count = int(evidence_audit.get("invalid_reference_count") or 0)
        findings = [item.model_dump(mode="json") for item in result.findings]
        findings.extend(_deterministic_critic_guard(outputs))
        if invalid_count:
            findings.append(
                {
                    "candidate_id": "global",
                    "severity": "blocker",
                    "issue": "方案审查结果引用了不存在的证据 ID",
                    "evidence_ids": sorted(
                        {
                            evidence_id
                            for values in evidence_audit["invalid_evidence_by_finding"].values()
                            for evidence_id in values
                        }
                    ),
                    "recommendation": "重新生成审查结果或补充对应原始证据",
                }
            )
        blocker_count = sum(item.get("severity") == "blocker" for item in findings)
        status = "blocked" if blocker_count else result.status
        return {
            **result.model_dump(mode="json"),
            "status": status,
            "findings": findings,
            "evidence_audit": evidence_audit,
            "generation": {**_model_metadata(model), "status": "ready", "reason": None},
        }
    except Exception as exc:
        return _fallback_critic(outputs, f"LLM generation failed: {exc}")


async def generate_planning_narrative(
    outputs: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    """实现`generate_planning_narrative`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    try:
        model = get_chat_model()
    except Exception as exc:
        return _fallback_narrative(outputs, request, str(exc))

    evidence: list[dict[str, str]] = []
    for topic in ("market", "competitor", "user_insight"):
        for hit in _record(outputs.get(topic)).get("hits", [])[:3]:
            record = _record(hit)
            evidence.append(
                {
                    "topic": topic,
                    "evidence_id": str(record.get("id") or ""),
                    "content": str(record.get("content") or ""),
                }
            )
    prompt = build_narrative_prompt(
        request,
        {
            "concept": outputs.get("concept"),
            "research_synthesis": outputs.get("research_synthesis"),
            "critic": outputs.get("critic"),
            "scorecard": outputs.get("scorecard"),
            "finance": outputs.get("finance"),
            "supplier": outputs.get("supplier"),
        },
        evidence,
    )
    try:
        result = await _invoke_contract(model, prompt, NarrativeOutput)
        return {
            "status": "ready",
            **_model_metadata(model),
            **result.model_dump(mode="json"),
            "evidence_ids": [item["evidence_id"] for item in evidence if item["evidence_id"]],
            "reason": None,
        }
    except Exception as exc:
        return _fallback_narrative(outputs, request, f"LLM generation failed: {exc}")
