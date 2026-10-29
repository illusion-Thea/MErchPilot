"""文件职责：验证 concepts 相关规则、边界与回归行为。"""

from merchpilot.services.concepts import (
    apply_candidate_selection,
    apply_candidate_validation_updates,
    build_candidate_concepts,
    resolve_candidate_concept,
)


def test_build_candidate_concepts_returns_evidence_backed_candidates() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    outputs = {
        "competitor": {
            "hits": [
                {
                    "id": "competitor-1",
                    "metadata": {
                        "normalized_row": {
                            "selling_points": "温显；防漏",
                            "demand_tags": "轻量；便携",
                            "price": 199,
                        }
                    },
                }
            ]
        },
        "user_insight": {
            "hits": [
                {
                    "id": "review-1",
                    "metadata": {
                        "normalized_row": {
                            "pain_points": "难清洗；漏水",
                            "demand_tags": "便携",
                        }
                    },
                }
            ]
        },
    }
    metrics = {
        "record_count": 20,
        "coverage": {
            "market_trend": 2,
            "competitor": 5,
            "user_reviews": 10,
            "supplier": 2,
            "cost": 2,
        },
        "price": {"min": 99, "max": 299, "median": 189, "p25": 139, "p75": 239},
        "suggested_finance_inputs": {"unit_cost": {"value": 65}},
    }

    concept = build_candidate_concepts(
        {
            "category": "智能保温杯",
            "target_market": "中国",
            "constraints": {"target_user": "城市白领"},
        },
        outputs,
        metrics,
    )

    assert concept["candidate_count"] == 3
    assert concept["name"] == "智能保温杯轻量通勤款"
    assert concept["candidates"][0]["evidence_features"] == ["便携", "温显", "防漏", "轻量"]
    assert concept["candidates"][0]["pain_points_addressed"] == ["难清洗", "漏水"]
    assert concept["candidates"][0]["price_reference"]["suggested_price"] == 139
    assert concept["candidates"][0]["unit_cost_reference"] == 65
    assert concept["candidates"][0]["requires_validation"] is True
    assert concept["candidates"][0]["evidence_ids"] == ["competitor-1", "review-1"]
    assert concept["data_basis"]["record_count"] == 20
    assert concept["recommended_candidate_id"] == "concept-1"
    assert concept["candidates"][0]["scorecard"]["total_score"] == 77
    assert concept["candidates"][0]["scorecard"]["breakdown"]["commercial"]["score"] == 35
    assert concept["candidates"][0]["recommendation"] == "优先验证"
    assert concept["candidates"][1]["recommendation"] == "备选验证"
    assert concept["candidates"][0]["financial_scenario"]["selling_price"] == 139.0
    assert concept["candidates"][0]["financial_scenario"]["unit_cost"] == 65.0
    validation_plan = concept["candidates"][0]["validation_plan"]
    assert validation_plan["status"] == "partial"
    assert validation_plan["completed_gates"] == 3
    assert validation_plan["total_gates"] == 4
    assert validation_plan["completion_rate"] == 75
    assert validation_plan["gates"][1]["label"] == "规格与样品"
    assert validation_plan["gates"][1]["status"] == "pending"
    assert validation_plan["gates"][1]["materials"] == []
    assert "完成样品和小批量测试" in validation_plan["next_actions"][0]

    selected = resolve_candidate_concept(concept, "concept-2")
    assert selected is not None
    assert selected["name"] == "智能保温杯智能温控款"
    approved = apply_candidate_selection(concept, "concept-2", "approved")
    assert approved["selected_candidate_id"] == "concept-2"
    assert approved["selected_candidate"]["name"] == "智能保温杯智能温控款"
    assert approved["selection_status"] == "approved"


def test_apply_candidate_validation_updates_recomputes_status_and_audit_fields() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    plan = {
        "status": "partial",
        "status_label": "部分具备，需补齐验证",
        "completed_gates": 3,
        "total_gates": 4,
        "completion_rate": 75,
        "gates": [
            {"id": "demand_fit", "label": "需求匹配", "status": "ready", "criteria": "需求证据"},
            {"id": "specification", "label": "规格与样品", "status": "pending", "criteria": "完成样品测试"},
        ],
        "next_actions": ["完成样品测试"],
        "requires_validation": True,
    }

    updated = apply_candidate_validation_updates(
        plan,
        [{"gate_id": "specification", "status": "ready", "note": "样品测试通过"}],
        actor_id="planner-1",
        updated_at="2026-08-26T12:00:00+00:00",
    )

    assert updated["status"] == "ready"
    assert updated["completion_rate"] == 100
    assert updated["requires_validation"] is False
    assert updated["next_actions"] == ["进入小批量试销，记录转化、退货和复购指标"]
    assert updated["gates"][1]["note"] == "样品测试通过"
    assert updated["gates"][1]["updated_by"] == "planner-1"
