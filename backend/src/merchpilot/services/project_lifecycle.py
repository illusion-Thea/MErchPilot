"""文件职责：把同一项目的规划、审批、选品、立项和上市事实推导为闭环台账。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

type LifecycleStageKey = Literal[
    "project",
    "agent",
    "approval",
    "selection",
    "validation",
    "initiative",
    "launch_review",
    "launched",
]
type LifecycleStageStatus = Literal["complete", "current", "waiting", "blocked"]
type LifecycleHealth = Literal["on_track", "attention", "blocked", "complete"]
type LifecycleActionType = Literal[
    "planning-project",
    "planning-approval",
    "selected-product",
    "initiative-create",
    "initiative",
    "launch-review",
]


@dataclass(frozen=True, slots=True)
class LifecycleStage:
    """`LifecycleStage` 封装可复用业务规则，避免接口层重复实现相同判断。"""
    key: LifecycleStageKey
    label: str
    status: LifecycleStageStatus
    detail: str
    entity_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectLifecycleState:
    """`ProjectLifecycleState` 封装可复用业务规则，避免接口层重复实现相同判断。"""
    stage: LifecycleStageKey
    stage_label: str
    progress_percent: int
    health: LifecycleHealth
    blockers: tuple[str, ...]
    next_action_label: str
    next_action_type: LifecycleActionType
    next_action_id: str
    stages: tuple[LifecycleStage, ...]
    current_milestone_id: str | None
    current_milestone_label: str | None
    current_milestone_status: str | None


def _milestone_text(value: object) -> str | None:
    """内部辅助函数`_milestone_text`；拆分主流程并集中处理当前模块的边界条件。"""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _milestone_due_date(value: object) -> date | None:
    """内部辅助函数`_milestone_due_date`；拆分主流程并集中处理当前模块的边界条件。"""
    text = _milestone_text(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _milestone_context(
    milestones: list[dict[str, Any]],
    *,
    today: date,
) -> tuple[str | None, str | None, str | None, tuple[str, ...], bool]:
    """内部辅助函数`_milestone_context`；拆分主流程并集中处理当前模块的边界条件。"""
    current: dict[str, Any] | None = None
    blocked: list[str] = []
    overdue: list[str] = []
    for milestone in milestones:
        status = _milestone_text(milestone.get("status")) or "pending"
        label = _milestone_text(milestone.get("label")) or "未命名里程碑"
        if status == "blocked":
            blocked.append(f"里程碑“{label}”已阻断")
        due_date = _milestone_due_date(milestone.get("due_date"))
        if status != "completed" and due_date is not None and due_date < today:
            overdue.append(f"里程碑“{label}”已延期")
        if current is None and status in {"blocked", "in_progress", "pending"}:
            current = milestone

    blockers = tuple(dict.fromkeys([*blocked, *overdue]))
    if current is None:
        return None, None, None, blockers, bool(overdue)
    return (
        _milestone_text(current.get("id")),
        _milestone_text(current.get("label")),
        _milestone_text(current.get("status")) or "pending",
        blockers,
        bool(overdue),
    )


def derive_project_lifecycle(
    *,
    project_id: str,
    project_status: str,
    run_id: str | None,
    run_status: str | None,
    run_error_message: str | None,
    approval_task_id: str | None,
    approval_status: str | None,
    selected_product_id: str | None,
    selected_product_status: str | None,
    validation_status: str | None,
    initiative_id: str | None,
    initiative_status: str | None,
    milestones: list[dict[str, Any]],
    launch_review_id: str | None,
    launch_review_status: str | None,
    today: date | None = None,
) -> ProjectLifecycleState:
    """把同一项目的规划、审批、选品、立项和上市事实推导为闭环台账状态。"""
    current_date = today or date.today()
    (
        milestone_id,
        milestone_label,
        milestone_status,
        milestone_blockers,
        has_overdue_milestone,
    ) = _milestone_context(milestones, today=current_date)

    blockers: list[str] = list(milestone_blockers)
    has_critical_blocker = milestone_status == "blocked"
    if project_status == "failed":
        blockers.append("规划项目运行失败")
        has_critical_blocker = True
    elif project_status == "cancelled":
        blockers.append("规划项目已取消")
        has_critical_blocker = True
    if run_status == "failed":
        blockers.append(run_error_message.strip() if run_error_message else "Agent 分析运行失败")
        has_critical_blocker = True
    elif run_status == "cancelled":
        blockers.append("Agent 分析运行已取消")
        has_critical_blocker = True
    if approval_status == "rejected":
        blockers.append("规划方案未通过人工审批")
        has_critical_blocker = True
    elif approval_status == "revision_required":
        blockers.append("规划方案需要修订后重新提交")
        has_critical_blocker = True
    elif approval_status == "cancelled":
        blockers.append("规划审批任务已取消")
        has_critical_blocker = True
    if validation_status == "blocked":
        blockers.append("正式选品验证存在阻断项")
        has_critical_blocker = True
    if selected_product_status in {"paused", "cancelled"}:
        blockers.append("正式选品已暂停" if selected_product_status == "paused" else "正式选品已取消")
        has_critical_blocker = True
    if initiative_status in {"paused", "cancelled"}:
        blockers.append("商品立项已暂停" if initiative_status == "paused" else "商品立项已取消")
        has_critical_blocker = True
    if launch_review_status == "rejected":
        blockers.append("上市评审未通过")
        has_critical_blocker = True
    elif launch_review_status == "revision_required":
        blockers.append("上市材料需要修订后重新评审")
        has_critical_blocker = True
    blockers = list(dict.fromkeys(blockers))

    has_run = run_id is not None
    # 历史数据可能存在上游状态未及时回写的情况；已产生下游事实时，以更强的业务事实为准。
    # 例如已经生成正式选品，就不能因为旧审批记录仍是 pending 而把项目错误地退回审批阶段。
    agent_complete = bool(
        run_status in {"approval_required", "completed", "superseded"}
        or approval_task_id
        or selected_product_id
    )
    approval_complete = bool(approval_status == "approved" or selected_product_id)
    selection_complete = selected_product_id is not None
    validation_complete = bool(validation_status == "ready" or initiative_id)
    initiative_complete = bool(
        initiative_status in {"launch_ready", "launched"} or launch_review_id
    )
    launch_review_complete = bool(launch_review_status == "approved" or initiative_status == "launched")
    launched_complete = initiative_status == "launched"

    project_stage_status: LifecycleStageStatus = "complete" if has_run else "current"
    if project_status in {"failed", "cancelled"} and not has_run:
        project_stage_status = "blocked"

    if agent_complete:
        agent_stage_status: LifecycleStageStatus = "complete"
    elif run_status in {"failed", "cancelled"} or project_status == "failed":
        agent_stage_status = "blocked"
    elif has_run:
        agent_stage_status = "current"
    else:
        agent_stage_status = "waiting"

    if approval_complete:
        approval_stage_status: LifecycleStageStatus = "complete"
    elif approval_status in {"rejected", "revision_required", "cancelled"}:
        approval_stage_status = "blocked"
    elif approval_status == "pending" or run_status in {"approval_required", "completed"}:
        approval_stage_status = "current"
    else:
        approval_stage_status = "waiting"

    selection_stage_status: LifecycleStageStatus = (
        "complete"
        if selection_complete
        else "current"
        if approval_complete
        else "waiting"
    )
    if validation_complete:
        validation_stage_status: LifecycleStageStatus = "complete"
    elif validation_status == "blocked" or selected_product_status in {"paused", "cancelled"}:
        validation_stage_status = "blocked"
    elif selection_complete:
        validation_stage_status = "current"
    else:
        validation_stage_status = "waiting"

    if initiative_complete:
        initiative_stage_status: LifecycleStageStatus = "complete"
    elif initiative_status in {"paused", "cancelled"} or milestone_status == "blocked":
        initiative_stage_status = "blocked"
    elif initiative_id:
        initiative_stage_status = "current"
    elif validation_complete:
        initiative_stage_status = "current"
    else:
        initiative_stage_status = "waiting"

    if launch_review_complete:
        launch_review_stage_status: LifecycleStageStatus = "complete"
    elif launch_review_status in {"rejected", "revision_required"}:
        launch_review_stage_status = "blocked"
    elif launch_review_status == "pending" or initiative_status == "launch_ready":
        launch_review_stage_status = "current"
    else:
        launch_review_stage_status = "waiting"
    launched_stage_status: LifecycleStageStatus = (
        "complete"
        if launched_complete
        else "current"
        if launch_review_complete
        else "waiting"
    )

    stages = (
        LifecycleStage(
            key="project",
            label="需求定义",
            status=project_stage_status,
            detail="项目范围已确认" if has_run else "配置品类、市场与业务约束",
            entity_id=project_id,
        ),
        LifecycleStage(
            key="agent",
            label="Agent 分析",
            status=agent_stage_status,
            detail=(
                "分析结果已形成"
                if agent_complete
                else "分析运行异常"
                if agent_stage_status == "blocked"
                else "正在生成机会判断"
                if has_run
                else "等待项目启动"
            ),
            entity_id=run_id,
        ),
        LifecycleStage(
            key="approval",
            label="规划审批",
            status=approval_stage_status,
            detail=(
                "人工审批已通过"
                if approval_complete
                else "需要处理审批意见"
                if approval_stage_status == "blocked"
                else "等待人工审批"
                if approval_stage_status == "current"
                else "等待分析完成"
            ),
            entity_id=approval_task_id,
        ),
        LifecycleStage(
            key="selection",
            label="正式选品",
            status=selection_stage_status,
            detail="正式选品已生成" if selection_complete else "等待沉淀正式选品",
            entity_id=selected_product_id,
        ),
        LifecycleStage(
            key="validation",
            label="选品验证",
            status=validation_stage_status,
            detail=(
                "验证门禁已通过"
                if validation_complete
                else "验证存在阻断项"
                if validation_stage_status == "blocked"
                else "补充样品、成本与供应材料"
                if selection_complete
                else "等待正式选品"
            ),
            entity_id=selected_product_id,
        ),
        LifecycleStage(
            key="initiative",
            label="商品立项",
            status=initiative_stage_status,
            detail=(
                "上市准备已完成"
                if initiative_complete
                else f"当前：{milestone_label}"
                if milestone_label
                else "创建商品立项并推进里程碑"
                if validation_complete
                else "等待验证通过"
            ),
            entity_id=initiative_id,
        ),
        LifecycleStage(
            key="launch_review",
            label="上市评审",
            status=launch_review_stage_status,
            detail=(
                "上市评审已通过"
                if launch_review_complete
                else "处理评审意见"
                if launch_review_stage_status == "blocked"
                else "等待人工上市评审"
                if launch_review_stage_status == "current"
                else "等待立项就绪"
            ),
            entity_id=launch_review_id,
        ),
        LifecycleStage(
            key="launched",
            label="上市落地",
            status=launched_stage_status,
            detail="商品已确认上市" if launched_complete else "等待最终上市确认",
            entity_id=initiative_id,
        ),
    )

    # 优先展示阻断或正在进行的最早环节，用户进入台账后可直接处理真正的当前问题。
    active_stage = next(
        (stage for stage in stages if stage.status in {"blocked", "current"}),
        stages[-1],
    )
    completed_count = sum(stage.status == "complete" for stage in stages)

    if launched_complete:
        health: LifecycleHealth = "complete"
    elif has_critical_blocker:
        health = "blocked"
    elif (
        blockers
        or (approval_status == "pending" and not approval_complete)
        or (launch_review_status == "pending" and not launch_review_complete)
    ):
        health = "attention"
    else:
        health = "on_track"

    # 下一步动作始终指向系统内可定位的实体，页面和 FastMCP 因此能复用同一闭环语义。
    if not has_run or run_status in {"queued", "running", "failed", "cancelled"}:
        action_label = "检查配置并推进 Agent" if has_run else "配置并启动 Agent"
        action_type: LifecycleActionType = "planning-project"
        action_id = project_id
    elif approval_status == "pending" and approval_task_id and not approval_complete:
        action_label = "进入规划审批"
        action_type = "planning-approval"
        action_id = approval_task_id
    elif approval_status in {"rejected", "revision_required", "cancelled"}:
        action_label = "修订规划方案"
        action_type = "planning-project"
        action_id = project_id
    elif not approval_complete:
        action_label = "查看分析与审批状态"
        action_type = "planning-project"
        action_id = project_id
    elif not selected_product_id:
        action_label = "查看正式选品生成状态"
        action_type = "planning-project"
        action_id = project_id
    elif not validation_complete:
        action_label = "处理选品验证"
        action_type = "selected-product"
        action_id = selected_product_id
    elif not initiative_id:
        action_label = "创建商品立项"
        action_type = "initiative-create"
        action_id = selected_product_id
    elif launch_review_status == "pending" and launch_review_id:
        action_label = "进入上市评审"
        action_type = "launch-review"
        action_id = launch_review_id
    else:
        action_label = "查看上市推进" if not launched_complete else "查看上市结果"
        action_type = "initiative"
        action_id = initiative_id

    return ProjectLifecycleState(
        stage=active_stage.key,
        stage_label=active_stage.label,
        progress_percent=round(completed_count / len(stages) * 100),
        health=health,
        blockers=tuple(blockers),
        next_action_label=action_label,
        next_action_type=action_type,
        next_action_id=action_id,
        stages=stages,
        current_milestone_id=milestone_id,
        current_milestone_label=milestone_label,
        current_milestone_status=milestone_status,
    )
