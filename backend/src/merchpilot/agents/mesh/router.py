"""文件职责：提供轻量 Agent 消息路由与跳数保护，避免循环调用。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from merchpilot.agents.mesh.messages import AgentMessage

AgentHandler = Callable[[AgentMessage], Awaitable[dict[str, Any]]]


class MeshRouter:
    """`MeshRouter` 封装本模块相关状态和行为，对调用方提供清晰边界。"""
    def __init__(self, max_hops: int = 12) -> None:
        """初始化`MeshRouter`所需依赖和默认状态。"""
        self.max_hops = max_hops
        self._handlers: dict[str, AgentHandler] = {}

    def register(self, agent_name: str, handler: AgentHandler) -> None:
        """实现Agent Mesh中的`register`节点或辅助流程，并合并结构化运行状态。"""
        if agent_name in self._handlers:
            raise ValueError(f"agent already registered: {agent_name}")
        self._handlers[agent_name] = handler

    async def dispatch(self, message: AgentMessage) -> dict[str, Any]:
        """实现Agent Mesh中的`dispatch`节点或辅助流程，并合并结构化运行状态。"""
        if message.hop_count >= self.max_hops:
            raise RuntimeError("agent mesh hop limit exceeded")
        handler = self._handlers.get(message.recipient)
        if handler is None:
            raise LookupError(f"agent is not registered: {message.recipient}")
        return await handler(message.model_copy(update={"hop_count": message.hop_count + 1}))
