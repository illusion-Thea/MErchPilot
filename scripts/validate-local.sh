#!/usr/bin/env bash
# 文件职责：对已启动的 Docker 本地环境执行 API、基础设施、FastMCP 和业务闭环验收。

set -euo pipefail

API_BASE_URL=${API_BASE_URL:-http://localhost:8000}
API_V1_BASE_URL=${API_V1_BASE_URL:-${API_BASE_URL}/api/v1}
WEB_URL=${WEB_URL:-http://localhost:3001}
MCP_URL=${MCP_URL:-http://localhost:8001}
validation_draft_project_id=""
project_id=""

archive_validation_draft() {
  if [[ -z "$validation_draft_project_id" ]]; then
    return 0
  fi
  local archive_status
  archive_status=$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 15 \
    -X POST \
    -H 'Authorization: Bearer local-profile:planner' \
    "${API_V1_BASE_URL}/planning-projects/${validation_draft_project_id}/archive" || true)
  if [[ "$archive_status" == "200" || "$archive_status" == "409" ]]; then
    validation_draft_project_id=""
    return 0
  fi
  return 1
}

cleanup_validation_draft() {
  archive_validation_draft || true
}

trap cleanup_validation_draft EXIT

request() {
  curl --fail --silent --show-error --max-time 15 "$1"
}

# API 可能先于 Celery Worker 启动；先等待核心依赖全部 ready，再开始业务验收。
wait_for_core_readiness() {
  local latest_ready=""
  for attempt in {1..30}; do
    latest_ready=$(curl --silent --show-error --max-time 15 \
      "${API_BASE_URL}/health/ready" || true)
    if [[ "$latest_ready" == *'"postgres":true'* \
      && "$latest_ready" == *'"redis":true'* \
      && "$latest_ready" == *'"milvus":true'* \
      && "$latest_ready" == *'"worker":true'* ]]; then
      printf '%s' "$latest_ready"
      return 0
    fi
    if [[ "$attempt" != "30" ]]; then
      sleep 2
    fi
  done
  printf 'FAIL  Core service readiness timeout\n%s\n' "$latest_ready" >&2
  return 1
}

mcp_request_as() {
  local profile=$1
  local payload=$2
  curl --fail --silent --show-error --max-time 30 \
    -H "Authorization: Bearer local-profile:${profile}" \
    -H 'Accept: application/json, text/event-stream' \
    -H 'Content-Type: application/json' \
    -H 'MCP-Protocol-Version: 2025-11-25' \
    --data "$payload" \
    "${MCP_URL}/mcp"
}

mcp_request() {
  mcp_request_as viewer "$1"
}

assert_contains() {
  local name=$1
  local value=$2
  local expected=$3
  if [[ "$value" != *"$expected"* ]]; then
    printf 'FAIL  %s (missing %s)\n' "$name" "$expected" >&2
    exit 1
  fi
  printf 'PASS  %s\n' "$name"
}

assert_not_contains() {
  local name=$1
  local value=$2
  local unexpected=$3
  if [[ "$value" == *"$unexpected"* ]]; then
    printf 'FAIL  %s (unexpected %s)\n' "$name" "$unexpected" >&2
    exit 1
  fi
  printf 'PASS  %s\n' "$name"
}

# 验证项目级分页结果中的列表、汇总和每条记录都属于同一当前项目。
assert_project_scoped_page() {
  local name=$1
  local value=$2
  local expected_project_id=$3
  if ! printf '%s' "$value" | python3 -c '
import json
import sys

expected_project_id = sys.argv[1]
payload = json.load(sys.stdin)
assert payload["total"] == payload["summary"]["total"]
assert all(item.get("project_id") == expected_project_id for item in payload["items"])
' "$expected_project_id"; then
    printf 'FAIL  %s\n' "$name" >&2
    exit 1
  fi
  printf 'PASS  %s\n' "$name"
}

printf 'MerchPilot local validation\n'
printf 'API: %s\nWeb: %s\nMCP: %s\n\n' "$API_V1_BASE_URL" "$WEB_URL" "$MCP_URL"

live=$(request "${API_BASE_URL}/health/live")
assert_contains "API liveness" "$live" '"status":"ok"'

ready=$(wait_for_core_readiness)
assert_contains "PostgreSQL readiness" "$ready" '"postgres":true'
assert_contains "Redis readiness" "$ready" '"redis":true'
assert_contains "Milvus readiness" "$ready" '"milvus":true'
assert_contains "Celery worker readiness" "$ready" '"worker":true'
assert_contains "FastMCP readiness" "$ready" '"mcp":true'
assert_contains "Identity provider readiness" "$ready" '"identity":true'
assert_contains "Object storage readiness" "$ready" '"object_storage":true'
assert_contains "Approval provider readiness" "$ready" '"approval":true'
assert_contains "Telemetry provider readiness" "$ready" '"telemetry":true'

identity=$(request "${API_V1_BASE_URL}/auth/me")
assert_contains "Identity context" "$identity" '"tenant_id"'
assert_contains "Identity roles" "$identity" '"roles"'

demo_workspace=$(curl --fail --silent --show-error --max-time 30 \
  -X POST \
  -H 'Authorization: Bearer local-profile:admin' \
  "${API_V1_BASE_URL}/demo-workspace")
assert_contains "Local demo evidence total" "$demo_workspace" '"evidence_count":15'
assert_contains "Local demo scenario planning approval" "$demo_workspace" '"scenario":"planning_approval"'
assert_contains "Local demo scenario validation" "$demo_workspace" '"scenario":"validation"'
assert_contains "Local demo scenario launch review" "$demo_workspace" '"scenario":"launch_review"'
assert_contains "Local demo scenario launched" "$demo_workspace" '"scenario":"launched"'
assert_contains "Local demo Milvus progress" "$demo_workspace" '"index_status"'

# 演示证据由 Celery 异步写入 Milvus；必须等到全部可检索，不能只验证任务已提交。
for attempt in {1..90}; do
  demo_workspace_view=$(curl --fail --silent --show-error --max-time 15 \
    -H 'Authorization: Bearer local-profile:viewer' \
    "${API_V1_BASE_URL}/demo-workspace")
  demo_index_status=$(printf '%s' "$demo_workspace_view" | python3 -c '
import json
import sys

print(json.load(sys.stdin)["index_status"])
')
  if [[ "$demo_index_status" == "indexed" ]]; then
    break
  fi
  if [[ "$demo_index_status" == "failed" ]]; then
    printf 'FAIL  Local demo Milvus indexing\n%s\n' "$demo_workspace_view" >&2
    exit 1
  fi
  if [[ "$attempt" == "90" ]]; then
    printf 'FAIL  Local demo Milvus indexing timeout\n' >&2
    exit 1
  fi
  sleep 2
done
assert_contains "Local demo indexed evidence total" "$demo_workspace_view" '"indexed_evidence_count":15'
assert_contains "Local demo no failed evidence" "$demo_workspace_view" '"failed_evidence_count":0'
assert_contains "Local demo Milvus ready" "$demo_workspace_view" '"index_status":"indexed"'

demo_workspace_repeat=$(curl --fail --silent --show-error --max-time 30 \
  -X POST \
  -H 'Authorization: Bearer local-profile:admin' \
  "${API_V1_BASE_URL}/demo-workspace")
assert_contains "Local demo idempotent repair" "$demo_workspace_repeat" '"created":false'

demo_retrieval=$(curl --fail --silent --show-error --max-time 180 \
  -H 'Authorization: Bearer local-profile:viewer' \
  -H 'Content-Type: application/json' \
  --data '{"query":"通勤场景需要温度显示和长效保温的杯子","category":"智能保温杯","target_market":"中国一二线城市","top_k":5}' \
  "${API_V1_BASE_URL}/retrieval/search")
assert_contains "Local demo semantic retrieval ready" "$demo_retrieval" '"status":"ready"'
assert_contains "Local demo semantic retrieval hit" "$demo_retrieval" '"demo_workspace":"merchpilot-local-demo-v1"'

mcp_health=$(request "${MCP_URL}/health")
assert_contains "FastMCP health" "$mcp_health" '"service":"merchpilot-mcp"'
assert_contains "FastMCP health status" "$mcp_health" '"status":"ok"'
assert_contains "FastMCP contract version" "$mcp_health" '"version":"0.9.0"'

mcp_unauthorized_status=$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 15 \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  "${MCP_URL}/mcp")
if [[ "$mcp_unauthorized_status" != "401" ]]; then
  printf 'FAIL  FastMCP bearer authentication (status %s)\n' "$mcp_unauthorized_status" >&2
  exit 1
fi
printf 'PASS  FastMCP bearer authentication\n'

mcp_tools=$(mcp_request '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}')
assert_contains "FastMCP planning tools" "$mcp_tools" '"name":"list_planning_projects"'
assert_contains "FastMCP evidence tools" "$mcp_tools" '"name":"search_enterprise_evidence"'
assert_contains "FastMCP lifecycle tools" "$mcp_tools" '"name":"list_project_lifecycles"'
assert_contains "FastMCP read-only annotations" "$mcp_tools" '"readOnlyHint":true'
assert_not_contains "FastMCP viewer write isolation" "$mcp_tools" '"name":"create_planning_project_draft"'
assert_not_contains "FastMCP viewer start isolation" "$mcp_tools" '"name":"start_planning_project_analysis"'

planner_mcp_tools=$(mcp_request_as planner '{"jsonrpc":"2.0","id":20,"method":"tools/list","params":{}}')
assert_contains "FastMCP planner controlled write" "$planner_mcp_tools" '"name":"create_planning_project_draft"'
assert_contains "FastMCP planner confirmed start" "$planner_mcp_tools" '"name":"start_planning_project_analysis"'
assert_contains "FastMCP planner validation gate" "$planner_mcp_tools" '"name":"update_validation_gate"'
assert_contains "FastMCP planner launch review" "$planner_mcp_tools" '"name":"submit_launch_review"'
assert_contains "FastMCP launch review context" "$planner_mcp_tools" '"name":"get_launch_review_context"'
assert_contains "FastMCP validation material boundary" "$planner_mcp_tools" '"material-required-for-ready"'
assert_contains "FastMCP human launch approval boundary" "$planner_mcp_tools" '"human-approval-required"'
assert_not_contains "FastMCP planner approval isolation" "$planner_mcp_tools" '"name":"claim_approval_task"'
assert_contains "FastMCP explicit confirmation contract" "$planner_mcp_tools" '"confirmation-required"'
assert_contains "FastMCP idempotent write annotation" "$planner_mcp_tools" '"idempotentHint":true'
assert_contains "FastMCP non-destructive write annotation" "$planner_mcp_tools" '"destructiveHint":false'

approver_mcp_tools=$(mcp_request_as approver '{"jsonrpc":"2.0","id":22,"method":"tools/list","params":{}}')
assert_contains "FastMCP approver task visibility" "$approver_mcp_tools" '"name":"list_approval_tasks"'
assert_contains "FastMCP controlled approval claim" "$approver_mcp_tools" '"name":"claim_approval_task"'
assert_contains "FastMCP controlled approval decision" "$approver_mcp_tools" '"name":"submit_approval_decision"'
assert_contains "FastMCP approval claim boundary" "$approver_mcp_tools" '"claim-required"'
assert_contains "FastMCP approval confirmation boundary" "$approver_mcp_tools" '"confirmation-required"'
assert_not_contains "FastMCP approver planning write isolation" "$approver_mcp_tools" '"name":"create_planning_project_draft"'
assert_not_contains "FastMCP approver validation isolation" "$approver_mcp_tools" '"name":"update_validation_gate"'
assert_not_contains "FastMCP approver launch submission isolation" "$approver_mcp_tools" '"name":"submit_launch_review"'

mcp_projects=$(mcp_request '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"list_planning_projects","arguments":{"page":1,"page_size":2}}}')
assert_contains "FastMCP API forwarding" "$mcp_projects" '"isError":false'
assert_contains "FastMCP bounded project result" "$mcp_projects" '"page_size":2'

mcp_lifecycles=$(mcp_request '{"jsonrpc":"2.0","id":31,"method":"tools/call","params":{"name":"list_project_lifecycles","arguments":{"page":1,"page_size":2,"sort":"priority"}}}')
assert_contains "FastMCP lifecycle forwarding" "$mcp_lifecycles" '"isError":false'
assert_contains "FastMCP bounded lifecycle result" "$mcp_lifecycles" '"page_size":2'
assert_contains "FastMCP lifecycle next action" "$mcp_lifecycles" '"next_action_type"'

mcp_draft_payload='{"jsonrpc":"2.0","id":21,"method":"tools/call","params":{"name":"create_planning_project_draft","arguments":{"request_id":"validate-local-draft-v1","name":"MCP 本地验收草稿","category":"保温杯","target_market":"中国","target_margin":0.35,"min_price":99,"max_price":199}}}'
mcp_draft=$(mcp_request_as planner "$mcp_draft_payload")
assert_contains "FastMCP controlled draft creation" "$mcp_draft" '"isError":false'
assert_contains "FastMCP stable draft creation boundary" "$mcp_draft" '"created_as":"draft"'
assert_contains "FastMCP review token" "$mcp_draft" '"review_token"'
assert_contains "FastMCP no automatic workflow action" "$mcp_draft" '"automatic_actions":[]'
validation_draft_project_id=$(printf '%s\n' "$mcp_draft" \
  | sed -n 's/.*"structuredContent":{"project":{"id":"\([^"]*\)".*/\1/p' \
  | head -n 1)
if [[ -z "$validation_draft_project_id" ]]; then
  printf 'FAIL  FastMCP validation draft identity\n' >&2
  exit 1
fi
printf 'PASS  FastMCP validation draft identity\n'

mcp_draft_replay=$(mcp_request_as planner "$mcp_draft_payload")
assert_contains "FastMCP idempotent replay" "$mcp_draft_replay" '"replayed":true'
assert_contains "FastMCP stable request identity" "$mcp_draft_replay" '"idempotency_key":"validate-local-draft-v1"'

mcp_integration=$(request "${API_V1_BASE_URL}/integrations/mcp?page=1&page_size=6")
assert_contains "FastMCP integration center status" "$mcp_integration" '"status":"ready"'
assert_contains "FastMCP integration identity" "$mcp_integration" '"authenticated":true'
assert_contains "FastMCP integration tool pagination" "$mcp_integration" '"page_size":6'
assert_contains "FastMCP integration client configuration" "$mcp_integration" '"mcpServers"'
assert_contains "FastMCP admin controlled-write summary" "$mcp_integration" '"controlled_write_total":6'

mcp_verification=$(curl --fail --silent --show-error --max-time 30 \
  -X POST \
  "${API_V1_BASE_URL}/integrations/mcp/verify")
assert_contains "FastMCP current identity verification" "$mcp_verification" '"status":"verified"'
assert_contains "FastMCP tenant-scoped dashboard" "$mcp_verification" '"project_total"'

viewer_mcp_integration=$(curl --fail --silent --show-error --max-time 30 \
  -H 'Authorization: Bearer local-profile:viewer' \
  "${API_V1_BASE_URL}/integrations/mcp?page=1&page_size=6")
assert_contains "FastMCP viewer identity" "$viewer_mcp_integration" '"user_id":"local-user-viewer"'
assert_contains "FastMCP viewer role" "$viewer_mcp_integration" '"roles":["viewer"]'
assert_contains "FastMCP viewer configuration" "$viewer_mcp_integration" '"Authorization":"Bearer local-profile:viewer"'
assert_contains "FastMCP viewer read-only summary" "$viewer_mcp_integration" '"controlled_write_total":0'
assert_not_contains "FastMCP viewer catalog write isolation" "$viewer_mcp_integration" '"name":"create_planning_project_draft"'
assert_not_contains "FastMCP viewer catalog start isolation" "$viewer_mcp_integration" '"name":"start_planning_project_analysis"'

viewer_mcp_verification=$(curl --fail --silent --show-error --max-time 30 \
  -X POST \
  -H 'Authorization: Bearer local-profile:viewer' \
  "${API_V1_BASE_URL}/integrations/mcp/verify")
assert_contains "FastMCP viewer business verification" "$viewer_mcp_verification" '"status":"verified"'
assert_contains "FastMCP viewer tenant isolation" "$viewer_mcp_verification" '"tenant_id":"default"'

mcp_activities=$(curl --fail --silent --show-error --max-time 30 \
  -H 'Authorization: Bearer local-profile:planner' \
  "${API_V1_BASE_URL}/integrations/mcp/activities?page=1&page_size=5")
assert_contains "FastMCP activity pagination" "$mcp_activities" '"page_size":5'
assert_contains "FastMCP activity project trace" "$mcp_activities" '"request_id":"validate-local-draft-v1"'
assert_contains "FastMCP activity project status" "$mcp_activities" '"project_status"'
assert_contains "FastMCP activity latest start projection" "$mcp_activities" '"latest_start_request_id"'
assert_contains "FastMCP activity source type" "$mcp_activities" '"activity_type"'
assert_contains "FastMCP activity original creator" "$mcp_activities" '"project_created_by"'
assert_contains "FastMCP activity approval projection" "$mcp_activities" '"latest_approval_request_id"'
assert_contains "FastMCP activity validation projection" "$mcp_activities" '"latest_validation_request_id"'
assert_contains "FastMCP activity launch review projection" "$mcp_activities" '"latest_launch_review_request_id"'
if ! archive_validation_draft; then
  printf 'FAIL  FastMCP validation draft cleanup\n' >&2
  exit 1
fi
printf 'PASS  FastMCP validation draft cleanup\n'

approver_mcp_activity_status=$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 15 \
  -H 'Authorization: Bearer local-profile:approver' \
  "${API_V1_BASE_URL}/integrations/mcp/activities")
if [[ "$approver_mcp_activity_status" != "200" ]]; then
  printf 'FAIL  FastMCP approver activity access (status %s)\n' "$approver_mcp_activity_status" >&2
  exit 1
fi
printf 'PASS  FastMCP approver activity access\n'

viewer_mcp_activity_status=$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 15 \
  -H 'Authorization: Bearer local-profile:viewer' \
  "${API_V1_BASE_URL}/integrations/mcp/activities")
if [[ "$viewer_mcp_activity_status" != "403" ]]; then
  printf 'FAIL  FastMCP activity role isolation (status %s)\n' "$viewer_mcp_activity_status" >&2
  exit 1
fi
printf 'PASS  FastMCP activity role isolation\n'

projects=$(request "${API_V1_BASE_URL}/planning-projects")
assert_contains "Planning project list" "$projects" '['

projects_page=$(request "${API_V1_BASE_URL}/planning-projects/page?page=1&page_size=8")
assert_contains "Planning project server pagination" "$projects_page" '"items"'
assert_contains "Planning project page metadata" "$projects_page" '"page_size":8'
assert_contains "Planning project summary" "$projects_page" '"summary"'

run_page=$(request "${API_V1_BASE_URL}/planning-projects/page?page=1&page_size=1")
if [[ "$run_page" == *'"items"'* ]]; then
  project_id=$(printf '%s' "$run_page" | sed -n 's/.*"id":"\([^"]*\)".*/\1/p' | head -n 1)
  if [[ -n "$project_id" ]]; then
    runs_page=$(request "${API_V1_BASE_URL}/planning-projects/${project_id}/runs/page?page=1&page_size=5")
    assert_contains "Planning run server pagination" "$runs_page" '"items"'
    assert_contains "Planning run page metadata" "$runs_page" '"page_size":5'
    assert_contains "Planning run summary" "$runs_page" '"summary"'
    run_id=$(printf '%s' "$runs_page" | sed -n 's/.*"items":\[{"id":"\([^"]*\)".*/\1/p' | head -n 1)
    if [[ -n "$run_id" ]]; then
      run_evidence_page=$(request "${API_V1_BASE_URL}/planning-projects/${project_id}/runs/${run_id}/evidence/page?page=1&page_size=8")
      assert_contains "Planning evidence server pagination" "$run_evidence_page" '"items"'
      assert_contains "Planning evidence page metadata" "$run_evidence_page" '"page_size":8'
      assert_contains "Planning evidence withdrawal summary" "$run_evidence_page" '"unavailable_total"'

      reports_page=$(request "${API_V1_BASE_URL}/planning-projects/${project_id}/runs/${run_id}/reports/page?page=1&page_size=5")
      assert_contains "Planning report server pagination" "$reports_page" '"items"'
      assert_contains "Planning report page metadata" "$reports_page" '"page_size":5'
    else
      printf 'PASS  Planning report pagination (no run data)\n'
    fi
  else
    printf 'PASS  Planning run pagination (no project data)\n'
  fi
else
  printf 'PASS  Planning run pagination (no project data)\n'
fi

imports=$(request "${API_V1_BASE_URL}/data-imports")
assert_contains "Data import list" "$imports" '['

imports_page=$(request "${API_V1_BASE_URL}/data-imports/page?page=1&page_size=5")
assert_contains "Data import server pagination" "$imports_page" '"items"'
assert_contains "Data import page metadata" "$imports_page" '"page_size":5'
assert_contains "Data import summary" "$imports_page" '"summary"'

quality=$(request "${API_V1_BASE_URL}/data-imports/quality-summary")
assert_contains "Data quality summary" "$quality" '"total_imports"'
assert_contains "Data quality bounded problem imports" "$quality" '"problem_import_total"'

coverage=$(request "${API_V1_BASE_URL}/data-imports/coverage")
assert_contains "Data coverage database aggregation" "$coverage" '"source_id_coverage_rate"'

duplicates_page=$(request "${API_V1_BASE_URL}/data-imports/duplicates/page?status=pending&page=1&page_size=6")
assert_contains "Duplicate candidate server pagination" "$duplicates_page" '"items"'
assert_contains "Duplicate candidate page metadata" "$duplicates_page" '"page_size":6'
assert_contains "Duplicate candidate review summary" "$duplicates_page" '"pending"'

dashboard=$(request "${API_V1_BASE_URL}/analytics/dashboard")
assert_contains "Dashboard snapshot" "$dashboard" '"project_total"'
assert_contains "Dashboard selected product summary" "$dashboard" '"selected_product_total"'

notifications=$(request "${API_V1_BASE_URL}/analytics/notifications")
assert_contains "Notification snapshot" "$notifications" '"actionable_approval_count"'
assert_contains "Notification import summary" "$notifications" '"failed_import_count"'

opportunities_page=$(request "${API_V1_BASE_URL}/analytics/opportunities/page?page=1&page_size=12")
assert_contains "Opportunity server pagination" "$opportunities_page" '"items"'
assert_contains "Opportunity page metadata" "$opportunities_page" '"page_size":12'

lifecycles_page=$(request "${API_V1_BASE_URL}/analytics/project-lifecycles/page?page=1&page_size=3&sort=priority")
assert_contains "Project lifecycle server pagination" "$lifecycles_page" '"items"'
assert_contains "Project lifecycle page metadata" "$lifecycles_page" '"page_size":3'
assert_contains "Project lifecycle stage trace" "$lifecycles_page" '"stages"'
assert_contains "Project lifecycle next action" "$lifecycles_page" '"next_action_type"'
assert_contains "Project lifecycle global summary" "$lifecycles_page" '"summary"'

updated_lifecycles_page=$(request "${API_V1_BASE_URL}/analytics/project-lifecycles/page?page=1&page_size=3&sort=updated")
assert_contains "Project lifecycle updated sorting" "$updated_lifecycles_page" '"page_size":3'

blocked_lifecycles_page=$(request "${API_V1_BASE_URL}/analytics/project-lifecycles/page?page=1&page_size=3&status=blocked")
assert_contains "Project lifecycle status filtering" "$blocked_lifecycles_page" '"summary"'

missing_lifecycle_search=$(request "${API_V1_BASE_URL}/analytics/project-lifecycles/page?page=1&page_size=3&keyword=__merchpilot_missing_lifecycle__")
assert_contains "Project lifecycle keyword filtering" "$missing_lifecycle_search" '"total":0'
assert_contains "Project lifecycle keyword-scoped summary" "$missing_lifecycle_search" '"summary":{"total":0'

approvals=$(request "${API_V1_BASE_URL}/approval-tasks")
assert_contains "Approval task list" "$approvals" '['

approvals_page=$(request "${API_V1_BASE_URL}/approval-tasks/page?status=pending&page=1&page_size=5")
assert_contains "Approval server pagination" "$approvals_page" '"items"'
assert_contains "Approval page metadata" "$approvals_page" '"page_size":5'
assert_contains "Approval summary" "$approvals_page" '"summary"'

launch_reviews_page=$(request "${API_V1_BASE_URL}/product-initiatives/launch-reviews/page?status=pending&page=1&page_size=5")
assert_contains "Launch review server pagination" "$launch_reviews_page" '"items"'
assert_contains "Launch review page metadata" "$launch_reviews_page" '"page_size":5'
assert_contains "Launch review summary" "$launch_reviews_page" '"summary"'

selected_products=$(request "${API_V1_BASE_URL}/selected-products")
assert_contains "Selected product list" "$selected_products" '['

selected_products_page=$(request "${API_V1_BASE_URL}/selected-products/page?page=1&page_size=6")
assert_contains "Selected product server pagination" "$selected_products_page" '"items"'
assert_contains "Selected product page metadata" "$selected_products_page" '"page_size":6'
assert_contains "Selected product summary" "$selected_products_page" '"summary"'

selected_product_probe=$(request "${API_V1_BASE_URL}/selected-products/page?page=1&page_size=1")
selected_product_id=$(printf '%s' "$selected_product_probe" | sed -n 's/.*"items":\[{"id":"\([^"]*\)".*/\1/p' | head -n 1)
if [[ -n "$selected_product_id" ]]; then
  selected_product_timeline_page=$(request "${API_V1_BASE_URL}/selected-products/${selected_product_id}/timeline/page?page=1&page_size=8")
  assert_contains "Selected product timeline pagination" "$selected_product_timeline_page" '"items"'
  assert_contains "Selected product timeline metadata" "$selected_product_timeline_page" '"page_size":8'
else
  printf 'PASS  Selected product timeline pagination (no selected product data)\n'
fi

initiatives=$(request "${API_V1_BASE_URL}/product-initiatives")
assert_contains "Product initiative list" "$initiatives" '['

initiatives_page=$(request "${API_V1_BASE_URL}/product-initiatives/page?page=1&page_size=6")
assert_contains "Product initiative server pagination" "$initiatives_page" '"items"'
assert_contains "Product initiative page metadata" "$initiatives_page" '"page_size":6'
assert_contains "Product initiative summary" "$initiatives_page" '"summary"'

initiative_probe=$(request "${API_V1_BASE_URL}/product-initiatives/page?page=1&page_size=1")
initiative_id=$(printf '%s' "$initiative_probe" | sed -n 's/.*"items":\[{"id":"\([^"]*\)".*/\1/p' | head -n 1)
if [[ -n "$initiative_id" ]]; then
  pilot_sales_page=$(request "${API_V1_BASE_URL}/product-initiatives/${initiative_id}/pilot-sales/page?page=1&page_size=5")
  assert_contains "Pilot sale server pagination" "$pilot_sales_page" '"items"'
  assert_contains "Pilot sale page metadata" "$pilot_sales_page" '"page_size":5'

  pilot_sales_trend=$(request "${API_V1_BASE_URL}/product-initiatives/${initiative_id}/pilot-sales-trend")
  assert_contains "Pilot sale bounded trend" "$pilot_sales_trend" '"period_total"'
  assert_contains "Pilot sale bounded channels" "$pilot_sales_trend" '"channel_total"'

  initiative_timeline_page=$(request "${API_V1_BASE_URL}/product-initiatives/${initiative_id}/timeline/page?page=1&page_size=8")
  assert_contains "Initiative timeline server pagination" "$initiative_timeline_page" '"items"'
  assert_contains "Initiative timeline page metadata" "$initiative_timeline_page" '"page_size":8'

  initiative_reviews_page=$(request "${API_V1_BASE_URL}/product-initiatives/launch-reviews/page?status=all&initiative_id=${initiative_id}&page=1&page_size=5")
  assert_contains "Initiative launch review pagination" "$initiative_reviews_page" '"items"'
  assert_contains "Initiative launch review summary" "$initiative_reviews_page" '"summary"'
else
  printf 'PASS  Product initiative detail pagination (no initiative data)\n'
fi

if [[ -n "$project_id" ]]; then
  scoped_approvals=$(request "${API_V1_BASE_URL}/approval-tasks/page?status=all&project_id=${project_id}&page=1&page_size=100")
  assert_project_scoped_page "Current project approval scope" "$scoped_approvals" "$project_id"

  scoped_products=$(request "${API_V1_BASE_URL}/selected-products/page?project_id=${project_id}&page=1&page_size=100")
  assert_project_scoped_page "Current project selected product scope" "$scoped_products" "$project_id"

  scoped_initiatives=$(request "${API_V1_BASE_URL}/product-initiatives/page?project_id=${project_id}&page=1&page_size=100")
  assert_project_scoped_page "Current project initiative scope" "$scoped_initiatives" "$project_id"

  scoped_launch_reviews=$(request "${API_V1_BASE_URL}/product-initiatives/launch-reviews/page?status=all&project_id=${project_id}&page=1&page_size=100")
  assert_project_scoped_page "Current project launch review scope" "$scoped_launch_reviews" "$project_id"

  scoped_lifecycle=$(request "${API_V1_BASE_URL}/analytics/project-lifecycles/page?project_id=${project_id}&page=1&page_size=1")
  assert_project_scoped_page "Current project lifecycle scope" "$scoped_lifecycle" "$project_id"
  assert_contains "Current project lifecycle stages" "$scoped_lifecycle" '"stages"'
  assert_contains "Current project lifecycle next action" "$scoped_lifecycle" '"next_action_type"'
else
  printf 'PASS  Current project module scope (no project data)\n'
fi

web_html=$(request "$WEB_URL/")
web_bundle=""
while IFS= read -r asset_path; do
  [[ -z "$asset_path" ]] && continue
  web_bundle+=$(request "${WEB_URL}${asset_path}")
done < <(printf '%s' "$web_html" | python3 -c '
import re
import sys

print("\n".join(re.findall(r"src=\"([^\"]+\.js)\"", sys.stdin.read())))
')
assert_contains "Web current project selector" "$web_bundle" '跨模块当前项目'
assert_contains "Web current project workflow actions" "$web_bundle" '项目视角已锁定'
assert_contains "Web current project lifecycle" "$web_bundle" '当前项目闭环'
assert_contains "Web current project next action" "$web_bundle" '建议下一步'
assert_contains "Web current project share link" "$web_bundle" '复制项目链接'
assert_contains "Web invalid project recovery" "$web_bundle" '链接或历史项目不可用，已恢复为全局视角'
assert_contains "Web local demo workspace" "$web_bundle" '本地完整演示'
assert_contains "Web local demo initializer" "$web_bundle" '生成本地演示工作区'
assert_contains "Web local demo Milvus status" "$web_bundle" 'Milvus 已索引'
printf 'PASS  Web application\n'

printf '\nLocal business loop endpoints are reachable.\n'
