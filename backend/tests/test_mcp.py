"""文件职责：验证 mcp 相关规则、边界与回归行为。"""

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken
from fastmcp.utilities.authorization import AuthContext

import merchpilot.mcp.server as server_module
from merchpilot.api.routes.mcp_integration import _decode_mcp_payload
from merchpilot.mcp import api_client
from merchpilot.mcp.auth import MerchPilotTokenVerifier
from merchpilot.mcp.server import app, mcp
from merchpilot.services.approval_guard import approval_review_fingerprint
from merchpilot.services.project_guard import project_configuration_fingerprint
from merchpilot.services.validation_guard import validation_review_fingerprint


async def test_mcp_exposes_bounded_read_only_tool_contract_without_http_identity() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    async with Client(mcp) as client:
        tools = await client.list_tools()

    tool_by_name = {tool.name: tool for tool in tools}
    assert set(tool_by_name) == {
        "list_planning_projects",
        "list_planning_runs",
        "get_planning_run",
        "list_run_evidence",
        "search_enterprise_evidence",
        "list_selected_products",
        "list_product_initiatives",
        "get_launch_review_context",
        "list_project_lifecycles",
        "get_business_dashboard",
    }
    assert tool_by_name["list_run_evidence"].annotations is not None
    assert tool_by_name["list_run_evidence"].annotations.read_only_hint is True
    assert tool_by_name["list_run_evidence"].annotations.destructive_hint is False
    assert tool_by_name["list_run_evidence"].input_schema["properties"]["page_size"]["maximum"] == 50


def test_mcp_http_tool_catalog_is_role_filtered() -> None:
    """验证“mcp http tool catalog is role filtered”场景，确保业务规则、权限和异常边界保持稳定。"""
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    with TestClient(app) as client:
        viewer_response = client.post(
            "/mcp",
            json=payload,
            headers={
                "Authorization": "Bearer local-profile:viewer",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-11-25",
            },
        )
        planner_response = client.post(
            "/mcp",
            json=payload,
            headers={
                "Authorization": "Bearer local-profile:planner",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-11-25",
            },
        )
        approver_response = client.post(
            "/mcp",
            json=payload,
            headers={
                "Authorization": "Bearer local-profile:approver",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-11-25",
            },
        )
        admin_response = client.post(
            "/mcp",
            json=payload,
            headers={
                "Authorization": "Bearer local-profile:admin",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-11-25",
            },
        )

    viewer_tools = {
        tool["name"] for tool in _decode_mcp_payload(viewer_response)["result"]["tools"]
    }
    planner_tools = {
        tool["name"]: tool
        for tool in _decode_mcp_payload(planner_response)["result"]["tools"]
    }
    approver_tools = {
        tool["name"]: tool
        for tool in _decode_mcp_payload(approver_response)["result"]["tools"]
    }
    admin_tools = {
        tool["name"]: tool
        for tool in _decode_mcp_payload(admin_response)["result"]["tools"]
    }
    assert len(viewer_tools) == 10
    assert len(planner_tools) == 14
    assert len(approver_tools) == 13
    assert len(admin_tools) == 17
    assert "create_planning_project_draft" not in viewer_tools
    assert "start_planning_project_analysis" not in viewer_tools
    assert "list_approval_tasks" not in viewer_tools
    assert "list_approval_tasks" not in planner_tools
    assert "claim_approval_task" not in planner_tools
    assert "submit_approval_decision" not in planner_tools
    assert "update_validation_gate" in planner_tools
    assert "update_validation_gate" not in approver_tools
    assert "get_launch_review_context" in viewer_tools
    assert "submit_launch_review" in planner_tools
    assert "submit_launch_review" not in approver_tools
    assert {
        "list_approval_tasks",
        "claim_approval_task",
        "submit_approval_decision",
    } <= set(approver_tools)
    create_tool = planner_tools["create_planning_project_draft"]
    start_tool = planner_tools["start_planning_project_analysis"]
    assert create_tool["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    assert create_tool["inputSchema"]["properties"]["request_id"]["minLength"] == 8
    assert start_tool["annotations"] == create_tool["annotations"]
    assert start_tool["inputSchema"]["required"] == [
        "request_id",
        "project_id",
        "review_token",
        "confirmation",
    ]
    assert start_tool["inputSchema"]["properties"]["review_token"]["minLength"] == 64
    validation_tool = planner_tools["update_validation_gate"]
    assert validation_tool["annotations"] == create_tool["annotations"]
    assert validation_tool["inputSchema"]["required"] == [
        "request_id",
        "project_id",
        "run_id",
        "candidate_id",
        "gate_id",
        "review_token",
        "status",
        "confirmation",
        "note",
    ]
    launch_review_tool = planner_tools["submit_launch_review"]
    assert launch_review_tool["annotations"] == create_tool["annotations"]
    assert launch_review_tool["inputSchema"]["required"] == [
        "request_id",
        "initiative_id",
        "review_token",
        "confirmation",
        "submission_note",
    ]
    decision_tool = approver_tools["submit_approval_decision"]
    assert decision_tool["annotations"] == create_tool["annotations"]
    assert decision_tool["inputSchema"]["required"][:5] == [
        "request_id",
        "task_id",
        "review_token",
        "action",
        "confirmation",
    ]


def test_mcp_planning_write_role_requires_admin_or_planner() -> None:
    """验证“mcp planning write role requires admin or planner”场景，确保业务规则、权限和异常边界保持稳定。"""
    component = object()
    viewer = AccessToken(
        token="viewer", client_id="viewer", scopes=["merchpilot.read"], claims={"roles": ["viewer"]}
    )
    planner = AccessToken(
        token="planner",
        client_id="planner",
        scopes=["merchpilot.read"],
        claims={"roles": ["planner"]},
    )
    admin = AccessToken(
        token="admin", client_id="admin", scopes=["merchpilot.read"], claims={"roles": ["admin"]}
    )

    assert server_module.planning_write_role(AuthContext(token=viewer, component=component)) is False
    assert server_module.planning_write_role(AuthContext(token=planner, component=component)) is True
    assert server_module.planning_write_role(AuthContext(token=admin, component=component)) is True


def test_mcp_approval_role_requires_admin_or_approver() -> None:
    """验证“mcp approval role requires admin or approver”场景，确保业务规则、权限和异常边界保持稳定。"""
    component = object()
    viewer = AccessToken(
        token="viewer", client_id="viewer", scopes=["merchpilot.read"], claims={"roles": ["viewer"]}
    )
    planner = AccessToken(
        token="planner",
        client_id="planner",
        scopes=["merchpilot.read"],
        claims={"roles": ["planner"]},
    )
    approver = AccessToken(
        token="approver",
        client_id="approver",
        scopes=["merchpilot.read"],
        claims={"roles": ["approver"]},
    )
    admin = AccessToken(
        token="admin", client_id="admin", scopes=["merchpilot.read"], claims={"roles": ["admin"]}
    )

    assert server_module.approval_role(AuthContext(token=viewer, component=component)) is False
    assert server_module.approval_role(AuthContext(token=planner, component=component)) is False
    assert server_module.approval_role(AuthContext(token=approver, component=component)) is True
    assert server_module.approval_role(AuthContext(token=admin, component=component)) is True


async def test_mcp_tool_forwards_bounded_page_request(monkeypatch) -> None:
    """验证“mcp tool forwards bounded page request”场景，确保业务规则、权限和异常边界保持稳定。"""
    calls: list[dict[str, object]] = []

    async def fake_request_api(method: str, path: str, **kwargs: object) -> dict[str, object]:
        """模拟`request_api`外部行为，避免测试依赖真实异步服务。"""
        calls.append({"method": method, "path": path, **kwargs})
        return {"items": [], "total": 0, "page": 2, "page_size": 3}

    monkeypatch.setattr(server_module, "request_api", fake_request_api)

    async with Client(mcp) as client:
        result = await client.call_tool(
            "list_planning_projects",
            {"page": 2, "page_size": 3, "keyword": "保温杯", "project_id": "project-1"},
        )

    assert result.is_error is False
    assert calls == [
        {
            "method": "GET",
            "path": "/planning-projects/page",
            "params": {
                "page": 2,
                "page_size": 3,
                "status": None,
                "keyword": "保温杯",
                "project_id": "project-1",
                "archived_only": False,
            },
        }
    ]


async def test_mcp_lifecycle_tool_forwards_priority_sort(monkeypatch) -> None:
    """验证“mcp lifecycle tool forwards priority sort”场景，确保业务规则、权限和异常边界保持稳定。"""
    calls: list[dict[str, object]] = []

    async def fake_request_api(method: str, path: str, **kwargs: object) -> dict[str, object]:
        """模拟`request_api`外部行为，避免测试依赖真实异步服务。"""
        calls.append({"method": method, "path": path, **kwargs})
        return {"items": [], "total": 0, "page": 2, "page_size": 4}

    monkeypatch.setattr(server_module, "request_api", fake_request_api)

    result = await server_module.list_project_lifecycles(
        page=2,
        page_size=4,
        project_id="project-1",
        keyword="保温杯",
        sort="updated",
    )

    assert result["page"] == 2
    assert calls == [
        {
            "method": "GET",
            "path": "/analytics/project-lifecycles/page",
            "params": {
                "page": 2,
                "page_size": 4,
                "project_id": "project-1",
                "keyword": "保温杯",
                "sort": "updated",
                "status": "all",
            },
        }
    ]


async def test_mcp_get_launch_review_context_forwards_initiative(monkeypatch) -> None:
    """验证“mcp get launch review context forwards initiative”场景，确保业务规则、权限和异常边界保持稳定。"""
    calls: list[dict[str, object]] = []
    context = {
        "initiative_id": "initiative-1",
        "can_submit": True,
        "review_token": "a" * 64,
    }

    async def fake_request_api(method: str, path: str, **kwargs: object) -> dict[str, object]:
        """模拟`request_api`外部行为，避免测试依赖真实异步服务。"""
        calls.append({"method": method, "path": path, **kwargs})
        return context

    monkeypatch.setattr(server_module, "request_api", fake_request_api)

    result = await server_module.get_launch_review_context("initiative-1")

    assert calls == [
        {
            "method": "GET",
            "path": "/product-initiatives/initiative-1/launch-review-context",
        }
    ]
    assert result == context


async def test_mcp_submit_launch_review_is_idempotent_and_keeps_human_approval(
    monkeypatch,
) -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    calls: list[dict[str, object]] = []

    async def fake_request_api(method: str, path: str, **kwargs: object) -> api_client.ApiResult:
        """模拟`request_api`外部行为，避免测试依赖真实异步服务。"""
        calls.append({"method": method, "path": path, **kwargs})
        return api_client.ApiResult(
            data={"id": "launch-review-1", "status": "pending"},
            headers={"idempotency-replayed": "true"},
        )

    monkeypatch.setattr(server_module, "request_api_with_metadata", fake_request_api)

    result = await server_module.submit_launch_review(
        request_id="agent:launch-review:001",
        initiative_id="initiative-1",
        review_token="b" * 64,
        confirmation="SUBMIT_LAUNCH_REVIEW",
        submission_note="  试销风险已复核，申请进入人工上市评审。  ",
    )

    assert calls == [
        {
            "method": "POST",
            "path": "/product-initiatives/initiative-1/launch-reviews",
            "json": {
                "submission_note": "试销风险已复核，申请进入人工上市评审。",
                "confirmation": "SUBMIT_LAUNCH_REVIEW",
                "review_token": "b" * 64,
            },
            "idempotency_key": "agent:launch-review:001",
        }
    ]
    assert result["replayed"] is True
    assert result["launch_review"]["status"] == "pending"
    assert result["automatic_actions"] == []
    assert "不会自动批准" in result["next_action"]


async def test_mcp_approval_list_adds_state_bound_review_token(monkeypatch) -> None:
    """验证“mcp approval list adds state bound review token”场景，确保业务规则、权限和异常边界保持稳定。"""
    calls: list[dict[str, object]] = []
    task = {
        "id": "approval-1",
        "project_id": "project-1",
        "run_id": "run-1",
        "approval_type": "planning_review",
        "checkpoint_ref": "checkpoint-1",
        "status": "pending",
        "assignee_id": None,
        "due_at": "2026-09-04T10:00:00",
        "summary": {"title": "规划审批", "score": 86},
    }

    async def fake_request_api(method: str, path: str, **kwargs: object) -> dict[str, object]:
        """模拟`request_api`外部行为，避免测试依赖真实异步服务。"""
        calls.append({"method": method, "path": path, **kwargs})
        return {"items": [task], "total": 1, "page": 1, "page_size": 5}

    monkeypatch.setattr(server_module, "request_api", fake_request_api)

    result = await server_module.list_approval_tasks(task_id="approval-1")

    assert calls == [
        {
            "method": "GET",
            "path": "/approval-tasks/page",
            "params": {
                "status": "pending",
                "assignee": "all",
                "project_id": None,
                "task_id": "approval-1",
                "page": 1,
                "page_size": 5,
            },
        }
    ]
    assert result["items"][0]["review_token"] == approval_review_fingerprint(
        task_id="approval-1",
        project_id="project-1",
        run_id="run-1",
        approval_type="planning_review",
        checkpoint_ref="checkpoint-1",
        status="pending",
        assignee_id=None,
        due_at="2026-09-04T10:00:00",
        summary={"title": "规划审批", "score": 86},
    )


async def test_mcp_claim_approval_forwards_idempotency_and_refreshes_token(monkeypatch) -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    calls: list[dict[str, object]] = []
    task = {
        "id": "approval-1",
        "project_id": "project-1",
        "run_id": "run-1",
        "approval_type": "planning_review",
        "checkpoint_ref": "checkpoint-1",
        "status": "pending",
        "assignee_id": "approver-1",
        "due_at": "2026-09-04T10:00:00",
        "summary": {"title": "规划审批"},
    }

    async def fake_request_api(method: str, path: str, **kwargs: object) -> api_client.ApiResult:
        """模拟`request_api`外部行为，避免测试依赖真实异步服务。"""
        calls.append({"method": method, "path": path, **kwargs})
        return api_client.ApiResult(data=task, headers={"idempotency-replayed": "false"})

    monkeypatch.setattr(server_module, "request_api_with_metadata", fake_request_api)

    result = await server_module.claim_approval_task(
        request_id="agent:approval:claim:001",
        task_id="approval-1",
    )

    assert calls == [
        {
            "method": "POST",
            "path": "/approval-tasks/approval-1/claim",
            "idempotency_key": "agent:approval:claim:001",
        }
    ]
    assert result["task"] == task
    assert result["review_token"] == approval_review_fingerprint(
        task_id="approval-1",
        project_id="project-1",
        run_id="run-1",
        approval_type="planning_review",
        checkpoint_ref="checkpoint-1",
        status="pending",
        assignee_id="approver-1",
        due_at="2026-09-04T10:00:00",
        summary={"title": "规划审批"},
    )
    assert result["replayed"] is False
    assert result["automatic_actions"] == []


async def test_mcp_submit_revision_forwards_only_bounded_changes(monkeypatch) -> None:
    """验证“mcp submit revision forwards only bounded changes”场景，确保业务规则、权限和异常边界保持稳定。"""
    calls: list[dict[str, object]] = []

    async def fake_request_api(method: str, path: str, **kwargs: object) -> api_client.ApiResult:
        """模拟`request_api`外部行为，避免测试依赖真实异步服务。"""
        calls.append({"method": method, "path": path, **kwargs})
        return api_client.ApiResult(
            data={"id": "approval-1", "status": "revision_required"},
            headers={"idempotency-replayed": "true"},
        )

    monkeypatch.setattr(server_module, "request_api_with_metadata", fake_request_api)
    review_token = "a" * 64

    result = await server_module.submit_approval_decision(
        request_id="agent:approval:decision:001",
        task_id="approval-1",
        review_token=review_token,
        action="revision_required",
        confirmation="REQUEST_PLANNING_REVISION",
        comment="  毛利率不足，请调整供应方案。  ",
        selected_candidate_id="candidate-1",
        target_margin=0.38,
        supplier_name=" 新供应商 ",
        moq=300,
    )

    assert calls == [
        {
            "method": "POST",
            "path": "/approval-tasks/approval-1/decision",
            "json": {
                "action": "revision_required",
                "comment": "毛利率不足，请调整供应方案。",
                "changes": {
                    "selected_candidate_id": "candidate-1",
                    "constraints": {
                        "target_margin": 0.38,
                        "supplier_name": "新供应商",
                        "moq": 300,
                    },
                },
                "confirmation": "REQUEST_PLANNING_REVISION",
                "review_token": review_token,
            },
            "idempotency_key": "agent:approval:decision:001",
        }
    ]
    assert result["replayed"] is True
    assert result["automatic_actions"] == []
    assert "新运行版本" in result["side_effects"][1]


async def test_mcp_submit_approval_rejects_unsafe_combinations() -> None:
    """验证“mcp submit approval rejects unsafe combinations”场景，确保业务规则、权限和异常边界保持稳定。"""
    with pytest.raises(ToolError, match="审批确认词"):
        await server_module.submit_approval_decision(
            request_id="agent:approval:decision:002",
            task_id="approval-1",
            review_token="a" * 64,
            action="approved",
            confirmation="REJECT_PLANNING",
            selected_candidate_id="candidate-1",
        )
    with pytest.raises(ToolError, match="必须填写审批意见"):
        await server_module.submit_approval_decision(
            request_id="agent:approval:decision:003",
            task_id="approval-1",
            review_token="a" * 64,
            action="rejected",
            confirmation="REJECT_PLANNING",
        )
    with pytest.raises(ToolError, match="只有要求修订"):
        await server_module.submit_approval_decision(
            request_id="agent:approval:decision:004",
            task_id="approval-1",
            review_token="a" * 64,
            action="approved",
            confirmation="APPROVE_PLANNING",
            selected_candidate_id="candidate-1",
            target_margin=0.4,
        )


async def test_mcp_create_draft_forwards_idempotency_and_never_runs_agent(monkeypatch) -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    calls: list[dict[str, object]] = []

    async def fake_request_api(method: str, path: str, **kwargs: object) -> api_client.ApiResult:
        """模拟`request_api`外部行为，避免测试依赖真实异步服务。"""
        calls.append({"method": method, "path": path, **kwargs})
        return api_client.ApiResult(
            data={"id": "project-1", "status": "draft", "name": "通勤杯规划"},
            headers={"idempotency-replayed": "false"},
        )

    monkeypatch.setattr(server_module, "request_api_with_metadata", fake_request_api)

    result = await server_module.create_planning_project_draft(
        request_id="agent:project:001",
        name="通勤杯规划",
        category="保温杯",
        target_market="中国",
        target_user="城市通勤人群",
        target_margin=0.35,
        min_price=129,
        max_price=199,
        unit_cost=70,
        logistics_cost=8,
        platform_fee_rate=0.05,
        tax_rate=0.03,
        marketing_rate=0.08,
        fixed_cost=20_000,
        forecast_units=1200,
        supplier_name="测试供应商",
        moq=300,
        lead_time_days=20,
        max_lead_time_days=30,
    )

    assert calls == [
        {
            "method": "POST",
            "path": "/planning-projects",
            "json": {
                "name": "通勤杯规划",
                "category": "保温杯",
                "target_market": "中国",
                "constraints": {
                    "target_user": "城市通勤人群",
                    "target_margin": 0.35,
                    "unit_cost": 70,
                    "logistics_cost": 8,
                    "platform_fee_rate": 0.05,
                    "tax_rate": 0.03,
                    "marketing_rate": 0.08,
                    "fixed_cost": 20_000,
                    "forecast_units": 1200,
                    "supplier_name": "测试供应商",
                    "moq": 300,
                    "lead_time_days": 20,
                    "max_lead_time_days": 30,
                    "price_range": {"min": 129, "max": 199},
                },
            },
            "idempotency_key": "agent:project:001",
        }
    ]
    assert result["project"] == {"id": "project-1", "status": "draft", "name": "通勤杯规划"}
    assert result["created_as"] == "draft"
    assert result["review_token"] == project_configuration_fingerprint(
        name="通勤杯规划",
        category="保温杯",
        target_market="中国",
        constraints={
            "target_user": "城市通勤人群",
            "target_margin": 0.35,
            "unit_cost": 70,
            "logistics_cost": 8,
            "platform_fee_rate": 0.05,
            "tax_rate": 0.03,
            "marketing_rate": 0.08,
            "fixed_cost": 20_000,
            "forecast_units": 1200,
            "supplier_name": "测试供应商",
            "moq": 300,
            "lead_time_days": 20,
            "max_lead_time_days": 30,
            "price_range": {"min": 129, "max": 199},
        },
    )
    assert result["automatic_actions"] == []
    assert result["replayed"] is False


async def test_mcp_start_analysis_forwards_confirmation_and_idempotency(monkeypatch) -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    calls: list[dict[str, object]] = []

    async def fake_request_api(method: str, path: str, **kwargs: object) -> api_client.ApiResult:
        """模拟`request_api`外部行为，避免测试依赖真实异步服务。"""
        calls.append({"method": method, "path": path, **kwargs})
        return api_client.ApiResult(
            data={"id": "run-1", "project_id": "project-1", "status": "queued"},
            headers={"idempotency-replayed": "false"},
        )

    monkeypatch.setattr(server_module, "request_api_with_metadata", fake_request_api)
    review_token = "a" * 64

    result = await server_module.start_planning_project_analysis(
        request_id="agent:run:001",
        project_id="project-1",
        review_token=review_token,
        confirmation="START_AGENT_ANALYSIS",
    )

    assert calls == [
        {
            "method": "POST",
            "path": "/planning-projects/project-1/runs",
            "json": {
                "confirmation": "START_AGENT_ANALYSIS",
                "review_token": review_token,
            },
            "idempotency_key": "agent:run:001",
        }
    ]
    assert result["run"]["id"] == "run-1"
    assert result["replayed"] is False
    assert result["side_effects"] == ["已创建规划运行并投递 Celery 队列"]
    assert result["automatic_actions"] == []


async def test_mcp_get_run_adds_validation_review_tokens(monkeypatch) -> None:
    """验证“mcp get run adds validation review tokens”场景，确保业务规则、权限和异常边界保持稳定。"""
    validation_plan = {
        "status": "partial",
        "gates": [{"id": "sample_test", "status": "pending", "materials": []}],
    }

    async def fake_request_api(method: str, path: str, **kwargs: object) -> dict[str, object]:
        """模拟`request_api`外部行为，避免测试依赖真实异步服务。"""
        assert method == "GET"
        assert path == "/planning-projects/project-1/runs/run-1"
        assert kwargs == {}
        return {
            "id": "run-1",
            "project_id": "project-1",
            "status": "approval_required",
            "result_snapshot": {
                "outputs": {
                    "concept": {
                        "candidates": [
                            {"id": "candidate-1", "validation_plan": validation_plan}
                        ],
                        "selected_candidate": {
                            "id": "candidate-1",
                            "validation_plan": {
                                "status": "partial",
                                "gates": [
                                    {
                                        "id": "sample_test",
                                        "status": "pending",
                                        "materials": [],
                                    }
                                ],
                            },
                        },
                    }
                }
            },
        }

    monkeypatch.setattr(server_module, "request_api", fake_request_api)

    result = await server_module.get_planning_run("project-1", "run-1")

    returned_plan = result["result_snapshot"]["outputs"]["concept"]["candidates"][0][
        "validation_plan"
    ]
    assert returned_plan["review_token"] == validation_review_fingerprint(
        project_id="project-1",
        run_id="run-1",
        run_status="approval_required",
        candidate_id="candidate-1",
        validation_plan=validation_plan,
    )
    selected_plan = result["result_snapshot"]["outputs"]["concept"]["selected_candidate"][
        "validation_plan"
    ]
    assert selected_plan["review_token"] == returned_plan["review_token"]


async def test_mcp_update_validation_gate_forwards_bounded_single_update(monkeypatch) -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    calls: list[dict[str, object]] = []

    async def fake_request_api(method: str, path: str, **kwargs: object) -> api_client.ApiResult:
        """模拟`request_api`外部行为，避免测试依赖真实异步服务。"""
        calls.append({"method": method, "path": path, **kwargs})
        return api_client.ApiResult(
            data={"id": "run-1", "project_id": "project-1", "status": "completed"},
            headers={"idempotency-replayed": "false"},
        )

    monkeypatch.setattr(server_module, "request_api_with_metadata", fake_request_api)
    review_token = "b" * 64

    result = await server_module.update_validation_gate(
        request_id="agent:validation:001",
        project_id="project-1",
        run_id="run-1",
        candidate_id="candidate-1",
        gate_id="sample_test",
        review_token=review_token,
        status="blocked",
        confirmation="MARK_VALIDATION_BLOCKED",
        note="  样品跌落测试未通过。  ",
    )

    assert calls == [
        {
            "method": "PATCH",
            "path": "/planning-projects/project-1/runs/run-1/validation-plan",
            "json": {
                "candidate_id": "candidate-1",
                "gates": [
                    {
                        "gate_id": "sample_test",
                        "status": "blocked",
                        "note": "样品跌落测试未通过。",
                    }
                ],
                "confirmation": "MARK_VALIDATION_BLOCKED",
                "review_token": review_token,
            },
            "idempotency_key": "agent:validation:001",
        }
    ]
    assert result["target_status"] == "blocked"
    assert result["replayed"] is False
    assert result["automatic_actions"] == []


async def test_mcp_update_validation_gate_rejects_confirmation_mismatch() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    with pytest.raises(ToolError, match="确认词"):
        await server_module.update_validation_gate(
            request_id="agent:validation:002",
            project_id="project-1",
            run_id="run-1",
            candidate_id="candidate-1",
            gate_id="sample_test",
            review_token="b" * 64,
            status="ready",
            confirmation="MARK_VALIDATION_BLOCKED",
            note="样品测试通过。",
        )


async def test_mcp_tool_requires_access_token(monkeypatch) -> None:
    """验证“mcp tool requires access token”场景，确保业务规则、权限和异常边界保持稳定。"""
    monkeypatch.setattr(api_client, "get_access_token", lambda: None)

    with pytest.raises(ToolError, match="缺少有效的 MerchPilot 身份凭证"):
        await api_client.request_api("GET", "/planning-projects/page")


async def test_mcp_token_verifier_reuses_local_identity() -> None:
    """验证“mcp token verifier reuses local identity”场景，确保业务规则、权限和异常边界保持稳定。"""
    access_token = await MerchPilotTokenVerifier().verify_token("local-profile:viewer")

    assert access_token is not None
    assert access_token.subject == "local-user-viewer"
    assert access_token.claims == {"tenant_id": "default", "roles": ["viewer"]}

    unknown = await MerchPilotTokenVerifier().verify_token("local-profile:unknown")
    assert unknown is None


def test_mcp_health_and_protocol_reject_missing_bearer() -> None:
    """验证“mcp health and protocol reject missing bearer”场景，确保业务规则、权限和异常边界保持稳定。"""
    initialize_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "0.1.0"},
        },
    }
    with TestClient(app) as client:
        health = client.get("/health")
        unauthorized = client.post(
            "/mcp",
            json=initialize_payload,
            headers={"Accept": "application/json, text/event-stream"},
        )

    assert health.status_code == 200
    assert health.json() == {
        "status": "ok",
        "service": "merchpilot-mcp",
        "version": "0.9.0",
    }
    assert unauthorized.status_code == 401
