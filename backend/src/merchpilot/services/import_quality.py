"""文件职责：汇总导入质量问题并判定警告、阻断和索引可用状态。"""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any

import pandas as pd

from merchpilot.infrastructure.models import DataImportJob, EvidenceRecord


def _excel_safe(value: object) -> object:
    """内部辅助函数`_excel_safe`；拆分主流程并集中处理当前模块的边界条件。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return f"'{value}" if value.lstrip().startswith(("=", "+", "-", "@")) else value
    if isinstance(value, (bool, int, float)):
        return value
    return _excel_safe(json.dumps(value, ensure_ascii=False, default=str))


def _normalized_row(record: EvidenceRecord) -> dict[str, Any]:
    """内部辅助函数`_normalized_row`；拆分主流程并集中处理当前模块的边界条件。"""
    value = (record.metadata_json or {}).get("normalized_row")
    return value if isinstance(value, dict) else {}


def _quality_issue_text(record: EvidenceRecord) -> str:
    """内部辅助函数`_quality_issue_text`；拆分主流程并集中处理当前模块的边界条件。"""
    value = (record.metadata_json or {}).get("quality_issues")
    if not isinstance(value, list):
        return ""
    messages = [str(item.get("message")) for item in value if isinstance(item, dict) and item.get("message")]
    return "；".join(messages)


def build_import_quality_report_bytes(
    job: DataImportJob,
    records: list[EvidenceRecord],
) -> bytes:
    """实现`build_import_quality_report_bytes`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    summary_frame = pd.DataFrame(
        [
            {"指标": "导入批次", "值": _excel_safe(job.id)},
            {"指标": "文件名", "值": _excel_safe(job.filename)},
            {"指标": "总记录", "值": job.total_rows},
            {"指标": "可用记录", "值": job.valid_rows},
            {"指标": "阻断记录", "值": job.invalid_rows},
        ]
    )
    detail_rows: list[dict[str, object]] = []
    for record in records:
        normalized = _normalized_row(record)
        detail_rows.append(
            {
                "Excel行号": record.source_row,
                "来源ID": _excel_safe(record.source_id),
                "数据类型": _excel_safe(normalized.get("data_type")),
                "品类": _excel_safe(normalized.get("category")),
                "目标市场": _excel_safe(normalized.get("target_market")),
                "质量状态": record.quality_status,
                "索引状态": record.index_status,
                "质量问题": _excel_safe(_quality_issue_text(record)),
                "内容": _excel_safe(record.content),
                "数据来源": _excel_safe(normalized.get("data_source")),
                "来源URL": _excel_safe(normalized.get("source_url")),
                "观察日期": record.observed_at.isoformat() if record.observed_at else "",
            }
        )
    detail_frame = pd.DataFrame(
        detail_rows,
        columns=[
            "Excel行号",
            "来源ID",
            "数据类型",
            "品类",
            "目标市场",
            "质量状态",
            "索引状态",
            "质量问题",
            "内容",
            "数据来源",
            "来源URL",
            "观察日期",
        ],
    )

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary_frame.to_excel(writer, sheet_name="质量汇总", index=False)
        detail_frame.to_excel(writer, sheet_name="问题明细", index=False)
        summary_sheet = writer.book["质量汇总"]
        summary_sheet.freeze_panes = "A2"
        summary_sheet.column_dimensions["A"].width = 18
        summary_sheet.column_dimensions["B"].width = 48
        detail_sheet = writer.book["问题明细"]
        detail_sheet.freeze_panes = "A2"
        widths = (12, 24, 14, 18, 16, 14, 16, 42, 60, 20, 36, 24)
        for index, width in enumerate(widths, start=1):
            detail_sheet.column_dimensions[detail_sheet.cell(1, index).column_letter].width = width
        detail_sheet.auto_filter.ref = detail_sheet.dimensions
    return output.getvalue()
