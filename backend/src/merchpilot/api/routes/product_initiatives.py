"""文件职责：管理商品立项、里程碑、试销、上市评审和完整时间线。"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal, TypedDict, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from pydantic import ValidationError
from sqlalchemy import func, or_, select, text
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from merchpilot.api.dependencies import get_current_identity, require_approver, require_planner
from merchpilot.api.schemas import (
    AuditEventPage,
    AuditEventRead,
    PilotSaleCreate,
    PilotSalePage,
    PilotSaleRead,
    PilotSaleSummary,
    PilotSaleTrend,
    PilotSaleUpdate,
    ProductInitiativeCreate,
    ProductInitiativePage,
    ProductInitiativePageSummary,
    ProductInitiativeRead,
    ProductInitiativeUpdate,
    ProductLaunchReadiness,
    ProductLaunchReviewContext,
    ProductLaunchReviewDecision,
    ProductLaunchReviewPage,
    ProductLaunchReviewPageSummary,
    ProductLaunchReviewRead,
    ProductLaunchReviewSubmit,
    ProductMilestoneUpdate,
)
from merchpilot.core.ids import new_id
from merchpilot.infrastructure.database import get_db_session
from merchpilot.infrastructure.models import (
    AuditEvent,
    PilotSaleRecord,
    ProductInitiative,
    ProductLaunchReview,
    SelectedProduct,
)
from merchpilot.ports.identity import Identity
from merchpilot.services.audit import record_audit_event
from merchpilot.services.idempotency import (
    build_idempotency_record,
    find_idempotency_record,
    idempotency_payload_hash,
)
from merchpilot.services.launch_review_guard import launch_review_fingerprint

router = APIRouter(prefix="/product-initiatives", tags=["product-initiatives"])

initiative_statuses = {"in_progress", "launch_ready", "launched", "paused", "cancelled"}
page_statuses = initiative_statuses | {"needs_attention"}
milestone_statuses = {"pending", "in_progress", "completed", "blocked"}
launch_review_statuses = {"pending", "approved", "rejected", "revision_required"}
launch_review_page_statuses = launch_review_statuses | {"processed", "all"}
selected_product_status_by_initiative_status = {
    "in_progress": "initiated",
    "launched": "launched",
    "paused": "paused",
    "cancelled": "cancelled",
}


class PilotSaleAggregate(TypedDict):
    """`PilotSaleAggregate` 封装本模块相关状态和行为，对调用方提供清晰边界。"""
    visitors: int
    orders: int
    units_sold: int
    revenue: float
    product_cost: float
    marketing_spend: float
    refunds_amount: float
    return_count: int
    conversion_rate: float | None
    return_rate: float | None
    average_order_value: float | None
    gross_profit: float
    actual_margin_rate: float | None
    marketing_roi: float | None


class PilotSaleSummaryPayload(PilotSaleAggregate):
    """`PilotSaleSummaryPayload` 封装本模块相关状态和行为，对调用方提供清晰边界。"""
    record_count: int
    average_rating: float | None
    planned_margin_rate: float | None
    margin_gap: float | None
    assessment_status: Literal["insufficient", "recommended", "review", "blocked"]
    assessment_label: str
    risks: list[str]
    recommendations: list[str]


class ProductLaunchReadinessPayload(TypedDict):
    """`ProductLaunchReadinessPayload` 封装本模块相关状态和行为，对调用方提供清晰边界。"""
    readiness_status: Literal["ready", "review", "blocked"]
    readiness_label: str
    checks: list[dict[str, str]]
    blockers: list[str]
    warnings: list[str]
    recommendations: list[str]


class ProductLaunchReviewContextPayload(TypedDict):
    """`ProductLaunchReviewContextPayload` 封装本模块相关状态和行为，对调用方提供清晰边界。"""
    initiative_id: str
    initiative_name: str
    initiative_status: str
    readiness: ProductLaunchReadinessPayload
    pilot_summary: PilotSaleSummaryPayload
    pending_review: dict[str, object] | None
    can_submit: bool
    submission_blockers: list[str]
    review_token: str


def _default_milestones(actor_id: str) -> list[dict[str, object]]:
    """内部辅助函数`_default_milestones`；拆分主流程并集中处理当前模块的边界条件。"""
    updated_at = datetime.now(UTC).isoformat()
    return [
        {
            "id": "project_kickoff",
            "label": "立项确认",
            "status": "completed",
            "owner_id": actor_id,
            "due_date": None,
            "note": "正式选品验证通过，已创建商品立项",
            "updated_by": actor_id,
            "updated_at": updated_at,
        },
        {
            "id": "sample_finalize",
            "label": "样品定版",
            "status": "pending",
            "owner_id": None,
            "due_date": None,
            "note": None,
        },
        {
            "id": "cost_finalize",
            "label": "成本定版",
            "status": "pending",
            "owner_id": None,
            "due_date": None,
            "note": None,
        },
        {
            "id": "pilot_sale",
            "label": "小批量试销",
            "status": "pending",
            "owner_id": None,
            "due_date": None,
            "note": None,
        },
        {
            "id": "launch_review",
            "label": "上市准备评审",
            "status": "pending",
            "owner_id": None,
            "due_date": None,
            "note": None,
        },
    ]


def _all_milestones_completed(initiative: ProductInitiative) -> bool:
    """内部辅助函数`_all_milestones_completed`；拆分主流程并集中处理当前模块的边界条件。"""
    return bool(initiative.milestones) and all(
        isinstance(item, dict) and item.get("status") == "completed"
        for item in initiative.milestones
    )


def _initiative_attention_condition() -> ColumnElement[bool]:
    """内部辅助函数`_initiative_attention_condition`；拆分主流程并集中处理当前模块的边界条件。"""
    blocked_milestone = ProductInitiative.milestones.contains([{"status": "blocked"}])
    overdue_milestone = text(
        "EXISTS ("
        "SELECT 1 FROM jsonb_array_elements(product_initiatives.milestones) AS milestone(value) "
        "WHERE milestone.value ->> 'status' <> 'completed' "
        "AND NULLIF(milestone.value ->> 'due_date', '') IS NOT NULL "
        "AND (milestone.value ->> 'due_date')::date < CURRENT_DATE"
        ")"
    )
    return or_(
        ProductInitiative.status == "launch_ready",
        blocked_milestone,
        (ProductInitiative.status == "in_progress") & overdue_milestone,
    )


def _safe_rate(numerator: float, denominator: float) -> float | None:
    """内部辅助函数`_safe_rate`；拆分主流程并集中处理当前模块的边界条件。"""
    return round(numerator / denominator, 6) if denominator > 0 else None


def _pilot_sale_read(record: PilotSaleRecord) -> dict[str, object]:
    """内部辅助函数`_pilot_sale_read`；拆分主流程并集中处理当前模块的边界条件。"""
    gross_profit = round(
        record.revenue - record.product_cost - record.marketing_spend - record.refunds_amount,
        2,
    )
    return {
        "id": record.id,
        "initiative_id": record.initiative_id,
        "period_start": record.period_start,
        "period_end": record.period_end,
        "channel": record.channel,
        "visitors": record.visitors,
        "orders": record.orders,
        "units_sold": record.units_sold,
        "revenue": record.revenue,
        "product_cost": record.product_cost,
        "marketing_spend": record.marketing_spend,
        "refunds_amount": record.refunds_amount,
        "return_count": record.return_count,
        "rating": record.rating,
        "notes": record.notes,
        "conversion_rate": _safe_rate(record.orders, record.visitors),
        "return_rate": _safe_rate(record.return_count, record.units_sold),
        "average_order_value": _safe_rate(record.revenue, record.orders),
        "gross_profit": gross_profit,
        "actual_margin_rate": _safe_rate(gross_profit, record.revenue),
        "marketing_roi": _safe_rate(gross_profit, record.marketing_spend),
        "created_by": record.created_by,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def _pilot_sale_snapshot(record: PilotSaleRecord) -> dict[str, object]:
    """内部辅助函数`_pilot_sale_snapshot`；拆分主流程并集中处理当前模块的边界条件。"""
    return {
        "period_start": record.period_start.isoformat(),
        "period_end": record.period_end.isoformat(),
        "channel": record.channel,
        "visitors": record.visitors,
        "orders": record.orders,
        "units_sold": record.units_sold,
        "revenue": record.revenue,
        "product_cost": record.product_cost,
        "marketing_spend": record.marketing_spend,
        "refunds_amount": record.refunds_amount,
        "return_count": record.return_count,
        "rating": record.rating,
        "notes": record.notes,
    }


def _pilot_sale_aggregate_columns() -> tuple[ColumnElement[Any], ...]:
    """内部辅助函数`_pilot_sale_aggregate_columns`；拆分主流程并集中处理当前模块的边界条件。"""
    return (
        func.count(PilotSaleRecord.id).label("record_count"),
        func.coalesce(func.sum(PilotSaleRecord.visitors), 0).label("visitors"),
        func.coalesce(func.sum(PilotSaleRecord.orders), 0).label("orders"),
        func.coalesce(func.sum(PilotSaleRecord.units_sold), 0).label("units_sold"),
        func.coalesce(func.sum(PilotSaleRecord.revenue), 0).label("revenue"),
        func.coalesce(func.sum(PilotSaleRecord.product_cost), 0).label("product_cost"),
        func.coalesce(func.sum(PilotSaleRecord.marketing_spend), 0).label("marketing_spend"),
        func.coalesce(func.sum(PilotSaleRecord.refunds_amount), 0).label("refunds_amount"),
        func.coalesce(func.sum(PilotSaleRecord.return_count), 0).label("return_count"),
        func.avg(PilotSaleRecord.rating).label("average_rating"),
    )


def _pilot_sale_aggregate_from_row(row: RowMapping) -> PilotSaleAggregate:
    """内部辅助函数`_pilot_sale_aggregate_from_row`；拆分主流程并集中处理当前模块的边界条件。"""
    visitors = int(row["visitors"] or 0)
    orders = int(row["orders"] or 0)
    units_sold = int(row["units_sold"] or 0)
    revenue = round(float(row["revenue"] or 0), 2)
    product_cost = round(float(row["product_cost"] or 0), 2)
    marketing_spend = round(float(row["marketing_spend"] or 0), 2)
    refunds_amount = round(float(row["refunds_amount"] or 0), 2)
    return_count = int(row["return_count"] or 0)
    gross_profit = round(revenue - product_cost - marketing_spend - refunds_amount, 2)
    return {
        "visitors": visitors,
        "orders": orders,
        "units_sold": units_sold,
        "revenue": revenue,
        "product_cost": product_cost,
        "marketing_spend": marketing_spend,
        "refunds_amount": refunds_amount,
        "return_count": return_count,
        "conversion_rate": _safe_rate(orders, visitors),
        "return_rate": _safe_rate(return_count, units_sold),
        "average_order_value": _safe_rate(revenue, orders),
        "gross_profit": gross_profit,
        "actual_margin_rate": _safe_rate(gross_profit, revenue),
        "marketing_roi": _safe_rate(gross_profit, marketing_spend),
    }


def _pilot_sale_trend_point_from_row(
    row: RowMapping,
    *,
    label: str,
    period_start: date,
    period_end: date,
    channel: str,
) -> dict[str, object]:
    """内部辅助函数`_pilot_sale_trend_point_from_row`；拆分主流程并集中处理当前模块的边界条件。"""
    aggregate = _pilot_sale_aggregate_from_row(row)
    return {
        "label": label,
        "period_start": period_start,
        "period_end": period_end,
        "channel": channel,
        "visitors": aggregate["visitors"],
        "orders": aggregate["orders"],
        "units_sold": aggregate["units_sold"],
        "revenue": aggregate["revenue"],
        "gross_profit": aggregate["gross_profit"],
        "conversion_rate": aggregate["conversion_rate"],
        "return_rate": aggregate["return_rate"],
        "actual_margin_rate": aggregate["actual_margin_rate"],
    }


async def _build_pilot_sales_summary(
    session: AsyncSession,
    initiative: ProductInitiative,
) -> PilotSaleSummaryPayload:
    """内部辅助函数`_build_pilot_sales_summary`；拆分主流程并集中处理当前模块的边界条件。"""
    metrics = (
        await session.execute(
            select(*_pilot_sale_aggregate_columns()).where(
                PilotSaleRecord.initiative_id == initiative.id,
                PilotSaleRecord.tenant_id == initiative.tenant_id,
            )
        )
    ).mappings().one()
    record_count = int(metrics["record_count"] or 0)
    totals = _pilot_sale_aggregate_from_row(metrics)
    gross_profit = totals["gross_profit"]
    selected_product = await session.get(SelectedProduct, initiative.selected_product_id)
    planned_margin_rate = selected_product.margin_rate if selected_product is not None else None
    actual_margin_rate = _safe_rate(gross_profit, totals["revenue"])
    conversion_rate = _safe_rate(totals["orders"], totals["visitors"])
    return_rate = _safe_rate(totals["return_count"], totals["units_sold"])
    average_rating = (
        round(float(metrics["average_rating"]), 2)
        if metrics["average_rating"] is not None
        else None
    )

    blockers: list[str] = []
    warnings: list[str] = []
    if record_count == 0:
        assessment_status: Literal["insufficient", "recommended", "review", "blocked"] = (
            "insufficient"
        )
        assessment_label = "暂无试销数据"
        risks = ["尚未形成可用于经营判断的试销记录"]
        recommendations = ["录入至少一个完整试销周期后再评估上市准备"]
    else:
        if totals["orders"] <= 0:
            blockers.append("试销期没有形成订单")
        if gross_profit <= 0:
            blockers.append("试销实际利润不为正")
        if return_rate is not None:
            if return_rate > 0.2:
                blockers.append("退货率超过 20%")
            elif return_rate > 0.1:
                warnings.append("退货率超过 10%")
        if average_rating is not None:
            if average_rating < 3:
                blockers.append("平均用户评分低于 3 分")
            elif average_rating < 4:
                warnings.append("平均用户评分低于 4 分")
        if actual_margin_rate is not None and actual_margin_rate < 0:
            blockers.append("实际毛利率为负")
        elif (
            actual_margin_rate is not None
            and planned_margin_rate is not None
            and actual_margin_rate < planned_margin_rate
        ):
            warnings.append("实际毛利率低于规划毛利率")
        if blockers:
            assessment_status = "blocked"
            assessment_label = "试销存在上市阻断项"
            recommendations = ["暂停上市准备，先解决阻断项并重新开展试销"]
        elif warnings:
            assessment_status = "review"
            assessment_label = "试销结果需要复核"
            recommendations = ["针对风险项调整定价、成本、投放或产品体验后继续观察"]
        else:
            assessment_status = "recommended"
            assessment_label = "试销表现支持继续推进"
            recommendations = ["可推进试销里程碑，并持续跟踪复购、售后与渠道稳定性"]
        risks = blockers + warnings

    return {
        "record_count": record_count,
        **totals,
        "conversion_rate": conversion_rate,
        "return_rate": return_rate,
        "average_order_value": totals["average_order_value"],
        "gross_profit": gross_profit,
        "actual_margin_rate": actual_margin_rate,
        "marketing_roi": totals["marketing_roi"],
        "average_rating": average_rating,
        "planned_margin_rate": planned_margin_rate,
        "margin_gap": (
            round(actual_margin_rate - planned_margin_rate, 6)
            if actual_margin_rate is not None and planned_margin_rate is not None
            else None
        ),
        "assessment_status": assessment_status,
        "assessment_label": assessment_label,
        "risks": risks,
        "recommendations": recommendations,
    }


async def _build_product_launch_readiness(
    session: AsyncSession,
    initiative: ProductInitiative,
    ignored_milestone_ids: set[str] | None = None,
) -> ProductLaunchReadinessPayload:
    """内部辅助函数`_build_product_launch_readiness`；拆分主流程并集中处理当前模块的边界条件。"""
    pilot_summary = await _build_pilot_sales_summary(session, initiative)
    ignored_milestone_ids = ignored_milestone_ids or set()
    checks: list[dict[str, str]] = []
    blockers: list[str] = []
    warnings: list[str] = []

    incomplete_milestones = [
        str(item.get("label") or item.get("id"))
        for item in initiative.milestones
        if (
            isinstance(item, dict)
            and item.get("id") not in ignored_milestone_ids
            and item.get("status") != "completed"
        )
    ]
    if incomplete_milestones:
        blockers.append(f"尚未完成里程碑：{', '.join(incomplete_milestones)}")
        checks.append({
            "id": "milestones",
            "label": "五阶段里程碑",
            "status": "blocked",
            "detail": f"还需完成：{'、'.join(incomplete_milestones)}",
        })
    else:
        checks.append({
            "id": "milestones",
            "label": "五阶段里程碑",
            "status": "passed",
            "detail": (
                "评审前置里程碑已完成"
                if "launch_review" in ignored_milestone_ids
                else "全部里程碑已完成"
            ),
        })

    pilot_status = str(pilot_summary["assessment_status"])
    if pilot_status == "insufficient":
        blockers.append("尚未形成可用于上市判断的试销数据")
        checks.append({
            "id": "pilot_sales",
            "label": "试销经营表现",
            "status": "blocked",
            "detail": "至少需要一个完整试销周期",
        })
    elif pilot_status == "blocked":
        blockers.extend(str(item) for item in pilot_summary["risks"])
        checks.append({
            "id": "pilot_sales",
            "label": "试销经营表现",
            "status": "blocked",
            "detail": str(pilot_summary["assessment_label"]),
        })
    elif pilot_status == "review":
        warnings.extend(str(item) for item in pilot_summary["risks"])
        checks.append({
            "id": "pilot_sales",
            "label": "试销经营表现",
            "status": "warning",
            "detail": str(pilot_summary["assessment_label"]),
        })
    else:
        checks.append({
            "id": "pilot_sales",
            "label": "试销经营表现",
            "status": "passed",
            "detail": str(pilot_summary["assessment_label"]),
        })

    if initiative.owner_id:
        checks.append({
            "id": "owner",
            "label": "上市负责人",
            "status": "passed",
            "detail": initiative.owner_id,
        })
    else:
        warnings.append("尚未设置上市负责人")
        checks.append({
            "id": "owner",
            "label": "上市负责人",
            "status": "warning",
            "detail": "请设置负责上市推进的人员",
        })

    if initiative.target_launch_date is None:
        warnings.append("尚未设置目标上市日期")
        checks.append({
            "id": "target_launch_date",
            "label": "目标上市日期",
            "status": "warning",
            "detail": "请补充目标上市日期",
        })
    elif initiative.target_launch_date < date.today():
        blockers.append("目标上市日期已过期")
        checks.append({
            "id": "target_launch_date",
            "label": "目标上市日期",
            "status": "blocked",
            "detail": f"目标日期为 {initiative.target_launch_date.isoformat()}",
        })
    else:
        checks.append({
            "id": "target_launch_date",
            "label": "目标上市日期",
            "status": "passed",
            "detail": initiative.target_launch_date.isoformat(),
        })

    if initiative.budget is None:
        warnings.append("尚未设置立项预算")
        checks.append({
            "id": "budget",
            "label": "立项预算",
            "status": "warning",
            "detail": "请补充预算，便于上市投入复盘",
        })
    else:
        checks.append({
            "id": "budget",
            "label": "立项预算",
            "status": "passed",
            "detail": f"¥{initiative.budget:,.2f}",
        })

    if blockers:
        readiness_status: Literal["ready", "review", "blocked"] = "blocked"
        readiness_label = "暂不能确认上市"
        recommendations = ["先处理上市阻断项，再重新执行上市准备预检"]
    elif warnings:
        readiness_status = "review"
        readiness_label = "满足上市条件，但需要人工复核"
        recommendations = ["完成风险复核并由负责人确认后再执行上市"]
    else:
        readiness_status = "ready"
        readiness_label = "已具备确认上市条件"
        recommendations = ["可由授权人员确认上市，并保留本次预检结果"]
    return {
        "readiness_status": readiness_status,
        "readiness_label": readiness_label,
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
        "recommendations": recommendations,
    }


def _launch_review_read(
    review: ProductLaunchReview,
    initiative_name: str | None = None,
    project_id: str | None = None,
    category: str | None = None,
    target_market: str | None = None,
) -> dict[str, object]:
    """内部辅助函数`_launch_review_read`；拆分主流程并集中处理当前模块的边界条件。"""
    return {
        "id": review.id,
        "tenant_id": review.tenant_id,
        "initiative_id": review.initiative_id,
        "initiative_name": initiative_name,
        "project_id": project_id,
        "category": category,
        "target_market": target_market,
        "status": review.status,
        "submission_note": review.submission_note,
        "decision_note": review.decision_note,
        "readiness_snapshot": review.readiness_snapshot,
        "submitted_by": review.submitted_by,
        "submitted_at": review.submitted_at,
        "decided_by": review.decided_by,
        "decided_at": review.decided_at,
        "created_at": review.created_at,
        "updated_at": review.updated_at,
    }


async def _pending_launch_review(
    session: AsyncSession,
    initiative: ProductInitiative,
) -> ProductLaunchReview | None:
    """内部辅助函数`_pending_launch_review`；拆分主流程并集中处理当前模块的边界条件。"""
    return cast(
        ProductLaunchReview | None,
        await session.scalar(
            select(ProductLaunchReview)
            .where(
                ProductLaunchReview.tenant_id == initiative.tenant_id,
                ProductLaunchReview.initiative_id == initiative.id,
                ProductLaunchReview.status == "pending",
            )
            .order_by(ProductLaunchReview.submitted_at.desc(), ProductLaunchReview.id.desc())
        ),
    )


async def _build_launch_review_context(
    session: AsyncSession,
    initiative: ProductInitiative,
) -> ProductLaunchReviewContextPayload:
    """内部辅助函数`_build_launch_review_context`；拆分主流程并集中处理当前模块的边界条件。"""
    readiness = await _build_product_launch_readiness(
        session,
        initiative,
        ignored_milestone_ids={"launch_review"},
    )
    pilot_summary = await _build_pilot_sales_summary(session, initiative)
    pending_review = await _pending_launch_review(session, initiative)
    pending_review_payload = (
        _launch_review_read(pending_review, initiative.name) if pending_review is not None else None
    )
    submission_blockers: list[str] = []
    if initiative.status in {"launched", "paused", "cancelled"}:
        submission_blockers.append("当前立项状态不允许提交上市准备评审")
    launch_review_milestone = next(
        (
            item
            for item in initiative.milestones
            if isinstance(item, dict) and item.get("id") == "launch_review"
        ),
        None,
    )
    if launch_review_milestone is None:
        submission_blockers.append("立项缺少上市准备评审里程碑")
    elif launch_review_milestone.get("status") == "completed":
        submission_blockers.append("上市准备评审已通过")
    if pending_review is not None:
        submission_blockers.append("已有待处理的上市准备评审")
    if readiness["readiness_status"] == "blocked":
        submission_blockers.extend(str(item) for item in readiness["blockers"])
    review_token = launch_review_fingerprint(
        initiative_id=initiative.id,
        project_id=initiative.project_id,
        run_id=initiative.run_id,
        selected_product_id=initiative.selected_product_id,
        initiative_status=initiative.status,
        owner_id=initiative.owner_id,
        target_launch_date=initiative.target_launch_date,
        budget=initiative.budget,
        notes=initiative.notes,
        milestones=[dict(item) for item in initiative.milestones if isinstance(item, dict)],
        readiness=dict(readiness),
        pilot_summary=dict(pilot_summary),
        pending_review=pending_review_payload,
    )
    return {
        "initiative_id": initiative.id,
        "initiative_name": initiative.name,
        "initiative_status": initiative.status,
        "readiness": readiness,
        "pilot_summary": pilot_summary,
        "pending_review": pending_review_payload,
        "can_submit": not submission_blockers,
        "submission_blockers": submission_blockers,
        "review_token": review_token,
    }


async def _latest_approved_launch_review(
    session: AsyncSession,
    initiative: ProductInitiative,
) -> ProductLaunchReview | None:
    """内部辅助函数`_latest_approved_launch_review`；拆分主流程并集中处理当前模块的边界条件。"""
    return cast(
        ProductLaunchReview | None,
        await session.scalar(
            select(ProductLaunchReview)
            .where(
                ProductLaunchReview.tenant_id == initiative.tenant_id,
                ProductLaunchReview.initiative_id == initiative.id,
                ProductLaunchReview.status == "approved",
            )
            .order_by(ProductLaunchReview.decided_at.desc(), ProductLaunchReview.id.desc())
        )
    )


def _update_launch_review_milestone(
    initiative: ProductInitiative,
    *,
    status_value: str,
    actor_id: str,
    note: str | None,
) -> None:
    """内部辅助函数`_update_launch_review_milestone`；拆分主流程并集中处理当前模块的边界条件。"""
    milestones = [dict(item) for item in initiative.milestones if isinstance(item, dict)]
    milestone = next((item for item in milestones if item.get("id") == "launch_review"), None)
    if milestone is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="立项缺少上市准备评审里程碑",
        )
    milestone["status"] = status_value
    milestone["owner_id"] = milestone.get("owner_id") or actor_id
    milestone["note"] = note
    milestone["updated_by"] = actor_id
    milestone["updated_at"] = datetime.now(UTC).isoformat()
    initiative.milestones = milestones


async def _get_initiative(
    session: AsyncSession,
    initiative_id: str,
    tenant_id: str,
    *,
    lock: bool = False,
) -> ProductInitiative:
    """内部辅助函数`_get_initiative`；拆分主流程并集中处理当前模块的边界条件。"""
    query = select(ProductInitiative).where(
        ProductInitiative.id == initiative_id,
        ProductInitiative.tenant_id == tenant_id,
    )
    if lock:
        query = query.with_for_update()
    initiative = await session.scalar(query)
    if initiative is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="product initiative not found",
        )
    return initiative


@router.get("", response_model=list[ProductInitiativeRead])
async def list_product_initiatives(
    initiative_status: str | None = Query(default=None, alias="status"),
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> list[ProductInitiative]:
    """处理`GET `接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    query = select(ProductInitiative).where(
        ProductInitiative.tenant_id == identity.tenant_id
    )
    if initiative_status is not None:
        if initiative_status not in initiative_statuses:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid product initiative status",
            )
        query = query.where(ProductInitiative.status == initiative_status)
    result = await session.scalars(
        query.order_by(ProductInitiative.updated_at.desc(), ProductInitiative.id.desc())
    )
    return list(result)


@router.get("/page", response_model=ProductInitiativePage)
async def page_product_initiatives(
    response: Response,
    initiative_status: str | None = Query(default=None, alias="status"),
    keyword: str | None = Query(default=None, min_length=1, max_length=255),
    initiative_id: str | None = None,
    project_id: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=6, ge=1, le=100),
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    """处理`GET /page`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    conditions = [ProductInitiative.tenant_id == identity.tenant_id]
    if initiative_status is not None:
        if initiative_status not in page_statuses:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid product initiative status",
            )
        if initiative_status == "needs_attention":
            conditions.append(_initiative_attention_condition())
        else:
            conditions.append(ProductInitiative.status == initiative_status)
    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        conditions.append(
            or_(
                ProductInitiative.id.ilike(pattern),
                ProductInitiative.name.ilike(pattern),
                ProductInitiative.category.ilike(pattern),
                ProductInitiative.target_market.ilike(pattern),
                ProductInitiative.owner_id.ilike(pattern),
                ProductInitiative.selected_product_id.ilike(pattern),
                ProductInitiative.project_id.ilike(pattern),
            )
        )
    if initiative_id is not None:
        conditions.append(ProductInitiative.id == initiative_id)
    if project_id is not None:
        conditions.append(ProductInitiative.project_id == project_id)

    total = int(
        await session.scalar(
            select(func.count(ProductInitiative.id)).where(*conditions)
        )
        or 0
    )
    summary_conditions = [ProductInitiative.tenant_id == identity.tenant_id]
    if project_id is not None:
        summary_conditions.append(ProductInitiative.project_id == project_id)
    summary = ProductInitiativePageSummary(
        total=int(
            await session.scalar(
                select(func.count(ProductInitiative.id)).where(*summary_conditions)
            )
            or 0
        ),
        active=int(
            await session.scalar(
                select(func.count(ProductInitiative.id)).where(
                    *summary_conditions,
                    ProductInitiative.status == "in_progress",
                )
            )
            or 0
        ),
        attention=int(
            await session.scalar(
                select(func.count(ProductInitiative.id)).where(
                    *summary_conditions,
                    _initiative_attention_condition(),
                )
            )
            or 0
        ),
        ready=int(
            await session.scalar(
                select(func.count(ProductInitiative.id)).where(
                    *summary_conditions,
                    ProductInitiative.status == "launch_ready",
                )
            )
            or 0
        ),
        launched=int(
            await session.scalar(
                select(func.count(ProductInitiative.id)).where(
                    *summary_conditions,
                    ProductInitiative.status == "launched",
                )
            )
            or 0
        ),
    )
    result = await session.scalars(
        select(ProductInitiative)
        .where(*conditions)
        .order_by(ProductInitiative.updated_at.desc(), ProductInitiative.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    response.headers["X-Total-Count"] = str(total)
    return {
        "items": list(result),
        "total": total,
        "page": page,
        "page_size": page_size,
        "summary": summary.model_dump(),
    }


@router.get("/launch-reviews", response_model=list[ProductLaunchReviewRead])
async def list_tenant_product_launch_reviews(
    review_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=200),
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, object]]:
    """处理`GET /launch-reviews`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    query = (
        select(
            ProductLaunchReview,
            ProductInitiative.name,
            ProductInitiative.project_id,
            ProductInitiative.category,
            ProductInitiative.target_market,
        )
        .join(ProductInitiative, ProductInitiative.id == ProductLaunchReview.initiative_id)
        .where(
            ProductLaunchReview.tenant_id == identity.tenant_id,
            ProductInitiative.tenant_id == identity.tenant_id,
        )
        .order_by(ProductLaunchReview.created_at.desc(), ProductLaunchReview.id.desc())
        .limit(limit)
    )
    if review_status is not None:
        if review_status not in launch_review_statuses:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid launch review status",
            )
        query = query.where(ProductLaunchReview.status == review_status)
    result = await session.execute(query)
    return [
        _launch_review_read(review, initiative_name, project_id, category, target_market)
        for review, initiative_name, project_id, category, target_market in result
    ]


@router.get("/launch-reviews/page", response_model=ProductLaunchReviewPage)
async def page_tenant_product_launch_reviews(
    response: Response,
    review_status: str | None = Query(default=None, alias="status"),
    initiative_id: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=5, ge=1, le=100),
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    """处理`GET /launch-reviews/page`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    conditions = [
        ProductLaunchReview.tenant_id == identity.tenant_id,
        ProductInitiative.tenant_id == identity.tenant_id,
    ]
    if initiative_id is not None:
        initiative = await _get_initiative(session, initiative_id, identity.tenant_id)
        conditions.append(ProductLaunchReview.initiative_id == initiative.id)
    if project_id is not None:
        conditions.append(ProductInitiative.project_id == project_id)
    if review_status is not None:
        if review_status not in launch_review_page_statuses:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid launch review status",
            )
        if review_status == "processed":
            conditions.append(ProductLaunchReview.status != "pending")
        elif review_status != "all":
            conditions.append(ProductLaunchReview.status == review_status)

    total = int(
        await session.scalar(
            select(func.count(ProductLaunchReview.id))
            .join(ProductInitiative, ProductInitiative.id == ProductLaunchReview.initiative_id)
            .where(*conditions)
        )
        or 0
    )
    summary_conditions = [
        ProductLaunchReview.tenant_id == identity.tenant_id,
        ProductInitiative.tenant_id == identity.tenant_id,
    ]
    if initiative_id is not None:
        summary_conditions.append(ProductLaunchReview.initiative_id == initiative_id)
    if project_id is not None:
        summary_conditions.append(ProductInitiative.project_id == project_id)
    summary_rows = await session.execute(
        select(ProductLaunchReview.status, func.count(ProductLaunchReview.id))
        .join(ProductInitiative, ProductInitiative.id == ProductLaunchReview.initiative_id)
        .where(*summary_conditions)
        .group_by(ProductLaunchReview.status)
    )
    summary_counts = {str(status_value): int(count) for status_value, count in summary_rows}
    result = await session.execute(
        select(
            ProductLaunchReview,
            ProductInitiative.name,
            ProductInitiative.project_id,
            ProductInitiative.category,
            ProductInitiative.target_market,
        )
        .join(ProductInitiative, ProductInitiative.id == ProductLaunchReview.initiative_id)
        .where(*conditions)
        .order_by(ProductLaunchReview.created_at.desc(), ProductLaunchReview.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    response.headers["X-Total-Count"] = str(total)
    return {
        "items": [
            _launch_review_read(review, initiative_name, project_id, category, target_market)
            for review, initiative_name, project_id, category, target_market in result
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "summary": ProductLaunchReviewPageSummary(
            total=sum(summary_counts.values()),
            pending=summary_counts.get("pending", 0),
            approved=summary_counts.get("approved", 0),
            rejected=summary_counts.get("rejected", 0),
            revision_required=summary_counts.get("revision_required", 0),
            processed=sum(
                count for status_value, count in summary_counts.items() if status_value != "pending"
            ),
        ).model_dump(),
    }


@router.get("/launch-reviews/{review_id}", response_model=ProductLaunchReviewRead)
async def get_tenant_product_launch_review(
    review_id: str,
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    """处理`GET /launch-reviews/{review_id}`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    result = await session.execute(
        select(
            ProductLaunchReview,
            ProductInitiative.name,
            ProductInitiative.project_id,
            ProductInitiative.category,
            ProductInitiative.target_market,
        )
        .join(ProductInitiative, ProductInitiative.id == ProductLaunchReview.initiative_id)
        .where(
            ProductLaunchReview.id == review_id,
            ProductLaunchReview.tenant_id == identity.tenant_id,
            ProductInitiative.tenant_id == identity.tenant_id,
        )
    )
    item = result.first()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="launch review not found")
    review, initiative_name, project_id, category, target_market = item
    return _launch_review_read(review, initiative_name, project_id, category, target_market)


@router.post("", response_model=ProductInitiativeRead, status_code=status.HTTP_201_CREATED)
async def create_product_initiative(
    payload: ProductInitiativeCreate,
    identity: Identity = Depends(require_planner),
    session: AsyncSession = Depends(get_db_session),
) -> ProductInitiative:
    """处理`POST `接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    selected_product = await session.scalar(
        select(SelectedProduct)
        .where(
            SelectedProduct.id == payload.selected_product_id,
            SelectedProduct.tenant_id == identity.tenant_id,
        )
        .with_for_update()
    )
    if selected_product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="selected product not found")
    if selected_product.validation_status != "ready" or selected_product.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="正式选品必须完成验证并处于可立项状态",
        )
    existing = await session.scalar(
        select(ProductInitiative).where(
            ProductInitiative.selected_product_id == selected_product.id
        )
    )
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该正式选品已创建立项")

    initiative = ProductInitiative(
        id=new_id("initiative"),
        tenant_id=identity.tenant_id,
        selected_product_id=selected_product.id,
        project_id=selected_product.project_id,
        run_id=selected_product.run_id,
        name=selected_product.name,
        category=selected_product.category,
        target_market=selected_product.target_market,
        status="in_progress",
        owner_id=(payload.owner_id or "").strip() or selected_product.owner_id or identity.user_id,
        target_launch_date=payload.target_launch_date,
        budget=payload.budget,
        milestones=_default_milestones(identity.user_id),
        notes=(payload.notes or "").strip() or None,
        created_by=identity.user_id,
    )
    session.add(initiative)
    selected_product.status = "initiated"
    record_audit_event(
        session,
        action="product_initiative.created",
        entity_type="product_initiative",
        entity_id=initiative.id,
        project_id=initiative.project_id,
        tenant_id=identity.tenant_id,
        actor_id=identity.user_id,
        detail={
            "selected_product_id": selected_product.id,
            "name": initiative.name,
            "owner_id": initiative.owner_id,
            "target_launch_date": (
                initiative.target_launch_date.isoformat()
                if initiative.target_launch_date is not None
                else None
            ),
        },
    )
    record_audit_event(
        session,
        action="selected_product.initiated",
        entity_type="selected_product",
        entity_id=selected_product.id,
        project_id=selected_product.project_id,
        tenant_id=identity.tenant_id,
        actor_id=identity.user_id,
        detail={"initiative_id": initiative.id, "name": initiative.name},
    )
    await session.commit()
    await session.refresh(initiative)
    return initiative


@router.get("/{initiative_id}", response_model=ProductInitiativeRead)
async def get_product_initiative(
    initiative_id: str,
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> ProductInitiative:
    """处理`GET /{initiative_id}`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    return await _get_initiative(session, initiative_id, identity.tenant_id)


@router.patch("/{initiative_id}", response_model=ProductInitiativeRead)
async def update_product_initiative(
    initiative_id: str,
    payload: ProductInitiativeUpdate,
    identity: Identity = Depends(require_planner),
    session: AsyncSession = Depends(get_db_session),
) -> ProductInitiative:
    """处理`PATCH /{initiative_id}`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    initiative = await _get_initiative(session, initiative_id, identity.tenant_id, lock=True)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return initiative
    previous_status = initiative.status
    launch_readiness: ProductLaunchReadinessPayload | None = None
    next_status: str | None = None
    if "status" in changes and changes["status"] is not None:
        next_status = str(changes["status"])
        if initiative.status == "launched" and next_status != "launched":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已上市立项不能回退状态")
        if initiative.status == "cancelled" and next_status != "cancelled":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已取消立项不能恢复或继续推进")
        initiative.status = next_status
    if "owner_id" in changes:
        initiative.owner_id = str(changes["owner_id"] or "").strip() or None
    if "target_launch_date" in changes:
        initiative.target_launch_date = changes["target_launch_date"]
    if "budget" in changes:
        initiative.budget = changes["budget"]
    if "notes" in changes:
        initiative.notes = str(changes["notes"] or "").strip() or None
    if next_status == "launched":
        launch_readiness = await _build_product_launch_readiness(session, initiative)
        if launch_readiness["readiness_status"] == "blocked":
            blockers = "；".join(str(item) for item in launch_readiness["blockers"])
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"上市准备预检未通过：{blockers}",
            )
        if initiative.launched_at is None:
            initiative.launched_at = datetime.now(UTC)
    selected_product_status = selected_product_status_by_initiative_status.get(next_status or "")
    if selected_product_status is not None:
        selected_product = await session.scalar(
            select(SelectedProduct)
            .where(
                SelectedProduct.id == initiative.selected_product_id,
                SelectedProduct.tenant_id == identity.tenant_id,
            )
            .with_for_update()
        )
        if selected_product is not None and selected_product.status != selected_product_status:
            previous_product_status = selected_product.status
            selected_product.status = selected_product_status
            record_audit_event(
                session,
                action="selected_product.status_synced",
                entity_type="selected_product",
                entity_id=selected_product.id,
                project_id=initiative.project_id,
                tenant_id=identity.tenant_id,
                actor_id=identity.user_id,
                detail={
                    "initiative_id": initiative.id,
                    "previous_status": previous_product_status,
                    "current_status": selected_product.status,
                },
            )
    record_audit_event(
        session,
        action="product_initiative.updated",
        entity_type="product_initiative",
        entity_id=initiative.id,
        project_id=initiative.project_id,
        tenant_id=identity.tenant_id,
        actor_id=identity.user_id,
        detail={
            "changed_fields": sorted(changes),
            "previous_status": previous_status,
            "current_status": initiative.status,
            "launch_readiness_status": (
                launch_readiness["readiness_status"]
                if launch_readiness is not None
                else None
            ),
            "launch_readiness_warnings": (
                launch_readiness["warnings"]
                if launch_readiness is not None
                else []
            ),
        },
    )
    await session.commit()
    await session.refresh(initiative)
    return initiative


@router.patch("/{initiative_id}/milestones/{milestone_id}", response_model=ProductInitiativeRead)
async def update_product_milestone(
    initiative_id: str,
    milestone_id: str,
    payload: ProductMilestoneUpdate,
    identity: Identity = Depends(require_planner),
    session: AsyncSession = Depends(get_db_session),
) -> ProductInitiative:
    """处理该接口。

    执行身份、租户、参数和业务状态校验后返回类型化响应。
    """
    initiative = await _get_initiative(session, initiative_id, identity.tenant_id, lock=True)
    if initiative.status in {"launched", "paused", "cancelled"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前立项状态不允许更新里程碑",
        )
    milestones = [dict(item) for item in initiative.milestones if isinstance(item, dict)]
    milestone_index = next(
        (index for index, item in enumerate(milestones) if item.get("id") == milestone_id),
        None,
    )
    if milestone_index is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="milestone not found")
    changes = payload.model_dump(exclude_unset=True)
    milestone = milestones[milestone_index]
    if "status" in changes and changes["status"] is not None:
        next_status = str(changes["status"])
        if next_status not in milestone_statuses:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid milestone status",
            )
        if next_status != "completed":
            active_later_milestones = [
                str(item.get("label") or item.get("id"))
                for item in milestones[milestone_index + 1 :]
                if item.get("status") in {"in_progress", "completed"}
            ]
            if active_later_milestones:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"后置里程碑已开始或完成，不能回退当前节点: "
                        f"{', '.join(active_later_milestones)}"
                    ),
                )
            if milestone_id == "launch_review":
                approved_review = await _latest_approved_launch_review(session, initiative)
                if approved_review is not None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="上市准备评审已通过，不能回退里程碑",
                    )
        if next_status == "completed":
            incomplete_dependencies = [
                str(item.get("label") or item.get("id"))
                for item in milestones[:milestone_index]
                if item.get("status") != "completed"
            ]
            if incomplete_dependencies:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"请先完成前置里程碑: {', '.join(incomplete_dependencies)}",
                )
            if milestone_id == "launch_review":
                approved_review = await _latest_approved_launch_review(session, initiative)
                if approved_review is None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="请先提交并通过上市准备评审",
                    )
            if milestone_id in {"pilot_sale", "launch_review"}:
                summary = await _build_pilot_sales_summary(session, initiative)
                if summary["record_count"] == 0:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="请先录入真实试销经营数据",
                    )
                if summary["assessment_status"] == "blocked":
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="试销评估存在上市阻断项，不能完成该里程碑",
                    )
        milestone["status"] = next_status
    if "owner_id" in changes:
        milestone["owner_id"] = str(changes["owner_id"] or "").strip() or None
    if "due_date" in changes:
        due_date = changes["due_date"]
        milestone["due_date"] = due_date.isoformat() if due_date is not None else None
    if "note" in changes:
        milestone["note"] = str(changes["note"] or "").strip() or None
    milestone["updated_by"] = identity.user_id
    milestone["updated_at"] = datetime.now(UTC).isoformat()
    milestones[milestone_index] = milestone
    initiative.milestones = milestones
    if _all_milestones_completed(initiative):
        initiative.status = "launch_ready"
    elif initiative.status not in {"paused", "cancelled"}:
        initiative.status = "in_progress"
    record_audit_event(
        session,
        action="product_initiative.milestone_updated",
        entity_type="product_initiative",
        entity_id=initiative.id,
        project_id=initiative.project_id,
        tenant_id=identity.tenant_id,
        actor_id=identity.user_id,
        detail={
            "milestone_id": milestone_id,
            "milestone_label": milestone.get("label"),
            "milestone_status": milestone.get("status"),
            "initiative_status": initiative.status,
        },
    )
    await session.commit()
    await session.refresh(initiative)
    return initiative


@router.get("/{initiative_id}/launch-reviews", response_model=list[ProductLaunchReviewRead])
async def list_product_launch_reviews(
    initiative_id: str,
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, object]]:
    """处理`GET /{initiative_id}/launch-reviews`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    initiative = await _get_initiative(session, initiative_id, identity.tenant_id)
    result = await session.scalars(
        select(ProductLaunchReview)
        .where(
            ProductLaunchReview.tenant_id == identity.tenant_id,
            ProductLaunchReview.initiative_id == initiative.id,
        )
        .order_by(ProductLaunchReview.created_at.desc(), ProductLaunchReview.id.desc())
    )
    return [
        _launch_review_read(
            item,
            initiative.name,
            initiative.project_id,
            initiative.category,
            initiative.target_market,
        )
        for item in result
    ]


@router.get(
    "/{initiative_id}/launch-review-context",
    response_model=ProductLaunchReviewContext,
)
async def get_product_launch_review_context(
    initiative_id: str,
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> ProductLaunchReviewContext:
    """处理该接口。

    执行身份、租户、参数和业务状态校验后返回类型化响应。
    """
    initiative = await _get_initiative(session, initiative_id, identity.tenant_id)
    return ProductLaunchReviewContext.model_validate(
        await _build_launch_review_context(session, initiative)
    )


@router.post(
    "/{initiative_id}/launch-reviews",
    response_model=ProductLaunchReviewRead,
    status_code=status.HTTP_201_CREATED,
)
async def submit_product_launch_review(
    initiative_id: str,
    payload: ProductLaunchReviewSubmit,
    response: Response,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
    ),
    client_name: str | None = Header(
        default=None,
        alias="X-MerchPilot-Client",
        max_length=64,
    ),
    identity: Identity = Depends(require_planner),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    """处理`POST /{initiative_id}/launch-reviews`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    request_key = idempotency_key.strip() if idempotency_key else None
    request_client = client_name.strip().lower() if client_name and client_name.strip() else "web"
    if idempotency_key is not None and (request_key is None or len(request_key) < 8):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="上市评审请求标识去除空格后至少需要 8 个字符",
        )
    normalized_note = (payload.submission_note or "").strip()
    payload_hash = idempotency_payload_hash(
        {"initiative_id": initiative_id, "submission_note": normalized_note or None}
    )
    operation = "product_launch_review.submit"

    async def replayed_submission() -> ProductLaunchReview | None:
        """返回同一幂等请求的既有结果，避免客户端重试重复创建业务事实。"""
        if request_key is None:
            return None
        existing = await find_idempotency_record(
            session,
            tenant_id=identity.tenant_id,
            actor_id=identity.user_id,
            operation=operation,
            idempotency_key=request_key,
        )
        if existing is None:
            return None
        if existing.payload_hash != payload_hash or existing.resource_type != "product_launch_review":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="同一上市评审请求标识不能提交不同的评审内容",
            )
        replayed = await session.scalar(
            select(ProductLaunchReview).where(
                ProductLaunchReview.id == existing.resource_id,
                ProductLaunchReview.tenant_id == identity.tenant_id,
                ProductLaunchReview.initiative_id == initiative_id,
            )
        )
        if replayed is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="幂等请求关联的上市评审不存在，请使用新的请求标识",
            )
        response.headers["Idempotency-Replayed"] = "true"
        response.status_code = status.HTTP_200_OK
        return replayed

    if request_client == "fastmcp":
        if request_key is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="FastMCP 提交上市评审必须提供幂等请求标识",
            )
        if payload.confirmation != "SUBMIT_LAUNCH_REVIEW":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="FastMCP 提交上市评审必须明确确认 SUBMIT_LAUNCH_REVIEW",
            )
        if payload.review_token is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="FastMCP 提交上市评审必须提供最新复核令牌",
            )
        if not normalized_note:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="FastMCP 提交上市评审必须填写评审说明",
            )

    replayed = await replayed_submission()
    if replayed is not None:
        return _launch_review_read(replayed)
    initiative = await _get_initiative(session, initiative_id, identity.tenant_id, lock=True)
    replayed = await replayed_submission()
    if replayed is not None:
        return _launch_review_read(replayed)
    context = await _build_launch_review_context(session, initiative)
    if not context["can_submit"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"上市准备评审提交前置条件未满足：{'；'.join(context['submission_blockers'])}",
        )
    if request_client == "fastmcp" and payload.review_token != context["review_token"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="上市准备状态已发生变化，请重新读取并复核最新状态后再提交",
        )
    readiness = context["readiness"]
    now = datetime.now(UTC)
    review = ProductLaunchReview(
        id=new_id("launch-review"),
        tenant_id=identity.tenant_id,
        initiative_id=initiative.id,
        status="pending",
        submission_note=normalized_note or None,
        readiness_snapshot=dict(readiness),
        submitted_by=identity.user_id,
        submitted_at=now,
    )
    session.add(review)
    _update_launch_review_milestone(
        initiative,
        status_value="in_progress",
        actor_id=identity.user_id,
        note="已提交上市准备评审，等待审批",
    )
    initiative.status = "in_progress"
    record_audit_event(
        session,
        action="product_initiative.launch_review_submitted",
        entity_type="product_initiative",
        entity_id=initiative.id,
        project_id=initiative.project_id,
        tenant_id=identity.tenant_id,
        actor_id=identity.user_id,
        detail={
            "review_id": review.id,
            "readiness_status": readiness["readiness_status"],
            "warnings": readiness["warnings"],
            "client": request_client,
            "idempotency_key": request_key,
            "review_token": payload.review_token,
        },
    )
    if request_key:
        session.add(
            build_idempotency_record(
                tenant_id=identity.tenant_id,
                actor_id=identity.user_id,
                operation=operation,
                idempotency_key=request_key,
                payload_hash=payload_hash,
                client_name=request_client,
                resource_type="product_launch_review",
                resource_id=review.id,
                response_snapshot={
                    "initiative_id": initiative.id,
                    "review_id": review.id,
                    "status": review.status,
                    "readiness_status": readiness["readiness_status"],
                },
            )
        )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        replayed = await replayed_submission()
        if replayed is not None:
            return _launch_review_read(replayed)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="上市评审提交发生并发冲突，请使用新的请求标识重试",
        ) from exc
    await session.refresh(review)
    response.headers["Idempotency-Replayed"] = "false"
    return _launch_review_read(review)


@router.post(
    "/{initiative_id}/launch-reviews/{review_id}/decision",
    response_model=ProductLaunchReviewRead,
)
async def decide_product_launch_review(
    initiative_id: str,
    review_id: str,
    payload: ProductLaunchReviewDecision,
    identity: Identity = Depends(require_approver),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    """处理该接口。

    执行身份、租户、参数和业务状态校验后返回类型化响应。
    """
    initiative = await _get_initiative(session, initiative_id, identity.tenant_id, lock=True)
    review = await session.scalar(
        select(ProductLaunchReview)
        .where(
            ProductLaunchReview.id == review_id,
            ProductLaunchReview.tenant_id == identity.tenant_id,
            ProductLaunchReview.initiative_id == initiative.id,
        )
        .with_for_update()
    )
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="launch review not found")
    if review.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="上市准备评审已处理")
    decision_note = payload.decision_note.strip()
    if payload.action != "approved" and not decision_note:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="退回修订或驳回必须填写处理意见",
        )
    if payload.action == "approved":
        readiness = await _build_product_launch_readiness(
            session,
            initiative,
            ignored_milestone_ids={"launch_review"},
        )
        if readiness["readiness_status"] == "blocked":
            blockers = "；".join(str(item) for item in readiness["blockers"])
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"当前数据已不满足上市评审：{blockers}",
            )
        _update_launch_review_milestone(
            initiative,
            status_value="completed",
            actor_id=identity.user_id,
            note=decision_note or "上市准备评审通过",
        )
        initiative.status = "launch_ready" if _all_milestones_completed(initiative) else "in_progress"
    elif payload.action == "revision_required":
        _update_launch_review_milestone(
            initiative,
            status_value="in_progress",
            actor_id=identity.user_id,
            note=decision_note,
        )
        initiative.status = "in_progress"
    else:
        _update_launch_review_milestone(
            initiative,
            status_value="blocked",
            actor_id=identity.user_id,
            note=decision_note,
        )
        initiative.status = "in_progress"
    now = datetime.now(UTC)
    review.status = payload.action
    review.decision_note = decision_note or None
    review.decided_by = identity.user_id
    review.decided_at = now
    record_audit_event(
        session,
        action="product_initiative.launch_review_decided",
        entity_type="product_initiative",
        entity_id=initiative.id,
        project_id=initiative.project_id,
        tenant_id=identity.tenant_id,
        actor_id=identity.user_id,
        detail={
            "review_id": review.id,
            "action": payload.action,
            "decision_note": decision_note,
            "initiative_status": initiative.status,
        },
    )
    await session.commit()
    await session.refresh(review)
    return _launch_review_read(review)


@router.get("/{initiative_id}/pilot-sales", response_model=list[PilotSaleRead])
async def list_pilot_sales(
    initiative_id: str,
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, object]]:
    """处理`GET /{initiative_id}/pilot-sales`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    initiative = await _get_initiative(session, initiative_id, identity.tenant_id)
    result = await session.scalars(
        select(PilotSaleRecord)
        .where(
            PilotSaleRecord.initiative_id == initiative.id,
            PilotSaleRecord.tenant_id == identity.tenant_id,
        )
        .order_by(PilotSaleRecord.period_end.desc(), PilotSaleRecord.created_at.desc())
    )
    return [_pilot_sale_read(record) for record in result]


@router.get("/{initiative_id}/pilot-sales/page", response_model=PilotSalePage)
async def page_pilot_sales(
    response: Response,
    initiative_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=5, ge=1, le=100),
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    """处理该接口。

    执行身份、租户、参数和业务状态校验后返回类型化响应。
    """
    initiative = await _get_initiative(session, initiative_id, identity.tenant_id)
    conditions = [
        PilotSaleRecord.initiative_id == initiative.id,
        PilotSaleRecord.tenant_id == identity.tenant_id,
    ]
    total = int(
        await session.scalar(select(func.count(PilotSaleRecord.id)).where(*conditions)) or 0
    )
    records = await session.scalars(
        select(PilotSaleRecord)
        .where(*conditions)
        .order_by(PilotSaleRecord.period_end.desc(), PilotSaleRecord.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    response.headers["X-Total-Count"] = str(total)
    return {
        "items": [_pilot_sale_read(record) for record in records],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post(
    "/{initiative_id}/pilot-sales",
    response_model=PilotSaleRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_pilot_sale(
    initiative_id: str,
    payload: PilotSaleCreate,
    identity: Identity = Depends(require_planner),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    """处理`POST /{initiative_id}/pilot-sales`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    initiative = await _get_initiative(session, initiative_id, identity.tenant_id)
    if initiative.status == "cancelled":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已取消立项不能录入试销数据")
    duplicate_record = await session.scalar(
        select(PilotSaleRecord.id).where(
            PilotSaleRecord.tenant_id == identity.tenant_id,
            PilotSaleRecord.initiative_id == initiative.id,
            PilotSaleRecord.period_start == payload.period_start,
            PilotSaleRecord.period_end == payload.period_end,
            PilotSaleRecord.channel == payload.channel,
        )
    )
    if duplicate_record is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="同一试销周期和渠道已有数据，请使用修订功能",
        )
    record = PilotSaleRecord(
        id=new_id("pilot"),
        tenant_id=identity.tenant_id,
        initiative_id=initiative.id,
        period_start=payload.period_start,
        period_end=payload.period_end,
        channel=payload.channel.strip(),
        visitors=payload.visitors,
        orders=payload.orders,
        units_sold=payload.units_sold,
        revenue=payload.revenue,
        product_cost=payload.product_cost,
        marketing_spend=payload.marketing_spend,
        refunds_amount=payload.refunds_amount,
        return_count=payload.return_count,
        rating=payload.rating,
        notes=(payload.notes or "").strip() or None,
        created_by=identity.user_id,
    )
    session.add(record)
    if initiative.status not in {"launched", "paused", "cancelled"}:
        milestones = [dict(item) for item in initiative.milestones if isinstance(item, dict)]
        pilot_index = next(
            (index for index, item in enumerate(milestones) if item.get("id") == "pilot_sale"),
            None,
        )
        if pilot_index is not None and milestones[pilot_index].get("status") == "pending":
            milestones[pilot_index]["status"] = "in_progress"
            milestones[pilot_index]["updated_by"] = identity.user_id
            milestones[pilot_index]["updated_at"] = datetime.now(UTC).isoformat()
            initiative.milestones = milestones
    record_audit_event(
        session,
        action="product_initiative.pilot_sale_recorded",
        entity_type="product_initiative",
        entity_id=initiative.id,
        project_id=initiative.project_id,
        tenant_id=identity.tenant_id,
        actor_id=identity.user_id,
        detail={
            "record_id": record.id,
            "channel": record.channel,
            "period_start": record.period_start.isoformat(),
            "period_end": record.period_end.isoformat(),
            "orders": record.orders,
            "revenue": record.revenue,
        },
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="同一试销周期和渠道已有数据，请使用修订功能",
        ) from exc
    await session.refresh(record)
    return _pilot_sale_read(record)


@router.patch(
    "/{initiative_id}/pilot-sales/{record_id}",
    response_model=PilotSaleRead,
)
async def update_pilot_sale(
    initiative_id: str,
    record_id: str,
    payload: PilotSaleUpdate,
    identity: Identity = Depends(require_planner),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    """处理该接口。

    执行身份、租户、参数和业务状态校验后返回类型化响应。
    """
    initiative = await _get_initiative(session, initiative_id, identity.tenant_id)
    if initiative.status == "cancelled":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已取消立项不能修改试销数据")
    record = await session.scalar(
        select(PilotSaleRecord).where(
            PilotSaleRecord.id == record_id,
            PilotSaleRecord.initiative_id == initiative.id,
            PilotSaleRecord.tenant_id == identity.tenant_id,
        )
    )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="pilot sale record not found")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="至少提供一项需要修改的试销数据",
        )
    current_values = {
        field_name: getattr(record, field_name)
        for field_name in (
            "period_start",
            "period_end",
            "channel",
            "visitors",
            "orders",
            "units_sold",
            "revenue",
            "product_cost",
            "marketing_spend",
            "refunds_amount",
            "return_count",
            "rating",
            "notes",
        )
    }
    current_values.update(changes)
    try:
        validated = PilotSaleCreate(**current_values)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.errors()) from exc
    before = _pilot_sale_snapshot(record)
    normalized = validated.model_dump()
    duplicate_record = await session.scalar(
        select(PilotSaleRecord.id).where(
            PilotSaleRecord.tenant_id == identity.tenant_id,
            PilotSaleRecord.initiative_id == initiative.id,
            PilotSaleRecord.period_start == normalized["period_start"],
            PilotSaleRecord.period_end == normalized["period_end"],
            PilotSaleRecord.channel == normalized["channel"],
            PilotSaleRecord.id != record.id,
        )
    )
    if duplicate_record is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="同一试销周期和渠道已有其他数据，请调整周期、渠道或修订已有记录",
        )
    for field_name in changes:
        value = normalized[field_name]
        if field_name == "channel":
            value = str(value).strip()
        elif field_name == "notes":
            value = str(value or "").strip() or None
        setattr(record, field_name, value)
    after = _pilot_sale_snapshot(record)
    record_audit_event(
        session,
        action="product_initiative.pilot_sale_updated",
        entity_type="product_initiative",
        entity_id=initiative.id,
        project_id=initiative.project_id,
        tenant_id=identity.tenant_id,
        actor_id=identity.user_id,
        detail={
            "record_id": record.id,
            "changed_fields": sorted(changes),
            "before": before,
            "after": after,
        },
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="同一试销周期和渠道已有其他数据，请调整周期、渠道或修订已有记录",
        ) from exc
    await session.refresh(record)
    return _pilot_sale_read(record)


@router.get("/{initiative_id}/pilot-sales-summary", response_model=PilotSaleSummary)
async def get_pilot_sales_summary(
    initiative_id: str,
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> PilotSaleSummary:
    """处理该接口。

    执行身份、租户、参数和业务状态校验后返回类型化响应。
    """
    initiative = await _get_initiative(session, initiative_id, identity.tenant_id)
    return PilotSaleSummary.model_validate(
        await _build_pilot_sales_summary(session, initiative)
    )


@router.get("/{initiative_id}/launch-readiness", response_model=ProductLaunchReadiness)
async def get_product_launch_readiness(
    initiative_id: str,
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> ProductLaunchReadiness:
    """处理该接口。

    执行身份、租户、参数和业务状态校验后返回类型化响应。
    """
    initiative = await _get_initiative(session, initiative_id, identity.tenant_id)
    return ProductLaunchReadiness.model_validate(
        await _build_product_launch_readiness(session, initiative)
    )


@router.get("/{initiative_id}/pilot-sales-trend", response_model=PilotSaleTrend)
async def get_pilot_sales_trend(
    initiative_id: str,
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    """处理该接口。

    执行身份、租户、参数和业务状态校验后返回类型化响应。
    """
    initiative = await _get_initiative(session, initiative_id, identity.tenant_id)
    conditions = [
        PilotSaleRecord.initiative_id == initiative.id,
        PilotSaleRecord.tenant_id == identity.tenant_id,
    ]
    period_total = int(
        await session.scalar(
            select(func.count())
            .select_from(
                select(PilotSaleRecord.period_start, PilotSaleRecord.period_end)
                .where(*conditions)
                .group_by(PilotSaleRecord.period_start, PilotSaleRecord.period_end)
                .subquery()
            )
        )
        or 0
    )
    channel_total = int(
        await session.scalar(
            select(func.count(func.distinct(PilotSaleRecord.channel))).where(*conditions)
        )
        or 0
    )
    period_rows = (
        await session.execute(
            select(
                PilotSaleRecord.period_start,
                PilotSaleRecord.period_end,
                *_pilot_sale_aggregate_columns(),
            )
            .where(*conditions)
            .group_by(PilotSaleRecord.period_start, PilotSaleRecord.period_end)
            .order_by(PilotSaleRecord.period_end.desc(), PilotSaleRecord.period_start.desc())
            .limit(24)
        )
    ).mappings().all()
    periods = [
        _pilot_sale_trend_point_from_row(
            row,
            label=f"{row['period_start'].isoformat()} 至 {row['period_end'].isoformat()}",
            period_start=row["period_start"],
            period_end=row["period_end"],
            channel="全部渠道",
        )
        for row in reversed(period_rows)
    ]
    channel_rows = (
        await session.execute(
            select(
                PilotSaleRecord.channel,
                func.min(PilotSaleRecord.period_start).label("period_start"),
                func.max(PilotSaleRecord.period_end).label("period_end"),
                *_pilot_sale_aggregate_columns(),
            )
            .where(*conditions)
            .group_by(PilotSaleRecord.channel)
            .order_by(func.sum(PilotSaleRecord.revenue).desc(), PilotSaleRecord.channel.asc())
            .limit(20)
        )
    ).mappings().all()
    channels = [
        _pilot_sale_trend_point_from_row(
            row,
            label=str(row["channel"]),
            period_start=row["period_start"],
            period_end=row["period_end"],
            channel=str(row["channel"]),
        )
        for row in channel_rows
    ]
    return {
        "periods": periods,
        "channels": channels,
        "period_total": period_total,
        "channel_total": channel_total,
    }


@router.get("/{initiative_id}/timeline/page", response_model=AuditEventPage)
async def page_product_initiative_timeline(
    response: Response,
    initiative_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=8, ge=1, le=100),
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    """处理`GET /{initiative_id}/timeline/page`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    initiative = await _get_initiative(session, initiative_id, identity.tenant_id)
    conditions = [
        AuditEvent.tenant_id == identity.tenant_id,
        AuditEvent.entity_type == "product_initiative",
        AuditEvent.entity_id == initiative.id,
    ]
    total = int(await session.scalar(select(func.count(AuditEvent.id)).where(*conditions)) or 0)
    events = await session.scalars(
        select(AuditEvent)
        .where(*conditions)
        .order_by(AuditEvent.sequence_no.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    response.headers["X-Total-Count"] = str(total)
    return {
        "items": list(events),
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{initiative_id}/timeline", response_model=list[AuditEventRead])
async def get_product_initiative_timeline(
    initiative_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> list[AuditEvent]:
    """处理`GET /{initiative_id}/timeline`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    initiative = await _get_initiative(session, initiative_id, identity.tenant_id)
    result = await session.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.tenant_id == identity.tenant_id,
            AuditEvent.entity_type == "product_initiative",
            AuditEvent.entity_id == initiative.id,
        )
        .order_by(AuditEvent.sequence_no.desc())
        .limit(limit)
    )
    return list(result)
