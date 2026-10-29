/**
 * 文件职责：声明 FastMCP 集成中心 API 契约。
 */

import { httpClient } from "@/lib/http/client";

/** 定义`McpTool`数据契约，约束组件属性或接口响应字段。 */
export interface McpTool {
  name: string;
  title: string;
  description: string;
  tags: string[];
  read_only: boolean;
  destructive: boolean;
  idempotent: boolean;
  required_fields: string[];
  max_page_size: number | null;
}

/** 定义`McpIntegration`数据契约，约束组件属性或接口响应字段。 */
export interface McpIntegration {
  status: "ready" | "degraded" | "unavailable";
  health_ready: boolean;
  authenticated: boolean;
  service_name: string;
  service_version: string;
  protocol_version: string;
  endpoint: string;
  auth_mode: string;
  user_id: string;
  tenant_id: string;
  roles: string[];
  tools: McpTool[];
  total: number;
  read_only_total: number;
  controlled_write_total: number;
  page: number;
  page_size: number;
  client_configuration: Record<string, unknown>;
  error: string | null;
}

/** 定义`McpVerification`数据契约，约束组件属性或接口响应字段。 */
export interface McpVerification {
  status: "verified";
  verified_at: string;
  tool_name: string;
  user_id: string;
  tenant_id: string;
  roles: string[];
  project_total: number;
  active_project_total: number;
  pending_approval_total: number;
  selected_product_total: number;
  active_initiative_total: number;
}

/** 定义`McpActivity`数据契约，约束组件属性或接口响应字段。 */
export interface McpActivity {
  id: string;
  activity_type: "mcp_created" | "mcp_started" | "mcp_approval_claimed" | "mcp_approval_decided" | "mcp_validation_updated" | "mcp_launch_review_submitted";
  request_id: string;
  actor_id: string;
  project_id: string;
  project_name: string;
  category: string;
  target_market: string;
  project_status: string;
  created_at: string;
  project_created_by: string;
  project_created_at: string;
  mcp_creation_request_id: string | null;
  mcp_creation_actor_id: string | null;
  mcp_created_at: string | null;
  latest_start_request_id: string | null;
  latest_start_actor_id: string | null;
  latest_start_at: string | null;
  latest_run_id: string | null;
  latest_run_status: string | null;
  latest_approval_request_id: string | null;
  latest_approval_actor_id: string | null;
  latest_approval_at: string | null;
  latest_approval_task_id: string | null;
  latest_approval_event: string | null;
  latest_approval_status: string | null;
  latest_validation_request_id: string | null;
  latest_validation_actor_id: string | null;
  latest_validation_at: string | null;
  latest_validation_run_id: string | null;
  latest_validation_candidate_id: string | null;
  latest_validation_gate_ids: string[];
  latest_validation_status: string | null;
  latest_validation_completion_rate: number | null;
  latest_launch_review_request_id: string | null;
  latest_launch_review_actor_id: string | null;
  latest_launch_review_at: string | null;
  latest_launch_review_initiative_id: string | null;
  latest_launch_review_initiative_name: string | null;
  latest_launch_review_id: string | null;
  latest_launch_review_status: string | null;
  latest_launch_review_readiness_status: string | null;
}

/** 定义`McpActivityPage`数据契约，约束组件属性或接口响应字段。 */
export interface McpActivityPage {
  items: McpActivity[];
  total: number;
  page: number;
  page_size: number;
}

/** 调用后端`getMcpIntegration`接口并返回类型化响应。 */
export async function getMcpIntegration(page = 1, pageSize = 6): Promise<McpIntegration> {
  const response = await httpClient.get<McpIntegration>("/integrations/mcp", {
    params: { page, page_size: pageSize },
  });
  return response.data;
}

/** 调用后端`verifyMcpIntegration`接口并返回类型化响应。 */
export async function verifyMcpIntegration(): Promise<McpVerification> {
  const response = await httpClient.post<McpVerification>("/integrations/mcp/verify");
  return response.data;
}

/** 调用后端`getMcpActivities`接口并返回类型化响应。 */
export async function getMcpActivities(page = 1, pageSize = 5): Promise<McpActivityPage> {
  const response = await httpClient.get<McpActivityPage>("/integrations/mcp/activities", {
    params: { page, page_size: pageSize },
  });
  return response.data;
}
