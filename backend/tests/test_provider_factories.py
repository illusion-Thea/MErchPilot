"""文件职责：验证 provider factories 相关规则、边界与回归行为。"""

import pytest

import merchpilot.adapters.providers as providers_module
from merchpilot.adapters.console_telemetry import ConsoleTelemetryAdapter
from merchpilot.adapters.internal_approval import InternalApprovalProvider
from merchpilot.adapters.local_identity import LocalIdentityProvider


def test_provider_factories_use_local_defaults(monkeypatch) -> None:
    """验证“provider factories use local defaults”场景，确保业务规则、权限和异常边界保持稳定。"""
    class LocalProviderSettings:
        """提供`LocalProviderSettings`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
        auth_mode = "local"
        external_approval_provider = "internal"
        telemetry_provider = "console"

    monkeypatch.setattr(providers_module, "get_settings", lambda: LocalProviderSettings())
    providers_module.get_external_approval_provider.cache_clear()
    providers_module.get_identity_provider.cache_clear()
    providers_module.get_telemetry_provider.cache_clear()

    try:
        assert isinstance(providers_module.get_identity_provider(), LocalIdentityProvider)
        assert isinstance(
            providers_module.get_external_approval_provider(),
            InternalApprovalProvider,
        )
        assert isinstance(providers_module.get_telemetry_provider(), ConsoleTelemetryAdapter)
    finally:
        providers_module.get_identity_provider.cache_clear()
        providers_module.get_external_approval_provider.cache_clear()
        providers_module.get_telemetry_provider.cache_clear()


@pytest.mark.parametrize(
    ("factory_name", "provider_name", "error_message"),
    [
        ("get_identity_provider", "oidc", "unsupported identity provider: oidc"),
        (
            "get_external_approval_provider",
            "oa",
            "unsupported external approval provider: oa",
        ),
        ("get_telemetry_provider", "aliyun", "unsupported telemetry provider: aliyun"),
    ],
)
def test_provider_factories_reject_unregistered_provider(
    monkeypatch,
    factory_name: str,
    provider_name: str,
    error_message: str,
) -> None:
    """验证“provider factories reject unregistered provider”场景，确保业务规则、权限和异常边界保持稳定。"""
    class UnsupportedProviderSettings:
        """提供`UnsupportedProviderSettings`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
        auth_mode = "local"
        external_approval_provider = "internal"
        telemetry_provider = "console"

    monkeypatch.setattr(providers_module, "get_settings", lambda: UnsupportedProviderSettings())
    if factory_name == "get_identity_provider":
        UnsupportedProviderSettings.auth_mode = provider_name
        factory = providers_module.get_identity_provider
    elif factory_name == "get_external_approval_provider":
        UnsupportedProviderSettings.external_approval_provider = provider_name
        factory = providers_module.get_external_approval_provider
    else:
        UnsupportedProviderSettings.telemetry_provider = provider_name
        factory = providers_module.get_telemetry_provider
    factory.cache_clear()

    try:
        with pytest.raises(RuntimeError, match=error_message):
            factory()
    finally:
        factory.cache_clear()
