"""文件职责：封装 FastMCP 到业务 REST API 的受控转发与错误转换。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token

from merchpilot.core.config import get_settings


@dataclass(frozen=True, slots=True)
class ApiResult:
    """`ApiResult` 封装本模块相关状态和行为，对调用方提供清晰边界。"""
    data: dict[str, Any]
    headers: dict[str, str]


def _authorization_header() -> str:
    """内部辅助函数`_authorization_header`；拆分主流程并集中处理当前模块的边界条件。"""
    access_token = get_access_token()
    if access_token is None or not access_token.token:
        raise ToolError("缺少有效的 MerchPilot 身份凭证")
    return f"Bearer {access_token.token}"


async def _request_api(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> ApiResult:
    """内部辅助函数`_request_api`；拆分主流程并集中处理当前模块的边界条件。"""
    settings = get_settings()
    headers = {
        "Authorization": _authorization_header(),
        "X-MerchPilot-Client": "fastmcp",
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    try:
        async with httpx.AsyncClient(
            base_url=settings.mcp_api_base_url.rstrip("/"),
            timeout=settings.mcp_request_timeout_seconds,
        ) as client:
            response = await client.request(
                method,
                path,
                params={key: value for key, value in (params or {}).items() if value is not None},
                json=json,
                headers=headers,
            )
    except httpx.HTTPError as exc:
        raise ToolError("MerchPilot API 当前不可用") from exc
    if response.is_error:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = None
        message = str(detail or response.reason_phrase or "请求失败")
        raise ToolError(f"MerchPilot API 返回 {response.status_code}：{message}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise ToolError("MerchPilot API 返回了非预期的数据结构")
    return ApiResult(data=payload, headers=dict(response.headers))


async def request_api(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """实现FastMCP的`request_api`流程，并保持鉴权、确认门禁和错误转换一致。"""
    result = await _request_api(
        method,
        path,
        params=params,
        json=json,
        idempotency_key=idempotency_key,
    )
    return result.data


async def request_api_with_metadata(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> ApiResult:
    """实现FastMCP的`request_api_with_metadata`流程，并保持鉴权、确认门禁和错误转换一致。"""
    return await _request_api(
        method,
        path,
        params=params,
        json=json,
        idempotency_key=idempotency_key,
    )
