"""文件职责：定义数据库迁移 20260823_0008_run_versions，保证既有环境可平滑升级。

add planning run version lineage

Revision ID: 20260823_0008
Revises: 20260822_0007
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260823_0008"
down_revision: str | None = "20260822_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """应用当前数据库迁移，把既有结构升级到本版本。"""
    op.add_column(
        "planning_runs",
        sa.Column("parent_run_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "planning_runs",
        sa.Column("revision_no", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.create_index("ix_planning_runs_parent_run_id", "planning_runs", ["parent_run_id"])
    op.create_index(
        "ix_runs_project_revision",
        "planning_runs",
        ["project_id", "revision_no"],
    )
    op.create_foreign_key(
        "fk_planning_runs_parent_run_id",
        "planning_runs",
        "planning_runs",
        ["parent_run_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """回滚当前数据库迁移，恢复到上一版本结构。"""
    op.drop_constraint("fk_planning_runs_parent_run_id", "planning_runs", type_="foreignkey")
    op.drop_index("ix_runs_project_revision", table_name="planning_runs")
    op.drop_index("ix_planning_runs_parent_run_id", table_name="planning_runs")
    op.drop_column("planning_runs", "revision_no")
    op.drop_column("planning_runs", "parent_run_id")
