"""文件职责：定义数据库迁移 20260822_0007_duplicate_review_lookup，保证既有环境可平滑升级。

index duplicate review lookup

Revision ID: 20260822_0007
Revises: 20260822_0006
Create Date: 2026-08-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260822_0007"
down_revision: str | None = "20260822_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """应用当前数据库迁移，把既有结构升级到本版本。"""
    op.create_index(
        "ix_duplicate_reviews_tenant_decision",
        "evidence_duplicate_reviews",
        ["tenant_id", "decision"],
    )


def downgrade() -> None:
    """回滚当前数据库迁移，恢复到上一版本结构。"""
    op.drop_index(
        "ix_duplicate_reviews_tenant_decision",
        table_name="evidence_duplicate_reviews",
    )
