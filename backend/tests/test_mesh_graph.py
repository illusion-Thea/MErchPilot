"""文件职责：验证 mesh graph 相关规则、边界与回归行为。"""

from typing import Any

from merchpilot.agents.mesh.graph import (
    AgentNodeExecutionError,
    MeshState,
    _with_node_retries,
    build_mesh_graph,
    market_agent,
)


async def test_mesh_graph_reaches_approval() -> None:
    """验证“mesh graph reaches approval”场景，确保业务规则、权限和异常边界保持稳定。"""
    graph = build_mesh_graph()
    result = await graph.ainvoke(
        {
            "run_id": "run_test",
            "request": {
                "category": "智能水杯",
                "target_market": "中国",
                "constraints": {"target_margin": 0.45},
            },
            "outputs": {},
            "status": "running",
            "approval_required": False,
        }
    )
    assert result["approval_required"] is True
    assert result["status"] == "approval_required"
    assert result["outputs"]["concept"]["target_market"] == "中国"
    assert result["outputs"]["concept"]["candidate_count"] == 3
    assert len(result["outputs"]["concept"]["candidates"]) == 3


async def test_mesh_graph_streams_each_agent_update() -> None:
    """验证“mesh graph streams each agent update”场景，确保业务规则、权限和异常边界保持稳定。"""
    graph = build_mesh_graph()
    seen_nodes: set[str] = set()
    async for update in graph.astream(
        {
            "run_id": "run_stream",
            "request": {
                "category": "智能水杯",
                "target_market": "中国",
                "constraints": {},
            },
            "outputs": {},
            "status": "running",
            "approval_required": False,
        },
        stream_mode="updates",
    ):
        seen_nodes.update(update)

    assert seen_nodes == {
        "requirement_agent",
        "research_planning_agent",
        "market_agent",
        "competitor_agent",
        "user_insight_agent",
        "research_synthesis_agent",
        "concept_agent",
        "supplier_agent",
        "finance_agent",
        "scoring_agent",
        "critic_agent",
        "narrative_agent",
        "review_agent",
    }


async def test_research_agents_apply_tenant_category_and_market_filters(monkeypatch) -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    captured: dict[str, Any] = {}

    class StubRetriever:
        """提供`StubRetriever`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
        async def search(self, query: str, **kwargs: object) -> dict[str, object]:
            """辅助构造`search`测试数据或依赖，减少用例中的重复准备代码。"""
            captured["query"] = query
            captured.update(kwargs)
            return {"status": "ready", "evidence_ids": [], "hits": []}

    monkeypatch.setattr(
        "merchpilot.agents.mesh.graph.get_evidence_retriever",
        lambda: StubRetriever(),
    )
    state: MeshState = {
        "run_id": "run_filters",
        "request": {
            "tenant_id": "tenant-a",
            "category": "智能保温杯",
            "target_market": "中国",
            "constraints": {},
        },
        "outputs": {
            "requirement": {
                "category": "智能保温杯",
                "target_market": "中国",
                "constraints": {},
            }
        },
        "status": "researching",
        "approval_required": False,
    }

    await market_agent(state)

    assert captured["tenant_id"] == "tenant-a"
    assert captured["category"] == "智能保温杯"
    assert captured["target_market"] == "中国"


async def test_agent_node_retries_then_completes() -> None:
    """验证“agent node retries then completes”场景，确保业务规则、权限和异常边界保持稳定。"""
    attempts = 0
    events: list[tuple[str, str, dict[str, object]]] = []

    async def flaky_node(state: MeshState) -> dict[str, object]:
        """辅助构造`flaky node`测试数据或依赖，减少用例中的重复准备代码。"""
        del state
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ConnectionError("temporary retrieval failure")
        return {"outputs": {"market": {"status": "ready"}}}

    async def handle_event(node_name: str, event: str, payload: dict[str, object]) -> None:
        """辅助构造`handle event`测试数据或依赖，减少用例中的重复准备代码。"""
        events.append((node_name, event, payload))

    wrapped = _with_node_retries(
        "market_agent",
        flaky_node,
        event_handler=handle_event,
        max_attempts=3,
        retry_base_seconds=0,
    )
    result = await wrapped(
        {
            "run_id": "run_retry",
            "request": {},
            "outputs": {},
            "status": "running",
            "approval_required": False,
            "resume_completed_nodes": [],
        }
    )

    assert result["outputs"]["market"]["status"] == "ready"
    assert attempts == 3
    assert [event for _, event, _ in events] == ["started", "retrying", "started", "retrying", "started"]


async def test_agent_node_failure_reports_final_error() -> None:
    """验证“agent node failure reports final error”场景，确保业务规则、权限和异常边界保持稳定。"""
    events: list[str] = []

    async def failing_node(state: MeshState) -> dict[str, object]:
        """辅助构造`failing node`测试数据或依赖，减少用例中的重复准备代码。"""
        del state
        raise RuntimeError("permanent failure")

    async def handle_event(node_name: str, event: str, payload: dict[str, object]) -> None:
        """辅助构造`handle event`测试数据或依赖，减少用例中的重复准备代码。"""
        del node_name, payload
        events.append(event)

    wrapped = _with_node_retries(
        "finance_agent",
        failing_node,
        event_handler=handle_event,
        max_attempts=2,
        retry_base_seconds=0,
    )

    try:
        await wrapped(
            {
                "run_id": "run_failure",
                "request": {},
                "outputs": {},
                "status": "running",
                "approval_required": False,
                "resume_completed_nodes": [],
            }
        )
    except AgentNodeExecutionError as exc:
        assert exc.node_name == "finance_agent"
        assert exc.attempt == 2
    else:
        raise AssertionError("expected AgentNodeExecutionError")

    assert events == ["started", "retrying", "started", "failed"]
