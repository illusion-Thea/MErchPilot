"""文件职责：解析 Excel/CSV，归一化字段并生成证据草稿和质量问题。"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import pandas as pd

from merchpilot.core.ids import new_id
from merchpilot.domain.enums import EvidenceQualityStatus
from merchpilot.services.data_collection_template import (
    COLLECTION_FIELDS,
    DATA_COLLECTION_SCHEMA_VERSION,
    DATA_QUALITY_VALUES,
    DATA_TYPE_VALUES,
    REQUIRED_COLLECTION_KEYS,
)

COLUMN_ALIASES = {
    "id": "source_id",
    "编号": "source_id",
    "编码": "source_id",
    "来源id": "source_id",
    "来源编号": "source_id",
    "sourceid": "source_id",
    "商品id": "source_id",
    "商品编号": "source_id",
    "productid": "source_id",
    "评论id": "source_id",
    "数据类型": "data_type",
    "内容": "content",
    "文本": "content",
    "正文": "content",
    "评论": "content",
    "评论内容": "content",
    "问题": "content",
    "反馈": "content",
    "text": "content",
    "review": "content",
    "comment": "content",
    "商品": "product_name",
    "商品名称": "product_name",
    "产品名称": "product_name",
    "productname": "product_name",
    "品牌": "brand",
    "品类": "category",
    "商品品类": "category",
    "类目": "category",
    "category": "category",
    "市场": "target_market",
    "目标市场": "target_market",
    "国家": "target_market",
    "市场地区": "target_market",
    "market": "target_market",
    "用户": "target_user",
    "目标用户": "target_user",
    "客群": "target_user",
    "供应商": "supplier",
    "供应商名称": "supplier",
    "supplier": "supplier",
    "平台渠道": "channel",
    "记录标题": "title",
    "核心卖点": "selling_points",
    "痛点标签": "pain_points",
    "需求标签": "demand_tags",
    "价格": "price",
    "售价": "price",
    "销售价": "price",
    "price": "price",
    "成本": "cost",
    "成本价": "cost",
    "采购成本": "cost",
    "cost": "cost",
    "物流成本": "logistics_cost",
    "销量": "sales",
    "销售量": "sales",
    "sales": "sales",
    "库存": "inventory",
    "库存量": "inventory",
    "inventory": "inventory",
    "moq": "moq",
    "交期天数": "lead_time_days",
    "评分": "rating",
    "指标值": "metric_value",
    "指标单位": "metric_unit",
    "同比": "yoy_rate",
    "环比": "mom_rate",
    "平台费率": "platform_rate",
    "税费率": "tax_rate",
    "营销费率": "marketing_rate",
    "固定投入": "fixed_investment",
    "预计销量": "forecast_sales",
    "时间": "observed_at",
    "日期": "observed_at",
    "时间戳": "observed_at",
    "发生时间": "observed_at",
    "observedat": "observed_at",
    "数据来源": "data_source",
    "来源url": "source_url",
    "sourceurl": "source_url",
    "数据质量": "data_quality",
    "采集人": "collector",
    "备注": "notes",
}

PASSIVE_ROW_KEYS = frozenset({"collector", "notes"})
NUMERIC_FIELD_KEYS = frozenset(
    {
        "price",
        "cost",
        "logistics_cost",
        "sales",
        "inventory",
        "moq",
        "lead_time_days",
        "rating",
        "metric_value",
        "yoy_rate",
        "mom_rate",
        "platform_rate",
        "tax_rate",
        "marketing_rate",
        "fixed_investment",
        "forecast_sales",
    }
)
RATE_FIELD_KEYS = frozenset(
    {"yoy_rate", "mom_rate", "platform_rate", "tax_rate", "marketing_rate"}
)
FEE_RATE_FIELD_KEYS = frozenset({"platform_rate", "tax_rate", "marketing_rate"})
INTEGER_FIELD_KEYS = frozenset(
    {"sales", "inventory", "moq", "lead_time_days", "fixed_investment", "forecast_sales"}
)


@dataclass(frozen=True, slots=True)
class EvidenceDraft:
    """`EvidenceDraft` 封装可复用业务规则，避免接口层重复实现相同判断。"""
    id: str
    source_id: str
    source_name: str
    source_row: int
    content: str
    metadata: dict[str, Any]
    content_hash: str
    quality_status: str
    observed_at: datetime | None


def normalize_column_name(value: object) -> str:
    """实现`normalize_column_name`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    raw = str(value).strip().lower()
    compact = re.sub(r"[\s_\-（）()]+", "", raw)
    if compact in COLUMN_ALIASES:
        return COLUMN_ALIASES[compact]
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", "_", raw).strip("_")
    return COLUMN_ALIASES.get(normalized, normalized or "unnamed")


def normalize_dataframe(frame: pd.DataFrame) -> pd.DataFrame:
    """实现`normalize_dataframe`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    renamed: dict[object, str] = {}
    used: set[str] = set()
    for column in frame.columns:
        normalized = normalize_column_name(column)
        candidate = normalized
        suffix = 2
        while candidate in used:
            candidate = f"{normalized}_{suffix}"
            suffix += 1
        renamed[column] = candidate
        used.add(candidate)
    return frame.rename(columns=renamed)


def read_tabular_content(content: bytes, filename: str) -> pd.DataFrame:
    """实现`read_tabular_content`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    suffix = Path(filename).suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        return normalize_dataframe(pd.read_excel(BytesIO(content), dtype=object))
    if suffix == ".csv":
        try:
            frame = pd.read_csv(BytesIO(content), dtype=object, encoding="utf-8-sig")
        except UnicodeDecodeError:
            frame = pd.read_csv(BytesIO(content), dtype=object, encoding="gb18030")
        return normalize_dataframe(frame)
    raise ValueError(f"unsupported tabular file type: {suffix}")


def read_tabular_file(path: Path) -> pd.DataFrame:
    """实现`read_tabular_file`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    return read_tabular_content(path.read_bytes(), path.name)


def _safe_value(value: object) -> Any:
    """内部辅助函数`_safe_value`；拆分主流程并集中处理当前模块的边界条件。"""
    if value is None or bool(pd.isna(value)):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def _has_business_data(values: dict[str, Any]) -> bool:
    """内部辅助函数`_has_business_data`；拆分主流程并集中处理当前模块的边界条件。"""
    return any(value is not None for key, value in values.items() if key not in PASSIVE_ROW_KEYS)


def _normalize_numeric_value(key: str, value: Any) -> tuple[Any, str | None]:
    """内部辅助函数`_normalize_numeric_value`；拆分主流程并集中处理当前模块的边界条件。"""
    if key not in NUMERIC_FIELD_KEYS or value is None or isinstance(value, bool):
        return value, None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return value, None
        return value, None

    raw = str(value).strip()
    compact = raw.replace(",", "").replace("，", "").replace(" ", "")
    matches = re.findall(r"[-+]?\d+(?:\.\d+)?", compact)
    if len(matches) != 1:
        return value, None

    number = float(matches[0])
    lowered = compact.lower()
    if key in RATE_FIELD_KEYS and ("%" in compact or "pct" in lowered or "百分点" in compact):
        number /= 100
    elif "亿" in compact:
        number *= 100_000_000
    elif "万" in compact:
        number *= 10_000
    elif "千" in compact:
        number *= 1_000

    normalized: int | float
    if key in INTEGER_FIELD_KEYS and number.is_integer():
        normalized = int(number)
    else:
        normalized = number
    return normalized, raw


def _normalize_numeric_values(values: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """内部辅助函数`_normalize_numeric_values`；拆分主流程并集中处理当前模块的边界条件。"""
    normalized = dict(values)
    raw_numeric_values: dict[str, str] = {}
    for key, value in values.items():
        normalized_value, raw_value = _normalize_numeric_value(key, value)
        normalized[key] = normalized_value
        if raw_value is not None:
            raw_numeric_values[key] = raw_value
    return normalized, raw_numeric_values


def _parse_datetime(value: object) -> datetime | None:
    """内部辅助函数`_parse_datetime`；拆分主流程并集中处理当前模块的边界条件。"""
    if value is None:
        return None
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return None
    parsed_datetime = cast(datetime, parsed.to_pydatetime())
    return parsed_datetime.astimezone(UTC)


def _content_from_values(values: dict[str, Any]) -> str:
    """内部辅助函数`_content_from_values`；拆分主流程并集中处理当前模块的边界条件。"""
    if values.get("content"):
        content = str(values["content"]).strip()
        if values.get("data_type") == "用户评论" and len(content) < 30:
            context = [
                ("品类", values.get("category")),
                ("商品", values.get("product_name")),
                ("品牌", values.get("brand")),
                ("渠道", values.get("channel")),
                ("标题", values.get("title")),
            ]
            prefix = "；".join(f"{label}：{value}" for label, value in context if value)
            if prefix:
                return f"{prefix}；评论：{content}"
        return content
    fragments = [
        f"{key}: {value}"
        for key, value in values.items()
        if value is not None and key not in {"source_id", "observed_at"}
    ]
    return "\n".join(fragments).strip()


def _quality_issue(field: str, code: str, message: str, severity: str) -> dict[str, str]:
    """内部辅助函数`_quality_issue`；拆分主流程并集中处理当前模块的边界条件。"""
    return {"field": field, "code": code, "message": message, "severity": severity}


def _collection_quality_issues(values: dict[str, Any], content: str) -> list[dict[str, str]]:
    """内部辅助函数`_collection_quality_issues`；拆分主流程并集中处理当前模块的边界条件。"""
    issues: list[dict[str, str]] = []
    is_collection_schema = "data_type" in values or "data_source" in values
    if not is_collection_schema:
        if not content:
            issues.append(_quality_issue("content", "missing_content", "缺少可用于检索的内容", "error"))
        elif not values.get("source_id"):
            issues.append(
                _quality_issue(
                    "source_id",
                    "generated_source_id",
                    "未填写来源ID，系统已使用行号代替",
                    "warning",
                )
            )
        return issues

    field_labels = {field.key: field.label for field in COLLECTION_FIELDS}
    for key in sorted(REQUIRED_COLLECTION_KEYS):
        if not values.get(key):
            issues.append(
                _quality_issue(
                    key,
                    "missing_required",
                    f"缺少必填字段：{field_labels[key]}",
                    "error",
                )
            )

    data_type = values.get("data_type")
    if data_type and str(data_type) not in DATA_TYPE_VALUES:
        issues.append(_quality_issue("data_type", "invalid_enum", "数据类型不在模板枚举范围内", "error"))
    observed_at = values.get("observed_at")
    if observed_at and _parse_datetime(observed_at) is None:
        issues.append(_quality_issue("observed_at", "invalid_date", "日期无法识别", "error"))
    data_quality = values.get("data_quality")
    if data_quality and str(data_quality) not in DATA_QUALITY_VALUES:
        issues.append(
            _quality_issue(
                "data_quality",
                "invalid_enum",
                "数据质量不在模板枚举范围内",
                "warning",
            )
        )
    elif str(data_quality or "").startswith("D-"):
        issues.append(
            _quality_issue(
                "data_quality",
                "needs_verification",
                "数据来源仍需人工核验",
                "warning",
            )
        )
    explicit_content = str(values.get("content") or "").strip()
    if explicit_content and len(explicit_content) < 30:
        issues.append(
            _quality_issue(
                "content",
                "content_too_short",
                "内容少于30字，证据上下文可能不足",
                "warning",
            )
        )
    if explicit_content and len(explicit_content) > 1000:
        issues.append(
            _quality_issue(
                "content",
                "content_too_long",
                "内容超过1000字，建议拆分记录",
                "warning",
            )
        )
    for key in NUMERIC_FIELD_KEYS:
        value = values.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            issues.append(
                _quality_issue(
                    key,
                    "invalid_numeric",
                    f"数值字段格式无法识别：{field_labels[key]}",
                    "warning",
                )
            )
    for key in FEE_RATE_FIELD_KEYS:
        value = values.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and not 0 <= value <= 1:
            issues.append(
                _quality_issue(
                    key,
                    "rate_out_of_range",
                    f"费率字段应使用0至1之间的小数：{field_labels[key]}",
                    "warning",
                )
            )
    return issues


def build_evidence_drafts(
    frame: pd.DataFrame,
    *,
    source_name: str,
    import_job_id: str,
) -> list[EvidenceDraft]:
    """实现`build_evidence_drafts`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    drafts: list[EvidenceDraft] = []
    for row_number, (_, row) in enumerate(frame.iterrows(), start=2):
        values = {key: _safe_value(value) for key, value in row.to_dict().items()}
        if not _has_business_data(values):
            continue
        values, raw_numeric_values = _normalize_numeric_values(values)
        source_id = str(values.get("source_id") or f"{source_name}:{row_number}")
        content = _content_from_values(values)
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        evidence_key = (f"{import_job_id}:{row_number}:{source_name}:{source_id}:{content_hash}").encode()
        evidence_id = f"evidence_{hashlib.sha256(evidence_key).hexdigest()[:32]}"
        quality_issues = _collection_quality_issues(values, content)
        if any(item["severity"] == "error" for item in quality_issues):
            quality = EvidenceQualityStatus.BLOCKED.value
        elif quality_issues:
            quality = EvidenceQualityStatus.WARNING.value
        else:
            quality = EvidenceQualityStatus.VERIFIED.value
        metadata = {
            "import_job_id": import_job_id,
            "normalized_row": values,
            "collection_schema_version": (
                DATA_COLLECTION_SCHEMA_VERSION if "data_type" in values or "data_source" in values else None
            ),
            "quality_issues": quality_issues,
            "raw_numeric_values": raw_numeric_values,
            "raw_content": values.get("content") if content != values.get("content") else None,
            "category": values.get("category"),
            "target_market": values.get("target_market"),
            "target_user": values.get("target_user"),
            "supplier": values.get("supplier"),
        }
        drafts.append(
            EvidenceDraft(
                id=evidence_id,
                source_id=source_id,
                source_name=source_name,
                source_row=row_number,
                content=content,
                metadata=metadata,
                content_hash=content_hash,
                quality_status=quality,
                observed_at=_parse_datetime(values.get("observed_at")),
            )
        )
    return drafts


def safe_storage_filename(filename: str) -> str:
    """实现`safe_storage_filename`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    basename = Path(filename).name
    sanitized = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", basename).strip("._")
    return sanitized or new_id("upload")
