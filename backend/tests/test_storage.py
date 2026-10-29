"""文件职责：验证 storage 相关规则、边界与回归行为。"""

from pathlib import Path

import pytest

import merchpilot.adapters.storage as storage_module
from merchpilot.adapters.local_storage import LocalFileStorageAdapter


def test_object_storage_factory_uses_configured_local_root(monkeypatch, tmp_path: Path) -> None:
    """验证“object storage factory uses configured local root”场景，确保业务规则、权限和异常边界保持稳定。"""
    class LocalStorageSettings:
        """提供`LocalStorageSettings`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
        object_storage_provider = "local"
        local_storage_path = tmp_path

    monkeypatch.setattr(storage_module, "get_settings", lambda: LocalStorageSettings())
    storage_module.get_object_storage_provider.cache_clear()

    try:
        provider = storage_module.get_object_storage_provider()
        assert isinstance(provider, LocalFileStorageAdapter)
        assert provider.root == tmp_path
    finally:
        storage_module.get_object_storage_provider.cache_clear()


def test_object_storage_factory_rejects_unconfigured_provider(monkeypatch) -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    class UnsupportedStorageSettings:
        """提供`UnsupportedStorageSettings`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
        object_storage_provider = "oss"
        local_storage_path = Path("/tmp/merchpilot-test-files")

    monkeypatch.setattr(storage_module, "get_settings", lambda: UnsupportedStorageSettings())
    storage_module.get_object_storage_provider.cache_clear()

    try:
        with pytest.raises(RuntimeError, match="unsupported object storage provider: oss"):
            storage_module.get_object_storage_provider()
    finally:
        storage_module.get_object_storage_provider.cache_clear()
