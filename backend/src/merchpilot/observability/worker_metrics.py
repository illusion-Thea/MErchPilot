"""文件职责：为每个 Celery Worker 容器暴露多进程 Prometheus 指标。"""

from __future__ import annotations

import os
import time
from importlib import import_module
from pathlib import Path
from typing import Any, cast

from prometheus_client import CollectorRegistry, multiprocess, start_http_server


def main() -> None:
    """启动 Worker 指标 HTTP 服务并保持父进程存活。"""
    import_module("merchpilot.observability.metrics")
    metrics_dir = Path(os.environ["PROMETHEUS_MULTIPROC_DIR"])
    metrics_dir.mkdir(parents=True, exist_ok=True)
    registry = CollectorRegistry()
    collector = cast(Any, multiprocess.MultiProcessCollector)
    collector(registry)
    start_http_server(int(os.getenv("WORKER_METRICS_PORT", "9108")), registry=registry)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
