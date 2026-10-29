"""文件职责：验证 validation guard 相关规则、边界与回归行为。"""

from merchpilot.services.validation_guard import validation_review_fingerprint


def test_validation_review_fingerprint_is_stable_for_key_order_and_ignores_output_token() -> None:
    """
    验证“validation review fingerprint is stable for key order and ignores output
    token”场景，确保业务规则、权限和异常边界保持稳定。
    """
    first = validation_review_fingerprint(
        project_id="project-1",
        run_id="run-1",
        run_status="approval_required",
        candidate_id="candidate-1",
        validation_plan={
            "status": "partial",
            "gates": [{"id": "sample", "status": "pending", "materials": []}],
        },
    )
    second = validation_review_fingerprint(
        project_id="project-1",
        run_id="run-1",
        run_status="approval_required",
        candidate_id="candidate-1",
        validation_plan={
            "review_token": "not-part-of-reviewed-state",
            "gates": [{"materials": [], "status": "pending", "id": "sample"}],
            "status": "partial",
        },
    )

    assert first == second
    assert len(first) == 64


def test_validation_review_fingerprint_changes_with_gate_state_or_materials() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    pending = validation_review_fingerprint(
        project_id="project-1",
        run_id="run-1",
        run_status="completed",
        candidate_id="candidate-1",
        validation_plan={"gates": [{"id": "sample", "status": "pending", "materials": []}]},
    )
    ready = validation_review_fingerprint(
        project_id="project-1",
        run_id="run-1",
        run_status="completed",
        candidate_id="candidate-1",
        validation_plan={
            "gates": [
                {
                    "id": "sample",
                    "status": "ready",
                    "materials": [{"id": "material-1", "storage_key": "sample.pdf"}],
                }
            ]
        },
    )

    assert pending != ready
