"""文件职责：验证 project lifecycle 相关规则、边界与回归行为。"""

from __future__ import annotations

from datetime import date
from typing import Any

from merchpilot.services.project_lifecycle import ProjectLifecycleState, derive_project_lifecycle


def lifecycle_state(**overrides: Any) -> ProjectLifecycleState:
    """辅助构造`lifecycle state`测试数据或依赖，减少用例中的重复准备代码。"""
    values: dict[str, Any] = {
        "project_id": "project-1",
        "project_status": "draft",
        "run_id": None,
        "run_status": None,
        "run_error_message": None,
        "approval_task_id": None,
        "approval_status": None,
        "selected_product_id": None,
        "selected_product_status": None,
        "validation_status": None,
        "initiative_id": None,
        "initiative_status": None,
        "milestones": [],
        "launch_review_id": None,
        "launch_review_status": None,
        "today": date(2026, 9, 3),
    }
    values.update(overrides)
    return derive_project_lifecycle(**values)


def test_draft_project_starts_at_configuration() -> None:
    """验证“draft project starts at configuration”场景，确保业务规则、权限和异常边界保持稳定。"""
    state = lifecycle_state()

    assert state.stage == "project"
    assert state.progress_percent == 0
    assert state.health == "on_track"
    assert state.next_action_type == "planning-project"
    assert state.next_action_id == "project-1"


def test_pending_planning_review_is_attention_and_actionable() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    state = lifecycle_state(
        project_status="approval_required",
        run_id="run-1",
        run_status="approval_required",
        approval_task_id="approval-1",
        approval_status="pending",
    )

    assert state.stage == "approval"
    assert state.progress_percent == 25
    assert state.health == "attention"
    assert state.next_action_type == "planning-approval"
    assert state.next_action_id == "approval-1"


def test_selected_product_waits_for_validation_before_initiative() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    state = lifecycle_state(
        project_status="completed",
        run_id="run-1",
        run_status="completed",
        approval_task_id="approval-1",
        approval_status="approved",
        selected_product_id="selection-1",
        selected_product_status="validating",
        validation_status="partial",
    )

    assert state.stage == "validation"
    assert state.progress_percent == 50
    assert state.next_action_type == "selected-product"
    assert state.next_action_id == "selection-1"


def test_downstream_selection_prevents_stale_pending_approval_from_rewinding_action() -> None:
    """
    验证“downstream selection prevents stale pending approval from rewinding
    action”场景，确保业务规则、权限和异常边界保持稳定。
    """
    state = lifecycle_state(
        project_status="approval_required",
        run_id="run-1",
        run_status="approval_required",
        approval_task_id="approval-1",
        approval_status="pending",
        selected_product_id="selection-1",
        selected_product_status="validating",
        validation_status="partial",
    )

    assert state.stage == "validation"
    assert state.health == "on_track"
    assert state.next_action_type == "selected-product"
    assert state.next_action_id == "selection-1"


def test_rejected_launch_review_is_a_blocked_human_checkpoint() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    state = lifecycle_state(
        project_status="completed",
        run_id="run-1",
        run_status="completed",
        approval_task_id="approval-1",
        approval_status="approved",
        selected_product_id="selection-1",
        selected_product_status="initiated",
        validation_status="ready",
        initiative_id="initiative-1",
        initiative_status="launch_ready",
        milestones=[
            {"id": "launch_review", "label": "上市准备评审", "status": "completed"}
        ],
        launch_review_id="review-1",
        launch_review_status="rejected",
    )

    assert state.stage == "launch_review"
    assert state.health == "blocked"
    assert "上市评审未通过" in state.blockers
    assert state.next_action_type == "initiative"
    assert state.next_action_id == "initiative-1"


def test_launched_project_is_a_complete_closed_loop() -> None:
    """验证“launched project is a complete closed loop”场景，确保业务规则、权限和异常边界保持稳定。"""
    state = lifecycle_state(
        project_status="completed",
        run_id="run-1",
        run_status="completed",
        approval_task_id="approval-1",
        approval_status="approved",
        selected_product_id="selection-1",
        selected_product_status="launched",
        validation_status="ready",
        initiative_id="initiative-1",
        initiative_status="launched",
        milestones=[],
        launch_review_id="review-1",
        launch_review_status="approved",
    )

    assert state.stage == "launched"
    assert state.progress_percent == 100
    assert state.health == "complete"
    assert state.next_action_type == "initiative"


def test_overdue_milestone_is_attention_without_hiding_other_progress() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    state = lifecycle_state(
        project_status="completed",
        run_id="run-1",
        run_status="completed",
        approval_task_id="approval-1",
        approval_status="approved",
        selected_product_id="selection-1",
        selected_product_status="initiated",
        validation_status="ready",
        initiative_id="initiative-1",
        initiative_status="in_progress",
        milestones=[
            {
                "id": "sample_finalize",
                "label": "样品定版",
                "status": "in_progress",
                "due_date": "2026-09-02",
            }
        ],
    )

    assert state.stage == "initiative"
    assert state.health == "attention"
    assert state.current_milestone_label == "样品定版"
    assert state.blockers == ("里程碑“样品定版”已延期",)
