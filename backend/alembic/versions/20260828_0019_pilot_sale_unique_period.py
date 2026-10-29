"""文件职责：定义数据库迁移 20260828_0019_pilot_sale_unique_period，保证既有环境可平滑升级。

prevent duplicate pilot sale periods

Revision ID: 20260828_0019
Revises: 20260827_0018
Create Date: 2026-08-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260828_0019"
down_revision: str | None = "20260827_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """应用当前数据库迁移，把既有结构升级到本版本。"""
    op.create_unique_constraint(
        "uq_pilot_sales_period_channel",
        "pilot_sale_records",
        ["tenant_id", "initiative_id", "period_start", "period_end", "channel"],
    )


def downgrade() -> None:
    """回滚当前数据库迁移，恢复到上一版本结构。"""
    op.drop_constraint("uq_pilot_sales_period_channel", "pilot_sale_records", type_="unique")
