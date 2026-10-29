"""文件职责：定义数据库迁移 20260822_0006_duplicate_review_candidates，保证既有环境可平滑升级。

track duplicate review candidates

Revision ID: 20260822_0006
Revises: 20260822_0005
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "20260822_0006"
down_revision: str | None = "20260822_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """应用当前数据库迁移，把既有结构升级到本版本。"""
    op.add_column(
        "evidence_duplicate_reviews",
        sa.Column("candidate_fingerprint", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "evidence_duplicate_reviews",
        sa.Column("candidate_evidence_ids", JSONB(), nullable=True),
    )


def downgrade() -> None:
    """回滚当前数据库迁移，恢复到上一版本结构。"""
    op.drop_column("evidence_duplicate_reviews", "candidate_evidence_ids")
    op.drop_column("evidence_duplicate_reviews", "candidate_fingerprint")
