"""文件职责：验证 identity 相关规则、边界与回归行为。"""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

import merchpilot.adapters.local_identity as local_identity_module
from merchpilot.adapters.local_identity import LocalIdentityProvider
from merchpilot.api.dependencies import (
    get_current_identity,
    require_admin,
    require_approver,
    require_planner,
)
from merchpilot.core.config import Settings
from merchpilot.main import app
from merchpilot.ports.identity import Identity


async def test_local_identity_uses_default_profile_without_token() -> None:
    """验证“local identity uses default user without token”场景，确保业务规则、权限和异常边界保持稳定。"""
    identity = await get_current_identity(None)
    assert identity.user_id == "local-user"
    assert identity.tenant_id == "default"
    assert identity.roles == ("admin",)


def test_production_rejects_local_admin_authentication() -> None:
    """验证“production rejects local admin authentication”场景，确保业务规则、权限和异常边界保持稳定。"""
    with pytest.raises(ValidationError, match="AUTH_MODE=local"):
        Settings(_env_file=None, app_env="production", auth_mode="local")


def test_non_development_rejects_local_authentication() -> None:
    """验证“non development rejects local authentication”场景，确保业务规则、权限和异常边界保持稳定。"""
    with pytest.raises(ValidationError, match="development environments"):
        Settings(_env_file=None, app_env="staging", auth_mode="local")


async def test_local_identity_rejects_arbitrary_bearer_subject() -> None:
    """验证“local identity uses bearer subject”场景，确保业务规则、权限和异常边界保持稳定。"""
    with pytest.raises(ValueError, match="不安全兼容模式"):
        await LocalIdentityProvider().authenticate("Bearer buyer-01")


async def test_local_identity_supports_configurable_tenant_and_roles(monkeypatch) -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    class LocalAuthSettings:
        """提供`LocalAuthSettings`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
        allow_insecure_local_auth = True
        local_auth_user_id = "configured-user"
        local_auth_tenant_id = "tenant-02"
        local_auth_role_list = ("planner", "viewer")

    monkeypatch.setattr(local_identity_module, "get_settings", LocalAuthSettings)

    identity = await LocalIdentityProvider().authenticate("")

    assert identity.user_id == "configured-user"
    assert identity.tenant_id == "tenant-02"
    assert identity.roles == ("planner", "viewer")


async def test_planner_and_approver_roles_are_separated() -> None:
    """验证“planner and approver roles are separated”场景，确保业务规则、权限和异常边界保持稳定。"""
    planner = Identity(user_id="planner-01", tenant_id="tenant-01", roles=("planner",))
    approver = Identity(user_id="approver-01", tenant_id="tenant-01", roles=("approver",))

    assert await require_planner(planner) == planner
    assert await require_approver(approver) == approver

    with pytest.raises(HTTPException) as planner_error:
        await require_approver(planner)
    assert planner_error.value.status_code == 403

    with pytest.raises(HTTPException) as approver_error:
        await require_planner(approver)
    assert approver_error.value.status_code == 403


async def test_audit_events_require_admin_role() -> None:
    """验证“audit events require admin role”场景，确保业务规则、权限和异常边界保持稳定。"""
    admin = Identity(user_id="admin-01", tenant_id="tenant-01", roles=("admin",))
    viewer = Identity(user_id="viewer-01", tenant_id="tenant-01", roles=("viewer",))

    assert await require_admin(admin) == admin
    with pytest.raises(HTTPException) as error:
        await require_admin(viewer)
    assert error.value.status_code == 403


def test_current_identity_endpoint_exposes_effective_identity() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer local-profile:planner"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "user_id": "local-user-planner",
        "tenant_id": "default",
        "roles": ["planner"],
        "auth_mode": "local",
        "local_profiles": ["admin", "planner", "approver", "viewer"],
    }


async def test_local_identity_profile_switches_roles() -> None:
    """验证“local identity profile switches roles”场景，确保业务规则、权限和异常边界保持稳定。"""
    identity = await LocalIdentityProvider().authenticate("Bearer local-profile:approver")

    assert identity.user_id == "local-user-approver"
    assert identity.tenant_id == "default"
    assert identity.roles == ("approver",)


async def test_local_identity_rejects_unknown_profile() -> None:
    """验证“local identity rejects unknown profile”场景，确保业务规则、权限和异常边界保持稳定。"""
    with pytest.raises(ValueError, match="本地身份档案不存在"):
        await LocalIdentityProvider().authenticate("Bearer local-profile:unknown")


async def test_local_identity_rejects_arbitrary_subject_when_insecure_mode_disabled(monkeypatch) -> None:
    """关闭兼容模式时，不允许任意 Bearer subject 获得默认角色。"""
    class SecureLocalAuthSettings:
        """提供关闭不安全兼容模式的最小配置替身。"""
        allow_insecure_local_auth = False
        local_auth_user_id = "configured-user"
        local_auth_tenant_id = "tenant-02"
        local_auth_profiles = "admin,planner"
        local_auth_roles = "admin"

        @property
        def local_auth_profile_list(self) -> tuple[str, ...]:
            return ("admin", "planner")

        @property
        def local_auth_role_list(self) -> tuple[str, ...]:
            return ("admin",)

    monkeypatch.setattr(local_identity_module, "get_settings", SecureLocalAuthSettings)
    with pytest.raises(ValueError, match="不安全兼容模式"):
        await LocalIdentityProvider().authenticate("Bearer arbitrary-subject")
