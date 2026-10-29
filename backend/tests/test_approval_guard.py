"""文件职责：验证 approval guard 相关规则、边界与回归行为。"""

from datetime import UTC, datetime

from merchpilot.services.approval_guard import approval_review_fingerprint


def test_approval_review_fingerprint_is_stable_for_summary_key_order() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    due_at = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    first = approval_review_fingerprint(
        task_id="approval-1",
        project_id="project-1",
        run_id="run-1",
        approval_type="planning_review",
        checkpoint_ref="checkpoint-1",
        status="pending",
        assignee_id="approver-1",
        due_at=due_at,
        summary={"score": 88, "candidate": {"id": "candidate-1", "name": "方案一"}},
    )
    second = approval_review_fingerprint(
        task_id="approval-1",
        project_id="project-1",
        run_id="run-1",
        approval_type="planning_review",
        checkpoint_ref="checkpoint-1",
        status="pending",
        assignee_id="approver-1",
        due_at=due_at.isoformat(),
        summary={"candidate": {"name": "方案一", "id": "candidate-1"}, "score": 88},
    )

    assert first == second
    assert len(first) == 64


def test_approval_review_fingerprint_changes_after_assignment() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    common = {
        "task_id": "approval-1",
        "project_id": "project-1",
        "run_id": "run-1",
        "approval_type": "planning_review",
        "checkpoint_ref": "checkpoint-1",
        "status": "pending",
        "due_at": None,
        "summary": {"title": "待审批"},
    }

    unassigned = approval_review_fingerprint(assignee_id=None, **common)
    assigned = approval_review_fingerprint(assignee_id="approver-1", **common)

    assert unassigned != assigned
