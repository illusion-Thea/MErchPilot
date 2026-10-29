"""文件职责：验证 data collection template 相关规则、边界与回归行为。"""

from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from merchpilot.main import app
from merchpilot.services.data_collection_template import (
    COLLECTION_FIELDS,
    DATA_COLLECTION_SCHEMA_VERSION,
    REQUIRED_COLLECTION_KEYS,
    build_data_collection_template,
)
from merchpilot.services.tabular_import import read_tabular_file


def test_template_places_import_sheet_first_and_contains_schema() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    content = build_data_collection_template()
    workbook = load_workbook(BytesIO(content), read_only=False, data_only=False)

    assert workbook.sheetnames == ["数据采集", "采集说明", "字段字典", "示例数据", "枚举与规则"]
    collection_sheet = workbook["数据采集"]
    headers = [collection_sheet.cell(1, column).value for column in range(1, len(COLLECTION_FIELDS) + 1)]
    assert headers == [field.label for field in COLLECTION_FIELDS]
    assert {field.key for field in COLLECTION_FIELDS}.issuperset(REQUIRED_COLLECTION_KEYS)
    assert len(collection_sheet.data_validations.dataValidation) == 2
    assert "DataCollectionTable" in collection_sheet.tables


def test_template_download_endpoint_returns_xlsx() -> None:
    """验证“template download endpoint returns xlsx”场景，确保业务规则、权限和异常边界保持稳定。"""
    with TestClient(app) as client:
        response = client.get("/api/v1/data-imports/template")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert response.headers["x-collection-schema-version"] == DATA_COLLECTION_SCHEMA_VERSION
    workbook = load_workbook(BytesIO(response.content), read_only=True)
    assert workbook.sheetnames[0] == "数据采集"


def test_generated_template_can_be_read_by_current_importer(tmp_path) -> None:
    """验证“generated template can be read by current importer”场景，确保业务规则、权限和异常边界保持稳定。"""
    path = tmp_path / "collection-template.xlsx"
    path.write_bytes(build_data_collection_template())

    frame = read_tabular_file(path)

    assert frame.empty
    assert list(frame.columns) == [field.key for field in COLLECTION_FIELDS]
