"""文件职责：定义数据库迁移 20260827_0018_pilot_sale_records，保证既有环境可平滑升级。

add pilot sale records

Revision ID: 20260827_0018
Revises: 20260827_0017
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260827_0018"
down_revision: str | None = "20260827_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """应用当前数据库迁移，把既有结构升级到本版本。"""
    op.create_table(
        "pilot_sale_records",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("initiative_id", sa.String(length=64), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("channel", sa.String(length=128), nullable=False),
        sa.Column("visitors", sa.Integer(), server_default="0", nullable=False),
        sa.Column("orders", sa.Integer(), server_default="0", nullable=False),
        sa.Column("units_sold", sa.Integer(), server_default="0", nullable=False),
        sa.Column("revenue", sa.Float(), server_default="0", nullable=False),
        sa.Column("product_cost", sa.Float(), server_default="0", nullable=False),
        sa.Column("marketing_spend", sa.Float(), server_default="0", nullable=False),
        sa.Column("refunds_amount", sa.Float(), server_default="0", nullable=False),
        sa.Column("return_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["initiative_id"], ["product_initiatives.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ["tenant_id", "initiative_id", "period_start", "period_end", "channel"]:
        op.create_index(f"ix_pilot_sale_records_{column}", "pilot_sale_records", [column])
    op.create_index(
        "ix_pilot_sales_tenant_initiative",
        "pilot_sale_records",
        ["tenant_id", "initiative_id"],
    )
    op.create_index(
        "ix_pilot_sales_initiative_period",
        "pilot_sale_records",
        ["initiative_id", "period_start", "period_end"],
    )


def downgrade() -> None:
    """回滚当前数据库迁移，恢复到上一版本结构。"""
    op.drop_table("pilot_sale_records")
