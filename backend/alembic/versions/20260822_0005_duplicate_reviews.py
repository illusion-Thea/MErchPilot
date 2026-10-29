"""文件职责：定义数据库迁移 20260822_0005_duplicate_reviews，保证既有环境可平滑升级。

add evidence duplicate reviews

Revision ID: 20260822_0005
Revises: 20260821_0004
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260822_0005"
down_revision: str | None = "20260821_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """应用当前数据库迁移，把既有结构升级到本版本。"""
    op.create_table(
        "evidence_duplicate_reviews",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("match_type", sa.String(length=32), nullable=False),
        sa.Column("match_value", sa.String(length=512), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("canonical_evidence_id", sa.String(length=64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(length=64), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["canonical_evidence_id"],
            ["evidence_records.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "match_type",
            "match_value",
            name="uq_duplicate_review_match",
        ),
    )
    op.create_index(
        "ix_evidence_duplicate_reviews_tenant_id",
        "evidence_duplicate_reviews",
        ["tenant_id"],
    )
    op.create_index(
        "ix_evidence_duplicate_reviews_decision",
        "evidence_duplicate_reviews",
        ["decision"],
    )
    op.create_index(
        "ix_evidence_duplicate_reviews_canonical_evidence_id",
        "evidence_duplicate_reviews",
        ["canonical_evidence_id"],
    )
    op.create_index(
        "ix_duplicate_reviews_tenant_reviewed",
        "evidence_duplicate_reviews",
        ["tenant_id", "reviewed_at"],
    )


def downgrade() -> None:
    """回滚当前数据库迁移，恢复到上一版本结构。"""
    op.drop_table("evidence_duplicate_reviews")
