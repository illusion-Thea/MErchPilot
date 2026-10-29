"""文件职责：验证 validation materials 相关规则、边界与回归行为。"""

from merchpilot.services.validation_materials import (
    add_validation_material,
    build_revision_validation_context,
    find_validation_material,
    remove_validation_material,
    validation_gate_exists,
)


def _snapshot() -> dict[str, object]:
    """辅助构造`snapshot`测试数据或依赖，减少用例中的重复准备代码。"""
    return {
        "outputs": {
            "concept": {
                "candidates": [
                    {
                        "id": "concept-1",
                        "validation_plan": {
                            "gates": [
                                {
                                    "id": "specification",
                                    "status": "pending",
                                    "materials": [],
                                }
                            ]
                        },
                    }
                ]
            }
        }
    }


def test_validation_material_lifecycle_updates_snapshot_copy() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    snapshot = _snapshot()
    material = {
        "id": "material-1",
        "candidate_id": "concept-1",
        "gate_id": "specification",
        "filename": "样品测试.pdf",
        "storage_key": "validation-materials/material-1.pdf",
    }

    assert validation_gate_exists(snapshot, "concept-1", "specification") is True
    updated = add_validation_material(snapshot, "concept-1", "specification", material)
    assert updated is not None
    assert find_validation_material(snapshot, "material-1") is None
    assert find_validation_material(updated, "material-1") == material

    removed = remove_validation_material(updated, "material-1")
    assert removed is not None
    cleaned, removed_material = removed
    assert removed_material == material
    assert find_validation_material(cleaned, "material-1") is None


def test_revision_validation_context_keeps_gate_state_and_materials() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    snapshot = _snapshot()
    candidate = snapshot["outputs"]["concept"]["candidates"][0]
    candidate["name"] = "轻量通勤款"
    candidate["validation_plan"]["gates"][0].update(
        {
            "status": "ready",
            "note": "样品测试通过",
            "materials": [
                {
                    "id": "material-1",
                    "filename": "样品测试.pdf",
                    "storage_key": "validation-materials/material-1.pdf",
                }
            ],
        }
    )

    context = build_revision_validation_context(snapshot)

    assert context["source_run_id"] is None
    assert context["candidates"] == [
        {
            "candidate_id": "concept-1",
            "candidate_name": "轻量通勤款",
            "gates": [
                {
                    "gate_id": "specification",
                    "status": "ready",
                    "note": "样品测试通过",
                    "materials": [
                        {
                            "id": "material-1",
                            "filename": "样品测试.pdf",
                            "storage_key": "validation-materials/material-1.pdf",
                        }
                    ],
                }
            ],
        }
    ]
