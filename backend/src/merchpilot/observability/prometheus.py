"""文件职责：统一输出单进程和 Prometheus 多进程模式的指标。"""

from __future__ import annotations

import os
from typing import Any, cast

from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, CollectorRegistry, generate_latest, multiprocess


def render_metrics() -> tuple[bytes, str]:
    """根据运行模式生成 Prometheus 文本指标。"""
    if os.getenv("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        collector = cast(Any, multiprocess.MultiProcessCollector)
        collector(registry)
    else:
        registry = REGISTRY
    return generate_latest(registry), CONTENT_TYPE_LATEST
