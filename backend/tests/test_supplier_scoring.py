"""文件职责：验证 supplier scoring 相关规则、边界与回归行为。"""

from merchpilot.services.scoring import build_scorecard
from merchpilot.services.supplier import evaluate_supplier_constraints


def test_supplier_evaluation_detects_operational_risks() -> None:
    """验证“supplier evaluation detects operational risks”场景，确保业务规则、权限和异常边界保持稳定。"""
    result = evaluate_supplier_constraints(
        {
            "supplier_name": "示例供应商",
            "moq": 1200,
            "lead_time_days": 45,
            "max_lead_time_days": 30,
            "forecast_units": 1000,
        }
    )

    assert result["status"] == "ready"
    assert result["risk_level"] == "high"
    assert result["risk_flags"] == [
        "moq_exceeds_forecast_units",
        "lead_time_exceeds_limit",
    ]


def test_scorecard_reaches_full_score_with_complete_low_risk_inputs() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    constraints = {
        "target_user": "年轻白领",
        "target_margin": 0.4,
        "supplier_name": "示例供应商",
        "moq": 500,
        "lead_time_days": 30,
    }
    finance = {
        "status": "ready",
        "selling_price": 100.0,
        "unit_cost": 40.0,
        "margin_rate": 0.45,
        "target_margin": 0.4,
    }
    supplier = {
        "status": "ready",
        "supplier_name": "示例供应商",
        "moq": 500,
        "lead_time_days": 30,
        "risk_flags": [],
    }

    result = build_scorecard([f"evidence-{index}" for index in range(5)], finance, supplier, constraints)

    assert result["score"] == 100
    assert result["status"] == "ready"
    assert result["breakdown"]["finance"] == {"score": 35, "max_score": 35}


def test_scorecard_blocks_when_evidence_and_finance_are_missing() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    result = build_scorecard(
        [],
        {"status": "requires_cost_data"},
        {"status": "requires_supplier_data"},
        {},
    )

    assert result["score"] == 0
    assert result["status"] == "blocked"
    assert len(result["blockers"]) == 2
