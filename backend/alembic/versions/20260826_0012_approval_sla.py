"""文件职责：定义数据库迁移 20260826_0012_approval_sla，保证既有环境可平滑升级。

add approval sla deadline

Revision ID: 20260826_0012
Revises: 20260826_0011
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260826_0012"
down_revision: str | None = "20260826_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """应用当前数据库迁移，把既有结构升级到本版本。"""
    op.add_column(
        "approval_tasks",
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE approval_tasks "
        "SET due_at = created_at + INTERVAL '24 hours' "
        "WHERE due_at IS NULL"
    )
    op.create_index("ix_approval_tasks_due_at", "approval_tasks", ["due_at"], unique=False)


def downgrade() -> None:
    """回滚当前数据库迁移，恢复到上一版本结构。"""
    op.drop_index("ix_approval_tasks_due_at", table_name="approval_tasks")
    op.drop_column("approval_tasks", "due_at")
