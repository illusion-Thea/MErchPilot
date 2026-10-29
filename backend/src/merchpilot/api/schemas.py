"""文件职责：定义 REST API 请求与响应模型，作为前后端数据契约。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from merchpilot.domain.enums import DuplicateReviewDecision


class IdentityRead(BaseModel):
    """`IdentityRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    user_id: str
    tenant_id: str
    roles: tuple[str, ...]
    auth_mode: str
    local_profiles: tuple[str, ...] = ()


class McpToolRead(BaseModel):
    """`McpToolRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    name: str
    title: str
    description: str
    tags: list[str] = Field(default_factory=list)
    read_only: bool
    destructive: bool
    idempotent: bool
    required_fields: list[str] = Field(default_factory=list)
    max_page_size: int | None = None


class McpIntegrationRead(BaseModel):
    """`McpIntegrationRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    status: Literal["ready", "degraded", "unavailable"]
    health_ready: bool
    authenticated: bool
    service_name: str
    service_version: str
    protocol_version: str
    endpoint: str
    auth_mode: str
    user_id: str
    tenant_id: str
    roles: list[str]
    tools: list[McpToolRead]
    total: int
    read_only_total: int
    controlled_write_total: int
    page: int
    page_size: int
    client_configuration: dict[str, Any]
    error: str | None = None


class LocalDemoProjectRead(BaseModel):
    """描述本地演示工作区中的一条可直接打开的业务主线。"""
    project_id: str
    project_name: str
    category: str
    target_market: str
    scenario: Literal["planning_approval", "validation", "launch_review", "launched"]
    scenario_label: str
    recommended_module: Literal["approval", "selection", "initiative"]
    run_id: str
    approval_task_id: str | None = None
    selected_product_id: str | None = None
    initiative_id: str | None = None
    launch_review_id: str | None = None


class LocalDemoWorkspaceRead(BaseModel):
    """返回演示数据初始化结果和可供页面导航的核心业务标识。"""
    enabled: bool
    created: bool
    tenant_id: str
    evidence_count: int
    indexed_evidence_count: int
    failed_evidence_count: int
    index_status: Literal["pending", "indexing", "indexed", "failed"]
    index_task_id: str | None = None
    primary_project_id: str
    projects: list[LocalDemoProjectRead]
    message: str


class McpVerificationRead(BaseModel):
    """`McpVerificationRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    status: Literal["verified"]
    verified_at: datetime
    tool_name: str
    user_id: str
    tenant_id: str
    roles: list[str]
    project_total: int
    active_project_total: int
    pending_approval_total: int
    selected_product_total: int
    active_initiative_total: int


class McpActivityRead(BaseModel):
    """`McpActivityRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    id: str
    activity_type: Literal[
        "mcp_created",
        "mcp_started",
        "mcp_approval_claimed",
        "mcp_approval_decided",
        "mcp_validation_updated",
        "mcp_launch_review_submitted",
    ]
    request_id: str
    actor_id: str
    project_id: str
    project_name: str
    category: str
    target_market: str
    project_status: str
    created_at: datetime
    project_created_by: str
    project_created_at: datetime
    mcp_creation_request_id: str | None = None
    mcp_creation_actor_id: str | None = None
    mcp_created_at: datetime | None = None
    latest_start_request_id: str | None = None
    latest_start_actor_id: str | None = None
    latest_start_at: datetime | None = None
    latest_run_id: str | None = None
    latest_run_status: str | None = None
    latest_approval_request_id: str | None = None
    latest_approval_actor_id: str | None = None
    latest_approval_at: datetime | None = None
    latest_approval_task_id: str | None = None
    latest_approval_event: str | None = None
    latest_approval_status: str | None = None
    latest_validation_request_id: str | None = None
    latest_validation_actor_id: str | None = None
    latest_validation_at: datetime | None = None
    latest_validation_run_id: str | None = None
    latest_validation_candidate_id: str | None = None
    latest_validation_gate_ids: list[str] = Field(default_factory=list)
    latest_validation_status: str | None = None
    latest_validation_completion_rate: int | None = None
    latest_launch_review_request_id: str | None = None
    latest_launch_review_actor_id: str | None = None
    latest_launch_review_at: datetime | None = None
    latest_launch_review_initiative_id: str | None = None
    latest_launch_review_initiative_name: str | None = None
    latest_launch_review_id: str | None = None
    latest_launch_review_status: str | None = None
    latest_launch_review_readiness_status: str | None = None


class McpActivityPage(BaseModel):
    """`McpActivityPage` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    items: list[McpActivityRead]
    total: int
    page: int
    page_size: int


class AsyncTaskStatusRead(BaseModel):
    """`AsyncTaskStatusRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    task_id: str
    state: str
    state_label: str
    ready: bool
    terminal: bool
    resource_type: Literal["planning_run", "data_import", "planning_report"]
    resource_id: str


class RetrievalSearchRequest(BaseModel):
    """`RetrievalSearchRequest` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    query: str = Field(min_length=2, max_length=500)
    category: str | None = Field(default=None, max_length=128)
    target_market: str | None = Field(default=None, max_length=128)
    top_k: int = Field(default=5, ge=1, le=20)


class RetrievalHitRead(BaseModel):
    """`RetrievalHitRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    evidence_id: str
    score: float
    vector_score: float | None = None
    hybrid_score: float | None = None
    retrieval_mode: str | None = None
    import_job_id: str | None = None
    source_name: str | None = None
    source_row: int | None = None
    source_id: str | None = None
    source_url: str | None = None
    observed_at: datetime | None = None
    category: str | None = None
    target_market: str | None = None
    quality_status: str | None = None
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    governance: dict[str, Any] | None = None


class RetrievalSearchRead(BaseModel):
    """`RetrievalSearchRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    status: Literal["ready", "partial", "degraded"]
    reason: str | None = None
    query: str
    evidence_ids: list[str]
    hits: list[RetrievalHitRead]
    governance: dict[str, list[str]]


class PlanningProjectCreate(BaseModel):
    """`PlanningProjectCreate` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    name: str = Field(min_length=2, max_length=255)
    category: str = Field(min_length=1, max_length=128)
    target_market: str = Field(min_length=1, max_length=128)
    constraints: dict[str, Any] = Field(default_factory=dict)


class PlanningProjectUpdate(BaseModel):
    """`PlanningProjectUpdate` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    name: str | None = Field(default=None, min_length=2, max_length=255)
    category: str | None = Field(default=None, min_length=1, max_length=128)
    target_market: str | None = Field(default=None, min_length=1, max_length=128)
    constraints: dict[str, Any] | None = None


class PlanningRunStartRequest(BaseModel):
    """`PlanningRunStartRequest` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    confirmation: Literal["START_AGENT_ANALYSIS"] | None = None
    review_token: str | None = Field(default=None, min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")


class PlanningProjectRead(BaseModel):
    """`PlanningProjectRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    name: str
    category: str
    target_market: str
    status: str
    constraints: dict[str, Any]
    archived_by: str | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PlanningProjectPageSummary(BaseModel):
    """`PlanningProjectPageSummary` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    total: int
    draft: int
    queued: int
    running: int
    approval_required: int
    completed: int
    failed: int
    cancelled: int


class PlanningProjectPage(BaseModel):
    """`PlanningProjectPage` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    items: list[PlanningProjectRead]
    total: int
    page: int
    page_size: int
    summary: PlanningProjectPageSummary


class PlanningRunRead(BaseModel):
    """`PlanningRunRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    parent_run_id: str | None
    revision_no: int
    thread_id: str
    status: str
    celery_task_id: str | None
    error_message: str | None
    execution_snapshot: dict[str, Any]
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PlanningRunPageSummary(BaseModel):
    """`PlanningRunPageSummary` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    total: int
    queued: int
    running: int
    approval_required: int
    completed: int
    failed: int
    cancelled: int
    superseded: int
    active: int


class PlanningRunPage(BaseModel):
    """`PlanningRunPage` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    items: list[PlanningRunRead]
    total: int
    page: int
    page_size: int
    summary: PlanningRunPageSummary


class PlanningRunDetail(PlanningRunRead):
    """`PlanningRunDetail` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    input_snapshot: dict[str, Any]
    result_snapshot: dict[str, Any] | None
    execution_snapshot: dict[str, Any]


class ValidationGateUpdate(BaseModel):
    """`ValidationGateUpdate` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    gate_id: str = Field(min_length=1, max_length=64)
    status: Literal["ready", "pending", "blocked"]
    note: str = Field(default="", max_length=2_000)


class PlanningValidationPlanUpdate(BaseModel):
    """`PlanningValidationPlanUpdate` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    candidate_id: str = Field(min_length=1, max_length=64)
    gates: list[ValidationGateUpdate] = Field(min_length=1, max_length=4)


class PlanningValidationPlanRequest(PlanningValidationPlanUpdate):
    """`PlanningValidationPlanRequest` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    confirmation: Literal[
        "MARK_VALIDATION_READY",
        "MARK_VALIDATION_BLOCKED",
        "RESET_VALIDATION_PENDING",
    ] | None = None
    review_token: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )


class RunEventRead(BaseModel):
    """`RunEventRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    event_id: str
    event_type: str
    occurred_at: datetime | None
    payload: dict[str, Any]


class PlanningRunEvidenceRead(BaseModel):
    """`PlanningRunEvidenceRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    evidence_id: str
    topics: list[str]
    source_name: str | None
    source_row: int | None
    source_id: str | None
    content: str
    metadata_json: dict[str, Any]
    quality_status: str | None
    observed_at: datetime | None
    retrieval_score: float | None
    vector_score: float | None
    is_canonical: bool
    duplicate_review_ids: list[str]
    available: bool


class PlanningRunEvidencePage(BaseModel):
    """`PlanningRunEvidencePage` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    items: list[PlanningRunEvidenceRead]
    total: int
    page: int
    page_size: int
    unavailable_total: int


class ApprovalTaskRead(BaseModel):
    """`ApprovalTaskRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    run_id: str
    approval_type: str
    status: str
    checkpoint_ref: str
    summary: dict[str, Any]
    decision: dict[str, Any] | None
    decision_request_id: str | None
    decision_payload_hash: str | None
    assignee_id: str | None
    due_at: datetime | None
    decided_by: str | None
    decided_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ApprovalProjectOption(BaseModel):
    """`ApprovalProjectOption` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    value: str
    label: str


class ApprovalTaskPageSummary(BaseModel):
    """`ApprovalTaskPageSummary` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    total: int
    pending: int
    approved: int
    rejected: int
    revision_required: int
    cancelled: int
    processed: int
    overdue: int
    due_soon: int
    mine_pending: int
    unassigned_pending: int


class ApprovalTaskPage(BaseModel):
    """`ApprovalTaskPage` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    items: list[ApprovalTaskRead]
    total: int
    page: int
    page_size: int
    summary: ApprovalTaskPageSummary
    project_options: list[ApprovalProjectOption]


class ApprovalDecision(BaseModel):
    """`ApprovalDecision` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    action: str = Field(pattern="^(approved|rejected|revision_required)$")
    comment: str = Field(default="", max_length=2_000)
    changes: dict[str, Any] = Field(default_factory=dict)


class ApprovalDecisionRequest(ApprovalDecision):
    """`ApprovalDecisionRequest` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    confirmation: Literal[
        "APPROVE_PLANNING",
        "REJECT_PLANNING",
        "REQUEST_PLANNING_REVISION",
    ] | None = None
    review_token: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )


class ApprovalAssignment(BaseModel):
    """`ApprovalAssignment` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    assignee_id: str = Field(min_length=1, max_length=64)


class SelectedProductRead(BaseModel):
    """`SelectedProductRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    project_id: str
    run_id: str
    approval_task_id: str | None
    candidate_id: str
    name: str
    project_name: str
    category: str
    target_market: str
    positioning: str | None
    status: str
    owner_id: str | None
    score: int | None
    selling_price: float | None
    margin_rate: float | None
    estimated_profit: float | None
    supplier_name: str | None
    validation_status: str | None
    selection_snapshot: dict[str, Any]
    notes: str | None
    selected_by: str
    selected_at: datetime
    created_at: datetime
    updated_at: datetime


class SelectedProductPageSummary(BaseModel):
    """`SelectedProductPageSummary` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    total: int
    validating: int
    ready: int
    initiated: int
    paused: int


class SelectedProductPage(BaseModel):
    """`SelectedProductPage` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    items: list[SelectedProductRead]
    total: int
    page: int
    page_size: int
    categories: list[str]
    summary: SelectedProductPageSummary


class SelectedProductUpdate(BaseModel):
    """`SelectedProductUpdate` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    status: Literal[
        "selected",
        "validating",
        "ready",
        "initiated",
        "launched",
        "paused",
        "cancelled",
    ] | None = None
    owner_id: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=2_000)


class ProductInitiativeCreate(BaseModel):
    """`ProductInitiativeCreate` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    selected_product_id: str = Field(min_length=1, max_length=64)
    owner_id: str | None = Field(default=None, max_length=64)
    target_launch_date: date | None = None
    budget: float | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=2_000)


class ProductInitiativeRead(BaseModel):
    """`ProductInitiativeRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    selected_product_id: str
    project_id: str
    run_id: str
    name: str
    category: str
    target_market: str
    status: str
    owner_id: str | None
    target_launch_date: date | None
    budget: float | None
    milestones: list[dict[str, Any]]
    notes: str | None
    created_by: str
    launched_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProductInitiativePageSummary(BaseModel):
    """`ProductInitiativePageSummary` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    total: int
    active: int
    attention: int
    ready: int
    launched: int


class ProductInitiativePage(BaseModel):
    """`ProductInitiativePage` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    items: list[ProductInitiativeRead]
    total: int
    page: int
    page_size: int
    summary: ProductInitiativePageSummary


class ProductInitiativeUpdate(BaseModel):
    """`ProductInitiativeUpdate` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    status: Literal["in_progress", "launched", "paused", "cancelled"] | None = None
    owner_id: str | None = Field(default=None, max_length=64)
    target_launch_date: date | None = None
    budget: float | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=2_000)


class ProductMilestoneUpdate(BaseModel):
    """`ProductMilestoneUpdate` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    status: Literal["pending", "in_progress", "completed", "blocked"] | None = None
    owner_id: str | None = Field(default=None, max_length=64)
    due_date: date | None = None
    note: str | None = Field(default=None, max_length=2_000)


class ProductLaunchReviewSubmit(BaseModel):
    """`ProductLaunchReviewSubmit` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    submission_note: str | None = Field(default=None, max_length=2_000)
    confirmation: Literal["SUBMIT_LAUNCH_REVIEW"] | None = None
    review_token: str | None = Field(default=None, min_length=64, max_length=64)


class ProductLaunchReviewDecision(BaseModel):
    """`ProductLaunchReviewDecision` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    action: Literal["approved", "rejected", "revision_required"]
    decision_note: str = Field(default="", max_length=2_000)


class ProductLaunchReviewRead(BaseModel):
    """`ProductLaunchReviewRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    initiative_id: str
    initiative_name: str | None = None
    project_id: str | None = None
    category: str | None = None
    target_market: str | None = None
    status: str
    submission_note: str | None
    decision_note: str | None
    readiness_snapshot: dict[str, Any]
    submitted_by: str
    submitted_at: datetime
    decided_by: str | None
    decided_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProductLaunchReviewPageSummary(BaseModel):
    """`ProductLaunchReviewPageSummary` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    total: int
    pending: int
    approved: int
    rejected: int
    revision_required: int
    processed: int


class ProductLaunchReviewPage(BaseModel):
    """`ProductLaunchReviewPage` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    items: list[ProductLaunchReviewRead]
    total: int
    page: int
    page_size: int
    summary: ProductLaunchReviewPageSummary


class PilotSaleCreate(BaseModel):
    """`PilotSaleCreate` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    period_start: date
    period_end: date
    channel: str = Field(min_length=1, max_length=128)
    visitors: int = Field(default=0, ge=0)
    orders: int = Field(default=0, ge=0)
    units_sold: int = Field(default=0, ge=0)
    revenue: float = Field(default=0, ge=0)
    product_cost: float = Field(default=0, ge=0)
    marketing_spend: float = Field(default=0, ge=0)
    refunds_amount: float = Field(default=0, ge=0)
    return_count: int = Field(default=0, ge=0)
    rating: float | None = Field(default=None, ge=0, le=5)
    notes: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def validate_business_totals(self) -> Self:
        """实现`validate_business_totals`流程；输入、输出和异常语义由类型标注及调用方约束。"""
        self.channel = self.channel.strip()
        if not self.channel:
            raise ValueError("channel must not be blank")
        if self.period_end < self.period_start:
            raise ValueError("period_end must not be earlier than period_start")
        if self.orders > self.visitors and self.visitors > 0:
            raise ValueError("orders must not exceed visitors")
        if self.return_count > self.units_sold:
            raise ValueError("return_count must not exceed units_sold")
        if self.refunds_amount > self.revenue:
            raise ValueError("refunds_amount must not exceed revenue")
        return self


class PilotSaleUpdate(BaseModel):
    """`PilotSaleUpdate` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    period_start: date | None = None
    period_end: date | None = None
    channel: str | None = Field(default=None, min_length=1, max_length=128)
    visitors: int | None = Field(default=None, ge=0)
    orders: int | None = Field(default=None, ge=0)
    units_sold: int | None = Field(default=None, ge=0)
    revenue: float | None = Field(default=None, ge=0)
    product_cost: float | None = Field(default=None, ge=0)
    marketing_spend: float | None = Field(default=None, ge=0)
    refunds_amount: float | None = Field(default=None, ge=0)
    return_count: int | None = Field(default=None, ge=0)
    rating: float | None = Field(default=None, ge=0, le=5)
    notes: str | None = Field(default=None, max_length=2_000)


class PilotSaleRead(BaseModel):
    """`PilotSaleRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    id: str
    initiative_id: str
    period_start: date
    period_end: date
    channel: str
    visitors: int
    orders: int
    units_sold: int
    revenue: float
    product_cost: float
    marketing_spend: float
    refunds_amount: float
    return_count: int
    rating: float | None
    notes: str | None
    conversion_rate: float | None
    return_rate: float | None
    average_order_value: float | None
    gross_profit: float
    actual_margin_rate: float | None
    marketing_roi: float | None
    created_by: str
    created_at: datetime
    updated_at: datetime


class PilotSalePage(BaseModel):
    """`PilotSalePage` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    items: list[PilotSaleRead]
    total: int
    page: int
    page_size: int


class PilotSaleSummary(BaseModel):
    """`PilotSaleSummary` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    record_count: int
    visitors: int
    orders: int
    units_sold: int
    revenue: float
    product_cost: float
    marketing_spend: float
    refunds_amount: float
    return_count: int
    conversion_rate: float | None
    return_rate: float | None
    average_order_value: float | None
    gross_profit: float
    actual_margin_rate: float | None
    marketing_roi: float | None
    average_rating: float | None
    planned_margin_rate: float | None
    margin_gap: float | None
    assessment_status: Literal["insufficient", "recommended", "review", "blocked"]
    assessment_label: str
    risks: list[str]
    recommendations: list[str]


class PilotSaleTrendPoint(BaseModel):
    """`PilotSaleTrendPoint` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    label: str
    period_start: date
    period_end: date
    channel: str
    visitors: int
    orders: int
    units_sold: int
    revenue: float
    gross_profit: float
    conversion_rate: float | None
    return_rate: float | None
    actual_margin_rate: float | None


class PilotSaleTrend(BaseModel):
    """`PilotSaleTrend` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    periods: list[PilotSaleTrendPoint]
    channels: list[PilotSaleTrendPoint]
    period_total: int
    channel_total: int


class ProductLaunchReadinessCheck(BaseModel):
    """`ProductLaunchReadinessCheck` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    id: str
    label: str
    status: Literal["passed", "pending", "warning", "blocked"]
    detail: str


class ProductLaunchReadiness(BaseModel):
    """`ProductLaunchReadiness` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    readiness_status: Literal["ready", "review", "blocked"]
    readiness_label: str
    checks: list[ProductLaunchReadinessCheck]
    blockers: list[str]
    warnings: list[str]
    recommendations: list[str]


class ProductLaunchReviewContext(BaseModel):
    """`ProductLaunchReviewContext` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    initiative_id: str
    initiative_name: str
    initiative_status: str
    readiness: ProductLaunchReadiness
    pilot_summary: PilotSaleSummary
    pending_review: ProductLaunchReviewRead | None
    can_submit: bool
    submission_blockers: list[str]
    review_token: str


class AuditEventRead(BaseModel):
    """`AuditEventRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    project_id: str | None
    actor_id: str
    action: str
    entity_type: str
    entity_id: str
    detail: dict[str, Any]
    occurred_at: datetime


class AuditEventPage(BaseModel):
    """`AuditEventPage` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    items: list[AuditEventRead]
    total: int
    page: int
    page_size: int


class OpportunitySummary(BaseModel):
    """`OpportunitySummary` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    project_id: str
    project_name: str
    category: str
    target_market: str
    project_status: str
    run_id: str | None
    run_status: str | None
    score: int | None
    score_status: str | None
    evidence_count: int
    margin_rate: float | None
    supplier_risk: str | None
    score_breakdown: dict[str, Any]
    updated_at: datetime


class OpportunityPage(BaseModel):
    """`OpportunityPage` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    items: list[OpportunitySummary]
    total: int
    page: int
    page_size: int


class PlanningReportRead(BaseModel):
    """`PlanningReportRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    run_id: str
    format: str
    status: str
    celery_task_id: str | None
    storage_key: str | None
    error_message: str | None
    created_by: str
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PlanningReportPage(BaseModel):
    """`PlanningReportPage` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    items: list[PlanningReportRead]
    total: int
    page: int
    page_size: int


class DataImportRead(BaseModel):
    """`DataImportRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    filename: str
    source_type: str
    status: str
    celery_task_id: str | None
    index_celery_task_id: str | None
    total_rows: int
    valid_rows: int
    invalid_rows: int
    indexable_rows: int = 0
    indexed_rows: int = 0
    pending_index_rows: int = 0
    failed_index_rows: int = 0
    retrieval_status: Literal["ready", "indexing", "failed", "empty", "unavailable"] = "unavailable"
    retrieval_ready: bool = False
    error_message: str | None
    created_by: str
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DataImportPageSummary(BaseModel):
    """`DataImportPageSummary` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    total: int
    queued: int
    processing: int
    completed: int
    failed: int


class DataImportPage(BaseModel):
    """`DataImportPage` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    items: list[DataImportRead]
    total: int
    page: int
    page_size: int
    summary: DataImportPageSummary


class DataImportQualityImportRead(BaseModel):
    """`DataImportQualityImportRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    import_id: str
    filename: str
    created_at: datetime
    warning_records: int
    blocked_records: int
    failed_index_records: int


class DataImportQualitySummary(BaseModel):
    """`DataImportQualitySummary` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    total_imports: int
    completed_imports: int
    failed_imports: int
    total_records: int
    verified_records: int
    warning_records: int
    blocked_records: int
    indexed_records: int
    pending_index_records: int
    failed_index_records: int
    problem_import_total: int
    problem_imports: list[DataImportQualityImportRead]


class DashboardSnapshot(BaseModel):
    """`DashboardSnapshot` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    latest_project: PlanningProjectRead | None
    latest_opportunity: OpportunitySummary | None
    latest_selection: SelectedProductRead | None
    latest_ready_selection: SelectedProductRead | None
    latest_pending_selection: SelectedProductRead | None
    latest_initiative: ProductInitiativeRead | None
    attention_initiative: ProductInitiativeRead | None
    progress_initiative: ProductInitiativeRead | None
    latest_approval: ApprovalTaskRead | None
    latest_launch_review: ProductLaunchReviewRead | None
    pending_approval_count: int
    pending_launch_review_count: int
    project_total: int
    active_project_total: int
    completed_project_total: int
    selected_product_total: int
    selected_product_validating: int
    selected_product_ready: int
    active_initiative_total: int
    pending_index_import_id: str | None


class ProjectLifecycleStageRead(BaseModel):
    """`ProjectLifecycleStageRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    key: Literal[
        "project",
        "agent",
        "approval",
        "selection",
        "validation",
        "initiative",
        "launch_review",
        "launched",
    ]
    label: str
    status: Literal["complete", "current", "waiting", "blocked"]
    detail: str
    entity_id: str | None


class ProjectLifecycleRead(BaseModel):
    """`ProjectLifecycleRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    project_id: str
    project_name: str
    category: str
    target_market: str
    project_status: str
    run_id: str | None
    run_status: str | None
    approval_task_id: str | None
    approval_status: str | None
    selected_product_id: str | None
    selected_product_name: str | None
    selected_product_status: str | None
    validation_status: str | None
    initiative_id: str | None
    initiative_status: str | None
    launch_review_id: str | None
    launch_review_status: str | None
    current_milestone_id: str | None
    current_milestone_label: str | None
    current_milestone_status: str | None
    stage: str
    stage_label: str
    progress_percent: int
    health: Literal["on_track", "attention", "blocked", "complete"]
    blockers: list[str]
    next_action_label: str
    next_action_type: Literal[
        "planning-project",
        "planning-approval",
        "selected-product",
        "initiative-create",
        "initiative",
        "launch-review",
    ]
    next_action_id: str
    stages: list[ProjectLifecycleStageRead]
    updated_at: datetime


class ProjectLifecyclePageSummary(BaseModel):
    """`ProjectLifecyclePageSummary` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    total: int
    blocked: int
    waiting_human: int
    active: int
    complete: int


class ProjectLifecyclePage(BaseModel):
    """`ProjectLifecyclePage` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    items: list[ProjectLifecycleRead]
    total: int
    page: int
    page_size: int
    summary: ProjectLifecyclePageSummary


class NotificationEntityReference(BaseModel):
    """`NotificationEntityReference` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    id: str
    label: str


class NotificationSnapshot(BaseModel):
    """`NotificationSnapshot` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    actionable_approval_count: int
    overdue_actionable_approval_count: int
    latest_actionable_approval: ApprovalTaskRead | None
    latest_overdue_approval: ApprovalTaskRead | None
    pending_launch_review_count: int
    latest_launch_review: ProductLaunchReviewRead | None
    new_selection_count: int
    latest_new_selection: NotificationEntityReference | None
    ready_selection_count: int
    latest_ready_selection: NotificationEntityReference | None
    failed_project_count: int
    latest_failed_project: NotificationEntityReference | None
    cancelled_project_count: int
    latest_cancelled_project: NotificationEntityReference | None
    awaiting_approval_project_count: int
    latest_awaiting_approval_project: NotificationEntityReference | None
    failed_import_count: int
    latest_failed_import: NotificationEntityReference | None
    invalid_import_count: int
    invalid_import_rows: int
    latest_invalid_import: NotificationEntityReference | None
    pending_index_import: NotificationEntityReference | None


class DataImportReindexRead(BaseModel):
    """`DataImportReindexRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    import_id: str
    queued_records: int
    task_id: str | None


class DataCoverageRead(BaseModel):
    """`DataCoverageRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    total_records: int
    verified_records: int
    dated_records: int
    source_id_records: int
    date_coverage_rate: float
    source_id_coverage_rate: float
    data_type_counts: dict[str, int]
    category_counts: dict[str, int]
    target_market_counts: dict[str, int]


class DataDuplicateRecordRead(BaseModel):
    """`DataDuplicateRecordRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    evidence_id: str
    source_id: str
    import_job_id: str | None
    source_name: str
    source_row: int
    quality_status: str
    observed_at: datetime | None
    content_preview: str


class DataDuplicateReviewRead(BaseModel):
    """`DataDuplicateReviewRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    model_config = ConfigDict(from_attributes=True)

    id: str
    match_type: str
    match_value: str
    decision: DuplicateReviewDecision
    canonical_evidence_id: str | None
    notes: str | None
    reviewed_by: str
    reviewed_at: datetime
    created_at: datetime
    updated_at: datetime


class DataDuplicateReviewUpsert(BaseModel):
    """`DataDuplicateReviewUpsert` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    match_type: str = Field(pattern="^(source_id|content_hash)$")
    match_value: str = Field(min_length=1, max_length=512)
    decision: DuplicateReviewDecision
    canonical_evidence_id: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def validate_canonical_evidence(self) -> Self:
        """实现`validate_canonical_evidence`流程；输入、输出和异常语义由类型标注及调用方约束。"""
        if self.decision == DuplicateReviewDecision.SELECT_CANONICAL:
            if not self.canonical_evidence_id:
                raise ValueError("选择主记录时必须指定主记录")
        elif self.canonical_evidence_id is not None:
            raise ValueError("仅选择主记录时可以指定主记录")
        return self


class DataDuplicateGroupRead(BaseModel):
    """`DataDuplicateGroupRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    match_type: str
    match_value: str
    record_count: int
    import_count: int
    evidence_ids: list[str]
    import_job_ids: list[str]
    source_ids: list[str]
    records: list[DataDuplicateRecordRead]
    review: DataDuplicateReviewRead | None = None


class DataDuplicateGroupSummaryRead(BaseModel):
    """`DataDuplicateGroupSummaryRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    match_type: str
    match_value: str
    record_count: int
    import_count: int
    records: list[DataDuplicateRecordRead]
    review: DataDuplicateReviewRead | None = None


class DataDuplicateGroupPageSummary(BaseModel):
    """`DataDuplicateGroupPageSummary` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    total: int
    pending: int
    reviewed: int


class DataDuplicateGroupPage(BaseModel):
    """`DataDuplicateGroupPage` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    items: list[DataDuplicateGroupSummaryRead]
    total: int
    page: int
    page_size: int
    summary: DataDuplicateGroupPageSummary


class DataDuplicateGroupRecordPage(BaseModel):
    """`DataDuplicateGroupRecordPage` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    match_type: str
    match_value: str
    record_count: int
    import_count: int
    items: list[DataDuplicateRecordRead]
    page: int
    page_size: int
    review: DataDuplicateReviewRead | None = None
    canonical_record: DataDuplicateRecordRead | None = None


class DataImportComparisonRead(BaseModel):
    """`DataImportComparisonRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    base_import_id: str
    target_import_id: str
    base_records: int
    target_records: int
    base_unkeyed_count: int
    target_unkeyed_count: int
    added_count: int
    removed_count: int
    changed_count: int
    unchanged_count: int
    added_source_ids: list[str]
    removed_source_ids: list[str]
    changed_source_ids: list[str]
    unchanged_source_ids: list[str]
    base_coverage: DataCoverageRead
    target_coverage: DataCoverageRead


class EvidenceRecordRead(BaseModel):
    """`EvidenceRecordRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    model_config = ConfigDict(from_attributes=True)

    id: str
    import_job_id: str | None
    source_type: str
    source_name: str
    source_row: int
    source_id: str
    content: str
    metadata_json: dict[str, Any]
    quality_status: str
    index_status: str
    embedding_model_version: str | None
    observed_at: datetime | None
    created_at: datetime


class EvidenceRecordPage(BaseModel):
    """`EvidenceRecordPage` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    items: list[EvidenceRecordRead]
    total: int
    page: int
    page_size: int


class EvidenceQualityReviewRequest(BaseModel):
    """`EvidenceQualityReviewRequest` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    action: Literal["verify", "block"]
    note: str | None = Field(default=None, max_length=1000)


class EvidenceQualityIssueSummaryItem(BaseModel):
    """`EvidenceQualityIssueSummaryItem` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    code: str
    field: str
    message: str
    severity: str
    count: int


class EvidenceQualityIssueSummaryRead(BaseModel):
    """`EvidenceQualityIssueSummaryRead` 是REST API数据契约，负责字段类型、默认值和输入校验。"""
    total_records: int
    verified_records: int
    warning_records: int
    blocked_records: int
    failed_index_records: int
    issues: list[EvidenceQualityIssueSummaryItem]
