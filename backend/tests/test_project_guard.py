"""文件职责：验证 project guard 相关规则、边界与回归行为。"""

from merchpilot.services.project_guard import project_configuration_fingerprint


def test_project_configuration_fingerprint_is_stable_for_key_order() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    first = project_configuration_fingerprint(
        name="通勤杯规划",
        category="保温杯",
        target_market="中国",
        constraints={"price_range": {"min": 129, "max": 199}, "target_margin": 0.35},
    )
    second = project_configuration_fingerprint(
        name="通勤杯规划",
        category="保温杯",
        target_market="中国",
        constraints={"target_margin": 0.35, "price_range": {"max": 199, "min": 129}},
    )

    assert first == second
    assert len(first) == 64


def test_project_configuration_fingerprint_changes_with_reviewed_input() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    original = project_configuration_fingerprint(
        name="通勤杯规划",
        category="保温杯",
        target_market="中国",
        constraints={"target_margin": 0.35},
    )
    updated = project_configuration_fingerprint(
        name="通勤杯规划",
        category="保温杯",
        target_market="中国",
        constraints={"target_margin": 0.36},
    )

    assert original != updated
