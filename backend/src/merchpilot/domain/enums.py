"""文件职责：定义跨接口、数据库和前端共用的核心业务状态枚举。"""

from __future__ import annotations

from enum import StrEnum


class ProjectStatus(StrEnum):
    """`ProjectStatus` 封装本模块相关状态和行为，对调用方提供清晰边界。"""
    DRAFT = "draft"
    RUNNING = "running"
    APPROVAL_REQUIRED = "approval_required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunStatus(StrEnum):
    """`RunStatus` 封装本模块相关状态和行为，对调用方提供清晰边界。"""
    QUEUED = "queued"
    RUNNING = "running"
    APPROVAL_REQUIRED = "approval_required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


class ApprovalStatus(StrEnum):
    """`ApprovalStatus` 封装本模块相关状态和行为，对调用方提供清晰边界。"""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISION_REQUIRED = "revision_required"
    CANCELLED = "cancelled"


class ImportStatus(StrEnum):
    """`ImportStatus` 封装本模块相关状态和行为，对调用方提供清晰边界。"""
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ReportStatus(StrEnum):
    """`ReportStatus` 封装本模块相关状态和行为，对调用方提供清晰边界。"""
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class EvidenceQualityStatus(StrEnum):
    """`EvidenceQualityStatus` 封装本模块相关状态和行为，对调用方提供清晰边界。"""
    VERIFIED = "verified"
    WARNING = "warning"
    BLOCKED = "blocked"


class EvidenceIndexStatus(StrEnum):
    """`EvidenceIndexStatus` 封装本模块相关状态和行为，对调用方提供清晰边界。"""
    PENDING = "pending"
    INDEXING = "indexing"
    INDEXED = "indexed"
    FAILED = "failed"


class DuplicateReviewDecision(StrEnum):
    """`DuplicateReviewDecision` 封装本模块相关状态和行为，对调用方提供清晰边界。"""
    KEEP_ALL = "keep_all"
    SELECT_CANONICAL = "select_canonical"
    DISMISSED = "dismissed"
