"""文件职责：验证 mcp integration 相关规则、边界与回归行为。"""

from __future__ import annotations

import json

import httpx

import merchpilot.api.routes.mcp_integration as integration_module
from merchpilot.core.config import Settings
from merchpilot.ports.identity import Identity


def tool_payload(index: int) -> dict[str, object]:
    """辅助构造`tool payload`测试数据或依赖，减少用例中的重复准备代码。"""
    return {
        "name": f"tool_{index}",
        "title": f"Tool {index}",
        "description": f"工具 {index}",
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
        "_meta": {"fastmcp": {"tags": ["readonly", "planning"]}},
        "inputSchema": {
            "type": "object",
            "required": ["project_id"] if index == 1 else [],
            "properties": {
                "page_size": {"type": "integer", "maximum": 50},
            },
        },
    }


def test_decode_mcp_event_stream_payload() -> None:
    """验证“decode mcp event stream payload”场景，确保业务规则、权限和异常边界保持稳定。"""
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
    response = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        text=f"event: message\ndata: {json.dumps(payload)}\n\n",
    )

    assert integration_module._decode_mcp_payload(response) == payload


async def test_mcp_integration_returns_paginated_current_identity_contract(monkeypatch) -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    async def fake_health(settings: object) -> tuple[bool, dict[str, object]]:
        """模拟`health`外部行为，避免测试依赖真实异步服务。"""
        del settings
        return True, {"status": "ok", "service": "merchpilot-mcp", "version": "0.1.0"}

    async def fake_request(
        settings: object,
        token: str,
        method: str,
        params: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """模拟`request`外部行为，避免测试依赖真实异步服务。"""
        del settings, params
        assert token == "local-profile:viewer"
        assert method == "tools/list"
        return {"tools": [tool_payload(index) for index in range(1, 10)]}

    monkeypatch.setattr(integration_module, "_probe_mcp_health", fake_health)
    monkeypatch.setattr(integration_module, "_mcp_request", fake_request)

    result = await integration_module.get_mcp_integration(
        page=2,
        page_size=4,
        authorization="Bearer local-profile:viewer",
        identity=Identity("viewer-1", "tenant-a", ("viewer",)),
    )

    assert result.status == "ready"
    assert result.authenticated is True
    assert result.total == 9
    assert result.read_only_total == 9
    assert result.controlled_write_total == 0
    assert [tool.name for tool in result.tools] == ["tool_5", "tool_6", "tool_7", "tool_8"]
    assert result.tools[0].read_only is True
    assert result.tools[0].max_page_size == 50
    assert result.tenant_id == "tenant-a"
    assert result.client_configuration["mcpServers"]["merchpilot"]["headers"] == {
        "Authorization": "Bearer local-profile:viewer"
    }


async def test_mcp_integration_degrades_without_service(monkeypatch) -> None:
    """验证“mcp integration degrades without service”场景，确保业务规则、权限和异常边界保持稳定。"""
    async def fake_health(settings: object) -> tuple[bool, dict[str, object]]:
        """模拟`health`外部行为，避免测试依赖真实异步服务。"""
        del settings
        return False, {}

    monkeypatch.setattr(integration_module, "_probe_mcp_health", fake_health)

    result = await integration_module.get_mcp_integration(
        page=1,
        page_size=6,
        authorization=None,
        identity=Identity("viewer-1", "tenant-a", ("viewer",)),
    )

    assert result.status == "unavailable"
    assert result.health_ready is False
    assert result.authenticated is False
    assert result.total == 0
    assert result.read_only_total == 0
    assert result.controlled_write_total == 0
    assert result.error == "FastMCP 服务未启动或健康检查失败"


async def test_mcp_verification_returns_bounded_business_scope(monkeypatch) -> None:
    """验证“mcp verification returns bounded business scope”场景，确保业务规则、权限和异常边界保持稳定。"""
    async def fake_request(
        settings: object,
        token: str,
        method: str,
        params: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """模拟`request`外部行为，避免测试依赖真实异步服务。"""
        del settings
        assert token == "local-profile:planner"
        assert method == "tools/call"
        assert params == {"name": "get_business_dashboard", "arguments": {}}
        return {
            "isError": False,
            "structuredContent": {
                "project_total": 8,
                "active_project_total": 3,
                "pending_approval_count": 2,
                "pending_launch_review_count": 1,
                "selected_product_total": 4,
                "active_initiative_total": 2,
            },
        }

    monkeypatch.setattr(integration_module, "_mcp_request", fake_request)

    result = await integration_module.verify_mcp_integration(
        authorization=None,
        identity=Identity("planner-1", "tenant-a", ("planner",)),
    )

    assert result.status == "verified"
    assert result.tool_name == "get_business_dashboard"
    assert result.tenant_id == "tenant-a"
    assert result.project_total == 8
    assert result.active_project_total == 3
    assert result.pending_approval_total == 3
    assert result.selected_product_total == 4
    assert result.active_initiative_total == 2


def test_production_client_configuration_never_embeds_current_token() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    settings = Settings(
        auth_mode="oidc",
        app_env="production",
        mcp_public_base_url="https://mcp.example.com",
    )

    configuration = integration_module._client_configuration(
        settings,
        Identity("user-1", "tenant-a", ("viewer",)),
    )

    assert configuration == {
        "mcpServers": {
            "merchpilot": {
                "url": "https://mcp.example.com/mcp",
                "headers": {"Authorization": "Bearer <MerchPilot access token>"},
            }
        }
    }
