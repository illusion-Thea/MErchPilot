"""文件职责：验证 audit 相关规则、边界与回归行为。"""

from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

import merchpilot.services.audit as audit_module
from merchpilot.infrastructure.models import AuditEvent
from merchpilot.services.audit import record_audit_event


class FakeSession:
    """提供`FakeSession`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
    def __init__(self) -> None:
        """辅助构造`init`测试数据或依赖，减少用例中的重复准备代码。"""
        self.added: list[AuditEvent] = []

    def add(self, event: AuditEvent) -> None:
        """辅助构造`add`测试数据或依赖，减少用例中的重复准备代码。"""
        self.added.append(event)


def test_record_audit_event_adds_authoritative_event() -> None:
    """验证“record audit event adds authoritative event”场景，确保业务规则、权限和异常边界保持稳定。"""
    session = FakeSession()

    event = record_audit_event(
        cast(AsyncSession, session),
        action="project.updated",
        entity_type="planning_project",
        entity_id="project-1",
        project_id="project-1",
        actor_id="local-user",
        detail={"changed_fields": ["constraints"]},
    )

    assert session.added == [event]
    assert event.id.startswith("audit_")
    assert event.action == "project.updated"
    assert event.detail == {"changed_fields": ["constraints"]}


def test_record_audit_event_emits_safe_telemetry_attributes(monkeypatch) -> None:
    """验证“record audit event emits safe telemetry attributes”场景，确保业务规则、权限和异常边界保持稳定。"""
    session = FakeSession()
    emitted: list[tuple[str, dict[str, Any]]] = []

    class FakeTelemetry:
        """提供`FakeTelemetry`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
        def emit_event(self, event_name: str, attributes: dict[str, Any]) -> None:
            """辅助构造`emit event`测试数据或依赖，减少用例中的重复准备代码。"""
            emitted.append((event_name, attributes))

    monkeypatch.setattr(audit_module, "get_telemetry_provider", lambda: FakeTelemetry())

    event = record_audit_event(
        cast(AsyncSession, session),
        action="approval.approved",
        entity_type="approval_task",
        entity_id="approval-1",
        project_id="project-1",
        tenant_id="tenant-1",
        actor_id="approver-1",
        detail={"comment": "通过", "changed_fields": ["status"]},
    )

    assert emitted == [
        (
            "approval.approved",
            {
                "audit_id": event.id,
                "tenant_id": "tenant-1",
                "actor_id": "approver-1",
                "entity_type": "approval_task",
                "entity_id": "approval-1",
                "project_id": "project-1",
                "detail_keys": ["changed_fields", "comment"],
            },
        )
    ]
    assert "comment" not in emitted[0][1]


def test_record_audit_event_is_not_blocked_by_telemetry_failure(monkeypatch) -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    session = FakeSession()

    class BrokenTelemetry:
        """提供`BrokenTelemetry`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
        def emit_event(self, event_name: str, attributes: dict[str, Any]) -> None:
            """辅助构造`emit event`测试数据或依赖，减少用例中的重复准备代码。"""
            del event_name, attributes
            raise RuntimeError("telemetry unavailable")

    monkeypatch.setattr(audit_module, "get_telemetry_provider", lambda: BrokenTelemetry())

    event = record_audit_event(
        cast(AsyncSession, session),
        action="project.created",
        entity_type="planning_project",
        entity_id="project-1",
    )

    assert session.added == [event]
