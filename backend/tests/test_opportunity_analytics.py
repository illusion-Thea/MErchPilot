"""文件职责：验证 opportunity analytics 相关规则、边界与回归行为。"""

from merchpilot.services.opportunity_analytics import extract_opportunity_metrics


def test_extract_opportunity_metrics_reads_latest_run_snapshot() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    metrics = extract_opportunity_metrics(
        {
            "outputs": {
                "scorecard": {
                    "score": 83,
                    "status": "ready",
                    "evidence_count": 7,
                    "breakdown": {"finance": {"score": 30, "max_score": 35}},
                },
                "finance": {"margin_rate": 0.4382},
                "supplier": {"risk_level": "low"},
            }
        }
    )

    assert metrics == {
        "score": 83,
        "score_status": "ready",
        "evidence_count": 7,
        "margin_rate": 0.4382,
        "supplier_risk": "low",
        "score_breakdown": {"finance": {"score": 30, "max_score": 35}},
    }


def test_extract_opportunity_metrics_does_not_invent_missing_score() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    assert extract_opportunity_metrics(None) == {
        "score": None,
        "score_status": None,
        "evidence_count": 0,
        "margin_rate": None,
        "supplier_risk": None,
        "score_breakdown": {},
    }
