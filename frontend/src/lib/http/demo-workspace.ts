/**
 * 文件职责：声明本地演示工作区 API 契约，并封装查询与幂等初始化请求。
 */

import { httpClient } from "@/lib/http/client";

/** 定义演示项目所处的业务阶段。 */
export type DemoScenario = "planning_approval" | "validation" | "launch_review" | "launched";

/** 描述一条可从驾驶舱直接打开的演示业务主线。 */
export interface LocalDemoProject {
  project_id: string;
  project_name: string;
  category: string;
  target_market: string;
  scenario: DemoScenario;
  scenario_label: string;
  recommended_module: "approval" | "selection" | "initiative";
  run_id: string;
  approval_task_id?: string;
  selected_product_id?: string;
  initiative_id?: string;
  launch_review_id?: string;
}

/** 返回当前租户演示数据是否就绪及全部可导航实体。 */
export interface LocalDemoWorkspace {
  enabled: boolean;
  created: boolean;
  tenant_id: string;
  evidence_count: number;
  indexed_evidence_count: number;
  failed_evidence_count: number;
  index_status: "pending" | "indexing" | "indexed" | "failed";
  index_task_id?: string;
  primary_project_id: string;
  projects: LocalDemoProject[];
  message: string;
}

/** 查询演示工作区；未初始化时后端返回 null。 */
export async function getLocalDemoWorkspace(): Promise<LocalDemoWorkspace | null> {
  const response = await httpClient.get<LocalDemoWorkspace | null>("/demo-workspace");
  return response.data;
}

/** 幂等创建或修复演示工作区，不删除当前租户已有业务数据。 */
export async function createLocalDemoWorkspace(): Promise<LocalDemoWorkspace> {
  const response = await httpClient.post<LocalDemoWorkspace>("/demo-workspace");
  return response.data;
}
