"""文件职责：验证研究覆盖度、补充检索和证据冲突治理规则。"""

from merchpilot.services.research_governance import (
    assess_research_result,
    build_research_synthesis,
    detect_evidence_conflicts,
    merge_research_results,
)


def test_research_assessment_requests_follow_up_for_incomplete_fields() -> None:
    """关键字段覆盖不足时，应明确要求补充研究。"""
    result = assess_research_result(
        "competitor",
        {
            "status": "ready",
            "hits": [
                {
                    "id": "competitor-1",
                    "metadata": {
                        "normalized_row": {
                            "product_name": "A款",
                            "brand": "A品牌",
                            "price": 199,
                        }
                    },
                }
            ],
        },
    )

    assert result["status"] == "partial"
    assert result["needs_follow_up"] is True
    assert result["evidence_ids"] == ["competitor-1"]
    assert "卖点" in result["follow_up_intent"]


def test_research_governance_detects_metric_conflicts() -> None:
    """相同商品的关键指标差异过大时，应形成可解释冲突记录。"""
    conflicts = detect_evidence_conflicts(
        {
            "competitor": {
                "hits": [
                    {
                        "id": "evidence-a",
                        "metadata": {"normalized_row": {"product_name": "A款", "price": 100}},
                    },
                    {
                        "id": "evidence-b",
                        "metadata": {"normalized_row": {"product_name": "A款", "price": 180}},
                    },
                ]
            }
        }
    )

    assert len(conflicts) == 1
    assert conflicts[0]["field"] == "price"
    assert conflicts[0]["evidence_ids"] == ["evidence-a", "evidence-b"]


def test_research_merge_keeps_highest_scored_duplicate() -> None:
    """补充检索和主检索出现重复证据时，应保留评分更高的一条。"""
    merged = merge_research_results(
        {
            "status": "ready",
            "query": "主查询",
            "hits": [{"id": "evidence-a", "content": "旧摘要", "score": 0.6}],
        },
        {
            "status": "degraded",
            "query": "补充查询",
            "hits": [
                {"id": "evidence-a", "content": "新摘要", "score": 0.9},
                {"id": "evidence-b", "content": "新增摘要", "score": 0.8},
            ],
        },
    )

    assert merged["retrieval_rounds"] == 2
    assert merged["evidence_ids"] == ["evidence-a", "evidence-b"]
    assert merged["hits"][0]["content"] == "新摘要"
    assert merged["queries"] == ["主查询", "补充查询"]


def test_research_synthesis_exposes_follow_up_and_conflict_summary() -> None:
    """汇总结果应同时暴露主题覆盖度、冲突和后续动作。"""
    synthesis = build_research_synthesis(
        {
            "market": {"status": "degraded", "hits": []},
            "competitor": {"status": "ready", "hits": []},
            "user_insight": {"status": "degraded", "hits": []},
        }
    )

    assert synthesis["status"] == "partial"
    assert synthesis["needs_follow_up"] is True
    assert set(synthesis["coverage"]) == {"market", "competitor", "user_insight"}
    assert synthesis["follow_up_actions"]

