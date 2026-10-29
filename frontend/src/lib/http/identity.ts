/**
 * 文件职责：承载 identity 模块的实现与类型定义。
 */

import { httpClient } from "@/lib/http/client";

/** 定义`CurrentIdentity`数据契约，约束组件属性或接口响应字段。 */
export interface CurrentIdentity {
  user_id: string;
  tenant_id: string;
  roles: string[];
  auth_mode: string;
  local_profiles?: string[];
}

/** 定义`ACCESS_TOKEN_STORAGE_KEY`客户端契约或共享常量。 */
export const ACCESS_TOKEN_STORAGE_KEY = "merchpilot_access_token";

/** 调用后端`getStoredAccessToken`接口并返回类型化响应。 */
export function getStoredAccessToken(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY) ?? "";
}

/** 调用后端`isLocalProfileAccessToken`接口并返回类型化响应。 */
export function isLocalProfileAccessToken(): boolean {
  return getStoredAccessToken().startsWith("local-profile:");
}

/** 调用后端`getCurrentIdentity`接口并返回类型化响应。 */
export async function getCurrentIdentity(): Promise<CurrentIdentity> {
  const response = await httpClient.get<CurrentIdentity>("/auth/me");
  return response.data;
}

/** 调用后端`setAccessToken`接口并返回类型化响应。 */
export function setAccessToken(token: string): void {
  if (typeof window === "undefined") return;
  if (token) {
    window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, token);
  } else {
    window.localStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY);
  }
}
