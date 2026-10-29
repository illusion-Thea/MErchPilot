"""文件职责：声明对象存储端口，隔离文件业务与本地或阿里云 OSS。"""

from __future__ import annotations

from typing import Protocol


class ObjectStorageProvider(Protocol):
    """`ObjectStorageProvider` 声明可替换的企业能力契约，使业务层不依赖具体实现。"""

    async def put_object(self, key: str, content: bytes, content_type: str) -> str:
        """保存对象并返回可持久化的对象键。"""
        ...

    async def get_object(self, key: str) -> bytes:
        """按对象键读取完整文件内容。"""
        ...

    async def delete_object(self, key: str) -> None:
        """删除指定对象，具体幂等语义由适配器实现。"""
        ...

    async def create_download_url(self, key: str, expires_seconds: int = 900) -> str:
        """创建有时效的下载地址，避免页面感知底层存储实现。"""
        ...
