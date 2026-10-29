"""文件职责：封装大模型调用入口，并提供本地可解释降级结果。"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from merchpilot.core.config import get_settings
from merchpilot.observability.resilience import ModelServiceGuard

llm_guard = ModelServiceGuard("llm")


@lru_cache(maxsize=2)
def get_chat_model(streaming: bool = False) -> Any:
    """实现`get_chat_model`流程；输入、输出和异常语义由类型标注及调用方约束。"""
    settings = get_settings()
    if not settings.llm_api_key:
        raise RuntimeError("DASHSCOPE_API_KEY is not configured")
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=SecretStr(settings.llm_api_key),
        base_url=settings.llm_base_url,
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout_seconds,
        streaming=streaming,
    )


@lru_cache(maxsize=2)
def get_multimodal_model(streaming: bool = False) -> Any:
    """返回支持图片输入的 Qwen-VL 兼容模型。"""
    settings = get_settings()
    if not settings.llm_api_key:
        raise RuntimeError("DASHSCOPE_API_KEY is not configured")
    return ChatOpenAI(
        model=settings.llm_multimodal_model,
        api_key=SecretStr(settings.llm_api_key),
        base_url=settings.llm_base_url,
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout_seconds,
        streaming=streaming,
    )


async def guarded_model_invoke(model: Any, payload: Any) -> Any:
    """通过共享舱壁和熔断器调用大模型，限制单 Worker 的模型并发。"""
    async with llm_guard.slot():
        return await model.ainvoke(payload)
