"""文件职责：定义数据库迁移 20260826_0011_project_archiving，保证既有环境可平滑升级。

add project archiving

Revision ID: 20260826_0011
Revises: 20260823_0010
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260826_0011"
down_revision: str | None = "20260823_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """应用当前数据库迁移，把既有结构升级到本版本。"""
    op.add_column(
        "planning_projects",
        sa.Column("archived_by", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "planning_projects",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_planning_projects_archived_at",
        "planning_projects",
        ["archived_at"],
    )


def downgrade() -> None:
    """回滚当前数据库迁移，恢复到上一版本结构。"""
    op.drop_index("ix_planning_projects_archived_at", table_name="planning_projects")
    op.drop_column("planning_projects", "archived_at")
    op.drop_column("planning_projects", "archived_by")
