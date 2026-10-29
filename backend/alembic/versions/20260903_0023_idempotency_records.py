"""文件职责：定义数据库迁移 20260903_0023_idempotency_records，保证既有环境可平滑升级。

add reusable idempotency request ledger

Revision ID: 20260903_0023
Revises: 20260829_0022
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "20260903_0023"
down_revision: str | None = "20260829_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """应用当前数据库迁移，把既有结构升级到本版本。"""
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=False),
        sa.Column("response_snapshot", JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "actor_id",
            "operation",
            "idempotency_key",
            name="uq_idempotency_scope_key",
        ),
    )
    op.create_index("ix_idempotency_records_tenant_id", "idempotency_records", ["tenant_id"])
    op.create_index("ix_idempotency_records_actor_id", "idempotency_records", ["actor_id"])
    op.create_index("ix_idempotency_records_operation", "idempotency_records", ["operation"])
    op.create_index("ix_idempotency_records_resource_id", "idempotency_records", ["resource_id"])
    op.create_index("ix_idempotency_records_created_at", "idempotency_records", ["created_at"])
    op.create_index(
        "ix_idempotency_tenant_created",
        "idempotency_records",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "ix_idempotency_resource",
        "idempotency_records",
        ["resource_type", "resource_id"],
    )


def downgrade() -> None:
    """回滚当前数据库迁移，恢复到上一版本结构。"""
    op.drop_table("idempotency_records")
