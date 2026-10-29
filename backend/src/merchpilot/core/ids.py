"""文件职责：生成带业务前缀的唯一标识，便于日志和数据表中识别实体类型。"""

from __future__ import annotations

from uuid import uuid4


def new_id(prefix: str) -> str:
    """实现`new_id`流程；输入、输出和异常语义由类型标注及调用方约束。"""
    return f"{prefix}_{uuid4().hex}"
