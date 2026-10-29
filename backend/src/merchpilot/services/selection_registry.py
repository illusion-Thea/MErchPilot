"""文件职责：在规划审批通过后登记正式选品，并保持来源链路可追溯。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, SupportsFloat, SupportsIndex, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from merchpilot.core.ids import new_id
from merchpilot.infrastructure.database import async_session_factory
from merchpilot.infrastructure.models import ApprovalTask, PlanningProject, PlanningRun, SelectedProduct
from merchpilot.services.audit import record_audit_event
from merchpilot.services.concepts import resolve_candidate_concept


def _record(value: object) -> dict[str, Any]:
    """内部辅助函数`_record`；拆分主流程并集中处理当前模块的边界条件。"""
    return value if isinstance(value, dict) else {}


def _text(value: object) -> str | None:
    """内部辅助函数`_text`；拆分主流程并集中处理当前模块的边界条件。"""
    normalized = str(value or "").strip()
    return normalized or None


def _number(value: object) -> float | None:
    """内部辅助函数`_number`；拆分主流程并集中处理当前模块的边界条件。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(cast(str | SupportsFloat | SupportsIndex, value))
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _integer(value: object) -> int | None:
    """内部辅助函数`_integer`；拆分主流程并集中处理当前模块的边界条件。"""
    number = _number(value)
    return round(number) if number is not None else None


async def register_approved_selection(
    run_id: str,
    state: dict[str, Any],
) -> SelectedProduct | None:
    """把审批通过的候选概念登记为正式选品，并保留项目、运行和证据来源。"""
    outputs = _record(state.get("outputs"))
    concept = _record(outputs.get("concept"))
    selected_candidate = _record(concept.get("selected_candidate"))
    if not selected_candidate:
        selected_candidate = resolve_candidate_concept(
            concept,
            concept.get("selected_candidate_id"),
        ) or {}
    candidate_id = _text(selected_candidate.get("id")) or f"legacy_{run_id}"

    async with async_session_factory() as session:
        existing = await session.scalar(
            select(SelectedProduct).where(SelectedProduct.run_id == run_id)
        )
        if existing is not None:
            return existing
        run = await session.get(PlanningRun, run_id)
        if run is None:
            raise RuntimeError("planning run not found while registering selected product")
        project = await session.get(PlanningProject, run.project_id)
        if project is None:
            raise RuntimeError("planning project not found while registering selected product")
        approval = await session.scalar(
            select(ApprovalTask)
            .where(
                ApprovalTask.run_id == run_id,
                ApprovalTask.status == "approved",
            )
            .order_by(ApprovalTask.decided_at.desc(), ApprovalTask.updated_at.desc())
            .limit(1)
        )
        if approval is None:
            return None

        finance = _record(outputs.get("selected_candidate_finance")) or _record(
            outputs.get("finance")
        )
        supplier = _record(outputs.get("supplier"))
        scorecard = _record(selected_candidate.get("scorecard"))
        overall_scorecard = _record(outputs.get("scorecard"))
        validation_plan = _record(selected_candidate.get("validation_plan"))
        selected_by = approval.decided_by or approval.assignee_id or "system"
        selected_product = SelectedProduct(
            id=new_id("selection"),
            tenant_id=project.tenant_id,
            project_id=project.id,
            run_id=run.id,
            approval_task_id=approval.id,
            candidate_id=candidate_id,
            name=(
                _text(selected_candidate.get("name"))
                or _text(concept.get("name"))
                or project.name
            ),
            project_name=project.name,
            category=project.category,
            target_market=project.target_market,
            positioning=(
                _text(selected_candidate.get("positioning"))
                or _text(concept.get("positioning"))
            ),
            status="selected",
            owner_id=selected_by,
            score=_integer(scorecard.get("total_score") or overall_scorecard.get("score")),
            selling_price=_number(finance.get("selling_price")),
            margin_rate=_number(finance.get("margin_rate")),
            estimated_profit=_number(finance.get("estimated_profit")),
            supplier_name=_text(supplier.get("supplier_name")),
            validation_status=_text(validation_plan.get("status")),
            selection_snapshot=state,
            selected_by=selected_by,
            selected_at=approval.decided_at or datetime.now(UTC),
        )
        session.add(selected_product)
        record_audit_event(
            session,
            action="selected_product.created",
            entity_type="selected_product",
            entity_id=selected_product.id,
            project_id=project.id,
            tenant_id=project.tenant_id,
            actor_id=selected_by,
            detail={
                "run_id": run.id,
                "approval_task_id": approval.id,
                "candidate_id": candidate_id,
                "name": selected_product.name,
            },
        )
        await session.commit()
        await session.refresh(selected_product)
        return selected_product


async def sync_selected_product_validation(
    session: AsyncSession,
    *,
    run_id: str,
    candidate_id: str,
    validation_plan: dict[str, Any],
    actor_id: str,
) -> SelectedProduct | None:
    """实现`sync_selected_product_validation`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    selected_product = await session.scalar(
        select(SelectedProduct)
        .where(
            SelectedProduct.run_id == run_id,
            SelectedProduct.candidate_id == candidate_id,
        )
        .with_for_update()
    )
    if selected_product is None:
        return None

    previous_status = selected_product.status
    previous_validation_status = selected_product.validation_status
    validation_status = _text(validation_plan.get("status"))
    selected_product.validation_status = validation_status
    if selected_product.status in {"selected", "validating", "ready"}:
        if validation_status == "ready":
            selected_product.status = "ready"
        elif selected_product.status in {"selected", "ready"}:
            selected_product.status = "validating"

    record_audit_event(
        session,
        action="selected_product.validation_synced",
        entity_type="selected_product",
        entity_id=selected_product.id,
        project_id=selected_product.project_id,
        tenant_id=selected_product.tenant_id,
        actor_id=actor_id,
        detail={
            "run_id": run_id,
            "candidate_id": candidate_id,
            "previous_status": previous_status,
            "current_status": selected_product.status,
            "previous_validation_status": previous_validation_status,
            "validation_status": validation_status,
            "completion_rate": _integer(validation_plan.get("completion_rate")),
        },
    )
    return selected_product
