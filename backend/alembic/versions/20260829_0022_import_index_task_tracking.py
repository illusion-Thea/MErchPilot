"""文件职责：定义数据库迁移 20260829_0022_import_index_task_tracking，保证既有环境可平滑升级。

track the asynchronous Milvus indexing task for data imports

Revision ID: 20260829_0022
Revises: 20260829_0021
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260829_0022"
down_revision: str | None = "20260829_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """应用当前数据库迁移，把既有结构升级到本版本。"""
    op.add_column(
        "data_import_jobs",
        sa.Column("index_celery_task_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    """回滚当前数据库迁移，恢复到上一版本结构。"""
    op.drop_column("data_import_jobs", "index_celery_task_id")
