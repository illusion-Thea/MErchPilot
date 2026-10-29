/**
 * 文件职责：声明仪表盘、通知、机会和闭环台账 API 类型与调用方法。
 */

import { httpClient } from "@/lib/http/client";
import type { ApprovalTask, PlanningProject } from "@/lib/http/planning";
import type { ProductInitiative, ProductLaunchReview } from "@/lib/http/product-initiatives";
import type { SelectedProduct } from "@/lib/http/selected-products";

/** 定义`OpportunitySummary`数据契约，约束组件属性或接口响应字段。 */
export interface OpportunitySummary {
  project_id: string;
  project_name: string;
  category: string;
  target_market: string;
  project_status: string;
  run_id?: string;
  run_status?: string;
  score?: number;
  score_status?: string;
  evidence_count: number;
  margin_rate?: number;
  supplier_risk?: string;
  score_breakdown: Record<string, unknown>;
  updated_at: string;
}

/** 定义`OpportunityPage`数据契约，约束组件属性或接口响应字段。 */
export interface OpportunityPage {
  items: OpportunitySummary[];
  total: number;
  page: number;
  page_size: number;
}

/** 定义`ProjectLifecycleStageKey`允许的状态或联合类型，避免跨模块使用任意字符串。 */
export type ProjectLifecycleStageKey =
  | "project"
  | "agent"
  | "approval"
  | "selection"
  | "validation"
  | "initiative"
  | "launch_review"
  | "launched";

/** 定义`ProjectLifecycleStage`数据契约，约束组件属性或接口响应字段。 */
export interface ProjectLifecycleStage {
  key: ProjectLifecycleStageKey;
  label: string;
  status: "complete" | "current" | "waiting" | "blocked";
  detail: string;
  entity_id: string | null;
}

/** 定义`ProjectLifecycleActionType`允许的状态或联合类型，避免跨模块使用任意字符串。 */
export type ProjectLifecycleActionType =
  | "planning-project"
  | "planning-approval"
  | "selected-product"
  | "initiative-create"
  | "initiative"
  | "launch-review";

/** 定义`ProjectLifecycle`数据契约，约束组件属性或接口响应字段。 */
export interface ProjectLifecycle {
  project_id: string;
  project_name: string;
  category: string;
  target_market: string;
  project_status: string;
  run_id: string | null;
  run_status: string | null;
  approval_task_id: string | null;
  approval_status: string | null;
  selected_product_id: string | null;
  selected_product_name: string | null;
  selected_product_status: string | null;
  validation_status: string | null;
  initiative_id: string | null;
  initiative_status: string | null;
  launch_review_id: string | null;
  launch_review_status: string | null;
  current_milestone_id: string | null;
  current_milestone_label: string | null;
  current_milestone_status: string | null;
  stage: ProjectLifecycleStageKey;
  stage_label: string;
  progress_percent: number;
  health: "on_track" | "attention" | "blocked" | "complete";
  blockers: string[];
  next_action_label: string;
  next_action_type: ProjectLifecycleActionType;
  next_action_id: string;
  stages: ProjectLifecycleStage[];
  updated_at: string;
}

/** 定义`ProjectLifecyclePage`数据契约，约束组件属性或接口响应字段。 */
export interface ProjectLifecyclePage {
  items: ProjectLifecycle[];
  total: number;
  page: number;
  page_size: number;
  summary: ProjectLifecyclePageSummary;
}

/** 定义`ProjectLifecycleSort`允许的状态或联合类型，避免跨模块使用任意字符串。 */
export type ProjectLifecycleSort = "priority" | "updated";
/** 定义`ProjectLifecycleStatus`允许的状态或联合类型，避免跨模块使用任意字符串。 */
export type ProjectLifecycleStatus =
  | "all"
  | "blocked"
  | "waiting_human"
  | "active"
  | "complete";

/** 定义`ProjectLifecyclePageSummary`数据契约，约束组件属性或接口响应字段。 */
export interface ProjectLifecyclePageSummary {
  total: number;
  blocked: number;
  waiting_human: number;
  active: number;
  complete: number;
}

/** 定义`DashboardSnapshot`数据契约，约束组件属性或接口响应字段。 */
export interface DashboardSnapshot {
  latest_project: PlanningProject | null;
  latest_opportunity: OpportunitySummary | null;
  latest_selection: SelectedProduct | null;
  latest_ready_selection: SelectedProduct | null;
  latest_pending_selection: SelectedProduct | null;
  latest_initiative: ProductInitiative | null;
  attention_initiative: ProductInitiative | null;
  progress_initiative: ProductInitiative | null;
  latest_approval: ApprovalTask | null;
  latest_launch_review: ProductLaunchReview | null;
  pending_approval_count: number;
  pending_launch_review_count: number;
  project_total: number;
  active_project_total: number;
  completed_project_total: number;
  selected_product_total: number;
  selected_product_validating: number;
  selected_product_ready: number;
  active_initiative_total: number;
  pending_index_import_id: string | null;
}

/** 定义`NotificationEntityReference`数据契约，约束组件属性或接口响应字段。 */
export interface NotificationEntityReference {
  id: string;
  label: string;
}

/** 定义`NotificationSnapshot`数据契约，约束组件属性或接口响应字段。 */
export interface NotificationSnapshot {
  actionable_approval_count: number;
  overdue_actionable_approval_count: number;
  latest_actionable_approval: ApprovalTask | null;
  latest_overdue_approval: ApprovalTask | null;
  pending_launch_review_count: number;
  latest_launch_review: ProductLaunchReview | null;
  new_selection_count: number;
  latest_new_selection: NotificationEntityReference | null;
  ready_selection_count: number;
  latest_ready_selection: NotificationEntityReference | null;
  failed_project_count: number;
  latest_failed_project: NotificationEntityReference | null;
  cancelled_project_count: number;
  latest_cancelled_project: NotificationEntityReference | null;
  awaiting_approval_project_count: number;
  latest_awaiting_approval_project: NotificationEntityReference | null;
  failed_import_count: number;
  latest_failed_import: NotificationEntityReference | null;
  invalid_import_count: number;
  invalid_import_rows: number;
  latest_invalid_import: NotificationEntityReference | null;
  pending_index_import: NotificationEntityReference | null;
}

/** 调用后端`getDashboardSnapshot`接口并返回类型化响应。 */
export async function getDashboardSnapshot(): Promise<DashboardSnapshot> {
  const response = await httpClient.get<DashboardSnapshot>("/analytics/dashboard");
  return response.data;
}

/** 调用后端`getNotificationSnapshot`接口并返回类型化响应。 */
export async function getNotificationSnapshot(): Promise<NotificationSnapshot> {
  const response = await httpClient.get<NotificationSnapshot>("/analytics/notifications");
  return response.data;
}

/** 调用后端`listOpportunities`接口并返回类型化响应。 */
export async function listOpportunities(): Promise<OpportunitySummary[]> {
  const response = await httpClient.get<OpportunitySummary[]>("/analytics/opportunities");
  return response.data;
}

/** 调用后端`listOpportunitiesPage`接口并返回类型化响应。 */
export async function listOpportunitiesPage(
  page = 1,
  pageSize = 12,
): Promise<OpportunityPage> {
  const response = await httpClient.get<OpportunityPage>("/analytics/opportunities/page", {
    params: { page, page_size: pageSize },
  });
  return response.data;
}

/** 调用后端`listProjectLifecyclesPage`接口并返回类型化响应。 */
export async function listProjectLifecyclesPage(
  page = 1,
  pageSize = 3,
  keyword?: string,
  sort: ProjectLifecycleSort = "priority",
  status: ProjectLifecycleStatus = "all",
  projectId?: string,
): Promise<ProjectLifecyclePage> {
  const response = await httpClient.get<ProjectLifecyclePage>(
    "/analytics/project-lifecycles/page",
    { params: { page, page_size: pageSize, project_id: projectId, keyword, sort, status } },
  );
  return response.data;
}
