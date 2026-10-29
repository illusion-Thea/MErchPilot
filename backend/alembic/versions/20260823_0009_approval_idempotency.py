"""文件职责：定义数据库迁移 20260823_0009_approval_idempotency，保证既有环境可平滑升级。

add approval decision idempotency fields

Revision ID: 20260823_0009
Revises: 20260823_0008
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260823_0009"
down_revision: str | None = "20260823_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """应用当前数据库迁移，把既有结构升级到本版本。"""
    op.add_column(
        "approval_tasks",
        sa.Column("decision_request_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "approval_tasks",
        sa.Column("decision_payload_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    """回滚当前数据库迁移，恢复到上一版本结构。"""
    op.drop_column("approval_tasks", "decision_payload_hash")
    op.drop_column("approval_tasks", "decision_request_id")
