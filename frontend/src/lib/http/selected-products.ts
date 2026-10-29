/**
 * 文件职责：声明正式选品、验证材料和时间线 API 契约。
 */

import { httpClient } from "@/lib/http/client";
import type { AuditEvent } from "@/lib/http/audit";

/** 定义`SelectedProductStatus`允许的状态或联合类型，避免跨模块使用任意字符串。 */
export type SelectedProductStatus =
  | "selected"
  | "validating"
  | "ready"
  | "initiated"
  | "launched"
  | "paused"
  | "cancelled";

/** 定义`SelectedProduct`数据契约，约束组件属性或接口响应字段。 */
export interface SelectedProduct {
  id: string;
  tenant_id: string;
  project_id: string;
  run_id: string;
  approval_task_id?: string;
  candidate_id: string;
  name: string;
  project_name: string;
  category: string;
  target_market: string;
  positioning?: string;
  status: SelectedProductStatus;
  owner_id?: string;
  score?: number;
  selling_price?: number;
  margin_rate?: number;
  estimated_profit?: number;
  supplier_name?: string;
  validation_status?: string;
  selection_snapshot: Record<string, unknown>;
  notes?: string;
  selected_by: string;
  selected_at: string;
  created_at: string;
  updated_at: string;
}

/** 定义`SelectedProductUpdate`数据契约，约束组件属性或接口响应字段。 */
export interface SelectedProductUpdate {
  status?: SelectedProductStatus;
  owner_id?: string | null;
  notes?: string | null;
}

/** 定义`SelectedProductPageSummary`数据契约，约束组件属性或接口响应字段。 */
export interface SelectedProductPageSummary {
  total: number;
  validating: number;
  ready: number;
  initiated: number;
  paused: number;
}

/** 定义`SelectedProductPage`数据契约，约束组件属性或接口响应字段。 */
export interface SelectedProductPage {
  items: SelectedProduct[];
  total: number;
  page: number;
  page_size: number;
  categories: string[];
  summary: SelectedProductPageSummary;
}

/** 定义`SelectedProductPageParams`数据契约，约束组件属性或接口响应字段。 */
export interface SelectedProductPageParams {
  status?: string;
  projectId?: string;
  category?: string;
  validationStatus?: string;
  keyword?: string;
  page?: number;
  pageSize?: number;
  selectedProductId?: string;
}

/** 定义`SelectedProductTimelinePage`数据契约，约束组件属性或接口响应字段。 */
export interface SelectedProductTimelinePage {
  items: AuditEvent[];
  total: number;
  page: number;
  page_size: number;
}

/** 调用后端`listSelectedProducts`接口并返回类型化响应。 */
export async function listSelectedProducts(status?: SelectedProductStatus): Promise<SelectedProduct[]> {
  const response = await httpClient.get<SelectedProduct[]>("/selected-products", {
    params: status ? { status } : undefined,
  });
  return response.data;
}

/** 调用后端`listSelectedProductsPage`接口并返回类型化响应。 */
export async function listSelectedProductsPage(
  params: SelectedProductPageParams = {},
): Promise<SelectedProductPage> {
  const response = await httpClient.get<SelectedProductPage>("/selected-products/page", {
    params: {
      status: params.status,
      project_id: params.projectId,
      category: params.category === "all" ? undefined : params.category,
      validation_status: params.validationStatus === "all" ? undefined : params.validationStatus,
      keyword: params.keyword?.trim() || undefined,
      page: params.page,
      page_size: params.pageSize,
      selected_product_id: params.selectedProductId,
    },
  });
  return response.data;
}

/** 调用后端单条正式选品接口，供跨模块精准定位时补全项目上下文。 */
export async function getSelectedProduct(selectedProductId: string): Promise<SelectedProduct> {
  const response = await httpClient.get<SelectedProduct>(
    `/selected-products/${selectedProductId}`,
  );
  return response.data;
}

/** 调用后端`updateSelectedProduct`接口并返回类型化响应。 */
export async function updateSelectedProduct(
  selectedProductId: string,
  payload: SelectedProductUpdate,
): Promise<SelectedProduct> {
  const response = await httpClient.patch<SelectedProduct>(
    `/selected-products/${selectedProductId}`,
    payload,
  );
  return response.data;
}

/** 调用后端`listSelectedProductTimeline`接口并返回类型化响应。 */
export async function listSelectedProductTimeline(
  selectedProductId: string,
): Promise<AuditEvent[]> {
  const response = await httpClient.get<AuditEvent[]>(
    `/selected-products/${selectedProductId}/timeline`,
  );
  return response.data;
}

/** 调用后端`listSelectedProductTimelinePage`接口并返回类型化响应。 */
export async function listSelectedProductTimelinePage(
  selectedProductId: string,
  page = 1,
  pageSize = 8,
): Promise<SelectedProductTimelinePage> {
  const response = await httpClient.get<SelectedProductTimelinePage>(
    `/selected-products/${selectedProductId}/timeline/page`,
    { params: { page, page_size: pageSize } },
  );
  return response.data;
}
