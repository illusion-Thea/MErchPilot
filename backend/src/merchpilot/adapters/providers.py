"""文件职责：根据配置选择本地或企业适配器，并保持调用方无感切换。"""

from __future__ import annotations

from functools import lru_cache

from merchpilot.adapters.console_telemetry import ConsoleTelemetryAdapter
from merchpilot.adapters.internal_approval import InternalApprovalProvider
from merchpilot.adapters.local_identity import LocalIdentityProvider
from merchpilot.core.config import get_settings
from merchpilot.ports.approval import ExternalApprovalProvider
from merchpilot.ports.identity import IdentityProvider
from merchpilot.ports.telemetry import TelemetryProvider


@lru_cache(maxsize=1)
def get_identity_provider() -> IdentityProvider:
    """实现`get_identity_provider`端口操作；保持本地实现与未来企业适配器契约一致。"""
    provider = get_settings().auth_mode.strip().lower()
    if provider == "local":
        return LocalIdentityProvider()
    raise RuntimeError(f"unsupported identity provider: {provider}")


@lru_cache(maxsize=1)
def get_external_approval_provider() -> ExternalApprovalProvider:
    """实现`get_external_approval_provider`端口操作；保持本地实现与未来企业适配器契约一致。"""
    provider = get_settings().external_approval_provider.strip().lower()
    if provider == "internal":
        return InternalApprovalProvider()
    raise RuntimeError(f"unsupported external approval provider: {provider}")


@lru_cache(maxsize=1)
def get_telemetry_provider() -> TelemetryProvider:
    """实现`get_telemetry_provider`端口操作；保持本地实现与未来企业适配器契约一致。"""
    provider = get_settings().telemetry_provider.strip().lower()
    if provider == "console":
        return ConsoleTelemetryAdapter()
    raise RuntimeError(f"unsupported telemetry provider: {provider}")
