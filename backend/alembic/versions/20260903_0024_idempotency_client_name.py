"""文件职责：定义数据库迁移 20260903_0024_idempotency_client_name，保证既有环境可平滑升级。

track idempotency request client provenance

Revision ID: 20260903_0024
Revises: 20260903_0023
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260903_0024"
down_revision: str | None = "20260903_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """应用当前数据库迁移，把既有结构升级到本版本。"""
    op.add_column(
        "idempotency_records",
        sa.Column(
            "client_name",
            sa.String(length=64),
            server_default="unknown",
            nullable=False,
        ),
    )
    op.execute(
        "UPDATE idempotency_records AS i SET client_name = COALESCE(a.detail ->> 'client', 'unknown') "
        "FROM audit_events AS a "
        "WHERE a.tenant_id = i.tenant_id "
        "AND a.actor_id = i.actor_id "
        "AND a.entity_type = i.resource_type "
        "AND a.entity_id = i.resource_id "
        "AND a.action = 'project.created' "
        "AND i.operation = 'planning_project.create'"
    )
    op.alter_column(
        "idempotency_records",
        "client_name",
        existing_type=sa.String(length=64),
        existing_nullable=False,
        server_default=None,
    )
    op.create_index(
        "ix_idempotency_tenant_client_created",
        "idempotency_records",
        ["tenant_id", "client_name", "created_at"],
    )


def downgrade() -> None:
    """回滚当前数据库迁移，恢复到上一版本结构。"""
    op.drop_index(
        "ix_idempotency_tenant_client_created",
        table_name="idempotency_records",
    )
    op.drop_column("idempotency_records", "client_name")
