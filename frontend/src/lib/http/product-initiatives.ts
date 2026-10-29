/**
 * 文件职责：声明商品立项、里程碑、试销和上市评审 API 契约。
 */

import type { AuditEvent } from "@/lib/http/audit";
import { httpClient } from "@/lib/http/client";

/** 定义`ProductInitiativeStatus`允许的状态或联合类型，避免跨模块使用任意字符串。 */
export type ProductInitiativeStatus =
  | "in_progress"
  | "launch_ready"
  | "launched"
  | "paused"
  | "cancelled";

/** 定义`ProductMilestoneStatus`允许的状态或联合类型，避免跨模块使用任意字符串。 */
export type ProductMilestoneStatus = "pending" | "in_progress" | "completed" | "blocked";

/** 定义`ProductMilestone`数据契约，约束组件属性或接口响应字段。 */
export interface ProductMilestone {
  id: string;
  label: string;
  status: ProductMilestoneStatus;
  owner_id?: string;
  due_date?: string;
  note?: string;
  updated_by?: string;
  updated_at?: string;
}

/** 定义`ProductInitiative`数据契约，约束组件属性或接口响应字段。 */
export interface ProductInitiative {
  id: string;
  tenant_id: string;
  selected_product_id: string;
  project_id: string;
  run_id: string;
  name: string;
  category: string;
  target_market: string;
  status: ProductInitiativeStatus;
  owner_id?: string;
  target_launch_date?: string;
  budget?: number;
  milestones: ProductMilestone[];
  notes?: string;
  created_by: string;
  launched_at?: string;
  created_at: string;
  updated_at: string;
}

/** 定义`ProductInitiativePageSummary`数据契约，约束组件属性或接口响应字段。 */
export interface ProductInitiativePageSummary {
  total: number;
  active: number;
  attention: number;
  ready: number;
  launched: number;
}

/** 定义`ProductInitiativePage`数据契约，约束组件属性或接口响应字段。 */
export interface ProductInitiativePage {
  items: ProductInitiative[];
  total: number;
  page: number;
  page_size: number;
  summary: ProductInitiativePageSummary;
}

/** 定义`ProductInitiativePageParams`数据契约，约束组件属性或接口响应字段。 */
export interface ProductInitiativePageParams {
  status?: string;
  keyword?: string;
  initiativeId?: string;
  projectId?: string;
  page?: number;
  pageSize?: number;
}

/** 定义`ProductInitiativeCreate`数据契约，约束组件属性或接口响应字段。 */
export interface ProductInitiativeCreate {
  selected_product_id: string;
  owner_id?: string | null;
  target_launch_date?: string | null;
  budget?: number | null;
  notes?: string | null;
}

/** 定义`ProductInitiativeUpdate`数据契约，约束组件属性或接口响应字段。 */
export interface ProductInitiativeUpdate {
  status?: "in_progress" | "launched" | "paused" | "cancelled";
  owner_id?: string | null;
  target_launch_date?: string | null;
  budget?: number | null;
  notes?: string | null;
}

/** 定义`ProductMilestoneUpdate`数据契约，约束组件属性或接口响应字段。 */
export interface ProductMilestoneUpdate {
  status?: ProductMilestoneStatus;
  owner_id?: string | null;
  due_date?: string | null;
  note?: string | null;
}

/** 定义`PilotSaleRecord`数据契约，约束组件属性或接口响应字段。 */
export interface PilotSaleRecord {
  id: string;
  initiative_id: string;
  period_start: string;
  period_end: string;
  channel: string;
  visitors: number;
  orders: number;
  units_sold: number;
  revenue: number;
  product_cost: number;
  marketing_spend: number;
  refunds_amount: number;
  return_count: number;
  rating?: number;
  notes?: string;
  conversion_rate?: number;
  return_rate?: number;
  average_order_value?: number;
  gross_profit: number;
  actual_margin_rate?: number;
  marketing_roi?: number;
  created_by: string;
  created_at: string;
  updated_at: string;
}

/** 定义`PilotSalePage`数据契约，约束组件属性或接口响应字段。 */
export interface PilotSalePage {
  items: PilotSaleRecord[];
  total: number;
  page: number;
  page_size: number;
}

/** 定义`ProductInitiativeTimelinePage`数据契约，约束组件属性或接口响应字段。 */
export interface ProductInitiativeTimelinePage {
  items: AuditEvent[];
  total: number;
  page: number;
  page_size: number;
}

/** 定义`PilotSaleCreate`允许的状态或联合类型，避免跨模块使用任意字符串。 */
export type PilotSaleCreate = Omit<
  PilotSaleRecord,
  | "id"
  | "initiative_id"
  | "conversion_rate"
  | "return_rate"
  | "average_order_value"
  | "gross_profit"
  | "actual_margin_rate"
  | "marketing_roi"
  | "created_by"
  | "created_at"
  | "updated_at"
>;

/** 定义`PilotSaleSummary`数据契约，约束组件属性或接口响应字段。 */
export interface PilotSaleSummary {
  record_count: number;
  visitors: number;
  orders: number;
  units_sold: number;
  revenue: number;
  product_cost: number;
  marketing_spend: number;
  refunds_amount: number;
  return_count: number;
  conversion_rate?: number;
  return_rate?: number;
  average_order_value?: number;
  gross_profit: number;
  actual_margin_rate?: number;
  marketing_roi?: number;
  average_rating?: number;
  planned_margin_rate?: number;
  margin_gap?: number;
  assessment_status: "insufficient" | "recommended" | "review" | "blocked";
  assessment_label: string;
  risks: string[];
  recommendations: string[];
}

/** 定义`PilotSaleTrendPoint`数据契约，约束组件属性或接口响应字段。 */
export interface PilotSaleTrendPoint {
  label: string;
  period_start: string;
  period_end: string;
  channel: string;
  visitors: number;
  orders: number;
  units_sold: number;
  revenue: number;
  gross_profit: number;
  conversion_rate?: number;
  return_rate?: number;
  actual_margin_rate?: number;
}

/** 定义`PilotSaleTrend`数据契约，约束组件属性或接口响应字段。 */
export interface PilotSaleTrend {
  periods: PilotSaleTrendPoint[];
  channels: PilotSaleTrendPoint[];
  period_total: number;
  channel_total: number;
}

/** 定义`ProductLaunchReadinessCheckStatus`允许的状态或联合类型，避免跨模块使用任意字符串。 */
export type ProductLaunchReadinessCheckStatus = "passed" | "pending" | "warning" | "blocked";

/** 定义`ProductLaunchReadinessCheck`数据契约，约束组件属性或接口响应字段。 */
export interface ProductLaunchReadinessCheck {
  id: string;
  label: string;
  status: ProductLaunchReadinessCheckStatus;
  detail: string;
}

/** 定义`ProductLaunchReadiness`数据契约，约束组件属性或接口响应字段。 */
export interface ProductLaunchReadiness {
  readiness_status: "ready" | "review" | "blocked";
  readiness_label: string;
  checks: ProductLaunchReadinessCheck[];
  blockers: string[];
  warnings: string[];
  recommendations: string[];
}

/** 定义`ProductLaunchReviewStatus`允许的状态或联合类型，避免跨模块使用任意字符串。 */
export type ProductLaunchReviewStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "revision_required";

/** 定义`ProductLaunchReview`数据契约，约束组件属性或接口响应字段。 */
export interface ProductLaunchReview {
  id: string;
  tenant_id: string;
  initiative_id: string;
  initiative_name?: string;
  project_id?: string;
  category?: string;
  target_market?: string;
  status: ProductLaunchReviewStatus;
  submission_note?: string;
  decision_note?: string;
  readiness_snapshot: ProductLaunchReadiness;
  submitted_by: string;
  submitted_at: string;
  decided_by?: string;
  decided_at?: string;
  created_at: string;
  updated_at: string;
}

/** 定义`ProductLaunchReviewPageSummary`数据契约，约束组件属性或接口响应字段。 */
export interface ProductLaunchReviewPageSummary {
  total: number;
  pending: number;
  approved: number;
  rejected: number;
  revision_required: number;
  processed: number;
}

/** 定义`ProductLaunchReviewPage`数据契约，约束组件属性或接口响应字段。 */
export interface ProductLaunchReviewPage {
  items: ProductLaunchReview[];
  total: number;
  page: number;
  page_size: number;
  summary: ProductLaunchReviewPageSummary;
}

/** 定义`ProductLaunchReviewSubmit`数据契约，约束组件属性或接口响应字段。 */
export interface ProductLaunchReviewSubmit {
  submission_note?: string | null;
}

/** 调用后端`listProductInitiatives`接口并返回类型化响应。 */
export async function listProductInitiatives(): Promise<ProductInitiative[]> {
  const response = await httpClient.get<ProductInitiative[]>("/product-initiatives");
  return response.data;
}

/** 调用后端`listProductInitiativesPage`接口并返回类型化响应。 */
export async function listProductInitiativesPage(
  params: ProductInitiativePageParams = {},
): Promise<ProductInitiativePage> {
  const response = await httpClient.get<ProductInitiativePage>("/product-initiatives/page", {
    params: {
      status: params.status === "all" ? undefined : params.status,
      keyword: params.keyword?.trim() || undefined,
      initiative_id: params.initiativeId,
      project_id: params.projectId,
      page: params.page,
      page_size: params.pageSize,
    },
  });
  return response.data;
}

/** 调用后端`getProductInitiative`接口并返回类型化响应。 */
export async function getProductInitiative(initiativeId: string): Promise<ProductInitiative> {
  const response = await httpClient.get<ProductInitiative>(`/product-initiatives/${initiativeId}`);
  return response.data;
}

/** 调用后端`createProductInitiative`接口并返回类型化响应。 */
export async function createProductInitiative(
  payload: ProductInitiativeCreate,
): Promise<ProductInitiative> {
  const response = await httpClient.post<ProductInitiative>("/product-initiatives", payload);
  return response.data;
}

/** 调用后端`updateProductInitiative`接口并返回类型化响应。 */
export async function updateProductInitiative(
  initiativeId: string,
  payload: ProductInitiativeUpdate,
): Promise<ProductInitiative> {
  const response = await httpClient.patch<ProductInitiative>(
    `/product-initiatives/${initiativeId}`,
    payload,
  );
  return response.data;
}

/** 调用后端`updateProductMilestone`接口并返回类型化响应。 */
export async function updateProductMilestone(
  initiativeId: string,
  milestoneId: string,
  payload: ProductMilestoneUpdate,
): Promise<ProductInitiative> {
  const response = await httpClient.patch<ProductInitiative>(
    `/product-initiatives/${initiativeId}/milestones/${milestoneId}`,
    payload,
  );
  return response.data;
}

/** 调用后端`listProductInitiativeTimeline`接口并返回类型化响应。 */
export async function listProductInitiativeTimeline(
  initiativeId: string,
): Promise<AuditEvent[]> {
  const response = await httpClient.get<AuditEvent[]>(
    `/product-initiatives/${initiativeId}/timeline`,
  );
  return response.data;
}

/** 调用后端`listProductInitiativeTimelinePage`接口并返回类型化响应。 */
export async function listProductInitiativeTimelinePage(
  initiativeId: string,
  page = 1,
  pageSize = 8,
): Promise<ProductInitiativeTimelinePage> {
  const response = await httpClient.get<ProductInitiativeTimelinePage>(
    `/product-initiatives/${initiativeId}/timeline/page`,
    { params: { page, page_size: pageSize } },
  );
  return response.data;
}

/** 调用后端`listPilotSales`接口并返回类型化响应。 */
export async function listPilotSales(initiativeId: string): Promise<PilotSaleRecord[]> {
  const response = await httpClient.get<PilotSaleRecord[]>(
    `/product-initiatives/${initiativeId}/pilot-sales`,
  );
  return response.data;
}

/** 调用后端`listPilotSalesPage`接口并返回类型化响应。 */
export async function listPilotSalesPage(
  initiativeId: string,
  page = 1,
  pageSize = 5,
): Promise<PilotSalePage> {
  const response = await httpClient.get<PilotSalePage>(
    `/product-initiatives/${initiativeId}/pilot-sales/page`,
    { params: { page, page_size: pageSize } },
  );
  return response.data;
}

/** 调用后端`createPilotSale`接口并返回类型化响应。 */
export async function createPilotSale(
  initiativeId: string,
  payload: PilotSaleCreate,
): Promise<PilotSaleRecord> {
  const response = await httpClient.post<PilotSaleRecord>(
    `/product-initiatives/${initiativeId}/pilot-sales`,
    payload,
  );
  return response.data;
}

/** 调用后端`updatePilotSale`接口并返回类型化响应。 */
export async function updatePilotSale(
  initiativeId: string,
  recordId: string,
  payload: Partial<PilotSaleCreate>,
): Promise<PilotSaleRecord> {
  const response = await httpClient.patch<PilotSaleRecord>(
    `/product-initiatives/${initiativeId}/pilot-sales/${recordId}`,
    payload,
  );
  return response.data;
}

/** 调用后端`getPilotSalesSummary`接口并返回类型化响应。 */
export async function getPilotSalesSummary(initiativeId: string): Promise<PilotSaleSummary> {
  const response = await httpClient.get<PilotSaleSummary>(
    `/product-initiatives/${initiativeId}/pilot-sales-summary`,
  );
  return response.data;
}

/** 调用后端`getPilotSalesTrend`接口并返回类型化响应。 */
export async function getPilotSalesTrend(initiativeId: string): Promise<PilotSaleTrend> {
  const response = await httpClient.get<PilotSaleTrend>(
    `/product-initiatives/${initiativeId}/pilot-sales-trend`,
  );
  return response.data;
}

/** 调用后端`getProductLaunchReadiness`接口并返回类型化响应。 */
export async function getProductLaunchReadiness(
  initiativeId: string,
): Promise<ProductLaunchReadiness> {
  const response = await httpClient.get<ProductLaunchReadiness>(
    `/product-initiatives/${initiativeId}/launch-readiness`,
  );
  return response.data;
}

/** 调用后端`listProductLaunchReviews`接口并返回类型化响应。 */
export async function listProductLaunchReviews(
  initiativeId: string,
): Promise<ProductLaunchReview[]> {
  const response = await httpClient.get<ProductLaunchReview[]>(
    `/product-initiatives/${initiativeId}/launch-reviews`,
  );
  return response.data;
}

/** 调用后端`listTenantProductLaunchReviews`接口并返回类型化响应。 */
export async function listTenantProductLaunchReviews(
  status?: ProductLaunchReviewStatus,
): Promise<ProductLaunchReview[]> {
  const response = await httpClient.get<ProductLaunchReview[]>(
    "/product-initiatives/launch-reviews",
    { params: status ? { status } : undefined },
  );
  return response.data;
}

/** 调用后端`listTenantProductLaunchReviewsPage`接口并返回类型化响应。 */
export async function listTenantProductLaunchReviewsPage(
  status?: "pending" | "processed" | "all",
  page = 1,
  pageSize = 5,
  initiativeId?: string,
  projectId?: string,
): Promise<ProductLaunchReviewPage> {
  const response = await httpClient.get<ProductLaunchReviewPage>(
    "/product-initiatives/launch-reviews/page",
    {
      params: {
        status: status === "all" ? undefined : status,
        initiative_id: initiativeId,
        project_id: projectId,
        page,
        page_size: pageSize,
      },
    },
  );
  return response.data;
}

/** 调用后端`getTenantProductLaunchReview`接口并返回类型化响应。 */
export async function getTenantProductLaunchReview(reviewId: string): Promise<ProductLaunchReview> {
  const response = await httpClient.get<ProductLaunchReview>(
    `/product-initiatives/launch-reviews/${reviewId}`,
  );
  return response.data;
}

/** 调用后端`submitProductLaunchReview`接口并返回类型化响应。 */
export async function submitProductLaunchReview(
  initiativeId: string,
  payload: ProductLaunchReviewSubmit,
): Promise<ProductLaunchReview> {
  const response = await httpClient.post<ProductLaunchReview>(
    `/product-initiatives/${initiativeId}/launch-reviews`,
    payload,
  );
  return response.data;
}

/** 调用后端`decideProductLaunchReview`接口并返回类型化响应。 */
export async function decideProductLaunchReview(
  initiativeId: string,
  reviewId: string,
  payload: { action: "approved" | "rejected" | "revision_required"; decision_note: string },
): Promise<ProductLaunchReview> {
  const response = await httpClient.post<ProductLaunchReview>(
    `/product-initiatives/${initiativeId}/launch-reviews/${reviewId}/decision`,
    payload,
  );
  return response.data;
}
