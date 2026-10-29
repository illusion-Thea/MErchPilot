"""文件职责：定义数据库迁移 20260828_0020_product_launch_reviews，保证既有环境可平滑升级。

add product launch review records

Revision ID: 20260828_0020
Revises: 20260828_0019
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "20260828_0020"
down_revision: str | None = "20260828_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """应用当前数据库迁移，把既有结构升级到本版本。"""
    op.create_table(
        "product_launch_reviews",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("initiative_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("submission_note", sa.Text(), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("readiness_snapshot", JSONB(), nullable=False),
        sa.Column("submitted_by", sa.String(length=64), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_by", sa.String(length=64), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["initiative_id"], ["product_initiatives.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_product_launch_reviews_tenant_id",
        "product_launch_reviews",
        ["tenant_id"],
    )
    op.create_index(
        "ix_product_launch_reviews_initiative_id",
        "product_launch_reviews",
        ["initiative_id"],
    )
    op.create_index(
        "ix_product_launch_reviews_status",
        "product_launch_reviews",
        ["status"],
    )
    op.create_index(
        "ix_product_launch_reviews_tenant_initiative",
        "product_launch_reviews",
        ["tenant_id", "initiative_id"],
    )
    op.create_index(
        "ix_product_launch_reviews_tenant_status",
        "product_launch_reviews",
        ["tenant_id", "status"],
    )


def downgrade() -> None:
    """回滚当前数据库迁移，恢复到上一版本结构。"""
    op.drop_table("product_launch_reviews")
