"""文件职责：定义数据库迁移 20260827_0013_selected_products，保证既有环境可平滑升级。

add selected product registry

Revision ID: 20260827_0013
Revises: 20260826_0012
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "20260827_0013"
down_revision: str | None = "20260826_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """应用当前数据库迁移，把既有结构升级到本版本。"""
    op.create_table(
        "selected_products",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("approval_task_id", sa.String(length=64), nullable=True),
        sa.Column("candidate_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=128), nullable=False),
        sa.Column("target_market", sa.String(length=128), nullable=False),
        sa.Column("positioning", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="selected"),
        sa.Column("owner_id", sa.String(length=64), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("selling_price", sa.Float(), nullable=True),
        sa.Column("margin_rate", sa.Float(), nullable=True),
        sa.Column("estimated_profit", sa.Float(), nullable=True),
        sa.Column("supplier_name", sa.String(length=255), nullable=True),
        sa.Column("validation_status", sa.String(length=32), nullable=True),
        sa.Column("selection_snapshot", JSONB(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("selected_by", sa.String(length=64), nullable=False),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["approval_task_id"], ["approval_tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["planning_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["planning_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_selected_products_run_id"),
    )
    op.create_index("ix_selected_products_tenant_id", "selected_products", ["tenant_id"])
    op.create_index("ix_selected_products_project_id", "selected_products", ["project_id"])
    op.create_index(
        "ix_selected_products_approval_task_id",
        "selected_products",
        ["approval_task_id"],
    )
    op.create_index("ix_selected_products_candidate_id", "selected_products", ["candidate_id"])
    op.create_index("ix_selected_products_category", "selected_products", ["category"])
    op.create_index("ix_selected_products_target_market", "selected_products", ["target_market"])
    op.create_index("ix_selected_products_status", "selected_products", ["status"])
    op.create_index("ix_selected_products_owner_id", "selected_products", ["owner_id"])
    op.create_index(
        "ix_selected_products_tenant_status",
        "selected_products",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_selected_products_category_market",
        "selected_products",
        ["category", "target_market"],
    )
    op.execute(
        "INSERT INTO selected_products ("
        "id, tenant_id, project_id, run_id, approval_task_id, candidate_id, name, "
        "project_name, category, target_market, positioning, status, owner_id, score, "
        "selling_price, margin_rate, estimated_profit, supplier_name, validation_status, "
        "selection_snapshot, notes, selected_by, selected_at"
        ") SELECT "
        "'selection_' || md5(random()::text || clock_timestamp()::text), p.tenant_id, p.id, r.id, a.id, "
        "COALESCE(r.result_snapshot #>> '{outputs,concept,selected_candidate,id}', 'legacy_' || r.id), "
        "COALESCE(r.result_snapshot #>> '{outputs,concept,selected_candidate,name}', "
        "r.result_snapshot #>> '{outputs,concept,name}', p.name), "
        "p.name, p.category, p.target_market, "
        "COALESCE(r.result_snapshot #>> '{outputs,concept,selected_candidate,positioning}', "
        "r.result_snapshot #>> '{outputs,concept,positioning}'), "
        "'selected', COALESCE(a.decided_by, a.assignee_id, 'system'), "
        "COALESCE(NULLIF(r.result_snapshot #>> "
        "'{outputs,concept,selected_candidate,scorecard,total_score}', '')::numeric::integer, "
        "NULLIF(r.result_snapshot #>> '{outputs,scorecard,score}', '')::numeric::integer), "
        "COALESCE(NULLIF(r.result_snapshot #>> "
        "'{outputs,selected_candidate_finance,selling_price}', '')::double precision, "
        "NULLIF(r.result_snapshot #>> '{outputs,finance,selling_price}', '')::double precision), "
        "COALESCE(NULLIF(r.result_snapshot #>> "
        "'{outputs,selected_candidate_finance,margin_rate}', '')::double precision, "
        "NULLIF(r.result_snapshot #>> '{outputs,finance,margin_rate}', '')::double precision), "
        "COALESCE(NULLIF(r.result_snapshot #>> "
        "'{outputs,selected_candidate_finance,estimated_profit}', '')::double precision, "
        "NULLIF(r.result_snapshot #>> '{outputs,finance,estimated_profit}', '')::double precision), "
        "r.result_snapshot #>> '{outputs,supplier,supplier_name}', "
        "r.result_snapshot #>> '{outputs,concept,selected_candidate,validation_plan,status}', "
        "r.result_snapshot, NULL, COALESCE(a.decided_by, a.assignee_id, 'system'), "
        "COALESCE(a.decided_at, r.completed_at, a.updated_at) "
        "FROM approval_tasks a "
        "JOIN planning_runs r ON r.id = a.run_id "
        "JOIN planning_projects p ON p.id = a.project_id "
        "WHERE a.status = 'approved' "
        "AND r.result_snapshot IS NOT NULL"
    )


def downgrade() -> None:
    """回滚当前数据库迁移，恢复到上一版本结构。"""
    op.drop_table("selected_products")
