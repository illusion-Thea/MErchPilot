"""文件职责：生成数据采集模板和字段说明，指导业务人员准备标准化输入。"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo

DATA_COLLECTION_TEMPLATE_FILENAME = "商品规划Agent_数据采集模板.xlsx"
DATA_COLLECTION_SCHEMA_VERSION = "2026.08"
DATA_TYPE_VALUES = ("自有商品", "竞品", "市场趋势", "用户评论", "供应商", "成本费用")
DATA_QUALITY_VALUES = ("A-官方/内部", "B-平台/机构", "C-公开采集", "D-待核验")


@dataclass(frozen=True, slots=True)
class CollectionField:
    """`CollectionField` 封装可复用业务规则，避免接口层重复实现相同判断。"""
    key: str
    label: str
    required: bool
    value_format: str
    example: object
    description: str


COLLECTION_FIELDS = (
    CollectionField("source_id", "来源ID", True, "文本", "cup-market-001", "稳定且尽量唯一的来源编号"),
    CollectionField("data_type", "数据类型", True, "枚举", "竞品", "记录所属的业务数据主题"),
    CollectionField("category", "品类", True, "文本", "智能保温杯", "统一商品类目"),
    CollectionField("target_market", "目标市场", True, "文本", "中国", "数据适用国家或区域"),
    CollectionField("product_name", "商品名称", False, "文本", "温显商务杯", "商品或方案名称"),
    CollectionField("brand", "品牌", False, "文本", "品牌A", "商品品牌"),
    CollectionField("target_user", "目标用户", False, "文本", "城市通勤白领", "核心用户画像"),
    CollectionField("supplier", "供应商名称", False, "文本", "华东杯业", "供应主体名称"),
    CollectionField("channel", "平台渠道", False, "文本", "天猫", "数据产生的平台或渠道"),
    CollectionField("title", "记录标题", False, "文本", "智能杯趋势摘要", "便于人工识别的标题"),
    CollectionField(
        "content",
        "内容",
        True,
        "长文本",
        "支持温度显示、12小时保温，售价229元。",
        "进入向量检索的核心文本",
    ),
    CollectionField("selling_points", "核心卖点", False, "标签", "温显；防漏", "商品差异化卖点"),
    CollectionField("pain_points", "痛点标签", False, "标签", "漏水；难清洗", "用户负向问题"),
    CollectionField("demand_tags", "需求标签", False, "标签", "轻量；防摔", "用户需求或机会点"),
    CollectionField("price", "售价", False, "数值", 229, "终端销售价格"),
    CollectionField("cost", "成本", False, "数值", 72, "单位采购或制造成本"),
    CollectionField("logistics_cost", "物流成本", False, "数值", 12, "单位物流履约成本"),
    CollectionField("sales", "销量", False, "整数", 5200, "统计周期内销量"),
    CollectionField("inventory", "库存", False, "整数", 3100, "当前可用库存"),
    CollectionField("moq", "MOQ", False, "整数", 1000, "最小起订量"),
    CollectionField("lead_time_days", "交期天数", False, "整数", 30, "下单至交付周期"),
    CollectionField("rating", "评分", False, "数值", 4.7, "平台或内部评分"),
    CollectionField("metric_value", "指标值", False, "数值", 18.5, "趋势报告核心指标"),
    CollectionField("metric_unit", "指标单位", False, "文本", "%", "指标量纲或单位"),
    CollectionField("yoy_rate", "同比", False, "小数", 0.185, "同比增长率"),
    CollectionField("mom_rate", "环比", False, "小数", 0.062, "环比增长率"),
    CollectionField("platform_rate", "平台费率", False, "小数", 0.08, "渠道平台费率"),
    CollectionField("tax_rate", "税费率", False, "小数", 0.06, "税费占销售额比例"),
    CollectionField("marketing_rate", "营销费率", False, "小数", 0.12, "营销费用占比"),
    CollectionField("fixed_investment", "固定投入", False, "数值", 100000, "研发或模具固定投入"),
    CollectionField("forecast_sales", "预计销量", False, "整数", 5000, "财务测算周期预计销量"),
    CollectionField("observed_at", "日期", True, "日期", "2026-08-20", "数据发生或观察日期"),
    CollectionField("data_source", "数据来源", True, "文本", "企业ERP", "来源系统、平台或机构"),
    CollectionField(
        "source_url",
        "来源URL",
        False,
        "文本",
        "https://example.com/item/001",
        "公开数据原始链接",
    ),
    CollectionField("data_quality", "数据质量", False, "枚举", "A-官方/内部", "来源可靠性分级"),
    CollectionField("collector", "采集人", False, "文本", "张三", "采集或整理责任人"),
    CollectionField("notes", "备注", False, "文本", "币种为人民币", "口径、币种和限制条件"),
)

REQUIRED_COLLECTION_KEYS = frozenset(field.key for field in COLLECTION_FIELDS if field.required)

_NAVY_FILL = PatternFill("solid", fgColor="17365D")
_TEAL_FILL = PatternFill("solid", fgColor="147D76")
_GREEN_FILL = PatternFill("solid", fgColor="DFF3E4")
_BLUE_FILL = PatternFill("solid", fgColor="EAF3F8")
_WHITE_FONT = Font(color="FFFFFF", bold=True)
_THIN_BORDER = Border(bottom=Side(style="thin", color="D9E2F3"))


def _style_title(cell: Any) -> None:
    """内部辅助函数`_style_title`；拆分主流程并集中处理当前模块的边界条件。"""
    cell.fill = _NAVY_FILL
    cell.font = Font(color="FFFFFF", bold=True, size=18)
    cell.alignment = Alignment(vertical="center")


def _style_header(sheet: Any, row: int, columns: int) -> None:
    """内部辅助函数`_style_header`；拆分主流程并集中处理当前模块的边界条件。"""
    for column in range(1, columns + 1):
        cell = sheet.cell(row=row, column=column)
        cell.fill = _TEAL_FILL
        cell.font = _WHITE_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _set_collection_widths(sheet: Any) -> None:
    """内部辅助函数`_set_collection_widths`；拆分主流程并集中处理当前模块的边界条件。"""
    widths = (
        20,
        14,
        16,
        16,
        22,
        16,
        20,
        20,
        16,
        24,
        48,
        28,
        24,
        24,
        12,
        12,
        14,
        12,
        12,
        12,
        14,
        12,
        14,
        14,
        12,
        12,
        14,
        12,
        14,
        14,
        14,
        14,
        20,
        34,
        16,
        14,
        30,
    )
    for index, width in enumerate(widths, start=1):
        letter = sheet.cell(row=1, column=index).column_letter
        sheet.column_dimensions[letter].width = width


def _build_collection_sheet(workbook: Workbook) -> None:
    """内部辅助函数`_build_collection_sheet`；拆分主流程并集中处理当前模块的边界条件。"""
    sheet = workbook.active
    sheet.title = "数据采集"
    sheet.sheet_view.showGridLines = False
    sheet.freeze_panes = "A2"
    sheet.append([field.label for field in COLLECTION_FIELDS])
    _style_header(sheet, 1, len(COLLECTION_FIELDS))
    sheet.row_dimensions[1].height = 32
    _set_collection_widths(sheet)

    for column, field in enumerate(COLLECTION_FIELDS, start=1):
        requirement = "P0必填" if field.required else "推荐填写"
        sheet.cell(1, column).comment = Comment(
            f"{requirement}｜{field.description}\n格式：{field.value_format}\n示例：{field.example}",
            "MerchPilot",
        )
    for row in range(2, 202):
        fill = _BLUE_FILL if row % 2 == 0 else PatternFill("solid", fgColor="FFFFFF")
        for column in range(1, len(COLLECTION_FIELDS) + 1):
            cell = sheet.cell(row=row, column=column)
            cell.fill = fill
            cell.border = _THIN_BORDER
            cell.alignment = Alignment(vertical="top", wrap_text=column in {11, 12, 13, 14, 37})

    table = Table(displayName="DataCollectionTable", ref="A1:AK201")
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2",
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=True,
        showColumnStripes=False,
    )
    sheet.add_table(table)

    data_type_validation = DataValidation(
        type="list",
        formula1=f'"{",".join(DATA_TYPE_VALUES)}"',
        allow_blank=False,
    )
    quality_validation = DataValidation(
        type="list",
        formula1=f'"{",".join(DATA_QUALITY_VALUES)}"',
        allow_blank=True,
    )
    sheet.add_data_validation(data_type_validation)
    sheet.add_data_validation(quality_validation)
    data_type_validation.add("B2:B1001")
    quality_validation.add("AI2:AI1001")

    for row in range(2, 1002):
        for column in (15, 16, 17):
            sheet.cell(row, column).number_format = "0.00"
        for column in (25, 26, 27, 28, 29):
            sheet.cell(row, column).number_format = "0.00%"
        sheet.cell(row, 32).number_format = "yyyy-mm-dd"


def _build_overview_sheet(workbook: Workbook) -> None:
    """内部辅助函数`_build_overview_sheet`；拆分主流程并集中处理当前模块的边界条件。"""
    sheet = workbook.create_sheet("采集说明")
    sheet.sheet_view.showGridLines = False
    sheet.merge_cells("A1:G1")
    sheet["A1"] = "商品规划 Agent｜数据采集任务清单"
    _style_title(sheet["A1"])
    sheet.row_dimensions[1].height = 38
    rows = (
        ("数据类型", "优先级", "最低数量", "建议频率", "主要来源", "验收重点", "当前数量"),
        (
            "自有商品",
            "P0",
            20,
            "每周",
            "ERP、商品中心、WMS",
            "价格、成本、销量口径一致",
            "=COUNTIF(数据采集!B:B,A3)",
        ),
        (
            "竞品",
            "P0",
            50,
            "每周",
            "电商平台、品牌官网",
            "同品类同市场并保留链接",
            "=COUNTIF(数据采集!B:B,A4)",
        ),
        (
            "市场趋势",
            "P1",
            24,
            "每月",
            "行业报告、研究机构",
            "指标、单位、周期完整",
            "=COUNTIF(数据采集!B:B,A5)",
        ),
        (
            "用户评论",
            "P0",
            300,
            "每周",
            "电商评论、客服工单",
            "保留原意并去除敏感信息",
            "=COUNTIF(数据采集!B:B,A6)",
        ),
        ("供应商", "P0", 10, "每月", "SRM、询价单", "MOQ、成本和交期可比较", "=COUNTIF(数据采集!B:B,A7)"),
        (
            "成本费用",
            "P0",
            10,
            "每月",
            "财务、平台和物流规则",
            "币种、费率和周期清晰",
            "=COUNTIF(数据采集!B:B,A8)",
        ),
    )
    for row_values in rows:
        sheet.append(row_values)
    _style_header(sheet, 2, 7)
    for row_index in range(3, 9):
        for column in range(1, 8):
            cell = sheet.cell(row_index, column)
            cell.fill = _GREEN_FILL if row_index % 2 else _BLUE_FILL
            cell.border = _THIN_BORDER
            cell.alignment = Alignment(vertical="center", wrap_text=True)
    sheet["A10"] = "最低可用要求"
    sheet["A10"].font = Font(bold=True, color="17365D", size=14)
    requirements = (
        "每行一条记录，第一行为表头；系统只读取第一个工作表。",
        "每条至少填写：来源ID、数据类型、品类、目标市场、内容、日期、数据来源。",
        "来源ID应稳定且尽量唯一；公开采集数据建议填写来源URL。",
        "金额不带货币符号；费率用小数，例如8%填写0.08。",
        "不要采集手机号、身份证、地址、账号密码等个人敏感信息。",
    )
    for index, requirement in enumerate(requirements, start=1):
        row_index = 10 + index
        sheet.cell(row_index, 1, f"{index}. {requirement}")
        sheet.merge_cells(
            start_row=row_index,
            start_column=1,
            end_row=row_index,
            end_column=7,
        )
    for index, width in enumerate((18, 12, 12, 14, 30, 38, 14), start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width


def _build_dictionary_sheet(workbook: Workbook) -> None:
    """内部辅助函数`_build_dictionary_sheet`；拆分主流程并集中处理当前模块的边界条件。"""
    sheet = workbook.create_sheet("字段字典")
    sheet.sheet_view.showGridLines = False
    sheet.merge_cells("A1:F1")
    sheet["A1"] = f"字段字典｜统一采集表（版本 {DATA_COLLECTION_SCHEMA_VERSION}）"
    _style_title(sheet["A1"])
    sheet.append([])
    sheet.append(["Excel列名", "系统字段", "必填级别", "格式", "示例", "业务含义"])
    _style_header(sheet, 3, 6)
    for field in COLLECTION_FIELDS:
        sheet.append(
            [
                field.label,
                field.key,
                "P0必填" if field.required else "推荐填写",
                field.value_format,
                field.example,
                field.description,
            ]
        )
    for row in range(4, sheet.max_row + 1):
        for column in range(1, 7):
            cell = sheet.cell(row, column)
            cell.fill = _GREEN_FILL if row % 2 == 0 else PatternFill("solid", fgColor="FFFFFF")
            cell.border = _THIN_BORDER
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for index, width in enumerate((18, 22, 14, 14, 28, 42), start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = "A4"


def _example_rows() -> tuple[dict[str, object], ...]:
    """内部辅助函数`_example_rows`；拆分主流程并集中处理当前模块的边界条件。"""
    common = {"category": "智能保温杯", "target_market": "中国"}
    return (
        {
            **common,
            "source_id": "own-001",
            "data_type": "自有商品",
            "product_name": "温显商务杯",
            "content": "温显商务杯支持12小时保温、防漏，售价229元，近30天销量5200件。",
            "price": 229,
            "cost": 72,
            "sales": 5200,
            "observed_at": "2026-08-20",
            "data_source": "企业ERP",
            "data_quality": "A-官方/内部",
        },
        {
            **common,
            "source_id": "comp-001",
            "data_type": "竞品",
            "product_name": "轻量随行杯",
            "brand": "竞品A",
            "content": "竞品主打轻量、防摔和高性价比，零售价149元，评价量超过14万。",
            "price": 149,
            "observed_at": "2026-08-18",
            "data_source": "京东商品页",
            "source_url": "https://example.com/comp-001",
            "data_quality": "C-公开采集",
        },
        {
            **common,
            "source_id": "review-001",
            "data_type": "用户评论",
            "product_name": "温显商务杯",
            "content": "保温效果很好、温度显示方便，但杯盖结构复杂，日常清洗不太方便。",
            "pain_points": "清洗困难",
            "rating": 4,
            "observed_at": "2026-08-19",
            "data_source": "天猫评论",
            "data_quality": "C-公开采集",
        },
        {
            **common,
            "source_id": "supplier-001",
            "data_type": "供应商",
            "supplier": "华东杯业",
            "content": "供应商支持温显杯定制，MOQ为1000件，交期30天，具备食品接触材料认证。",
            "cost": 72,
            "moq": 1000,
            "lead_time_days": 30,
            "observed_at": "2026-08-15",
            "data_source": "SRM询价单",
            "data_quality": "A-官方/内部",
        },
    )


def _build_examples_sheet(workbook: Workbook) -> None:
    """内部辅助函数`_build_examples_sheet`；拆分主流程并集中处理当前模块的边界条件。"""
    sheet = workbook.create_sheet("示例数据")
    sheet.sheet_view.showGridLines = False
    sheet.append([field.label for field in COLLECTION_FIELDS])
    _style_header(sheet, 1, len(COLLECTION_FIELDS))
    for example in _example_rows():
        sheet.append([example.get(field.key) for field in COLLECTION_FIELDS])
    for row in range(2, sheet.max_row + 1):
        for column in range(1, len(COLLECTION_FIELDS) + 1):
            cell = sheet.cell(row, column)
            cell.fill = _BLUE_FILL if row % 2 == 0 else _GREEN_FILL
            cell.border = _THIN_BORDER
            cell.alignment = Alignment(vertical="top", wrap_text=column in {11, 12, 13, 14, 37})
    _set_collection_widths(sheet)
    sheet.freeze_panes = "A2"


def _build_rules_sheet(workbook: Workbook) -> None:
    """内部辅助函数`_build_rules_sheet`；拆分主流程并集中处理当前模块的边界条件。"""
    sheet = workbook.create_sheet("枚举与规则")
    sheet.sheet_view.showGridLines = False
    sheet.merge_cells("A1:F1")
    sheet["A1"] = "枚举值与上传规则"
    _style_title(sheet["A1"])
    sheet.append([])
    sheet.append(["数据类型", "用途", "数据质量", "判断标准", "规则", "说明"])
    _style_header(sheet, 3, 6)
    purposes = (
        "内部商品表现、库存、价格和卖点",
        "竞品价格、销量、品牌和卖点",
        "行业规模、增速、价格带和趋势结论",
        "需求、痛点、场景和真实评价",
        "MOQ、成本、交期、产能、认证和风险",
        "售价、成本、物流、平台、税费和营销参数",
    )
    qualities = (
        "ERP、财务、SRM或官方统计等可追溯数据",
        "主流平台、行业数据库或研究机构数据",
        "公开网页或人工整理，需保留来源URL",
        "来源不完整、口径不明或仅供线索使用",
    )
    rules = (
        ("文件格式", ".xlsx、.xlsm 或 .csv"),
        ("工作表", "数据采集表必须放在第一位"),
        ("表头", "第一行必须是字段名，不使用合并单元格"),
        ("记录粒度", "一行一条商品、评论、供应商、指标或费用记录"),
        ("唯一编号", "来源ID稳定且尽量唯一"),
        ("数值格式", "金额不带货币符号；费率使用小数"),
        ("隐私安全", "不要采集个人敏感信息"),
        ("最低可用", "填写全部P0必填字段"),
    )
    for index in range(len(rules)):
        data_type = DATA_TYPE_VALUES[index] if index < len(DATA_TYPE_VALUES) else None
        quality = DATA_QUALITY_VALUES[index] if index < len(DATA_QUALITY_VALUES) else None
        sheet.append(
            [
                data_type,
                purposes[index] if data_type else None,
                quality,
                qualities[index] if quality else None,
                rules[index][0],
                rules[index][1],
            ]
        )
    for row in range(4, sheet.max_row + 1):
        for column in range(1, 7):
            cell = sheet.cell(row, column)
            cell.border = _THIN_BORDER
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for index, width in enumerate((18, 36, 18, 42, 16, 54), start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width


def build_data_collection_template() -> bytes:
    """实现`build_data_collection_template`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    workbook = Workbook()
    _build_collection_sheet(workbook)
    _build_overview_sheet(workbook)
    _build_dictionary_sheet(workbook)
    _build_examples_sheet(workbook)
    _build_rules_sheet(workbook)
    workbook.calculation.fullCalcOnLoad = True
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
