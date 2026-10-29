"""文件职责：使用本地目录实现对象存储端口，便于 Docker 本地开发。"""

from __future__ import annotations

from pathlib import Path

from merchpilot.core.config import get_settings


class LocalFileStorageAdapter:
    """`LocalFileStorageAdapter` 是端口的本地适配实现，用于开发环境并保留企业替换边界。"""
    def __init__(self, root: Path | None = None) -> None:
        """初始化`LocalFileStorageAdapter`所需依赖和默认状态。"""
        self.root = root or get_settings().local_storage_path
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        """内部辅助函数`_path`；拆分主流程并集中处理当前模块的边界条件。"""
        resolved = (self.root / key).resolve()
        if self.root.resolve() not in resolved.parents and resolved != self.root.resolve():
            raise ValueError("invalid object key")
        return resolved

    def path_for(self, key: str) -> Path:
        """实现`path_for`端口操作；保持本地实现与未来企业适配器契约一致。"""
        return self._path(key)

    async def put_object(self, key: str, content: bytes, content_type: str) -> str:
        """实现`put_object`端口操作；保持本地实现与未来企业适配器契约一致。"""
        del content_type
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return key

    async def get_object(self, key: str) -> bytes:
        """实现`get_object`端口操作；保持本地实现与未来企业适配器契约一致。"""
        return self._path(key).read_bytes()

    async def delete_object(self, key: str) -> None:
        """实现`delete_object`端口操作；保持本地实现与未来企业适配器契约一致。"""
        self._path(key).unlink(missing_ok=True)

    async def create_download_url(self, key: str, expires_seconds: int = 900) -> str:
        """实现`create_download_url`端口操作；保持本地实现与未来企业适配器契约一致。"""
        del expires_seconds
        return f"/api/v1/files/{key}"
