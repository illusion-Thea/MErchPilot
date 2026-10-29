/**
 * 文件职责：声明审计时间线 API 类型与调用方法。
 */

import { httpClient } from "@/lib/http/client";

/** 定义`AuditEvent`数据契约，约束组件属性或接口响应字段。 */
export interface AuditEvent {
  id: string;
  tenant_id: string;
  project_id?: string;
  actor_id: string;
  action: string;
  entity_type: string;
  entity_id: string;
  detail: Record<string, unknown>;
  occurred_at: string;
}

/** 调用后端`listAuditEvents`接口并返回类型化响应。 */
export async function listAuditEvents(params?: {
  project_id?: string;
  entity_type?: string;
  action?: string;
  limit?: number;
  offset?: number;
}): Promise<AuditEvent[]> {
  const response = await httpClient.get<AuditEvent[]>("/audit-events", { params });
  return response.data;
}

/** 调用后端`listAuditEventsPage`接口并返回类型化响应。 */
export async function listAuditEventsPage(params: {
  project_id?: string;
  entity_type?: string;
  action?: string;
  limit: number;
  offset: number;
}): Promise<{ items: AuditEvent[]; total: number }> {
  const response = await httpClient.get<AuditEvent[]>("/audit-events", { params });
  const headerValue = response.headers["x-total-count"];
  const total = Number.parseInt(typeof headerValue === "string" ? headerValue : "", 10);
  return {
    items: response.data,
    total: Number.isFinite(total) ? total : response.data.length,
  };
}
