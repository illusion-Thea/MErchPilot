"""文件职责：配置 Celery 应用、任务路由和 Redis Broker/结果后端。"""

from __future__ import annotations

from time import perf_counter

from celery import Celery
from celery.signals import task_postrun, task_prerun

from merchpilot.core.config import get_settings
from merchpilot.observability.metrics import celery_task_duration_seconds, celery_tasks_total

settings = get_settings()

celery_app = Celery(
    "merchpilot",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["merchpilot.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_routes={
        "merchpilot.execute_planning_run": {"queue": "planning.normal"},
        "merchpilot.resume_planning_run": {"queue": "agent.review"},
        "merchpilot.generate_embedding_index": {"queue": "index.embedding"},
        "merchpilot.process_tabular_import": {"queue": "index.parse"},
        "merchpilot.index_evidence_batch": {"queue": "index.embedding"},
        "merchpilot.generate_planning_report": {"queue": "report.generate"},
    },
)


@task_prerun.connect
def _task_started(task_id: str | None = None, task: object | None = None, **_: object) -> None:
    """记录任务起始时间，供任务耗时指标使用。"""
    if task is not None:
        task.__dict__["_merchpilot_started_at"] = perf_counter()


@task_postrun.connect
def _task_finished(
    task_id: str | None = None,
    task: object | None = None,
    task_name: str | None = None,
    state: str | None = None,
    **_: object,
) -> None:
    """记录任务完成状态和耗时。"""
    del task_id
    name = task_name or getattr(task, "name", "unknown")
    celery_tasks_total.labels(task=name, state=state or "UNKNOWN").inc()
    started_at = getattr(task, "_merchpilot_started_at", None)
    if isinstance(started_at, float):
        celery_task_duration_seconds.labels(task=name).observe(perf_counter() - started_at)
