"""文件职责：返回当前身份、角色和企业集成能力状态。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from merchpilot.api.dependencies import get_current_identity
from merchpilot.api.schemas import IdentityRead
from merchpilot.core.config import get_settings
from merchpilot.ports.identity import Identity

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=IdentityRead)
async def get_current_user(
    identity: Identity = Depends(get_current_identity),
) -> IdentityRead:
    """处理`GET /me`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    settings = get_settings()
    return IdentityRead(
        user_id=identity.user_id,
        tenant_id=identity.tenant_id,
        roles=identity.roles,
        auth_mode=settings.auth_mode,
        local_profiles=settings.local_auth_profile_list if settings.auth_mode == "local" else (),
    )
