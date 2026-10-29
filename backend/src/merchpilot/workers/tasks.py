"""文件职责：实现 Celery 长任务，串联数据导入、索引、Agent Mesh、报告与状态回写。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import select, update

from merchpilot.agents.mesh.graph import AgentNodeExecutionError, build_mesh_graph
from merchpilot.core.config import get_settings
from merchpilot.core.ids import new_id
from merchpilot.core.logging import get_logger
from merchpilot.domain.enums import EvidenceIndexStatus, ProjectStatus, RunStatus
from merchpilot.infrastructure.celery_app import celery_app
from merchpilot.infrastructure.checkpoints import RedisCheckpointStore
from merchpilot.infrastructure.database import async_session_factory
from merchpilot.infrastructure.database import engine as database_engine
from merchpilot.infrastructure.events import publish_run_event
from merchpilot.infrastructure.locks import DistributedLockBusy, DistributedLockUnavailable, distributed_lock
from merchpilot.infrastructure.model_clients import close_model_service_clients
from merchpilot.infrastructure.models import (
    ApprovalTask,
    DataImportJob,
    EvidenceRecord,
    PlanningProject,
    PlanningRun,
)
from merchpilot.infrastructure.redis import get_redis
from merchpilot.services.audit import record_audit_event
from merchpilot.services.concepts import (
    apply_candidate_selection,
    apply_candidate_validation_updates,
    resolve_candidate_concept,
)
from merchpilot.services.data_import import process_tabular_import_job
from merchpilot.services.evidence_indexing import index_evidence_records
from merchpilot.services.finance import calculate_candidate_financials
from merchpilot.services.llm_planning import generate_planning_narrative
from merchpilot.services.planning_metrics import collect_planning_metrics
from merchpilot.services.report_generation import generate_planning_report_job
from merchpilot.services.scoring import build_scorecard
from merchpilot.services.selection_registry import register_approved_selection
from merchpilot.services.validation_materials import (
    build_revision_validation_context,
    clone_revision_validation_materials,
)

logger = get_logger(__name__)


async def _with_run_lock[TaskResult](
    run_id: str,
    operation: Callable[[], Awaitable[TaskResult]],
) -> TaskResult:
    """可配置地串行化同一规划运行，防止重复 Celery 投递并发执行。"""
    settings = get_settings()
    if not settings.run_distributed_lock_enabled:
        return await operation()
    try:
        async with distributed_lock(
            f"{settings.redis_key_prefix}:lock:run:{run_id}",
            blocking_timeout=0.2,
        ):
            return await operation()
    except DistributedLockUnavailable:
        if settings.distributed_lock_fail_open:
            return await operation()
        raise


async def _run_async_task[TaskResult](awaitable: Awaitable[TaskResult]) -> TaskResult:
    """内部辅助函数`_run_async_task`；拆分主流程并集中处理当前模块的边界条件。"""
    try:
        return await awaitable
    finally:
        try:
            await close_model_service_clients()
        finally:
            try:
                await database_engine.dispose()
            finally:
                if get_redis.cache_info().currsize:
                    redis = get_redis()
                    try:
                        await redis.aclose()
                    finally:
                        get_redis.cache_clear()


async def _safe_publish_run_event(
    run_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """内部辅助函数`_safe_publish_run_event`；拆分主流程并集中处理当前模块的边界条件。"""
    try:
        await publish_run_event(run_id, event_type, payload)
    except Exception as exc:
        logger.warning(
            "run_event_publish_failed",
            run_id=run_id,
            event_type=event_type,
            error=str(exc),
        )


async def _set_run_status(
    run_id: str,
    status: RunStatus,
    *,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """内部辅助函数`_set_run_status`；拆分主流程并集中处理当前模块的边界条件。"""
    async with async_session_factory() as session:
        run = await session.scalar(select(PlanningRun).where(PlanningRun.id == run_id))
        if run is None:
            return
        previous_status = run.status
        run.status = status.value
        if status == RunStatus.RUNNING:
            run.started_at = datetime.now(UTC)
            run.completed_at = None
        if status in {
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.SUPERSEDED,
        }:
            run.completed_at = datetime.now(UTC)
        if result is not None:
            run.result_snapshot = result
        run.error_message = error
        project = await session.get(PlanningProject, run.project_id)
        if project is not None:
            if status == RunStatus.RUNNING:
                project.status = "running"
            elif status == RunStatus.APPROVAL_REQUIRED:
                project.status = "approval_required"
            elif status == RunStatus.COMPLETED:
                project.status = "completed"
            elif status == RunStatus.FAILED:
                project.status = "failed"
            elif status == RunStatus.CANCELLED:
                project.status = "cancelled"
        if previous_status != status.value:
            record_audit_event(
                session,
                action=f"run.{status.value}",
                entity_type="planning_run",
                entity_id=run.id,
                project_id=run.project_id,
                tenant_id=project.tenant_id if project is not None else "default",
                actor_id="system",
                detail={
                    "previous_status": previous_status,
                    "status": status.value,
                    **({"error": error} if error else {}),
                },
            )
        await session.commit()


async def _set_import_index_task_id(import_id: str, task_id: str) -> None:
    """内部辅助函数`_set_import_index_task_id`；拆分主流程并集中处理当前模块的边界条件。"""
    async with async_session_factory() as session:
        job = await session.get(DataImportJob, import_id)
        if job is None:
            return
        job.index_celery_task_id = task_id
        await session.commit()


async def _mark_import_index_dispatch_failed(import_id: str, error: str) -> None:
    """内部辅助函数`_mark_import_index_dispatch_failed`；拆分主流程并集中处理当前模块的边界条件。"""
    async with async_session_factory() as session:
        job = await session.get(DataImportJob, import_id)
        if job is None:
            return
        await session.execute(
            update(EvidenceRecord)
            .where(
                EvidenceRecord.import_job_id == import_id,
                EvidenceRecord.index_status.in_(
                    [EvidenceIndexStatus.PENDING.value, EvidenceIndexStatus.INDEXING.value]
                ),
            )
            .values(index_status=EvidenceIndexStatus.FAILED.value)
        )
        job.error_message = f"解析已完成，但 Milvus 索引任务提交失败: {error}"
        record_audit_event(
            session,
            action="import.index_dispatch_failed",
            entity_type="data_import",
            entity_id=job.id,
            tenant_id=job.tenant_id,
            actor_id="system",
            detail={"error": error},
        )
        await session.commit()


async def _record_node_execution(
    run_id: str,
    node_name: str,
    event: str,
    payload: dict[str, Any],
    *,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """内部辅助函数`_record_node_execution`；拆分主流程并集中处理当前模块的边界条件。"""
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        run = await session.scalar(
            select(PlanningRun).where(PlanningRun.id == run_id).with_for_update()
        )
        if run is None:
            return dict(payload)
        execution = dict(run.execution_snapshot or {})
        nodes = dict(execution.get("nodes") or {})
        node = dict(nodes.get(node_name) or {})
        node.update(
            {
                "node": node_name,
                "status": (
                    "running"
                    if event == "started"
                    else "completed"
                    if event == "skipped"
                    else event
                ),
                "updated_at": now.isoformat(),
            }
        )
        if event == "started":
            node["started_at"] = now.isoformat()
            node["error"] = None
            node["reused"] = False
        elif event == "skipped":
            node["reused"] = True
            node["completed_at"] = now.isoformat()
            node["error"] = None
        elif event == "completed":
            node["completed_at"] = now.isoformat()
            node["error"] = None
        node.update(payload)
        nodes[node_name] = node
        execution["nodes"] = nodes
        execution["updated_at"] = now.isoformat()
        run.execution_snapshot = execution
        if result is not None:
            run.result_snapshot = result
        await session.commit()
        return node


async def _publish_node_event(
    run_id: str,
    node_name: str,
    event: str,
    payload: dict[str, Any],
) -> None:
    """内部辅助函数`_publish_node_event`；拆分主流程并集中处理当前模块的边界条件。"""
    try:
        node = await _record_node_execution(run_id, node_name, event, payload)
    except Exception as exc:
        logger.warning(
            "node_execution_snapshot_update_failed",
            run_id=run_id,
            node=node_name,
            node_event=event,
            error=str(exc),
        )
        node = dict(payload)
    await _safe_publish_run_event(
        run_id,
        f"agent.node.{event}",
        {"run_id": run_id, "node": node_name, **node},
    )


async def _load_run_resume_state(
    run_id: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    """内部辅助函数`_load_run_resume_state`；拆分主流程并集中处理当前模块的边界条件。"""
    async with async_session_factory() as session:
        run = await session.get(PlanningRun, run_id)
        if run is None:
            return None, []
        execution = run.execution_snapshot or {}
        nodes = execution.get("nodes")
        completed_nodes = (
            [
                node_name
                for node_name, detail in nodes.items()
                if isinstance(detail, dict) and detail.get("status") == "completed"
            ]
            if isinstance(nodes, dict)
            else []
        )
        return run.result_snapshot, completed_nodes


async def _load_approval_resume_state(
    run_id: str,
    thread_id: str,
    checkpoint_store: RedisCheckpointStore,
) -> dict[str, Any]:
    """优先读取 Redis 检查点，并在缓存缺失或不可用时回退 PostgreSQL 运行快照。"""
    try:
        checkpoint = await checkpoint_store.load_latest(thread_id)
    except Exception as exc:
        logger.warning(
            "approval_checkpoint_load_failed",
            run_id=run_id,
            thread_id=thread_id,
            error=str(exc),
        )
        checkpoint = None
    if isinstance(checkpoint, dict):
        checkpoint_state = checkpoint.get("state")
        if isinstance(checkpoint_state, dict):
            return dict(checkpoint_state)

    async with async_session_factory() as session:
        run = await session.get(PlanningRun, run_id)
        if run is None:
            raise RuntimeError("planning run not found")
        if not isinstance(run.result_snapshot, dict) or not run.result_snapshot:
            raise RuntimeError("planning checkpoint and persisted result snapshot are unavailable")
        state = dict(run.result_snapshot)
        if not isinstance(state.get("request"), dict) or not state.get("request"):
            state["request"] = dict(run.input_snapshot or {})
        state.setdefault("run_id", run.id)
        state.setdefault("outputs", {})
        state.setdefault("metrics", {})
        logger.warning(
            "approval_checkpoint_fallback_to_database",
            run_id=run_id,
            thread_id=thread_id,
        )
        return state


async def _save_approval_checkpoint(
    checkpoint_store: RedisCheckpointStore,
    thread_id: str,
    state: dict[str, Any],
    *,
    run_id: str,
) -> str | None:
    """尽力回写审批检查点，Redis 故障时不阻断已由 PostgreSQL 承载的核心业务状态。"""
    try:
        return await checkpoint_store.save(thread_id, state)
    except Exception as exc:
        logger.warning(
            "approval_checkpoint_save_failed",
            run_id=run_id,
            thread_id=thread_id,
            error=str(exc),
        )
        return None


def _merge_graph_update(state: dict[str, Any], update: dict[str, Any]) -> None:
    """内部辅助函数`_merge_graph_update`；拆分主流程并集中处理当前模块的边界条件。"""
    outputs = update.get("outputs")
    if isinstance(outputs, dict):
        current_outputs = state.setdefault("outputs", {})
        if isinstance(current_outputs, dict):
            current_outputs.update(outputs)
    for key, value in update.items():
        if key != "outputs":
            state[key] = value


def _agent_trace(node_update: dict[str, Any]) -> dict[str, Any]:
    """从节点产出提取轻量追踪信息，避免把完整模型结果重复写入事件。"""
    outputs = node_update.get("outputs")
    if not isinstance(outputs, dict):
        return {}
    trace: dict[str, Any] = {}
    for output_key, output_value in outputs.items():
        if not isinstance(output_value, dict):
            continue
        generation = output_value.get("generation")
        if isinstance(generation, dict):
            trace[output_key] = {
                "status": generation.get("status"),
                "provider": generation.get("provider"),
                "model": generation.get("model"),
                "prompt_version": generation.get("prompt_version"),
                "reason": generation.get("reason"),
            }
        evidence_audit = output_value.get("evidence_audit")
        if isinstance(evidence_audit, dict):
            trace.setdefault(output_key, {})["evidence_audit"] = {
                "invalid_reference_count": evidence_audit.get("invalid_reference_count", 0),
                "invalid_evidence_by_candidate": evidence_audit.get(
                    "invalid_evidence_by_candidate", {}
                ),
            }
    return trace


def _apply_revision_changes(
    request: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    """内部辅助函数`_apply_revision_changes`；拆分主流程并集中处理当前模块的边界条件。"""
    revised_request = dict(request)
    changes = decision.get("changes")
    if isinstance(changes, dict):
        revised_constraints = dict(revised_request.get("constraints") or {})
        constraint_changes = changes.get("constraints")
        if isinstance(constraint_changes, dict):
            revised_constraints.update(constraint_changes)
        revised_request["constraints"] = revised_constraints
        for key in ("name", "category", "target_market"):
            if changes.get(key):
                revised_request[key] = changes[key]
    revised_request["revision_context"] = {
        "comment": decision.get("comment", ""),
        "requested_at": datetime.now(UTC).isoformat(),
    }
    if isinstance(changes, dict) and changes.get("selected_candidate_id"):
        revised_request["revision_context"]["selected_candidate_id"] = str(
            changes["selected_candidate_id"]
        )
    return revised_request


def _apply_revision_validation_context(
    result: dict[str, Any],
    request: dict[str, Any],
) -> None:
    """内部辅助函数`_apply_revision_validation_context`；拆分主流程并集中处理当前模块的边界条件。"""
    revision_context = request.get("revision_context")
    if not isinstance(revision_context, dict):
        return
    validation_context = revision_context.get("validation_context")
    if not isinstance(validation_context, dict):
        return
    inherited_candidates = validation_context.get("candidates")
    if not isinstance(inherited_candidates, list):
        return

    outputs = result.get("outputs")
    if not isinstance(outputs, dict):
        return
    concept = outputs.get("concept")
    if not isinstance(concept, dict):
        return
    candidates = concept.get("candidates")
    if not isinstance(candidates, list):
        return

    now = datetime.now(UTC).isoformat()
    for inherited_entry in inherited_candidates:
        if not isinstance(inherited_entry, dict):
            continue
        candidate_id = str(inherited_entry.get("candidate_id") or "").strip()
        candidate_name = str(inherited_entry.get("candidate_name") or "").strip()
        candidate = next(
            (
                item
                for item in candidates
                if isinstance(item, dict)
                and (
                    str(item.get("id") or "").strip() == candidate_id
                    or (
                        candidate_name
                        and str(item.get("name") or "").strip() == candidate_name
                    )
                )
            ),
            None,
        )
        if candidate is None:
            continue
        validation_plan = candidate.get("validation_plan")
        if not isinstance(validation_plan, dict):
            continue
        inherited_gates = inherited_entry.get("gates")
        if not isinstance(inherited_gates, list):
            continue

        gate_materials = {
            str(gate.get("gate_id") or "").strip(): gate.get("materials")
            for gate in inherited_gates
            if isinstance(gate, dict) and str(gate.get("gate_id") or "").strip()
        }
        inherited_plan = dict(validation_plan)
        inherited_plan["gates"] = [
            dict(gate)
            for gate in validation_plan.get("gates", [])
            if isinstance(gate, dict)
        ]
        for gate in inherited_plan["gates"]:
            gate_id = str(gate.get("id") or "").strip()
            materials = gate_materials.get(gate_id)
            if isinstance(materials, list):
                gate["materials"] = [
                    dict(material)
                    for material in materials
                    if isinstance(material, dict)
                ]

        updates = [
            {
                "gate_id": str(gate.get("gate_id") or "").strip(),
                "status": gate.get("status"),
                "note": gate.get("note") or "",
            }
            for gate in inherited_gates
            if isinstance(gate, dict) and str(gate.get("gate_id") or "").strip()
        ]
        candidate["validation_plan"] = apply_candidate_validation_updates(
            inherited_plan,
            updates,
            actor_id="revision_inherited",
            updated_at=now,
        )
        candidate["requires_validation"] = candidate["validation_plan"][
            "requires_validation"
        ]


def _apply_approval_selection(state: dict[str, Any], decision: dict[str, Any]) -> bool:
    """内部辅助函数`_apply_approval_selection`；拆分主流程并集中处理当前模块的边界条件。"""
    changes = decision.get("changes")
    if not isinstance(changes, dict):
        return False
    candidate_id = changes.get("selected_candidate_id")
    if not candidate_id:
        return False
    outputs = state.setdefault("outputs", {})
    if not isinstance(outputs, dict):
        return False
    concept = outputs.get("concept")
    if not isinstance(concept, dict):
        return False
    selected_candidate = resolve_candidate_concept(concept, candidate_id)
    if selected_candidate is None:
        raise RuntimeError("selected candidate concept not found in planning result")
    selection_status = "approved" if decision.get("action") == "approved" else "revision_requested"
    outputs["concept"] = apply_candidate_selection(concept, candidate_id, selection_status)
    request = state.get("request")
    request = request if isinstance(request, dict) else {}
    constraints = request.get("constraints")
    constraints = constraints if isinstance(constraints, dict) else {}
    metrics = state.get("metrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    selected_finance = calculate_candidate_financials(selected_candidate, constraints, metrics)
    outputs["finance"] = selected_finance
    outputs["selected_candidate_finance"] = selected_finance
    supplier = outputs.get("supplier")
    supplier = supplier if isinstance(supplier, dict) else {}
    evidence_ids = outputs["concept"].get("evidence_ids", [])
    evidence_ids = evidence_ids if isinstance(evidence_ids, list) else []
    outputs["scorecard"] = build_scorecard(
        [str(item) for item in evidence_ids if item],
        selected_finance,
        supplier,
        constraints,
        metrics,
    )
    return True


async def _create_revision_run(
    parent_run_id: str,
    revised_request: dict[str, Any],
    decision: dict[str, Any],
    result: dict[str, Any],
) -> tuple[PlanningRun, bool]:
    """内部辅助函数`_create_revision_run`；拆分主流程并集中处理当前模块的边界条件。"""
    async with async_session_factory() as session:
        parent = await session.scalar(
            select(PlanningRun).where(PlanningRun.id == parent_run_id).with_for_update()
        )
        if parent is None:
            raise RuntimeError("planning run not found")
        existing_child = await session.scalar(
            select(PlanningRun)
            .where(PlanningRun.parent_run_id == parent.id)
            .order_by(PlanningRun.revision_no.desc())
            .limit(1)
        )
        if existing_child is not None:
            return existing_child, False

        project = await session.get(PlanningProject, parent.project_id)
        if project is None:
            raise RuntimeError("planning project not found")
        revision_no = parent.revision_no + 1
        child_request = dict(revised_request)
        child_id = new_id("run")
        validation_context = build_revision_validation_context(result)
        revision_context = dict(child_request.get("revision_context") or {})
        revision_context.update(
            {
                "parent_run_id": parent.id,
                "revision_no": revision_no,
                "comment": decision.get("comment", ""),
            }
        )
        if validation_context.get("candidates"):
            revision_context["validation_context"] = (
                await clone_revision_validation_materials(
                    validation_context,
                    project_id=parent.project_id,
                    parent_run_id=parent.id,
                    child_run_id=child_id,
                )
            )
        child_request["revision_context"] = revision_context
        project.name = str(child_request.get("name") or project.name)
        project.category = str(child_request.get("category") or project.category)
        project.target_market = str(child_request.get("target_market") or project.target_market)
        constraints = child_request.get("constraints")
        if isinstance(constraints, dict):
            project.constraints = constraints
        child = PlanningRun(
            id=child_id,
            project_id=parent.project_id,
            parent_run_id=parent.id,
            revision_no=revision_no,
            thread_id=new_id("thread"),
            status=RunStatus.QUEUED.value,
            input_snapshot=child_request,
        )
        session.add(child)
        parent.status = RunStatus.SUPERSEDED.value
        parent.completed_at = datetime.now(UTC)
        parent.result_snapshot = result
        project.status = ProjectStatus.RUNNING.value
        record_audit_event(
            session,
            action="run.superseded",
            entity_type="planning_run",
            entity_id=parent.id,
            project_id=parent.project_id,
            tenant_id=project.tenant_id,
            actor_id="system",
            detail={
                "child_run_id": child.id,
                "revision_no": revision_no,
                "comment": decision.get("comment", ""),
            },
        )
        record_audit_event(
            session,
            action="run.queued",
            entity_type="planning_run",
            entity_id=child.id,
            project_id=child.project_id,
            tenant_id=project.tenant_id,
            actor_id="system",
            detail={"parent_run_id": parent.id, "revision_no": revision_no},
        )
        await session.commit()
        await session.refresh(child)
        return child, True


def _revision_run_resume_mode(child_run: PlanningRun, *, created: bool) -> bool | None:
    """判断修订子运行是否需要执行，并返回是否按失败续跑模式恢复。"""
    if created or child_run.status == RunStatus.QUEUED.value:
        return False
    if child_run.status == RunStatus.FAILED.value:
        return True
    return None


async def _execute_planning_run(
    run_id: str,
    thread_id: str,
    request: dict[str, Any],
    *,
    resume: bool = False,
) -> dict[str, Any]:
    """执行完整Agent Mesh，并持续回写节点事件、检查点、产出和最终状态。"""
    checkpoint_store = RedisCheckpointStore()
    # 恢复模式读取最近快照与已完成节点，只重跑失败点及其后续节点。
    stored_result, completed_nodes = await _load_run_resume_state(run_id) if resume else (None, [])
    stored_outputs = stored_result.get("outputs") if isinstance(stored_result, dict) else None
    stored_metrics = stored_result.get("metrics") if isinstance(stored_result, dict) else None
    if isinstance(stored_metrics, dict):
        planning_metrics = stored_metrics
    else:
        async with async_session_factory() as session:
            planning_metrics = await collect_planning_metrics(
                session,
                tenant_id=str(request.get("tenant_id") or "default"),
                category=str(request.get("category") or "") or None,
                target_market=str(request.get("target_market") or "") or None,
            )
    initial_outputs = dict(stored_outputs) if isinstance(stored_outputs, dict) else {}
    initial_state: dict[str, Any] = {
        "run_id": run_id,
        "request": request,
        "outputs": initial_outputs,
        "status": (
            str(stored_result.get("status") or "running")
            if isinstance(stored_result, dict)
            else "running"
        ),
        "approval_required": (
            bool(stored_result.get("approval_required"))
            if isinstance(stored_result, dict)
            else False
        ),
        "resume_completed_nodes": completed_nodes,
        "metrics": planning_metrics,
    }
    result = cast(dict[str, Any], {**initial_state, "outputs": dict(initial_outputs)})
    try:
        await _set_run_status(run_id, RunStatus.RUNNING)
        await _safe_publish_run_event(
            run_id,
            "run.resumed" if resume else "run.started",
            {"run_id": run_id, "reused_nodes": completed_nodes},
        )
        await checkpoint_store.save(thread_id, initial_state)

        async def handle_node_event(
            node_name: str,
            event: str,
            payload: dict[str, Any],
        ) -> None:
            """执行`handle_node_event`异步任务步骤，并把进度、结果或失败状态持久化。"""
            await _publish_node_event(run_id, node_name, event, payload)

        settings = get_settings()
        graph = build_mesh_graph(
            event_handler=handle_node_event,
            max_attempts=settings.agent_node_max_attempts,
            retry_base_seconds=settings.agent_node_retry_base_seconds,
        )
        # 使用流式更新逐节点持久化产出，浏览器刷新或 Worker 重启后仍能从最近状态继续。
        async for graph_update in graph.astream(initial_state, stream_mode="updates"):
            if not isinstance(graph_update, dict):
                continue
            for node_name, node_update in graph_update.items():
                if not isinstance(node_update, dict):
                    continue
                _merge_graph_update(result, node_update)
                node_outputs = node_update.get("outputs")
                output_keys = list(node_outputs) if isinstance(node_outputs, dict) else []
                trace = _agent_trace(node_update)
                node_detail = await _record_node_execution(
                    run_id,
                    node_name,
                    "completed",
                    {"output_keys": output_keys, "trace": trace},
                    result=result,
                )
                await checkpoint_store.save(thread_id, result)
                await _safe_publish_run_event(
                    run_id,
                    "agent.node.completed",
                    {
                        "run_id": run_id,
                        "node": node_name,
                        "status": result.get("status"),
                        "output_keys": output_keys,
                        "attempt": node_detail.get("attempt"),
                        "max_attempts": node_detail.get("max_attempts"),
                        "reused": bool(node_detail.get("reused")),
                        "trace": trace,
                    },
                )
        _apply_revision_validation_context(result, request)
        checkpoint_ref = await checkpoint_store.save(thread_id, result)
        final_status = RunStatus.APPROVAL_REQUIRED if result["approval_required"] else RunStatus.COMPLETED
        await _set_run_status(run_id, final_status, result=result)
        approval_task_id = None
        # 自动分析完成只创建人工审批任务；最终选品不会在 Worker 中被自动批准。
        if result["approval_required"]:
            async with async_session_factory() as session:
                existing = await session.scalar(
                    select(ApprovalTask).where(
                        ApprovalTask.run_id == run_id,
                        ApprovalTask.status == "pending",
                    )
                )
                if existing is None:
                    existing = ApprovalTask(
                        id=new_id("approval"),
                        project_id=request["project_id"],
                        run_id=run_id,
                        approval_type="business",
                        checkpoint_ref=checkpoint_ref,
                        summary={
                            "title": "商品规划方案待业务审核",
                            "run_id": run_id,
                            "project_name": request.get("name"),
                            "category": request.get("category"),
                            "target_market": request.get("target_market"),
                            "outputs": result.get("outputs", {}),
                        },
                    )
                    session.add(existing)
                    await session.flush()
                    await session.refresh(existing, attribute_names=["created_at"])
                    existing.due_at = existing.created_at + timedelta(
                        hours=settings.approval_sla_hours
                    )
                    record_audit_event(
                        session,
                        action="approval.created",
                        entity_type="approval_task",
                        entity_id=existing.id,
                        project_id=request["project_id"],
                        tenant_id=str(request.get("tenant_id") or "default"),
                        actor_id="system",
                        detail={"run_id": run_id, "approval_type": existing.approval_type},
                    )
                    await session.commit()
                elif existing.due_at is None:
                    existing.due_at = existing.created_at + timedelta(
                        hours=settings.approval_sla_hours
                    )
                    await session.commit()
                approval_task_id = existing.id
        await _safe_publish_run_event(
            run_id,
            "approval.required" if result["approval_required"] else "run.completed",
            {
                "run_id": run_id,
                "checkpoint_ref": checkpoint_ref,
                "approval_task_id": approval_task_id,
                "status": final_status.value,
            },
        )
        return result
    except Exception as exc:
        failed_node = exc.node_name if isinstance(exc, AgentNodeExecutionError) else None
        try:
            await _set_run_status(run_id, RunStatus.FAILED, result=result, error=str(exc))
        except Exception as status_exc:
            logger.exception(
                "planning_run_failure_status_update_failed",
                run_id=run_id,
                error=str(status_exc),
            )
        await _safe_publish_run_event(
            run_id,
            "run.failed",
            {"run_id": run_id, "error": str(exc), "failed_node": failed_node},
        )
        raise


async def _resume_planning_run(run_id: str, thread_id: str, decision: dict[str, Any]) -> None:
    """内部辅助函数`_resume_planning_run`；拆分主流程并集中处理当前模块的边界条件。"""
    state: dict[str, Any] | None = None
    revision_child_id: str | None = None
    try:
        checkpoint_store = RedisCheckpointStore()
        state = await _load_approval_resume_state(run_id, thread_id, checkpoint_store)
        latest_result, _ = await _load_run_resume_state(run_id)
        if isinstance(latest_result, dict):
            latest_outputs = latest_result.get("outputs")
            if isinstance(latest_outputs, dict):
                latest_concept = latest_outputs.get("concept")
                if isinstance(latest_concept, dict):
                    state_outputs = state.setdefault("outputs", {})
                    if isinstance(state_outputs, dict):
                        state_outputs["concept"] = latest_concept
        state["approval_required"] = False
        state["status"] = "completed" if decision["action"] == "approved" else decision["action"]
        selection_applied = _apply_approval_selection(state, decision)
        state.setdefault("outputs", {})["approval"] = decision
        if selection_applied and decision["action"] == "approved":
            state["outputs"]["narrative"] = await generate_planning_narrative(
                state["outputs"],
                state.get("request", {}),
            )
        if decision["action"] == "revision_required":
            revised_request = _apply_revision_changes(dict(state.get("request") or {}), decision)
            state["request"] = revised_request
            await _save_approval_checkpoint(
                checkpoint_store,
                thread_id,
                state,
                run_id=run_id,
            )
            child_run, created = await _create_revision_run(
                run_id,
                revised_request,
                decision,
                state,
            )
            revision_child_id = child_run.id
            await _safe_publish_run_event(
                run_id,
                "run.revision_created",
                {
                    "run_id": run_id,
                    "child_run_id": child_run.id,
                    "revision_no": child_run.revision_no,
                    "decision": decision,
                },
            )
            resume_child = _revision_run_resume_mode(child_run, created=created)
            if resume_child is not None:
                await _execute_planning_run(
                    child_run.id,
                    child_run.thread_id,
                    child_run.input_snapshot,
                    resume=resume_child,
                )
            return
        selected_product = None
        if decision["action"] == "approved":
            selected_product = await register_approved_selection(run_id, state)
        await _save_approval_checkpoint(
            checkpoint_store,
            thread_id,
            state,
            run_id=run_id,
        )
        final_status = (
            RunStatus.COMPLETED if decision["action"] == "approved" else RunStatus.CANCELLED
        )
        await _set_run_status(run_id, final_status, result=state)
        await _safe_publish_run_event(
            run_id,
            "approval.completed",
            {
                "run_id": run_id,
                "action": decision["action"],
                "status": final_status.value,
                "selected_product_id": selected_product.id if selected_product is not None else None,
            },
        )
    except Exception as exc:
        target_run_id = revision_child_id or run_id
        await _set_run_status(target_run_id, RunStatus.FAILED, result=state, error=str(exc))
        await _safe_publish_run_event(
            target_run_id,
            "run.failed",
            {"run_id": target_run_id, "error": str(exc), "phase": "approval_resume"},
        )
        raise


@celery_app.task(
    name="merchpilot.execute_planning_run",
    bind=True,
    autoretry_for=(ConnectionError, TimeoutError, DistributedLockBusy),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
)
def execute_planning_run(
    self: Any,
    run_id: str,
    thread_id: str,
    request: dict[str, Any],
    resume: bool = False,
) -> dict[str, Any]:
    """执行`execute_planning_run`异步任务步骤，并把进度、结果或失败状态持久化。"""
    del self
    return asyncio.run(
        _run_async_task(
            _with_run_lock(
                run_id,
                lambda: _execute_planning_run(run_id, thread_id, request, resume=resume),
            )
        )
    )


@celery_app.task(
    name="merchpilot.resume_planning_run",
    bind=True,
    autoretry_for=(ConnectionError, TimeoutError, DistributedLockBusy),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def resume_planning_run(
    self: Any,
    run_id: str,
    thread_id: str,
    decision: dict[str, Any],
) -> None:
    """执行`resume_planning_run`异步任务步骤，并把进度、结果或失败状态持久化。"""
    del self
    asyncio.run(
        _run_async_task(
            _with_run_lock(run_id, lambda: _resume_planning_run(run_id, thread_id, decision))
        )
    )


@celery_app.task(name="merchpilot.generate_embedding_index")
def generate_embedding_index(evidence_id: str) -> dict[str, Any]:
    """执行`generate_embedding_index`异步任务步骤，并把进度、结果或失败状态持久化。"""
    return asyncio.run(_run_async_task(index_evidence_records([evidence_id])))


@celery_app.task(name="merchpilot.process_tabular_import")
def process_tabular_import(import_id: str) -> dict[str, Any]:
    """执行`process_tabular_import`异步任务步骤，并把进度、结果或失败状态持久化。"""
    result = asyncio.run(_run_async_task(process_tabular_import_job(import_id)))
    evidence_ids = result.get("evidence_ids", [])
    if evidence_ids:
        try:
            task = index_evidence_batch.delay(evidence_ids)
        except Exception as exc:
            asyncio.run(_run_async_task(_mark_import_index_dispatch_failed(import_id, str(exc))))
            raise
        result["index_task_id"] = task.id
        asyncio.run(_run_async_task(_set_import_index_task_id(import_id, task.id)))
    return result


@celery_app.task(
    name="merchpilot.index_evidence_batch",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 5},
)
def index_evidence_batch(self: Any, evidence_ids: list[str]) -> dict[str, Any]:
    """执行`index_evidence_batch`异步任务步骤，并把进度、结果或失败状态持久化。"""
    del self
    return asyncio.run(_run_async_task(index_evidence_records(evidence_ids)))


@celery_app.task(name="merchpilot.generate_planning_report")
def generate_planning_report(report_id: str) -> dict[str, Any]:
    """执行`generate_planning_report`异步任务步骤，并把进度、结果或失败状态持久化。"""
    return asyncio.run(_run_async_task(generate_planning_report_job(report_id)))
