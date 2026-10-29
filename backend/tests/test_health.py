"""文件职责：验证 health 相关规则、边界与回归行为。"""

from fastapi.testclient import TestClient

import merchpilot.api.routes.health as health_routes
from merchpilot.main import app


def test_liveness() -> None:
    """验证“liveness”场景，确保业务规则、权限和异常边界保持稳定。"""
    with TestClient(app) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_local_docker_web_origin_is_allowed() -> None:
    """验证“local docker web origin is allowed”场景，确保业务规则、权限和异常边界保持稳定。"""
    with TestClient(app) as client:
        response = client.options(
            "/api/v1/auth/me",
            headers={
                "Origin": "http://localhost:3001",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3001"


async def test_readiness_separates_core_and_optional_services(monkeypatch) -> None:
    """验证“readiness separates core and optional services”场景，确保业务规则、权限和异常边界保持稳定。"""
    async def postgres_probe(database_url: str) -> bool:
        """辅助构造`postgres probe`测试数据或依赖，减少用例中的重复准备代码。"""
        del database_url
        return True

    async def redis_probe(redis_url: str) -> bool:
        """辅助构造`redis probe`测试数据或依赖，减少用例中的重复准备代码。"""
        del redis_url
        return True

    async def milvus_probe(milvus_uri: str, milvus_token: str) -> bool:
        """辅助构造`milvus probe`测试数据或依赖，减少用例中的重复准备代码。"""
        del milvus_uri, milvus_token
        return True

    async def worker_probe() -> bool:
        """辅助构造`worker probe`测试数据或依赖，减少用例中的重复准备代码。"""
        return True

    async def model_probe(service_url: str) -> bool:
        """辅助构造`model probe`测试数据或依赖，减少用例中的重复准备代码。"""
        return "embedding-service" not in service_url and "reranker-service" not in service_url

    async def mcp_probe(service_url: str) -> bool:
        """辅助构造`mcp probe`测试数据或依赖，减少用例中的重复准备代码。"""
        return service_url == "http://mcp:8001"

    monkeypatch.setattr(health_routes, "_probe_postgres", postgres_probe)
    monkeypatch.setattr(health_routes, "_probe_redis", redis_probe)
    monkeypatch.setattr(health_routes, "_probe_milvus", milvus_probe)
    monkeypatch.setattr(health_routes, "_probe_worker", worker_probe)
    monkeypatch.setattr(health_routes, "_probe_model_service", model_probe)
    monkeypatch.setattr(health_routes, "_probe_mcp_service", mcp_probe)
    monkeypatch.setattr(health_routes, "get_identity_provider", lambda: object())
    monkeypatch.setattr(health_routes, "get_object_storage_provider", lambda: object())
    monkeypatch.setattr(health_routes, "get_external_approval_provider", lambda: object())
    monkeypatch.setattr(health_routes, "get_telemetry_provider", lambda: object())

    result = await health_routes.ready()

    assert result["status"] == "ok"
    assert result["integration_status"] == "ok"
    assert result["components"] == {
        "postgres": True,
        "redis": True,
        "milvus": True,
        "worker": True,
        "embedding": False,
        "reranker": False,
        "mcp": True,
    }
    assert result["core_components"] == {
        "postgres": True,
        "redis": True,
        "milvus": True,
        "worker": True,
    }
    assert result["optional_components"] == {
        "embedding": False,
        "reranker": False,
        "mcp": True,
    }
    assert result["integration_components"] == {
        "identity": True,
        "object_storage": True,
        "approval": True,
        "telemetry": True,
    }
    assert result["provider_modes"] == {
        "identity": "local",
        "object_storage": "local",
        "approval": "internal",
        "telemetry": "console",
    }


def test_provider_probe_returns_false_for_factory_failure() -> None:
    """验证“provider probe returns false for factory failure”场景，确保业务规则、权限和异常边界保持稳定。"""
    def broken_provider() -> object:
        """辅助构造`broken provider`测试数据或依赖，减少用例中的重复准备代码。"""
        raise RuntimeError("provider unavailable")

    assert health_routes._probe_provider(broken_provider) is False


def test_worker_probe_requires_registered_tasks_and_queues(monkeypatch) -> None:
    """验证“worker probe requires registered tasks and queues”场景，确保业务规则、权限和异常边界保持稳定。"""
    class Inspector:
        """提供`Inspector`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
        def ping(self) -> dict[str, dict[str, str]]:
            """辅助构造`ping`测试数据或依赖，减少用例中的重复准备代码。"""
            return {"worker-1": {"ok": "pong"}}

        def registered(self) -> dict[str, list[str]]:
            """辅助构造`registered`测试数据或依赖，减少用例中的重复准备代码。"""
            return {
                "worker-1": [
                    *health_routes.required_worker_tasks,
                ]
            }

        def active_queues(self) -> dict[str, list[dict[str, str]]]:
            """辅助构造`active queues`测试数据或依赖，减少用例中的重复准备代码。"""
            return {
                "worker-1": [
                    {"name": queue_name}
                    for queue_name in health_routes.required_worker_queues
                ]
            }

    monkeypatch.setattr(
        health_routes.celery_app.control,
        "inspect",
        lambda timeout: Inspector(),
    )

    assert health_routes._probe_worker_sync() is True


def test_worker_probe_rejects_ping_without_business_coverage(monkeypatch) -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    class Inspector:
        """提供`Inspector`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
        def ping(self) -> dict[str, dict[str, str]]:
            """辅助构造`ping`测试数据或依赖，减少用例中的重复准备代码。"""
            return {"worker-1": {"ok": "pong"}}

        def registered(self) -> dict[str, list[str]]:
            """辅助构造`registered`测试数据或依赖，减少用例中的重复准备代码。"""
            return {"worker-1": []}

        def active_queues(self) -> dict[str, list[dict[str, str]]]:
            """辅助构造`active queues`测试数据或依赖，减少用例中的重复准备代码。"""
            return {"worker-1": []}

    monkeypatch.setattr(
        health_routes.celery_app.control,
        "inspect",
        lambda timeout: Inspector(),
    )

    assert health_routes._probe_worker_sync() is False
