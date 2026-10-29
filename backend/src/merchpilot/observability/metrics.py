"""文件职责：定义 API、数据库、队列和模型服务共用的 Prometheus 指标。"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

http_requests_total = Counter(
    "merchpilot_http_requests_total",
    "HTTP 请求总数。",
    ("method", "path", "status"),
)
http_request_duration_seconds = Histogram(
    "merchpilot_http_request_duration_seconds",
    "HTTP 请求耗时。",
    ("method", "path"),
)
rate_limit_rejections_total = Counter(
    "merchpilot_rate_limit_rejections_total",
    "被 Redis 限流拒绝的请求数。",
    ("scope",),
)
db_query_duration_seconds = Histogram(
    "merchpilot_db_query_duration_seconds",
    "PostgreSQL 查询耗时。",
)
db_slow_queries_total = Counter(
    "merchpilot_db_slow_queries_total",
    "超过慢查询阈值的 PostgreSQL 查询数。",
)
celery_tasks_total = Counter(
    "merchpilot_celery_tasks_total",
    "Celery 任务执行次数。",
    ("task", "state"),
)
celery_task_duration_seconds = Histogram(
    "merchpilot_celery_task_duration_seconds",
    "Celery 任务执行耗时。",
    ("task",),
)
celery_queue_depth = Gauge(
    "merchpilot_celery_queue_depth",
    "Celery Redis 队列待处理任务数。",
    ("queue",),
    multiprocess_mode="mostrecent",
)
celery_workers = Gauge(
    "merchpilot_celery_workers",
    "当前可响应的 Celery Worker 数量。",
    multiprocess_mode="mostrecent",
)
model_requests_total = Counter(
    "merchpilot_model_requests_total",
    "模型服务请求结果。",
    ("service", "state"),
)
model_request_duration_seconds = Histogram(
    "merchpilot_model_request_duration_seconds",
    "模型服务请求耗时。",
    ("service",),
)
model_bulkhead_rejections_total = Counter(
    "merchpilot_model_bulkhead_rejections_total",
    "模型服务因舱壁并发上限被拒绝的请求数。",
    ("service",),
)
model_circuit_open_total = Counter(
    "merchpilot_model_circuit_open_total",
    "模型服务因熔断器打开而拒绝的请求数。",
    ("service",),
)
