"""文件职责：集中维护各 Agent 的角色 Prompt、输入边界和输出格式。"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from merchpilot.agents.contracts import (
    ConceptDraftSet,
    CriticReview,
    NarrativeOutput,
    RequirementAnalysis,
    ResearchPlan,
)

PROMPT_VERSION = "2026-09-06.v1"
MULTIMODAL_PROMPT_VERSION = "2026-09-06.multimodal.v1"


@dataclass(frozen=True)
class PromptDefinition:
    """记录 Prompt 构造器、版本和可审计身份。"""

    name: str
    version: str
    builder: Callable[..., str]


def _json(value: Any) -> str:
    """把业务输入序列化为稳定、可读且不会丢失中文的 Prompt 片段。"""
    return json.dumps(value, ensure_ascii=False, default=str)


def _schema(model: type[Any]) -> str:
    """把 Pydantic 契约转成模型可理解的 JSON Schema。"""
    return _json(model.model_json_schema())


def _revision_context(request: dict[str, Any]) -> str:
    """提取人工审批反馈，明确告诉后续 Agent 本轮修订的业务原因。"""
    context = request.get("revision_context")
    if not isinstance(context, dict):
        return "本次为首次规划，没有历史审批修订意见。"
    comment = str(context.get("comment") or "").strip()
    if not comment:
        return "本次为修订运行，但审批人未提供文字意见。"
    return _json(
        {
            "revision_no": context.get("revision_no"),
            "parent_run_id": context.get("parent_run_id"),
            "approval_feedback": comment,
        }
    )


def build_requirement_prompt(request: dict[str, Any]) -> str:
    """构造需求理解 Agent 的 Prompt。"""
    return f"""
你是商品规划流程中的「需求理解 Agent」，负责把业务输入整理成可执行的商品规划约束。
你的输出会直接交给研究规划 Agent，不要生成商品方案，也不要擅自补充业务事实。

工作要求：
1. 保留用户明确给出的品类、目标市场和约束；不确定的信息放入 assumptions。
2. 把约束拆成可验证的条件，把成功标准拆成可衡量指标。
3. 如果关键信息缺失，写入 clarifying_questions，但仍然给出当前可执行的最小理解结果。
4. 只返回 JSON，不要 Markdown、解释文字或代码块。

输入业务请求：
{_json(request)}

人工审批反馈（如有）：
{_revision_context(request)}

必须符合以下 JSON Schema：
{_schema(RequirementAnalysis)}
""".strip()


def build_research_planning_prompt(
    request: dict[str, Any],
    requirement: dict[str, Any],
) -> str:
    """构造研究规划 Agent 的 Prompt。"""
    return f"""
你是商品规划流程中的「多源证据研究 Agent」。你不直接下结论，而是为市场、竞品、用户洞察三个主题设计检索策略。

工作要求：
1. 为三个主题分别生成高信息量检索 query，query 必须包含品类、市场和需要验证的业务问题。
2. 明确每个主题需要覆盖的字段；不要把无法从证据验证的主观判断写成事实。
3. 预判可能存在的时间、规格、价格或统计口径冲突，并给出补充检索方向。
4. 只返回 JSON，不要 Markdown、解释文字或代码块。

原始请求：
{_json(request)}

人工审批反馈（如有）：
{_revision_context(request)}

已整理需求：
{_json(requirement)}

必须符合以下 JSON Schema：
{_schema(ResearchPlan)}
""".strip()


def build_concept_prompt(
    request: dict[str, Any],
    requirement: dict[str, Any],
    research_synthesis: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> str:
    """构造商品概念生成 Agent 的 Prompt。"""
    return f"""
你是商品规划流程中的「商品概念生成 Agent」。请基于已治理的证据，提出可以进入供应链和财务评估的候选商品方案。

工作要求：
1. 生成 2 到 4 个彼此有明显差异的候选方案，不得套用固定的轻量款、智能款、基础款模板。
2. 每个候选方案必须说明目标用户、核心卖点、要解决的痛点、规格假设和差异化假设。
3. 把无法被当前证据证明的内容放入 assumptions，把审批前必须验证的内容放入 validation_items。
4. evidence_ids 只能从下方“允许引用的证据 ID”中选择；没有证据支持的内容必须写成假设或验证项。
5. 不要虚构销量、价格、成本、供应商或用户评价；价格和成本只能引用证据中的范围，或留空等待确定性工具测算。
6. 只返回 JSON，不要 Markdown、解释文字或代码块。

原始请求：
{_json(request)}

人工审批反馈（如有）：
{_revision_context(request)}

需求理解：
{_json(requirement)}

研究治理结果：
{_json(research_synthesis)}

证据明细：
{_json(evidence)}

允许引用的证据 ID：
{_json([item.get("evidence_id") for item in evidence if item.get("evidence_id")])}

必须符合以下 JSON Schema：
{_schema(ConceptDraftSet)}
""".strip()


def build_critic_prompt(
    request: dict[str, Any],
    research_synthesis: dict[str, Any],
    concept: dict[str, Any],
    finance: dict[str, Any],
    supplier: dict[str, Any],
    scorecard: dict[str, Any],
) -> str:
    """构造方案审查 Agent 的 Prompt。"""
    return f"""
你是商品规划流程中的「方案审查 Agent」，职责是反驳候选方案，而不是替方案辩护。

请逐个检查候选方案：
1. 核对每个关键卖点、痛点和差异化假设是否有证据 ID 支撑。
2. 检查候选方案与财务、供应链、评分结果是否存在逻辑矛盾。
3. 识别可能的幻觉、过度外推、口径冲突和缺失验证项。
4. blocker 表示不能直接进入审批的硬问题，warning 表示需要补充验证，info 表示优化建议。
5. 只返回 JSON，不要 Markdown、解释文字或代码块。

原始请求：
{_json(request)}

人工审批反馈（如有）：
{_revision_context(request)}

研究治理：
{_json(research_synthesis)}

候选方案：
{_json(concept)}

财务结果：
{_json(finance)}

供应链结果：
{_json(supplier)}

评分结果：
{_json(scorecard)}

必须符合以下 JSON Schema：
{_schema(CriticReview)}
""".strip()


def build_narrative_prompt(
    request: dict[str, Any],
    outputs: dict[str, Any],
    evidence: list[dict[str, str]],
) -> str:
    """构造规划报告 Agent 的 Prompt。"""
    return f"""
你是商品规划流程中的「规划报告 Agent」，负责把证据、商业评估和审查结果整理成供业务审批阅读的结论。

工作要求：
1. 结论必须区分事实、假设和待验证事项；不能把候选方案假设写成已验证事实。
2. 优先反映方案审查 Agent 的 blocker、warning 和必做修订。
3. 建议要能落到商品、供应链、财务或验证动作；风险要具体，不要泛泛而谈。
4. 只返回 JSON，不要 Markdown、解释文字或代码块。

项目请求：
{_json(request)}

人工审批反馈（如有）：
{_revision_context(request)}

当前结果：
{_json(outputs)}

可引用证据：
{_json(evidence)}

必须符合以下 JSON Schema：
{_schema(NarrativeOutput)}
""".strip()


def build_multimodal_extraction_prompt(
    filename: str,
    locator: str,
    auxiliary_text: str,
) -> str:
    """构造 PDF、PPT、DOCX 和图片的 Qwen-VL/OCR 抽取 Prompt。"""
    return f"""
你是企业商品规划平台的「多模态证据抽取 Agent」，使用 Qwen-VL 读取文件片段。
文件：{filename}
片段定位：{locator}
辅助文本：{auxiliary_text or "无"}

请完成 OCR、表格/图表识别和商品业务字段抽取。只返回 JSON，不要 Markdown。
要求：
1. 只记录片段中明确出现或可直接读取的事实，不要编造销量、价格、品牌或用户结论。
2. 无法确认的字段留空；需要人工核对的内容将 needs_review=true。
3. 将一页/一张图中可以独立追溯的事实拆成多个 items；没有可靠内容时返回空 items。
4. content 要保留原始语义，便于后续 Milvus 检索；不要输出超长重复 OCR 噪声。

返回结构必须符合：
{{"items":[{{"title":"","content":"","category":"","target_market":"","target_user":"","data_type":"document_extract","observed_at":"","evidence_tags":[],"confidence":"low|medium|high","needs_review":true}}],"summary":""}}
""".strip()


PROMPT_REGISTRY: dict[str, PromptDefinition] = {
    "build_requirement_prompt": PromptDefinition(
        name="build_requirement_prompt",
        version=PROMPT_VERSION,
        builder=build_requirement_prompt,
    ),
    "build_research_planning_prompt": PromptDefinition(
        name="build_research_planning_prompt",
        version=PROMPT_VERSION,
        builder=build_research_planning_prompt,
    ),
    "build_concept_prompt": PromptDefinition(
        name="build_concept_prompt",
        version=PROMPT_VERSION,
        builder=build_concept_prompt,
    ),
    "build_critic_prompt": PromptDefinition(
        name="build_critic_prompt",
        version=PROMPT_VERSION,
        builder=build_critic_prompt,
    ),
    "build_narrative_prompt": PromptDefinition(
        name="build_narrative_prompt",
        version=PROMPT_VERSION,
        builder=build_narrative_prompt,
    ),
    "build_multimodal_extraction_prompt": PromptDefinition(
        name="build_multimodal_extraction_prompt",
        version=MULTIMODAL_PROMPT_VERSION,
        builder=build_multimodal_extraction_prompt,
    ),
}
