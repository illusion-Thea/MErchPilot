"""文件职责：以结构化日志实现本地监控适配器，保留未来云监控接口。"""

from __future__ import annotations

from typing import Any

from merchpilot.core.logging import get_logger


class ConsoleTelemetryAdapter:
    """把监控事件写入结构化日志，作为本地开发阶段的监控实现。"""

    def __init__(self) -> None:
        """创建独立的 telemetry 日志记录器。"""

        self.logger = get_logger("telemetry")

    def emit_event(self, event_name: str, attributes: dict[str, Any]) -> None:
        """记录事件名称与属性，保持与未来云监控适配器相同的调用方式。"""

        self.logger.info(event_name, **attributes)
