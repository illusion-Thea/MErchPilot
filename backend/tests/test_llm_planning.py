"""文件职责：验证 llm planning 相关规则、边界与回归行为。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from merchpilot.agents.prompts import build_concept_prompt, build_requirement_prompt
from merchpilot.services.llm_planning import (
    generate_concept_drafts,
    generate_planning_narrative,
    generate_requirement_analysis,
    generate_research_plan,
    review_candidate_concepts,
)


@pytest.mark.asyncio
async def test_narrative_falls_back_without_llm_key(monkeypatch) -> None:
    """验证“narrative falls back without llm key”场景，确保业务规则、权限和异常边界保持稳定。"""
    def unavailable_model():
        """辅助构造`unavailable model`测试数据或依赖，减少用例中的重复准备代码。"""
        raise RuntimeError("DASHSCOPE_API_KEY is not configured")

    monkeypatch.setattr("merchpilot.services.llm_planning.get_chat_model", unavailable_model)
    result = await generate_planning_narrative(
        {
            "scorecard": {"score": 80, "warnings": []},
            "finance": {"margin_rate": 0.3732},
            "supplier": {"risk_level": "low"},
            "market": {"evidence_ids": ["evidence-a"]},
        },
        {"category": "智能保温杯", "target_market": "中国"},
    )

    assert result["status"] == "degraded"
    assert result["provider"] == "deterministic"
    assert result["recommendations"]


@pytest.mark.asyncio
async def test_narrative_uses_structured_llm_response(monkeypatch) -> None:
    """验证“narrative uses structured llm response”场景，确保业务规则、权限和异常边界保持稳定。"""
    class StubModel:
        """提供`StubModel`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
        model_name = "qwen-plus"

        async def ainvoke(self, prompt: str):
            """辅助构造`ainvoke`测试数据或依赖，减少用例中的重复准备代码。"""
            assert "只返回 JSON" in prompt
            return SimpleNamespace(
                content='{"summary":"建议继续验证","recommendations":["先做样品测试"],"risks":["供应商资质待补"]}'
            )

    monkeypatch.setattr("merchpilot.services.llm_planning.get_chat_model", lambda: StubModel())
    result = await generate_planning_narrative({}, {"category": "智能水杯", "target_market": "中国"})

    assert result == {
        "status": "ready",
        "provider": "dashscope",
        "model": "qwen-plus",
        "prompt_version": "2026-09-06.v1",
        "summary": "建议继续验证",
        "recommendations": ["先做样品测试"],
        "risks": ["供应商资质待补"],
        "evidence_ids": [],
        "reason": None,
    }


@pytest.mark.asyncio
async def test_prompt_agents_keep_structured_contracts(monkeypatch) -> None:
    """验证需求、研究、概念和审查 Agent 都按独立契约返回结构化结果。"""

    class StubModel:
        """提供测试模型，返回各个 Prompt Agent 所需的最小合法 JSON。"""

        model_name = "qwen-plus"

        async def ainvoke(self, prompt: str):
            """根据 Prompt 角色返回对应的结构化模型结果。"""
            if "需求理解 Agent" in prompt:
                content = '{"category":"智能水杯","target_market":"中国","target_user":"城市白领"}'
            elif "多源证据研究 Agent" in prompt:
                content = (
                    '{"market_query":"市场查询","competitor_query":"竞品查询",'
                    '"user_insight_query":"用户查询"}'
                )
            elif "商品概念生成 Agent" in prompt:
                content = (
                    '{"candidates":[{"id":"draft-a","name":"证据型水杯",'
                    '"positioning":"通勤防漏","feature_hypotheses":["防漏"],'
                    '"evidence_ids":["e1"]}]}'
                )
            else:
                content = (
                    '{"status":"ready","summary":"未发现阻塞问题",'
                    '"findings":[],"recommended_candidate_id":"concept-1"}'
                )
            return SimpleNamespace(content=content)

    monkeypatch.setattr("merchpilot.services.llm_planning.get_chat_model", lambda: StubModel())
    request = {"category": "智能水杯", "target_market": "中国", "constraints": {"target_user": "城市白领"}}
    requirement = await generate_requirement_analysis(request)
    research_plan = await generate_research_plan(request, requirement)
    outputs = {
        "requirement": requirement,
        "research_synthesis": {"status": "ready"},
        "market": {"hits": [{"id": "e1", "content": "证据"}]},
    }
    concept_generation = await generate_concept_drafts(outputs, request)
    outputs["concept"] = {"candidates": concept_generation["drafts"]}
    critic = await review_candidate_concepts(outputs, request)

    assert requirement["category"] == "智能水杯"
    assert research_plan["market_query"] == "市场查询"
    assert concept_generation["drafts"][0]["name"] == "证据型水杯"
    assert critic["status"] == "ready"


@pytest.mark.asyncio
async def test_critic_blocks_model_result_without_traceable_evidence(monkeypatch) -> None:
    """模型自报 ready 但候选方案无证据时，确定性守门仍必须阻塞。"""

    class StubModel:
        """返回表面合法、但缺少业务证据的审查结果。"""

        model_name = "qwen-plus"

        async def ainvoke(self, prompt: str):
            """模拟审查模型没有发现候选方案证据问题。"""
            assert "方案审查 Agent" in prompt
            return SimpleNamespace(
                content=(
                    '{"status":"ready","summary":"未发现阻塞问题",'
                    '"findings":[],"recommended_candidate_id":"concept-1"}'
                )
            )

    monkeypatch.setattr("merchpilot.services.llm_planning.get_chat_model", lambda: StubModel())
    critic = await review_candidate_concepts(
        {
            "concept": {
                "candidates": [
                    {
                        "id": "concept-1",
                        "feature_hypotheses": ["防漏"],
                        "evidence_ids": [],
                    }
                ]
            },
            "market": {"hits": [{"id": "e1", "content": "证据"}]},
        },
        {"category": "智能水杯", "target_market": "中国", "constraints": {}},
    )

    assert critic["status"] == "blocked"
    assert any(
        finding["severity"] == "blocker"
        and "没有关联任何有效研究证据" in finding["issue"]
        for finding in critic["findings"]
    )


@pytest.mark.asyncio
async def test_prompt_agents_fall_back_without_model(monkeypatch) -> None:
    """验证没有模型密钥时，Prompt Agent 仍返回可解释的确定性降级结果。"""

    def unavailable_model():
        """模拟本地开发环境未配置模型密钥。"""
        raise RuntimeError("DASHSCOPE_API_KEY is not configured")

    monkeypatch.setattr("merchpilot.services.llm_planning.get_chat_model", unavailable_model)
    request = {"category": "智能水杯", "target_market": "中国", "constraints": {}}
    requirement = await generate_requirement_analysis(request)
    plan = await generate_research_plan(request, requirement)
    drafts = await generate_concept_drafts({"requirement": requirement}, request)
    critic = await review_candidate_concepts({"concept": {"candidates": []}}, request)

    assert requirement["generation"]["status"] == "degraded"
    assert "中国 智能水杯" in plan["market_query"]
    assert drafts["drafts"] == []
    assert critic["generation"]["status"] == "degraded"


def test_revision_feedback_is_present_in_business_prompts() -> None:
    """审批修订意见必须进入需求和概念 Prompt，保证人工反馈真正影响下一轮分析。"""
    request = {
        "category": "智能水杯",
        "target_market": "中国",
        "constraints": {},
        "revision_context": {
            "revision_no": 2,
            "parent_run_id": "run-parent",
            "comment": "请降低单位成本，并补充杯盖清洗体验证据",
        },
    }
    requirement_prompt = build_requirement_prompt(request)
    concept_prompt = build_concept_prompt(
        request,
        {"category": "智能水杯", "target_market": "中国"},
        {"status": "partial"},
        [],
    )

    assert "请降低单位成本，并补充杯盖清洗体验证据" in requirement_prompt
    assert "run-parent" in concept_prompt
