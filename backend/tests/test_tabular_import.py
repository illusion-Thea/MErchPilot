"""文件职责：验证 tabular import 相关规则、边界与回归行为。"""

from datetime import UTC, datetime

import pandas as pd

from merchpilot.services.tabular_import import (
    build_evidence_drafts,
    normalize_dataframe,
    safe_storage_filename,
)


def test_normalize_dataframe_and_build_evidence_drafts() -> None:
    """验证“normalize dataframe and build evidence drafts”场景，确保业务规则、权限和异常边界保持稳定。"""
    frame = pd.DataFrame(
        [
            {
                "商品编号": "sku-001",
                "商品名称": "智能水杯",
                "类目": "水杯",
                "目标市场": "中国",
                "销量": 1200,
                "日期": "2026-08-20 10:00:00+08:00",
            },
            {
                "商品编号": None,
                "商品名称": "便携水杯",
                "类目": "水杯",
                "目标市场": "中国",
                "销量": 800,
                "日期": None,
            },
        ]
    )

    drafts = build_evidence_drafts(
        normalize_dataframe(frame),
        source_name="sales.xlsx",
        import_job_id="import_test",
    )

    assert len(drafts) == 2
    assert drafts[0].source_id == "sku-001"
    assert drafts[0].quality_status == "verified"
    assert drafts[0].metadata["category"] == "水杯"
    assert drafts[0].observed_at == datetime(2026, 8, 20, 2, tzinfo=UTC)
    assert drafts[1].quality_status == "warning"
    assert "product_name: 便携水杯" in drafts[1].content


def test_safe_storage_filename_removes_parent_paths() -> None:
    """验证“safe storage filename removes parent paths”场景，确保业务规则、权限和异常边界保持稳定。"""
    assert safe_storage_filename("../../销售 数据.xlsx") == "销售_数据.xlsx"


def test_normalize_dataframe_supports_source_id_and_unknown_chinese_columns() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    frame = normalize_dataframe(
        pd.DataFrame(
            [
                {
                    "来源ID": "external-001",
                    "内容": "通勤保温杯支持温度显示",
                    "品牌定位": "中高端",
                }
            ]
        )
    )

    assert list(frame.columns) == ["source_id", "content", "品牌定位"]
    draft = build_evidence_drafts(
        frame,
        source_name="market.xlsx",
        import_job_id="import_alias_test",
    )[0]
    assert draft.source_id == "external-001"
    assert draft.quality_status == "verified"
    assert draft.metadata["normalized_row"]["品牌定位"] == "中高端"


def test_collection_template_row_requires_minimum_fields() -> None:
    """验证“collection template row requires minimum fields”场景，确保业务规则、权限和异常边界保持稳定。"""
    frame = normalize_dataframe(
        pd.DataFrame(
            [
                {
                    "来源ID": "review-001",
                    "数据类型": "用户评论",
                    "品类": "智能保温杯",
                    "目标市场": "中国",
                    "内容": "杯盖容易积水，清洗不方便。",
                    "日期": "2026-08-20",
                }
            ]
        )
    )

    draft = build_evidence_drafts(
        frame,
        source_name="collection.xlsx",
        import_job_id="import_collection_missing",
    )[0]

    assert draft.quality_status == "blocked"
    assert draft.metadata["collection_schema_version"] == "2026.08"
    issues = draft.metadata["quality_issues"]
    assert any(issue["field"] == "data_source" and issue["severity"] == "error" for issue in issues)
    assert any(issue["code"] == "content_too_short" for issue in issues)


def test_collection_template_row_normalizes_all_core_fields() -> None:
    """验证“collection template row normalizes all core fields”场景，确保业务规则、权限和异常边界保持稳定。"""
    frame = normalize_dataframe(
        pd.DataFrame(
            [
                {
                    "来源ID": "supplier-001",
                    "数据类型": "供应商",
                    "品类": "智能保温杯",
                    "目标市场": "中国",
                    "供应商名称": "华东杯业",
                    "内容": "供应商支持温显杯定制，最小起订量1000件，标准交期30天，并提供食品接触材料认证。",
                    "MOQ": 1000,
                    "交期天数": 30,
                    "日期": "2026-08-20",
                    "数据来源": "SRM询价单",
                    "来源URL": "https://example.com/supplier-001",
                    "数据质量": "A-官方/内部",
                }
            ]
        )
    )

    draft = build_evidence_drafts(
        frame,
        source_name="collection.xlsx",
        import_job_id="import_collection_valid",
    )[0]

    assert draft.quality_status == "verified"
    normalized = draft.metadata["normalized_row"]
    assert normalized["data_type"] == "供应商"
    assert normalized["supplier"] == "华东杯业"
    assert normalized["moq"] == 1000
    assert normalized["lead_time_days"] == 30
    assert normalized["data_source"] == "SRM询价单"
    assert normalized["source_url"] == "https://example.com/supplier-001"


def test_collection_import_skips_rows_without_business_data() -> None:
    """验证“collection import skips rows without business data”场景，确保业务规则、权限和异常边界保持稳定。"""
    frame = normalize_dataframe(
        pd.DataFrame(
            [
                {"采集人": "系统采集"},
                {
                    "来源ID": "review-002",
                    "数据类型": "用户评论",
                    "品类": "智能保温杯",
                    "目标市场": "中国",
                    "内容": "杯盖不容易清洗。",
                    "日期": "2026-08-20",
                    "数据来源": "电商评论",
                    "采集人": "系统采集",
                },
            ]
        )
    )

    drafts = build_evidence_drafts(
        frame,
        source_name="collection.xlsx",
        import_job_id="import_skip_empty",
    )

    assert len(drafts) == 1
    assert drafts[0].source_row == 3
    assert drafts[0].source_id == "review-002"


def test_collection_import_normalizes_unitized_numbers_and_preserves_raw_values() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    frame = normalize_dataframe(
        pd.DataFrame(
            [
                {
                    "来源ID": "cost-001",
                    "数据类型": "成本费用",
                    "品类": "智能保温杯",
                    "目标市场": "中国",
                    "内容": "智能保温杯成本测算，包含售价、销量、费率、固定投入和预计销量。",
                    "销量": "月销5.2万+",
                    "平台费率": "5%",
                    "同比": "+3.2pct",
                    "固定投入": "30万",
                    "预计销量": "3000台/月",
                    "日期": "2026-08-20",
                    "数据来源": "内部财务测算",
                }
            ]
        )
    )

    draft = build_evidence_drafts(
        frame,
        source_name="collection.xlsx",
        import_job_id="import_numeric_normalization",
    )[0]

    normalized = draft.metadata["normalized_row"]
    assert normalized["sales"] == 52_000
    assert normalized["platform_rate"] == 0.05
    assert normalized["yoy_rate"] == 0.032
    assert normalized["fixed_investment"] == 300_000
    assert normalized["forecast_sales"] == 3_000
    assert draft.metadata["raw_numeric_values"] == {
        "sales": "月销5.2万+",
        "yoy_rate": "+3.2pct",
        "platform_rate": "5%",
        "fixed_investment": "30万",
        "forecast_sales": "3000台/月",
    }


def test_short_review_content_is_enriched_for_retrieval() -> None:
    """验证“short review content is enriched for retrieval”场景，确保业务规则、权限和异常边界保持稳定。"""
    frame = normalize_dataframe(
        pd.DataFrame(
            [
                {
                    "来源ID": "review-003",
                    "数据类型": "用户评论",
                    "品类": "智能保温杯",
                    "目标市场": "中国",
                    "商品名称": "通勤温显杯",
                    "平台渠道": "京东",
                    "内容": "杯盖不容易清洗。",
                    "日期": "2026-08-20",
                    "数据来源": "京东评论",
                }
            ]
        )
    )

    draft = build_evidence_drafts(
        frame,
        source_name="collection.xlsx",
        import_job_id="import_review_context",
    )[0]

    assert draft.content == "品类：智能保温杯；商品：通勤温显杯；渠道：京东；评论：杯盖不容易清洗。"
    assert draft.metadata["raw_content"] == "杯盖不容易清洗。"
    assert any(issue["code"] == "content_too_short" for issue in draft.metadata["quality_issues"])
