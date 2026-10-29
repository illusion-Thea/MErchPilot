"""文件职责：声明监控埋点端口，支持本地日志与未来云监控替换。"""

from __future__ import annotations

from typing import Any, Protocol


class TelemetryProvider(Protocol):
    """`TelemetryProvider` 声明可替换的企业能力契约，使业务层不依赖具体实现。"""

    def emit_event(self, event_name: str, attributes: dict[str, Any]) -> None:
        """发送结构化事件；调用方不依赖具体监控平台。"""
        ...
