"""文件职责：验证 worker state 相关规则、边界与回归行为。"""

from types import SimpleNamespace

import merchpilot.workers.tasks as worker_tasks
from merchpilot.api.routes.approvals import _decision_payload_hash
from merchpilot.api.schemas import ApprovalDecision
from merchpilot.infrastructure import events as run_events
from merchpilot.workers.tasks import (
    _apply_revision_changes,
    _apply_revision_validation_context,
    _merge_graph_update,
    _record_node_execution,
    _revision_run_resume_mode,
    _safe_publish_run_event,
)


def test_merge_graph_update_combines_parallel_outputs() -> None:
    """验证“merge graph update combines parallel outputs”场景，确保业务规则、权限和异常边界保持稳定。"""
    state = {
        "outputs": {"requirement": {"category": "水杯"}},
        "status": "researching",
    }

    _merge_graph_update(
        state,
        {
            "outputs": {"market": {"evidence_ids": ["evidence-1"]}},
            "status": "validating",
        },
    )

    assert state["outputs"] == {
        "requirement": {"category": "水杯"},
        "market": {"evidence_ids": ["evidence-1"]},
    }
    assert state["status"] == "validating"


async def test_record_node_execution_updates_persisted_snapshot(monkeypatch) -> None:
    """验证“record node execution updates persisted snapshot”场景，确保业务规则、权限和异常边界保持稳定。"""
    class FakeSession:
        """提供`FakeSession`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
        async def __aenter__(self):
            """辅助构造`aenter`测试数据或依赖，减少用例中的重复准备代码。"""
            return self

        async def __aexit__(self, *args):
            """辅助构造`aexit`测试数据或依赖，减少用例中的重复准备代码。"""
            return None

        async def scalar(self, query):
            """辅助构造`scalar`测试数据或依赖，减少用例中的重复准备代码。"""
            del query
            return type(
                "Run",
                (),
                {"execution_snapshot": {}, "result_snapshot": None},
            )()

        async def commit(self):
            """辅助构造`commit`测试数据或依赖，减少用例中的重复准备代码。"""
            return None

    monkeypatch.setattr(worker_tasks, "async_session_factory", lambda: FakeSession())

    snapshot = await _record_node_execution(
        "run_snapshot",
        "market_agent",
        "retrying",
        {"attempt": 1, "next_attempt": 2, "max_attempts": 3, "error": "timeout"},
    )

    assert snapshot["status"] == "retrying"
    assert snapshot["attempt"] == 1
    assert snapshot["error"] == "timeout"


async def test_safe_publish_run_event_does_not_fail_business_flow(monkeypatch) -> None:
    """验证“safe publish run event does not fail business flow”场景，确保业务规则、权限和异常边界保持稳定。"""
    async def failing_publish(*args, **kwargs) -> str:
        """辅助构造`failing publish`测试数据或依赖，减少用例中的重复准备代码。"""
        del args, kwargs
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(worker_tasks, "publish_run_event", failing_publish)

    await _safe_publish_run_event("run_test", "run.started", {"run_id": "run_test"})


def test_decode_run_event_handles_invalid_payload() -> None:
    """验证“decode run event handles invalid payload”场景，确保业务规则、权限和异常边界保持稳定。"""
    decoded = run_events.decode_run_event(
        "1740000000000-0",
        {
            "event_type": "agent.node.failed",
            "occurred_at": "2026-08-24T10:00:00+00:00",
            "payload": "not-json",
        },
    )

    assert decoded == {
        "event_id": "1740000000000-0",
        "event_type": "agent.node.failed",
        "occurred_at": "2026-08-24T10:00:00+00:00",
        "payload": {},
    }


async def test_list_run_events_returns_chronological_order(monkeypatch) -> None:
    """验证“list run events returns chronological order”场景，确保业务规则、权限和异常边界保持稳定。"""
    class FakeRedis:
        """提供`FakeRedis`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
        async def xrevrange(self, stream_name, *, max, min, count):
            """辅助构造`xrevrange`测试数据或依赖，减少用例中的重复准备代码。"""
            assert stream_name.endswith(":run:run_events:events")
            assert max == "+"
            assert min == "-"
            assert count == 2
            return [
                (
                    "1740000000002-0",
                    {
                        "event_type": "run.completed",
                        "occurred_at": "2026-08-24T10:00:02+00:00",
                        "payload": "{}",
                    },
                ),
                (
                    "1740000000001-0",
                    {
                        "event_type": "run.started",
                        "occurred_at": "2026-08-24T10:00:01+00:00",
                        "payload": "{}",
                    },
                ),
            ]

    monkeypatch.setattr(run_events, "get_redis", lambda: FakeRedis())

    result = await run_events.list_run_events("run_events", limit=2)

    assert [event["event_type"] for event in result] == ["run.started", "run.completed"]


async def test_async_task_runner_disposes_loop_bound_resources(monkeypatch) -> None:
    """验证“async task runner disposes loop bound resources”场景，确保业务规则、权限和异常边界保持稳定。"""
    calls: list[str] = []

    class FakeEngine:
        """提供`FakeEngine`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
        async def dispose(self) -> None:
            """辅助构造`dispose`测试数据或依赖，减少用例中的重复准备代码。"""
            calls.append("database")

    class FakeRedis:
        """提供`FakeRedis`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
        async def aclose(self) -> None:
            """辅助构造`aclose`测试数据或依赖，减少用例中的重复准备代码。"""
            calls.append("redis")

    class FakeCacheInfo:
        """提供`FakeCacheInfo`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
        currsize = 1

    class FakeRedisProvider:
        """提供`FakeRedisProvider`测试替身或场景容器，隔离外部依赖并记录调用结果。"""
        def __call__(self) -> FakeRedis:
            """辅助构造`call`测试数据或依赖，减少用例中的重复准备代码。"""
            return FakeRedis()

        def cache_info(self) -> FakeCacheInfo:
            """辅助构造`cache info`测试数据或依赖，减少用例中的重复准备代码。"""
            return FakeCacheInfo()

        def cache_clear(self) -> None:
            """辅助构造`cache clear`测试数据或依赖，减少用例中的重复准备代码。"""
            calls.append("cache")

    monkeypatch.setattr(worker_tasks, "database_engine", FakeEngine())
    monkeypatch.setattr(worker_tasks, "get_redis", FakeRedisProvider())

    async def operation() -> str:
        """辅助构造`operation`测试数据或依赖，减少用例中的重复准备代码。"""
        calls.append("operation")
        return "done"

    assert await worker_tasks._run_async_task(operation()) == "done"
    assert calls == ["operation", "database", "redis", "cache"]


def test_apply_revision_changes_merges_constraints_without_losing_existing_values() -> None:
    """
    验证“apply revision changes merges constraints without losing existing
    values”场景，确保业务规则、权限和异常边界保持稳定。
    """
    revised = _apply_revision_changes(
        {
            "name": "原项目",
            "category": "水杯",
            "target_market": "中国",
            "constraints": {"target_margin": 0.4, "unit_cost": 30},
        },
        {
            "action": "revision_required",
            "comment": "调整成本",
            "changes": {
                "target_market": "东南亚",
                "constraints": {"unit_cost": 28, "selling_price": 99},
            },
        },
    )

    assert revised["target_market"] == "东南亚"
    assert revised["constraints"] == {
        "target_margin": 0.4,
        "unit_cost": 28,
        "selling_price": 99,
    }
    assert revised["revision_context"]["comment"] == "调整成本"


def test_revision_validation_context_is_applied_to_new_concepts() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    result = {
        "outputs": {
            "concept": {
                "candidates": [
                    {
                        "id": "concept-1",
                        "name": "轻量通勤款",
                        "validation_plan": {
                            "status": "partial",
                            "gates": [
                                {
                                    "id": "specification",
                                    "status": "pending",
                                    "materials": [],
                                }
                            ],
                        },
                        "requires_validation": True,
                    }
                ]
            }
        }
    }

    _apply_revision_validation_context(
        result,
        {
            "revision_context": {
                "validation_context": {
                    "candidates": [
                        {
                            "candidate_id": "concept-1",
                            "candidate_name": "轻量通勤款",
                            "gates": [
                                {
                                    "gate_id": "specification",
                                    "status": "ready",
                                    "note": "样品测试通过",
                                    "materials": [
                                        {
                                            "id": "material-child",
                                            "filename": "样品测试.pdf",
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                }
            }
        },
    )

    candidate = result["outputs"]["concept"]["candidates"][0]
    gate = candidate["validation_plan"]["gates"][0]
    assert gate["status"] == "ready"
    assert gate["note"] == "样品测试通过"
    assert gate["materials"][0]["filename"] == "样品测试.pdf"


def test_approval_decision_hash_is_stable_for_equivalent_payloads() -> None:
    """验证该测试函数描述的业务场景。

    确保业务规则、权限与异常边界保持稳定。
    """
    first = ApprovalDecision(
        action="revision_required",
        comment="调整参数",
        changes={"constraints": {"target_margin": 0.4, "lead_time_days": 25}},
    )
    second = ApprovalDecision(
        action="revision_required",
        comment="调整参数",
        changes={"constraints": {"lead_time_days": 25, "target_margin": 0.4}},
    )

    assert _decision_payload_hash(first) == _decision_payload_hash(second)


def test_revision_run_resume_mode_recovers_created_queued_and_failed_children() -> None:
    """修订恢复重试必须继续执行已创建但尚未完成的子运行。"""
    created_child = type("Run", (), {"status": "queued"})()
    queued_child = type("Run", (), {"status": "queued"})()
    failed_child = type("Run", (), {"status": "failed"})()
    running_child = type("Run", (), {"status": "running"})()
    completed_child = type("Run", (), {"status": "completed"})()

    assert _revision_run_resume_mode(created_child, created=True) is False
    assert _revision_run_resume_mode(queued_child, created=False) is False
    assert _revision_run_resume_mode(failed_child, created=False) is True
    assert _revision_run_resume_mode(running_child, created=False) is None
    assert _revision_run_resume_mode(completed_child, created=False) is None


async def test_revision_resume_executes_existing_queued_child(monkeypatch) -> None:
    """任务重投时，已经落库但尚未启动的修订子运行必须继续执行。"""
    state = {
        "request": {
            "project_id": "project-1",
            "tenant_id": "tenant-1",
            "constraints": {"target_margin": 0.4},
        },
        "outputs": {},
    }
    child_run = SimpleNamespace(
        id="run-child",
        thread_id="thread-child",
        revision_no=2,
        status="queued",
        input_snapshot={"project_id": "project-1", "constraints": {"target_margin": 0.45}},
    )
    executed: list[tuple[str, str, dict, bool]] = []

    async def load_approval_state(*args, **kwargs):
        del args, kwargs
        return state

    async def load_run_state(*args, **kwargs):
        del args, kwargs
        return None, []

    async def save_checkpoint(*args, **kwargs):
        del args, kwargs
        return "checkpoint-parent"

    async def create_revision(*args, **kwargs):
        del args, kwargs
        return child_run, False

    async def publish_event(*args, **kwargs):
        del args, kwargs

    async def execute_child(run_id, thread_id, request, *, resume=False):
        executed.append((run_id, thread_id, request, resume))
        return {}

    monkeypatch.setattr(worker_tasks, "RedisCheckpointStore", lambda: object())
    monkeypatch.setattr(worker_tasks, "_load_approval_resume_state", load_approval_state)
    monkeypatch.setattr(worker_tasks, "_load_run_resume_state", load_run_state)
    monkeypatch.setattr(worker_tasks, "_save_approval_checkpoint", save_checkpoint)
    monkeypatch.setattr(worker_tasks, "_create_revision_run", create_revision)
    monkeypatch.setattr(worker_tasks, "_safe_publish_run_event", publish_event)
    monkeypatch.setattr(worker_tasks, "_execute_planning_run", execute_child)

    await worker_tasks._resume_planning_run(
        "run-parent",
        "thread-parent",
        {
            "action": "revision_required",
            "comment": "提高目标毛利率",
            "changes": {"constraints": {"target_margin": 0.45}},
        },
    )

    assert executed == [
        ("run-child", "thread-child", child_run.input_snapshot, False),
    ]
