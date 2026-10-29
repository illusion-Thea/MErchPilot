"""文件职责：定义 LLM Agent、确定性业务工具和人工审批门禁组成的 LangGraph Mesh。"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, NotRequired, TypedDict, cast

from langgraph.graph import END, START, StateGraph

from merchpilot.core.config import get_settings
from merchpilot.infrastructure.locks import DistributedLockUnavailable, distributed_lock
from merchpilot.services.concepts import (
    build_candidate_concepts,
    finalize_candidate_concepts,
    resolve_candidate_concept,
)
from merchpilot.services.finance import calculate_candidate_financials, calculate_financials
from merchpilot.services.llm_planning import (
    generate_concept_drafts,
    generate_planning_narrative,
    generate_requirement_analysis,
    generate_research_plan,
    review_candidate_concepts,
)
from merchpilot.services.research_governance import (
    build_research_synthesis,
    merge_research_results,
)
from merchpilot.services.retrieval import get_evidence_retriever
from merchpilot.services.scoring import build_scorecard
from merchpilot.services.supplier import evaluate_supplier_constraints


def merge_outputs(current: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    """实现Agent Mesh中的`merge_outputs`节点或辅助流程，并合并结构化运行状态。"""
    return {**current, **update}


class MeshState(TypedDict):
    """`MeshState` 封装本模块相关状态和行为，对调用方提供清晰边界。"""
    run_id: str
    request: dict[str, Any]
    outputs: Annotated[dict[str, Any], merge_outputs]
    status: str
    approval_required: bool
    resume_completed_nodes: list[str]
    metrics: NotRequired[dict[str, Any]]


NodeEventHandler = Callable[[str, str, dict[str, Any]], Awaitable[None]]
AgentNode = Callable[[MeshState], dict[str, Any] | Awaitable[dict[str, Any]]]
WrappedAgentNode = Callable[[MeshState], Awaitable[dict[str, Any]]]


class AgentNodeExecutionError(RuntimeError):
    """`AgentNodeExecutionError` 表示本模块专用异常，并携带上层处理错误所需的上下文。"""
    def __init__(self, node_name: str, attempt: int, error: Exception) -> None:
        """初始化`AgentNodeExecutionError`所需依赖和默认状态。"""
        self.node_name = node_name
        self.attempt = attempt
        self.original_error = error
        super().__init__(f"Agent 节点 {node_name} 执行失败（第 {attempt} 次尝试）: {error}")


async def _noop_node_event_handler(
    node_name: str,
    event: str,
    payload: dict[str, Any],
) -> None:
    """内部辅助函数`_noop_node_event_handler`；拆分主流程并集中处理当前模块的边界条件。"""
    del node_name, event, payload


def _with_node_retries(
    node_name: str,
    node: AgentNode,
    *,
    event_handler: NodeEventHandler,
    max_attempts: int,
    retry_base_seconds: float,
) -> WrappedAgentNode:
    """内部辅助函数`_with_node_retries`；拆分主流程并集中处理当前模块的边界条件。"""
    async def execute(state: MeshState) -> dict[str, Any]:
        """实现Agent Mesh中的`execute`节点或辅助流程，并合并结构化运行状态。"""
        # 恢复执行时复用已经持久化的节点产出，避免重复调用模型或覆盖人工复核过的结果。
        if node_name in state.get("resume_completed_nodes", []):
            await event_handler(
                node_name,
                "skipped",
                {"reason": "completed_output_reused", "max_attempts": max_attempts},
            )
            return {}

        # 节点级重试比整条工作流重跑更安全；指数退避也能减少外部模型短暂故障时的请求冲击。
        for attempt in range(1, max_attempts + 1):
            await event_handler(
                node_name,
                "started",
                {"attempt": attempt, "max_attempts": max_attempts},
            )
            try:
                settings = get_settings()
                if not settings.agent_distributed_lock_enabled:
                    outcome = node(state)
                    return await outcome if inspect.isawaitable(outcome) else outcome
                run_id = state.get("run_id", "unknown")
                try:
                    async with distributed_lock(
                        f"{settings.redis_key_prefix}:lock:agent-node:{run_id}:{node_name}",
                        blocking_timeout=0.05,
                    ):
                        outcome = node(state)
                        return await outcome if inspect.isawaitable(outcome) else outcome
                except DistributedLockUnavailable:
                    if not settings.distributed_lock_fail_open:
                        raise
                    outcome = node(state)
                    return await outcome if inspect.isawaitable(outcome) else outcome
            except Exception as exc:
                if attempt >= max_attempts:
                    await event_handler(
                        node_name,
                        "failed",
                        {
                            "attempt": attempt,
                            "max_attempts": max_attempts,
                            "error": str(exc),
                        },
                    )
                    raise AgentNodeExecutionError(node_name, attempt, exc) from exc
                retry_delay = retry_base_seconds * (2 ** (attempt - 1))
                await event_handler(
                    node_name,
                    "retrying",
                    {
                        "attempt": attempt,
                        "next_attempt": attempt + 1,
                        "max_attempts": max_attempts,
                        "retry_delay_seconds": retry_delay,
                        "error": str(exc),
                    },
                )
                if retry_delay > 0:
                    await asyncio.sleep(retry_delay)

        raise RuntimeError("unreachable")

    return execute


async def requirement_agent(state: MeshState) -> dict[str, Any]:
    """实现Agent Mesh中的`requirement_agent`节点或辅助流程，并合并结构化运行状态。"""
    request = state["request"]
    requirement = await generate_requirement_analysis(request)
    return {
        "outputs": {"requirement": requirement},
        "status": "researching",
    }


async def research_planning_agent(state: MeshState) -> dict[str, Any]:
    """执行研究策略 Prompt，决定三路证据检索的查询方向和字段要求。"""
    requirement = state["outputs"].get("requirement", {})
    normalized_requirement = requirement if isinstance(requirement, dict) else {}
    return {
        "outputs": {
            "research_plan": await generate_research_plan(
                state["request"],
                normalized_requirement,
            )
        },
        "status": "researching",
    }


async def _research(state: MeshState, topic: str, intent: str) -> dict[str, Any]:
    """内部辅助函数`_research`；拆分主流程并集中处理当前模块的边界条件。"""
    requirement = state["outputs"].get("requirement", {})
    category = str(requirement.get("category") or "")
    target_market = str(requirement.get("target_market") or "")
    research_plan = state["outputs"].get("research_plan", {})
    planned_query = (
        research_plan.get(f"{topic}_query")
        if isinstance(research_plan, dict)
        else None
    )
    query = str(planned_query or f"{target_market} {category} {intent}").strip()
    result = await get_evidence_retriever().search(
        query,
        tenant_id=str(state["request"].get("tenant_id") or "default"),
        category=category or None,
        target_market=target_market or None,
        top_k=5,
    )
    return {
        "outputs": {
            topic: {
                **result,
                "run_id": state["run_id"],
            }
        }
    }


async def market_agent(state: MeshState) -> dict[str, Any]:
    """实现Agent Mesh中的`market_agent`节点或辅助流程，并合并结构化运行状态。"""
    return await _research(state, "market", "市场规模 增长趋势 销量 价格带")


async def competitor_agent(state: MeshState) -> dict[str, Any]:
    """实现Agent Mesh中的`competitor_agent`节点或辅助流程，并合并结构化运行状态。"""
    return await _research(state, "competitor", "竞品 品牌 产品卖点 定价 销量")


async def user_insight_agent(state: MeshState) -> dict[str, Any]:
    """实现Agent Mesh中的`user_insight_agent`节点或辅助流程，并合并结构化运行状态。"""
    return await _research(state, "user_insight", "目标用户 需求 痛点 评价 使用场景")


async def research_synthesis_agent(state: MeshState) -> dict[str, Any]:
    """汇总研究覆盖率，并在有效证据覆盖不足时自动执行一次补充检索。"""
    outputs = state["outputs"]
    preliminary = build_research_synthesis(outputs)
    assessments = preliminary.get("topic_assessments")
    topic_assessments = assessments if isinstance(assessments, dict) else {}
    research_plan = outputs.get("research_plan", {})
    normalized_plan = research_plan if isinstance(research_plan, dict) else {}
    follow_up_queries = normalized_plan.get("follow_up_queries")
    normalized_follow_ups = follow_up_queries if isinstance(follow_up_queries, dict) else {}
    requirement = outputs.get("requirement", {})
    normalized_requirement = requirement if isinstance(requirement, dict) else {}
    category = str(normalized_requirement.get("category") or "")
    target_market = str(normalized_requirement.get("target_market") or "")
    supplemented_outputs: dict[str, Any] = {}
    supplemented_topics: list[str] = []

    for topic in ("market", "competitor", "user_insight"):
        assessment = topic_assessments.get(topic)
        normalized_assessment = assessment if isinstance(assessment, dict) else {}
        # 空结果通常代表数据源缺失，重复同类查询没有价值；已有命中但覆盖不足时才补检索。
        should_supplement = (
            normalized_assessment.get("needs_follow_up") is True
            and normalized_assessment.get("retrieval_status") == "ready"
            and int(normalized_assessment.get("evidence_count") or 0) > 0
        )
        if not should_supplement:
            continue
        planned_queries = normalized_follow_ups.get(topic)
        query_candidates = planned_queries if isinstance(planned_queries, list) else []
        follow_up_intent = str(normalized_assessment.get("follow_up_intent") or "补充证据")
        query = str(
            next((item for item in query_candidates if isinstance(item, str) and item.strip()), "")
            or f"{target_market} {category} {follow_up_intent}"
        ).strip()
        supplement = await get_evidence_retriever().search(
            query,
            tenant_id=str(state["request"].get("tenant_id") or "default"),
            category=category or None,
            target_market=target_market or None,
            top_k=5,
        )
        primary = outputs.get(topic, {})
        normalized_primary = primary if isinstance(primary, dict) else {}
        supplemented_outputs[topic] = {
            **merge_research_results(normalized_primary, supplement),
            "run_id": state["run_id"],
            "supplement_reason": follow_up_intent,
        }
        supplemented_topics.append(topic)

    final_outputs = {**outputs, **supplemented_outputs}
    synthesis = build_research_synthesis(final_outputs)
    synthesis["supplemented_topics"] = supplemented_topics
    synthesis["supplemented_count"] = len(supplemented_topics)
    return {
        "outputs": {
            **supplemented_outputs,
            "research_synthesis": synthesis,
        },
        "status": "validating",
    }


async def concept_agent(state: MeshState) -> dict[str, Any]:
    """实现Agent Mesh中的`concept_agent`节点或辅助流程，并合并结构化运行状态。"""
    requirement = state["outputs"].get("requirement", {})
    normalized_requirement = requirement if isinstance(requirement, dict) else {}
    generation = await generate_concept_drafts(state["outputs"], state["request"])
    drafts = generation.get("drafts")
    if isinstance(drafts, list) and drafts:
        concept = finalize_candidate_concepts(
            normalized_requirement,
            state["outputs"],
            drafts,
            state.get("metrics"),
            generation_mode="llm_structured",
            generation_metadata={
                **(
                    generation.get("generation")
                    if isinstance(generation.get("generation"), dict)
                    else {}
                ),
                "evidence_audit": generation.get("evidence_audit", {}),
            },
        )
    else:
        concept = build_candidate_concepts(
            normalized_requirement,
            state["outputs"],
            state.get("metrics"),
        )
        concept["generation_mode"] = "deterministic_fallback"
        concept["generation"] = generation.get("generation", {})
        concept["evidence_audit"] = generation.get("evidence_audit", {})
    return {
        "outputs": {
            "concept": concept,
            "concept_generation": generation,
        },
        "status": "validating",
    }


def supplier_agent(state: MeshState) -> dict[str, Any]:
    """实现Agent Mesh中的`supplier_agent`节点或辅助流程，并合并结构化运行状态。"""
    constraints = state["request"].get("constraints", {})
    normalized_constraints = constraints if isinstance(constraints, dict) else {}
    return {
        "outputs": {
            "supplier": evaluate_supplier_constraints(
                normalized_constraints,
                state.get("metrics"),
            )
        }
    }


def finance_agent(state: MeshState) -> dict[str, Any]:
    """实现Agent Mesh中的`finance_agent`节点或辅助流程，并合并结构化运行状态。"""
    constraints = state["request"].get("constraints", {})
    normalized_constraints = constraints if isinstance(constraints, dict) else {}
    revision_context = state["request"].get("revision_context", {})
    candidate_id = (
        revision_context.get("selected_candidate_id")
        if isinstance(revision_context, dict)
        else None
    )
    concept = state["outputs"].get("concept", {})
    selected_candidate = (
        resolve_candidate_concept(concept, candidate_id)
        if isinstance(concept, dict) and candidate_id
        else None
    )
    financials = (
        calculate_candidate_financials(selected_candidate, normalized_constraints, state.get("metrics"))
        if selected_candidate is not None
        else calculate_financials(normalized_constraints, state.get("metrics"))
    )
    return {
        "outputs": {
            "finance": financials
        }
    }


def scoring_agent(state: MeshState) -> dict[str, Any]:
    """实现Agent Mesh中的`scoring_agent`节点或辅助流程，并合并结构化运行状态。"""
    evidence_ids = state["outputs"].get("concept", {}).get("evidence_ids", [])
    normalized_evidence_ids = (
        [str(evidence_id) for evidence_id in evidence_ids if evidence_id]
        if isinstance(evidence_ids, list)
        else []
    )
    finance = state["outputs"].get("finance", {})
    supplier = state["outputs"].get("supplier", {})
    constraints = state["request"].get("constraints", {})
    return {
        "outputs": {
            "scorecard": build_scorecard(
                normalized_evidence_ids,
                finance if isinstance(finance, dict) else {},
                supplier if isinstance(supplier, dict) else {},
                constraints if isinstance(constraints, dict) else {},
                state.get("metrics"),
            )
        },
        "status": "reviewing",
    }


async def critic_agent(state: MeshState) -> dict[str, Any]:
    """执行方案审查 Prompt，反驳候选方案并输出阻塞项、警告和修订建议。"""
    critic = await review_candidate_concepts(state["outputs"], state["request"])
    return {"outputs": {"critic": critic}, "status": "reviewing"}


async def narrative_agent(state: MeshState) -> dict[str, Any]:
    """实现Agent Mesh中的`narrative_agent`节点或辅助流程，并合并结构化运行状态。"""
    narrative = await generate_planning_narrative(
        state["outputs"],
        state["request"],
    )
    return {"outputs": {"narrative": narrative}, "status": "reviewing"}


def review_agent(state: MeshState) -> dict[str, Any]:
    """结束自动分析并把运行切换为人工审批状态，不替代审批人作业务决定。"""
    critic = state["outputs"].get("critic", {})
    critic_status = critic.get("status") if isinstance(critic, dict) else None
    findings = critic.get("findings", []) if isinstance(critic, dict) else []
    blocker_count = sum(
        1
        for finding in findings
        if isinstance(finding, dict) and finding.get("severity") == "blocker"
    )
    return {
        "outputs": {
            "approval_gate": {
                "status": (
                    "pending_human_review_with_blockers"
                    if blocker_count
                    else "pending_human_review"
                ),
                "critic_status": critic_status or "partial",
                "blocker_count": blocker_count,
                "recommended_action": "要求修订" if blocker_count else "人工确认",
                "decision_owner": "商品规划负责人",
            }
        },
        "approval_required": True,
        "status": "approval_required",
    }


def build_mesh_graph(
    *,
    event_handler: NodeEventHandler | None = None,
    max_attempts: int = 3,
    retry_base_seconds: float = 1.0,
) -> Any:
    """组装 LLM Agent、确定性工具和人工审批门禁，并定义并行汇合规则。"""
    lifecycle_handler = event_handler or _noop_node_event_handler
    graph = StateGraph(MeshState)
    nodes: tuple[tuple[str, AgentNode], ...] = (
        ("requirement_agent", requirement_agent),
        ("research_planning_agent", research_planning_agent),
        ("market_agent", market_agent),
        ("competitor_agent", competitor_agent),
        ("user_insight_agent", user_insight_agent),
        ("research_synthesis_agent", research_synthesis_agent),
        ("concept_agent", concept_agent),
        ("supplier_agent", supplier_agent),
        ("finance_agent", finance_agent),
        ("scoring_agent", scoring_agent),
        ("critic_agent", critic_agent),
        ("narrative_agent", narrative_agent),
        ("review_agent", review_agent),
    )
    for node_name, node in nodes:
        wrapped_node = _with_node_retries(
            node_name,
            node,
            event_handler=lifecycle_handler,
            max_attempts=max_attempts,
            retry_base_seconds=retry_base_seconds,
        )
        graph.add_node(node_name, cast(Any, wrapped_node))

    # 需求理解和研究规划先后执行；研究规划再驱动三路检索工具并行执行。
    graph.add_edge(START, "requirement_agent")
    graph.add_edge("requirement_agent", "research_planning_agent")
    graph.add_edge("research_planning_agent", "market_agent")
    graph.add_edge("research_planning_agent", "competitor_agent")
    graph.add_edge("research_planning_agent", "user_insight_agent")
    graph.add_edge(
        ["market_agent", "competitor_agent", "user_insight_agent"],
        "research_synthesis_agent",
    )
    graph.add_edge("research_synthesis_agent", "concept_agent")
    # 供应链与财务评估彼此独立，完成后共同进入机会评分，减少无意义的串行等待。
    graph.add_edge("concept_agent", "supplier_agent")
    graph.add_edge("concept_agent", "finance_agent")
    graph.add_edge(["supplier_agent", "finance_agent"], "scoring_agent")
    graph.add_edge("scoring_agent", "critic_agent")
    graph.add_edge("critic_agent", "narrative_agent")
    # 自动 Agent 只生成建议；最后必须切入人工审批门禁，不能自动替代业务负责人决策。
    graph.add_edge("narrative_agent", "review_agent")
    graph.add_edge("review_agent", END)
    return graph.compile()
