/**
 * 文件职责：声明系统健康与依赖服务状态 API 契约。
 */

import { httpClient } from "@/lib/http/client";
import { getRuntimeApiBaseUrl } from "@/lib/runtime-config";

/** 定义`SystemReadiness`数据契约，约束组件属性或接口响应字段。 */
export interface SystemReadiness {
  status: "ok" | "degraded";
  integration_status?: "ok" | "degraded";
  components: Record<string, boolean>;
  core_components?: Record<string, boolean>;
  optional_components?: Record<string, boolean>;
  integration_components?: Record<string, boolean>;
  provider_modes?: Record<string, string>;
}

/** 调用后端`getSystemReadiness`接口并返回类型化响应。 */
export async function getSystemReadiness(): Promise<SystemReadiness> {
  const apiBaseUrl = getRuntimeApiBaseUrl();
  const apiOrigin = apiBaseUrl.replace(/\/api\/v1\/?$/, "");
  const response = await httpClient.get<SystemReadiness>("/health/ready", {
    baseURL: apiOrigin,
    timeout: 5_000,
  });
  return response.data;
}
