"""文件职责：统一登记规划节点、Prompt 契约、工具类型和业务边界。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from merchpilot.agents.prompts import (
    MULTIMODAL_PROMPT_VERSION,
    PROMPT_REGISTRY,
    PROMPT_VERSION,
)

AgentExecutionType = Literal["llm_agent", "deterministic_tool", "human_gate"]
AgentExecutionScope = Literal["planning_mesh", "import_pipeline"]


class AgentDefinition(BaseModel):
    """描述一个 Mesh 执行节点；节点可以是 LLM Agent、确定性工具或人工门禁。"""

    node_name: str
    display_name: str
    execution_type: AgentExecutionType
    execution_scope: AgentExecutionScope = "planning_mesh"
    description: str
    input_keys: list[str] = Field(default_factory=list)
    output_keys: list[str] = Field(default_factory=list)
    prompt_name: str | None = None
    prompt_version: str | None = None
    degradation_policy: str
    business_boundary: str


AGENT_CATALOG: tuple[AgentDefinition, ...] = (
    AgentDefinition(
        node_name="requirement_agent",
        display_name="需求理解 Agent",
        execution_type="llm_agent",
        description="把品类、市场、用户和约束整理为可执行需求上下文。",
        input_keys=["request"],
        output_keys=["requirement"],
        prompt_name="build_requirement_prompt",
        prompt_version=PROMPT_VERSION,
        degradation_policy="模型不可用时保留原始请求并标记为 degraded。",
        business_boundary="不得擅自补充业务事实，不负责生成商品方案。",
    ),
    AgentDefinition(
        node_name="research_planning_agent",
        display_name="研究规划 Agent",
        execution_type="llm_agent",
        description="为市场、竞品和用户洞察生成检索策略、字段要求和补充方向。",
        input_keys=["request", "requirement"],
        output_keys=["research_plan"],
        prompt_name="build_research_planning_prompt",
        prompt_version=PROMPT_VERSION,
        degradation_policy="模型不可用时使用固定主题查询和最低字段要求。",
        business_boundary="只规划证据获取，不直接把主观判断写成事实。",
    ),
    AgentDefinition(
        node_name="market_agent",
        display_name="市场研究工具",
        execution_type="deterministic_tool",
        description="按研究规划检索市场规模、趋势、销量和价格带证据。",
        input_keys=["request", "requirement", "research_plan"],
        output_keys=["market"],
        degradation_policy="检索失败由节点重试和状态快照记录，不伪造证据。",
        business_boundary="只返回带来源的检索结果，不负责生成结论。",
    ),
    AgentDefinition(
        node_name="competitor_agent",
        display_name="竞品研究工具",
        execution_type="deterministic_tool",
        description="按研究规划检索竞品、品牌、卖点、价格和销量证据。",
        input_keys=["request", "requirement", "research_plan"],
        output_keys=["competitor"],
        degradation_policy="检索失败由节点重试和状态快照记录，不伪造证据。",
        business_boundary="只返回带来源的检索结果，不负责生成结论。",
    ),
    AgentDefinition(
        node_name="user_insight_agent",
        display_name="用户洞察检索工具",
        execution_type="deterministic_tool",
        description="按研究规划检索用户评论、痛点、需求标签和使用场景证据。",
        input_keys=["request", "requirement", "research_plan"],
        output_keys=["user_insight"],
        degradation_policy="检索失败由节点重试和状态快照记录，不伪造证据。",
        business_boundary="只返回带来源的检索结果，不替用户做无证据推断。",
    ),
    AgentDefinition(
        node_name="research_synthesis_agent",
        display_name="证据治理节点",
        execution_type="deterministic_tool",
        description="汇总三路研究结果，计算覆盖率并识别冲突和补充检索需求。",
        input_keys=["research_plan", "market", "competitor", "user_insight"],
        output_keys=["research_synthesis"],
        degradation_policy="覆盖不足时最多执行一次自动补充检索，并保留 partial 状态。",
        business_boundary="只治理证据质量，不把缺失字段补成模型事实。",
    ),
    AgentDefinition(
        node_name="concept_agent",
        display_name="商品概念 Agent",
        execution_type="llm_agent",
        description="基于治理后的证据生成 2 到 4 个候选商品概念草案。",
        input_keys=["request", "requirement", "research_synthesis", "evidence"],
        output_keys=["concept_generation", "concept"],
        prompt_name="build_concept_prompt",
        prompt_version=PROMPT_VERSION,
        degradation_policy="模型草案契约校验失败时切换确定性概念规则，并保留证据审计。",
        business_boundary="不得虚构价格、成本、供应商或销量；正式方案必须经过财务和供应链计算。",
    ),
    AgentDefinition(
        node_name="supplier_agent",
        display_name="供应商评估工具",
        execution_type="deterministic_tool",
        description="检查供应商、MOQ、交期、资质和样品验证风险。",
        input_keys=["request.constraints", "planning_metrics"],
        output_keys=["supplier"],
        degradation_policy="缺少供应商数据时返回 partial 或 requires_supplier_data。",
        business_boundary="只评估供应链可行性，不替供应商做事实承诺。",
    ),
    AgentDefinition(
        node_name="finance_agent",
        display_name="财务测算引擎",
        execution_type="deterministic_tool",
        description="计算售价、成本、费用、毛利、贡献利润和盈亏平衡。",
        input_keys=["request.constraints", "concept", "planning_metrics"],
        output_keys=["finance"],
        degradation_policy="参数缺失或非法时返回 requires_cost_data、invalid_constraints 或 unviable。",
        business_boundary="价格和成本以确定性规则为准，不接受模型自由编造的财务数字。",
    ),
    AgentDefinition(
        node_name="scoring_agent",
        display_name="机会评分引擎",
        execution_type="deterministic_tool",
        description="按证据、财务、供应商和数据完整度计算机会分和阻塞项。",
        input_keys=["concept", "finance", "supplier", "request.constraints"],
        output_keys=["scorecard"],
        degradation_policy="关键参数缺失时返回 blocked 或 partial，并拆解扣分原因。",
        business_boundary="评分解释必须可由输入数据复算，不能由模型直接改分。",
    ),
    AgentDefinition(
        node_name="critic_agent",
        display_name="方案审查 Agent",
        execution_type="llm_agent",
        description="反驳候选方案，检查证据引用、财务供应链矛盾和验证缺口。",
        input_keys=["request", "research_synthesis", "concept", "finance", "supplier", "scorecard"],
        output_keys=["critic"],
        prompt_name="build_critic_prompt",
        prompt_version=PROMPT_VERSION,
        degradation_policy="模型不可用时使用确定性审查守门，证据缺失或无效引用直接 blocker。",
        business_boundary="不能因为模型自报 ready 就绕过证据和商业规则。",
    ),
    AgentDefinition(
        node_name="narrative_agent",
        display_name="规划报告 Agent",
        execution_type="llm_agent",
        description="将证据、商业评估和审查结果整理为审批可读的结论。",
        input_keys=["request", "concept", "research_synthesis", "critic", "finance", "supplier", "scorecard"],
        output_keys=["narrative"],
        prompt_name="build_narrative_prompt",
        prompt_version=PROMPT_VERSION,
        degradation_policy="模型不可用时生成确定性摘要，并明确标记降级原因。",
        business_boundary="必须区分事实、假设和待验证项，不替审批人做决策。",
    ),
    AgentDefinition(
        node_name="review_agent",
        display_name="线上人工审批门禁",
        execution_type="human_gate",
        description="把自动分析结果提交给商品规划负责人在线审批。",
        input_keys=["critic", "narrative"],
        output_keys=["approval_gate"],
        degradation_policy="审批服务异常时保持 approval_required，不自动放行。",
        business_boundary="只能创建人工决策边界，不能替代审批人通过、驳回或要求修订。",
    ),
    AgentDefinition(
        node_name="multimodal_evidence_agent",
        display_name="多模态证据抽取 Agent",
        execution_type="llm_agent",
        execution_scope="import_pipeline",
        description="使用 Qwen-VL 对 PDF、PPTX、DOCX 和图片执行 OCR、图表识别和结构化证据抽取。",
        input_keys=["uploaded_file", "file_fragment"],
        output_keys=["evidence_drafts"],
        prompt_name="build_multimodal_extraction_prompt",
        prompt_version=MULTIMODAL_PROMPT_VERSION,
        degradation_policy="Qwen-VL 不可用时仅保留原生文本，并将证据标记为 warning 和 needs_review。",
        business_boundary="不能把图片中无法确认的内容伪装成事实；所有抽取结果必须保留文件定位。",
    ),
)


def validate_agent_catalog() -> None:
    """校验 Mesh 节点的分类、Prompt 名称和版本是否真实注册。"""
    node_names = [item.node_name for item in AGENT_CATALOG]
    if len(node_names) != len(set(node_names)):
        raise ValueError("Agent catalog contains duplicate node names")

    for item in AGENT_CATALOG:
        if item.execution_type == "llm_agent":
            if not item.prompt_name or not item.prompt_version:
                raise ValueError(f"LLM Agent {item.node_name} is missing prompt identity")
            prompt = PROMPT_REGISTRY.get(item.prompt_name)
            if prompt is None:
                raise ValueError(f"Prompt {item.prompt_name} is not registered")
            if prompt.version != item.prompt_version:
                raise ValueError(
                    f"Prompt version mismatch for {item.node_name}: "
                    f"catalog={item.prompt_version}, registry={prompt.version}"
                )
        elif item.prompt_name or item.prompt_version:
            raise ValueError(f"Non-LLM node {item.node_name} must not declare a Prompt")


validate_agent_catalog()


def get_agent_catalog() -> list[AgentDefinition]:
    """返回可序列化的 Agent 目录副本，避免调用方修改全局注册信息。"""
    return [item.model_copy(deep=True) for item in AGENT_CATALOG]
