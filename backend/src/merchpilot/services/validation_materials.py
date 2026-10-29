"""文件职责：规范样品、成本、供应商等验证材料的类型与完整性。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from merchpilot.adapters.storage import get_object_storage_provider
from merchpilot.core.ids import new_id


def _record(value: object) -> dict[str, Any]:
    """内部辅助函数`_record`；拆分主流程并集中处理当前模块的边界条件。"""
    return value if isinstance(value, dict) else {}


def _candidate_gates(snapshot: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """内部辅助函数`_candidate_gates`；拆分主流程并集中处理当前模块的边界条件。"""
    outputs = _record(snapshot.get("outputs"))
    concept = _record(outputs.get("concept"))
    candidates = concept.get("candidates")
    if not isinstance(candidates, list):
        return []
    result: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        validation_plan = _record(candidate.get("validation_plan"))
        gates = validation_plan.get("gates")
        if not isinstance(gates, list):
            continue
        result.extend(
            (candidate, gate)
            for gate in gates
            if isinstance(gate, dict)
        )
    return result


def validation_gate_exists(
    snapshot: dict[str, Any],
    candidate_id: str,
    gate_id: str,
) -> bool:
    """实现`validation_gate_exists`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    return any(
        str(candidate.get("id") or "") == candidate_id and str(gate.get("id") or "") == gate_id
        for candidate, gate in _candidate_gates(snapshot)
    )


def add_validation_material(
    snapshot: dict[str, Any],
    candidate_id: str,
    gate_id: str,
    material: dict[str, Any],
) -> dict[str, Any] | None:
    """实现`add_validation_material`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    updated_snapshot = deepcopy(snapshot)
    for candidate, gate in _candidate_gates(updated_snapshot):
        if str(candidate.get("id") or "") != candidate_id or str(gate.get("id") or "") != gate_id:
            continue
        materials = gate.get("materials")
        materials = list(materials) if isinstance(materials, list) else []
        materials.append(dict(material))
        gate["materials"] = materials
        return updated_snapshot
    return None


def find_validation_material(
    snapshot: dict[str, Any],
    material_id: str,
) -> dict[str, Any] | None:
    """实现`find_validation_material`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    for _, gate in _candidate_gates(snapshot):
        materials = gate.get("materials")
        if not isinstance(materials, list):
            continue
        for material in materials:
            if isinstance(material, dict) and str(material.get("id") or "") == material_id:
                return dict(material)
    return None


def remove_validation_material(
    snapshot: dict[str, Any],
    material_id: str,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """实现`remove_validation_material`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    updated_snapshot = deepcopy(snapshot)
    for _, gate in _candidate_gates(updated_snapshot):
        materials = gate.get("materials")
        if not isinstance(materials, list):
            continue
        for index, material in enumerate(materials):
            if not isinstance(material, dict) or str(material.get("id") or "") != material_id:
                continue
            removed = dict(materials.pop(index))
            gate["materials"] = materials
            return updated_snapshot, removed
    return None


def build_revision_validation_context(snapshot: dict[str, Any]) -> dict[str, Any]:
    """实现`build_revision_validation_context`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    context: dict[str, Any] = {"source_run_id": None, "candidates": []}
    candidate_entries: dict[str, dict[str, Any]] = {}
    for candidate, gate in _candidate_gates(snapshot):
        candidate_id = str(candidate.get("id") or "").strip()
        gate_id = str(gate.get("id") or "").strip()
        if not candidate_id or not gate_id:
            continue
        entry = candidate_entries.setdefault(
            candidate_id,
            {
                "candidate_id": candidate_id,
                "candidate_name": candidate.get("name"),
                "gates": [],
            },
        )
        materials = gate.get("materials")
        entry["gates"].append(
            {
                "gate_id": gate_id,
                "status": gate.get("status"),
                "note": gate.get("note") or "",
                "materials": [
                    dict(material)
                    for material in materials
                    if isinstance(material, dict)
                ] if isinstance(materials, list) else [],
            }
        )
    context["candidates"] = list(candidate_entries.values())
    return context


async def clone_revision_validation_materials(
    context: dict[str, Any],
    *,
    project_id: str,
    parent_run_id: str,
    child_run_id: str,
) -> dict[str, Any]:
    """实现`clone_revision_validation_materials`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    cloned_context = deepcopy(context)
    cloned_context["source_run_id"] = parent_run_id
    storage = get_object_storage_provider()
    for candidate_entry in cloned_context.get("candidates", []):
        if not isinstance(candidate_entry, dict):
            continue
        candidate_id = str(candidate_entry.get("candidate_id") or "")
        for gate_entry in candidate_entry.get("gates", []):
            if not isinstance(gate_entry, dict):
                continue
            gate_id = str(gate_entry.get("gate_id") or "")
            cloned_materials: list[dict[str, Any]] = []
            for material_value in gate_entry.get("materials", []):
                if not isinstance(material_value, dict):
                    continue
                material = dict(material_value)
                source_key = material.get("storage_key")
                material_id = new_id("material")
                filename = str(material.get("filename") or "validation-material")
                target_key = (
                    f"validation-materials/{project_id}/{child_run_id}/{candidate_id}/{gate_id}/"
                    f"{material_id}-{filename}"
                )
                source_missing = False
                if isinstance(source_key, str) and source_key:
                    try:
                        content = await storage.get_object(source_key)
                        await storage.put_object(
                            target_key,
                            content,
                            str(material.get("content_type") or "application/octet-stream"),
                        )
                    except (OSError, ValueError):
                        source_missing = True
                else:
                    source_missing = True
                material.update(
                    {
                        "id": material_id,
                        "source_material_id": material.get("id"),
                        "source_run_id": parent_run_id,
                        "storage_key": "" if source_missing else target_key,
                        "download_path": "" if source_missing else (
                            f"/api/v1/planning-projects/{project_id}/runs/{child_run_id}/"
                            f"validation-materials/{material_id}/download"
                        ),
                        "source_missing": source_missing,
                    }
                )
                cloned_materials.append(material)
            gate_entry["materials"] = cloned_materials
    return cloned_context
