/**
 * 文件职责：封装 Axios 基础地址、身份请求头和统一业务错误解析。
 */

import axios, { AxiosError, InternalAxiosRequestConfig } from "axios";

import { getRuntimeApiBaseUrl } from "@/lib/runtime-config";

/** 定义`ApiErrorPayload`数据契约，约束组件属性或接口响应字段。 */
export interface ApiErrorPayload {
  detail?: string;
  code?: string;
}

/** 生成请求追踪 ID，兼容 HTTP 局域网环境中不可用的 randomUUID。 */
function createRequestId(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }

  if (typeof globalThis.crypto?.getRandomValues === "function") {
    const randomBytes = new Uint8Array(16);
    globalThis.crypto.getRandomValues(randomBytes);
    return Array.from(randomBytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  }

  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/** 统一Axios基础地址、超时、身份请求头和响应错误处理。 */
export const httpClient = axios.create({
  baseURL: getRuntimeApiBaseUrl(),
  timeout: 30_000,
});

httpClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  if (typeof window !== "undefined") {
    const token = window.localStorage.getItem("merchpilot_access_token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  }
  config.headers["X-Request-ID"] = createRequestId();
  return config;
});

httpClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiErrorPayload>) => {
    const message = error.response?.data?.detail ?? error.message ?? "请求失败";
    return Promise.reject(new Error(message));
  },
);
