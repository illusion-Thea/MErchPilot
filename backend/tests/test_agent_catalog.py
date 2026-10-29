"""文件职责：验证规划节点目录与实际 Mesh 节点保持一致。"""

from merchpilot.agents.catalog import AGENT_CATALOG, get_agent_catalog, validate_agent_catalog
from merchpilot.agents.mesh.graph import build_mesh_graph
from merchpilot.agents.prompts import PROMPT_REGISTRY


def test_agent_catalog_covers_all_mesh_nodes() -> None:
    """每个运行节点都必须有明确的执行类型和业务边界。"""
    node_names = [item.node_name for item in AGENT_CATALOG]

    assert len(node_names) == 14
    assert len(set(node_names)) == len(node_names)
    assert all(item.business_boundary for item in AGENT_CATALOG)
    assert all(item.degradation_policy for item in AGENT_CATALOG)


def test_mesh_node_categories_are_explicit() -> None:
    """规划流程应明确区分 LLM Agent、确定性工具和人工审批门禁。"""
    counts = {
        execution_type: sum(item.execution_type == execution_type for item in AGENT_CATALOG)
        for execution_type in ("llm_agent", "deterministic_tool", "human_gate")
    }

    assert counts == {"llm_agent": 6, "deterministic_tool": 7, "human_gate": 1}
    assert (
        next(item for item in AGENT_CATALOG if item.node_name == "finance_agent").display_name
        == "财务测算引擎"
    )
    assert (
        next(item for item in AGENT_CATALOG if item.node_name == "review_agent").display_name
        == "线上人工审批门禁"
    )


def test_llm_agents_have_prompt_identity() -> None:
    """需要模型推理的节点必须登记 Prompt 构造器和版本。"""
    prompt_agents = [item for item in AGENT_CATALOG if item.execution_type == "llm_agent"]

    assert {item.node_name for item in prompt_agents} == {
        "requirement_agent",
        "research_planning_agent",
        "concept_agent",
        "critic_agent",
        "narrative_agent",
        "multimodal_evidence_agent",
    }
    assert all(item.prompt_name and item.prompt_version for item in prompt_agents)


def test_llm_agents_match_registered_builders() -> None:
    """每个模型 Agent 都必须绑定可调用的 Prompt 构造器和正确版本。"""
    validate_agent_catalog()
    prompt_agents = [item for item in AGENT_CATALOG if item.execution_type == "llm_agent"]

    assert {item.prompt_name for item in prompt_agents} == set(PROMPT_REGISTRY)
    assert all(callable(definition.builder) for definition in PROMPT_REGISTRY.values())
    assert all(
        PROMPT_REGISTRY[item.prompt_name].version == item.prompt_version
        for item in prompt_agents
        if item.prompt_name
    )


def test_catalog_returns_independent_copies() -> None:
    """目录查询结果不能反向修改全局注册表。"""
    catalog = get_agent_catalog()
    catalog[0].input_keys.append("temporary")

    assert "temporary" not in AGENT_CATALOG[0].input_keys


def test_agent_catalog_matches_compiled_mesh_nodes() -> None:
    """目录必须覆盖 LangGraph 实际注册的全部业务节点。"""
    graph_nodes = set(build_mesh_graph().nodes) - {"__start__", "__end__"}
    catalog_nodes = {
        item.node_name
        for item in AGENT_CATALOG
        if item.execution_scope == "planning_mesh"
    }

    assert graph_nodes == catalog_nodes
