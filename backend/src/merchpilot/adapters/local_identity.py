"""文件职责：从请求头解析本地演示身份，模拟企业 SSO 用户上下文。"""

from __future__ import annotations

from merchpilot.core.config import get_settings
from merchpilot.ports.identity import Identity


class LocalIdentityProvider:
    """`LocalIdentityProvider` 是端口的本地适配实现，用于开发环境并保留企业替换边界。"""
    async def authenticate(self, credential: str) -> Identity:
        """校验访问凭证并返回后端可信的用户、租户和角色上下文。"""
        settings = get_settings()
        token = credential.removeprefix("Bearer ").strip()
        if not token:
            return Identity(
                user_id=settings.local_auth_user_id,
                tenant_id=settings.local_auth_tenant_id,
                roles=settings.local_auth_role_list,
            )
        if token.startswith("local-profile:"):
            profile = token.removeprefix("local-profile:").strip()
            if profile not in settings.local_auth_profile_list:
                raise ValueError("本地身份档案不存在")
            return Identity(
                user_id=f"{settings.local_auth_user_id}-{profile}",
                tenant_id=settings.local_auth_tenant_id,
                roles=(profile,),
            )
        # 测试替身和旧配置对象可能没有该字段；真实 Settings 默认关闭不安全兼容模式。
        if not getattr(settings, "allow_insecure_local_auth", False):
            raise ValueError(
                "本地身份认证未开启不安全兼容模式，请使用 local-profile:<profile> 凭证"
            )
        return Identity(
            user_id=token,
            tenant_id=settings.local_auth_tenant_id,
            roles=settings.local_auth_role_list,
        )
