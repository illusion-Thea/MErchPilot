/**
 * 文件职责：声明异步任务查询 API 类型与调用方法。
 */

import { httpClient } from "@/lib/http/client";

/** 定义`AsyncTaskStatus`数据契约，约束组件属性或接口响应字段。 */
export interface AsyncTaskStatus {
  task_id: string;
  state: string;
  state_label: string;
  ready: boolean;
  terminal: boolean;
  resource_type: "planning_run" | "data_import" | "planning_report";
  resource_id: string;
}

/** 调用后端`getAsyncTaskStatuses`接口并返回类型化响应。 */
export async function getAsyncTaskStatuses(taskIds: string[]): Promise<AsyncTaskStatus[]> {
  const normalizedTaskIds = [...new Set(taskIds.filter(Boolean))];
  if (normalizedTaskIds.length === 0) {
    return [];
  }
  const response = await httpClient.get<AsyncTaskStatus[]>("/async-tasks/status", {
    params: { task_ids: normalizedTaskIds.join(",") },
  });
  return response.data;
}
