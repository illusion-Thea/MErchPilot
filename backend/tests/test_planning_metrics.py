"""文件职责：验证 planning metrics 相关规则、边界与回归行为。"""

from merchpilot.infrastructure.models import EvidenceRecord
from merchpilot.services.finance import calculate_financials
from merchpilot.services.planning_metrics import build_planning_metrics
from merchpilot.services.supplier import evaluate_supplier_constraints


def record(evidence_id: str, data_type: str, **values: object) -> EvidenceRecord:
    """辅助构造`record`测试数据或依赖，减少用例中的重复准备代码。"""
    row = {
        "data_type": data_type,
        "category": "智能保温杯",
        "target_market": "中国",
        **values,
    }
    return EvidenceRecord(
        id=evidence_id,
        tenant_id="tenant-a",
        source_name="metrics.xlsx",
        source_row=2,
        source_id=evidence_id,
        content=str(values.get("content") or data_type),
        metadata_json={"normalized_row": row},
        quality_status="verified",
        index_status="indexed",
    )


def test_planning_metrics_aggregates_business_fields() -> None:
    """验证“planning metrics aggregates business fields”场景，确保业务规则、权限和异常边界保持稳定。"""
    metrics = build_planning_metrics(
        [
            record(
                "market-1",
                "竞品",
                price=199,
                sales=1000,
                rating=4.5,
                demand_tags="轻量；防摔",
            ),
            record(
                "review-1",
                "用户评论",
                rating=4.0,
                pain_points="难清洗；漏水",
                demand_tags="轻量",
            ),
            record(
                "supplier-1",
                "供应商",
                supplier="华东杯业",
                cost=72,
                moq=500,
                lead_time_days=25,
            ),
            record(
                "cost-1",
                "成本费用",
                price=219,
                cost=80,
                logistics_cost=10,
                forecast_sales=1200,
            ),
        ],
        category="智能保温杯",
        target_market="中国",
    )

    assert metrics["record_count"] == 4
    assert metrics["data_type_counts"] == {
        "竞品": 1,
        "用户评论": 1,
        "供应商": 1,
        "成本费用": 1,
    }
    assert metrics["price"]["median"] == 209.0
    assert metrics["reviews"]["pain_points"][0] == {"label": "难清洗", "count": 1}
    assert metrics["suggested_finance_inputs"]["unit_cost"]["value"] == 80.0
    assert metrics["supplier_candidates"][0]["supplier_name"] == "华东杯业"


def test_finance_uses_evidence_metrics_only_for_missing_inputs() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    result = calculate_financials(
        {"selling_price": 220, "target_margin": 0.4},
        {
            "record_count": 4,
            "suggested_finance_inputs": {
                "selling_price": {"value": 200},
                "unit_cost": {"value": 80},
                "logistics_cost": {"value": 10},
            },
        },
    )

    assert result["status"] == "ready"
    assert result["selling_price"] == 220.0
    assert result["unit_cost"] == 80.0
    assert result["logistics_cost"] == 10.0
    assert result["data_backed_fields"] == ["logistics_cost", "unit_cost"]


def test_supplier_uses_best_available_evidence_candidate() -> None:
    """验证“supplier uses best available evidence candidate”场景，确保业务规则、权限和异常边界保持稳定。"""
    result = evaluate_supplier_constraints(
        {},
        {
            "supplier_candidates": [
                {
                    "supplier_name": "华东杯业",
                    "moq": 500,
                    "lead_time_days": 25,
                    "evidence_id": "supplier-1",
                    "completeness_score": 2,
                }
            ]
        },
    )

    assert result["status"] == "ready"
    assert result["supplier_name"] == "华东杯业"
    assert result["moq"] == 500
    assert result["lead_time_days"] == 25
    assert result["resolution"]["mode"] == "recommended"
    assert result["data_backed"] is True
