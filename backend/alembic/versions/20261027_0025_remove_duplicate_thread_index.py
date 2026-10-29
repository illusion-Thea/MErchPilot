"""删除与 thread_id 唯一约束重复的唯一索引。

Revision ID: 20261027_0025
Revises: 20260903_0024
Create Date: 2026-10-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261027_0025"
down_revision: str | None = "20260903_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """移除重复的 thread_id 唯一索引，保留唯一约束作为唯一性来源。"""
    op.drop_index("ix_planning_runs_thread_id", table_name="planning_runs")


def downgrade() -> None:
    """回滚时恢复原有唯一索引。"""
    op.create_index(
        "ix_planning_runs_thread_id",
        "planning_runs",
        ["thread_id"],
        unique=True,
    )
