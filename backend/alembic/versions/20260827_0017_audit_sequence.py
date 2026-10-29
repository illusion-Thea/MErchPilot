"""文件职责：定义数据库迁移 20260827_0017_audit_sequence，保证既有环境可平滑升级。

add deterministic audit sequence

Revision ID: 20260827_0017
Revises: 20260827_0016
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260827_0017"
down_revision: str | None = "20260827_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """应用当前数据库迁移，把既有结构升级到本版本。"""
    op.add_column(
        "audit_events",
        sa.Column("sequence_no", sa.BigInteger(), nullable=True),
    )
    op.execute(
        "CREATE SEQUENCE audit_events_sequence_no_seq OWNED BY audit_events.sequence_no"
    )
    op.execute(
        "UPDATE audit_events SET sequence_no = nextval('audit_events_sequence_no_seq')"
    )
    op.alter_column("audit_events", "sequence_no", nullable=False)
    op.alter_column(
        "audit_events",
        "sequence_no",
        server_default=sa.text("nextval('audit_events_sequence_no_seq')"),
    )
    op.drop_constraint("audit_events_pkey", "audit_events", type_="primary")
    op.create_primary_key("audit_events_pkey", "audit_events", ["sequence_no"])
    op.create_unique_constraint("ix_audit_events_id", "audit_events", ["id"])


def downgrade() -> None:
    """回滚当前数据库迁移，恢复到上一版本结构。"""
    op.drop_constraint("ix_audit_events_id", "audit_events", type_="unique")
    op.drop_constraint("audit_events_pkey", "audit_events", type_="primary")
    op.drop_column("audit_events", "sequence_no")
    op.create_primary_key("audit_events_pkey", "audit_events", ["id"])
