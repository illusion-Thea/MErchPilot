/**
 * 文件职责：声明规划项目、运行、审批、证据和报告 API 契约。
 */

import { httpClient } from "@/lib/http/client";

import type { RunEvent } from "@/lib/ws/run-socket";

/** 定义`PlanningProject`数据契约，约束组件属性或接口响应字段。 */
export interface PlanningProject {
  id: string;
  tenant_id: string;
  name: string;
  category: string;
  target_market: string;
  status: string;
  constraints: Record<string, unknown>;
  archived_by?: string;
  archived_at?: string;
  created_at: string;
  updated_at: string;
}

/** 定义`PlanningProjectPageSummary`数据契约，约束组件属性或接口响应字段。 */
export interface PlanningProjectPageSummary {
  total: number;
  draft: number;
  queued: number;
  running: number;
  approval_required: number;
  completed: number;
  failed: number;
  cancelled: number;
}

/** 定义`PlanningProjectPage`数据契约，约束组件属性或接口响应字段。 */
export interface PlanningProjectPage {
  items: PlanningProject[];
  total: number;
  page: number;
  page_size: number;
  summary: PlanningProjectPageSummary;
}

/** 定义`PlanningProjectPageParams`数据契约，约束组件属性或接口响应字段。 */
export interface PlanningProjectPageParams {
  archivedOnly?: boolean;
  status?: string;
  keyword?: string;
  projectId?: string;
  page?: number;
  pageSize?: number;
}

/** 定义`PlanningProjectCreate`数据契约，约束组件属性或接口响应字段。 */
export interface PlanningProjectCreate {
  name: string;
  category: string;
  target_market: string;
  constraints: Record<string, unknown>;
}

/** 定义`PlanningProjectUpdate`允许的状态或联合类型，避免跨模块使用任意字符串。 */
export type PlanningProjectUpdate = Partial<PlanningProjectCreate>;

/** 定义`PlanningRun`数据契约，约束组件属性或接口响应字段。 */
export interface PlanningRun {
  id: string;
  project_id: string;
  parent_run_id?: string;
  revision_no: number;
  thread_id: string;
  status: string;
  celery_task_id?: string;
  error_message?: string;
  execution_snapshot?: Record<string, unknown>;
  started_at?: string;
  completed_at?: string;
  created_at: string;
  updated_at: string;
  input_snapshot?: Record<string, unknown>;
  result_snapshot?: Record<string, unknown>;
}

/** 定义`PlanningRunPageSummary`数据契约，约束组件属性或接口响应字段。 */
export interface PlanningRunPageSummary {
  total: number;
  queued: number;
  running: number;
  approval_required: number;
  completed: number;
  failed: number;
  cancelled: number;
  superseded: number;
  active: number;
}

/** 定义`PlanningRunPage`数据契约，约束组件属性或接口响应字段。 */
export interface PlanningRunPage {
  items: PlanningRun[];
  total: number;
  page: number;
  page_size: number;
  summary: PlanningRunPageSummary;
}

/** 定义`PlanningRunEvidence`数据契约，约束组件属性或接口响应字段。 */
export interface PlanningRunEvidence {
  evidence_id: string;
  topics: string[];
  source_name: string | null;
  source_row: number | null;
  source_id: string | null;
  content: string;
  metadata_json: Record<string, unknown>;
  quality_status: "verified" | "warning" | "blocked" | null;
  observed_at: string | null;
  retrieval_score: number | null;
  vector_score: number | null;
  is_canonical: boolean;
  duplicate_review_ids: string[];
  available: boolean;
}

/** 定义`PlanningRunEvidencePage`数据契约，约束组件属性或接口响应字段。 */
export interface PlanningRunEvidencePage {
  items: PlanningRunEvidence[];
  total: number;
  page: number;
  page_size: number;
  unavailable_total: number;
}

/** 定义`ValidationGateStatus`允许的状态或联合类型，避免跨模块使用任意字符串。 */
export type ValidationGateStatus = "ready" | "pending" | "blocked";

/** 定义`ValidationGateUpdate`数据契约，约束组件属性或接口响应字段。 */
export interface ValidationGateUpdate {
  gate_id: string;
  status: ValidationGateStatus;
  note?: string;
}

/** 定义`ApprovalAction`允许的状态或联合类型，避免跨模块使用任意字符串。 */
export type ApprovalAction = "approved" | "rejected" | "revision_required";

/** 定义`ApprovalTask`数据契约，约束组件属性或接口响应字段。 */
export interface ApprovalTask {
  id: string;
  project_id: string;
  run_id: string;
  approval_type: string;
  status: string;
  checkpoint_ref: string;
  summary: Record<string, unknown>;
  decision?: Record<string, unknown>;
  decision_request_id?: string;
  decision_payload_hash?: string;
  assignee_id?: string;
  due_at?: string;
  decided_by?: string;
  decided_at?: string;
  created_at: string;
  updated_at: string;
}

/** 定义`ApprovalTaskPageSummary`数据契约，约束组件属性或接口响应字段。 */
export interface ApprovalTaskPageSummary {
  total: number;
  pending: number;
  approved: number;
  rejected: number;
  revision_required: number;
  cancelled: number;
  processed: number;
  overdue: number;
  due_soon: number;
  mine_pending: number;
  unassigned_pending: number;
}

/** 定义`ApprovalProjectOption`数据契约，约束组件属性或接口响应字段。 */
export interface ApprovalProjectOption {
  value: string;
  label: string;
}

/** 定义`ApprovalTaskPage`数据契约，约束组件属性或接口响应字段。 */
export interface ApprovalTaskPage {
  items: ApprovalTask[];
  total: number;
  page: number;
  page_size: number;
  summary: ApprovalTaskPageSummary;
  project_options: ApprovalProjectOption[];
}

/** 定义`ApprovalTaskPageParams`数据契约，约束组件属性或接口响应字段。 */
export interface ApprovalTaskPageParams {
  status?: "pending" | "overdue" | "processed" | "all";
  assignee?: "all" | "mine" | "unassigned";
  projectId?: string;
  page?: number;
  pageSize?: number;
}

/** 调用后端`listPlanningProjects`接口并返回类型化响应。 */
export async function listPlanningProjects(
  includeArchived = false,
): Promise<PlanningProject[]> {
  const response = await httpClient.get<PlanningProject[]>("/planning-projects", {
    params: includeArchived ? { include_archived: true } : undefined,
  });
  return response.data;
}

/** 调用后端`listPlanningProjectsPage`接口并返回类型化响应。 */
export async function listPlanningProjectsPage(
  params: PlanningProjectPageParams = {},
): Promise<PlanningProjectPage> {
  const response = await httpClient.get<PlanningProjectPage>("/planning-projects/page", {
    params: {
      archived_only: params.archivedOnly,
      status: params.status === "all" ? undefined : params.status,
      keyword: params.keyword?.trim() || undefined,
      project_id: params.projectId,
      page: params.page,
      page_size: params.pageSize,
    },
  });
  return response.data;
}

/** 调用后端`getPlanningProject`接口并返回类型化响应。 */
export async function getPlanningProject(projectId: string): Promise<PlanningProject> {
  const response = await httpClient.get<PlanningProject>(`/planning-projects/${projectId}`);
  return response.data;
}

/** 调用后端`createPlanningProject`接口并返回类型化响应。 */
export async function createPlanningProject(
  payload: PlanningProjectCreate,
): Promise<PlanningProject> {
  const response = await httpClient.post<PlanningProject>("/planning-projects", payload);
  return response.data;
}

/** 调用后端`updatePlanningProject`接口并返回类型化响应。 */
export async function updatePlanningProject(
  projectId: string,
  payload: PlanningProjectUpdate,
): Promise<PlanningProject> {
  const response = await httpClient.patch<PlanningProject>(
    `/planning-projects/${projectId}`,
    payload,
  );
  return response.data;
}

/** 调用后端`archivePlanningProject`接口并返回类型化响应。 */
export async function archivePlanningProject(projectId: string): Promise<PlanningProject> {
  const response = await httpClient.post<PlanningProject>(
    `/planning-projects/${projectId}/archive`,
  );
  return response.data;
}

/** 调用后端`restorePlanningProject`接口并返回类型化响应。 */
export async function restorePlanningProject(projectId: string): Promise<PlanningProject> {
  const response = await httpClient.post<PlanningProject>(
    `/planning-projects/${projectId}/restore`,
  );
  return response.data;
}

/** 调用后端`listProjectRuns`接口并返回类型化响应。 */
export async function listProjectRuns(projectId: string): Promise<PlanningRun[]> {
  const response = await httpClient.get<PlanningRun[]>(`/planning-projects/${projectId}/runs`);
  return response.data;
}

/** 调用后端`listProjectRunsPage`接口并返回类型化响应。 */
export async function listProjectRunsPage(
  projectId: string,
  page = 1,
  pageSize = 5,
): Promise<PlanningRunPage> {
  const response = await httpClient.get<PlanningRunPage>(
    `/planning-projects/${projectId}/runs/page`,
    { params: { page, page_size: pageSize } },
  );
  return response.data;
}

/** 调用后端`startProjectRun`接口并返回类型化响应。 */
export async function startProjectRun(projectId: string): Promise<PlanningRun> {
  const response = await httpClient.post<PlanningRun>(`/planning-projects/${projectId}/runs`);
  return response.data;
}

/** 调用后端`retryProjectRun`接口并返回类型化响应。 */
export async function retryProjectRun(projectId: string, runId: string): Promise<PlanningRun> {
  const response = await httpClient.post<PlanningRun>(
    `/planning-projects/${projectId}/runs/${runId}/retry`,
  );
  return response.data;
}

/** 调用后端`getProjectRun`接口并返回类型化响应。 */
export async function getProjectRun(projectId: string, runId: string): Promise<PlanningRun> {
  const response = await httpClient.get<PlanningRun>(
    `/planning-projects/${projectId}/runs/${runId}`,
  );
  return response.data;
}

/** 调用后端`updateRunValidationPlan`接口并返回类型化响应。 */
export async function updateRunValidationPlan(
  projectId: string,
  runId: string,
  candidateId: string,
  gates: ValidationGateUpdate[],
): Promise<PlanningRun> {
  const response = await httpClient.patch<PlanningRun>(
    `/planning-projects/${projectId}/runs/${runId}/validation-plan`,
    { candidate_id: candidateId, gates },
  );
  return response.data;
}

/** 调用后端`uploadRunValidationMaterial`接口并返回类型化响应。 */
export async function uploadRunValidationMaterial(
  projectId: string,
  runId: string,
  candidateId: string,
  gateId: string,
  file: File,
  note = "",
): Promise<PlanningRun> {
  const formData = new FormData();
  formData.append("candidate_id", candidateId);
  formData.append("gate_id", gateId);
  formData.append("note", note);
  formData.append("file", file);
  const response = await httpClient.post<PlanningRun>(
    `/planning-projects/${projectId}/runs/${runId}/validation-materials`,
    formData,
  );
  return response.data;
}

/** 调用后端`deleteRunValidationMaterial`接口并返回类型化响应。 */
export async function deleteRunValidationMaterial(
  projectId: string,
  runId: string,
  materialId: string,
): Promise<PlanningRun> {
  const response = await httpClient.delete<PlanningRun>(
    `/planning-projects/${projectId}/runs/${runId}/validation-materials/${materialId}`,
  );
  return response.data;
}

/** 调用后端`downloadRunValidationMaterial`接口并返回类型化响应。 */
export async function downloadRunValidationMaterial(
  projectId: string,
  runId: string,
  materialId: string,
): Promise<Blob> {
  const response = await httpClient.get<Blob>(
    `/planning-projects/${projectId}/runs/${runId}/validation-materials/${materialId}/download`,
    { responseType: "blob" },
  );
  return response.data;
}

/** 调用后端`getProjectRunEvents`接口并返回类型化响应。 */
export async function getProjectRunEvents(projectId: string, runId: string): Promise<RunEvent[]> {
  const response = await httpClient.get<RunEvent[]>(
    `/planning-projects/${projectId}/runs/${runId}/events`,
    { params: { limit: 200 } },
  );
  return response.data;
}

/** 调用后端`getProjectRunEvidence`接口并返回类型化响应。 */
export async function getProjectRunEvidence(
  projectId: string,
  runId: string,
): Promise<PlanningRunEvidence[]> {
  const response = await httpClient.get<PlanningRunEvidence[]>(
    `/planning-projects/${projectId}/runs/${runId}/evidence`,
  );
  return response.data;
}

/** 调用后端`listProjectRunEvidencePage`接口并返回类型化响应。 */
export async function listProjectRunEvidencePage(
  projectId: string,
  runId: string,
  page = 1,
  pageSize = 8,
): Promise<PlanningRunEvidencePage> {
  const response = await httpClient.get<PlanningRunEvidencePage>(
    `/planning-projects/${projectId}/runs/${runId}/evidence/page`,
    { params: { page, page_size: pageSize } },
  );
  return response.data;
}

/** 调用后端`listApprovalTasks`接口并返回类型化响应。 */
export async function listApprovalTasks(status?: string): Promise<ApprovalTask[]> {
  const response = await httpClient.get<ApprovalTask[]>("/approval-tasks", {
    params: status ? { status } : undefined,
  });
  return response.data;
}

/** 调用后端`listApprovalTasksPage`接口并返回类型化响应。 */
export async function listApprovalTasksPage(
  params: ApprovalTaskPageParams = {},
): Promise<ApprovalTaskPage> {
  const response = await httpClient.get<ApprovalTaskPage>("/approval-tasks/page", {
    params: {
      status: params.status,
      assignee: params.assignee === "all" ? undefined : params.assignee,
      project_id: params.projectId === "all" ? undefined : params.projectId,
      page: params.page,
      page_size: params.pageSize,
    },
  });
  return response.data;
}

/** 调用后端`getApprovalTask`接口并返回类型化响应。 */
export async function getApprovalTask(taskId: string): Promise<ApprovalTask> {
  const response = await httpClient.get<ApprovalTask>(`/approval-tasks/${taskId}`);
  return response.data;
}

/** 调用后端`claimApprovalTask`接口并返回类型化响应。 */
export async function claimApprovalTask(taskId: string): Promise<ApprovalTask> {
  const response = await httpClient.post<ApprovalTask>(`/approval-tasks/${taskId}/claim`);
  return response.data;
}

/** 调用后端`releaseApprovalTask`接口并返回类型化响应。 */
export async function releaseApprovalTask(taskId: string): Promise<ApprovalTask> {
  const response = await httpClient.post<ApprovalTask>(`/approval-tasks/${taskId}/release`);
  return response.data;
}

/** 调用后端`assignApprovalTask`接口并返回类型化响应。 */
export async function assignApprovalTask(
  taskId: string,
  assigneeId: string,
): Promise<ApprovalTask> {
  const response = await httpClient.post<ApprovalTask>(`/approval-tasks/${taskId}/assign`, {
    assignee_id: assigneeId,
  });
  return response.data;
}

/** 调用后端`decideApprovalTask`接口并返回类型化响应。 */
export async function decideApprovalTask(
  taskId: string,
  payload: { action: ApprovalAction; comment: string; changes: Record<string, unknown> },
  requestId: string,
): Promise<ApprovalTask> {
  const response = await httpClient.post<ApprovalTask>(
    `/approval-tasks/${taskId}/decision`,
    payload,
    { headers: { "Idempotency-Key": requestId } },
  );
  return response.data;
}
