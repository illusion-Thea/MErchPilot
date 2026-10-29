/**
 * 文件职责：声明数据导入、质量、重复审核和索引 API 契约。
 */

import { httpClient } from "@/lib/http/client";

/** 定义`DataImportJob`数据契约，约束组件属性或接口响应字段。 */
export interface DataImportJob {
  id: string;
  tenant_id: string;
  filename: string;
  source_type: string;
  status: "queued" | "processing" | "completed" | "failed";
  celery_task_id?: string;
  index_celery_task_id?: string;
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  indexable_rows: number;
  indexed_rows: number;
  pending_index_rows: number;
  failed_index_rows: number;
  retrieval_status: "ready" | "indexing" | "failed" | "empty" | "unavailable";
  retrieval_ready: boolean;
  error_message?: string;
  created_by: string;
  completed_at?: string;
  created_at: string;
  updated_at: string;
}

/** 定义`DataImportPageSummary`数据契约，约束组件属性或接口响应字段。 */
export interface DataImportPageSummary {
  total: number;
  queued: number;
  processing: number;
  completed: number;
  failed: number;
}

/** 定义`DataImportPage`数据契约，约束组件属性或接口响应字段。 */
export interface DataImportPage {
  items: DataImportJob[];
  total: number;
  page: number;
  page_size: number;
  summary: DataImportPageSummary;
}

/** 定义`DataImportPageParams`数据契约，约束组件属性或接口响应字段。 */
export interface DataImportPageParams {
  status?: string;
  keyword?: string;
  importId?: string;
  page?: number;
  pageSize?: number;
}

/** 定义`EvidenceQualityIssue`数据契约，约束组件属性或接口响应字段。 */
export interface EvidenceQualityIssue {
  field: string;
  code: string;
  message: string;
  severity: "error" | "warning";
}

/** 定义`EvidenceQualityStatus`允许的状态或联合类型，避免跨模块使用任意字符串。 */
export type EvidenceQualityStatus = "verified" | "warning" | "blocked";
/** 定义`EvidenceIndexStatus`允许的状态或联合类型，避免跨模块使用任意字符串。 */
export type EvidenceIndexStatus = "pending" | "indexing" | "indexed" | "failed";

/** 定义`EvidenceRecord`数据契约，约束组件属性或接口响应字段。 */
export interface EvidenceRecord {
  id: string;
  import_job_id?: string;
  source_type: string;
  source_name: string;
  source_row: number;
  source_id: string;
  content: string;
  metadata_json: Record<string, unknown>;
  quality_status: EvidenceQualityStatus;
  index_status: EvidenceIndexStatus;
  embedding_model_version?: string;
  observed_at?: string;
  created_at: string;
}

/** 定义`EvidenceRecordPage`数据契约，约束组件属性或接口响应字段。 */
export interface EvidenceRecordPage {
  items: EvidenceRecord[];
  total: number;
  page: number;
  page_size: number;
}

/** 定义`EvidenceRecordPageParams`数据契约，约束组件属性或接口响应字段。 */
export interface EvidenceRecordPageParams {
  qualityStatus?: EvidenceQualityStatus;
  indexStatus?: EvidenceIndexStatus;
  keyword?: string;
  page?: number;
  pageSize?: number;
}

/** 定义`DataImportQualityImport`数据契约，约束组件属性或接口响应字段。 */
export interface DataImportQualityImport {
  import_id: string;
  filename: string;
  created_at: string;
  warning_records: number;
  blocked_records: number;
  failed_index_records: number;
}

/** 定义`DataImportQualitySummary`数据契约，约束组件属性或接口响应字段。 */
export interface DataImportQualitySummary {
  total_imports: number;
  completed_imports: number;
  failed_imports: number;
  total_records: number;
  verified_records: number;
  warning_records: number;
  blocked_records: number;
  indexed_records: number;
  pending_index_records: number;
  failed_index_records: number;
  problem_import_total: number;
  problem_imports: DataImportQualityImport[];
}

/** 定义`DataImportReindexResult`数据契约，约束组件属性或接口响应字段。 */
export interface DataImportReindexResult {
  import_id: string;
  queued_records: number;
  task_id?: string;
}

/** 定义`EvidenceQualityReviewPayload`数据契约，约束组件属性或接口响应字段。 */
export interface EvidenceQualityReviewPayload {
  action: "verify" | "block";
  note?: string;
}

/** 定义`DataCoverage`数据契约，约束组件属性或接口响应字段。 */
export interface DataCoverage {
  total_records: number;
  verified_records: number;
  dated_records: number;
  source_id_records: number;
  date_coverage_rate: number;
  source_id_coverage_rate: number;
  data_type_counts: Record<string, number>;
  category_counts: Record<string, number>;
  target_market_counts: Record<string, number>;
}

/** 定义`DuplicateReviewDecision`允许的状态或联合类型，避免跨模块使用任意字符串。 */
export type DuplicateReviewDecision = "keep_all" | "select_canonical" | "dismissed";

/** 定义`DataDuplicateRecord`数据契约，约束组件属性或接口响应字段。 */
export interface DataDuplicateRecord {
  evidence_id: string;
  source_id: string;
  import_job_id: string | null;
  source_name: string;
  source_row: number;
  quality_status: "verified" | "warning" | "blocked";
  observed_at: string | null;
  content_preview: string;
}

/** 定义`DataDuplicateReview`数据契约，约束组件属性或接口响应字段。 */
export interface DataDuplicateReview {
  id: string;
  match_type: "source_id" | "content_hash";
  match_value: string;
  decision: DuplicateReviewDecision;
  canonical_evidence_id: string | null;
  notes: string | null;
  reviewed_by: string;
  reviewed_at: string;
  created_at: string;
  updated_at: string;
}

/** 定义`EvidenceQualityIssueSummaryItem`数据契约，约束组件属性或接口响应字段。 */
export interface EvidenceQualityIssueSummaryItem {
  code: string;
  field: string;
  message: string;
  severity: "error" | "warning" | string;
  count: number;
}

/** 定义`EvidenceQualityIssueSummary`数据契约，约束组件属性或接口响应字段。 */
export interface EvidenceQualityIssueSummary {
  total_records: number;
  verified_records: number;
  warning_records: number;
  blocked_records: number;
  failed_index_records: number;
  issues: EvidenceQualityIssueSummaryItem[];
}

/** 定义`DataDuplicateGroup`数据契约，约束组件属性或接口响应字段。 */
export interface DataDuplicateGroup {
  match_type: "source_id" | "content_hash";
  match_value: string;
  record_count: number;
  import_count: number;
  evidence_ids: string[];
  import_job_ids: string[];
  source_ids: string[];
  records: DataDuplicateRecord[];
  review: DataDuplicateReview | null;
}

/** 定义`DataDuplicateGroupSummary`数据契约，约束组件属性或接口响应字段。 */
export interface DataDuplicateGroupSummary {
  match_type: "source_id" | "content_hash";
  match_value: string;
  record_count: number;
  import_count: number;
  records: DataDuplicateRecord[];
  review: DataDuplicateReview | null;
}

/** 定义`DataDuplicateGroupPageSummary`数据契约，约束组件属性或接口响应字段。 */
export interface DataDuplicateGroupPageSummary {
  total: number;
  pending: number;
  reviewed: number;
}

/** 定义`DataDuplicateGroupPage`数据契约，约束组件属性或接口响应字段。 */
export interface DataDuplicateGroupPage {
  items: DataDuplicateGroupSummary[];
  total: number;
  page: number;
  page_size: number;
  summary: DataDuplicateGroupPageSummary;
}

/** 定义`DataDuplicateGroupRecordPage`数据契约，约束组件属性或接口响应字段。 */
export interface DataDuplicateGroupRecordPage {
  match_type: "source_id" | "content_hash";
  match_value: string;
  record_count: number;
  import_count: number;
  items: DataDuplicateRecord[];
  page: number;
  page_size: number;
  review: DataDuplicateReview | null;
  canonical_record: DataDuplicateRecord | null;
}

/** 定义`DataImportComparison`数据契约，约束组件属性或接口响应字段。 */
export interface DataImportComparison {
  base_import_id: string;
  target_import_id: string;
  base_records: number;
  target_records: number;
  base_unkeyed_count: number;
  target_unkeyed_count: number;
  added_count: number;
  removed_count: number;
  changed_count: number;
  unchanged_count: number;
  added_source_ids: string[];
  removed_source_ids: string[];
  changed_source_ids: string[];
  unchanged_source_ids: string[];
  base_coverage: DataCoverage;
  target_coverage: DataCoverage;
}

/** 调用后端`listDataImports`接口并返回类型化响应。 */
export async function listDataImports(): Promise<DataImportJob[]> {
  const response = await httpClient.get<DataImportJob[]>("/data-imports");
  return response.data;
}

/** 调用后端`listDataImportsPage`接口并返回类型化响应。 */
export async function listDataImportsPage(
  params: DataImportPageParams = {},
): Promise<DataImportPage> {
  const response = await httpClient.get<DataImportPage>("/data-imports/page", {
    params: {
      status: params.status === "all" ? undefined : params.status,
      keyword: params.keyword?.trim() || undefined,
      import_id: params.importId,
      page: params.page,
      page_size: params.pageSize,
    },
  });
  return response.data;
}

/** 调用后端`getDataImport`接口并返回类型化响应。 */
export async function getDataImport(importId: string): Promise<DataImportJob> {
  const response = await httpClient.get<DataImportJob>(`/data-imports/${importId}`);
  return response.data;
}

/** 调用后端`getDataImportQualitySummary`接口并返回类型化响应。 */
export async function getDataImportQualitySummary(): Promise<DataImportQualitySummary> {
  const response = await httpClient.get<DataImportQualitySummary>("/data-imports/quality-summary");
  return response.data;
}

/** 调用后端`getDataCoverage`接口并返回类型化响应。 */
export async function getDataCoverage(): Promise<DataCoverage> {
  const response = await httpClient.get<DataCoverage>("/data-imports/coverage");
  return response.data;
}

/** 调用后端`listDuplicateEvidenceGroups`接口并返回类型化响应。 */
export async function listDuplicateEvidenceGroups(): Promise<DataDuplicateGroup[]> {
  const response = await httpClient.get<DataDuplicateGroup[]>("/data-imports/duplicates");
  return response.data;
}

/** 调用后端`listDuplicateEvidenceGroupsPage`接口并返回类型化响应。 */
export async function listDuplicateEvidenceGroupsPage(
  status: "pending" | "reviewed" | "all" = "pending",
  page = 1,
  pageSize = 6,
): Promise<DataDuplicateGroupPage> {
  const response = await httpClient.get<DataDuplicateGroupPage>("/data-imports/duplicates/page", {
    params: { status, page, page_size: pageSize },
  });
  return response.data;
}

/** 调用后端`getDuplicateEvidenceGroup`接口并返回类型化响应。 */
export async function getDuplicateEvidenceGroup(
  matchType: DataDuplicateGroup["match_type"],
  matchValue: string,
  page = 1,
  pageSize = 20,
): Promise<DataDuplicateGroupRecordPage> {
  const response = await httpClient.get<DataDuplicateGroupRecordPage>(
    "/data-imports/duplicates/group",
    {
      params: {
        match_type: matchType,
        match_value: matchValue,
        page,
        page_size: pageSize,
      },
    },
  );
  return response.data;
}

/** 调用后端`reviewDuplicateEvidenceGroup`接口并返回类型化响应。 */
export async function reviewDuplicateEvidenceGroup(payload: {
  match_type: DataDuplicateGroup["match_type"];
  match_value: string;
  decision: DuplicateReviewDecision;
  canonical_evidence_id?: string;
  notes?: string;
}): Promise<DataDuplicateReview> {
  const response = await httpClient.put<DataDuplicateReview>(
    "/data-imports/duplicates/review",
    payload,
  );
  return response.data;
}

/** 调用后端`compareDataImports`接口并返回类型化响应。 */
export async function compareDataImports(
  baseImportId: string,
  targetImportId: string,
): Promise<DataImportComparison> {
  const response = await httpClient.get<DataImportComparison>(
    `/data-imports/${baseImportId}/compare/${targetImportId}`,
  );
  return response.data;
}

/** 调用后端通用文件导入接口并返回类型化响应。 */
export async function uploadDataFile(file: File): Promise<DataImportJob> {
  const payload = new FormData();
  payload.append("file", file);
  const response = await httpClient.post<DataImportJob>("/data-imports/files", payload);
  return response.data;
}

/** 兼容只上传表格的旧调用方。 */
export async function uploadTabularFile(file: File): Promise<DataImportJob> {
  const payload = new FormData();
  payload.append("file", file);
  const response = await httpClient.post<DataImportJob>("/data-imports/tabular", payload);
  return response.data;
}

/** 调用后端`listImportEvidence`接口并返回类型化响应。 */
export async function listImportEvidence(
  importId: string,
  filters?: {
    qualityStatus?: EvidenceQualityStatus;
    indexStatus?: EvidenceIndexStatus;
    keyword?: string;
    limit?: number;
  },
): Promise<EvidenceRecord[]> {
  const response = await httpClient.get<EvidenceRecord[]>(`/data-imports/${importId}/evidence`, {
    params: {
      quality_status: filters?.qualityStatus,
      index_status: filters?.indexStatus,
      keyword: filters?.keyword || undefined,
      limit: filters?.limit,
    },
  });
  return response.data;
}

/** 调用后端`listImportEvidencePage`接口并返回类型化响应。 */
export async function listImportEvidencePage(
  importId: string,
  filters?: EvidenceRecordPageParams,
): Promise<EvidenceRecordPage> {
  const response = await httpClient.get<EvidenceRecordPage>(
    `/data-imports/${importId}/evidence/page`,
    {
      params: {
        quality_status: filters?.qualityStatus,
        index_status: filters?.indexStatus,
        keyword: filters?.keyword || undefined,
        page: filters?.page,
        page_size: filters?.pageSize,
      },
    },
  );
  return response.data;
}

/** 调用后端`getImportQualityIssuesSummary`接口并返回类型化响应。 */
export async function getImportQualityIssuesSummary(
  importId: string,
): Promise<EvidenceQualityIssueSummary> {
  const response = await httpClient.get<EvidenceQualityIssueSummary>(
    `/data-imports/${importId}/quality-issues-summary`,
  );
  return response.data;
}

/** 调用后端`downloadDataCollectionTemplate`接口并返回类型化响应。 */
export async function downloadDataCollectionTemplate(): Promise<Blob> {
  const response = await httpClient.get<Blob>("/data-imports/template", {
    responseType: "blob",
  });
  return response.data;
}

/** 调用后端`retryDataImport`接口并返回类型化响应。 */
export async function retryDataImport(importId: string): Promise<DataImportJob> {
  const response = await httpClient.post<DataImportJob>(`/data-imports/${importId}/retry`);
  return response.data;
}

/** 调用后端`reindexDataImport`接口并返回类型化响应。 */
export async function reindexDataImport(importId: string): Promise<DataImportReindexResult> {
  const response = await httpClient.post<DataImportReindexResult>(
    `/data-imports/${importId}/reindex`,
  );
  return response.data;
}

/** 调用后端`reviewImportEvidence`接口并返回类型化响应。 */
export async function reviewImportEvidence(
  importId: string,
  evidenceId: string,
  payload: EvidenceQualityReviewPayload,
): Promise<EvidenceRecord> {
  const response = await httpClient.patch<EvidenceRecord>(
    `/data-imports/${importId}/evidence/${evidenceId}/quality-review`,
    payload,
  );
  return response.data;
}

/** 调用后端`withdrawDataImport`接口并返回类型化响应。 */
export async function withdrawDataImport(importId: string): Promise<void> {
  await httpClient.delete(`/data-imports/${importId}`);
}

/** 调用后端`downloadImportQualityReport`接口并返回类型化响应。 */
export async function downloadImportQualityReport(importId: string): Promise<Blob> {
  const response = await httpClient.get<Blob>(`/data-imports/${importId}/quality-report`, {
    responseType: "blob",
  });
  return response.data;
}
