"""文件职责：解析规划运行引用的证据顺序，并提供可追溯分页视图。"""

from __future__ import annotations

from typing import Any

from merchpilot.infrastructure.models import EvidenceRecord

TOPIC_LABELS = {
    "market": "市场",
    "competitor": "竞品",
    "user_insight": "用户洞察",
}


def _record(value: object) -> dict[str, Any]:
    """内部辅助函数`_record`；拆分主流程并集中处理当前模块的边界条件。"""
    return value if isinstance(value, dict) else {}


def _number(value: object) -> float | None:
    """内部辅助函数`_number`；拆分主流程并集中处理当前模块的边界条件。"""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def extract_planning_evidence_references(
    snapshot: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """实现`extract_planning_evidence_references`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    outputs = _record((snapshot or {}).get("outputs"))
    references: dict[str, dict[str, Any]] = {}
    for topic, topic_label in TOPIC_LABELS.items():
        hits = _record(outputs.get(topic)).get("hits")
        if not isinstance(hits, list):
            continue
        for item in hits:
            hit = _record(item)
            evidence_id = hit.get("id")
            if not isinstance(evidence_id, str) or not evidence_id:
                continue
            reference = references.setdefault(
                evidence_id,
                {
                    "evidence_id": evidence_id,
                    "topics": [],
                    "source_name": None,
                    "content": "",
                    "metadata_json": {},
                    "retrieval_score": None,
                    "vector_score": None,
                    "is_canonical": False,
                    "duplicate_review_ids": [],
                },
            )
            if topic_label not in reference["topics"]:
                reference["topics"].append(topic_label)
            if not reference["source_name"] and isinstance(hit.get("source_name"), str):
                reference["source_name"] = hit["source_name"]
            if not reference["content"] and isinstance(hit.get("content"), str):
                reference["content"] = hit["content"]
            metadata = hit.get("metadata")
            if not reference["metadata_json"] and isinstance(metadata, dict):
                reference["metadata_json"] = metadata
            score = _number(hit.get("score"))
            if score is not None and (
                reference["retrieval_score"] is None or score > reference["retrieval_score"]
            ):
                reference["retrieval_score"] = score
            vector_score = _number(hit.get("vector_score"))
            if vector_score is not None and (
                reference["vector_score"] is None or vector_score > reference["vector_score"]
            ):
                reference["vector_score"] = vector_score
            governance = _record(hit.get("governance"))
            if governance.get("is_canonical") is True:
                reference["is_canonical"] = True
            review_ids = governance.get("duplicate_review_ids")
            if isinstance(review_ids, list):
                reference["duplicate_review_ids"] = sorted(
                    {
                        *reference["duplicate_review_ids"],
                        *(str(review_id) for review_id in review_ids if review_id),
                    }
                )
    return list(references.values())


def resolve_planning_evidence(
    snapshot: dict[str, Any] | None,
    records: list[EvidenceRecord],
) -> list[dict[str, Any]]:
    """实现`resolve_planning_evidence`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    return resolve_planning_evidence_references(
        extract_planning_evidence_references(snapshot),
        records,
    )


def resolve_planning_evidence_references(
    references: list[dict[str, Any]],
    records: list[EvidenceRecord],
) -> list[dict[str, Any]]:
    """实现`resolve_planning_evidence_references`业务规则；根据类型化输入返回可复用、可解释的结果。"""
    records_by_id = {record.id: record for record in records}
    resolved: list[dict[str, Any]] = []
    for reference in references:
        record = records_by_id.get(reference["evidence_id"])
        resolved.append(
            {
                **reference,
                "source_name": record.source_name if record else reference["source_name"],
                "source_row": record.source_row if record else None,
                "source_id": record.source_id if record else None,
                "content": record.content if record else reference["content"],
                "metadata_json": record.metadata_json if record else reference["metadata_json"],
                "quality_status": record.quality_status if record else None,
                "observed_at": record.observed_at if record else None,
                "available": record is not None,
            }
        )
    return resolved
