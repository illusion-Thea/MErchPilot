"""文件职责：定义数据库迁移 20260821_0004_planning_reports，保证既有环境可平滑升级。

add planning reports

Revision ID: 20260821_0004
Revises: 20260821_0003
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260821_0004"
down_revision: str | None = "20260821_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """应用当前数据库迁移，把既有结构升级到本版本。"""
    op.create_table(
        "planning_reports",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("format", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["planning_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["planning_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_planning_reports_project_id", "planning_reports", ["project_id"])
    op.create_index("ix_planning_reports_run_id", "planning_reports", ["run_id"])
    op.create_index("ix_planning_reports_status", "planning_reports", ["status"])


def downgrade() -> None:
    """回滚当前数据库迁移，恢复到上一版本结构。"""
    op.drop_table("planning_reports")
