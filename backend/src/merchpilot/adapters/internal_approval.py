"""文件职责：实现本地内部审批适配器，并预留企业 OA 对接边界。"""

from __future__ import annotations

from typing import Any

from merchpilot.core.ids import new_id


class InternalApprovalProvider:
    """`InternalApprovalProvider` 是端口的本地适配实现，用于开发环境并保留企业替换边界。"""
    async def create_approval(self, payload: dict[str, Any]) -> str:
        """实现`create_approval`端口操作；保持本地实现与未来企业适配器契约一致。"""
        del payload
        return new_id("approval")

    async def cancel_approval(self, external_id: str) -> None:
        """实现`cancel_approval`端口操作；保持本地实现与未来企业适配器契约一致。"""
        del external_id

    async def query_approval(self, external_id: str) -> dict[str, Any]:
        """实现`query_approval`端口操作；保持本地实现与未来企业适配器契约一致。"""
        return {"external_id": external_id, "provider": "internal"}

    async def verify_callback(self, headers: dict[str, str], body: bytes) -> bool:
        """实现`verify_callback`端口操作；保持本地实现与未来企业适配器契约一致。"""
        del headers, body
        return True
