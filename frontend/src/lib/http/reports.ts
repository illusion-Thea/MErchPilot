/**
 * 文件职责：声明规划报告生成和下载 API 契约。
 */

import { httpClient } from "@/lib/http/client";

/** 定义`PlanningReport`数据契约，约束组件属性或接口响应字段。 */
export interface PlanningReport {
  id: string;
  project_id: string;
  run_id: string;
  format: string;
  status: "queued" | "processing" | "completed" | "failed";
  celery_task_id?: string;
  storage_key?: string;
  error_message?: string;
  created_by: string;
  completed_at?: string;
  created_at: string;
  updated_at: string;
}

/** 定义`PlanningReportPage`数据契约，约束组件属性或接口响应字段。 */
export interface PlanningReportPage {
  items: PlanningReport[];
  total: number;
  page: number;
  page_size: number;
}

/** 调用后端`createPlanningReport`接口并返回类型化响应。 */
export async function createPlanningReport(
  projectId: string,
  runId: string,
): Promise<PlanningReport> {
  const response = await httpClient.post<PlanningReport>(
    `/planning-projects/${projectId}/runs/${runId}/reports`,
  );
  return response.data;
}

/** 调用后端`listPlanningReports`接口并返回类型化响应。 */
export async function listPlanningReports(
  projectId: string,
  runId: string,
): Promise<PlanningReport[]> {
  const response = await httpClient.get<PlanningReport[]>(
    `/planning-projects/${projectId}/runs/${runId}/reports`,
  );
  return response.data;
}

/** 调用后端`listPlanningReportsPage`接口并返回类型化响应。 */
export async function listPlanningReportsPage(
  projectId: string,
  runId: string,
  page = 1,
  pageSize = 5,
): Promise<PlanningReportPage> {
  const response = await httpClient.get<PlanningReportPage>(
    `/planning-projects/${projectId}/runs/${runId}/reports/page`,
    { params: { page, page_size: pageSize } },
  );
  return response.data;
}

/** 调用后端`getPlanningReport`接口并返回类型化响应。 */
export async function getPlanningReport(reportId: string): Promise<PlanningReport> {
  const response = await httpClient.get<PlanningReport>(`/planning-reports/${reportId}`);
  return response.data;
}

/** 调用后端`downloadPlanningReport`接口并返回类型化响应。 */
export async function downloadPlanningReport(
  reportId: string,
): Promise<{ blob: Blob; filename: string }> {
  const response = await httpClient.get<Blob>(`/planning-reports/${reportId}/download`, {
    responseType: "blob",
  });
  const disposition = response.headers["content-disposition"] as string | undefined;
  const encodedFilename = disposition?.match(/filename\*=utf-8''([^;]+)/i)?.[1];
  const quotedFilename = disposition?.match(/filename="([^"]+)"/i)?.[1];
  return {
    blob: response.data,
    filename: encodedFilename
      ? decodeURIComponent(encodedFilename)
      : quotedFilename ?? `MerchPilot_${reportId}.xlsx`,
  };
}
