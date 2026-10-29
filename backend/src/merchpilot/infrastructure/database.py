"""文件职责：创建 PostgreSQL 异步连接池与会话，并提供数据库健康检查。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from time import perf_counter
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from structlog import get_logger

from merchpilot.core.config import get_settings
from merchpilot.observability.metrics import db_query_duration_seconds, db_slow_queries_total


class Base(DeclarativeBase):
    """`Base` 封装基础设施资源及其连接、错误和生命周期管理。"""
    pass


settings = get_settings()
logger = get_logger("database")
engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_timeout=settings.database_pool_timeout_seconds,
    pool_recycle=settings.database_pool_recycle_seconds,
)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@event.listens_for(engine.sync_engine, "before_cursor_execute")
def _before_cursor_execute(
    connection: Any,
    cursor: object,
    statement: str,
    parameters: object,
    context: object,
    executemany: bool,
) -> None:
    """记录单条 SQL 的开始时间，为慢查询告警和 Prometheus 指标提供数据。"""
    del cursor, statement, parameters, context, executemany
    info = connection.info
    info.setdefault("merchpilot_query_starts", []).append(perf_counter())


@event.listens_for(engine.sync_engine, "after_cursor_execute")
def _after_cursor_execute(
    connection: Any,
    cursor: object,
    statement: str,
    parameters: object,
    context: object,
    executemany: bool,
) -> None:
    """记录 SQL 耗时；超过阈值时只记录摘要，避免日志泄露参数内容。"""
    del cursor, parameters, context, executemany
    info = connection.info
    starts = info.get("merchpilot_query_starts", [])
    if not starts:
        return
    elapsed_ms = (perf_counter() - starts.pop()) * 1000
    db_query_duration_seconds.observe(elapsed_ms / 1000)
    if elapsed_ms >= settings.database_slow_query_threshold_ms:
        db_slow_queries_total.inc()
        logger.warning(
            "slow_sql",
            duration_ms=round(elapsed_ms, 2),
            statement=str(statement)[:500],
        )


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """实现`get_db_session`基础设施操作；统一资源访问、异常和生命周期语义。"""
    async with async_session_factory() as session:
        yield session
