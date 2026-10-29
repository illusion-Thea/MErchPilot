"""文件职责：配置结构化日志格式，统一服务运行与故障排查输出。"""

from __future__ import annotations

import logging
from typing import cast

import structlog


def configure_logging() -> None:
    """实现`configure_logging`流程；输入、输出和异常语义由类型标注及调用方约束。"""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """实现`get_logger`流程；输入、输出和异常语义由类型标注及调用方约束。"""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))
