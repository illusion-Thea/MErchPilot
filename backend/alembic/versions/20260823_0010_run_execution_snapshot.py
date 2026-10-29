"""文件职责：定义数据库迁移 20260823_0010_run_execution_snapshot，保证既有环境可平滑升级。

add planning run execution snapshot

Revision ID: 20260823_0010
Revises: 20260823_0009
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "20260823_0010"
down_revision: str | None = "20260823_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """应用当前数据库迁移，把既有结构升级到本版本。"""
    op.add_column(
        "planning_runs",
        sa.Column("execution_snapshot", JSONB(), nullable=False, server_default=sa.text("('{}')")),
    )


def downgrade() -> None:
    """回滚当前数据库迁移，恢复到上一版本结构。"""
    op.drop_column("planning_runs", "execution_snapshot")
