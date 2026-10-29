"""文件职责：配置 Alembic 在线与离线迁移环境，并复用应用数据库元数据。"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from merchpilot.core.config import get_settings
from merchpilot.infrastructure.database import Base
from merchpilot.infrastructure import models


del models
config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("+asyncpg", "+psycopg"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """实现`run_migrations_offline`流程；输入、输出和异常语义由类型标注及调用方约束。"""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """实现`run_migrations_online`流程；输入、输出和异常语义由类型标注及调用方约束。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
