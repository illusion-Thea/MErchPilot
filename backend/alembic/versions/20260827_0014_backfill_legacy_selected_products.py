"""文件职责：定义数据库迁移 20260827_0014_backfill_legacy_selected_products，保证既有环境可平滑升级。

backfill legacy approved concepts into selected products

Revision ID: 20260827_0014
Revises: 20260827_0013
Create Date: 2026-08-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260827_0014"
down_revision: str | None = "20260827_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """应用当前数据库迁移，把既有结构升级到本版本。"""
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
        "r.result_snapshot, '历史审批数据自动回填', "
        "COALESCE(a.decided_by, a.assignee_id, 'system'), "
        "COALESCE(a.decided_at, r.completed_at, a.updated_at) "
        "FROM approval_tasks a "
        "JOIN planning_runs r ON r.id = a.run_id "
        "JOIN planning_projects p ON p.id = a.project_id "
        "LEFT JOIN selected_products sp ON sp.run_id = r.id "
        "WHERE a.status = 'approved' "
        "AND r.result_snapshot IS NOT NULL "
        "AND sp.id IS NULL"
    )


def downgrade() -> None:
    """回滚当前数据库迁移，恢复到上一版本结构。"""
    op.execute(
        "DELETE FROM selected_products "
        "WHERE notes = '历史审批数据自动回填' "
        "AND candidate_id LIKE 'legacy_%'"
    )
