"""文件职责：定义数据库迁移 20260827_0015_product_initiatives，保证既有环境可平滑升级。

add product initiative tracking

Revision ID: 20260827_0015
Revises: 20260827_0014
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "20260827_0015"
down_revision: str | None = "20260827_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """应用当前数据库迁移，把既有结构升级到本版本。"""
    op.create_table(
        "product_initiatives",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("selected_product_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=128), nullable=False),
        sa.Column("target_market", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="in_progress", nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=True),
        sa.Column("target_launch_date", sa.Date(), nullable=True),
        sa.Column("budget", sa.Float(), nullable=True),
        sa.Column("milestones", JSONB(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("launched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["planning_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["planning_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["selected_product_id"], ["selected_products.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("selected_product_id", name="uq_product_initiatives_selected_product_id"),
    )
    op.create_index("ix_product_initiatives_tenant_id", "product_initiatives", ["tenant_id"])
    op.create_index(
        "ix_product_initiatives_selected_product_id",
        "product_initiatives",
        ["selected_product_id"],
    )
    op.create_index("ix_product_initiatives_project_id", "product_initiatives", ["project_id"])
    op.create_index("ix_product_initiatives_run_id", "product_initiatives", ["run_id"])
    op.create_index("ix_product_initiatives_category", "product_initiatives", ["category"])
    op.create_index(
        "ix_product_initiatives_target_market", "product_initiatives", ["target_market"]
    )
    op.create_index("ix_product_initiatives_status", "product_initiatives", ["status"])
    op.create_index("ix_product_initiatives_owner_id", "product_initiatives", ["owner_id"])
    op.create_index(
        "ix_product_initiatives_target_launch_date",
        "product_initiatives",
        ["target_launch_date"],
    )
    op.create_index(
        "ix_product_initiatives_tenant_status",
        "product_initiatives",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_product_initiatives_category_market",
        "product_initiatives",
        ["category", "target_market"],
    )


def downgrade() -> None:
    """回滚当前数据库迁移，恢复到上一版本结构。"""
    op.drop_table("product_initiatives")
