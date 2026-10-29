"""文件职责：声明企业身份提供方端口，为本地身份和未来 SSO 提供统一契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Identity:
    """保存一次请求经过鉴权后的用户、租户和角色上下文。"""

    user_id: str
    tenant_id: str
    roles: tuple[str, ...]


class IdentityProvider(Protocol):
    """`IdentityProvider` 声明可替换的企业能力契约，使业务层不依赖具体实现。"""

    async def authenticate(self, credential: str) -> Identity:
        """校验访问凭证并返回后端可信的身份上下文。"""
        ...
