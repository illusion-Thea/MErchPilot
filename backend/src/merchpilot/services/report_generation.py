"""文件职责：把规划运行结果渲染为可下载、可追溯的报告文件。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

import pandas as pd

from merchpilot.adapters.storage import get_object_storage_provider
from merchpilot.domain.enums import ReportStatus
from merchpilot.infrastructure.database import async_session_factory
from merchpilot.infrastructure.models import PlanningProject, PlanningReport, PlanningRun
from merchpilot.services.audit import record_audit_event


def _record(value: object) -> dict[str, Any]:
    """内部辅助函数`_record`；拆分主流程并集中处理当前模块的边界条件。"""
    return value if isinstance(value, dict) else {}


def _excel_safe(value: object) -> object:
    """内部辅助函数`_excel_safe`；拆分主流程并集中处理当前模块的边界条件。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return f"'{value}" if value.lstrip().startswith(("=", "+", "-", "@")) else value
    if isinstance(value, (bool, int, float)):
        return value
    return _excel_safe(json.dumps(value, ensure_ascii=False, default=str))


def _percent(value: object) -> str:
    """内部辅助函数`_percent`；拆分主流程并集中处理当前模块的边界条件。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    return f"{value * 100:.2f}%"


def build_planning_report_bytes(project: PlanningProject, run: PlanningRun) -> bytes:
    """把规划快照、证据和业务指标渲染为可下载的结构化报告。"""
    snapshot = run.result_snapshot or {}
    outputs = _record(snapshot.get("outputs"))
    scorecard = _record(outputs.get("scorecard"))
    finance = _record(outputs.get("finance"))
    supplier = _record(outputs.get("supplier"))
    concept = _record(outputs.get("concept"))
    narrative = _record(outputs.get("narrative"))
    selected_candidate = _record(concept.get("selected_candidate"))
    selected_validation = _record(selected_candidate.get("validation_plan"))

    summary_rows = [
        ("项目名称", project.name),
        ("商品品类", project.category),
        ("目标市场", project.target_market),
        ("项目状态", project.status),
        ("运行 ID", run.id),
        ("运行状态", run.status),
        ("候选方案", concept.get("name")),
        ("建议优先验证", concept.get("recommended_candidate_name")),
        ("已选候选方案", selected_candidate.get("name")),
        ("已选方案验证状态", selected_validation.get("status_label") or selected_validation.get("status")),
        ("已选方案验证完成度", selected_validation.get("completion_rate")),
        ("机会分", scorecard.get("score")),
        ("评分状态", scorecard.get("status")),
        ("评分说明", scorecard.get("reason")),
        ("证据数量", scorecard.get("evidence_count")),
        ("计划售价", finance.get("selling_price")),
        ("单位采购成本", finance.get("unit_cost")),
        ("单位贡献毛利", finance.get("contribution_margin_per_unit")),
        ("预计毛利率", _percent(finance.get("margin_rate"))),
        ("目标毛利率", _percent(finance.get("target_margin"))),
        ("盈亏平衡销量", finance.get("break_even_units")),
        ("预计销售额", finance.get("estimated_revenue")),
        ("预计利润", finance.get("estimated_profit")),
        ("供应商", supplier.get("supplier_name")),
        ("MOQ", supplier.get("moq")),
        ("交期（天）", supplier.get("lead_time_days")),
        ("供应风险", supplier.get("risk_level")),
        ("规划建议状态", narrative.get("status")),
        ("规划摘要", narrative.get("summary")),
    ]
    summary_frame = pd.DataFrame(
        [{"指标": name, "值": _excel_safe(value)} for name, value in summary_rows]
    )

    breakdown = _record(scorecard.get("breakdown"))
    breakdown_labels = {
        "evidence": "证据",
        "finance": "财务",
        "supplier": "供应",
        "completeness": "完整度",
    }
    breakdown_frame = pd.DataFrame(
        [
            {
                "维度": breakdown_labels.get(key, key),
                "得分": _record(value).get("score"),
                "满分": _record(value).get("max_score"),
            }
            for key, value in breakdown.items()
        ],
        columns=["维度", "得分", "满分"],
    )

    constraints_frame = pd.DataFrame(
        [
            {"参数": _excel_safe(key), "值": _excel_safe(value)}
            for key, value in sorted(project.constraints.items())
        ],
        columns=["参数", "值"],
    )

    evidence_rows: list[dict[str, object]] = []
    topic_labels = {"market": "市场", "competitor": "竞品", "user_insight": "用户洞察"}
    for topic, topic_label in topic_labels.items():
        hits = _record(outputs.get(topic)).get("hits")
        if not isinstance(hits, list):
            continue
        for item in hits:
            hit = _record(item)
            evidence_rows.append(
                {
                    "类型": topic_label,
                    "证据 ID": _excel_safe(hit.get("id")),
                    "来源": _excel_safe(hit.get("source_name")),
                    "相关度": hit.get("score"),
                    "内容摘要": _excel_safe(hit.get("content")),
                }
            )
    evidence_frame = pd.DataFrame(
        evidence_rows,
        columns=["类型", "证据 ID", "来源", "相关度", "内容摘要"],
    )

    narrative_rows = [
        {"类型": "规划摘要", "内容": _excel_safe(narrative.get("summary"))},
        *[
            {"类型": "建议", "内容": _excel_safe(item)}
            for item in narrative.get("recommendations", [])
            if isinstance(item, str)
        ],
        *[
            {"类型": "风险", "内容": _excel_safe(item)}
            for item in narrative.get("risks", [])
            if isinstance(item, str)
        ],
    ]
    narrative_frame = pd.DataFrame(narrative_rows, columns=["类型", "内容"])

    candidate_rows: list[dict[str, object]] = []
    candidates = concept.get("candidates")
    if isinstance(candidates, list):
        for item in candidates:
            candidate = _record(item)
            price_reference = _record(candidate.get("price_reference"))
            candidate_scorecard = _record(candidate.get("scorecard"))
            financial_scenario = _record(candidate.get("financial_scenario"))
            validation_plan = _record(candidate.get("validation_plan"))
            material_summaries: list[str] = []
            validation_gates = validation_plan.get("gates")
            if isinstance(validation_gates, list):
                for gate_value in validation_gates:
                    gate = _record(gate_value)
                    gate_label = str(gate.get("label") or gate.get("id") or "验证门")
                    materials = gate.get("materials")
                    if not isinstance(materials, list):
                        continue
                    for material_value in materials:
                        material = _record(material_value)
                        filename = str(material.get("filename") or "验证材料")
                        note = str(material.get("note") or "").strip()
                        material_summaries.append(
                            f"{gate_label}: {filename}{f'（{note}）' if note else ''}"
                        )
            candidate_rows.append(
                {
                    "候选 ID": _excel_safe(candidate.get("id")),
                    "选择状态": (
                        "已选"
                        if candidate.get("id") == concept.get("selected_candidate_id")
                        else "候选"
                    ),
                    "方案名称": _excel_safe(candidate.get("name")),
                    "方案评分": candidate_scorecard.get("total_score"),
                    "推荐级别": _excel_safe(candidate.get("recommendation")),
                    "验证状态": _excel_safe(
                        validation_plan.get("status_label") or validation_plan.get("status")
                    ),
                    "验证完成度": validation_plan.get("completion_rate"),
                    "验证下一步": _excel_safe("；".join(
                        item for item in validation_plan.get("next_actions", []) if isinstance(item, str)
                    )),
                    "参考毛利率": _percent(financial_scenario.get("margin_rate")),
                    "预计利润": financial_scenario.get("estimated_profit"),
                    "定位": _excel_safe(candidate.get("positioning")),
                    "目标用户": _excel_safe(candidate.get("target_user")),
                    "证据特征": _excel_safe("；".join(
                        item for item in candidate.get("evidence_features", []) if isinstance(item, str)
                    )),
                    "待解决痛点": _excel_safe("；".join(
                        item for item in candidate.get("pain_points_addressed", []) if isinstance(item, str)
                    )),
                    "功能假设": _excel_safe("；".join(
                        item for item in candidate.get("feature_hypotheses", []) if isinstance(item, str)
                    )),
                    "建议售价": price_reference.get("suggested_price"),
                    "成本参考": candidate.get("unit_cost_reference"),
                    "差异化假设": _excel_safe(candidate.get("differentiation_hypothesis")),
                    "置信度": _excel_safe(candidate.get("confidence")),
                    "风险": _excel_safe("；".join(
                        item for item in candidate.get("risks", []) if isinstance(item, str)
                    )),
                    "证据 ID": _excel_safe("；".join(
                        item for item in candidate.get("evidence_ids", []) if isinstance(item, str)
                    )),
                    "验证材料": _excel_safe("；".join(material_summaries)),
                }
            )
    candidate_frame = pd.DataFrame(
        candidate_rows,
        columns=[
            "候选 ID", "选择状态", "方案名称", "方案评分", "推荐级别", "验证状态", "验证完成度", "验证下一步",
            "参考毛利率", "预计利润",
            "定位", "目标用户",
            "证据特征", "待解决痛点",
            "功能假设", "建议售价", "成本参考", "差异化假设", "置信度", "风险", "证据 ID", "验证材料",
        ],
    )

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frames = {
            "方案摘要": summary_frame,
            "评分拆解": breakdown_frame,
            "约束参数": constraints_frame,
            "候选商品": candidate_frame,
            "规划建议": narrative_frame,
            "证据明细": evidence_frame,
        }
        for sheet_name, frame in frames.items():
            frame.to_excel(writer, sheet_name=sheet_name, index=False)
            worksheet = writer.book[sheet_name]
            worksheet.freeze_panes = "A2"
            for column in worksheet.columns:
                values = [str(cell.value or "") for cell in column]
                width = min(max(max(map(len, values), default=8) + 2, 12), 60)
                worksheet.column_dimensions[column[0].column_letter].width = width
    return buffer.getvalue()


async def generate_planning_report_job(report_id: str) -> dict[str, Any]:
    """实现`generate_planning_report_job`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    storage = get_object_storage_provider()
    storage_key: str | None = None
    async with async_session_factory() as session:
        report = await session.get(PlanningReport, report_id)
        if report is None:
            raise ValueError(f"planning report not found: {report_id}")
        project = await session.get(PlanningProject, report.project_id)
        run = await session.get(PlanningRun, report.run_id)
        if project is None or run is None:
            raise ValueError("planning report source not found")
        report.status = ReportStatus.PROCESSING.value
        report.error_message = None
        record_audit_event(
            session,
            action="report.processing",
            entity_type="planning_report",
            entity_id=report.id,
            project_id=project.id,
            tenant_id=project.tenant_id,
            actor_id="system",
            detail={"run_id": run.id},
        )
        await session.commit()

        try:
            content = build_planning_report_bytes(project, run)
            storage_key = f"reports/{project.id}/{report.id}.xlsx"
            await storage.put_object(
                storage_key,
                content,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            report.storage_key = storage_key
            report.status = ReportStatus.COMPLETED.value
            report.completed_at = datetime.now(UTC)
            record_audit_event(
                session,
                action="report.completed",
                entity_type="planning_report",
                entity_id=report.id,
                project_id=project.id,
                tenant_id=project.tenant_id,
                actor_id="system",
                detail={"run_id": run.id, "storage_key": storage_key},
            )
            await session.commit()
            return {"report_id": report.id, "status": report.status, "storage_key": storage_key}
        except Exception as exc:
            await session.rollback()
            if storage_key is not None:
                await storage.delete_object(storage_key)
            report = await session.get(PlanningReport, report_id)
            project = await session.get(PlanningProject, report.project_id) if report else None
            if report is not None:
                report.status = ReportStatus.FAILED.value
                report.error_message = str(exc)
                record_audit_event(
                    session,
                    action="report.failed",
                    entity_type="planning_report",
                    entity_id=report.id,
                    project_id=report.project_id,
                    tenant_id=project.tenant_id if project is not None else "default",
                    actor_id="system",
                    detail={"error": str(exc)},
                )
                await session.commit()
            raise
