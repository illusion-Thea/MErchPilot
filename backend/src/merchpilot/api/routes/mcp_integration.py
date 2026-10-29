"""文件职责：展示 FastMCP 工具、客户端配置、活动和权限治理状态。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, cast

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from merchpilot.api.dependencies import get_current_identity, require_mcp_operator
from merchpilot.api.schemas import (
    McpActivityPage,
    McpActivityRead,
    McpIntegrationRead,
    McpToolRead,
    McpVerificationRead,
)
from merchpilot.core.config import Settings, get_settings
from merchpilot.infrastructure.database import get_db_session
from merchpilot.infrastructure.models import (
    ApprovalTask,
    AuditEvent,
    IdempotencyRecord,
    PlanningProject,
    PlanningRun,
    ProductInitiative,
    ProductLaunchReview,
)
from merchpilot.ports.identity import Identity

router = APIRouter(prefix="/integrations/mcp", tags=["mcp-integration"])

MCP_PROTOCOL_VERSION = "2025-11-25"
MCP_SERVICE_NAME = "MerchPilot Enterprise MCP"
MCP_SERVICE_VERSION = "0.9.0"


def _string_list(value: object) -> list[str]:
    """内部辅助函数`_string_list`；拆分主流程并集中处理当前模块的边界条件。"""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if item is not None]


def _decode_mcp_payload(response: httpx.Response) -> dict[str, Any]:
    """内部辅助函数`_decode_mcp_payload`；拆分主流程并集中处理当前模块的边界条件。"""
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" not in content_type:
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("MCP 返回了非预期的数据结构")
        return payload
    for line in response.text.splitlines():
        if not line.startswith("data:"):
            continue
        payload = json.loads(line.removeprefix("data:").strip())
        if isinstance(payload, dict):
            return payload
    raise ValueError("MCP 未返回有效的协议消息")


def _mcp_token(
    authorization: str | None,
    identity: Identity,
    settings: Settings,
) -> str:
    """内部辅助函数`_mcp_token`；拆分主流程并集中处理当前模块的边界条件。"""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token:
            return token
    if settings.auth_mode.strip().lower() == "local":
        profile = next(
            (role for role in identity.roles if role in settings.local_auth_profile_list),
            settings.local_auth_profile_list[0],
        )
        return f"local-profile:{profile}"
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="当前登录凭证不能转交给 MCP，请重新登录后再验证",
    )


async def _probe_mcp_health(settings: Settings) -> tuple[bool, dict[str, Any]]:
    """内部辅助函数`_probe_mcp_health`；拆分主流程并集中处理当前模块的边界条件。"""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{settings.mcp_internal_base_url.rstrip('/')}/health")
        response.raise_for_status()
        payload = response.json()
        return payload.get("status") == "ok", payload
    except (httpx.HTTPError, ValueError):
        return False, {}


async def _mcp_request(
    settings: Settings,
    token: str,
    method: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """内部辅助函数`_mcp_request`；拆分主流程并集中处理当前模块的边界条件。"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
    }
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    async with httpx.AsyncClient(timeout=settings.mcp_request_timeout_seconds) as client:
        response = await client.post(
            f"{settings.mcp_internal_base_url.rstrip('/')}{settings.mcp_path}",
            headers=headers,
            json=payload,
        )
    response.raise_for_status()
    message = _decode_mcp_payload(response)
    if "error" in message:
        error = message.get("error")
        detail = error.get("message") if isinstance(error, dict) else str(error)
        raise RuntimeError(detail or "MCP 请求失败")
    result = message.get("result")
    if not isinstance(result, dict):
        raise ValueError("MCP 返回结果为空")
    return result


def _tool_read(payload: dict[str, Any]) -> McpToolRead:
    """内部辅助函数`_tool_read`；拆分主流程并集中处理当前模块的边界条件。"""
    annotations_value = payload.get("annotations")
    annotations: dict[str, Any] = annotations_value if isinstance(annotations_value, dict) else {}
    input_schema_value = payload.get("inputSchema")
    input_schema: dict[str, Any] = (
        input_schema_value if isinstance(input_schema_value, dict) else {}
    )
    properties_value = input_schema.get("properties")
    properties: dict[str, Any] = properties_value if isinstance(properties_value, dict) else {}
    page_size_value = properties.get("page_size")
    page_size: dict[str, Any] = page_size_value if isinstance(page_size_value, dict) else {}
    metadata_value = payload.get("_meta")
    metadata: dict[str, Any] = metadata_value if isinstance(metadata_value, dict) else {}
    fastmcp_metadata_value = metadata.get("fastmcp")
    fastmcp_metadata: dict[str, Any] = (
        fastmcp_metadata_value if isinstance(fastmcp_metadata_value, dict) else {}
    )
    return McpToolRead(
        name=str(payload.get("name") or ""),
        title=str(payload.get("title") or payload.get("name") or ""),
        description=str(payload.get("description") or ""),
        tags=[str(tag) for tag in fastmcp_metadata.get("tags", [])],
        read_only=bool(annotations.get("readOnlyHint")),
        destructive=bool(annotations.get("destructiveHint")),
        idempotent=bool(annotations.get("idempotentHint")),
        required_fields=[str(field) for field in input_schema.get("required", [])],
        max_page_size=page_size.get("maximum") if isinstance(page_size.get("maximum"), int) else None,
    )


def _structured_tool_result(result: dict[str, Any]) -> dict[str, Any]:
    """内部辅助函数`_structured_tool_result`；拆分主流程并集中处理当前模块的边界条件。"""
    if result.get("isError") is True:
        raise RuntimeError("MCP 工具执行失败")
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    for content in result.get("content", []):
        if not isinstance(content, dict) or content.get("type") != "text":
            continue
        try:
            payload = json.loads(str(content.get("text") or ""))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise ValueError("MCP 工具未返回结构化业务数据")


def _client_configuration(settings: Settings, identity: Identity) -> dict[str, Any]:
    """内部辅助函数`_client_configuration`；拆分主流程并集中处理当前模块的边界条件。"""
    if settings.auth_mode.strip().lower() == "local":
        profile = next(
            (role for role in identity.roles if role in settings.local_auth_profile_list),
            settings.local_auth_profile_list[0],
        )
        credential = f"local-profile:{profile}"
    else:
        credential = "<MerchPilot access token>"
    return {
        "mcpServers": {
            "merchpilot": {
                "url": f"{settings.mcp_public_base_url.rstrip('/')}{settings.mcp_path}",
                "headers": {"Authorization": f"Bearer {credential}"},
            }
        }
    }


@router.get("/activities", response_model=McpActivityPage)
async def list_mcp_activities(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=20)] = 5,
    identity: Identity = Depends(require_mcp_operator),
    session: AsyncSession = Depends(get_db_session),
) -> McpActivityPage:
    """合并FastMCP调用与业务审计事件，生成可分页追溯的集成活动。"""
    mcp_events = union_all(
        select(
            IdempotencyRecord.id.label("activity_id"),
            IdempotencyRecord.resource_id.label("project_id"),
            IdempotencyRecord.idempotency_key.label("request_id"),
            IdempotencyRecord.actor_id.label("actor_id"),
            IdempotencyRecord.created_at.label("activity_at"),
            literal("mcp_created").label("activity_type"),
            literal(0).label("activity_priority"),
            literal(0).label("activity_sequence"),
        ).where(
            IdempotencyRecord.tenant_id == identity.tenant_id,
            IdempotencyRecord.operation == "planning_project.create",
            IdempotencyRecord.client_name == "fastmcp",
            IdempotencyRecord.resource_type == "planning_project",
        ),
        select(
            IdempotencyRecord.id.label("activity_id"),
            PlanningRun.project_id.label("project_id"),
            IdempotencyRecord.idempotency_key.label("request_id"),
            IdempotencyRecord.actor_id.label("actor_id"),
            IdempotencyRecord.created_at.label("activity_at"),
            literal("mcp_started").label("activity_type"),
            literal(1).label("activity_priority"),
            literal(0).label("activity_sequence"),
        )
        .select_from(IdempotencyRecord)
        .join(PlanningRun, PlanningRun.id == IdempotencyRecord.resource_id)
        .join(PlanningProject, PlanningProject.id == PlanningRun.project_id)
        .where(
            IdempotencyRecord.tenant_id == identity.tenant_id,
            IdempotencyRecord.operation == "planning_run.start",
            IdempotencyRecord.client_name == "fastmcp",
            IdempotencyRecord.resource_type == "planning_run",
            PlanningProject.tenant_id == identity.tenant_id,
        ),
        select(
            IdempotencyRecord.id.label("activity_id"),
            ApprovalTask.project_id.label("project_id"),
            IdempotencyRecord.idempotency_key.label("request_id"),
            IdempotencyRecord.actor_id.label("actor_id"),
            IdempotencyRecord.created_at.label("activity_at"),
            literal("mcp_approval_claimed").label("activity_type"),
            literal(2).label("activity_priority"),
            literal(0).label("activity_sequence"),
        )
        .select_from(IdempotencyRecord)
        .join(ApprovalTask, ApprovalTask.id == IdempotencyRecord.resource_id)
        .join(PlanningProject, PlanningProject.id == ApprovalTask.project_id)
        .where(
            IdempotencyRecord.tenant_id == identity.tenant_id,
            IdempotencyRecord.operation == "approval_task.claim",
            IdempotencyRecord.client_name == "fastmcp",
            IdempotencyRecord.resource_type == "approval_task",
            PlanningProject.tenant_id == identity.tenant_id,
        ),
        select(
            AuditEvent.id.label("activity_id"),
            AuditEvent.project_id.label("project_id"),
            AuditEvent.detail["decision_request_id"].as_string().label("request_id"),
            AuditEvent.actor_id.label("actor_id"),
            AuditEvent.occurred_at.label("activity_at"),
            literal("mcp_approval_decided").label("activity_type"),
            literal(3).label("activity_priority"),
            AuditEvent.sequence_no.label("activity_sequence"),
        ).where(
            AuditEvent.tenant_id == identity.tenant_id,
            AuditEvent.project_id.is_not(None),
            AuditEvent.entity_type == "approval_task",
            AuditEvent.action.in_(
                {"approval.approved", "approval.rejected", "approval.revision_required"}
            ),
            AuditEvent.detail["client"].as_string() == "fastmcp",
        ),
        select(
            AuditEvent.id.label("activity_id"),
            AuditEvent.project_id.label("project_id"),
            AuditEvent.detail["idempotency_key"].as_string().label("request_id"),
            AuditEvent.actor_id.label("actor_id"),
            AuditEvent.occurred_at.label("activity_at"),
            literal("mcp_validation_updated").label("activity_type"),
            literal(4).label("activity_priority"),
            AuditEvent.sequence_no.label("activity_sequence"),
        ).where(
            AuditEvent.tenant_id == identity.tenant_id,
            AuditEvent.project_id.is_not(None),
            AuditEvent.entity_type == "planning_run",
            AuditEvent.action == "planning_validation.updated",
            AuditEvent.detail["client"].as_string() == "fastmcp",
        ),
        select(
            IdempotencyRecord.id.label("activity_id"),
            ProductInitiative.project_id.label("project_id"),
            IdempotencyRecord.idempotency_key.label("request_id"),
            IdempotencyRecord.actor_id.label("actor_id"),
            IdempotencyRecord.created_at.label("activity_at"),
            literal("mcp_launch_review_submitted").label("activity_type"),
            literal(5).label("activity_priority"),
            literal(0).label("activity_sequence"),
        )
        .select_from(IdempotencyRecord)
        .join(ProductLaunchReview, ProductLaunchReview.id == IdempotencyRecord.resource_id)
        .join(ProductInitiative, ProductInitiative.id == ProductLaunchReview.initiative_id)
        .join(PlanningProject, PlanningProject.id == ProductInitiative.project_id)
        .where(
            IdempotencyRecord.tenant_id == identity.tenant_id,
            IdempotencyRecord.operation == "product_launch_review.submit",
            IdempotencyRecord.client_name == "fastmcp",
            IdempotencyRecord.resource_type == "product_launch_review",
            ProductLaunchReview.tenant_id == identity.tenant_id,
            ProductInitiative.tenant_id == identity.tenant_id,
            PlanningProject.tenant_id == identity.tenant_id,
        ),
    ).subquery()
    ranked_events = (
        select(
            mcp_events,
            func.row_number()
            .over(
                partition_by=mcp_events.c.project_id,
                order_by=(
                    mcp_events.c.activity_at.desc(),
                    mcp_events.c.activity_priority.desc(),
                    mcp_events.c.activity_sequence.desc(),
                    mcp_events.c.activity_id.desc(),
                ),
            )
            .label("row_number"),
        )
    ).subquery()
    total = int(
        await session.scalar(
            select(func.count(ranked_events.c.project_id))
            .select_from(ranked_events)
            .join(PlanningProject, PlanningProject.id == ranked_events.c.project_id)
            .where(
                ranked_events.c.row_number == 1,
                PlanningProject.tenant_id == identity.tenant_id,
            )
        )
        or 0
    )
    event_rows = (
        await session.execute(
            select(ranked_events)
            .join(PlanningProject, PlanningProject.id == ranked_events.c.project_id)
            .where(
                ranked_events.c.row_number == 1,
                PlanningProject.tenant_id == identity.tenant_id,
            )
            .order_by(
                ranked_events.c.activity_at.desc(),
                ranked_events.c.activity_priority.desc(),
                ranked_events.c.activity_sequence.desc(),
                ranked_events.c.activity_id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).mappings().all()
    project_ids = [str(row["project_id"]) for row in event_rows]
    projects = list(
        await session.scalars(
            select(PlanningProject).where(
                PlanningProject.tenant_id == identity.tenant_id,
                PlanningProject.id.in_(project_ids),
            )
        )
    )
    project_by_id = {project.id: project for project in projects}
    latest_creation_by_project: dict[str, dict[str, Any]] = {}
    latest_start_by_project: dict[str, dict[str, Any]] = {}
    latest_approval_by_project: dict[str, dict[str, Any]] = {}
    latest_validation_by_project: dict[str, dict[str, Any]] = {}
    latest_launch_review_by_project: dict[str, dict[str, Any]] = {}
    if project_ids:
        ranked_creations = (
            select(
                IdempotencyRecord.resource_id.label("project_id"),
                IdempotencyRecord.idempotency_key.label("request_id"),
                IdempotencyRecord.actor_id.label("actor_id"),
                IdempotencyRecord.created_at.label("created_at"),
                func.row_number()
                .over(
                    partition_by=IdempotencyRecord.resource_id,
                    order_by=(IdempotencyRecord.created_at.desc(), IdempotencyRecord.id.desc()),
                )
                .label("row_number"),
            )
            .where(
                IdempotencyRecord.tenant_id == identity.tenant_id,
                IdempotencyRecord.operation == "planning_project.create",
                IdempotencyRecord.client_name == "fastmcp",
                IdempotencyRecord.resource_type == "planning_project",
                IdempotencyRecord.resource_id.in_(project_ids),
            )
            .subquery()
        )
        creation_rows = (
            await session.execute(
                select(ranked_creations).where(ranked_creations.c.row_number == 1)
            )
        ).mappings()
        latest_creation_by_project = {
            str(row["project_id"]): {
                "request_id": str(row["request_id"]),
                "actor_id": str(row["actor_id"]),
                "created_at": row["created_at"],
            }
            for row in creation_rows
        }
        ranked_starts = (
            select(
                PlanningRun.project_id.label("project_id"),
                PlanningRun.id.label("run_id"),
                PlanningRun.status.label("run_status"),
                IdempotencyRecord.idempotency_key.label("request_id"),
                IdempotencyRecord.actor_id.label("actor_id"),
                IdempotencyRecord.created_at.label("started_at"),
                func.row_number()
                .over(
                    partition_by=PlanningRun.project_id,
                    order_by=(IdempotencyRecord.created_at.desc(), IdempotencyRecord.id.desc()),
                )
                .label("row_number"),
            )
            .select_from(IdempotencyRecord)
            .join(PlanningRun, PlanningRun.id == IdempotencyRecord.resource_id)
            .join(PlanningProject, PlanningProject.id == PlanningRun.project_id)
            .where(
                IdempotencyRecord.tenant_id == identity.tenant_id,
                IdempotencyRecord.operation == "planning_run.start",
                IdempotencyRecord.client_name == "fastmcp",
                IdempotencyRecord.resource_type == "planning_run",
                PlanningProject.tenant_id == identity.tenant_id,
                PlanningRun.project_id.in_(project_ids),
            )
            .subquery()
        )
        latest_rows = (
            await session.execute(
                select(ranked_starts).where(ranked_starts.c.row_number == 1)
            )
        ).mappings()
        latest_start_by_project = {
            str(row["project_id"]): {
                "request_id": str(row["request_id"]),
                "actor_id": str(row["actor_id"]),
                "started_at": row["started_at"],
                "run_id": str(row["run_id"]),
                "run_status": str(row["run_status"]),
            }
            for row in latest_rows
        }
        approval_events = union_all(
            select(
                ApprovalTask.project_id.label("project_id"),
                ApprovalTask.id.label("task_id"),
                ApprovalTask.status.label("approval_status"),
                IdempotencyRecord.idempotency_key.label("request_id"),
                IdempotencyRecord.actor_id.label("actor_id"),
                IdempotencyRecord.created_at.label("event_at"),
                literal("claimed").label("approval_event"),
                IdempotencyRecord.id.label("event_id"),
                literal(0).label("event_priority"),
            )
            .select_from(IdempotencyRecord)
            .join(ApprovalTask, ApprovalTask.id == IdempotencyRecord.resource_id)
            .join(PlanningProject, PlanningProject.id == ApprovalTask.project_id)
            .where(
                IdempotencyRecord.tenant_id == identity.tenant_id,
                IdempotencyRecord.operation == "approval_task.claim",
                IdempotencyRecord.client_name == "fastmcp",
                IdempotencyRecord.resource_type == "approval_task",
                PlanningProject.tenant_id == identity.tenant_id,
                ApprovalTask.project_id.in_(project_ids),
            ),
            select(
                ApprovalTask.project_id.label("project_id"),
                ApprovalTask.id.label("task_id"),
                ApprovalTask.status.label("approval_status"),
                AuditEvent.detail["decision_request_id"].as_string().label("request_id"),
                AuditEvent.actor_id.label("actor_id"),
                AuditEvent.occurred_at.label("event_at"),
                func.replace(AuditEvent.action, "approval.", "").label("approval_event"),
                AuditEvent.id.label("event_id"),
                literal(1).label("event_priority"),
            )
            .select_from(AuditEvent)
            .join(ApprovalTask, ApprovalTask.id == AuditEvent.entity_id)
            .join(PlanningProject, PlanningProject.id == ApprovalTask.project_id)
            .where(
                AuditEvent.tenant_id == identity.tenant_id,
                AuditEvent.entity_type == "approval_task",
                AuditEvent.action.in_(
                    {"approval.approved", "approval.rejected", "approval.revision_required"}
                ),
                AuditEvent.detail["client"].as_string() == "fastmcp",
                PlanningProject.tenant_id == identity.tenant_id,
                ApprovalTask.project_id.in_(project_ids),
            ),
        ).subquery()
        ranked_approvals = (
            select(
                approval_events,
                func.row_number()
                .over(
                    partition_by=approval_events.c.project_id,
                    order_by=(
                        approval_events.c.event_at.desc(),
                        approval_events.c.event_priority.desc(),
                        approval_events.c.event_id.desc(),
                    ),
                )
                .label("row_number"),
            )
        ).subquery()
        approval_rows = (
            await session.execute(
                select(ranked_approvals).where(ranked_approvals.c.row_number == 1)
            )
        ).mappings()
        latest_approval_by_project = {
            str(row["project_id"]): {
                "request_id": str(row["request_id"]),
                "actor_id": str(row["actor_id"]),
                "event_at": row["event_at"],
                "task_id": str(row["task_id"]),
                "approval_event": str(row["approval_event"]),
                "approval_status": str(row["approval_status"]),
            }
            for row in approval_rows
        }
        ranked_validations = (
            select(
                AuditEvent.project_id.label("project_id"),
                AuditEvent.entity_id.label("run_id"),
                AuditEvent.detail["idempotency_key"].as_string().label("request_id"),
                AuditEvent.actor_id.label("actor_id"),
                AuditEvent.occurred_at.label("event_at"),
                AuditEvent.detail["candidate_id"].as_string().label("candidate_id"),
                AuditEvent.detail["gate_ids"].label("gate_ids"),
                AuditEvent.detail["validation_status"].as_string().label(
                    "validation_status"
                ),
                AuditEvent.detail["completion_rate"].as_integer().label(
                    "completion_rate"
                ),
                func.row_number()
                .over(
                    partition_by=AuditEvent.project_id,
                    order_by=(AuditEvent.occurred_at.desc(), AuditEvent.sequence_no.desc()),
                )
                .label("row_number"),
            )
            .where(
                AuditEvent.tenant_id == identity.tenant_id,
                AuditEvent.project_id.in_(project_ids),
                AuditEvent.entity_type == "planning_run",
                AuditEvent.action == "planning_validation.updated",
                AuditEvent.detail["client"].as_string() == "fastmcp",
            )
            .subquery()
        )
        validation_rows = (
            await session.execute(
                select(ranked_validations).where(ranked_validations.c.row_number == 1)
            )
        ).mappings()
        latest_validation_by_project = {
            str(row["project_id"]): {
                "request_id": (
                    str(row["request_id"]) if row["request_id"] is not None else None
                ),
                "actor_id": str(row["actor_id"]) if row["actor_id"] is not None else None,
                "event_at": row["event_at"],
                "run_id": str(row["run_id"]) if row["run_id"] is not None else None,
                "candidate_id": (
                    str(row["candidate_id"])
                    if row["candidate_id"] is not None
                    else None
                ),
                "gate_ids": _string_list(row["gate_ids"]),
                "validation_status": (
                    str(row["validation_status"])
                    if row["validation_status"] is not None
                    else None
                ),
                "completion_rate": (
                    int(row["completion_rate"])
                    if row["completion_rate"] is not None
                    else None
                ),
            }
            for row in validation_rows
        }
        ranked_launch_reviews = (
            select(
                ProductInitiative.project_id.label("project_id"),
                ProductInitiative.id.label("initiative_id"),
                ProductInitiative.name.label("initiative_name"),
                ProductLaunchReview.id.label("review_id"),
                ProductLaunchReview.status.label("review_status"),
                ProductLaunchReview.readiness_snapshot["readiness_status"]
                .as_string()
                .label("readiness_status"),
                IdempotencyRecord.idempotency_key.label("request_id"),
                IdempotencyRecord.actor_id.label("actor_id"),
                IdempotencyRecord.created_at.label("event_at"),
                func.row_number()
                .over(
                    partition_by=ProductInitiative.project_id,
                    order_by=(
                        IdempotencyRecord.created_at.desc(),
                        IdempotencyRecord.id.desc(),
                    ),
                )
                .label("row_number"),
            )
            .select_from(IdempotencyRecord)
            .join(ProductLaunchReview, ProductLaunchReview.id == IdempotencyRecord.resource_id)
            .join(ProductInitiative, ProductInitiative.id == ProductLaunchReview.initiative_id)
            .join(PlanningProject, PlanningProject.id == ProductInitiative.project_id)
            .where(
                IdempotencyRecord.tenant_id == identity.tenant_id,
                IdempotencyRecord.operation == "product_launch_review.submit",
                IdempotencyRecord.client_name == "fastmcp",
                IdempotencyRecord.resource_type == "product_launch_review",
                ProductLaunchReview.tenant_id == identity.tenant_id,
                ProductInitiative.tenant_id == identity.tenant_id,
                PlanningProject.tenant_id == identity.tenant_id,
                ProductInitiative.project_id.in_(project_ids),
            )
            .subquery()
        )
        launch_review_rows = (
            await session.execute(
                select(ranked_launch_reviews).where(ranked_launch_reviews.c.row_number == 1)
            )
        ).mappings()
        latest_launch_review_by_project = {
            str(row["project_id"]): {
                "request_id": str(row["request_id"]),
                "actor_id": str(row["actor_id"]),
                "event_at": row["event_at"],
                "initiative_id": str(row["initiative_id"]),
                "initiative_name": str(row["initiative_name"]),
                "review_id": str(row["review_id"]),
                "review_status": str(row["review_status"]),
                "readiness_status": (
                    str(row["readiness_status"])
                    if row["readiness_status"] is not None
                    else None
                ),
            }
            for row in launch_review_rows
        }
    return McpActivityPage(
        items=[
            McpActivityRead(
                id=str(row["activity_id"]),
                activity_type=cast(
                    Literal[
                        "mcp_created",
                        "mcp_started",
                        "mcp_approval_claimed",
                        "mcp_approval_decided",
                        "mcp_validation_updated",
                        "mcp_launch_review_submitted",
                    ],
                    str(row["activity_type"]),
                ),
                request_id=str(row["request_id"]),
                actor_id=str(row["actor_id"]),
                project_id=project_by_id[str(row["project_id"])].id,
                project_name=project_by_id[str(row["project_id"])].name,
                category=project_by_id[str(row["project_id"])].category,
                target_market=project_by_id[str(row["project_id"])].target_market,
                project_status=project_by_id[str(row["project_id"])].status,
                created_at=row["activity_at"],
                project_created_by=project_by_id[str(row["project_id"])].created_by,
                project_created_at=project_by_id[str(row["project_id"])].created_at,
                mcp_creation_request_id=(
                    latest_creation_by_project.get(str(row["project_id"])) or {}
                ).get("request_id"),
                mcp_creation_actor_id=(
                    latest_creation_by_project.get(str(row["project_id"])) or {}
                ).get("actor_id"),
                mcp_created_at=(
                    latest_creation_by_project.get(str(row["project_id"])) or {}
                ).get("created_at"),
                latest_start_request_id=(
                    latest_start_by_project.get(str(row["project_id"])) or {}
                ).get(
                    "request_id"
                ),
                latest_start_actor_id=(
                    latest_start_by_project.get(str(row["project_id"])) or {}
                ).get("actor_id"),
                latest_start_at=(
                    latest_start_by_project.get(str(row["project_id"])) or {}
                ).get("started_at"),
                latest_run_id=(latest_start_by_project.get(str(row["project_id"])) or {}).get(
                    "run_id"
                ),
                latest_run_status=(
                    latest_start_by_project.get(str(row["project_id"])) or {}
                ).get("run_status"),
                latest_approval_request_id=(
                    latest_approval_by_project.get(str(row["project_id"])) or {}
                ).get("request_id"),
                latest_approval_actor_id=(
                    latest_approval_by_project.get(str(row["project_id"])) or {}
                ).get("actor_id"),
                latest_approval_at=(
                    latest_approval_by_project.get(str(row["project_id"])) or {}
                ).get("event_at"),
                latest_approval_task_id=(
                    latest_approval_by_project.get(str(row["project_id"])) or {}
                ).get("task_id"),
                latest_approval_event=(
                    latest_approval_by_project.get(str(row["project_id"])) or {}
                ).get("approval_event"),
                latest_approval_status=(
                    latest_approval_by_project.get(str(row["project_id"])) or {}
                ).get("approval_status"),
                latest_validation_request_id=(
                    latest_validation_by_project.get(str(row["project_id"])) or {}
                ).get("request_id"),
                latest_validation_actor_id=(
                    latest_validation_by_project.get(str(row["project_id"])) or {}
                ).get("actor_id"),
                latest_validation_at=(
                    latest_validation_by_project.get(str(row["project_id"])) or {}
                ).get("event_at"),
                latest_validation_run_id=(
                    latest_validation_by_project.get(str(row["project_id"])) or {}
                ).get("run_id"),
                latest_validation_candidate_id=(
                    latest_validation_by_project.get(str(row["project_id"])) or {}
                ).get("candidate_id"),
                latest_validation_gate_ids=(
                    latest_validation_by_project.get(str(row["project_id"])) or {}
                ).get("gate_ids", []),
                latest_validation_status=(
                    latest_validation_by_project.get(str(row["project_id"])) or {}
                ).get("validation_status"),
                latest_validation_completion_rate=(
                    latest_validation_by_project.get(str(row["project_id"])) or {}
                ).get("completion_rate"),
                latest_launch_review_request_id=(
                    latest_launch_review_by_project.get(str(row["project_id"])) or {}
                ).get("request_id"),
                latest_launch_review_actor_id=(
                    latest_launch_review_by_project.get(str(row["project_id"])) or {}
                ).get("actor_id"),
                latest_launch_review_at=(
                    latest_launch_review_by_project.get(str(row["project_id"])) or {}
                ).get("event_at"),
                latest_launch_review_initiative_id=(
                    latest_launch_review_by_project.get(str(row["project_id"])) or {}
                ).get("initiative_id"),
                latest_launch_review_initiative_name=(
                    latest_launch_review_by_project.get(str(row["project_id"])) or {}
                ).get("initiative_name"),
                latest_launch_review_id=(
                    latest_launch_review_by_project.get(str(row["project_id"])) or {}
                ).get("review_id"),
                latest_launch_review_status=(
                    latest_launch_review_by_project.get(str(row["project_id"])) or {}
                ).get("review_status"),
                latest_launch_review_readiness_status=(
                    latest_launch_review_by_project.get(str(row["project_id"])) or {}
                ).get("readiness_status"),
            )
            for row in event_rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("", response_model=McpIntegrationRead)
async def get_mcp_integration(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=12)] = 6,
    authorization: Annotated[str | None, Header()] = None,
    identity: Identity = Depends(get_current_identity),
) -> McpIntegrationRead:
    """处理`GET `接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    settings = get_settings()
    health_ready, health_payload = await _probe_mcp_health(settings)
    tools: list[McpToolRead] = []
    authenticated = False
    error: str | None = None
    if health_ready:
        try:
            token = _mcp_token(authorization, identity, settings)
            result = await _mcp_request(settings, token, "tools/list")
            tools = [
                _tool_read(tool)
                for tool in result.get("tools", [])
                if isinstance(tool, dict) and tool.get("name")
            ]
            authenticated = True
        except (HTTPException, httpx.HTTPError, RuntimeError, ValueError) as exc:
            error = exc.detail if isinstance(exc, HTTPException) else str(exc)
    elif not health_ready:
        error = "FastMCP 服务未启动或健康检查失败"
    total = len(tools)
    read_only_total = sum(tool.read_only for tool in tools)
    controlled_write_total = total - read_only_total
    offset = (page - 1) * page_size
    integration_status: Literal["ready", "degraded", "unavailable"]
    if health_ready and authenticated:
        integration_status = "ready"
    elif health_ready:
        integration_status = "degraded"
    else:
        integration_status = "unavailable"
    return McpIntegrationRead(
        status=integration_status,
        health_ready=health_ready,
        authenticated=authenticated,
        service_name=str(health_payload.get("service") or MCP_SERVICE_NAME),
        service_version=str(health_payload.get("version") or MCP_SERVICE_VERSION),
        protocol_version=MCP_PROTOCOL_VERSION,
        endpoint=f"{settings.mcp_public_base_url.rstrip('/')}{settings.mcp_path}",
        auth_mode=settings.auth_mode,
        user_id=identity.user_id,
        tenant_id=identity.tenant_id,
        roles=list(identity.roles),
        tools=tools[offset : offset + page_size],
        total=total,
        read_only_total=read_only_total,
        controlled_write_total=controlled_write_total,
        page=page,
        page_size=page_size,
        client_configuration=_client_configuration(settings, identity),
        error=error,
    )


@router.post("/verify", response_model=McpVerificationRead)
async def verify_mcp_integration(
    authorization: Annotated[str | None, Header()] = None,
    identity: Identity = Depends(get_current_identity),
) -> McpVerificationRead:
    """处理`POST /verify`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    settings = get_settings()
    try:
        token = _mcp_token(authorization, identity, settings)
        result = await _mcp_request(
            settings,
            token,
            "tools/call",
            {"name": "get_business_dashboard", "arguments": {}},
        )
        dashboard = _structured_tool_result(result)
    except HTTPException:
        raise
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"MCP 当前身份验证失败：{exc}",
        ) from exc
    return McpVerificationRead(
        status="verified",
        verified_at=datetime.now(UTC),
        tool_name="get_business_dashboard",
        user_id=identity.user_id,
        tenant_id=identity.tenant_id,
        roles=list(identity.roles),
        project_total=int(dashboard.get("project_total") or 0),
        active_project_total=int(dashboard.get("active_project_total") or 0),
        pending_approval_total=int(dashboard.get("pending_approval_count") or 0)
        + int(dashboard.get("pending_launch_review_count") or 0),
        selected_product_total=int(dashboard.get("selected_product_total") or 0),
        active_initiative_total=int(dashboard.get("active_initiative_total") or 0),
    )
