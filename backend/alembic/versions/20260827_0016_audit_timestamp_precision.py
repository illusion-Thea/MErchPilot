"""文件职责：定义数据库迁移 20260827_0016_audit_timestamp_precision，保证既有环境可平滑升级。

increase audit timestamp precision

Revision ID: 20260827_0016
Revises: 20260827_0015
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260827_0016"
down_revision: str | None = "20260827_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """应用当前数据库迁移，把既有结构升级到本版本。"""
    op.alter_column(
        "audit_events",
        "occurred_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(timezone=True),
        existing_nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def downgrade() -> None:
    """回滚当前数据库迁移，恢复到上一版本结构。"""
    op.alter_column(
        "audit_events",
        "occurred_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(timezone=True),
        existing_nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
