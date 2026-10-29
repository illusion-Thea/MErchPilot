"""文件职责：定义 PostgreSQL ORM 业务模型、索引、关联关系和持久化字段。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from merchpilot.domain.enums import (
    ApprovalStatus,
    DuplicateReviewDecision,
    EvidenceIndexStatus,
    EvidenceQualityStatus,
    ImportStatus,
    ProjectStatus,
    ReportStatus,
    RunStatus,
)
from merchpilot.infrastructure.database import Base

audit_timestamp_type = DateTime(timezone=True)


class PlanningProject(Base):
    """`PlanningProject` 是 PostgreSQL ORM 业务实体，集中定义字段、索引和关联关系。"""
    __tablename__ = "planning_projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(128))
    target_market: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default=ProjectStatus.DRAFT.value, index=True)
    constraints: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    archived_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    runs: Mapped[list[PlanningRun]] = relationship(back_populates="project", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_projects_tenant_created", "tenant_id", "created_at"),)


class PlanningRun(Base):
    """`PlanningRun` 是 PostgreSQL ORM 业务实体，集中定义字段、索引和关联关系。"""
    __tablename__ = "planning_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("planning_projects.id", ondelete="CASCADE"), index=True
    )
    parent_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("planning_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    revision_no: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    thread_id: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default=RunStatus.QUEUED.value, index=True)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    execution_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("thread_id", name="thread_id"),
        Index("ix_runs_project_revision", "project_id", "revision_no"),
    )

    project: Mapped[PlanningProject] = relationship(back_populates="runs")


class ApprovalTask(Base):
    """`ApprovalTask` 是 PostgreSQL ORM 业务实体，集中定义字段、索引和关联关系。"""
    __tablename__ = "approval_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("planning_projects.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(ForeignKey("planning_runs.id", ondelete="CASCADE"), index=True)
    approval_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default=ApprovalStatus.PENDING.value, index=True)
    checkpoint_ref: Mapped[str] = mapped_column(String(255))
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    decision: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    decision_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    decision_payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assignee_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SelectedProduct(Base):
    """`SelectedProduct` 是 PostgreSQL ORM 业务实体，集中定义字段、索引和关联关系。"""
    __tablename__ = "selected_products"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("planning_projects.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(ForeignKey("planning_runs.id", ondelete="CASCADE"))
    approval_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("approval_tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    candidate_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))
    project_name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(128), index=True)
    target_market: Mapped[str] = mapped_column(String(128), index=True)
    positioning: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="selected", index=True)
    owner_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    selling_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    margin_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    supplier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    validation_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    selection_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    selected_by: Mapped[str] = mapped_column(String(64), default="system")
    selected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("run_id", name="uq_selected_products_run_id"),
        Index("ix_selected_products_tenant_status", "tenant_id", "status"),
        Index("ix_selected_products_category_market", "category", "target_market"),
    )


class ProductInitiative(Base):
    """`ProductInitiative` 是 PostgreSQL ORM 业务实体，集中定义字段、索引和关联关系。"""
    __tablename__ = "product_initiatives"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    selected_product_id: Mapped[str] = mapped_column(
        ForeignKey("selected_products.id", ondelete="CASCADE")
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("planning_projects.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("planning_runs.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(128), index=True)
    target_market: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), default="in_progress", index=True)
    owner_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    target_launch_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    milestones: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    launched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "selected_product_id",
            name="uq_product_initiatives_selected_product_id",
        ),
        Index("ix_product_initiatives_selected_product_id", "selected_product_id"),
        Index("ix_product_initiatives_tenant_status", "tenant_id", "status"),
        Index("ix_product_initiatives_category_market", "category", "target_market"),
    )


class ProductLaunchReview(Base):
    """`ProductLaunchReview` 是 PostgreSQL ORM 业务实体，集中定义字段、索引和关联关系。"""
    __tablename__ = "product_launch_reviews"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    initiative_id: Mapped[str] = mapped_column(
        ForeignKey("product_initiatives.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    submission_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    readiness_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    submitted_by: Mapped[str] = mapped_column(String(64))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_product_launch_reviews_tenant_initiative", "tenant_id", "initiative_id"),
        Index("ix_product_launch_reviews_tenant_status", "tenant_id", "status"),
    )


class PilotSaleRecord(Base):
    """`PilotSaleRecord` 是 PostgreSQL ORM 业务实体，集中定义字段、索引和关联关系。"""
    __tablename__ = "pilot_sale_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    initiative_id: Mapped[str] = mapped_column(
        ForeignKey("product_initiatives.id", ondelete="CASCADE"), index=True
    )
    period_start: Mapped[date] = mapped_column(Date, index=True)
    period_end: Mapped[date] = mapped_column(Date, index=True)
    channel: Mapped[str] = mapped_column(String(128), index=True)
    visitors: Mapped[int] = mapped_column(Integer, default=0)
    orders: Mapped[int] = mapped_column(Integer, default=0)
    units_sold: Mapped[int] = mapped_column(Integer, default=0)
    revenue: Mapped[float] = mapped_column(Float, default=0)
    product_cost: Mapped[float] = mapped_column(Float, default=0)
    marketing_spend: Mapped[float] = mapped_column(Float, default=0)
    refunds_amount: Mapped[float] = mapped_column(Float, default=0)
    return_count: Mapped[int] = mapped_column(Integer, default=0)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_pilot_sales_tenant_initiative", "tenant_id", "initiative_id"),
        Index("ix_pilot_sales_initiative_period", "initiative_id", "period_start", "period_end"),
        UniqueConstraint(
            "tenant_id",
            "initiative_id",
            "period_start",
            "period_end",
            "channel",
            name="uq_pilot_sales_period_channel",
        ),
    )


class AuditEvent(Base):
    """`AuditEvent` 是 PostgreSQL ORM 业务实体，集中定义字段、索引和关联关系。"""
    __tablename__ = "audit_events"

    sequence_no: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("planning_projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_id: Mapped[str] = mapped_column(String(64), default="system", index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(64), index=True)
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        audit_timestamp_type, server_default=func.now(), index=True
    )

    __table_args__ = (
        Index("ix_audit_tenant_occurred", "tenant_id", "occurred_at"),
        Index("ix_audit_entity_occurred", "entity_type", "entity_id", "occurred_at"),
    )


class IdempotencyRecord(Base):
    """`IdempotencyRecord` 是 PostgreSQL ORM 业务实体，集中定义字段、索引和关联关系。"""
    __tablename__ = "idempotency_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    client_name: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    response_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        audit_timestamp_type, server_default=func.now(), index=True
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "actor_id",
            "operation",
            "idempotency_key",
            name="uq_idempotency_scope_key",
        ),
        Index("ix_idempotency_tenant_created", "tenant_id", "created_at"),
        Index(
            "ix_idempotency_tenant_client_created",
            "tenant_id",
            "client_name",
            "created_at",
        ),
        Index("ix_idempotency_resource", "resource_type", "resource_id"),
    )


class PlanningReport(Base):
    """`PlanningReport` 是 PostgreSQL ORM 业务实体，集中定义字段、索引和关联关系。"""
    __tablename__ = "planning_reports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("planning_projects.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("planning_runs.id", ondelete="CASCADE"), index=True
    )
    format: Mapped[str] = mapped_column(String(16), default="xlsx")
    status: Mapped[str] = mapped_column(String(32), default=ReportStatus.QUEUED.value, index=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DataImportJob(Base):
    """`DataImportJob` 是 PostgreSQL ORM 业务实体，集中定义字段、索引和关联关系。"""
    __tablename__ = "data_import_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(512))
    source_type: Mapped[str] = mapped_column(String(64), default="tabular")
    status: Mapped[str] = mapped_column(String(32), default=ImportStatus.QUEUED.value, index=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    index_celery_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    total_rows: Mapped[int] = mapped_column(default=0)
    valid_rows: Mapped[int] = mapped_column(default=0)
    invalid_rows: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    evidence_records: Mapped[list[EvidenceRecord]] = relationship(back_populates="import_job")


class EvidenceRecord(Base):
    """`EvidenceRecord` 是 PostgreSQL ORM 业务实体，集中定义字段、索引和关联关系。"""
    __tablename__ = "evidence_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    import_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("data_import_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_type: Mapped[str] = mapped_column(String(64), default="tabular")
    source_name: Mapped[str] = mapped_column(String(255))
    source_row: Mapped[int] = mapped_column(default=0)
    source_id: Mapped[str] = mapped_column(String(255), index=True)
    content: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    quality_status: Mapped[str] = mapped_column(
        String(32), default=EvidenceQualityStatus.WARNING.value, index=True
    )
    index_status: Mapped[str] = mapped_column(
        String(32), default=EvidenceIndexStatus.PENDING.value, index=True
    )
    embedding_model_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    import_job: Mapped[DataImportJob | None] = relationship(back_populates="evidence_records")


class EvidenceDuplicateReview(Base):
    """`EvidenceDuplicateReview` 是 PostgreSQL ORM 业务实体，集中定义字段、索引和关联关系。"""
    __tablename__ = "evidence_duplicate_reviews"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    match_type: Mapped[str] = mapped_column(String(32))
    match_value: Mapped[str] = mapped_column(String(512))
    candidate_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    candidate_evidence_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    decision: Mapped[str] = mapped_column(
        String(32), default=DuplicateReviewDecision.KEEP_ALL.value, index=True
    )
    canonical_evidence_id: Mapped[str | None] = mapped_column(
        ForeignKey("evidence_records.id", ondelete="SET NULL"), nullable=True, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str] = mapped_column(String(64))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "match_type",
            "match_value",
            name="uq_duplicate_review_match",
        ),
        Index("ix_duplicate_reviews_tenant_reviewed", "tenant_id", "reviewed_at"),
        Index("ix_duplicate_reviews_tenant_decision", "tenant_id", "decision"),
    )
