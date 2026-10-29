"""文件职责：提供对象存储兼容辅助方法和安全文件路径处理。"""

from __future__ import annotations

from functools import lru_cache

from merchpilot.adapters.local_storage import LocalFileStorageAdapter
from merchpilot.core.config import get_settings
from merchpilot.ports.object_storage import ObjectStorageProvider


@lru_cache(maxsize=1)
def get_object_storage_provider() -> ObjectStorageProvider:
    """实现`get_object_storage_provider`端口操作；保持本地实现与未来企业适配器契约一致。"""
    settings = get_settings()
    provider = settings.object_storage_provider.strip().lower()
    if provider == "local":
        return LocalFileStorageAdapter(settings.local_storage_path)
    raise RuntimeError(f"unsupported object storage provider: {provider}")
