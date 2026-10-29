"""文件职责：提供 FastAPI 数据库会话、身份解析和角色权限依赖。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from merchpilot.adapters.providers import get_identity_provider
from merchpilot.core.config import get_settings
from merchpilot.infrastructure.locks import (
    DistributedLockBusy,
    DistributedLockUnavailable,
    distributed_lock,
)
from merchpilot.observability.rate_limit import RateLimitExceeded, check_rate_limit
from merchpilot.ports.identity import Identity

bearer_scheme = HTTPBearer(auto_error=False)


async def authenticate_credential(credential: str) -> Identity:
    """实现`authenticate_credential`流程；输入、输出和异常语义由类型标注及调用方约束。"""
    try:
        identity = await get_identity_provider().authenticate(credential)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="身份认证服务尚未配置",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="身份凭证无效",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    try:
        await check_rate_limit(tenant_id=identity.tenant_id, user_id=identity.user_id)
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="请求过于频繁，请稍后重试",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    return identity


async def get_current_identity(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(bearer_scheme),
    ] = None,
) -> Identity:
    """实现`get_current_identity`流程；输入、输出和异常语义由类型标注及调用方约束。"""
    credential = ""
    if credentials is not None:
        credential = f"{credentials.scheme} {credentials.credentials}"
    return await authenticate_credential(credential)


def _ensure_roles(identity: Identity, allowed_roles: frozenset[str]) -> Identity:
    """内部辅助函数`_ensure_roles`；拆分主流程并集中处理当前模块的边界条件。"""
    if allowed_roles.isdisjoint(identity.roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前用户无权执行此操作",
        )
    return identity


async def require_planner(
    identity: Identity = Depends(get_current_identity),
) -> Identity:
    """实现`require_planner`流程；输入、输出和异常语义由类型标注及调用方约束。"""
    return _ensure_roles(identity, frozenset({"admin", "planner"}))


async def require_approver(
    identity: Identity = Depends(get_current_identity),
) -> Identity:
    """实现`require_approver`流程；输入、输出和异常语义由类型标注及调用方约束。"""
    return _ensure_roles(identity, frozenset({"admin", "approver"}))


async def require_mcp_operator(
    identity: Identity = Depends(get_current_identity),
) -> Identity:
    """实现`require_mcp_operator`流程；输入、输出和异常语义由类型标注及调用方约束。"""
    return _ensure_roles(identity, frozenset({"admin", "planner", "approver"}))


async def require_admin(
    identity: Identity = Depends(get_current_identity),
) -> Identity:
    """实现`require_admin`流程；输入、输出和异常语义由类型标注及调用方约束。"""
    return _ensure_roles(identity, frozenset({"admin"}))


async def acquire_project_run_lock(project_id: str) -> AsyncIterator[None]:
    """为同一项目的规划启动建立跨进程锁，避免重复消耗 Agent 和模型资源。"""
    settings = get_settings()
    if not settings.project_distributed_lock_enabled:
        yield
        return
    try:
        async with distributed_lock(f"{get_settings().redis_key_prefix}:lock:project-run:{project_id}"):
            yield
    except DistributedLockBusy as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该项目正在被其他请求处理，请稍后重试",
        ) from exc
    except DistributedLockUnavailable as exc:
        if settings.distributed_lock_fail_open:
            yield
            return
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该项目正在被其他请求处理，请稍后重试",
        ) from exc
