"""文件职责：声明企业审批系统端口，隔离业务规则与具体 OA 实现。"""

from __future__ import annotations

from typing import Any, Protocol


class ExternalApprovalProvider(Protocol):
    """`ExternalApprovalProvider` 声明可替换的企业能力契约，使业务层不依赖具体实现。"""

    async def create_approval(self, payload: dict[str, Any]) -> str:
        """创建外部审批单并返回外部系统标识。"""
        ...

    async def cancel_approval(self, external_id: str) -> None:
        """撤销仍允许取消的外部审批单。"""
        ...

    async def query_approval(self, external_id: str) -> dict[str, Any]:
        """查询外部审批状态，供本地状态对账。"""
        ...

    async def verify_callback(self, headers: dict[str, str], body: bytes) -> bool:
        """验证 OA 回调来源与正文签名，防止伪造审批结果。"""
        ...
