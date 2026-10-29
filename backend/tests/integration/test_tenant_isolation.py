"""文件职责：验证 tenant isolation 相关规则、边界与回归行为。"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import Header, HTTPException, status
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import merchpilot.api.routes.approvals as approvals_route_module
import merchpilot.api.routes.async_tasks as async_tasks_route_module
import merchpilot.api.routes.demo_workspace as demo_workspace_route_module
import merchpilot.api.routes.imports as imports_route_module
import merchpilot.api.routes.projects as projects_route_module
import merchpilot.api.routes.reports as reports_route_module
import merchpilot.api.routes.retrieval as retrieval_route_module
import merchpilot.services.selection_registry as selection_registry_service
import merchpilot.workers.tasks as worker_tasks
from merchpilot.api.dependencies import get_current_identity
from merchpilot.infrastructure.database import Base, get_db_session
from merchpilot.infrastructure.models import (
    ApprovalTask,
    AuditEvent,
    DataImportJob,
    EvidenceRecord,
    PlanningProject,
    PlanningReport,
    PlanningRun,
    ProductInitiative,
    ProductLaunchReview,
    SelectedProduct,
)
from merchpilot.main import app
from merchpilot.ports.identity import Identity
from merchpilot.services.approval_guard import approval_review_fingerprint
from merchpilot.services.project_guard import project_configuration_fingerprint
from merchpilot.services.retrieval_governance import EvidenceGovernanceResolver
from merchpilot.services.validation_guard import validation_review_fingerprint

pytestmark = pytest.mark.integration


def authorization(subject: str) -> dict[str, str]:
    """生成基础认证请求头，模拟本地身份提供方收到的访问凭证。"""
    return {"Authorization": f"Bearer {subject}"}


def identity_for(subject: str) -> Identity:
    """构造指定租户和角色的测试身份，用于验证租户隔离与权限边界。"""
    identities = {
        "tenant-a-admin": Identity("admin-a", "tenant-a", ("admin",)),
        "tenant-a-planner": Identity("planner-a", "tenant-a", ("planner",)),
        "tenant-a-approver": Identity("approver-a", "tenant-a", ("approver",)),
        "tenant-a-approver-2": Identity("approver-a-2", "tenant-a", ("approver",)),
        "tenant-a-viewer": Identity("viewer-a", "tenant-a", ("viewer",)),
        "tenant-b-admin": Identity("admin-b", "tenant-b", ("admin",)),
        "tenant-b-viewer": Identity("viewer-b", "tenant-b", ("viewer",)),
    }
    try:
        return identities[subject]
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown test identity") from exc


async def upload_test_validation_material(
    tenant_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    note: str,
) -> Response:
    """上传一份内存验证材料，供依赖验证通过前置条件的集成用例复用。"""
    class MemoryStorage:
        """提供验证材料上传所需的最小对象存储测试替身。"""

        async def put_object(self, key: str, content: bytes, content_type: str) -> str:
            """接收测试文件内容并返回稳定的对象键。"""
            del content, content_type
            return key

    monkeypatch.setattr(
        projects_route_module,
        "get_object_storage_provider",
        lambda: MemoryStorage(),
    )
    return await tenant_client.post(
        "/api/v1/planning-projects/project-a/runs/run-a/validation-materials",
        headers=authorization("tenant-a-planner"),
        data={
            "candidate_id": "candidate-a",
            "gate_id": "sample_test",
            "note": note,
        },
        files={"file": ("validation-report.pdf", b"validated report", "application/pdf")},
    )


async def seed_tenants(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """向 PostgreSQL 写入两个租户的完整业务样本，为跨租户集成测试提供固定基线。"""
    async with session_factory() as session:
        session.add_all(
            [
                PlanningProject(
                    id="project-a",
                    tenant_id="tenant-a",
                    name="租户 A 项目",
                    category="保温杯",
                    target_market="中国",
                    status="approval_required",
                    constraints={},
                    created_by="planner-a",
                ),
                PlanningProject(
                    id="project-b",
                    tenant_id="tenant-b",
                    name="租户 B 项目",
                    category="咖啡机",
                    target_market="美国",
                    status="approval_required",
                    constraints={},
                    created_by="planner-b",
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                PlanningRun(
                    id="run-a",
                    project_id="project-a",
                    thread_id="thread-a",
                    status="approval_required",
                    input_snapshot={},
                    result_snapshot={
                        "outputs": {
                            "scorecard": {
                                "score": 86,
                                "status": "recommended",
                                "evidence_count": 1,
                            },
                            "market": {
                                "status": "ready",
                                "hits": [
                                    {
                                        "id": "evidence-a",
                                        "source_name": "运行快照.xlsx",
                                        "score": 0.93,
                                        "vector_score": 0.81,
                                        "content": "租户 A 运行时证据摘要",
                                    }
                                ],
                            },
                            "competitor": {
                                "status": "ready",
                                "hits": [
                                    {
                                        "id": "evidence-a",
                                        "source_name": "运行快照.xlsx",
                                        "score": 0.89,
                                        "content": "租户 A 运行时证据摘要",
                                    }
                                ],
                            },
                            "concept": {
                                "selected_candidate_id": "candidate-a",
                                "selected_candidate": {
                                    "id": "candidate-a",
                                    "name": "租户 A 正式选品",
                                    "validation_plan": {
                                        "status": "partial",
                                        "status_label": "部分具备，需补齐验证",
                                        "completed_gates": 0,
                                        "total_gates": 1,
                                        "completion_rate": 0,
                                        "requires_validation": True,
                                        "next_actions": ["完成样品测试"],
                                        "gates": [
                                            {
                                                "id": "sample_test",
                                                "label": "规格与样品",
                                                "status": "pending",
                                                "criteria": "完成样品测试",
                                                "materials": [],
                                            }
                                        ],
                                    },
                                },
                                "candidates": [
                                    {
                                        "id": "candidate-a",
                                        "name": "租户 A 正式选品",
                                        "validation_plan": {
                                            "status": "partial",
                                            "status_label": "部分具备，需补齐验证",
                                            "completed_gates": 0,
                                            "total_gates": 1,
                                            "completion_rate": 0,
                                            "requires_validation": True,
                                            "next_actions": ["完成样品测试"],
                                            "gates": [
                                                {
                                                    "id": "sample_test",
                                                    "label": "规格与样品",
                                                    "status": "pending",
                                                    "criteria": "完成样品测试",
                                                    "materials": [],
                                                }
                                            ],
                                        },
                                    }
                                ],
                            },
                        }
                    },
                ),
                PlanningRun(
                    id="run-b",
                    project_id="project-b",
                    thread_id="thread-b",
                    status="approval_required",
                    input_snapshot={},
                    result_snapshot={"scorecard": {"score": 74, "status": "review"}},
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                ApprovalTask(
                    id="approval-a",
                    project_id="project-a",
                    run_id="run-a",
                    approval_type="planning_review",
                    status="pending",
                    checkpoint_ref="checkpoint-a",
                    summary={"title": "租户 A 审批"},
                    due_at=datetime.now(UTC) - timedelta(hours=1),
                ),
                ApprovalTask(
                    id="approval-b",
                    project_id="project-b",
                    run_id="run-b",
                    approval_type="planning_review",
                    status="pending",
                    checkpoint_ref="checkpoint-b",
                    summary={"title": "租户 B 审批"},
                    due_at=datetime.now(UTC) + timedelta(hours=12),
                ),
                DataImportJob(
                    id="import-a",
                    tenant_id="tenant-a",
                    filename="tenant-a.xlsx",
                    storage_key="imports/tenant-a.xlsx",
                    source_type="tabular",
                    status="completed",
                    total_rows=2,
                    valid_rows=2,
                    invalid_rows=0,
                    created_by="planner-a",
                ),
                DataImportJob(
                    id="import-a-failed",
                    tenant_id="tenant-a",
                    filename="tenant-a-failed.xlsx",
                    storage_key="imports/tenant-a-failed.xlsx",
                    source_type="tabular",
                    status="failed",
                    total_rows=0,
                    valid_rows=0,
                    invalid_rows=0,
                    error_message="测试失败",
                    created_by="planner-a",
                ),
                DataImportJob(
                    id="import-a-v2",
                    tenant_id="tenant-a",
                    filename="tenant-a-v2.xlsx",
                    storage_key="imports/tenant-a-v2.xlsx",
                    source_type="tabular",
                    status="completed",
                    total_rows=3,
                    valid_rows=3,
                    invalid_rows=0,
                    created_by="planner-a",
                ),
                DataImportJob(
                    id="import-b",
                    tenant_id="tenant-b",
                    filename="tenant-b.xlsx",
                    storage_key="imports/tenant-b.xlsx",
                    source_type="tabular",
                    status="completed",
                    total_rows=1,
                    valid_rows=1,
                    invalid_rows=0,
                    created_by="planner-b",
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                SelectedProduct(
                    id="selection-a",
                    tenant_id="tenant-a",
                    project_id="project-a",
                    run_id="run-a",
                    approval_task_id="approval-a",
                    candidate_id="candidate-a",
                    name="租户 A 正式选品",
                    project_name="租户 A 项目",
                    category="保温杯",
                    target_market="中国",
                    positioning="通勤保温方案",
                    status="selected",
                    owner_id="planner-a",
                    score=88,
                    selling_price=199,
                    margin_rate=0.42,
                    estimated_profit=42000,
                    supplier_name="租户 A 供应商",
                    validation_status="partial",
                    selection_snapshot={"outputs": {"concept": {"selected_candidate_id": "candidate-a"}}},
                    selected_by="approver-a",
                    selected_at=datetime.now(UTC),
                ),
                SelectedProduct(
                    id="selection-b",
                    tenant_id="tenant-b",
                    project_id="project-b",
                    run_id="run-b",
                    approval_task_id="approval-b",
                    candidate_id="candidate-b",
                    name="租户 B 正式选品",
                    project_name="租户 B 项目",
                    category="咖啡机",
                    target_market="美国",
                    status="ready",
                    owner_id="admin-b",
                    selection_snapshot={"outputs": {"concept": {"selected_candidate_id": "candidate-b"}}},
                    selected_by="admin-b",
                    selected_at=datetime.now(UTC),
                ),
                EvidenceRecord(
                    id="evidence-a",
                    tenant_id="tenant-a",
                    import_job_id="import-a",
                    source_type="tabular",
                    source_name="tenant-a.xlsx",
                    source_row=2,
                    source_id="source-a",
                    content="租户 A 证据",
                    metadata_json={
                        "normalized_row": {
                            "source_id": "source-a",
                            "data_type": "竞品",
                            "category": "保温杯",
                            "target_market": "中国",
                            "data_source": "测试数据",
                        }
                    },
                    content_hash="hash-a",
                    quality_status="verified",
                    index_status="indexed",
                    observed_at=datetime(2026, 8, 20, tzinfo=UTC),
                ),
                EvidenceRecord(
                    id="evidence-a-reindex",
                    tenant_id="tenant-a",
                    import_job_id="import-a",
                    source_type="tabular",
                    source_name="tenant-a.xlsx",
                    source_row=3,
                    source_id="source-a-reindex",
                    content="租户 A 待重建索引证据",
                    metadata_json={
                        "normalized_row": {
                            "source_id": "source-a-reindex",
                            "data_type": "竞品",
                            "category": "保温杯",
                            "target_market": "中国",
                            "data_source": "测试数据",
                        },
                        "quality_issues": [
                            {
                                "field": "content",
                                "code": "content_too_short",
                                "message": "内容较短",
                                "severity": "warning",
                            }
                        ],
                    },
                    content_hash="hash-a-reindex",
                    quality_status="warning",
                    index_status="failed",
                    observed_at=datetime(2026, 8, 20, tzinfo=UTC),
                ),
                EvidenceRecord(
                    id="evidence-a-v2-unchanged",
                    tenant_id="tenant-a",
                    import_job_id="import-a-v2",
                    source_type="tabular",
                    source_name="tenant-a-v2.xlsx",
                    source_row=2,
                    source_id="source-a",
                    content="租户 A 证据",
                    metadata_json={
                        "normalized_row": {
                            "source_id": "source-a",
                            "data_type": "竞品",
                            "category": "保温杯",
                            "target_market": "中国",
                            "data_source": "测试数据",
                        }
                    },
                    content_hash="hash-a",
                    quality_status="verified",
                    index_status="indexed",
                    observed_at=datetime(2026, 8, 21, tzinfo=UTC),
                ),
                EvidenceRecord(
                    id="evidence-a-v2-changed",
                    tenant_id="tenant-a",
                    import_job_id="import-a-v2",
                    source_type="tabular",
                    source_name="tenant-a-v2.xlsx",
                    source_row=3,
                    source_id="source-a-reindex",
                    content="租户 A 已更新证据",
                    metadata_json={
                        "normalized_row": {
                            "source_id": "source-a-reindex",
                            "data_type": "竞品",
                            "category": "保温杯",
                            "target_market": "中国",
                            "data_source": "测试数据",
                        }
                    },
                    content_hash="hash-a-reindex-new",
                    quality_status="verified",
                    index_status="indexed",
                    observed_at=datetime(2026, 8, 21, tzinfo=UTC),
                ),
                EvidenceRecord(
                    id="evidence-a-v2-added",
                    tenant_id="tenant-a",
                    import_job_id="import-a-v2",
                    source_type="tabular",
                    source_name="tenant-a-v2.xlsx",
                    source_row=4,
                    source_id="source-a-new",
                    content="租户 A 新增证据",
                    metadata_json={
                        "normalized_row": {
                            "source_id": "source-a-new",
                            "data_type": "竞品",
                            "category": "保温杯",
                            "target_market": "中国",
                            "data_source": "测试数据",
                        }
                    },
                    content_hash="hash-a-new",
                    quality_status="verified",
                    index_status="indexed",
                    observed_at=datetime(2026, 8, 21, tzinfo=UTC),
                ),
                EvidenceRecord(
                    id="evidence-b",
                    tenant_id="tenant-b",
                    import_job_id="import-b",
                    source_type="tabular",
                    source_name="tenant-b.xlsx",
                    source_row=2,
                    source_id="source-b",
                    content="租户 B 证据",
                    metadata_json={},
                    content_hash="hash-b",
                    quality_status="verified",
                    index_status="indexed",
                ),
                PlanningReport(
                    id="report-a",
                    project_id="project-a",
                    run_id="run-a",
                    format="xlsx",
                    status="completed",
                    storage_key="reports/report-a.xlsx",
                    created_by="planner-a",
                ),
                PlanningReport(
                    id="report-b",
                    project_id="project-b",
                    run_id="run-b",
                    format="xlsx",
                    status="completed",
                    storage_key="reports/report-b.xlsx",
                    created_by="planner-b",
                ),
                AuditEvent(
                    id="audit-a",
                    tenant_id="tenant-a",
                    project_id="project-a",
                    actor_id="planner-a",
                    action="project.created",
                    entity_type="planning_project",
                    entity_id="project-a",
                    detail={},
                ),
                AuditEvent(
                    id="audit-b",
                    tenant_id="tenant-b",
                    project_id="project-b",
                    actor_id="planner-b",
                    action="project.created",
                    entity_type="planning_project",
                    entity_id="project-b",
                    detail={},
                ),
            ]
        )
        await session.commit()


@pytest.fixture
async def tenant_client() -> AsyncIterator[AsyncClient]:
    """创建覆盖数据库会话和身份依赖的测试客户端，并在用例结束后恢复应用状态。"""
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is required for integration tests")

    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    await seed_tenants(session_factory)

    async def override_db_session() -> AsyncIterator[AsyncSession]:
        """让接口测试复用当前集成测试会话，确保数据准备与请求位于同一数据库。"""
        async with session_factory() as session:
            yield session

    async def override_identity(
        authorization_header: str | None = Header(default=None, alias="Authorization"),
    ) -> Identity:
        """把当前测试身份注入FastAPI依赖，便于逐角色验证访问边界。"""
        subject = (authorization_header or "").removeprefix("Bearer ").strip()
        return identity_for(subject)

    app.dependency_overrides[get_db_session] = override_db_session
    app.dependency_overrides[get_current_identity] = override_identity
    app.state.integration_session_factory = session_factory
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_current_identity, None)
        del app.state.integration_session_factory
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


async def test_tenant_lists_only_return_owned_business_data(tenant_client: AsyncClient) -> None:
    """验证“tenant lists only return owned business data”场景，确保业务规则、权限和异常边界保持稳定。"""
    viewer_headers = authorization("tenant-a-viewer")

    projects = await tenant_client.get("/api/v1/planning-projects", headers=viewer_headers)
    projects_page = await tenant_client.get(
        "/api/v1/planning-projects/page",
        params={"keyword": "租户 A", "status": "approval_required", "page": 1, "page_size": 1},
        headers=viewer_headers,
    )
    isolated_projects_page = await tenant_client.get(
        "/api/v1/planning-projects/page",
        params={"project_id": "project-a", "page": 1, "page_size": 1},
        headers=authorization("tenant-b-viewer"),
    )
    runs_page = await tenant_client.get(
        "/api/v1/planning-projects/project-a/runs/page",
        params={"page": 1, "page_size": 1},
        headers=viewer_headers,
    )
    isolated_runs_page = await tenant_client.get(
        "/api/v1/planning-projects/project-a/runs/page",
        params={"page": 1, "page_size": 1},
        headers=authorization("tenant-b-viewer"),
    )
    approvals = await tenant_client.get("/api/v1/approval-tasks", headers=viewer_headers)
    approvals_page = await tenant_client.get(
        "/api/v1/approval-tasks/page",
        params={"status": "overdue", "assignee": "unassigned", "page": 1, "page_size": 1},
        headers=viewer_headers,
    )
    isolated_approvals_page = await tenant_client.get(
        "/api/v1/approval-tasks/page",
        params={"status": "all", "project_id": "project-a", "page": 1, "page_size": 1},
        headers=authorization("tenant-b-viewer"),
    )
    imports = await tenant_client.get("/api/v1/data-imports", headers=viewer_headers)
    imports_page = await tenant_client.get(
        "/api/v1/data-imports/page",
        params={"status": "completed", "keyword": "tenant-a", "page": 1, "page_size": 1},
        headers=viewer_headers,
    )
    isolated_imports_page = await tenant_client.get(
        "/api/v1/data-imports/page",
        params={"import_id": "import-b", "page": 1, "page_size": 1},
        headers=viewer_headers,
    )
    selected_products = await tenant_client.get(
        "/api/v1/selected-products",
        headers=viewer_headers,
    )
    selected_products_page = await tenant_client.get(
        "/api/v1/selected-products/page",
        params={"page": 1, "page_size": 1, "keyword": "正式选品"},
        headers=viewer_headers,
    )
    opportunities = await tenant_client.get("/api/v1/analytics/opportunities", headers=viewer_headers)
    opportunities_page = await tenant_client.get(
        "/api/v1/analytics/opportunities/page",
        params={"page": 1, "page_size": 1},
        headers=viewer_headers,
    )
    lifecycles_page = await tenant_client.get(
        "/api/v1/analytics/project-lifecycles/page",
        params={"page": 1, "page_size": 1},
        headers=viewer_headers,
    )
    isolated_lifecycles_page = await tenant_client.get(
        "/api/v1/analytics/project-lifecycles/page",
        params={"keyword": "租户 A", "page": 1, "page_size": 1},
        headers=authorization("tenant-b-viewer"),
    )
    isolated_opportunities_page = await tenant_client.get(
        "/api/v1/analytics/opportunities/page",
        params={"page": 1, "page_size": 1},
        headers=authorization("tenant-b-viewer"),
    )
    dashboard = await tenant_client.get("/api/v1/analytics/dashboard", headers=viewer_headers)
    isolated_dashboard = await tenant_client.get(
        "/api/v1/analytics/dashboard",
        headers=authorization("tenant-b-viewer"),
    )
    viewer_notifications = await tenant_client.get(
        "/api/v1/analytics/notifications",
        headers=viewer_headers,
    )
    approver_notifications = await tenant_client.get(
        "/api/v1/analytics/notifications",
        headers=authorization("tenant-a-approver"),
    )
    admin_notifications = await tenant_client.get(
        "/api/v1/analytics/notifications",
        headers=authorization("tenant-a-admin"),
    )
    isolated_notifications = await tenant_client.get(
        "/api/v1/analytics/notifications",
        headers=authorization("tenant-b-viewer"),
    )
    evidence = await tenant_client.get(
        "/api/v1/data-imports/import-a/evidence",
        headers=viewer_headers,
    )
    warning_evidence = await tenant_client.get(
        "/api/v1/data-imports/import-a/evidence",
        params={"quality_status": "warning"},
        headers=viewer_headers,
    )
    evidence_by_id = await tenant_client.get(
        "/api/v1/data-imports/import-a/evidence",
        params={"keyword": "evidence-a"},
        headers=viewer_headers,
    )
    evidence_page = await tenant_client.get(
        "/api/v1/data-imports/import-a/evidence/page",
        params={"page": 1, "page_size": 1},
        headers=viewer_headers,
    )
    issue_summary = await tenant_client.get(
        "/api/v1/data-imports/import-a/quality-issues-summary",
        headers=viewer_headers,
    )
    reports = await tenant_client.get(
        "/api/v1/planning-projects/project-a/runs/run-a/reports",
        headers=viewer_headers,
    )
    reports_page = await tenant_client.get(
        "/api/v1/planning-projects/project-a/runs/run-a/reports/page",
        params={"page": 1, "page_size": 1},
        headers=viewer_headers,
    )
    audits = await tenant_client.get(
        "/api/v1/audit-events",
        headers=authorization("tenant-a-admin"),
    )
    paged_audits = await tenant_client.get(
        "/api/v1/audit-events",
        params={"limit": 1, "offset": 0},
        headers=authorization("tenant-a-admin"),
    )

    assert projects.status_code == 200
    assert {item["id"] for item in projects.json()} == {"project-a"}
    assert projects_page.status_code == 200
    assert projects_page.headers["X-Total-Count"] == "1"
    assert projects_page.json()["total"] == 1
    assert projects_page.json()["page"] == 1
    assert projects_page.json()["page_size"] == 1
    assert [item["id"] for item in projects_page.json()["items"]] == ["project-a"]
    assert projects_page.json()["summary"] == {
        "total": 1,
        "draft": 0,
        "queued": 0,
        "running": 0,
        "approval_required": 1,
        "completed": 0,
        "failed": 0,
        "cancelled": 0,
    }
    assert isolated_projects_page.status_code == 200
    assert isolated_projects_page.headers["X-Total-Count"] == "0"
    assert isolated_projects_page.json()["items"] == []
    assert runs_page.status_code == 200
    assert runs_page.headers["X-Total-Count"] == "1"
    assert runs_page.json()["total"] == 1
    assert runs_page.json()["page"] == 1
    assert runs_page.json()["page_size"] == 1
    assert [item["id"] for item in runs_page.json()["items"]] == ["run-a"]
    assert runs_page.json()["summary"] == {
        "total": 1,
        "queued": 0,
        "running": 0,
        "approval_required": 1,
        "completed": 0,
        "failed": 0,
        "cancelled": 0,
        "superseded": 0,
        "active": 1,
    }
    assert isolated_runs_page.status_code == 404
    assert approvals.status_code == 200
    assert {item["id"] for item in approvals.json()} == {"approval-a"}
    assert approvals_page.status_code == 200
    assert approvals_page.headers["X-Total-Count"] == "1"
    assert approvals_page.json()["total"] == 1
    assert approvals_page.json()["page"] == 1
    assert approvals_page.json()["page_size"] == 1
    assert [item["id"] for item in approvals_page.json()["items"]] == ["approval-a"]
    assert approvals_page.json()["summary"] == {
        "total": 1,
        "pending": 1,
        "approved": 0,
        "rejected": 0,
        "revision_required": 0,
        "cancelled": 0,
        "processed": 0,
        "overdue": 1,
        "due_soon": 0,
        "mine_pending": 0,
        "unassigned_pending": 1,
    }
    assert approvals_page.json()["project_options"] == [
        {"value": "project-a", "label": "租户 A 项目"}
    ]
    assert isolated_approvals_page.status_code == 200
    assert isolated_approvals_page.headers["X-Total-Count"] == "0"
    assert isolated_approvals_page.json()["items"] == []
    assert imports.status_code == 200
    assert {item["id"] for item in imports.json()} == {
        "import-a",
        "import-a-failed",
        "import-a-v2",
    }
    import_a = next(item for item in imports.json() if item["id"] == "import-a")
    assert import_a["indexable_rows"] == 2
    assert import_a["indexed_rows"] == 1
    assert import_a["pending_index_rows"] == 0
    assert import_a["failed_index_rows"] == 1
    assert import_a["retrieval_status"] == "failed"
    assert import_a["retrieval_ready"] is False
    assert imports_page.status_code == 200
    assert imports_page.headers["X-Total-Count"] == "2"
    assert imports_page.json()["total"] == 2
    assert imports_page.json()["page"] == 1
    assert imports_page.json()["page_size"] == 1
    assert len(imports_page.json()["items"]) == 1
    assert imports_page.json()["items"][0]["status"] == "completed"
    assert imports_page.json()["summary"] == {
        "total": 3,
        "queued": 0,
        "processing": 0,
        "completed": 2,
        "failed": 1,
    }
    assert isolated_imports_page.status_code == 200
    assert isolated_imports_page.headers["X-Total-Count"] == "0"
    assert isolated_imports_page.json()["items"] == []
    assert selected_products.status_code == 200
    assert {item["id"] for item in selected_products.json()} == {"selection-a"}
    assert selected_products_page.status_code == 200
    assert selected_products_page.headers["X-Total-Count"] == "1"
    assert selected_products_page.json()["page"] == 1
    assert selected_products_page.json()["page_size"] == 1
    assert [item["id"] for item in selected_products_page.json()["items"]] == ["selection-a"]
    assert selected_products_page.json()["summary"] == {
        "total": 1,
        "validating": 1,
        "ready": 0,
        "initiated": 0,
        "paused": 0,
    }
    assert opportunities.status_code == 200
    assert {item["project_id"] for item in opportunities.json()} == {"project-a"}
    assert opportunities_page.status_code == 200
    assert opportunities_page.headers["X-Total-Count"] == "1"
    assert opportunities_page.json()["total"] == 1
    assert opportunities_page.json()["page"] == 1
    assert opportunities_page.json()["page_size"] == 1
    assert [item["project_id"] for item in opportunities_page.json()["items"]] == ["project-a"]
    assert lifecycles_page.status_code == 200
    assert lifecycles_page.headers["X-Total-Count"] == "1"
    assert lifecycles_page.json()["total"] == 1
    lifecycle = lifecycles_page.json()["items"][0]
    assert lifecycle["project_id"] == "project-a"
    assert lifecycle["run_id"] == "run-a"
    assert lifecycle["approval_task_id"] == "approval-a"
    assert lifecycle["selected_product_id"] == "selection-a"
    assert lifecycle["initiative_id"] is None
    assert lifecycle["stage"] == "validation"
    assert lifecycle["next_action_type"] == "selected-product"
    assert lifecycles_page.json()["summary"] == {
        "total": 1,
        "blocked": 0,
        "waiting_human": 0,
        "active": 1,
        "complete": 0,
    }
    assert isolated_lifecycles_page.status_code == 200
    assert isolated_lifecycles_page.headers["X-Total-Count"] == "0"
    assert isolated_lifecycles_page.json()["items"] == []
    assert isolated_opportunities_page.status_code == 200
    assert isolated_opportunities_page.headers["X-Total-Count"] == "1"
    assert [item["project_id"] for item in isolated_opportunities_page.json()["items"]] == [
        "project-b"
    ]
    assert dashboard.status_code == 200
    assert dashboard.json()["latest_project"]["id"] == "project-a"
    assert dashboard.json()["latest_opportunity"]["run_id"] == "run-a"
    assert dashboard.json()["latest_selection"]["id"] == "selection-a"
    assert dashboard.json()["latest_pending_selection"]["id"] == "selection-a"
    assert dashboard.json()["latest_approval"]["id"] == "approval-a"
    assert dashboard.json()["project_total"] == 1
    assert dashboard.json()["active_project_total"] == 1
    assert dashboard.json()["completed_project_total"] == 0
    assert dashboard.json()["pending_approval_count"] == 1
    assert dashboard.json()["pending_launch_review_count"] == 0
    assert dashboard.json()["selected_product_total"] == 1
    assert dashboard.json()["selected_product_validating"] == 1
    assert dashboard.json()["selected_product_ready"] == 0
    assert dashboard.json()["active_initiative_total"] == 0
    assert isolated_dashboard.status_code == 200
    assert isolated_dashboard.json()["latest_project"]["id"] == "project-b"
    assert isolated_dashboard.json()["latest_opportunity"]["run_id"] == "run-b"
    assert isolated_dashboard.json()["latest_selection"]["id"] == "selection-b"
    assert isolated_dashboard.json()["project_total"] == 1
    assert isolated_dashboard.json()["pending_approval_count"] == 1
    assert isolated_dashboard.json()["selected_product_total"] == 1
    assert viewer_notifications.status_code == 200
    assert viewer_notifications.json()["actionable_approval_count"] == 0
    assert viewer_notifications.json()["overdue_actionable_approval_count"] == 0
    assert viewer_notifications.json()["new_selection_count"] == 1
    assert viewer_notifications.json()["latest_new_selection"] == {
        "id": "selection-a",
        "label": "租户 A 正式选品",
    }
    assert viewer_notifications.json()["ready_selection_count"] == 0


    assert viewer_notifications.json()["awaiting_approval_project_count"] == 1
    assert viewer_notifications.json()["latest_awaiting_approval_project"]["id"] == "project-a"
    assert viewer_notifications.json()["failed_import_count"] == 1
    assert viewer_notifications.json()["latest_failed_import"]["id"] == "import-a-failed"
    assert viewer_notifications.json()["invalid_import_count"] == 0
    assert viewer_notifications.json()["pending_index_import"] is None
    assert approver_notifications.status_code == 200
    assert approver_notifications.json()["actionable_approval_count"] == 1
    assert approver_notifications.json()["overdue_actionable_approval_count"] == 1
    assert approver_notifications.json()["latest_overdue_approval"]["id"] == "approval-a"
    assert admin_notifications.status_code == 200
    assert admin_notifications.json()["actionable_approval_count"] == 1
    assert admin_notifications.json()["latest_overdue_approval"]["id"] == "approval-a"
    assert isolated_notifications.status_code == 200
    assert isolated_notifications.json()["actionable_approval_count"] == 0
    assert isolated_notifications.json()["new_selection_count"] == 0
    assert isolated_notifications.json()["ready_selection_count"] == 1
    assert isolated_notifications.json()["latest_ready_selection"] == {
        "id": "selection-b",
        "label": "租户 B 正式选品",
    }
    assert isolated_notifications.json()["failed_import_count"] == 0
    assert isolated_notifications.json()["awaiting_approval_project_count"] == 1
    assert isolated_notifications.json()["latest_awaiting_approval_project"]["id"] == "project-b"
    assert evidence.status_code == 200
    assert len(evidence.json()) == 2
    assert warning_evidence.status_code == 200
    assert {item["id"] for item in warning_evidence.json()} == {"evidence-a-reindex"}
    assert evidence_by_id.status_code == 200
    assert {item["id"] for item in evidence_by_id.json()} == {"evidence-a", "evidence-a-reindex"}
    assert evidence_page.status_code == 200
    assert evidence_page.headers["X-Total-Count"] == "2"
    assert evidence_page.json()["total"] == 2
    assert evidence_page.json()["page"] == 1
    assert evidence_page.json()["page_size"] == 1
    assert [item["id"] for item in evidence_page.json()["items"]] == ["evidence-a"]
    assert issue_summary.status_code == 200
    assert issue_summary.json()["warning_records"] == 1
    assert issue_summary.json()["failed_index_records"] == 1
    assert issue_summary.json()["issues"][0]["code"] == "content_too_short"
    assert reports.status_code == 200
    assert {item["id"] for item in reports.json()} == {"report-a"}
    assert reports_page.status_code == 200
    assert reports_page.headers["X-Total-Count"] == "1"
    assert reports_page.json()["total"] == 1
    assert reports_page.json()["page"] == 1
    assert reports_page.json()["page_size"] == 1
    assert [item["id"] for item in reports_page.json()["items"]] == ["report-a"]
    assert audits.status_code == 200
    assert {item["id"] for item in audits.json()} == {"audit-a"}
    assert paged_audits.status_code == 200
    assert paged_audits.headers["X-Total-Count"] == "1"
    assert [item["id"] for item in paged_audits.json()] == ["audit-a"]


async def test_project_context_scopes_module_lists_and_summaries(
    tenant_client: AsyncClient,
) -> None:
    """验证同租户切换项目后，审批、选品、立项与上市评审的列表和汇总保持同一口径。"""
    now = datetime.now(UTC)
    async with app.state.integration_session_factory() as session:
        session.add(
            PlanningProject(
                id="project-a-secondary",
                tenant_id="tenant-a",
                name="租户 A 第二项目",
                category="户外电源",
                target_market="欧洲",
                status="completed",
                constraints={},
                created_by="planner-a",
            )
        )
        await session.flush()
        session.add(
            PlanningRun(
                id="run-a-secondary",
                project_id="project-a-secondary",
                thread_id="thread-a-secondary",
                status="completed",
                input_snapshot={},
                result_snapshot={"scorecard": {"score": 91, "status": "approved"}},
            )
        )
        await session.flush()
        session.add(
            ApprovalTask(
                id="approval-a-secondary",
                project_id="project-a-secondary",
                run_id="run-a-secondary",
                approval_type="planning_review",
                status="approved",
                checkpoint_ref="checkpoint-a-secondary",
                summary={"title": "租户 A 第二项目审批"},
                decided_by="approver-a",
                decided_at=now,
            )
        )
        await session.flush()
        session.add(
            SelectedProduct(
                id="selection-a-secondary",
                tenant_id="tenant-a",
                project_id="project-a-secondary",
                run_id="run-a-secondary",
                approval_task_id="approval-a-secondary",
                candidate_id="candidate-a-secondary",
                name="租户 A 第二项目正式选品",
                project_name="租户 A 第二项目",
                category="户外电源",
                target_market="欧洲",
                status="paused",
                validation_status="partial",
                selection_snapshot={},
                selected_by="approver-a",
                selected_at=now,
            )
        )
        await session.flush()
        session.add_all(
            [
                ProductInitiative(
                    id="initiative-a-primary",
                    tenant_id="tenant-a",
                    selected_product_id="selection-a",
                    project_id="project-a",
                    run_id="run-a",
                    name="租户 A 主项目立项",
                    category="保温杯",
                    target_market="中国",
                    status="in_progress",
                    milestones=[],
                    created_by="planner-a",
                ),
                ProductInitiative(
                    id="initiative-a-secondary",
                    tenant_id="tenant-a",
                    selected_product_id="selection-a-secondary",
                    project_id="project-a-secondary",
                    run_id="run-a-secondary",
                    name="租户 A 第二项目立项",
                    category="户外电源",
                    target_market="欧洲",
                    status="launched",
                    milestones=[],
                    created_by="planner-a",
                    launched_at=now,
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                ProductLaunchReview(
                    id="launch-review-a-primary",
                    tenant_id="tenant-a",
                    initiative_id="initiative-a-primary",
                    status="pending",
                    readiness_snapshot={"readiness_status": "review"},
                    submitted_by="planner-a",
                    submitted_at=now,
                ),
                ProductLaunchReview(
                    id="launch-review-a-secondary",
                    tenant_id="tenant-a",
                    initiative_id="initiative-a-secondary",
                    status="approved",
                    readiness_snapshot={"readiness_status": "ready"},
                    submitted_by="planner-a",
                    submitted_at=now,
                    decided_by="approver-a",
                    decided_at=now,
                ),
            ]
        )
        await session.commit()

    headers = authorization("tenant-a-viewer")
    approvals = await tenant_client.get(
        "/api/v1/approval-tasks/page",
        params={"status": "all", "project_id": "project-a", "page": 1, "page_size": 10},
        headers=headers,
    )
    selections = await tenant_client.get(
        "/api/v1/selected-products/page",
        params={"project_id": "project-a", "page": 1, "page_size": 10},
        headers=headers,
    )
    initiatives = await tenant_client.get(
        "/api/v1/product-initiatives/page",
        params={"project_id": "project-a", "page": 1, "page_size": 10},
        headers=headers,
    )
    launch_reviews = await tenant_client.get(
        "/api/v1/product-initiatives/launch-reviews/page",
        params={"project_id": "project-a", "page": 1, "page_size": 10},
        headers=headers,
    )

    assert approvals.status_code == 200
    assert [item["id"] for item in approvals.json()["items"]] == ["approval-a"]
    assert approvals.json()["summary"]["total"] == 1
    assert approvals.json()["summary"]["pending"] == 1
    assert approvals.json()["summary"]["approved"] == 0
    assert selections.status_code == 200
    assert [item["id"] for item in selections.json()["items"]] == ["selection-a"]
    assert selections.json()["summary"] == {
        "total": 1,
        "validating": 1,
        "ready": 0,
        "initiated": 0,
        "paused": 0,
    }
    assert selections.json()["categories"] == ["保温杯"]
    assert initiatives.status_code == 200
    assert [item["id"] for item in initiatives.json()["items"]] == ["initiative-a-primary"]
    assert initiatives.json()["summary"] == {
        "total": 1,
        "active": 1,
        "attention": 0,
        "ready": 0,
        "launched": 0,
    }
    assert launch_reviews.status_code == 200
    assert [item["id"] for item in launch_reviews.json()["items"]] == [
        "launch-review-a-primary"
    ]
    assert launch_reviews.json()["summary"] == {
        "total": 1,
        "pending": 1,
        "approved": 0,
        "rejected": 0,
        "revision_required": 0,
        "processed": 0,
    }
    assert launch_reviews.json()["items"][0]["project_id"] == "project-a"


async def test_retrieval_endpoint_uses_current_tenant_context(
    tenant_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证“retrieval endpoint uses current tenant context”场景，确保业务规则、权限和异常边界保持稳定。"""
    calls: list[dict[str, object]] = []

    class StubRetriever:
        """提供`StubRetriever`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
        async def search(self, query: str, **kwargs: object) -> dict[str, object]:
            """辅助构造`search`测试数据或依赖，减少用例中的重复准备代码。"""
            calls.append({"query": query, **kwargs})
            return {
                "status": "ready",
                "reason": None,
                "query": query,
                "evidence_ids": ["evidence-a"],
                "hits": [
                    {
                        "id": "evidence-a",
                        "score": 0.91,
                        "vector_score": 0.82,
                        "source_name": "tenant-a.xlsx",
                        "category": "保温杯",
                        "target_market": "中国",
                        "quality_status": "verified",
                        "content": "租户 A 证据",
                        "metadata": {},
                    }
                ],
                "governance": {
                    "canonical_evidence_ids": [],
                    "suppressed_evidence_ids": [],
                    "applied_review_ids": [],
                    "conflicting_review_ids": [],
                },
            }

    monkeypatch.setattr(retrieval_route_module, "get_evidence_retriever", lambda: StubRetriever())
    response = await tenant_client.post(
        "/api/v1/retrieval/search",
        headers=authorization("tenant-a-viewer"),
        json={
            "query": "  中国 保温杯市场  ",
            "category": " 保温杯 ",
            "target_market": " 中国 ",
            "top_k": 3,
        },
    )

    assert response.status_code == 200
    assert response.json()["hits"][0]["evidence_id"] == "evidence-a"
    assert calls == [
        {
            "query": "中国 保温杯市场",
            "tenant_id": "tenant-a",
            "category": "保温杯",
            "target_market": "中国",
            "top_k": 3,
        }
    ]

    invalid = await tenant_client.post(
        "/api/v1/retrieval/search",
        headers=authorization("tenant-a-viewer"),
        json={"query": "   "},
    )
    assert invalid.status_code == 422


async def test_cross_tenant_resource_reads_are_hidden(tenant_client: AsyncClient) -> None:
    """验证“cross tenant resource reads are hidden”场景，确保业务规则、权限和异常边界保持稳定。"""
    headers = authorization("tenant-a-viewer")
    paths = [
        "/api/v1/planning-projects/project-b",
        "/api/v1/planning-projects/project-b/runs",
        "/api/v1/planning-projects/project-b/runs/run-b",
        "/api/v1/planning-projects/project-b/runs/run-b/evidence",
        "/api/v1/planning-projects/project-b/runs/run-b/evidence/page",
        "/api/v1/planning-projects/project-b/runs/run-b/reports",
        "/api/v1/planning-projects/project-b/runs/run-b/reports/page",
        "/api/v1/approval-tasks/approval-b",
        "/api/v1/selected-products/selection-b",
        "/api/v1/selected-products/selection-b/timeline/page",
        "/api/v1/data-imports/import-b",
        "/api/v1/data-imports/import-b/evidence",
        "/api/v1/data-imports/import-b/evidence/page",
        "/api/v1/data-imports/import-b/quality-report",
        "/api/v1/data-imports/import-b/quality-issues-summary",
        "/api/v1/data-imports/import-a/compare/import-b",
        "/api/v1/planning-reports/report-b",
        "/api/v1/planning-reports/report-b/download",
    ]

    for path in paths:
        response = await tenant_client.get(path, headers=headers)
        assert response.status_code == 404, path


async def test_cross_tenant_writes_and_role_escalation_are_rejected(
    tenant_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    monkeypatch.setattr(
        imports_route_module.MilvusVectorStore,
        "delete",
        lambda store, evidence_ids: {"delete_count": len(evidence_ids)},
    )
    viewer_create = await tenant_client.post(
        "/api/v1/planning-projects",
        headers=authorization("tenant-a-viewer"),
        json={
            "name": "无权限项目",
            "category": "测试",
            "target_market": "中国",
            "constraints": {},
        },
    )
    viewer_audit = await tenant_client.get(
        "/api/v1/audit-events",
        headers=authorization("tenant-a-viewer"),
    )
    cross_project_update = await tenant_client.patch(
        "/api/v1/planning-projects/project-b",
        headers=authorization("tenant-a-planner"),
        json={"name": "越权修改"},
    )
    cross_approval = await tenant_client.post(
        "/api/v1/approval-tasks/approval-b/decision",
        headers=authorization("tenant-a-approver"),
        json={"action": "approved", "comment": "越权审批", "changes": {}},
    )
    viewer_selection_update = await tenant_client.patch(
        "/api/v1/selected-products/selection-a",
        headers=authorization("tenant-a-viewer"),
        json={"status": "ready"},
    )
    cross_selection_update = await tenant_client.patch(
        "/api/v1/selected-products/selection-b",
        headers=authorization("tenant-a-planner"),
        json={"status": "paused"},
    )
    viewer_retry = await tenant_client.post(
        "/api/v1/data-imports/import-a-failed/retry",
        headers=authorization("tenant-a-viewer"),
    )
    viewer_reindex = await tenant_client.post(
        "/api/v1/data-imports/import-a/reindex",
        headers=authorization("tenant-a-viewer"),
    )
    viewer_quality_review = await tenant_client.patch(
        "/api/v1/data-imports/import-a/evidence/evidence-a-reindex/quality-review",
        headers=authorization("tenant-a-viewer"),
        json={"action": "verify"},
    )
    cross_quality_review = await tenant_client.patch(
        "/api/v1/data-imports/import-b/evidence/evidence-b/quality-review",
        headers=authorization("tenant-a-planner"),
        json={"action": "block", "note": "越权处理"},
    )
    viewer_withdraw = await tenant_client.delete(
        "/api/v1/data-imports/import-a",
        headers=authorization("tenant-a-viewer"),
    )

    assert viewer_create.status_code == 403
    assert viewer_audit.status_code == 403
    assert cross_project_update.status_code == 404
    assert cross_approval.status_code == 404
    assert viewer_selection_update.status_code == 403
    assert cross_selection_update.status_code == 404
    assert viewer_retry.status_code == 403
    assert viewer_reindex.status_code == 403
    assert viewer_quality_review.status_code == 403
    assert cross_quality_review.status_code == 404
    assert viewer_withdraw.status_code == 403

    untouched_project = await tenant_client.get(
        "/api/v1/planning-projects/project-b",
        headers=authorization("tenant-b-viewer"),
    )
    untouched_approval = await tenant_client.get(
        "/api/v1/approval-tasks/approval-b",
        headers=authorization("tenant-b-viewer"),
    )
    assert untouched_project.json()["name"] == "租户 B 项目"
    assert untouched_approval.json()["status"] == "pending"


async def test_planner_can_update_selected_product_registry(
    tenant_client: AsyncClient,
) -> None:
    """验证“planner can update selected product registry”场景，确保业务规则、权限和异常边界保持稳定。"""
    invalid_ready = await tenant_client.patch(
        "/api/v1/selected-products/selection-a",
        headers=authorization("tenant-a-planner"),
        json={"status": "ready"},
    )
    updated = await tenant_client.patch(
        "/api/v1/selected-products/selection-a",
        headers=authorization("tenant-a-planner"),
        json={
            "status": "validating",
            "owner_id": "owner-a",
            "notes": "样品和供应报价验证中",
        },
    )
    filtered = await tenant_client.get(
        "/api/v1/selected-products?status=validating",
        headers=authorization("tenant-a-viewer"),
    )
    audits = await tenant_client.get(
        "/api/v1/audit-events?entity_type=selected_product",
        headers=authorization("tenant-a-admin"),
    )

    assert invalid_ready.status_code == 409
    assert updated.status_code == 200
    assert updated.json()["status"] == "validating"
    assert updated.json()["owner_id"] == "owner-a"
    assert updated.json()["notes"] == "样品和供应报价验证中"
    assert {item["id"] for item in filtered.json()} == {"selection-a"}
    assert any(
        item["action"] == "selected_product.updated" and item["entity_id"] == "selection-a"
        for item in audits.json()
    )


async def test_selected_product_ready_requires_completed_validation(
    tenant_client: AsyncClient,
) -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    response = await tenant_client.patch(
        "/api/v1/selected-products/selection-b",
        headers=authorization("tenant-b-admin"),
        json={"status": "ready"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "落地验证尚未完成，不能标记为可进入立项"


async def test_web_validation_gate_requires_available_material(
    tenant_client: AsyncClient,
) -> None:
    """验证普通网页客户端不能绕过人工验证材料直接标记验证通过。"""
    response = await tenant_client.patch(
        "/api/v1/planning-projects/project-a/runs/run-a/validation-plan",
        headers=authorization("tenant-a-planner"),
        json={
            "candidate_id": "candidate-a",
            "gates": [
                {
                    "gate_id": "sample_test",
                    "status": "ready",
                    "note": "网页客户端未上传材料，不应通过",
                }
            ],
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "标记验证通过前必须先由人工上传可用验证材料"


async def test_cancelled_selected_product_cannot_resume_or_initiate(
    tenant_client: AsyncClient,
) -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    cancelled = await tenant_client.patch(
        "/api/v1/selected-products/selection-a",
        headers=authorization("tenant-a-planner"),
        json={"status": "cancelled"},
    )
    resume = await tenant_client.patch(
        "/api/v1/selected-products/selection-a",
        headers=authorization("tenant-a-planner"),
        json={"status": "selected"},
    )
    initiate = await tenant_client.patch(
        "/api/v1/selected-products/selection-a",
        headers=authorization("tenant-a-planner"),
        json={"status": "ready"},
    )

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert resume.status_code == 409
    assert resume.json()["detail"] == "已取消正式选品不能恢复或继续推进"
    assert initiate.status_code == 409
    assert initiate.json()["detail"] == "已取消正式选品不能恢复或继续推进"


async def test_initiative_status_syncs_selected_product_registry(
    tenant_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证“initiative status syncs selected product registry”场景，确保业务规则、权限和异常边界保持稳定。"""
    material = await upload_test_validation_material(
        tenant_client,
        monkeypatch,
        note="立项状态同步测试材料",
    )
    validation_plan = await tenant_client.patch(
        "/api/v1/planning-projects/project-a/runs/run-a/validation-plan",
        headers=authorization("tenant-a-planner"),
        json={
            "candidate_id": "candidate-a",
            "gates": [
                {
                    "gate_id": "sample_test",
                    "status": "ready",
                    "note": "立项状态同步测试完成验证",
                }
            ],
        },
    )
    initiative = await tenant_client.post(
        "/api/v1/product-initiatives",
        headers=authorization("tenant-a-planner"),
        json={"selected_product_id": "selection-a"},
    )
    initiative_id = initiative.json()["id"]
    paused = await tenant_client.patch(
        f"/api/v1/product-initiatives/{initiative_id}",
        headers=authorization("tenant-a-planner"),
        json={"status": "paused"},
    )
    direct_override = await tenant_client.patch(
        "/api/v1/selected-products/selection-a",
        headers=authorization("tenant-a-planner"),
        json={"status": "selected"},
    )
    paused_product = await tenant_client.get(
        "/api/v1/selected-products/selection-a",
        headers=authorization("tenant-a-viewer"),
    )
    resumed = await tenant_client.patch(
        f"/api/v1/product-initiatives/{initiative_id}",
        headers=authorization("tenant-a-planner"),
        json={"status": "in_progress"},
    )
    resumed_product = await tenant_client.get(
        "/api/v1/selected-products/selection-a",
        headers=authorization("tenant-a-viewer"),
    )
    cancelled = await tenant_client.patch(
        f"/api/v1/product-initiatives/{initiative_id}",
        headers=authorization("tenant-a-planner"),
        json={"status": "cancelled"},
    )
    cancelled_product = await tenant_client.get(
        "/api/v1/selected-products/selection-a",
        headers=authorization("tenant-a-viewer"),
    )

    assert material.status_code == 201
    assert validation_plan.status_code == 200
    assert initiative.status_code == 201
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    assert direct_override.status_code == 409
    assert direct_override.json()["detail"] == "进入立项后的商品状态只能由商品立项流程更新"
    assert paused_product.json()["status"] == "paused"
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "in_progress"
    assert resumed_product.json()["status"] == "initiated"
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled_product.json()["status"] == "cancelled"


async def test_cancelled_initiative_cannot_resume_or_launch(
    tenant_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证“cancelled initiative cannot resume or launch”场景，确保业务规则、权限和异常边界保持稳定。"""
    material = await upload_test_validation_material(
        tenant_client,
        monkeypatch,
        note="取消状态回归测试材料",
    )
    validation_plan = await tenant_client.patch(
        "/api/v1/planning-projects/project-a/runs/run-a/validation-plan",
        headers=authorization("tenant-a-planner"),
        json={
            "candidate_id": "candidate-a",
            "gates": [
                {
                    "gate_id": "sample_test",
                    "status": "ready",
                    "note": "取消状态回归测试完成验证",
                }
            ],
        },
    )
    initiative = await tenant_client.post(
        "/api/v1/product-initiatives",
        headers=authorization("tenant-a-planner"),
        json={"selected_product_id": "selection-a"},
    )
    initiative_id = initiative.json()["id"]
    cancelled = await tenant_client.patch(
        f"/api/v1/product-initiatives/{initiative_id}",
        headers=authorization("tenant-a-planner"),
        json={"status": "cancelled"},
    )
    resume = await tenant_client.patch(
        f"/api/v1/product-initiatives/{initiative_id}",
        headers=authorization("tenant-a-planner"),
        json={"status": "in_progress"},
    )
    launch = await tenant_client.patch(
        f"/api/v1/product-initiatives/{initiative_id}",
        headers=authorization("tenant-a-planner"),
        json={"status": "launched"},
    )

    assert material.status_code == 201
    assert validation_plan.status_code == 200
    assert initiative.status_code == 201
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert resume.status_code == 409
    assert resume.json()["detail"] == "已取消立项不能恢复或继续推进"
    assert launch.status_code == 409
    assert launch.json()["detail"] == "已取消立项不能恢复或继续推进"


async def test_mcp_validation_gate_requires_latest_review_material_and_is_idempotent(
    tenant_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    stored_objects: dict[str, bytes] = {}

    class MemoryStorage:
        """提供`MemoryStorage`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
        async def put_object(self, key: str, content: bytes, content_type: str) -> str:
            """辅助构造`put object`测试数据或依赖，减少用例中的重复准备代码。"""
            del content_type
            stored_objects[key] = content
            return key

        async def delete_object(self, key: str) -> None:
            """辅助构造`delete object`测试数据或依赖，减少用例中的重复准备代码。"""
            stored_objects.pop(key, None)

    monkeypatch.setattr(
        projects_route_module,
        "get_object_storage_provider",
        lambda: MemoryStorage(),
    )
    run_response = await tenant_client.get(
        "/api/v1/planning-projects/project-a/runs/run-a",
        headers=authorization("tenant-a-planner"),
    )
    run_payload = run_response.json()
    validation_plan = run_payload["result_snapshot"]["outputs"]["concept"]["candidates"][0][
        "validation_plan"
    ]
    initial_review_token = validation_review_fingerprint(
        project_id="project-a",
        run_id="run-a",
        run_status=run_payload["status"],
        candidate_id="candidate-a",
        validation_plan=validation_plan,
    )
    base_headers = {
        **authorization("tenant-a-planner"),
        "X-MerchPilot-Client": "FastMCP",
    }
    blocked_payload = {
        "candidate_id": "candidate-a",
        "gates": [
            {
                "gate_id": "sample_test",
                "status": "blocked",
                "note": "样品跌落测试未通过。",
            }
        ],
        "confirmation": "MARK_VALIDATION_BLOCKED",
        "review_token": initial_review_token,
    }
    missing_request_id = await tenant_client.patch(
        "/api/v1/planning-projects/project-a/runs/run-a/validation-plan",
        headers=base_headers,
        json=blocked_payload,
    )
    viewer_update = await tenant_client.patch(
        "/api/v1/planning-projects/project-a/runs/run-a/validation-plan",
        headers={
            **authorization("tenant-a-viewer"),
            "X-MerchPilot-Client": "fastmcp",
            "Idempotency-Key": "mcp-validation-viewer-001",
        },
        json=blocked_payload,
    )
    wrong_confirmation = await tenant_client.patch(
        "/api/v1/planning-projects/project-a/runs/run-a/validation-plan",
        headers={**base_headers, "Idempotency-Key": "mcp-validation-confirmation-001"},
        json={**blocked_payload, "confirmation": "MARK_VALIDATION_READY"},
    )
    ready_without_material = await tenant_client.patch(
        "/api/v1/planning-projects/project-a/runs/run-a/validation-plan",
        headers={**base_headers, "Idempotency-Key": "mcp-validation-no-material-001"},
        json={
            **blocked_payload,
            "gates": [
                {
                    "gate_id": "sample_test",
                    "status": "ready",
                    "note": "样品测试通过。",
                }
            ],
            "confirmation": "MARK_VALIDATION_READY",
        },
    )
    blocked_headers = {**base_headers, "Idempotency-Key": "mcp-validation-blocked-001"}
    blocked = await tenant_client.patch(
        "/api/v1/planning-projects/project-a/runs/run-a/validation-plan",
        headers=blocked_headers,
        json=blocked_payload,
    )
    blocked_replay = await tenant_client.patch(
        "/api/v1/planning-projects/project-a/runs/run-a/validation-plan",
        headers=blocked_headers,
        json=blocked_payload,
    )
    blocked_conflict = await tenant_client.patch(
        "/api/v1/planning-projects/project-a/runs/run-a/validation-plan",
        headers=blocked_headers,
        json={
            **blocked_payload,
            "gates": [
                {
                    "gate_id": "sample_test",
                    "status": "blocked",
                    "note": "改用另一个阻塞结论。",
                }
            ],
        },
    )
    stale_pending = await tenant_client.patch(
        "/api/v1/planning-projects/project-a/runs/run-a/validation-plan",
        headers={**base_headers, "Idempotency-Key": "mcp-validation-stale-001"},
        json={
            "candidate_id": "candidate-a",
            "gates": [
                {
                    "gate_id": "sample_test",
                    "status": "pending",
                    "note": "等待复测。",
                }
            ],
            "confirmation": "RESET_VALIDATION_PENDING",
            "review_token": initial_review_token,
        },
    )
    blocked_run = await tenant_client.get(
        "/api/v1/planning-projects/project-a/runs/run-a",
        headers=authorization("tenant-a-planner"),
    )
    blocked_payload_value = blocked_run.json()
    blocked_plan = blocked_payload_value["result_snapshot"]["outputs"]["concept"][
        "candidates"
    ][0]["validation_plan"]
    blocked_review_token = validation_review_fingerprint(
        project_id="project-a",
        run_id="run-a",
        run_status=blocked_payload_value["status"],
        candidate_id="candidate-a",
        validation_plan=blocked_plan,
    )
    material = await tenant_client.post(
        "/api/v1/planning-projects/project-a/runs/run-a/validation-materials",
        headers=authorization("tenant-a-planner"),
        data={
            "candidate_id": "candidate-a",
            "gate_id": "sample_test",
            "note": "人工上传复测报告",
        },
        files={"file": ("sample-report.pdf", b"validated sample report", "application/pdf")},
    )
    stale_after_material = await tenant_client.patch(
        "/api/v1/planning-projects/project-a/runs/run-a/validation-plan",
        headers={**base_headers, "Idempotency-Key": "mcp-validation-material-stale-001"},
        json={
            "candidate_id": "candidate-a",
            "gates": [
                {
                    "gate_id": "sample_test",
                    "status": "ready",
                    "note": "人工复测材料已确认。",
                }
            ],
            "confirmation": "MARK_VALIDATION_READY",
            "review_token": blocked_review_token,
        },
    )
    material_payload = material.json()
    material_plan = material_payload["result_snapshot"]["outputs"]["concept"]["candidates"][
        0
    ]["validation_plan"]
    material_review_token = validation_review_fingerprint(
        project_id="project-a",
        run_id="run-a",
        run_status=material_payload["status"],
        candidate_id="candidate-a",
        validation_plan=material_plan,
    )
    ready_payload = {
        "candidate_id": "candidate-a",
        "gates": [
            {
                "gate_id": "sample_test",
                "status": "ready",
                "note": "人工复测材料已确认。",
            }
        ],
        "confirmation": "MARK_VALIDATION_READY",
        "review_token": material_review_token,
    }
    ready_headers = {**base_headers, "Idempotency-Key": "mcp-validation-ready-001"}
    ready = await tenant_client.patch(
        "/api/v1/planning-projects/project-a/runs/run-a/validation-plan",
        headers=ready_headers,
        json=ready_payload,
    )
    ready_replay = await tenant_client.patch(
        "/api/v1/planning-projects/project-a/runs/run-a/validation-plan",
        headers=ready_headers,
        json=ready_payload,
    )
    selected_product = await tenant_client.get(
        "/api/v1/selected-products/selection-a",
        headers=authorization("tenant-a-viewer"),
    )
    audits = await tenant_client.get(
        "/api/v1/audit-events",
        params={"project_id": "project-a", "action": "planning_validation.updated"},
        headers=authorization("tenant-a-admin"),
    )
    activities = await tenant_client.get(
        "/api/v1/integrations/mcp/activities",
        headers=authorization("tenant-a-planner"),
    )

    assert run_response.status_code == 200
    assert missing_request_id.status_code == 422
    assert viewer_update.status_code == 403
    assert wrong_confirmation.status_code == 422
    assert ready_without_material.status_code == 409
    assert blocked.status_code == 200
    assert blocked.headers["Idempotency-Replayed"] == "false"
    assert blocked_replay.status_code == 200
    assert blocked_replay.headers["Idempotency-Replayed"] == "true"
    assert blocked_conflict.status_code == 409
    assert stale_pending.status_code == 409
    assert material.status_code == 201
    assert stored_objects
    assert stale_after_material.status_code == 409
    assert ready.status_code == 200
    assert ready.headers["Idempotency-Replayed"] == "false"
    assert ready_replay.status_code == 200
    assert ready_replay.headers["Idempotency-Replayed"] == "true"
    ready_gate = ready.json()["result_snapshot"]["outputs"]["concept"]["candidates"][0][
        "validation_plan"
    ]["gates"][0]
    assert ready_gate["status"] == "ready"
    assert ready_gate["note"] == "人工复测材料已确认。"
    assert len(ready_gate["materials"]) == 1
    assert selected_product.json()["status"] == "ready"
    assert selected_product.json()["validation_status"] == "ready"
    mcp_updates = [item for item in audits.json() if item["detail"]["client"] == "fastmcp"]
    assert [item["detail"]["idempotency_key"] for item in mcp_updates] == [
        "mcp-validation-ready-001",
        "mcp-validation-blocked-001",
    ]
    assert mcp_updates[0]["detail"]["review_token"] == material_review_token
    assert activities.status_code == 200
    project_activity = next(
        item for item in activities.json()["items"] if item["project_id"] == "project-a"
    )
    assert project_activity["activity_type"] == "mcp_validation_updated"
    assert project_activity["request_id"] == "mcp-validation-ready-001"
    assert project_activity["latest_validation_request_id"] == "mcp-validation-ready-001"
    assert project_activity["latest_validation_actor_id"] == "planner-a"
    assert project_activity["latest_validation_run_id"] == "run-a"
    assert project_activity["latest_validation_candidate_id"] == "candidate-a"
    assert project_activity["latest_validation_gate_ids"] == ["sample_test"]
    assert project_activity["latest_validation_status"] == "ready"
    assert project_activity["latest_validation_completion_rate"] == 100


async def test_validation_plan_updates_selected_product_and_timeline(
    tenant_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    material = await upload_test_validation_material(
        tenant_client,
        monkeypatch,
        note="样品测试通过材料",
    )
    updated_run = await tenant_client.patch(
        "/api/v1/planning-projects/project-a/runs/run-a/validation-plan",
        headers=authorization("tenant-a-planner"),
        json={
            "candidate_id": "candidate-a",
            "gates": [
                {
                    "gate_id": "sample_test",
                    "status": "ready",
                    "note": "样品测试通过",
                }
            ],
        },
    )
    selected_product = await tenant_client.get(
        "/api/v1/selected-products/selection-a",
        headers=authorization("tenant-a-viewer"),
    )
    timeline = await tenant_client.get(
        "/api/v1/selected-products/selection-a/timeline",
        headers=authorization("tenant-a-viewer"),
    )
    timeline_page = await tenant_client.get(
        "/api/v1/selected-products/selection-a/timeline/page",
        params={"page": 1, "page_size": 1},
        headers=authorization("tenant-a-viewer"),
    )
    isolated_timeline = await tenant_client.get(
        "/api/v1/selected-products/selection-b/timeline",
        headers=authorization("tenant-a-viewer"),
    )
    isolated_timeline_page = await tenant_client.get(
        "/api/v1/selected-products/selection-b/timeline/page",
        params={"page": 1, "page_size": 1},
        headers=authorization("tenant-a-viewer"),
    )
    invalid_regression = await tenant_client.patch(
        "/api/v1/selected-products/selection-a",
        headers=authorization("tenant-a-planner"),
        json={"status": "validating"},
    )
    initiative = await tenant_client.post(
        "/api/v1/product-initiatives",
        headers=authorization("tenant-a-planner"),
        json={
            "selected_product_id": "selection-a",
            "owner_id": "launch-owner-a",
            "target_launch_date": "2026-12-01",
            "budget": 120000,
            "notes": "进入商品开发与试销阶段",
        },
    )
    initiative_id = initiative.json()["id"]
    initiative_update = await tenant_client.patch(
        f"/api/v1/product-initiatives/{initiative_id}",
        headers=authorization("tenant-a-planner"),
        json={
            "owner_id": "launch-owner-a-updated",
            "target_launch_date": "2026-12-15",
            "budget": 135000,
            "notes": "已补充样品、成本和试销推进计划",
        },
    )
    duplicate_initiative = await tenant_client.post(
        "/api/v1/product-initiatives",
        headers=authorization("tenant-a-planner"),
        json={"selected_product_id": "selection-a"},
    )
    invalid_selection_override = await tenant_client.patch(
        "/api/v1/selected-products/selection-a",
        headers=authorization("tenant-a-planner"),
        json={"status": "paused"},
    )
    tenant_initiatives = await tenant_client.get(
        "/api/v1/product-initiatives",
        headers=authorization("tenant-a-viewer"),
    )
    tenant_initiatives_page = await tenant_client.get(
        "/api/v1/product-initiatives/page",
        params={
            "keyword": "正式选品",
            "project_id": "project-a",
            "page": 1,
            "page_size": 1,
        },
        headers=authorization("tenant-a-viewer"),
    )
    unrelated_project_initiatives_page = await tenant_client.get(
        "/api/v1/product-initiatives/page",
        params={"project_id": "project-b", "page": 1, "page_size": 1},
        headers=authorization("tenant-a-viewer"),
    )
    isolated_initiative = await tenant_client.get(
        f"/api/v1/product-initiatives/{initiative_id}",
        headers=authorization("tenant-b-viewer"),
    )
    readiness_initial = await tenant_client.get(
        f"/api/v1/product-initiatives/{initiative_id}/launch-readiness",
        headers=authorization("tenant-a-viewer"),
    )
    isolated_readiness = await tenant_client.get(
        f"/api/v1/product-initiatives/{initiative_id}/launch-readiness",
        headers=authorization("tenant-b-viewer"),
    )
    early_launch = await tenant_client.patch(
        f"/api/v1/product-initiatives/{initiative_id}",
        headers=authorization("tenant-a-planner"),
        json={"status": "launched"},
    )
    out_of_order_milestone = await tenant_client.patch(
        f"/api/v1/product-initiatives/{initiative_id}/milestones/cost_finalize",
        headers=authorization("tenant-a-planner"),
        json={"status": "completed"},
    )
    for milestone_id in ["sample_finalize", "cost_finalize"]:
        milestone_update = await tenant_client.patch(
            f"/api/v1/product-initiatives/{initiative_id}/milestones/{milestone_id}",
            headers=authorization("tenant-a-planner"),
            json={"status": "completed", "note": f"{milestone_id} 本地验收完成"},
        )
        assert milestone_update.status_code == 200
    milestone_regression = await tenant_client.patch(
        f"/api/v1/product-initiatives/{initiative_id}/milestones/sample_finalize",
        headers=authorization("tenant-a-planner"),
        json={"status": "pending"},
    )
    pilot_without_data = await tenant_client.patch(
        f"/api/v1/product-initiatives/{initiative_id}/milestones/pilot_sale",
        headers=authorization("tenant-a-planner"),
        json={"status": "completed"},
    )
    pilot_sale = await tenant_client.post(
        f"/api/v1/product-initiatives/{initiative_id}/pilot-sales",
        headers=authorization("tenant-a-planner"),
        json={
            "period_start": "2026-08-01",
            "period_end": "2026-08-07",
            "channel": "租户 A 试销店",
            "visitors": 1000,
            "orders": 50,
            "units_sold": 60,
            "revenue": 12000,
            "product_cost": 6000,
            "marketing_spend": 2000,
            "refunds_amount": 500,
            "return_count": 3,
            "rating": 4.6,
        },
    )
    duplicate_pilot_sale = await tenant_client.post(
        f"/api/v1/product-initiatives/{initiative_id}/pilot-sales",
        headers=authorization("tenant-a-planner"),
        json={
            "period_start": "2026-08-01",
            "period_end": "2026-08-07",
            "channel": "租户 A 试销店",
            "visitors": 1200,
            "orders": 60,
            "units_sold": 70,
            "revenue": 13000,
            "product_cost": 6500,
            "marketing_spend": 2000,
            "refunds_amount": 400,
            "return_count": 2,
            "rating": 4.7,
        },
    )
    pilot_sale_update = await tenant_client.patch(
        f"/api/v1/product-initiatives/{initiative_id}/pilot-sales/{pilot_sale.json()['id']}",
        headers=authorization("tenant-a-planner"),
        json={"notes": "已完成首轮渠道复盘"},
    )
    isolated_pilot_sale_update = await tenant_client.patch(
        f"/api/v1/product-initiatives/{initiative_id}/pilot-sales/{pilot_sale.json()['id']}",
        headers=authorization("tenant-b-admin"),
        json={"notes": "不应越租户修改"},
    )
    pilot_sales_page = await tenant_client.get(
        f"/api/v1/product-initiatives/{initiative_id}/pilot-sales/page",
        params={"page": 1, "page_size": 1},
        headers=authorization("tenant-a-viewer"),
    )
    isolated_pilot_sales_page = await tenant_client.get(
        f"/api/v1/product-initiatives/{initiative_id}/pilot-sales/page",
        params={"page": 1, "page_size": 1},
        headers=authorization("tenant-b-viewer"),
    )
    pilot_trend = await tenant_client.get(
        f"/api/v1/product-initiatives/{initiative_id}/pilot-sales-trend",
        headers=authorization("tenant-a-viewer"),
    )
    pilot_summary = await tenant_client.get(
        f"/api/v1/product-initiatives/{initiative_id}/pilot-sales-summary",
        headers=authorization("tenant-a-viewer"),
    )
    isolated_pilot_summary = await tenant_client.get(
        f"/api/v1/product-initiatives/{initiative_id}/pilot-sales-summary",
        headers=authorization("tenant-b-viewer"),
    )
    isolated_pilot_trend = await tenant_client.get(
        f"/api/v1/product-initiatives/{initiative_id}/pilot-sales-trend",
        headers=authorization("tenant-b-viewer"),
    )
    launch_review_context_before = await tenant_client.get(
        f"/api/v1/product-initiatives/{initiative_id}/launch-review-context",
        headers=authorization("tenant-a-viewer"),
    )
    pilot_milestone_update = await tenant_client.patch(
        f"/api/v1/product-initiatives/{initiative_id}/milestones/pilot_sale",
        headers=authorization("tenant-a-planner"),
        json={
            "status": "completed",
            "owner_id": "launch-owner-a",
            "note": "pilot_sale 本地验收完成",
        },
    )
    stale_launch_review_submit = await tenant_client.post(
        f"/api/v1/product-initiatives/{initiative_id}/launch-reviews",
        headers={
            **authorization("tenant-a-planner"),
            "X-MerchPilot-Client": "fastmcp",
            "Idempotency-Key": "launch-review-stale-001",
        },
        json={
            "submission_note": "使用过期状态申请上市评审",
            "confirmation": "SUBMIT_LAUNCH_REVIEW",
            "review_token": launch_review_context_before.json()["review_token"],
        },
    )
    launch_review_context = await tenant_client.get(
        f"/api/v1/product-initiatives/{initiative_id}/launch-review-context",
        headers=authorization("tenant-a-viewer"),
    )
    isolated_launch_review_context = await tenant_client.get(
        f"/api/v1/product-initiatives/{initiative_id}/launch-review-context",
        headers=authorization("tenant-b-viewer"),
    )
    launch_review_request_headers = {
        **authorization("tenant-a-planner"),
        "X-MerchPilot-Client": "fastmcp",
        "Idempotency-Key": "launch-review-submit-001",
    }
    launch_review_payload = {
        "submission_note": "样品、成本和试销数据已完成，请审批上市准备",
        "confirmation": "SUBMIT_LAUNCH_REVIEW",
        "review_token": launch_review_context.json()["review_token"],
    }
    launch_review_submit = await tenant_client.post(
        f"/api/v1/product-initiatives/{initiative_id}/launch-reviews",
        headers=launch_review_request_headers,
        json=launch_review_payload,
    )
    launch_review_id = launch_review_submit.json()["id"]
    launch_review_replay = await tenant_client.post(
        f"/api/v1/product-initiatives/{initiative_id}/launch-reviews",
        headers=launch_review_request_headers,
        json=launch_review_payload,
    )
    launch_review_request_conflict = await tenant_client.post(
        f"/api/v1/product-initiatives/{initiative_id}/launch-reviews",
        headers=launch_review_request_headers,
        json={**launch_review_payload, "submission_note": "同一请求标识不可修改内容"},
    )
    launch_review_context_after = await tenant_client.get(
        f"/api/v1/product-initiatives/{initiative_id}/launch-review-context",
        headers=authorization("tenant-a-viewer"),
    )
    launch_review_activities = await tenant_client.get(
        "/api/v1/integrations/mcp/activities?page=1&page_size=5",
        headers=authorization("tenant-a-planner"),
    )
    tenant_launch_reviews = await tenant_client.get(
        "/api/v1/product-initiatives/launch-reviews",
        headers=authorization("tenant-a-viewer"),
    )
    tenant_launch_reviews_page = await tenant_client.get(
        "/api/v1/product-initiatives/launch-reviews/page",
        params={
            "status": "pending",
            "initiative_id": initiative_id,
            "page": 1,
            "page_size": 1,
        },
        headers=authorization("tenant-a-viewer"),
    )
    isolated_tenant_launch_reviews = await tenant_client.get(
        "/api/v1/product-initiatives/launch-reviews",
        headers=authorization("tenant-b-viewer"),
    )
    isolated_tenant_launch_reviews_page = await tenant_client.get(
        "/api/v1/product-initiatives/launch-reviews/page",
        params={
            "status": "all",
            "initiative_id": initiative_id,
            "page": 1,
            "page_size": 1,
        },
        headers=authorization("tenant-b-viewer"),
    )
    duplicate_launch_review_submit = await tenant_client.post(
        f"/api/v1/product-initiatives/{initiative_id}/launch-reviews",
        headers=authorization("tenant-a-planner"),
        json={"submission_note": "不应重复创建待审批评审"},
    )
    planner_launch_review_decision = await tenant_client.post(
        f"/api/v1/product-initiatives/{initiative_id}/launch-reviews/{launch_review_id}/decision",
        headers=authorization("tenant-a-planner"),
        json={"action": "approved", "decision_note": "规划人员不应代审批"},
    )
    isolated_launch_reviews = await tenant_client.get(
        f"/api/v1/product-initiatives/{initiative_id}/launch-reviews",
        headers=authorization("tenant-b-viewer"),
    )
    isolated_launch_review_decision = await tenant_client.post(
        f"/api/v1/product-initiatives/{initiative_id}/launch-reviews/{launch_review_id}/decision",
        headers=authorization("tenant-b-admin"),
        json={"action": "approved", "decision_note": "不应跨租户审批"},
    )
    manual_launch_review_complete = await tenant_client.patch(
        f"/api/v1/product-initiatives/{initiative_id}/milestones/launch_review",
        headers=authorization("tenant-a-planner"),
        json={"status": "completed"},
    )
    launch_reviews = await tenant_client.get(
        f"/api/v1/product-initiatives/{initiative_id}/launch-reviews",
        headers=authorization("tenant-a-viewer"),
    )
    launch_review_decision = await tenant_client.post(
        f"/api/v1/product-initiatives/{initiative_id}/launch-reviews/{launch_review_id}/decision",
        headers=authorization("tenant-a-admin"),
        json={"action": "approved", "decision_note": "上市准备条件已复核通过"},
    )
    tenant_all_launch_reviews_after_decision = await tenant_client.get(
        "/api/v1/product-initiatives/launch-reviews",
        headers=authorization("tenant-a-viewer"),
    )
    tenant_pending_launch_reviews_after_decision = await tenant_client.get(
        "/api/v1/product-initiatives/launch-reviews",
        params={"status": "pending"},
        headers=authorization("tenant-a-viewer"),
    )
    tenant_approved_launch_reviews_after_decision = await tenant_client.get(
        "/api/v1/product-initiatives/launch-reviews",
        params={"status": "approved"},
        headers=authorization("tenant-a-viewer"),
    )
    readiness_final = await tenant_client.get(
        f"/api/v1/product-initiatives/{initiative_id}/launch-readiness",
        headers=authorization("tenant-a-viewer"),
    )
    expired_launch_date = await tenant_client.patch(
        f"/api/v1/product-initiatives/{initiative_id}",
        headers=authorization("tenant-a-planner"),
        json={"target_launch_date": "2026-01-01"},
    )
    expired_launch = await tenant_client.patch(
        f"/api/v1/product-initiatives/{initiative_id}",
        headers=authorization("tenant-a-planner"),
        json={"status": "launched"},
    )
    restored_launch_date = await tenant_client.patch(
        f"/api/v1/product-initiatives/{initiative_id}",
        headers=authorization("tenant-a-planner"),
        json={"target_launch_date": "2026-12-01"},
    )
    launched = await tenant_client.patch(
        f"/api/v1/product-initiatives/{initiative_id}",
        headers=authorization("tenant-a-planner"),
        json={"status": "launched"},
    )
    launched_product = await tenant_client.get(
        "/api/v1/selected-products/selection-a",
        headers=authorization("tenant-a-viewer"),
    )
    initiative_timeline = await tenant_client.get(
        f"/api/v1/product-initiatives/{initiative_id}/timeline",
        headers=authorization("tenant-a-viewer"),
    )
    initiative_timeline_page = await tenant_client.get(
        f"/api/v1/product-initiatives/{initiative_id}/timeline/page",
        params={"page": 1, "page_size": 2},
        headers=authorization("tenant-a-viewer"),
    )
    isolated_initiative_timeline_page = await tenant_client.get(
        f"/api/v1/product-initiatives/{initiative_id}/timeline/page",
        params={"page": 1, "page_size": 2},
        headers=authorization("tenant-b-viewer"),
    )

    assert material.status_code == 201
    assert updated_run.status_code == 200
    updated_candidate = updated_run.json()["result_snapshot"]["outputs"]["concept"][
        "selected_candidate"
    ]
    assert updated_candidate["validation_plan"]["status"] == "ready"
    assert selected_product.status_code == 200
    assert selected_product.json()["validation_status"] == "ready"
    assert selected_product.json()["status"] == "ready"
    assert timeline.status_code == 200
    assert timeline.json()[0]["action"] == "selected_product.validation_synced"
    assert timeline.json()[0]["detail"]["completion_rate"] == 100
    assert timeline_page.status_code == 200
    assert timeline_page.headers["X-Total-Count"] == str(len(timeline.json()))
    assert timeline_page.json()["total"] == len(timeline.json())
    assert timeline_page.json()["page"] == 1
    assert timeline_page.json()["page_size"] == 1
    assert timeline_page.json()["items"][0]["action"] == "selected_product.validation_synced"
    assert isolated_timeline.status_code == 404
    assert isolated_timeline_page.status_code == 404
    assert invalid_regression.status_code == 409
    assert initiative.status_code == 201
    assert initiative.json()["status"] == "in_progress"
    assert initiative.json()["milestones"][0]["status"] == "completed"
    assert initiative_update.status_code == 200
    assert initiative_update.json()["owner_id"] == "launch-owner-a-updated"
    assert initiative_update.json()["target_launch_date"] == "2026-12-15"
    assert initiative_update.json()["budget"] == 135000
    assert initiative_update.json()["notes"] == "已补充样品、成本和试销推进计划"
    assert duplicate_initiative.status_code == 409
    assert invalid_selection_override.status_code == 409
    assert {item["id"] for item in tenant_initiatives.json()} == {initiative_id}
    assert tenant_initiatives_page.status_code == 200
    assert tenant_initiatives_page.headers["X-Total-Count"] == "1"
    assert tenant_initiatives_page.json()["total"] == 1
    assert tenant_initiatives_page.json()["page"] == 1
    assert tenant_initiatives_page.json()["page_size"] == 1
    assert {item["id"] for item in tenant_initiatives_page.json()["items"]} == {initiative_id}
    assert tenant_initiatives_page.json()["summary"]["total"] == 1
    assert unrelated_project_initiatives_page.status_code == 200
    assert unrelated_project_initiatives_page.headers["X-Total-Count"] == "0"
    assert unrelated_project_initiatives_page.json()["items"] == []
    assert isolated_initiative.status_code == 404
    assert readiness_initial.status_code == 200
    assert readiness_initial.json()["readiness_status"] == "blocked"
    assert "尚未完成里程碑：样品定版, 成本定版, 小批量试销, 上市准备评审" in (
        readiness_initial.json()["blockers"]
    )
    assert isolated_readiness.status_code == 404
    assert early_launch.status_code == 409
    assert out_of_order_milestone.status_code == 409
    assert milestone_regression.status_code == 409
    assert pilot_without_data.status_code == 409
    assert pilot_sale.status_code == 201
    assert pilot_sale.json()["conversion_rate"] == 0.05
    assert pilot_sale.json()["gross_profit"] == 3500
    assert duplicate_pilot_sale.status_code == 409
    assert duplicate_pilot_sale.json()["detail"] == "同一试销周期和渠道已有数据，请使用修订功能"
    assert pilot_sale_update.status_code == 200
    assert pilot_sale_update.json()["notes"] == "已完成首轮渠道复盘"
    assert pilot_sale_update.json()["updated_at"] >= pilot_sale.json()["updated_at"]
    assert isolated_pilot_sale_update.status_code == 404
    assert pilot_sales_page.status_code == 200
    assert pilot_sales_page.headers["X-Total-Count"] == "1"
    assert pilot_sales_page.json()["total"] == 1
    assert pilot_sales_page.json()["page"] == 1
    assert pilot_sales_page.json()["page_size"] == 1
    assert [item["id"] for item in pilot_sales_page.json()["items"]] == [
        pilot_sale.json()["id"]
    ]
    assert isolated_pilot_sales_page.status_code == 404
    assert pilot_trend.status_code == 200
    assert len(pilot_trend.json()["periods"]) == 1
    assert len(pilot_trend.json()["channels"]) == 1
    assert pilot_trend.json()["period_total"] == 1
    assert pilot_trend.json()["channel_total"] == 1
    assert pilot_trend.json()["periods"][0]["revenue"] == 12000
    assert isolated_pilot_trend.status_code == 404
    assert pilot_summary.status_code == 200
    assert pilot_summary.json()["actual_margin_rate"] == 0.291667
    assert pilot_summary.json()["return_rate"] == 0.05
    assert pilot_summary.json()["marketing_roi"] == 1.75
    assert pilot_summary.json()["assessment_status"] == "review"
    assert "实际毛利率低于规划毛利率" in pilot_summary.json()["risks"]
    assert isolated_pilot_summary.status_code == 404
    assert launch_review_context_before.status_code == 200
    assert launch_review_context_before.json()["can_submit"] is False
    assert "尚未完成里程碑：小批量试销" in launch_review_context_before.json()[
        "submission_blockers"
    ]
    assert readiness_final.status_code == 200
    assert readiness_final.json()["readiness_status"] == "review"
    assert readiness_final.json()["blockers"] == []
    assert "实际毛利率低于规划毛利率" in readiness_final.json()["warnings"]
    assert expired_launch_date.status_code == 200
    assert expired_launch.status_code == 409
    assert "目标上市日期已过期" in expired_launch.json()["detail"]
    assert restored_launch_date.status_code == 200
    assert pilot_milestone_update.status_code == 200
    assert stale_launch_review_submit.status_code == 409
    assert "重新读取并复核最新状态" in stale_launch_review_submit.json()["detail"]
    assert launch_review_context.status_code == 200
    assert launch_review_context.json()["can_submit"] is True
    assert launch_review_context.json()["readiness"]["readiness_status"] == "review"
    assert launch_review_context.json()["pilot_summary"]["assessment_status"] == "review"
    assert isolated_launch_review_context.status_code == 404
    assert launch_review_submit.status_code == 201
    assert launch_review_submit.headers["Idempotency-Replayed"] == "false"
    assert launch_review_submit.json()["status"] == "pending"
    assert launch_review_submit.json()["readiness_snapshot"]["readiness_status"] == "review"
    assert launch_review_replay.status_code == 200
    assert launch_review_replay.headers["Idempotency-Replayed"] == "true"
    assert launch_review_replay.json()["id"] == launch_review_id
    assert launch_review_request_conflict.status_code == 409
    assert launch_review_context_after.status_code == 200
    assert launch_review_context_after.json()["can_submit"] is False
    assert launch_review_context_after.json()["pending_review"]["id"] == launch_review_id
    assert "已有待处理的上市准备评审" in launch_review_context_after.json()[
        "submission_blockers"
    ]
    assert launch_review_activities.status_code == 200
    launch_review_activity = next(
        item
        for item in launch_review_activities.json()["items"]
        if item["project_id"] == "project-a"
    )
    assert launch_review_activity["activity_type"] == "mcp_launch_review_submitted"
    assert launch_review_activity["request_id"] == "launch-review-submit-001"
    assert launch_review_activity["latest_launch_review_request_id"] == (
        "launch-review-submit-001"
    )
    assert launch_review_activity["latest_launch_review_initiative_id"] == initiative_id
    assert launch_review_activity["latest_launch_review_id"] == launch_review_id
    assert launch_review_activity["latest_launch_review_status"] == "pending"
    assert launch_review_activity["latest_launch_review_readiness_status"] == "review"
    assert tenant_launch_reviews.status_code == 200
    assert len(tenant_launch_reviews.json()) == 1
    assert tenant_launch_reviews.json()[0]["initiative_name"] == "租户 A 正式选品"
    assert tenant_launch_reviews_page.status_code == 200
    assert tenant_launch_reviews_page.headers["X-Total-Count"] == "1"
    assert tenant_launch_reviews_page.json()["total"] == 1
    assert tenant_launch_reviews_page.json()["page"] == 1
    assert tenant_launch_reviews_page.json()["page_size"] == 1
    assert [item["id"] for item in tenant_launch_reviews_page.json()["items"]] == [launch_review_id]
    assert tenant_launch_reviews_page.json()["summary"] == {
        "total": 1,
        "pending": 1,
        "approved": 0,
        "rejected": 0,
        "revision_required": 0,
        "processed": 0,
    }
    assert isolated_tenant_launch_reviews.status_code == 200
    assert isolated_tenant_launch_reviews.json() == []
    assert isolated_tenant_launch_reviews_page.status_code == 404
    assert duplicate_launch_review_submit.status_code == 409
    assert planner_launch_review_decision.status_code == 403
    assert isolated_launch_reviews.status_code == 404
    assert isolated_launch_review_decision.status_code == 404
    assert manual_launch_review_complete.status_code == 409
    assert launch_reviews.status_code == 200
    assert len(launch_reviews.json()) == 1
    assert launch_review_decision.status_code == 200
    assert launch_review_decision.json()["status"] == "approved"
    assert launch_review_decision.json()["decided_by"] == "admin-a"
    assert tenant_all_launch_reviews_after_decision.status_code == 200
    assert tenant_all_launch_reviews_after_decision.json()[0]["status"] == "approved"
    assert tenant_pending_launch_reviews_after_decision.status_code == 200
    assert tenant_pending_launch_reviews_after_decision.json() == []
    assert tenant_approved_launch_reviews_after_decision.status_code == 200
    assert len(tenant_approved_launch_reviews_after_decision.json()) == 1
    approved_launch_reviews_page = await tenant_client.get(
        "/api/v1/product-initiatives/launch-reviews/page",
        params={"status": "processed", "page": 1, "page_size": 1},
        headers=authorization("tenant-a-viewer"),
    )
    assert approved_launch_reviews_page.status_code == 200
    assert approved_launch_reviews_page.headers["X-Total-Count"] == "1"
    assert [item["id"] for item in approved_launch_reviews_page.json()["items"]] == [launch_review_id]
    assert launched.status_code == 200
    assert launched.json()["status"] == "launched"
    assert launched.json()["launched_at"] is not None
    assert launched_product.json()["status"] == "launched"
    assert initiative_timeline.status_code == 200
    assert initiative_timeline.json()[0]["action"] == "product_initiative.updated"
    assert initiative_timeline_page.status_code == 200
    assert initiative_timeline_page.headers["X-Total-Count"] == str(
        len(initiative_timeline.json())
    )
    assert initiative_timeline_page.json()["total"] == len(initiative_timeline.json())
    assert initiative_timeline_page.json()["page"] == 1
    assert initiative_timeline_page.json()["page_size"] == 2
    assert len(initiative_timeline_page.json()["items"]) == 2
    assert isolated_initiative_timeline_page.status_code == 404


async def test_import_quality_summary_and_report_are_tenant_scoped(
    tenant_client: AsyncClient,
) -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    headers = authorization("tenant-a-viewer")

    summary = await tenant_client.get("/api/v1/data-imports/quality-summary", headers=headers)
    report = await tenant_client.get(
        "/api/v1/data-imports/import-a/quality-report",
        headers=headers,
    )

    assert summary.status_code == 200
    summary_payload = summary.json()
    assert {
        key: value for key, value in summary_payload.items() if key != "problem_imports"
    } == {
        "total_imports": 3,
        "completed_imports": 2,
        "failed_imports": 1,
        "total_records": 5,
        "verified_records": 4,
        "warning_records": 1,
        "blocked_records": 0,
        "indexed_records": 4,
        "pending_index_records": 0,
        "failed_index_records": 1,
        "problem_import_total": 1,
    }
    assert summary_payload["problem_imports"] == [
        {
            "import_id": "import-a",
            "filename": "tenant-a.xlsx",
            "created_at": summary_payload["problem_imports"][0]["created_at"],
            "warning_records": 1,
            "blocked_records": 0,
            "failed_index_records": 1,
        }
    ]
    assert report.status_code == 200
    assert report.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


async def test_run_evidence_combines_snapshot_topics_and_current_lineage(
    tenant_client: AsyncClient,
) -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    evidence = await tenant_client.get(
        "/api/v1/planning-projects/project-a/runs/run-a/evidence",
        headers=authorization("tenant-a-viewer"),
    )
    evidence_page = await tenant_client.get(
        "/api/v1/planning-projects/project-a/runs/run-a/evidence/page",
        params={"page": 1, "page_size": 1},
        headers=authorization("tenant-a-viewer"),
    )

    assert evidence.status_code == 200
    assert len(evidence.json()) == 1
    assert evidence.json()[0]["evidence_id"] == "evidence-a"
    assert evidence.json()[0]["topics"] == ["市场", "竞品"]
    assert evidence.json()[0]["source_name"] == "tenant-a.xlsx"
    assert evidence.json()[0]["source_row"] == 2
    assert evidence.json()[0]["source_id"] == "source-a"
    assert evidence.json()[0]["retrieval_score"] == 0.93
    assert evidence.json()[0]["vector_score"] == 0.81
    assert evidence.json()[0]["available"] is True
    assert evidence_page.status_code == 200
    assert evidence_page.headers["X-Total-Count"] == "1"
    assert evidence_page.json()["total"] == 1
    assert evidence_page.json()["page"] == 1
    assert evidence_page.json()["page_size"] == 1
    assert evidence_page.json()["unavailable_total"] == 0
    assert evidence_page.json()["items"] == evidence.json()


async def test_import_analysis_is_tenant_scoped(tenant_client: AsyncClient) -> None:
    """验证“import analysis is tenant scoped”场景，确保业务规则、权限和异常边界保持稳定。"""
    headers = authorization("tenant-a-viewer")

    coverage = await tenant_client.get("/api/v1/data-imports/coverage", headers=headers)
    duplicates = await tenant_client.get("/api/v1/data-imports/duplicates", headers=headers)
    duplicate_page = await tenant_client.get(
        "/api/v1/data-imports/duplicates/page",
        params={"status": "pending", "page": 1, "page_size": 1},
        headers=headers,
    )
    source_group_page = await tenant_client.get(
        "/api/v1/data-imports/duplicates/group",
        params={
            "match_type": "source_id",
            "match_value": "source-a",
            "page": 1,
            "page_size": 1,
        },
        headers=headers,
    )
    isolated_source_group = await tenant_client.get(
        "/api/v1/data-imports/duplicates/group",
        params={"match_type": "source_id", "match_value": "source-a"},
        headers=authorization("tenant-b-viewer"),
    )
    comparison = await tenant_client.get(
        "/api/v1/data-imports/import-a/compare/import-a-v2",
        headers=headers,
    )
    failed_comparison = await tenant_client.get(
        "/api/v1/data-imports/import-a/compare/import-a-failed",
        headers=headers,
    )

    assert coverage.status_code == 200
    assert coverage.json()["total_records"] == 5
    assert coverage.json()["source_id_coverage_rate"] == 1.0
    assert coverage.json()["date_coverage_rate"] == 1.0
    assert duplicates.status_code == 200
    assert {item["match_type"] for item in duplicates.json()} == {
        "source_id",
        "content_hash",
    }
    assert duplicate_page.status_code == 200
    assert duplicate_page.json()["summary"]["total"] == len(duplicates.json())
    assert duplicate_page.json()["summary"]["pending"] == len(duplicates.json())
    assert duplicate_page.json()["summary"]["reviewed"] == 0
    assert duplicate_page.json()["total"] == len(duplicates.json())
    assert len(duplicate_page.json()["items"]) == 1
    assert len(duplicate_page.json()["items"][0]["records"]) <= 2
    assert source_group_page.status_code == 200
    assert source_group_page.json()["record_count"] == 2
    assert source_group_page.json()["import_count"] == 2
    assert len(source_group_page.json()["items"]) == 1
    assert source_group_page.json()["review"] is None
    assert source_group_page.json()["canonical_record"] is None
    assert isolated_source_group.status_code == 404
    assert comparison.status_code == 200
    assert comparison.json()["added_source_ids"] == ["source-a-new"]
    assert comparison.json()["changed_source_ids"] == ["source-a-reindex"]
    assert comparison.json()["unchanged_source_ids"] == ["source-a"]
    assert failed_comparison.status_code == 409


async def test_duplicate_review_is_authorized_tenant_scoped_and_audited(
    tenant_client: AsyncClient,
) -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    payload = {
        "match_type": "source_id",
        "match_value": "source-a",
        "decision": "select_canonical",
        "canonical_evidence_id": "evidence-a-v2-unchanged",
        "notes": "优先使用最新批次记录",
    }

    viewer_review = await tenant_client.put(
        "/api/v1/data-imports/duplicates/review",
        headers=authorization("tenant-a-viewer"),
        json=payload,
    )
    cross_tenant_review = await tenant_client.put(
        "/api/v1/data-imports/duplicates/review",
        headers=authorization("tenant-b-admin"),
        json=payload,
    )
    missing_canonical = await tenant_client.put(
        "/api/v1/data-imports/duplicates/review",
        headers=authorization("tenant-a-planner"),
        json={**payload, "canonical_evidence_id": None},
    )
    foreign_canonical = await tenant_client.put(
        "/api/v1/data-imports/duplicates/review",
        headers=authorization("tenant-a-planner"),
        json={**payload, "canonical_evidence_id": "evidence-b"},
    )
    reviewed = await tenant_client.put(
        "/api/v1/data-imports/duplicates/review",
        headers=authorization("tenant-a-planner"),
        json=payload,
    )
    duplicate_groups = await tenant_client.get(
        "/api/v1/data-imports/duplicates",
        headers=authorization("tenant-a-viewer"),
    )
    reviewed_page = await tenant_client.get(
        "/api/v1/data-imports/duplicates/page",
        params={"status": "reviewed", "page": 1, "page_size": 6},
        headers=authorization("tenant-a-viewer"),
    )
    reviewed_group_page = await tenant_client.get(
        "/api/v1/data-imports/duplicates/group",
        params={
            "match_type": "source_id",
            "match_value": "source-a",
            "page": 1,
            "page_size": 1,
        },
        headers=authorization("tenant-a-viewer"),
    )
    audit_events = await tenant_client.get(
        "/api/v1/audit-events",
        params={"action": "duplicate.reviewed"},
        headers=authorization("tenant-a-admin"),
    )

    assert viewer_review.status_code == 403
    assert cross_tenant_review.status_code == 404
    assert missing_canonical.status_code == 422
    assert foreign_canonical.status_code == 400
    assert reviewed.status_code == 200
    assert reviewed.json()["decision"] == "select_canonical"
    assert reviewed.json()["canonical_evidence_id"] == "evidence-a-v2-unchanged"
    assert reviewed.json()["reviewed_by"] == "planner-a"

    source_group = next(
        item
        for item in duplicate_groups.json()
        if item["match_type"] == "source_id" and item["match_value"] == "source-a"
    )
    assert {item["evidence_id"] for item in source_group["records"]} == {
        "evidence-a",
        "evidence-a-v2-unchanged",
    }
    assert source_group["review"]["id"] == reviewed.json()["id"]
    assert source_group["review"]["notes"] == "优先使用最新批次记录"
    assert reviewed_page.status_code == 200
    assert reviewed_page.json()["summary"]["reviewed"] == 1
    assert reviewed_page.json()["total"] == 1
    assert reviewed_page.json()["items"][0]["match_type"] == "source_id"
    assert reviewed_page.json()["items"][0]["match_value"] == "source-a"
    assert reviewed_group_page.status_code == 200
    assert reviewed_group_page.json()["review"]["id"] == reviewed.json()["id"]
    assert reviewed_group_page.json()["canonical_record"]["evidence_id"] == (
        "evidence-a-v2-unchanged"
    )
    assert len(reviewed_group_page.json()["items"]) == 1
    assert audit_events.status_code == 200
    assert len(audit_events.json()) == 1
    assert audit_events.json()[0]["entity_id"] == reviewed.json()["id"]
    assert audit_events.json()[0]["detail"]["canonical_evidence_id"] == (
        "evidence-a-v2-unchanged"
    )

    resolver = EvidenceGovernanceResolver(app.state.integration_session_factory)
    governed = await resolver.resolve(
        [
            {"id": "evidence-a", "score": 0.9, "content": "租户 A 证据"},
            {"id": "evidence-a-v2-unchanged", "score": 0.8, "content": "租户 A 证据"},
            {"id": "evidence-a-v2-added", "score": 0.7, "content": "租户 A 新增证据"},
        ],
        tenant_id="tenant-a",
    )
    tenant_b_governed = await resolver.resolve(
        [
            {"id": "evidence-a", "score": 0.9, "content": "租户 A 证据"},
            {"id": "evidence-a-v2-unchanged", "score": 0.8, "content": "租户 A 证据"},
        ],
        tenant_id="tenant-b",
    )
    assert [hit["id"] for hit in governed.hits] == [
        "evidence-a-v2-unchanged",
        "evidence-a-v2-added",
    ]
    assert governed.suppressed_evidence_ids == ["evidence-a"]
    assert tenant_b_governed.suppressed_evidence_ids == []

    updated = await tenant_client.put(
        "/api/v1/data-imports/duplicates/review",
        headers=authorization("tenant-a-admin"),
        json={
            "match_type": "source_id",
            "match_value": "source-a",
            "decision": "keep_all",
            "notes": "两个批次均保留用于追溯",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["id"] == reviewed.json()["id"]
    assert updated.json()["decision"] == "keep_all"
    assert updated.json()["canonical_evidence_id"] is None


async def test_planner_can_retry_and_reindex_imports(
    tenant_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证“planner can retry and reindex imports”场景，确保业务规则、权限和异常边界保持稳定。"""
    class TaskResult:
        """提供`TaskResult`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
        id = "task-reindex"

    monkeypatch.setattr(
        imports_route_module.process_tabular_import,
        "delay",
        lambda import_id: type("TaskResult", (), {"id": "task-import-retry"})(),
    )
    monkeypatch.setattr(
        imports_route_module.index_evidence_batch,
        "delay",
        lambda evidence_ids: TaskResult(),
    )
    async with app.state.integration_session_factory() as session:
        import_job = await session.get(DataImportJob, "import-a")
        assert import_job is not None
        import_job.celery_task_id = "task-import-parse-existing"
        import_job.index_celery_task_id = "task-import-index-old"
        await session.commit()
    headers = authorization("tenant-a-planner")

    retry = await tenant_client.post(
        "/api/v1/data-imports/import-a-failed/retry",
        headers=headers,
    )
    reindex = await tenant_client.post(
        "/api/v1/data-imports/import-a/reindex",
        headers=headers,
    )

    assert retry.status_code == 202
    assert retry.json()["status"] == "queued"
    assert retry.json()["celery_task_id"] == "task-import-retry"
    assert reindex.status_code == 200
    assert reindex.json() == {
        "import_id": "import-a",
        "queued_records": 1,
        "task_id": "task-reindex",
    }
    retry_detail = await tenant_client.get(
        "/api/v1/data-imports/import-a-failed",
        headers=headers,
    )
    reindex_detail = await tenant_client.get(
        "/api/v1/data-imports/import-a",
        headers=headers,
    )
    assert retry_detail.status_code == 200
    assert retry_detail.json()["celery_task_id"] == "task-import-retry"
    assert retry_detail.json()["retrieval_status"] == "indexing"
    assert reindex_detail.status_code == 200
    assert reindex_detail.json()["celery_task_id"] == "task-import-parse-existing"
    assert reindex_detail.json()["index_celery_task_id"] == "task-reindex"
    assert reindex_detail.json()["indexed_rows"] == 1
    assert reindex_detail.json()["pending_index_rows"] == 1
    assert reindex_detail.json()["failed_index_rows"] == 0
    assert reindex_detail.json()["retrieval_status"] == "indexing"


async def test_planner_can_queue_report_and_track_task(
    tenant_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证“planner can queue report and track task”场景，确保业务规则、权限和异常边界保持稳定。"""
    monkeypatch.setattr(
        reports_route_module.generate_planning_report,
        "delay",
        lambda report_id: type("TaskResult", (), {"id": "task-report"})(),
    )
    headers = authorization("tenant-a-planner")

    response = await tenant_client.post(
        "/api/v1/planning-projects/project-a/runs/run-a/reports",
        headers=headers,
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["celery_task_id"] == "task-report"

    detail = await tenant_client.get(
        f"/api/v1/planning-reports/{payload['id']}",
        headers=authorization("tenant-a-viewer"),
    )
    assert detail.status_code == 200
    assert detail.json()["celery_task_id"] == "task-report"


async def test_async_task_status_is_tenant_scoped(
    tenant_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证“async task status is tenant scoped”场景，确保业务规则、权限和异常边界保持稳定。"""
    async with app.state.integration_session_factory() as session:
        run_a = await session.get(PlanningRun, "run-a")
        run_b = await session.get(PlanningRun, "run-b")
        import_a = await session.get(DataImportJob, "import-a")
        report_a = await session.get(PlanningReport, "report-a")
        assert run_a is not None
        assert run_b is not None
        assert import_a is not None
        assert report_a is not None
        run_a.celery_task_id = "task-run-a"
        run_b.celery_task_id = "task-run-b"
        import_a.celery_task_id = "task-import-a"
        import_a.index_celery_task_id = "task-import-index-a"
        report_a.celery_task_id = "task-report-a"
        await session.commit()

    states = {
        "task-run-a": "STARTED",
        "task-run-b": "FAILURE",
        "task-import-a": "PENDING",
        "task-import-index-a": "STARTED",
        "task-report-a": "SUCCESS",
    }

    class TaskResult:
        """提供`TaskResult`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
        def __init__(self, task_id: str) -> None:
            """辅助构造`init`测试数据或依赖，减少用例中的重复准备代码。"""
            self.state = states[task_id]

    monkeypatch.setattr(
        async_tasks_route_module.celery_app,
        "AsyncResult",
        lambda task_id: TaskResult(task_id),
    )

    response = await tenant_client.get(
        "/api/v1/async-tasks/status",
        params={
            "task_ids": (
                "task-run-a,task-run-b,task-import-a,task-import-index-a,"
                "task-report-a,unknown"
            )
        },
        headers=authorization("tenant-a-viewer"),
    )

    assert response.status_code == 200
    assert {item["task_id"] for item in response.json()} == {
        "task-run-a",
        "task-import-a",
        "task-import-index-a",
        "task-report-a",
    }
    by_task_id = {item["task_id"]: item for item in response.json()}
    assert by_task_id["task-run-a"]["state_label"] == "执行中"
    assert by_task_id["task-run-a"]["terminal"] is False
    assert by_task_id["task-import-a"]["state_label"] == "排队中"
    assert by_task_id["task-import-index-a"]["state_label"] == "执行中"
    assert by_task_id["task-report-a"]["state_label"] == "已完成"
    assert by_task_id["task-report-a"]["terminal"] is True


async def test_planner_can_review_evidence_quality(
    tenant_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证“planner can review evidence quality”场景，确保业务规则、权限和异常边界保持稳定。"""
    class TaskResult:
        """提供`TaskResult`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
        id = "task-quality-review"

    deleted_ids: list[str] = []

    def delete_vectors(store, evidence_ids: list[str]) -> dict[str, int]:
        """辅助构造`delete vectors`测试数据或依赖，减少用例中的重复准备代码。"""
        del store
        deleted_ids.extend(evidence_ids)
        return {"delete_count": len(evidence_ids)}

    monkeypatch.setattr(imports_route_module.MilvusVectorStore, "delete", delete_vectors)
    monkeypatch.setattr(
        imports_route_module.index_evidence_batch,
        "delay",
        lambda evidence_ids: TaskResult(),
    )
    headers = authorization("tenant-a-planner")

    missing_note = await tenant_client.patch(
        "/api/v1/data-imports/import-a/evidence/evidence-a-reindex/quality-review",
        headers=headers,
        json={"action": "block"},
    )
    verified = await tenant_client.patch(
        "/api/v1/data-imports/import-a/evidence/evidence-a-reindex/quality-review",
        headers=headers,
        json={"action": "verify", "note": "人工确认内容可用"},
    )
    blocked = await tenant_client.patch(
        "/api/v1/data-imports/import-a/evidence/evidence-a-reindex/quality-review",
        headers=headers,
        json={"action": "block", "note": "来源无法核验"},
    )
    viewer = await tenant_client.patch(
        "/api/v1/data-imports/import-a/evidence/evidence-a-reindex/quality-review",
        headers=authorization("tenant-a-viewer"),
        json={"action": "verify"},
    )

    assert missing_note.status_code == 422
    assert verified.status_code == 200
    assert verified.json()["quality_status"] == "verified"
    assert verified.json()["index_status"] == "pending"
    assert verified.json()["metadata_json"]["quality_review"]["note"] == "人工确认内容可用"
    assert blocked.status_code == 200
    assert blocked.json()["quality_status"] == "blocked"
    assert blocked.json()["index_status"] == "failed"
    assert blocked.json()["metadata_json"]["quality_review"]["action"] == "block"
    assert deleted_ids == ["evidence-a-reindex"]
    assert viewer.status_code == 403

    audits = await tenant_client.get(
        "/api/v1/audit-events",
        params={"entity_type": "evidence_record", "action": "evidence.quality_reviewed"},
        headers=authorization("tenant-a-admin"),
    )
    assert audits.status_code == 200
    assert [item["entity_id"] for item in audits.json()] == [
        "evidence-a-reindex",
        "evidence-a-reindex",
    ]


async def test_planner_can_withdraw_completed_import(
    tenant_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证“planner can withdraw completed import”场景，确保业务规则、权限和异常边界保持稳定。"""
    deleted_ids: list[str] = []

    def delete_vectors(store, evidence_ids: list[str]) -> dict[str, int]:
        """辅助构造`delete vectors`测试数据或依赖，减少用例中的重复准备代码。"""
        del store
        deleted_ids.extend(evidence_ids)
        return {"delete_count": len(evidence_ids)}

    monkeypatch.setattr(imports_route_module.MilvusVectorStore, "delete", delete_vectors)
    headers = authorization("tenant-a-planner")

    withdrawn = await tenant_client.delete("/api/v1/data-imports/import-a", headers=headers)
    missing = await tenant_client.get("/api/v1/data-imports/import-a", headers=headers)
    historical_evidence = await tenant_client.get(
        "/api/v1/planning-projects/project-a/runs/run-a/evidence",
        headers=headers,
    )
    historical_evidence_page = await tenant_client.get(
        "/api/v1/planning-projects/project-a/runs/run-a/evidence/page",
        params={"page": 1, "page_size": 1},
        headers=headers,
    )

    assert withdrawn.status_code == 204
    assert missing.status_code == 404
    assert deleted_ids == ["evidence-a"]
    assert historical_evidence.status_code == 200
    assert historical_evidence.json()[0]["available"] is False
    assert historical_evidence.json()[0]["source_name"] == "运行快照.xlsx"
    assert historical_evidence.json()[0]["content"] == "租户 A 运行时证据摘要"
    assert historical_evidence_page.status_code == 200
    assert historical_evidence_page.json()["unavailable_total"] == 1
    assert historical_evidence_page.json()["items"] == historical_evidence.json()


async def test_planner_cannot_withdraw_import_while_indexing(
    tenant_client: AsyncClient,
) -> None:
    """验证“planner cannot withdraw import while indexing”场景，确保业务规则、权限和异常边界保持稳定。"""
    async with app.state.integration_session_factory() as session:
        evidence = await session.get(EvidenceRecord, "evidence-a-reindex")
        assert evidence is not None
        evidence.index_status = "indexing"
        await session.commit()

    response = await tenant_client.delete(
        "/api/v1/data-imports/import-a",
        headers=authorization("tenant-a-planner"),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Milvus 索引仍在处理中，请等待完成或先处理索引失败记录"


async def test_created_project_is_bound_to_authenticated_tenant(
    tenant_client: AsyncClient,
) -> None:
    """验证“created project is bound to authenticated tenant”场景，确保业务规则、权限和异常边界保持稳定。"""
    created = await tenant_client.post(
        "/api/v1/planning-projects",
        headers=authorization("tenant-a-planner"),
        json={
            "name": "租户 A 新项目",
            "category": "户外用品",
            "target_market": "欧洲",
            "constraints": {},
        },
    )

    assert created.status_code == 201
    assert created.json()["tenant_id"] == "tenant-a"

    tenant_b_projects = await tenant_client.get(
        "/api/v1/planning-projects",
        headers=authorization("tenant-b-viewer"),
    )
    assert created.json()["id"] not in {item["id"] for item in tenant_b_projects.json()}


async def test_project_archive_lifecycle_is_tenant_scoped(
    tenant_client: AsyncClient,
) -> None:
    """验证“project archive lifecycle is tenant scoped”场景，确保业务规则、权限和异常边界保持稳定。"""
    planner_headers = authorization("tenant-a-planner")
    created = await tenant_client.post(
        "/api/v1/planning-projects",
        headers=planner_headers,
        json={
            "name": "待归档项目",
            "category": "家居用品",
            "target_market": "中国",
            "constraints": {},
        },
    )
    project_id = created.json()["id"]

    viewer_archive = await tenant_client.post(
        f"/api/v1/planning-projects/{project_id}/archive",
        headers=authorization("tenant-a-viewer"),
    )
    active_archive = await tenant_client.post(
        "/api/v1/planning-projects/project-a/archive",
        headers=planner_headers,
    )
    archived = await tenant_client.post(
        f"/api/v1/planning-projects/{project_id}/archive",
        headers=planner_headers,
    )
    active_projects = await tenant_client.get(
        "/api/v1/planning-projects",
        headers=authorization("tenant-a-viewer"),
    )
    all_projects = await tenant_client.get(
        "/api/v1/planning-projects?include_archived=true",
        headers=authorization("tenant-a-viewer"),
    )
    archived_page = await tenant_client.get(
        "/api/v1/planning-projects/page",
        params={"archived_only": True, "project_id": project_id, "page": 1, "page_size": 1},
        headers=authorization("tenant-a-viewer"),
    )
    archived_update = await tenant_client.patch(
        f"/api/v1/planning-projects/{project_id}",
        headers=planner_headers,
        json={"name": "不应修改"},
    )
    cross_tenant_restore = await tenant_client.post(
        f"/api/v1/planning-projects/{project_id}/restore",
        headers=authorization("tenant-b-admin"),
    )
    restored = await tenant_client.post(
        f"/api/v1/planning-projects/{project_id}/restore",
        headers=planner_headers,
    )
    restored_projects = await tenant_client.get(
        "/api/v1/planning-projects",
        headers=authorization("tenant-a-viewer"),
    )

    assert created.status_code == 201
    assert viewer_archive.status_code == 403
    assert active_archive.status_code == 409
    assert archived.status_code == 200
    assert archived.json()["archived_by"] == "planner-a"
    assert archived.json()["archived_at"] is not None
    assert project_id not in {item["id"] for item in active_projects.json()}
    assert project_id in {item["id"] for item in all_projects.json()}
    assert archived_page.status_code == 200
    assert archived_page.headers["X-Total-Count"] == "1"
    assert [item["id"] for item in archived_page.json()["items"]] == [project_id]
    assert archived_page.json()["summary"]["total"] == 1
    assert archived_update.status_code == 409
    assert cross_tenant_restore.status_code == 404
    assert restored.status_code == 200
    assert restored.json()["archived_by"] is None
    assert restored.json()["archived_at"] is None
    assert project_id in {item["id"] for item in restored_projects.json()}


async def test_approval_claim_lifecycle_prevents_parallel_processing(
    tenant_client: AsyncClient,
) -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    viewer_claim = await tenant_client.post(
        "/api/v1/approval-tasks/approval-a/claim",
        headers=authorization("tenant-a-viewer"),
    )
    cross_tenant_claim = await tenant_client.post(
        "/api/v1/approval-tasks/approval-b/claim",
        headers=authorization("tenant-a-approver"),
    )
    claimed = await tenant_client.post(
        "/api/v1/approval-tasks/approval-a/claim",
        headers=authorization("tenant-a-approver"),
    )
    duplicate_claim = await tenant_client.post(
        "/api/v1/approval-tasks/approval-a/claim",
        headers=authorization("tenant-a-approver"),
    )
    competing_claim = await tenant_client.post(
        "/api/v1/approval-tasks/approval-a/claim",
        headers=authorization("tenant-a-approver-2"),
    )
    competing_decision = await tenant_client.post(
        "/api/v1/approval-tasks/approval-a/decision",
        headers=authorization("tenant-a-approver-2"),
        json={"action": "approved", "comment": "并发审批", "changes": {}},
    )
    competing_release = await tenant_client.post(
        "/api/v1/approval-tasks/approval-a/release",
        headers=authorization("tenant-a-approver-2"),
    )
    admin_release = await tenant_client.post(
        "/api/v1/approval-tasks/approval-a/release",
        headers=authorization("tenant-a-admin"),
    )
    reassigned = await tenant_client.post(
        "/api/v1/approval-tasks/approval-a/claim",
        headers=authorization("tenant-a-approver-2"),
    )
    non_admin_assign = await tenant_client.post(
        "/api/v1/approval-tasks/approval-a/assign",
        headers=authorization("tenant-a-approver"),
        json={"assignee_id": "approver-a"},
    )
    cross_tenant_assign = await tenant_client.post(
        "/api/v1/approval-tasks/approval-b/assign",
        headers=authorization("tenant-a-admin"),
        json={"assignee_id": "approver-a"},
    )
    admin_assign = await tenant_client.post(
        "/api/v1/approval-tasks/approval-a/assign",
        headers=authorization("tenant-a-admin"),
        json={"assignee_id": "approver-a"},
    )
    audits = await tenant_client.get(
        "/api/v1/audit-events",
        headers=authorization("tenant-a-admin"),
    )

    assert viewer_claim.status_code == 403
    assert cross_tenant_claim.status_code == 404
    assert claimed.status_code == 200
    assert claimed.json()["assignee_id"] == "approver-a"
    assert claimed.json()["due_at"] is not None
    assert duplicate_claim.status_code == 200
    assert duplicate_claim.json()["assignee_id"] == "approver-a"
    assert competing_claim.status_code == 409
    assert competing_decision.status_code == 409
    assert competing_release.status_code == 403
    assert admin_release.status_code == 200
    assert admin_release.json()["assignee_id"] is None
    assert reassigned.status_code == 200
    assert reassigned.json()["assignee_id"] == "approver-a-2"
    assert non_admin_assign.status_code == 403
    assert cross_tenant_assign.status_code == 404
    assert admin_assign.status_code == 200
    assert admin_assign.json()["assignee_id"] == "approver-a"
    approval_actions = {
        item["action"]
        for item in audits.json()
        if item["entity_type"] == "approval_task" and item["entity_id"] == "approval-a"
    }
    assert {"approval.claimed", "approval.released", "approval.assigned"} <= approval_actions


async def test_mcp_approval_claim_and_decision_are_guarded_and_idempotent(
    tenant_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    dispatched: list[tuple[str, str, dict[str, object]]] = []

    def fake_delay(run_id: str, thread_id: str, decision: dict[str, object]) -> None:
        """模拟`delay`外部行为，避免测试依赖真实异步服务。"""
        dispatched.append((run_id, thread_id, decision))

    monkeypatch.setattr(approvals_route_module.resume_planning_run, "delay", fake_delay)
    initial_task = await tenant_client.get(
        "/api/v1/approval-tasks/approval-a",
        headers=authorization("tenant-a-approver"),
    )
    initial_payload = initial_task.json()
    initial_review_token = approval_review_fingerprint(
        task_id=initial_payload["id"],
        project_id=initial_payload["project_id"],
        run_id=initial_payload["run_id"],
        approval_type=initial_payload["approval_type"],
        checkpoint_ref=initial_payload["checkpoint_ref"],
        status=initial_payload["status"],
        assignee_id=initial_payload["assignee_id"],
        due_at=initial_payload["due_at"],
        summary=initial_payload["summary"],
    )
    base_headers = {
        **authorization("tenant-a-approver"),
        "X-MerchPilot-Client": "FastMCP",
    }
    before_claim = await tenant_client.post(
        "/api/v1/approval-tasks/approval-a/decision",
        headers={**base_headers, "Idempotency-Key": "mcp-approval-before-claim-001"},
        json={
            "action": "rejected",
            "comment": "证据不足，暂不通过。",
            "changes": {},
            "confirmation": "REJECT_PLANNING",
            "review_token": initial_review_token,
        },
    )
    missing_request_id = await tenant_client.post(
        "/api/v1/approval-tasks/approval-a/claim",
        headers=base_headers,
    )
    viewer_claim = await tenant_client.post(
        "/api/v1/approval-tasks/approval-a/claim",
        headers={
            **authorization("tenant-a-viewer"),
            "X-MerchPilot-Client": "fastmcp",
            "Idempotency-Key": "mcp-approval-viewer-001",
        },
    )
    cross_tenant_claim = await tenant_client.post(
        "/api/v1/approval-tasks/approval-b/claim",
        headers={**base_headers, "Idempotency-Key": "mcp-approval-cross-tenant-001"},
    )
    claim_headers = {**base_headers, "Idempotency-Key": "mcp-approval-claim-001"}
    claimed = await tenant_client.post(
        "/api/v1/approval-tasks/approval-a/claim",
        headers=claim_headers,
    )
    claim_replay = await tenant_client.post(
        "/api/v1/approval-tasks/approval-a/claim",
        headers=claim_headers,
    )
    competing_claim = await tenant_client.post(
        "/api/v1/approval-tasks/approval-a/claim",
        headers={
            **authorization("tenant-a-approver-2"),
            "X-MerchPilot-Client": "fastmcp",
            "Idempotency-Key": "mcp-approval-competing-001",
        },
    )
    claimed_payload = claimed.json()
    review_token = approval_review_fingerprint(
        task_id=claimed_payload["id"],
        project_id=claimed_payload["project_id"],
        run_id=claimed_payload["run_id"],
        approval_type=claimed_payload["approval_type"],
        checkpoint_ref=claimed_payload["checkpoint_ref"],
        status=claimed_payload["status"],
        assignee_id=claimed_payload["assignee_id"],
        due_at=claimed_payload["due_at"],
        summary=claimed_payload["summary"],
    )
    wrong_confirmation = await tenant_client.post(
        "/api/v1/approval-tasks/approval-a/decision",
        headers={**base_headers, "Idempotency-Key": "mcp-approval-confirmation-001"},
        json={
            "action": "rejected",
            "comment": "证据不足，暂不通过。",
            "changes": {},
            "confirmation": "APPROVE_PLANNING",
            "review_token": review_token,
        },
    )
    stale_review = await tenant_client.post(
        "/api/v1/approval-tasks/approval-a/decision",
        headers={**base_headers, "Idempotency-Key": "mcp-approval-stale-001"},
        json={
            "action": "rejected",
            "comment": "证据不足，暂不通过。",
            "changes": {},
            "confirmation": "REJECT_PLANNING",
            "review_token": initial_review_token,
        },
    )
    unsafe_changes = await tenant_client.post(
        "/api/v1/approval-tasks/approval-a/decision",
        headers={**base_headers, "Idempotency-Key": "mcp-approval-unsafe-001"},
        json={
            "action": "rejected",
            "comment": "证据不足，暂不通过。",
            "changes": {"selected_candidate_id": "candidate-a"},
            "confirmation": "REJECT_PLANNING",
            "review_token": review_token,
        },
    )
    decision_headers = {**base_headers, "Idempotency-Key": "mcp-approval-decision-001"}
    decision_payload = {
        "action": "rejected",
        "comment": "证据不足，暂不通过。",
        "changes": {},
        "confirmation": "REJECT_PLANNING",
        "review_token": review_token,
    }
    decided = await tenant_client.post(
        "/api/v1/approval-tasks/approval-a/decision",
        headers=decision_headers,
        json=decision_payload,
    )
    decision_replay = await tenant_client.post(
        "/api/v1/approval-tasks/approval-a/decision",
        headers=decision_headers,
        json=decision_payload,
    )
    decision_conflict = await tenant_client.post(
        "/api/v1/approval-tasks/approval-a/decision",
        headers=decision_headers,
        json={**decision_payload, "comment": "改用另一个驳回理由。"},
    )
    audits = await tenant_client.get(
        "/api/v1/audit-events",
        params={"entity_type": "approval_task"},
        headers=authorization("tenant-a-admin"),
    )
    approver_activities = await tenant_client.get(
        "/api/v1/integrations/mcp/activities?page=1&page_size=5",
        headers=authorization("tenant-a-approver"),
    )
    viewer_activities = await tenant_client.get(
        "/api/v1/integrations/mcp/activities?page=1&page_size=5",
        headers=authorization("tenant-a-viewer"),
    )

    assert initial_task.status_code == 200
    assert before_claim.status_code == 409
    assert missing_request_id.status_code == 422
    assert viewer_claim.status_code == 403
    assert cross_tenant_claim.status_code == 404
    assert claimed.status_code == 200
    assert claimed.headers["Idempotency-Replayed"] == "false"
    assert claimed_payload["assignee_id"] == "approver-a"
    assert claim_replay.status_code == 200
    assert claim_replay.headers["Idempotency-Replayed"] == "true"
    assert competing_claim.status_code == 409
    assert wrong_confirmation.status_code == 422
    assert stale_review.status_code == 409
    assert unsafe_changes.status_code == 422
    assert decided.status_code == 200
    assert decided.headers["Idempotency-Replayed"] == "false"
    assert decided.json()["status"] == "rejected"
    assert decided.json()["decided_by"] == "approver-a"
    assert decided.json()["decision"] == {
        "action": "rejected",
        "comment": "证据不足，暂不通过。",
        "changes": {},
    }
    assert decision_replay.status_code == 200
    assert decision_replay.headers["Idempotency-Replayed"] == "true"
    assert decision_conflict.status_code == 409
    assert dispatched == [
        (
            "run-a",
            "thread-a",
            {
                "action": "rejected",
                "comment": "证据不足，暂不通过。",
                "changes": {},
            },
        )
    ]
    approval_audits = [
        item for item in audits.json() if item["entity_id"] == "approval-a"
    ]
    claim_audit = next(item for item in approval_audits if item["action"] == "approval.claimed")
    decision_audit = next(item for item in approval_audits if item["action"] == "approval.rejected")
    assert claim_audit["detail"]["client"] == "fastmcp"
    assert claim_audit["detail"]["idempotency_key"] == "mcp-approval-claim-001"
    assert decision_audit["detail"]["client"] == "fastmcp"
    assert decision_audit["detail"]["review_token"] == review_token
    assert approver_activities.status_code == 200
    project_activity = next(
        item for item in approver_activities.json()["items"] if item["project_id"] == "project-a"
    )
    assert project_activity["activity_type"] == "mcp_approval_decided"
    assert project_activity["request_id"] == "mcp-approval-decision-001"
    assert project_activity["latest_approval_request_id"] == "mcp-approval-decision-001"
    assert project_activity["latest_approval_actor_id"] == "approver-a"
    assert project_activity["latest_approval_task_id"] == "approval-a"
    assert project_activity["latest_approval_event"] == "rejected"
    assert project_activity["latest_approval_status"] == "rejected"
    assert viewer_activities.status_code == 403


async def test_mcp_approval_dispatch_failure_rolls_back_and_allows_retry(
    tenant_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    dispatch_attempts = 0

    def flaky_delay(run_id: str, thread_id: str, decision: dict[str, object]) -> None:
        """辅助构造`flaky delay`测试数据或依赖，减少用例中的重复准备代码。"""
        nonlocal dispatch_attempts
        dispatch_attempts += 1
        if dispatch_attempts == 1:
            raise RuntimeError("queue unavailable")

    monkeypatch.setattr(approvals_route_module.resume_planning_run, "delay", flaky_delay)
    headers = {
        **authorization("tenant-a-approver"),
        "X-MerchPilot-Client": "fastmcp",
        "Idempotency-Key": "mcp-approval-retry-claim-001",
    }
    claimed = await tenant_client.post(
        "/api/v1/approval-tasks/approval-a/claim",
        headers=headers,
    )
    task = claimed.json()
    review_token = approval_review_fingerprint(
        task_id=task["id"],
        project_id=task["project_id"],
        run_id=task["run_id"],
        approval_type=task["approval_type"],
        checkpoint_ref=task["checkpoint_ref"],
        status=task["status"],
        assignee_id=task["assignee_id"],
        due_at=task["due_at"],
        summary=task["summary"],
    )
    decision_headers = {
        **authorization("tenant-a-approver"),
        "X-MerchPilot-Client": "fastmcp",
        "Idempotency-Key": "mcp-approval-retry-decision-001",
    }
    decision_payload = {
        "action": "rejected",
        "comment": "当前数据不能支撑立项。",
        "changes": {},
        "confirmation": "REJECT_PLANNING",
        "review_token": review_token,
    }
    failed = await tenant_client.post(
        "/api/v1/approval-tasks/approval-a/decision",
        headers=decision_headers,
        json=decision_payload,
    )
    after_failure = await tenant_client.get(
        "/api/v1/approval-tasks/approval-a",
        headers=authorization("tenant-a-approver"),
    )
    retried = await tenant_client.post(
        "/api/v1/approval-tasks/approval-a/decision",
        headers=decision_headers,
        json=decision_payload,
    )
    replayed = await tenant_client.post(
        "/api/v1/approval-tasks/approval-a/decision",
        headers=decision_headers,
        json=decision_payload,
    )
    failed_audits = await tenant_client.get(
        "/api/v1/audit-events",
        params={"action": "approval.dispatch_failed"},
        headers=authorization("tenant-a-admin"),
    )

    assert claimed.status_code == 200
    assert failed.status_code == 503
    assert after_failure.status_code == 200
    assert after_failure.json()["status"] == "pending"
    assert after_failure.json()["assignee_id"] == "approver-a"
    assert after_failure.json()["decision"] is None
    assert after_failure.json()["decision_request_id"] is None
    assert retried.status_code == 200
    assert retried.headers["Idempotency-Replayed"] == "false"
    assert replayed.status_code == 200
    assert replayed.headers["Idempotency-Replayed"] == "true"
    assert dispatch_attempts == 2
    assert len(failed_audits.json()) == 1
    assert failed_audits.json()[0]["detail"] == {
        "run_id": "run-a",
        "client": "fastmcp",
        "decision_request_id": "mcp-approval-retry-decision-001",
        "error": "queue unavailable",
    }


async def test_project_creation_idempotency_is_scoped_and_audited(
    tenant_client: AsyncClient,
) -> None:
    """验证“project creation idempotency is scoped and audited”场景，确保业务规则、权限和异常边界保持稳定。"""
    payload = {
        "name": "MCP 幂等规划草稿",
        "category": "保温杯",
        "target_market": "中国",
        "constraints": {"target_margin": 0.35, "price_range": {"min": 129, "max": 199}},
    }
    planner_headers = {
        **authorization("tenant-a-planner"),
        "Idempotency-Key": "mcp-project-draft-001",
        "X-MerchPilot-Client": "fastmcp",
    }
    first = await tenant_client.post(
        "/api/v1/planning-projects",
        headers=planner_headers,
        json=payload,
    )
    replay = await tenant_client.post(
        "/api/v1/planning-projects",
        headers=planner_headers,
        json=payload,
    )
    conflict = await tenant_client.post(
        "/api/v1/planning-projects",
        headers=planner_headers,
        json={**payload, "name": "同一请求标识的不同内容"},
    )
    viewer = await tenant_client.post(
        "/api/v1/planning-projects",
        headers={
            **authorization("tenant-a-viewer"),
            "Idempotency-Key": "mcp-project-draft-viewer",
        },
        json=payload,
    )
    blank_request_key = await tenant_client.post(
        "/api/v1/planning-projects",
        headers={
            **authorization("tenant-a-planner"),
            "Idempotency-Key": "        ",
        },
        json=payload,
    )
    admin_same_key = await tenant_client.post(
        "/api/v1/planning-projects",
        headers={
            **authorization("tenant-a-admin"),
            "Idempotency-Key": "mcp-project-draft-001",
        },
        json={**payload, "name": "管理员独立草稿"},
    )
    tenant_b_same_key = await tenant_client.post(
        "/api/v1/planning-projects",
        headers={
            **authorization("tenant-b-admin"),
            "Idempotency-Key": "mcp-project-draft-001",
        },
        json={**payload, "name": "租户 B 独立草稿"},
    )
    audits = await tenant_client.get(
        "/api/v1/audit-events",
        headers=authorization("tenant-a-admin"),
    )
    activities = await tenant_client.get(
        "/api/v1/integrations/mcp/activities?page=1&page_size=1",
        headers=authorization("tenant-a-planner"),
    )
    viewer_activities = await tenant_client.get(
        "/api/v1/integrations/mcp/activities",
        headers=authorization("tenant-a-viewer"),
    )
    tenant_b_activities = await tenant_client.get(
        "/api/v1/integrations/mcp/activities",
        headers=authorization("tenant-b-admin"),
    )

    assert first.status_code == 201
    assert first.headers["Idempotency-Replayed"] == "false"
    assert replay.status_code == 200
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json()["id"] == first.json()["id"]
    assert conflict.status_code == 409
    assert viewer.status_code == 403
    assert blank_request_key.status_code == 422
    assert admin_same_key.status_code == 201
    assert admin_same_key.json()["id"] != first.json()["id"]
    assert tenant_b_same_key.status_code == 201
    assert tenant_b_same_key.json()["tenant_id"] == "tenant-b"
    assert activities.status_code == 200
    assert activities.json()["total"] == 1
    assert activities.json()["page_size"] == 1
    assert activities.json()["items"][0]["request_id"] == "mcp-project-draft-001"
    assert activities.json()["items"][0]["activity_type"] == "mcp_created"
    assert activities.json()["items"][0]["project_id"] == first.json()["id"]
    assert activities.json()["items"][0]["project_name"] == payload["name"]
    assert activities.json()["items"][0]["actor_id"] == "planner-a"
    assert activities.json()["items"][0]["project_created_by"] == "planner-a"
    assert activities.json()["items"][0]["mcp_creation_request_id"] == "mcp-project-draft-001"
    assert activities.json()["items"][0]["mcp_creation_actor_id"] == "planner-a"
    assert activities.json()["items"][0]["mcp_created_at"] is not None
    assert activities.json()["items"][0]["latest_start_request_id"] is None
    assert activities.json()["items"][0]["latest_run_id"] is None
    assert viewer_activities.status_code == 403
    assert tenant_b_activities.status_code == 200
    assert tenant_b_activities.json()["total"] == 0
    matching_audits = [
        item
        for item in audits.json()
        if item["action"] == "project.created" and item["entity_id"] == first.json()["id"]
    ]
    assert len(matching_audits) == 1
    assert matching_audits[0]["detail"]["client"] == "fastmcp"
    assert matching_audits[0]["detail"]["idempotency_key"] == "mcp-project-draft-001"


async def test_mcp_analysis_start_requires_current_review_and_is_idempotent(
    tenant_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    submitted_tasks: list[tuple[str, str, dict[str, object]]] = []

    class SubmittedTask:
        """提供`SubmittedTask`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
        id = "task-mcp-analysis-001"

    def submit_task(run_id: str, thread_id: str, input_snapshot: dict[str, object]) -> SubmittedTask:
        """辅助构造`submit task`测试数据或依赖，减少用例中的重复准备代码。"""
        submitted_tasks.append((run_id, thread_id, input_snapshot))
        return SubmittedTask()

    monkeypatch.setattr(projects_route_module.execute_planning_run, "delay", submit_task)
    project_payload = {
        "name": "MCP 待复核分析项目",
        "category": "保温杯",
        "target_market": "中国",
        "constraints": {"target_margin": 0.38, "price_range": {"min": 139, "max": 209}},
    }
    project = await tenant_client.post(
        "/api/v1/planning-projects",
        headers={
            **authorization("tenant-a-planner"),
            "Idempotency-Key": "mcp-analysis-project-001",
            "X-MerchPilot-Client": "fastmcp",
        },
        json=project_payload,
    )
    project_id = project.json()["id"]
    review_token = project_configuration_fingerprint(
        name=project_payload["name"],
        category=project_payload["category"],
        target_market=project_payload["target_market"],
        constraints=project_payload["constraints"],
    )
    start_headers = {
        **authorization("tenant-a-planner"),
        "Idempotency-Key": "mcp-analysis-run-001",
        "X-MerchPilot-Client": "fastmcp",
    }
    start_payload = {
        "confirmation": "START_AGENT_ANALYSIS",
        "review_token": review_token,
    }

    missing_confirmation = await tenant_client.post(
        f"/api/v1/planning-projects/{project_id}/runs",
        headers={
            **start_headers,
            "Idempotency-Key": "mcp-analysis-missing-001",
            "X-MerchPilot-Client": "FastMCP",
        },
        json={"review_token": review_token},
    )
    viewer = await tenant_client.post(
        f"/api/v1/planning-projects/{project_id}/runs",
        headers={
            **authorization("tenant-a-viewer"),
            "Idempotency-Key": "mcp-analysis-viewer-001",
            "X-MerchPilot-Client": "fastmcp",
        },
        json=start_payload,
    )
    cross_tenant = await tenant_client.post(
        f"/api/v1/planning-projects/{project_id}/runs",
        headers={
            **authorization("tenant-b-admin"),
            "Idempotency-Key": "mcp-analysis-tenant-b-001",
            "X-MerchPilot-Client": "fastmcp",
        },
        json=start_payload,
    )
    first = await tenant_client.post(
        f"/api/v1/planning-projects/{project_id}/runs",
        headers=start_headers,
        json=start_payload,
    )
    replay = await tenant_client.post(
        f"/api/v1/planning-projects/{project_id}/runs",
        headers=start_headers,
        json=start_payload,
    )
    conflict = await tenant_client.post(
        f"/api/v1/planning-projects/{project_id}/runs",
        headers=start_headers,
        json={**start_payload, "review_token": "0" * 64},
    )

    stale_payload = {**project_payload, "name": "MCP 旧令牌项目"}
    stale_project = await tenant_client.post(
        "/api/v1/planning-projects",
        headers=authorization("tenant-a-planner"),
        json=stale_payload,
    )
    stale_project_id = stale_project.json()["id"]
    stale_review_token = project_configuration_fingerprint(
        name=stale_payload["name"],
        category=stale_payload["category"],
        target_market=stale_payload["target_market"],
        constraints=stale_payload["constraints"],
    )
    updated = await tenant_client.patch(
        f"/api/v1/planning-projects/{stale_project_id}",
        headers=authorization("tenant-a-planner"),
        json={"name": "MCP 已更新参数项目"},
    )
    stale_start = await tenant_client.post(
        f"/api/v1/planning-projects/{stale_project_id}/runs",
        headers={
            **authorization("tenant-a-planner"),
            "Idempotency-Key": "mcp-analysis-stale-001",
            "X-MerchPilot-Client": "fastmcp",
        },
        json={
            "confirmation": "START_AGENT_ANALYSIS",
            "review_token": stale_review_token,
        },
    )
    non_draft_token = project_configuration_fingerprint(
        name="租户 A 项目",
        category="保温杯",
        target_market="中国",
        constraints={},
    )
    non_draft = await tenant_client.post(
        "/api/v1/planning-projects/project-a/runs",
        headers={
            **authorization("tenant-a-planner"),
            "Idempotency-Key": "mcp-analysis-nondraft-001",
            "X-MerchPilot-Client": "fastmcp",
        },
        json={
            "confirmation": "START_AGENT_ANALYSIS",
            "review_token": non_draft_token,
        },
    )
    takeover_payload = {
        "name": "Web 创建后由 MCP 接管",
        "category": "保温杯",
        "target_market": "中国",
        "constraints": {"target_margin": 0.4},
    }
    takeover_project = await tenant_client.post(
        "/api/v1/planning-projects",
        headers=authorization("tenant-a-planner"),
        json=takeover_payload,
    )
    takeover_project_id = takeover_project.json()["id"]
    takeover_review_token = project_configuration_fingerprint(
        name=takeover_payload["name"],
        category=takeover_payload["category"],
        target_market=takeover_payload["target_market"],
        constraints=takeover_payload["constraints"],
    )
    takeover_start = await tenant_client.post(
        f"/api/v1/planning-projects/{takeover_project_id}/runs",
        headers={
            **authorization("tenant-a-planner"),
            "Idempotency-Key": "mcp-takeover-run-001",
            "X-MerchPilot-Client": "fastmcp",
        },
        json={
            "confirmation": "START_AGENT_ANALYSIS",
            "review_token": takeover_review_token,
        },
    )
    runs = await tenant_client.get(
        f"/api/v1/planning-projects/{project_id}/runs/page",
        headers=authorization("tenant-a-planner"),
    )
    audits = await tenant_client.get(
        "/api/v1/audit-events",
        headers=authorization("tenant-a-admin"),
    )
    activities = await tenant_client.get(
        "/api/v1/integrations/mcp/activities?page=1&page_size=5",
        headers=authorization("tenant-a-planner"),
    )

    assert project.status_code == 201
    assert missing_confirmation.status_code == 422
    assert viewer.status_code == 403
    assert cross_tenant.status_code == 404
    assert first.status_code == 202
    assert first.headers["Idempotency-Replayed"] == "false"
    assert first.json()["status"] == "queued"
    assert replay.status_code == 200
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json()["id"] == first.json()["id"]
    assert conflict.status_code == 409
    assert updated.status_code == 200
    assert stale_start.status_code == 409
    assert "重新读取并复核" in stale_start.json()["detail"]
    assert non_draft.status_code == 409
    assert "草稿状态" in non_draft.json()["detail"]
    assert takeover_project.status_code == 201
    assert takeover_start.status_code == 202
    assert len(submitted_tasks) == 2
    assert runs.status_code == 200
    assert runs.json()["total"] == 1
    matching_audits = [
        item
        for item in audits.json()
        if item["action"] == "run.queued" and item["entity_id"] == first.json()["id"]
    ]
    assert len(matching_audits) == 1
    assert matching_audits[0]["detail"]["client"] == "fastmcp"
    assert matching_audits[0]["detail"]["idempotency_key"] == "mcp-analysis-run-001"
    assert matching_audits[0]["detail"]["review_token"] == review_token
    matching_activities = [
        item for item in activities.json()["items"] if item["project_id"] == project_id
    ]
    assert activities.status_code == 200
    assert len(matching_activities) == 1
    assert matching_activities[0]["activity_type"] == "mcp_started"
    assert matching_activities[0]["request_id"] == "mcp-analysis-run-001"
    assert matching_activities[0]["mcp_creation_request_id"] == "mcp-analysis-project-001"
    assert matching_activities[0]["latest_start_request_id"] == "mcp-analysis-run-001"
    assert matching_activities[0]["latest_start_actor_id"] == "planner-a"
    assert matching_activities[0]["latest_start_at"] is not None
    assert matching_activities[0]["latest_run_id"] == first.json()["id"]
    assert matching_activities[0]["latest_run_status"] == "queued"
    takeover_activities = [
        item for item in activities.json()["items"] if item["project_id"] == takeover_project_id
    ]
    assert len(takeover_activities) == 1
    assert takeover_activities[0]["activity_type"] == "mcp_started"
    assert takeover_activities[0]["request_id"] == "mcp-takeover-run-001"
    assert takeover_activities[0]["project_created_by"] == "planner-a"
    assert takeover_activities[0]["mcp_creation_request_id"] is None
    assert takeover_activities[0]["mcp_creation_actor_id"] is None
    assert takeover_activities[0]["latest_start_request_id"] == "mcp-takeover-run-001"
    assert takeover_activities[0]["latest_run_id"] == takeover_start.json()["id"]


async def test_web_analysis_start_remains_backward_compatible(
    tenant_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证“web analysis start remains backward compatible”场景，确保业务规则、权限和异常边界保持稳定。"""
    submitted_tasks: list[str] = []

    class SubmittedTask:
        """提供`SubmittedTask`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
        id = "task-web-analysis-001"

    def submit_task(run_id: str, thread_id: str, input_snapshot: dict[str, object]) -> SubmittedTask:
        """辅助构造`submit task`测试数据或依赖，减少用例中的重复准备代码。"""
        submitted_tasks.append(run_id)
        return SubmittedTask()

    monkeypatch.setattr(projects_route_module.execute_planning_run, "delay", submit_task)
    project = await tenant_client.post(
        "/api/v1/planning-projects",
        headers=authorization("tenant-a-planner"),
        json={
            "name": "Web 兼容启动项目",
            "category": "保温杯",
            "target_market": "中国",
            "constraints": {"target_margin": 0.35},
        },
    )

    started = await tenant_client.post(
        f"/api/v1/planning-projects/{project.json()['id']}/runs",
        headers=authorization("tenant-a-planner"),
    )

    assert project.status_code == 201
    assert started.status_code == 202
    assert started.json()["status"] == "queued"
    assert started.headers["Idempotency-Replayed"] == "false"
    assert submitted_tasks == [started.json()["id"]]

async def test_project_lifecycle_page_prioritizes_actionable_work(
    tenant_client: AsyncClient,
) -> None:
    """验证“project lifecycle page prioritizes actionable work”场景，确保业务规则、权限和异常边界保持稳定。"""
    now = datetime.now(UTC)
    async with app.state.integration_session_factory() as session:
        session.add_all(
            [
                PlanningProject(
                    id="lifecycle-sort-blocked",
                    tenant_id="tenant-a",
                    name="闭环排序验收-阻断",
                    category="保温杯",
                    target_market="中国",
                    status="failed",
                    constraints={},
                    created_by="planner-a",
                    created_at=now - timedelta(hours=4),
                    updated_at=now - timedelta(hours=4),
                ),
                PlanningProject(
                    id="lifecycle-sort-pending",
                    tenant_id="tenant-a",
                    name="闭环排序验收-待审批",
                    category="保温杯",
                    target_market="中国",
                    status="approval_required",
                    constraints={},
                    created_by="planner-a",
                    created_at=now - timedelta(hours=3),
                    updated_at=now - timedelta(hours=3),
                ),
                PlanningProject(
                    id="lifecycle-sort-active",
                    tenant_id="tenant-a",
                    name="闭环排序验收-推进中",
                    category="保温杯",
                    target_market="中国",
                    status="completed",
                    constraints={},
                    created_by="planner-a",
                    created_at=now - timedelta(hours=2),
                    updated_at=now - timedelta(hours=2),
                ),
                PlanningProject(
                    id="lifecycle-sort-complete",
                    tenant_id="tenant-a",
                    name="闭环排序验收-已上市",
                    category="保温杯",
                    target_market="中国",
                    status="completed",
                    constraints={},
                    created_by="planner-a",
                    created_at=now - timedelta(hours=1),
                    updated_at=now - timedelta(hours=1),
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                PlanningRun(
                    id="lifecycle-sort-run-pending",
                    project_id="lifecycle-sort-pending",
                    thread_id="lifecycle-sort-thread-pending",
                    status="approval_required",
                    input_snapshot={},
                    result_snapshot={},
                ),
                PlanningRun(
                    id="lifecycle-sort-run-active",
                    project_id="lifecycle-sort-active",
                    thread_id="lifecycle-sort-thread-active",
                    status="completed",
                    input_snapshot={},
                    result_snapshot={},
                ),
                PlanningRun(
                    id="lifecycle-sort-run-complete",
                    project_id="lifecycle-sort-complete",
                    thread_id="lifecycle-sort-thread-complete",
                    status="completed",
                    input_snapshot={},
                    result_snapshot={},
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                ApprovalTask(
                    id="lifecycle-sort-approval-pending",
                    project_id="lifecycle-sort-pending",
                    run_id="lifecycle-sort-run-pending",
                    approval_type="planning_review",
                    status="pending",
                    checkpoint_ref="lifecycle-sort-checkpoint-pending",
                    summary={},
                ),
                ApprovalTask(
                    id="lifecycle-sort-approval-active",
                    project_id="lifecycle-sort-active",
                    run_id="lifecycle-sort-run-active",
                    approval_type="planning_review",
                    status="approved",
                    checkpoint_ref="lifecycle-sort-checkpoint-active",
                    summary={},
                ),
                ApprovalTask(
                    id="lifecycle-sort-approval-complete",
                    project_id="lifecycle-sort-complete",
                    run_id="lifecycle-sort-run-complete",
                    approval_type="planning_review",
                    status="approved",
                    checkpoint_ref="lifecycle-sort-checkpoint-complete",
                    summary={},
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                SelectedProduct(
                    id="lifecycle-sort-selection-active",
                    tenant_id="tenant-a",
                    project_id="lifecycle-sort-active",
                    run_id="lifecycle-sort-run-active",
                    approval_task_id="lifecycle-sort-approval-active",
                    candidate_id="lifecycle-sort-candidate-active",
                    name="闭环排序验收商品-推进中",
                    project_name="闭环排序验收-推进中",
                    category="保温杯",
                    target_market="中国",
                    status="initiated",
                    validation_status="ready",
                    selection_snapshot={},
                    selected_by="approver-a",
                    selected_at=now,
                ),
                SelectedProduct(
                    id="lifecycle-sort-selection-complete",
                    tenant_id="tenant-a",
                    project_id="lifecycle-sort-complete",
                    run_id="lifecycle-sort-run-complete",
                    approval_task_id="lifecycle-sort-approval-complete",
                    candidate_id="lifecycle-sort-candidate-complete",
                    name="闭环排序验收商品-已上市",
                    project_name="闭环排序验收-已上市",
                    category="保温杯",
                    target_market="中国",
                    status="launched",
                    validation_status="ready",
                    selection_snapshot={},
                    selected_by="approver-a",
                    selected_at=now,
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                ProductInitiative(
                    id="lifecycle-sort-initiative-active",
                    tenant_id="tenant-a",
                    selected_product_id="lifecycle-sort-selection-active",
                    project_id="lifecycle-sort-active",
                    run_id="lifecycle-sort-run-active",
                    name="闭环排序验收立项-推进中",
                    category="保温杯",
                    target_market="中国",
                    status="in_progress",
                    milestones=[
                        {
                            "id": "sample_finalize",
                            "label": "样品定版",
                            "status": "in_progress",
                        }
                    ],
                    created_by="planner-a",
                ),
                ProductInitiative(
                    id="lifecycle-sort-initiative-complete",
                    tenant_id="tenant-a",
                    selected_product_id="lifecycle-sort-selection-complete",
                    project_id="lifecycle-sort-complete",
                    run_id="lifecycle-sort-run-complete",
                    name="闭环排序验收立项-已上市",
                    category="保温杯",
                    target_market="中国",
                    status="launched",
                    milestones=[],
                    created_by="planner-a",
                    launched_at=now,
                ),
            ]
        )
        await session.flush()
        session.add(
            ProductLaunchReview(
                id="lifecycle-sort-review-complete",
                tenant_id="tenant-a",
                initiative_id="lifecycle-sort-initiative-complete",
                status="approved",
                readiness_snapshot={},
                submitted_by="planner-a",
                submitted_at=now,
                decided_by="approver-a",
                decided_at=now,
            )
        )
        await session.commit()

    priority_page = await tenant_client.get(
        "/api/v1/analytics/project-lifecycles/page",
        params={"keyword": "闭环排序验收", "sort": "priority", "page": 1, "page_size": 10},
        headers=authorization("tenant-a-viewer"),
    )
    updated_page = await tenant_client.get(
        "/api/v1/analytics/project-lifecycles/page",
        params={"keyword": "闭环排序验收", "sort": "updated", "page": 1, "page_size": 10},
        headers=authorization("tenant-a-viewer"),
    )
    waiting_human_page = await tenant_client.get(
        "/api/v1/analytics/project-lifecycles/page",
        params={
            "keyword": "闭环排序验收",
            "status": "waiting_human",
            "page": 1,
            "page_size": 10,
        },
        headers=authorization("tenant-a-viewer"),
    )
    exact_project_page = await tenant_client.get(
        "/api/v1/analytics/project-lifecycles/page",
        params={
            "project_id": "lifecycle-sort-active",
            "page": 1,
            "page_size": 1,
        },
        headers=authorization("tenant-a-viewer"),
    )

    assert priority_page.status_code == 200
    assert [item["project_id"] for item in priority_page.json()["items"]] == [
        "lifecycle-sort-blocked",
        "lifecycle-sort-pending",
        "lifecycle-sort-active",
        "lifecycle-sort-complete",
    ]
    assert [item["health"] for item in priority_page.json()["items"]] == [
        "blocked",
        "attention",
        "on_track",
        "complete",
    ]
    assert priority_page.json()["summary"] == {
        "total": 4,
        "blocked": 1,
        "waiting_human": 1,
        "active": 1,
        "complete": 1,
    }
    assert updated_page.status_code == 200
    assert [item["project_id"] for item in updated_page.json()["items"]] == [
        "lifecycle-sort-complete",
        "lifecycle-sort-active",
        "lifecycle-sort-pending",
        "lifecycle-sort-blocked",
    ]
    assert waiting_human_page.status_code == 200
    assert waiting_human_page.json()["total"] == 1
    assert [item["project_id"] for item in waiting_human_page.json()["items"]] == [
        "lifecycle-sort-pending"
    ]
    assert waiting_human_page.json()["summary"] == priority_page.json()["summary"]
    assert exact_project_page.status_code == 200
    assert exact_project_page.headers["X-Total-Count"] == "1"
    assert exact_project_page.json()["summary"] == {
        "total": 1,
        "blocked": 0,
        "waiting_human": 0,
        "active": 1,
        "complete": 0,
    }
    assert [item["project_id"] for item in exact_project_page.json()["items"]] == [
        "lifecycle-sort-active"
    ]


async def test_local_demo_workspace_is_idempotent_tenant_scoped_and_navigable(
    tenant_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证本地演示初始化能生成四阶段闭环，并保持权限、租户和幂等边界。"""
    indexed_batches: list[list[str]] = []

    class SubmittedTask:
        """模拟 Celery 提交结果，使测试只聚焦数据库与 API 业务语义。"""

        id = "task-demo-index"

    def submit_index(evidence_ids: list[str]) -> SubmittedTask:
        """记录索引批次并返回固定任务标识。"""
        indexed_batches.append(evidence_ids)
        return SubmittedTask()

    monkeypatch.setattr(
        demo_workspace_route_module.index_evidence_batch,
        "delay",
        submit_index,
    )
    admin_headers = authorization("tenant-a-admin")
    viewer_headers = authorization("tenant-a-viewer")

    before_initialization = await tenant_client.get(
        "/api/v1/demo-workspace",
        headers=viewer_headers,
    )
    forbidden_initialization = await tenant_client.post(
        "/api/v1/demo-workspace",
        headers=authorization("tenant-a-planner"),
    )
    first = await tenant_client.post(
        "/api/v1/demo-workspace",
        headers=admin_headers,
    )
    second = await tenant_client.post(
        "/api/v1/demo-workspace",
        headers=admin_headers,
    )
    tenant_view = await tenant_client.get(
        "/api/v1/demo-workspace",
        headers=viewer_headers,
    )
    isolated_view = await tenant_client.get(
        "/api/v1/demo-workspace",
        headers=authorization("tenant-b-viewer"),
    )

    assert before_initialization.status_code == 200
    assert before_initialization.json() is None
    assert forbidden_initialization.status_code == 403
    assert first.status_code == 200
    assert second.status_code == 200
    assert tenant_view.status_code == 200
    assert isolated_view.status_code == 200
    assert isolated_view.json() is None

    first_payload = first.json()
    second_payload = second.json()
    view_payload = tenant_view.json()
    assert first_payload["created"] is True
    assert second_payload["created"] is False
    assert first_payload["evidence_count"] == 15
    assert first_payload["indexed_evidence_count"] == 0
    assert first_payload["failed_evidence_count"] == 0
    assert first_payload["index_status"] == "indexing"
    assert len(first_payload["projects"]) == 4
    assert first_payload["index_task_id"] == "task-demo-index"
    assert second_payload["index_task_id"] == "task-demo-index"
    assert [item["project_id"] for item in first_payload["projects"]] == [
        item["project_id"] for item in second_payload["projects"]
    ]
    assert view_payload["tenant_id"] == "tenant-a"
    assert view_payload["created"] is False
    assert view_payload["index_status"] == "indexing"
    assert len(indexed_batches) == 1
    assert all(len(batch) == 15 for batch in indexed_batches)

    projects_by_scenario = {
        item["scenario"]: item for item in first_payload["projects"]
    }
    assert set(projects_by_scenario) == {
        "planning_approval",
        "validation",
        "launch_review",
        "launched",
    }

    planning = projects_by_scenario["planning_approval"]
    validation = projects_by_scenario["validation"]
    launch_review = projects_by_scenario["launch_review"]
    launched = projects_by_scenario["launched"]
    approval_page = await tenant_client.get(
        "/api/v1/approval-tasks/page",
        params={"status": "pending", "task_id": planning["approval_task_id"]},
        headers=viewer_headers,
    )
    selection_page = await tenant_client.get(
        "/api/v1/selected-products/page",
        params={"selected_product_id": validation["selected_product_id"]},
        headers=viewer_headers,
    )
    initiative_page = await tenant_client.get(
        "/api/v1/product-initiatives/page",
        params={"initiative_id": launch_review["initiative_id"]},
        headers=viewer_headers,
    )
    launch_reviews = await tenant_client.get(
        "/api/v1/product-initiatives/launch-reviews",
        params={"status": "pending"},
        headers=viewer_headers,
    )
    lifecycles = await tenant_client.get(
        "/api/v1/analytics/project-lifecycles/page",
        params={"keyword": "演示｜", "sort": "priority", "page": 1, "page_size": 10},
        headers=viewer_headers,
    )

    assert approval_page.status_code == 200
    assert approval_page.json()["total"] == 1
    assert approval_page.json()["items"][0]["id"] == planning["approval_task_id"]
    assert selection_page.status_code == 200
    assert selection_page.json()["total"] == 1
    assert selection_page.json()["items"][0]["id"] == validation["selected_product_id"]
    assert selection_page.json()["items"][0]["validation_status"] != "ready"
    assert initiative_page.status_code == 200
    assert initiative_page.json()["total"] == 1
    assert initiative_page.json()["items"][0]["id"] == launch_review["initiative_id"]
    assert initiative_page.json()["items"][0]["status"] == "launch_ready"
    assert launch_reviews.status_code == 200
    assert launch_review["launch_review_id"] in {
        item["id"] for item in launch_reviews.json()
    }

    assert lifecycles.status_code == 200
    assert lifecycles.json()["total"] == 4
    lifecycle_by_project = {
        item["project_id"]: item for item in lifecycles.json()["items"]
    }
    assert lifecycle_by_project[planning["project_id"]]["stage"] == "approval"
    assert lifecycle_by_project[validation["project_id"]]["stage"] == "validation"
    assert lifecycle_by_project[launch_review["project_id"]]["stage"] == "launch_review"
    assert lifecycle_by_project[launched["project_id"]]["stage"] == "launched"
    assert lifecycle_by_project[launched["project_id"]]["health"] == "complete"

    dispatched_approvals: list[tuple[str, str, dict[str, object]]] = []

    def submit_approval_resume(
        run_id: str,
        thread_id: str,
        decision: dict[str, object],
    ) -> None:
        """记录审批恢复参数，随后由测试同步执行 Worker 主流程。"""
        dispatched_approvals.append((run_id, thread_id, decision))

    class UnavailableCheckpointStore:
        """模拟 Redis 检查点缺失且回写失败，验证 PostgreSQL 快照可独立恢复审批。"""

        async def load_latest(self, thread_id: str) -> None:
            """返回空检查点，模拟 Redis 数据已过期。"""
            del thread_id
            return None

        async def save(self, thread_id: str, state: dict[str, object]) -> str:
            """模拟 Redis 暂时不可写，核心业务仍应完成。"""
            del thread_id, state
            raise ConnectionError("redis unavailable")

    async def preserve_demo_narrative(
        outputs: dict[str, object],
        request: dict[str, object],
    ) -> dict[str, object]:
        """避免集成测试访问模型服务，只验证审批和选品落库。"""
        del request
        narrative = outputs.get("narrative")
        return narrative if isinstance(narrative, dict) else {"status": "ready"}

    monkeypatch.setattr(approvals_route_module.resume_planning_run, "delay", submit_approval_resume)
    monkeypatch.setattr(worker_tasks, "async_session_factory", app.state.integration_session_factory)
    monkeypatch.setattr(
        selection_registry_service,
        "async_session_factory",
        app.state.integration_session_factory,
    )
    monkeypatch.setattr(worker_tasks, "RedisCheckpointStore", UnavailableCheckpointStore)
    monkeypatch.setattr(worker_tasks, "generate_planning_narrative", preserve_demo_narrative)
    planning_task = approval_page.json()["items"][0]
    planning_candidates = planning_task["summary"]["outputs"]["concept"]["candidates"]
    selected_candidate_id = planning_candidates[0]["id"]
    approval_decision = await tenant_client.post(
        f"/api/v1/approval-tasks/{planning['approval_task_id']}/decision",
        headers={
            **authorization("tenant-a-approver"),
            "Idempotency-Key": "demo-approval-fallback-001",
        },
        json={
            "action": "approved",
            "comment": "演示审批通过，进入样品验证",
            "changes": {"selected_candidate_id": selected_candidate_id},
        },
    )
    assert approval_decision.status_code == 200
    assert approval_decision.json()["status"] == "approved"
    assert len(dispatched_approvals) == 1
    await worker_tasks._resume_planning_run(*dispatched_approvals[0])

    approved_selection_page = await tenant_client.get(
        "/api/v1/selected-products/page",
        params={"project_id": planning["project_id"], "page": 1, "page_size": 5},
        headers=viewer_headers,
    )
    advanced_lifecycle = await tenant_client.get(
        "/api/v1/analytics/project-lifecycles/page",
        params={"project_id": planning["project_id"], "page": 1, "page_size": 1},
        headers=viewer_headers,
    )
    assert approved_selection_page.status_code == 200
    assert approved_selection_page.json()["total"] == 1
    assert approved_selection_page.json()["items"][0]["candidate_id"] == selected_candidate_id
    assert approved_selection_page.json()["items"][0]["status"] == "selected"
    assert advanced_lifecycle.status_code == 200
    assert advanced_lifecycle.json()["items"][0]["stage"] == "validation"

    def fail_index(_evidence_ids: list[str]) -> None:
        """模拟消息队列提交失败，验证页面不会把未索引证据标记为已完成。"""
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(
        demo_workspace_route_module.index_evidence_batch,
        "delay",
        fail_index,
    )
    failed_dispatch = await tenant_client.post(
        "/api/v1/demo-workspace",
        headers=authorization("tenant-b-admin"),
    )
    failed_view = await tenant_client.get(
        "/api/v1/demo-workspace",
        headers=authorization("tenant-b-viewer"),
    )
    assert failed_dispatch.status_code == 200
    assert failed_dispatch.json()["index_status"] == "failed"
    assert failed_dispatch.json()["failed_evidence_count"] == 15
    assert "Milvus 索引任务暂未提交" in failed_dispatch.json()["message"]
    assert failed_view.json()["index_status"] == "failed"

    monkeypatch.setattr(
        demo_workspace_route_module.index_evidence_batch,
        "delay",
        submit_index,
    )
    retried_dispatch = await tenant_client.post(
        "/api/v1/demo-workspace",
        headers=authorization("tenant-b-admin"),
    )
    assert retried_dispatch.status_code == 200
    assert retried_dispatch.json()["created"] is False
    assert retried_dispatch.json()["index_status"] == "indexing"
    assert retried_dispatch.json()["failed_evidence_count"] == 0
