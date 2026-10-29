"""文件职责：注册 FastMCP 工具，将现有业务能力以可审计、受门禁的方式开放。"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AuthContext
from fastmcp.utilities.authorization import AuthCheck
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from merchpilot.core.config import get_settings
from merchpilot.mcp.api_client import request_api, request_api_with_metadata
from merchpilot.mcp.auth import MerchPilotTokenVerifier
from merchpilot.services.approval_guard import approval_review_fingerprint
from merchpilot.services.project_guard import project_configuration_fingerprint
from merchpilot.services.validation_guard import validation_review_fingerprint

settings = get_settings()
read_only_annotations = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}
controlled_write_annotations = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}
BusinessId = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"),
]


def planning_write_role(context: AuthContext) -> bool:
    """实现FastMCP的`planning_write_role`流程，并保持鉴权、确认门禁和错误转换一致。"""
    if context.token is None:
        return False
    roles = context.token.claims.get("roles", [])
    if isinstance(roles, str):
        roles = [roles]
    return bool({"admin", "planner"}.intersection(str(role) for role in roles))


planning_write_auth: AuthCheck = planning_write_role


def approval_role(context: AuthContext) -> bool:
    """实现FastMCP的`approval_role`流程，并保持鉴权、确认门禁和错误转换一致。"""
    if context.token is None:
        return False
    roles = context.token.claims.get("roles", [])
    if isinstance(roles, str):
        roles = [roles]
    return bool({"admin", "approver"}.intersection(str(role) for role in roles))


approval_auth: AuthCheck = approval_role

mcp = FastMCP(
    name="MerchPilot Enterprise MCP",
    version="0.9.0",
    instructions=(
        "查询当前身份可访问的商品规划、选品、审批、证据与商品立项数据；"
        "admin/planner 还可以幂等创建规划草稿，并在复核最新配置后明确确认启动 Agent。"
        "admin/planner 可以在复核最新清单后单项更新验证门禁，标记通过前必须已有人工材料。"
        "admin/planner 可以读取上市评审上下文，并在复核最新状态后提交待人工审批的上市评审。"
        "admin/approver 可以认领审批任务，并在复核最新任务后明确确认提交线上审批决定。"
        "所有列表工具均为服务端分页，禁止假设能够访问其他租户的数据。"
        "创建草稿不会自动启动；启动工具也不会自动审批、生成正式选品或修改商品立项状态。"
    ),
    auth=MerchPilotTokenVerifier(base_url=settings.mcp_public_base_url),
    mask_error_details=True,
)


@mcp.tool(annotations=read_only_annotations, tags={"planning", "readonly"})
async def list_planning_projects(
    page: Annotated[int, Field(ge=1)] = 1,
    page_size: Annotated[int, Field(ge=1, le=50)] = 8,
    status: str | None = None,
    keyword: str | None = None,
    project_id: BusinessId | None = None,
    archived_only: bool = False,
) -> dict[str, Any]:
    """分页查询当前租户的规划项目和状态汇总。"""
    result = await request_api(
        "GET",
        "/planning-projects/page",
        params={
            "page": page,
            "page_size": page_size,
            "status": status,
            "keyword": keyword,
            "project_id": project_id,
            "archived_only": archived_only,
        },
    )
    for item in result.get("items", []):
        if not isinstance(item, dict):
            continue
        constraints_value = item.get("constraints")
        item_constraints: dict[str, Any] = (
            constraints_value if isinstance(constraints_value, dict) else {}
        )
        item["review_token"] = project_configuration_fingerprint(
            name=str(item.get("name") or ""),
            category=str(item.get("category") or ""),
            target_market=str(item.get("target_market") or ""),
            constraints=item_constraints,
        )
    return result


@mcp.tool(
    annotations=controlled_write_annotations,
    tags={"planning", "controlled-write", "idempotent"},
    auth=planning_write_auth,
)
async def create_planning_project_draft(
    request_id: Annotated[
        str,
        Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"),
    ],
    name: Annotated[str, Field(min_length=2, max_length=255)],
    category: Annotated[str, Field(min_length=1, max_length=128)],
    target_market: Annotated[str, Field(min_length=1, max_length=128)],
    target_user: Annotated[str | None, Field(max_length=255)] = None,
    target_margin: Annotated[float | None, Field(ge=0, le=1)] = None,
    min_price: Annotated[float | None, Field(ge=0)] = None,
    max_price: Annotated[float | None, Field(ge=0)] = None,
    unit_cost: Annotated[float | None, Field(ge=0)] = None,
    logistics_cost: Annotated[float | None, Field(ge=0)] = None,
    platform_fee_rate: Annotated[float | None, Field(ge=0, le=1)] = None,
    tax_rate: Annotated[float | None, Field(ge=0, le=1)] = None,
    marketing_rate: Annotated[float | None, Field(ge=0, le=1)] = None,
    fixed_cost: Annotated[float | None, Field(ge=0)] = None,
    forecast_units: Annotated[int | None, Field(ge=1)] = None,
    supplier_name: Annotated[str | None, Field(max_length=255)] = None,
    moq: Annotated[int | None, Field(ge=1)] = None,
    lead_time_days: Annotated[int | None, Field(ge=1)] = None,
    max_lead_time_days: Annotated[int | None, Field(ge=1)] = None,
) -> dict[str, Any]:
    """幂等创建规划草稿；不会自动启动 Agent、提交审批或修改后续商品状态。"""
    if (min_price is None) != (max_price is None):
        raise ToolError("最低价和最高价必须同时提供")
    if min_price is not None and max_price is not None and min_price > max_price:
        raise ToolError("最低价不能高于最高价")
    if (
        lead_time_days is not None
        and max_lead_time_days is not None
        and lead_time_days > max_lead_time_days
    ):
        raise ToolError("预计交期不能超过最长可接受交期")
    constraints: dict[str, Any] = {}
    optional_constraints = {
        "target_user": target_user.strip() if target_user else None,
        "target_margin": target_margin,
        "unit_cost": unit_cost,
        "logistics_cost": logistics_cost,
        "platform_fee_rate": platform_fee_rate,
        "tax_rate": tax_rate,
        "marketing_rate": marketing_rate,
        "fixed_cost": fixed_cost,
        "forecast_units": forecast_units,
        "supplier_name": supplier_name.strip() if supplier_name else None,
        "moq": moq,
        "lead_time_days": lead_time_days,
        "max_lead_time_days": max_lead_time_days,
    }
    constraints.update({key: value for key, value in optional_constraints.items() if value is not None})
    if min_price is not None and max_price is not None:
        constraints["price_range"] = {"min": min_price, "max": max_price}
    result = await request_api_with_metadata(
        "POST",
        "/planning-projects",
        json={
            "name": name.strip(),
            "category": category.strip(),
            "target_market": target_market.strip(),
            "constraints": constraints,
        },
        idempotency_key=request_id,
    )
    return {
        "project": result.data,
        "created_as": "draft",
        "review_token": project_configuration_fingerprint(
            name=str(result.data.get("name") or name.strip()),
            category=str(result.data.get("category") or category.strip()),
            target_market=str(result.data.get("target_market") or target_market.strip()),
            constraints=(
                result.data["constraints"]
                if isinstance(result.data.get("constraints"), dict)
                else constraints
            ),
        ),
        "next_action": "请在规划执行页面复核约束后，由规划人员手动启动 Multi-Agent 运行。",
        "automatic_actions": [],
        "idempotency_key": request_id,
        "replayed": result.headers.get("idempotency-replayed") == "true",
    }


@mcp.tool(
    annotations=controlled_write_annotations,
    tags={"planning", "controlled-write", "idempotent", "confirmation-required"},
    auth=planning_write_auth,
)
async def start_planning_project_analysis(
    request_id: Annotated[
        str,
        Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"),
    ],
    project_id: BusinessId,
    review_token: Annotated[str, Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")],
    confirmation: Literal["START_AGENT_ANALYSIS"],
) -> dict[str, Any]:
    """明确确认后幂等启动规划 Agent；会投递 Celery，但不会自动审批或生成正式选品。"""
    if confirmation != "START_AGENT_ANALYSIS":
        raise ToolError("启动规划 Agent 必须明确传入确认词 START_AGENT_ANALYSIS")
    result = await request_api_with_metadata(
        "POST",
        f"/planning-projects/{project_id}/runs",
        json={"confirmation": confirmation, "review_token": review_token},
        idempotency_key=request_id,
    )
    return {
        "run": result.data,
        "project_id": project_id,
        "idempotency_key": request_id,
        "replayed": result.headers.get("idempotency-replayed") == "true",
        "side_effects": ["已创建规划运行并投递 Celery 队列"],
        "automatic_actions": [],
        "next_action": "使用 get_planning_run 或规划执行页面跟踪实时进度；规划结果仍需人工审批。",
    }


@mcp.tool(annotations=read_only_annotations, tags={"planning", "readonly"})
async def list_planning_runs(
    project_id: BusinessId,
    page: Annotated[int, Field(ge=1)] = 1,
    page_size: Annotated[int, Field(ge=1, le=50)] = 5,
) -> dict[str, Any]:
    """分页查询指定规划项目的运行版本。"""
    return await request_api(
        "GET",
        f"/planning-projects/{project_id}/runs/page",
        params={"page": page, "page_size": page_size},
    )


@mcp.tool(annotations=read_only_annotations, tags={"planning", "readonly"})
async def get_planning_run(project_id: BusinessId, run_id: BusinessId) -> dict[str, Any]:
    """读取指定运行版本的输入、结果和执行快照。"""
    result = await request_api("GET", f"/planning-projects/{project_id}/runs/{run_id}")
    result_snapshot = result.get("result_snapshot")
    outputs = result_snapshot.get("outputs") if isinstance(result_snapshot, dict) else None
    concept = outputs.get("concept") if isinstance(outputs, dict) else None
    candidates = concept.get("candidates") if isinstance(concept, dict) else None
    validation_tokens: dict[str, str] = {}
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            candidate_id = str(candidate.get("id") or "").strip()
            validation_plan = candidate.get("validation_plan")
            if not candidate_id or not isinstance(validation_plan, dict):
                continue
            review_token = validation_review_fingerprint(
                project_id=project_id,
                run_id=run_id,
                run_status=str(result.get("status") or ""),
                candidate_id=candidate_id,
                validation_plan=validation_plan,
            )
            validation_plan["review_token"] = review_token
            validation_tokens[candidate_id] = review_token
    selected_candidate = concept.get("selected_candidate") if isinstance(concept, dict) else None
    if isinstance(selected_candidate, dict):
        selected_candidate_id = str(selected_candidate.get("id") or "").strip()
        selected_validation_plan = selected_candidate.get("validation_plan")
        selected_review_token = validation_tokens.get(selected_candidate_id)
        if selected_review_token and isinstance(selected_validation_plan, dict):
            selected_validation_plan["review_token"] = selected_review_token
    return result


@mcp.tool(
    annotations=controlled_write_annotations,
    tags={
        "planning",
        "validation",
        "controlled-write",
        "idempotent",
        "confirmation-required",
        "material-required-for-ready",
    },
    auth=planning_write_auth,
)
async def update_validation_gate(
    request_id: Annotated[
        str,
        Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"),
    ],
    project_id: BusinessId,
    run_id: BusinessId,
    candidate_id: BusinessId,
    gate_id: BusinessId,
    review_token: Annotated[str, Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")],
    status: Literal["ready", "pending", "blocked"],
    confirmation: Literal[
        "MARK_VALIDATION_READY",
        "MARK_VALIDATION_BLOCKED",
        "RESET_VALIDATION_PENDING",
    ],
    note: Annotated[str, Field(min_length=1, max_length=2_000)],
) -> dict[str, Any]:
    """复核最新运行后，幂等更新当前已选方案的一个验证门禁。"""
    expected_confirmation = {
        "ready": "MARK_VALIDATION_READY",
        "blocked": "MARK_VALIDATION_BLOCKED",
        "pending": "RESET_VALIDATION_PENDING",
    }[status]
    if confirmation != expected_confirmation:
        raise ToolError("验证门禁确认词必须与 ready、blocked 或 pending 目标状态一致")
    normalized_note = note.strip()
    if not normalized_note:
        raise ToolError("更新验证门禁必须填写复核说明")
    result = await request_api_with_metadata(
        "PATCH",
        f"/planning-projects/{project_id}/runs/{run_id}/validation-plan",
        json={
            "candidate_id": candidate_id,
            "gates": [{"gate_id": gate_id, "status": status, "note": normalized_note}],
            "confirmation": confirmation,
            "review_token": review_token,
        },
        idempotency_key=request_id,
    )
    return {
        "run": result.data,
        "project_id": project_id,
        "candidate_id": candidate_id,
        "gate_id": gate_id,
        "target_status": status,
        "idempotency_key": request_id,
        "replayed": result.headers.get("idempotency-replayed") == "true",
        "side_effects": ["已更新运行快照、正式选品验证状态、审计台账和实时事件"],
        "automatic_actions": [],
        "next_action": "重新读取运行确认验证清单；如需标记通过，验证材料必须由人工先在 Web 页面上传。",
    }


@mcp.tool(annotations=read_only_annotations, tags={"evidence", "readonly"})
async def list_run_evidence(
    project_id: BusinessId,
    run_id: BusinessId,
    page: Annotated[int, Field(ge=1)] = 1,
    page_size: Annotated[int, Field(ge=1, le=50)] = 8,
) -> dict[str, Any]:
    """按运行时引用顺序分页读取证据，并返回已撤回证据总数。"""
    return await request_api(
        "GET",
        f"/planning-projects/{project_id}/runs/{run_id}/evidence/page",
        params={"page": page, "page_size": page_size},
    )


@mcp.tool(annotations=read_only_annotations, tags={"evidence", "retrieval", "readonly"})
async def search_enterprise_evidence(
    query: Annotated[str, Field(min_length=2, max_length=500)],
    category: str | None = None,
    target_market: str | None = None,
    top_k: Annotated[int, Field(ge=1, le=20)] = 5,
) -> dict[str, Any]:
    """使用当前租户的 BGE-M3、Milvus、Reranker 与治理规则检索企业证据。"""
    return await request_api(
        "POST",
        "/retrieval/search",
        json={
            "query": query,
            "category": category,
            "target_market": target_market,
            "top_k": top_k,
        },
    )


@mcp.tool(annotations=read_only_annotations, tags={"approval", "readonly"}, auth=approval_auth)
async def list_approval_tasks(
    status: Literal["pending", "overdue", "processed", "all"] = "pending",
    assignee: Literal["all", "mine", "unassigned"] = "all",
    project_id: str | None = None,
    task_id: BusinessId | None = None,
    page: Annotated[int, Field(ge=1)] = 1,
    page_size: Annotated[int, Field(ge=1, le=50)] = 5,
) -> dict[str, Any]:
    """分页查询当前租户的线上审批任务，并返回随任务状态变化的复核令牌。"""
    result = await request_api(
        "GET",
        "/approval-tasks/page",
        params={
            "status": status,
            "assignee": assignee,
            "project_id": project_id,
            "task_id": task_id,
            "page": page,
            "page_size": page_size,
        },
    )
    for item in result.get("items", []):
        if not isinstance(item, dict):
            continue
        summary_value = item.get("summary")
        item_summary: dict[str, Any] = summary_value if isinstance(summary_value, dict) else {}
        item["review_token"] = approval_review_fingerprint(
            task_id=str(item.get("id") or ""),
            project_id=str(item.get("project_id") or ""),
            run_id=str(item.get("run_id") or ""),
            approval_type=str(item.get("approval_type") or ""),
            checkpoint_ref=str(item.get("checkpoint_ref") or ""),
            status=str(item.get("status") or ""),
            assignee_id=(str(item["assignee_id"]) if item.get("assignee_id") else None),
            due_at=str(item["due_at"]) if item.get("due_at") else None,
            summary=item_summary,
        )
    return result


@mcp.tool(
    annotations=controlled_write_annotations,
    tags={"approval", "controlled-write", "idempotent", "claim-required"},
    auth=approval_auth,
)
async def claim_approval_task(
    request_id: Annotated[
        str,
        Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"),
    ],
    task_id: BusinessId,
) -> dict[str, Any]:
    """幂等领取当前租户的待审批任务；只改变处理人，不提交审批决定。"""
    result = await request_api_with_metadata(
        "POST",
        f"/approval-tasks/{task_id}/claim",
        idempotency_key=request_id,
    )
    task = result.data
    summary_value = task.get("summary")
    task_summary: dict[str, Any] = summary_value if isinstance(summary_value, dict) else {}
    review_token = approval_review_fingerprint(
        task_id=str(task.get("id") or task_id),
        project_id=str(task.get("project_id") or ""),
        run_id=str(task.get("run_id") or ""),
        approval_type=str(task.get("approval_type") or ""),
        checkpoint_ref=str(task.get("checkpoint_ref") or ""),
        status=str(task.get("status") or ""),
        assignee_id=(str(task["assignee_id"]) if task.get("assignee_id") else None),
        due_at=str(task["due_at"]) if task.get("due_at") else None,
        summary=task_summary,
    )
    return {
        "task": task,
        "review_token": review_token,
        "idempotency_key": request_id,
        "replayed": result.headers.get("idempotency-replayed") == "true",
        "automatic_actions": [],
        "next_action": "复核任务摘要、候选方案和证据后，再调用 submit_approval_decision 明确提交决定。",
    }


@mcp.tool(
    annotations=controlled_write_annotations,
    tags={
        "approval",
        "controlled-write",
        "idempotent",
        "claim-required",
        "confirmation-required",
    },
    auth=approval_auth,
)
async def submit_approval_decision(
    request_id: Annotated[
        str,
        Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"),
    ],
    task_id: BusinessId,
    review_token: Annotated[str, Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")],
    action: Literal["approved", "rejected", "revision_required"],
    confirmation: Literal[
        "APPROVE_PLANNING",
        "REJECT_PLANNING",
        "REQUEST_PLANNING_REVISION",
    ],
    comment: Annotated[str, Field(max_length=2_000)] = "",
    selected_candidate_id: BusinessId | None = None,
    target_margin: Annotated[float | None, Field(ge=0, le=1)] = None,
    selling_price: Annotated[float | None, Field(gt=0)] = None,
    unit_cost: Annotated[float | None, Field(ge=0)] = None,
    supplier_name: Annotated[str | None, Field(max_length=255)] = None,
    moq: Annotated[int | None, Field(ge=1)] = None,
    lead_time_days: Annotated[int | None, Field(ge=1)] = None,
) -> dict[str, Any]:
    """对已由当前审批人领取的任务，复核后幂等提交明确审批决定。"""
    expected_confirmation = {
        "approved": "APPROVE_PLANNING",
        "rejected": "REJECT_PLANNING",
        "revision_required": "REQUEST_PLANNING_REVISION",
    }[action]
    if confirmation != expected_confirmation:
        raise ToolError("审批确认词必须与 approved、rejected 或 revision_required 决定一致")
    normalized_comment = comment.strip()
    if action in {"rejected", "revision_required"} and not normalized_comment:
        raise ToolError("驳回或要求修订时必须填写审批意见")
    if action in {"approved", "revision_required"} and selected_candidate_id is None:
        raise ToolError("通过或要求修订时必须选择候选商品方案")
    revision_values = {
        "target_margin": target_margin,
        "selling_price": selling_price,
        "unit_cost": unit_cost,
        "supplier_name": supplier_name.strip() if supplier_name else None,
        "moq": moq,
        "lead_time_days": lead_time_days,
    }
    if action != "revision_required" and any(value is not None for value in revision_values.values()):
        raise ToolError("只有要求修订时才能提交约束参数变更")
    if action == "rejected" and selected_candidate_id is not None:
        raise ToolError("驳回决定不能选择候选商品方案")
    changes: dict[str, Any] = {}
    if selected_candidate_id is not None:
        changes["selected_candidate_id"] = selected_candidate_id
    if action == "revision_required":
        changes["constraints"] = {
            key: value for key, value in revision_values.items() if value is not None
        }
    result = await request_api_with_metadata(
        "POST",
        f"/approval-tasks/{task_id}/decision",
        json={
            "action": action,
            "comment": normalized_comment,
            "changes": changes,
            "confirmation": confirmation,
            "review_token": review_token,
        },
        idempotency_key=request_id,
    )
    return {
        "task": result.data,
        "idempotency_key": request_id,
        "replayed": result.headers.get("idempotency-replayed") == "true",
        "side_effects": [
            "审批决定已提交到现有 Celery 恢复链路",
            (
                "通过后将生成正式选品"
                if action == "approved"
                else "要求修订后将创建新运行版本"
                if action == "revision_required"
                else "驳回后将取消当前规划运行"
            ),
        ],
        "automatic_actions": [],
        "next_action": "在审批中心和规划执行页面跟踪后续处理结果。",
    }


@mcp.tool(annotations=read_only_annotations, tags={"products", "readonly"})
async def list_selected_products(
    status: str | None = None,
    keyword: str | None = None,
    project_id: str | None = None,
    page: Annotated[int, Field(ge=1)] = 1,
    page_size: Annotated[int, Field(ge=1, le=50)] = 6,
) -> dict[str, Any]:
    """分页查询正式选品及其验证和立项状态。"""
    return await request_api(
        "GET",
        "/selected-products/page",
        params={
            "status": status,
            "keyword": keyword,
            "project_id": project_id,
            "page": page,
            "page_size": page_size,
        },
    )


@mcp.tool(annotations=read_only_annotations, tags={"products", "readonly"})
async def list_product_initiatives(
    status: str | None = None,
    keyword: str | None = None,
    project_id: str | None = None,
    page: Annotated[int, Field(ge=1)] = 1,
    page_size: Annotated[int, Field(ge=1, le=50)] = 6,
) -> dict[str, Any]:
    """分页查询商品立项、里程碑和上市推进状态。"""
    return await request_api(
        "GET",
        "/product-initiatives/page",
        params={
            "status": status,
            "keyword": keyword,
            "project_id": project_id,
            "page": page,
            "page_size": page_size,
        },
    )


@mcp.tool(annotations=read_only_annotations, tags={"products", "launch-review", "readonly"})
async def get_launch_review_context(initiative_id: BusinessId) -> dict[str, Any]:
    """读取商品立项最新上市准备、试销摘要、待审状态和受控提交复核令牌。"""
    return await request_api(
        "GET",
        f"/product-initiatives/{initiative_id}/launch-review-context",
    )


@mcp.tool(
    annotations=controlled_write_annotations,
    tags={
        "products",
        "launch-review",
        "controlled-write",
        "idempotent",
        "confirmation-required",
        "human-approval-required",
    },
    auth=planning_write_auth,
)
async def submit_launch_review(
    request_id: Annotated[
        str,
        Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"),
    ],
    initiative_id: BusinessId,
    review_token: Annotated[
        str,
        Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$"),
    ],
    confirmation: Literal["SUBMIT_LAUNCH_REVIEW"],
    submission_note: Annotated[str, Field(min_length=1, max_length=2_000)],
) -> dict[str, Any]:
    """复核最新上市准备状态后，幂等提交待人工审批的上市评审。"""
    normalized_note = submission_note.strip()
    if confirmation != "SUBMIT_LAUNCH_REVIEW":
        raise ToolError("上市评审确认词必须为 SUBMIT_LAUNCH_REVIEW")
    if not normalized_note:
        raise ToolError("提交上市评审必须填写评审说明")
    result = await request_api_with_metadata(
        "POST",
        f"/product-initiatives/{initiative_id}/launch-reviews",
        json={
            "submission_note": normalized_note,
            "confirmation": confirmation,
            "review_token": review_token,
        },
        idempotency_key=request_id,
    )
    return {
        "launch_review": result.data,
        "initiative_id": initiative_id,
        "idempotency_key": request_id,
        "replayed": result.headers.get("idempotency-replayed") == "true",
        "side_effects": ["已创建上市准备评审待办并更新立项评审里程碑"],
        "automatic_actions": [],
        "next_action": "由审批人员在线审核；MCP 提交不会自动批准、确认上市或修改为已上市。",
    }


@mcp.tool(annotations=read_only_annotations, tags={"analytics", "readonly"})
async def list_project_lifecycles(
    page: Annotated[int, Field(ge=1)] = 1,
    page_size: Annotated[int, Field(ge=1, le=50)] = 6,
    project_id: Annotated[str | None, Field(max_length=64)] = None,
    keyword: Annotated[str | None, Field(max_length=128)] = None,
    sort: Literal["priority", "updated"] = "priority",
    status: Literal["all", "blocked", "waiting_human", "active", "complete"] = "all",
) -> dict[str, Any]:
    """分页读取同一项目从需求、Agent、审批、选品到上市的完整闭环台账。"""
    return await request_api(
        "GET",
        "/analytics/project-lifecycles/page",
        params={
            "page": page,
            "page_size": page_size,
            "project_id": project_id,
            "keyword": keyword,
            "sort": sort,
            "status": status,
        },
    )


@mcp.tool(annotations=read_only_annotations, tags={"analytics", "readonly"})
async def get_business_dashboard() -> dict[str, Any]:
    """读取当前租户的项目、审批、选品、立项和数据质量驾驶舱快照。"""
    return await request_api("GET", "/analytics/dashboard")


async def health(_: Request) -> JSONResponse:
    """实现FastMCP的`health`流程，并保持鉴权、确认门禁和错误转换一致。"""
    return JSONResponse({"status": "ok", "service": "merchpilot-mcp", "version": "0.9.0"})


app = mcp.http_app(path=settings.mcp_path, stateless_http=True)
app.routes.insert(0, Route("/health", health, methods=["GET"]))
