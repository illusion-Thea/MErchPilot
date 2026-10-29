"""文件职责：解析 FastMCP Bearer 身份并实施租户与角色访问控制。"""

from __future__ import annotations

from fastmcp.server.auth import AccessToken, TokenVerifier

from merchpilot.api.dependencies import authenticate_credential


class MerchPilotTokenVerifier(TokenVerifier):
    """`MerchPilotTokenVerifier` 封装本模块相关状态和行为，对调用方提供清晰边界。"""
    async def verify_token(self, token: str) -> AccessToken | None:
        """实现FastMCP的`verify_token`流程，并保持鉴权、确认门禁和错误转换一致。"""
        try:
            identity = await authenticate_credential(f"Bearer {token}")
        except Exception:
            return None
        return AccessToken(
            token=token,
            client_id=identity.user_id,
            subject=identity.user_id,
            scopes=["merchpilot.read"],
            claims={
                "tenant_id": identity.tenant_id,
                "roles": list(identity.roles),
            },
        )
