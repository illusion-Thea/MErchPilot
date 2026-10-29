"""文件职责：验证 finance 相关规则、边界与回归行为。"""

from merchpilot.services.finance import calculate_candidate_financials, calculate_financials


def test_calculate_financials_with_complete_constraints() -> None:
    """验证“calculate financials with complete constraints”场景，确保业务规则、权限和异常边界保持稳定。"""
    result = calculate_financials(
        {
            "price_range": [100, 120],
            "unit_cost": 40,
            "logistics_cost": 5,
            "platform_fee_rate": 10,
            "tax_rate": 3,
            "marketing_rate": 5,
            "target_margin": 40,
            "fixed_cost": 1000,
            "forecast_units": 100,
        }
    )

    assert result["status"] == "ready"
    assert result["selling_price"] == 110.0
    assert result["variable_cost_per_unit"] == 64.8
    assert result["contribution_margin_per_unit"] == 45.2
    assert result["margin_rate"] == 0.4109
    assert result["passed_target_margin"] is True
    assert result["break_even_units"] == 23
    assert result["estimated_profit"] == 3520.0


def test_calculate_financials_reports_missing_and_invalid_fields() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    result = calculate_financials(
        {
            "price_range": [100, None],
            "unit_cost": -1,
            "platform_fee_rate": 120,
        }
    )

    assert result["status"] == "invalid_constraints"
    assert result["missing_fields"] == ["selling_price", "unit_cost"]
    assert set(result["invalid_fields"]) == {"price_range", "unit_cost", "platform_fee_rate"}


def test_candidate_financials_use_candidate_references_for_missing_inputs() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    result = calculate_candidate_financials(
        {
            "id": "concept-1",
            "name": "轻量通勤款",
            "price_reference": {"suggested_price": 139},
            "unit_cost_reference": 65,
            "evidence_ids": ["evidence-1"],
        },
        {"target_margin": 0.4, "forecast_units": 1000},
        {"suggested_finance_inputs": {"logistics_cost": {"value": 10}}},
    )

    assert result["status"] == "ready"
    assert result["selling_price"] == 139.0
    assert result["unit_cost"] == 65.0
    assert result["candidate_backed_fields"] == ["selling_price", "unit_cost"]
    assert result["input_sources"]["selling_price"] == "candidate_reference"
    assert result["input_sources"]["unit_cost"] == "candidate_reference"
    assert result["data_backed_fields"] == ["logistics_cost", "selling_price", "unit_cost"]
    assert result["candidate_evidence_ids"] == ["evidence-1"]


def test_candidate_financials_preserve_explicit_project_constraints() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    result = calculate_candidate_financials(
        {
            "id": "concept-1",
            "price_reference": {"suggested_price": 139},
            "unit_cost_reference": 65,
        },
        {"selling_price": 199, "unit_cost": 80},
    )

    assert result["selling_price"] == 199.0
    assert result["unit_cost"] == 80.0
    assert result["candidate_backed_fields"] == []
