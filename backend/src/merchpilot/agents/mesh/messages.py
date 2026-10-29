"""文件职责：定义 Agent Mesh 节点之间传递的结构化消息契约。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from merchpilot.core.ids import new_id


class AgentMessage(BaseModel):
    """`AgentMessage` 封装本模块相关状态和行为，对调用方提供清晰边界。"""
    message_id: str = Field(default_factory=lambda: new_id("msg"))
    run_id: str
    sender: str
    recipient: str
    message_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    state_version: int = 1
    hop_count: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MeshEnvelope(BaseModel):
    """`MeshEnvelope` 封装本模块相关状态和行为，对调用方提供清晰边界。"""
    run_id: str
    request: dict[str, Any]
    messages: list[AgentMessage] = Field(default_factory=list)
