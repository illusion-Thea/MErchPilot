/**
 * 文件职责：从用户视角汇总业务指标、待办和同项目闭环台账。
 */

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRightOutlined,
  CheckCircleFilled,
  DatabaseOutlined,
  FileSearchOutlined,
  LoadingOutlined,
  ProductOutlined,
  ProjectOutlined,
  ReloadOutlined,
  RocketOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import { Alert, Button, Input, Pagination, Progress, Segmented, Skeleton, Tag } from "antd";

import {
  DashboardSnapshot,
  getDashboardSnapshot,
  listProjectLifecyclesPage,
  OpportunitySummary,
  ProjectLifecycle,
  ProjectLifecyclePage,
  ProjectLifecycleSort,
  ProjectLifecycleStatus,
} from "@/lib/http/analytics";
import {
  DataImportQualitySummary,
  EvidenceIndexStatus,
  getDataImportQualitySummary,
} from "@/lib/http/data-imports";
import { ApprovalTask, PlanningProject } from "@/lib/http/planning";
import { SelectedProduct } from "@/lib/http/selected-products";
import {
  ProductInitiative,
  ProductMilestone,
  ProductLaunchReview,
} from "@/lib/http/product-initiatives";
import { BUSINESS_DATA_CHANGED_EVENT } from "@/lib/business-events";
import { useAppSelector } from "@/store/hooks";
import { hasAnyRole } from "@/store/identity-slice";

/** 定义`WorkflowState`允许的状态或联合类型，避免跨模块使用任意字符串。 */
type WorkflowState = "complete" | "current" | "waiting" | "error";
/** 定义`BusinessWorkItemTone`允许的状态或联合类型，避免跨模块使用任意字符串。 */
type BusinessWorkItemTone = "error" | "warning" | "info" | "success";
/** 定义`BusinessWorkItemIcon`允许的状态或联合类型，避免跨模块使用任意字符串。 */
type BusinessWorkItemIcon = "quality" | "approval" | "launch" | "validation" | "selection" | "initiative";

/** 定义`BusinessWorkItem`数据契约，约束组件属性或接口响应字段。 */
interface BusinessWorkItem {
  id: string;
  tone: BusinessWorkItemTone;
  icon: BusinessWorkItemIcon;
  title: string;
  description: string;
  action: string;
  target: string;
  focusId?: string;
}

/** 定义`OverviewNextAction`数据契约，约束组件属性或接口响应字段。 */
interface OverviewNextAction {
  title: string;
  description: string;
  button: string;
  target: string;
  actionable?: boolean;
  focusId?: string;
  focusRunId?: string;
  focusType?: "project" | "planning-approval" | "launch-review" | "selected-product" | "initiative-create" | "initiative";
}

/** 定义项目闭环动作所需的角色能力，避免页面向只读用户展示不可执行操作。 */
interface ProjectLifecycleAccess {
  canApprove: boolean;
  canManage: boolean;
}

/** 定义角色化后的闭环动作，统一按钮文案、实际跳转目标和可执行状态。 */
interface ProjectLifecycleActionPresentation {
  label: string;
  actionable: boolean;
  actionType: ProjectLifecycle["next_action_type"];
  actionId: string;
}

/** 定义`OverviewData`数据契约，约束组件属性或接口响应字段。 */
interface OverviewData {
  projects: PlanningProject[];
  approvals: ApprovalTask[];
  opportunities: OpportunitySummary[];
  selectedProducts: SelectedProduct[];
  initiatives: ProductInitiative[];
  launchReviews: ProductLaunchReview[];
  qualitySummary: DataImportQualitySummary | null;
  projectTotal: number;
  activeProjectTotal: number;
  completedProjectTotal: number;
  pendingApprovalCount: number;
  pendingLaunchReviewCount: number;
  selectedProductTotal: number;
  selectedProductValidating: number;
  selectedProductReady: number;
  activeInitiativeTotal: number;
  pendingIndexImportId?: string;
}

/** 定义`ScorePart`数据契约，约束组件属性或接口响应字段。 */
interface ScorePart {
  score: number;
  maxScore: number;
}

/** 定义`lifecyclePageSize`服务端分页每页数量，保持页面负载稳定。 */
const lifecyclePageSize = 3;
/** 定义`emptyLifecyclePage`初始状态，避免加载期间出现空值分支。 */
const emptyLifecyclePage: ProjectLifecyclePage = {
  items: [],
  total: 0,
  page: 1,
  page_size: lifecyclePageSize,
  summary: {
    total: 0,
    blocked: 0,
    waiting_human: 0,
    active: 0,
    complete: 0,
  },
};

/** 定义`lifecycleHealthPresentation`展示映射，集中维护状态文案、颜色或选项。 */
const lifecycleHealthPresentation = {
  on_track: { color: "processing", label: "推进正常" },
  attention: { color: "warning", label: "需要关注" },
  blocked: { color: "error", label: "存在阻断" },
  complete: { color: "success", label: "已完成闭环" },
} as const;

/** 定义`emptyData`初始状态，避免加载期间出现空值分支。 */
const emptyData: OverviewData = {
  projects: [],
  approvals: [],
  opportunities: [],
  selectedProducts: [],
  initiatives: [],
  launchReviews: [],
  qualitySummary: null,
  projectTotal: 0,
  activeProjectTotal: 0,
  completedProjectTotal: 0,
  pendingApprovalCount: 0,
  pendingLaunchReviewCount: 0,
  selectedProductTotal: 0,
  selectedProductValidating: 0,
  selectedProductReady: 0,
  activeInitiativeTotal: 0,
};

/** 定义`scoreLabels`展示映射，集中维护状态文案、颜色或选项。 */
const scoreLabels: Record<string, string> = {
  finance: "财务可行性",
  evidence: "证据充分度",
  supplier: "供应链可靠性",
  completeness: "方案完整度",
};

/** 定义`workflowDefinitions`展示映射，集中维护状态文案、颜色或选项。 */
const workflowDefinitions = [
  { key: "data", label: "数据准备", icon: <DatabaseOutlined /> },
  { key: "project", label: "建立规划", icon: <ProjectOutlined /> },
  { key: "agent", label: "Agent 分析", icon: <RobotOutlined /> },
  { key: "approval", label: "人工审批", icon: <SafetyCertificateOutlined /> },
  { key: "selection", label: "正式选品", icon: <ProductOutlined /> },
  { key: "initiative", label: "商品立项", icon: <RocketOutlined /> },
] as const;

/** 实现`scorePart`辅助逻辑，集中处理页面展示或状态转换规则。 */
function scorePart(value: unknown): ScorePart | undefined {
  if (!value || typeof value !== "object") return undefined;
  const record = value as Record<string, unknown>;
  if (
    typeof record.score !== "number" ||
    typeof record.max_score !== "number" ||
    record.max_score <= 0
  ) {
    return undefined;
  }
  return { score: record.score, maxScore: record.max_score };
}

/** 从并行请求结果中提取成功值，失败时保留调用方提供的回退数据。 */
function settledValue<T>(result: PromiseSettledResult<T>, fallback: T): T {
  return result.status === "fulfilled" ? result.value : fallback;
}

/** 实现`uniqueRecords`辅助逻辑，集中处理页面展示或状态转换规则。 */
function uniqueRecords<T extends { id: string }>(
  ...records: Array<T | null | undefined>
): T[] {
  return [...new Map(records.filter((record): record is T => Boolean(record)).map((record) => [record.id, record])).values()];
}

/** 实现`currentInitiativeMilestone`辅助逻辑，集中处理页面展示或状态转换规则。 */
function currentInitiativeMilestone(initiative?: ProductInitiative): ProductMilestone | undefined {
  if (!initiative) return undefined;
  return initiative.milestones.find((item) => item.status === "blocked")
    ?? initiative.milestones.find((item) => item.status === "in_progress")
    ?? initiative.milestones.find((item) => item.status === "pending")
    ?? initiative.milestones.at(-1);
}

/** 实现`initiativeMilestoneIsOverdue`辅助逻辑，集中处理页面展示或状态转换规则。 */
function initiativeMilestoneIsOverdue(milestone?: ProductMilestone): boolean {
  if (!milestone?.due_date || milestone.status === "completed") return false;
  const dueAt = new Date(milestone.due_date).getTime();
  return !Number.isNaN(dueAt) && dueAt < Date.now();
}

/** 把formatSyncTime相关原始值格式化为页面可读文本。 */
function formatSyncTime(value?: Date): string {
  if (!value) return "尚未同步";
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(value);
}

/** 把formatPercent相关原始值格式化为页面可读文本。 */
function formatPercent(value?: number): string {
  return typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "待计算";
}

/** 实现`supplierRiskLabel`辅助逻辑，集中处理页面展示或状态转换规则。 */
function supplierRiskLabel(value?: string): string {
  if (value === "low") return "低风险";
  if (value === "medium") return "中风险";
  if (value === "high") return "高风险";
  return "待评估";
}

/** 实现`scrollToSection`辅助逻辑，集中处理页面展示或状态转换规则。 */
function scrollToSection(sectionId: string) {
  document.getElementById(sectionId)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

/** 发送`focusDataImport`跨模块定位事件，并在目标模块加载后聚焦具体记录。 */
function focusDataImport(
  importId: string | undefined,
  focus: { qualityStatus?: "warning" | "blocked"; indexStatus?: EvidenceIndexStatus } = {},
) {
  window.setTimeout(() => {
    window.dispatchEvent(
      new CustomEvent("merchpilot:focus-import", {
        detail: { importId, ...focus },
      }),
    );
  }, 150);
}

/** 发送`focusApproval`跨模块定位事件，并在目标模块加载后聚焦具体记录。 */
function focusApproval(
  kind: "planning" | "launch-review",
  targetId?: string,
) {
  window.setTimeout(() => {
    window.dispatchEvent(
      new CustomEvent("merchpilot:focus-approval", {
        detail: {
          kind,
          ...(kind === "planning" ? { taskId: targetId } : { reviewId: targetId }),
        },
      }),
    );
  }, 150);
}

/** 发送`focusPlanningProject`跨模块定位事件，并在目标模块加载后聚焦具体记录。 */
function focusPlanningProject(projectId?: string, runId?: string) {
  if (!projectId) return;
  window.setTimeout(() => {
    window.dispatchEvent(
      new CustomEvent("merchpilot:focus-planning-project", {
        detail: { projectId, runId },
      }),
    );
  }, 150);
}

/** 发送`focusSelectedProducts`跨模块定位事件，并在目标模块加载后聚焦具体记录。 */
function focusSelectedProducts(validation: "pending" | "ready", productId?: string) {
  window.setTimeout(() => {
    window.dispatchEvent(
      new CustomEvent("merchpilot:focus-selected-products", {
        detail: { validation, productId },
      }),
    );
  }, 150);
}

/** 发送`focusInitiativeCreate`跨模块定位事件，并在目标模块加载后聚焦具体记录。 */
function focusInitiativeCreate(selectedProductId?: string) {
  window.setTimeout(() => {
    window.dispatchEvent(
      new CustomEvent("merchpilot:focus-initiative-create", {
        detail: { selectedProductId },
      }),
    );
  }, 150);
}

/** 发送`focusInitiative`跨模块定位事件，并在目标模块加载后聚焦具体记录。 */
function focusInitiative(initiativeId?: string) {
  if (!initiativeId) return;
  window.setTimeout(() => {
    window.dispatchEvent(
      new CustomEvent("merchpilot:focus-initiative", {
        detail: { initiativeId },
      }),
    );
  }, 150);
}

/** 根据身份能力转换闭环下一步，不能处理的角色仍可进入对应详情查看进展。 */
function projectLifecycleActionPresentation(
  item: ProjectLifecycle,
  access: ProjectLifecycleAccess,
): ProjectLifecycleActionPresentation {
  if (item.next_action_type === "planning-project") {
    return {
      label: access.canManage ? item.next_action_label : "查看规划详情",
      actionable: access.canManage,
      actionType: item.next_action_type,
      actionId: item.project_id,
    };
  }
  if (item.next_action_type === "planning-approval") {
    return {
      label: access.canApprove ? "处理规划审批" : "查看审批状态",
      actionable: access.canApprove,
      actionType: item.next_action_type,
      actionId: item.next_action_id,
    };
  }
  if (item.next_action_type === "selected-product") {
    return {
      label: access.canManage ? item.next_action_label : "查看选品验证",
      actionable: access.canManage,
      actionType: item.next_action_type,
      actionId: item.next_action_id,
    };
  }
  if (item.next_action_type === "initiative-create" && !access.canManage) {
    return {
      label: "查看待立项选品",
      actionable: false,
      actionType: "selected-product",
      actionId: item.selected_product_id ?? item.next_action_id,
    };
  }
  if (item.next_action_type === "initiative-create") {
    return {
      label: item.next_action_label,
      actionable: true,
      actionType: item.next_action_type,
      actionId: item.next_action_id,
    };
  }
  if (item.next_action_type === "launch-review") {
    return {
      label: access.canApprove ? "处理上市评审" : "查看上市评审",
      actionable: access.canApprove,
      actionType: item.next_action_type,
      actionId: item.next_action_id,
    };
  }
  return {
    label: access.canManage ? item.next_action_label : "查看上市推进",
    actionable: access.canManage,
    actionType: item.next_action_type,
    actionId: item.next_action_id,
  };
}

/** 根据角色化动作打开对应详情或处理入口。 */
function openProjectLifecycle(
  item: ProjectLifecycle,
  access: ProjectLifecycleAccess,
) {
  const action = projectLifecycleActionPresentation(item, access);
  if (action.actionType === "planning-project") {
    scrollToSection("planning-workspace");
    focusPlanningProject(item.project_id, item.run_id ?? undefined);
    return;
  }
  if (action.actionType === "planning-approval") {
    scrollToSection("approval-panel");
    focusApproval("planning", action.actionId);
    return;
  }
  if (action.actionType === "selected-product") {
    scrollToSection("selected-product-panel");
    focusSelectedProducts(item.validation_status === "ready" ? "ready" : "pending", action.actionId);
    return;
  }
  if (action.actionType === "initiative-create") {
    scrollToSection("product-initiative-panel");
    focusInitiativeCreate(action.actionId);
    return;
  }
  if (action.actionType === "launch-review") {
    scrollToSection("approval-panel");
    focusApproval("launch-review", action.actionId);
    return;
  }
  scrollToSection("product-initiative-panel");
  focusInitiative(action.actionId);
}

/** 从闭环阶段节点跳转到该项目对应的历史或当前业务记录。 */
function openProjectLifecycleStage(
  item: ProjectLifecycle,
  stage: ProjectLifecycle["stages"][number],
) {
  if (!stage.entity_id) return;
  if (stage.key === "project") {
    scrollToSection("planning-workspace");
    focusPlanningProject(item.project_id);
    return;
  }
  if (stage.key === "agent") {
    scrollToSection("planning-workspace");
    focusPlanningProject(item.project_id, stage.entity_id);
    return;
  }
  if (stage.key === "approval") {
    scrollToSection("approval-panel");
    focusApproval("planning", stage.entity_id);
    return;
  }
  if (stage.key === "selection" || stage.key === "validation") {
    scrollToSection("selected-product-panel");
    focusSelectedProducts(
      item.validation_status === "ready" ? "ready" : "pending",
      stage.entity_id,
    );
    return;
  }
  if (stage.key === "launch_review") {
    scrollToSection("approval-panel");
    focusApproval("launch-review", stage.entity_id);
    return;
  }
  scrollToSection("product-initiative-panel");
  focusInitiative(stage.entity_id);
}

/** 实现`projectLifecycleNextAction`辅助逻辑，集中处理页面展示或状态转换规则。 */
function projectLifecycleNextAction(
  item: ProjectLifecycle,
  access: ProjectLifecycleAccess,
): OverviewNextAction {
  const action = projectLifecycleActionPresentation(item, access);
  const base = {
    title: item.health === "blocked" && action.actionable
      ? `处理${item.stage_label}阻断`
      : item.health === "complete"
        ? "查看完整上市结果"
        : action.label,
    description: item.blockers[0]
      ?? (item.health === "complete"
        ? `“${item.project_name}”已完成从规划、审批、选品到上市的完整业务闭环。`
        : `“${item.project_name}”当前处于${item.stage_label}，闭环完成度 ${item.progress_percent}%。`),
    button: action.label,
    actionable: action.actionable,
    focusId: action.actionId,
    focusRunId: action.actionType === "planning-project" ? item.run_id ?? undefined : undefined,
  };
  if (action.actionType === "planning-project") {
    return { ...base, target: "planning-workspace", focusType: "project" };
  }
  if (action.actionType === "planning-approval") {
    return { ...base, target: "approval-panel", focusType: "planning-approval" };
  }
  if (action.actionType === "selected-product") {
    return { ...base, target: "selected-product-panel", focusType: "selected-product" };
  }
  if (action.actionType === "initiative-create") {
    return { ...base, target: "product-initiative-panel", focusType: "initiative-create" };
  }
  if (action.actionType === "launch-review") {
    return { ...base, target: "approval-panel", focusType: "launch-review" };
  }
  return { ...base, target: "product-initiative-panel", focusType: "initiative" };
}

/** 实现`projectLifecycleWorkflowState`辅助逻辑，集中处理页面展示或状态转换规则。 */
function projectLifecycleWorkflowState(
  stages: ProjectLifecycle["stages"],
): WorkflowState {
  if (stages.some((stage) => stage.status === "blocked")) return "error";
  if (stages.length > 0 && stages.every((stage) => stage.status === "complete")) {
    return "complete";
  }
  if (stages.some((stage) => stage.status === "current" || stage.status === "complete")) {
    return "current";
  }
  return "waiting";
}

/** 实现`projectLifecycleWorkflowDetail`辅助逻辑，集中处理页面展示或状态转换规则。 */
function projectLifecycleWorkflowDetail(
  stages: ProjectLifecycle["stages"],
): string {
  return stages.find((stage) => stage.status === "blocked")?.detail
    ?? stages.find((stage) => stage.status === "current")?.detail
    ?? stages.findLast((stage) => stage.status === "complete")?.detail
    ?? "等待前序完成";
}

/** 聚合首页指标、用户待办和同一项目的端到端闭环台账。 */
export function BusinessOverview() {
  const [data, setData] = useState<OverviewData>(emptyData);
  const [lifecycleData, setLifecycleData] = useState<ProjectLifecyclePage>(emptyLifecyclePage);
  const [primaryLifecycle, setPrimaryLifecycle] = useState<ProjectLifecycle>();
  const [lifecyclePage, setLifecyclePage] = useState(1);
  const [lifecycleSort, setLifecycleSort] = useState<ProjectLifecycleSort>("priority");
  const [lifecycleStatus, setLifecycleStatus] = useState<ProjectLifecycleStatus>("all");
  const [lifecycleKeywordInput, setLifecycleKeywordInput] = useState("");
  const [lifecycleKeyword, setLifecycleKeyword] = useState("");
  const [lifecycleLoading, setLifecycleLoading] = useState(true);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<Date>();
  const [error, setError] = useState<string>();
  const identity = useAppSelector((state) => state.identity.current);
  const canApprove = hasAnyRole(identity, ["admin", "approver"]);
  const canManage = hasAnyRole(identity, ["admin", "planner"]);
  const dashboardRequestRef = useRef(0);
  const manualRefreshRequestRef = useRef<number | undefined>(undefined);

  const refreshDashboard = useCallback(async (manual = false) => {
    if (!manual && manualRefreshRequestRef.current !== undefined) return;
    // 请求序号保证较慢的旧响应不会覆盖用户刚切换筛选后返回的新结果。
    const requestId = dashboardRequestRef.current + 1;
    dashboardRequestRef.current = requestId;
    if (manual) {
      manualRefreshRequestRef.current = requestId;
      setRefreshing(true);
    }
    try {
      const lifecycleRequest = listProjectLifecyclesPage(
        lifecyclePage,
        lifecyclePageSize,
        lifecycleKeyword || undefined,
        lifecycleSort,
        lifecycleStatus,
      );
      // 主叙事始终使用全局最高优先级项目，不随下方台账翻页或筛选而改变。
      const primaryLifecycleRequest = lifecyclePage === 1
        && lifecycleSort === "priority"
        && lifecycleStatus === "all"
        && !lifecycleKeyword
        ? lifecycleRequest
        : listProjectLifecyclesPage(1, 1, undefined, "priority", "all");
      // 部分接口失败时保留最近一次可用数据，避免首页因单个依赖短暂故障整体空白。
      const results = await Promise.allSettled([
        getDashboardSnapshot(),
        getDataImportQualitySummary(),
        lifecycleRequest,
        primaryLifecycleRequest,
      ]);
      if (requestId !== dashboardRequestRef.current) return;
      setData((current) => {
        const snapshot = settledValue<DashboardSnapshot | undefined>(results[0], undefined);
        const qualitySummary = settledValue(results[1], current.qualitySummary);
        if (!snapshot) {
          return { ...current, qualitySummary };
        }
        return {
          projects: uniqueRecords(snapshot.latest_project),
          approvals: uniqueRecords(snapshot.latest_approval),
          opportunities: snapshot.latest_opportunity ? [snapshot.latest_opportunity] : [],
          selectedProducts: uniqueRecords(
            snapshot.latest_selection,
            snapshot.latest_ready_selection,
            snapshot.latest_pending_selection,
          ),
          initiatives: uniqueRecords(
            snapshot.latest_initiative,
            snapshot.attention_initiative,
            snapshot.progress_initiative,
          ),
          launchReviews: uniqueRecords(snapshot.latest_launch_review),
          qualitySummary,
          projectTotal: snapshot.project_total,
          activeProjectTotal: snapshot.active_project_total,
          completedProjectTotal: snapshot.completed_project_total,
          pendingApprovalCount: snapshot.pending_approval_count,
          pendingLaunchReviewCount: snapshot.pending_launch_review_count,
          selectedProductTotal: snapshot.selected_product_total,
          selectedProductValidating: snapshot.selected_product_validating,
          selectedProductReady: snapshot.selected_product_ready,
          activeInitiativeTotal: snapshot.active_initiative_total,
          pendingIndexImportId: snapshot.pending_index_import_id ?? undefined,
        };
      });
      const lifecycleResult = settledValue<ProjectLifecyclePage | undefined>(
        results[2],
        undefined,
      );
      if (lifecycleResult) {
        setLifecycleData(lifecycleResult);
      }
      const primaryLifecycleResult = settledValue<ProjectLifecyclePage | undefined>(
        results[3],
        undefined,
      );
      if (primaryLifecycleResult) {
        setPrimaryLifecycle(primaryLifecycleResult.items[0]);
      }
      setLifecycleLoading(false);
      setError(
        results.some((result) => result.status === "rejected")
          ? "部分驾驶舱数据暂时无法刷新，已保留最近一次可用结果。"
          : undefined,
      );
      setLastUpdatedAt(new Date());
      setLoading(false);
    } finally {
      if (manual && manualRefreshRequestRef.current === requestId) {
        manualRefreshRequestRef.current = undefined;
        setRefreshing(false);
      }
    }
  }, [lifecycleKeyword, lifecyclePage, lifecycleSort, lifecycleStatus]);

  useEffect(() => {
    const initialLoad = window.setTimeout(() => void refreshDashboard(), 0);
    const timer = window.setInterval(() => void refreshDashboard(), 10_000);
    const handleBusinessDataChanged = () => void refreshDashboard();
    window.addEventListener(BUSINESS_DATA_CHANGED_EVENT, handleBusinessDataChanged);
    return () => {
      window.clearTimeout(initialLoad);
      window.clearInterval(timer);
      window.removeEventListener(BUSINESS_DATA_CHANGED_EVENT, handleBusinessDataChanged);
      dashboardRequestRef.current += 1;
      manualRefreshRequestRef.current = undefined;
    };
  }, [refreshDashboard]);

  const summary = useMemo(() => {
    const projects = [...data.projects].sort(
      (left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at),
    );
    const latestProject = projects[0];
    const opportunities = [...data.opportunities].sort(
      (left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at),
    );
    const latestOpportunity = opportunities.find((item) => item.project_id === latestProject?.id);
    const latestSelection = [...data.selectedProducts]
      .filter((item) => item.project_id === latestProject?.id)
      .sort((left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at))[0];
    const latestInitiative = [...data.initiatives]
      .filter((item) =>
        latestSelection
          ? item.selected_product_id === latestSelection.id
          : item.project_id === latestProject?.id,
      )
      .sort((left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at))[0];
    const latestInitiativeMilestone = currentInitiativeMilestone(latestInitiative);
    const parsedValidRows = data.qualitySummary?.verified_records ?? 0;
    const parsedInvalidRows = data.qualitySummary?.blocked_records ?? 0;
    const parsedTotalRows = parsedValidRows + parsedInvalidRows;
    const evidenceTotalRecords = data.qualitySummary?.total_records ?? parsedTotalRows;
    const verifiedEvidenceRecords = data.qualitySummary?.verified_records ?? parsedValidRows;
    const warningEvidenceRecords = data.qualitySummary?.warning_records ?? 0;
    const blockedEvidenceRecords = data.qualitySummary?.blocked_records ?? parsedInvalidRows;
    const completedProjects = data.completedProjectTotal;
    const hasData = evidenceTotalRecords > 0;
    const hasProject = Boolean(latestProject);
    const isDraft = latestProject?.status === "draft";
    const isFailed = latestProject?.status === "failed";
    const isCancelled = latestProject?.status === "cancelled";
    const projectEstablished = hasProject && !isDraft;
    const hasAnalysis = typeof latestOpportunity?.score === "number";
    const needsApproval = latestProject?.status === "approval_required";
    const isCompleted = latestProject?.status === "completed";
    const selectionIsComplete = Boolean(
      latestSelection
      && ["ready", "initiated", "launched", "paused", "cancelled"].includes(latestSelection.status),
    );
    const selectionIsCurrent = Boolean(latestSelection && !selectionIsComplete);
    const initiativeIsComplete = latestInitiative?.status === "launched";
    const initiativeIsCurrent = Boolean(
      latestInitiative
      && ["in_progress", "launch_ready"].includes(latestInitiative.status),
    ) || Boolean(latestSelection?.status === "ready" && !latestInitiative);

    const workflowStates: Record<(typeof workflowDefinitions)[number]["key"], WorkflowState> = {
      data: hasData ? "complete" : "current",
      project: isDraft ? "current" : hasProject ? "complete" : hasData ? "current" : "waiting",
      agent: isFailed ? "error" : hasAnalysis ? "complete" : projectEstablished ? "current" : "waiting",
      approval: isCompleted ? "complete" : needsApproval ? "current" : isCancelled ? "error" : "waiting",
      selection: selectionIsComplete ? "complete" : selectionIsCurrent ? "current" : isCompleted ? "current" : "waiting",
      initiative: ["paused", "cancelled"].includes(latestInitiative?.status ?? "")
        ? "error"
        : initiativeIsComplete
          ? "complete"
          : initiativeIsCurrent
            ? "current"
            : "waiting",
    };
    let nextAction: OverviewNextAction = {
      title: "导入第一批业务数据",
      description: "先准备市场、竞品、用户和供应链证据，Agent 才能形成可靠判断。",
      button: "去导入数据",
      target: "data-import-panel",
    };
    if (!hasData) {
      nextAction = {
        title: "导入第一批业务数据",
        description: "先准备市场、竞品、用户和供应链证据，Agent 才能形成可靠判断。",
        button: "去导入数据",
        target: "data-import-panel",
      };
    } else if (isFailed) {
      nextAction = {
        title: "检查失败运行并重新启动",
        description: "本次 Agent 运行没有完成，建议先查看错误原因，再调整参数或重新运行。",
        button: "去查看失败运行",
        target: "planning-workspace",
        focusId: latestProject?.id,
        focusType: "project",
      };
    } else if (isCancelled) {
      nextAction = {
        title: "修订参数后重新运行规划",
        description: "上一轮方案未通过审批，历史审批意见和参数差异已保留，可回到工作台调整后重新启动 Agent。",
        button: "去修订并重新运行",
        target: "planning-workspace",
        focusId: latestProject?.id,
        focusType: "project",
      };
    } else if (isDraft) {
      nextAction = {
        title: "启动商品规划 Agent",
        description: "项目参数已经保存，启动后系统会进入市场、用户、供应链和财务分析。",
        button: "去启动 Agent",
        target: "planning-workspace",
        focusId: latestProject?.id,
        focusType: "project",
      };
    } else if (hasData && !hasProject) {
      nextAction = {
        title: "创建商品规划项目",
        description: "数据已经可用，填写目标品类、市场和财务约束即可启动 Agent。",
        button: "去新建规划",
        target: "planning-workspace",
      };
    } else if (latestProject?.status === "running" || latestProject?.status === "queued") {
      nextAction = {
        title: "Agent 正在生成方案",
        description: "市场、用户、供应链和财务 Agent 正在协作，可进入工作区查看实时进度。",
        button: "查看运行进度",
        target: "planning-workspace",
        focusId: latestProject?.id,
        focusType: "project",
      };
    } else if (needsApproval) {
      nextAction = {
        title: `${data.pendingApprovalCount || 1} 项方案等待审批`,
        description: "Agent 分析已经完成，需要业务负责人确认后才能形成正式规划结果。",
        button: "去审批方案",
        target: "approval-panel",
        focusId: data.approvals[0]?.id,
        focusType: "planning-approval",
      };
    } else if (canApprove && data.pendingLaunchReviewCount > 0) {
      nextAction = {
        title: `${data.pendingLaunchReviewCount} 项上市准备评审待处理`,
        description: "商品立项已进入上市准备评审，请审批人员查看预检结果、风险项和提交说明。",
        button: "去处理上市评审",
        target: "approval-panel",
        focusId: data.launchReviews[0]?.id,
        focusType: "launch-review",
      };
    } else if (latestInitiative && latestInitiative.status === "launch_ready") {
      nextAction = {
        title: "商品立项已具备上市条件",
        description: "五个里程碑和试销准备已经满足要求，确认上市前请再核对最终商品信息。",
        button: canManage ? "去确认上市" : "查看上市准备",
        target: "product-initiative-panel",
        focusId: latestInitiative.id,
        focusType: "initiative",
      };
    } else if (latestInitiative && latestInitiative.status === "in_progress") {
      nextAction = {
        title: latestInitiativeMilestone
          ? `推进商品立项：${latestInitiativeMilestone.label}`
          : "查看商品立项推进",
        description: latestInitiativeMilestone?.status === "blocked"
          ? "当前里程碑存在阻断项，请进入商品立项详情处理后再继续。"
          : "商品已经进入落地阶段，请继续维护当前里程碑、负责人和试销数据。",
        button: "去处理商品立项",
        target: "product-initiative-panel",
        focusId: latestInitiative.id,
        focusType: "initiative",
      };
    } else if (latestSelection) {
      const canCreateInitiative = canManage && latestSelection.status === "ready";
      nextAction = {
        title: latestSelection.status === "ready" ? "正式选品已具备立项条件" : "推进正式选品落地验证",
        description: latestSelection.status === "ready"
          ? "方案已完成选品和验证，可进入商品立项、采购或上架准备阶段。"
          : "审批结果已进入正式选品池，请继续维护样品、成本、供应和负责人状态。",
        button: canCreateInitiative ? "去建立立项" : "查看正式选品",
        target: canCreateInitiative ? "product-initiative-panel" : "selected-product-panel",
        focusId: latestSelection.id,
        focusType: canCreateInitiative ? "initiative-create" : "selected-product",
      };
    } else if (isCompleted) {
      nextAction = {
        title: "确认正式选品结果",
        description: "当前规划已经完成，可核对完整证据链和报告，正式选品台账正在同步。",
        button: "查看完整方案",
        target: "planning-workspace",
        focusId: latestProject?.id,
        focusType: "project",
      };
    }

    const lifecycleStages = primaryLifecycle?.stages ?? [];
    const lifecycleStage = (key: ProjectLifecycle["stages"][number]["key"]) =>
      lifecycleStages.filter((stage) => stage.key === key);
    const selectionStages = lifecycleStages.filter((stage) =>
      stage.key === "selection" || stage.key === "validation"
    );
    const initiativeStages = lifecycleStages.filter((stage) =>
      stage.key === "initiative" || stage.key === "launch_review" || stage.key === "launched"
    );
    const authoritativeWorkflowStates: typeof workflowStates = primaryLifecycle
      ? {
          data: hasData ? "complete" : "current",
          project: projectLifecycleWorkflowState(lifecycleStage("project")),
          agent: projectLifecycleWorkflowState(lifecycleStage("agent")),
          approval: projectLifecycleWorkflowState(lifecycleStage("approval")),
          selection: projectLifecycleWorkflowState(selectionStages),
          initiative: projectLifecycleWorkflowState(initiativeStages),
        }
      : workflowStates;
    const workflowDetails: Record<(typeof workflowDefinitions)[number]["key"], string> = {
      data: hasData ? "可信业务证据已就绪" : "等待导入业务数据",
      project: primaryLifecycle
        ? projectLifecycleWorkflowDetail(lifecycleStage("project"))
        : hasData
          ? "创建商品规划项目"
          : "等待业务数据就绪",
      agent: projectLifecycleWorkflowDetail(lifecycleStage("agent")),
      approval: projectLifecycleWorkflowDetail(lifecycleStage("approval")),
      selection: projectLifecycleWorkflowDetail(selectionStages),
      initiative: projectLifecycleWorkflowDetail(initiativeStages),
    };
    const authoritativeCompletedStages = Object.values(authoritativeWorkflowStates)
      .filter((state) => state === "complete").length;
    if (hasData && primaryLifecycle) {
      nextAction = projectLifecycleNextAction(primaryLifecycle, { canApprove, canManage });
    }

    const scoreParts = Object.entries(latestOpportunity?.score_breakdown ?? {})
      .map(([key, value]) => ({ key, value: scorePart(value) }))
      .filter((item): item is { key: string; value: ScorePart } => Boolean(item.value));
    const weakestPart = [...scoreParts].sort(
      (left, right) =>
        left.value.score / left.value.maxScore - right.value.score / right.value.maxScore,
    )[0];
    const improvementSuggestion =
      weakestPart?.key === "evidence"
        ? "当前短板是证据充分度，建议继续补充竞品销量、用户评价和渠道趋势数据。"
        : weakestPart?.key === "finance"
          ? "当前短板是财务可行性，建议核对采购成本、平台费用和营销投入。"
          : weakestPart?.key === "supplier"
            ? "当前短板是供应链可靠性，建议补充供应商评级、MOQ 和交期数据。"
            : "继续补齐业务约束，可提升规划方案的完整度和可执行性。";
    const qualityIssueCount = data.qualitySummary
      ? data.qualitySummary.warning_records +
        data.qualitySummary.blocked_records +
        data.qualitySummary.failed_index_records
      : 0;
    const pendingIndexRecords = data.qualitySummary?.pending_index_records ?? 0;
    const qualityIssueTypes = data.qualitySummary
      ? [
          data.qualitySummary.failed_index_records > 0
            ? `索引失败 ${data.qualitySummary.failed_index_records.toLocaleString("zh-CN")} 条`
            : "",
          data.qualitySummary.blocked_records > 0
            ? `证据阻断 ${data.qualitySummary.blocked_records.toLocaleString("zh-CN")} 条`
            : "",
          data.qualitySummary.warning_records > 0
            ? `质量提醒 ${data.qualitySummary.warning_records.toLocaleString("zh-CN")} 条`
            : "",
        ].filter(Boolean).join("、")
      : "";
    const pendingValidationCount = data.selectedProductValidating;
    const pendingValidationProduct = data.selectedProducts.find(
      (product) =>
        ["selected", "validating"].includes(product.status) &&
        product.validation_status !== "ready",
    );
    const readySelectionCount = data.selectedProductReady;
    const activeInitiativeCount = data.activeInitiativeTotal;
    const readySelectionProduct = data.selectedProducts.find((product) => product.status === "ready");
    const initiativeCandidates = [...data.initiatives]
      .filter((initiative) => ["in_progress", "launch_ready"].includes(initiative.status))
      .sort((left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at));
    const attentionInitiative = initiativeCandidates.find((initiative) =>
      initiative.status === "launch_ready"
      || currentInitiativeMilestone(initiative)?.status === "blocked"
      || initiativeMilestoneIsOverdue(currentInitiativeMilestone(initiative)),
    );
    const progressInitiative = initiativeCandidates[0];
    const progressMilestone = currentInitiativeMilestone(progressInitiative);
    const workItems: BusinessWorkItem[] = [];

    if (qualityIssueCount > 0) {
      workItems.push({
        id: "data-quality",
        tone:
          data.qualitySummary?.failed_index_records || data.qualitySummary?.blocked_records
            ? "error"
            : "warning",
        icon: "quality",
        title: "处理数据质量问题",
        description: `涉及 ${data.qualitySummary?.problem_import_total ?? 0} 个导入批次：${qualityIssueTypes}，建议复核或重建索引。`,
        action: "去治理",
        target: "data-import-panel",
      });
    }
    if (pendingIndexRecords > 0) {
      workItems.push({
        id: "data-indexing",
        tone: "info",
        icon: "quality",
        title: "Milvus 证据索引处理中",
        description: `${pendingIndexRecords.toLocaleString("zh-CN")} 条证据正在写入检索索引，完成后才会被 Agent 稳定检索。`,
        action: "查看进度",
        target: "data-import-panel",
        focusId: data.pendingIndexImportId,
      });
    }
    if (data.pendingApprovalCount > 0) {
      workItems.push({
        id: "planning-approval",
        tone: "warning",
        icon: "approval",
        title: "处理方案审批",
        description: `${data.pendingApprovalCount} 项规划方案等待线上审批，审批结果会自动驱动后续流程。`,
        action: "去审批",
        target: "approval-panel",
        focusId: data.approvals[0]?.id,
      });
    }
    if (data.pendingLaunchReviewCount > 0) {
      workItems.push({
        id: "launch-review",
        tone: "info",
        icon: "launch",
        title: "处理上市准备评审",
        description: canApprove
          ? `${data.pendingLaunchReviewCount} 项立项已提交上市预检，请核对风险和准备度后处理。`
          : `${data.pendingLaunchReviewCount} 项立项已提交上市预检，等待审批人员处理。`,
        action: "去评审",
        target: "approval-panel",
        focusId: data.launchReviews[0]?.id,
      });
    }
    if (pendingValidationCount > 0) {
      workItems.push({
        id: "selected-product-validation",
        tone: "warning",
        icon: "validation",
        title: "推进正式选品验证",
        description: `${pendingValidationCount} 个正式选品仍需补齐样品、成本、供应或负责人信息。`,
        action: "去验证",
        target: "selected-product-panel",
        focusId: pendingValidationProduct?.id,
      });
    }
    if (readySelectionCount > 0) {
      workItems.push({
        id: "selected-product-ready",
        tone: "success",
        icon: "selection",
        title: "确认可立项选品",
        description: `${readySelectionCount} 个正式选品已通过验证，可继续进入商品立项流程。`,
        action: canManage ? "去立项" : "查看详情",
        target: canManage ? "product-initiative-panel" : "selected-product-panel",
        focusId:
          readySelectionCount === 1
            ? readySelectionProduct?.id
            : undefined,
      });
    }
    if (attentionInitiative) {
      const milestone = currentInitiativeMilestone(attentionInitiative);
      workItems.push({
        id: "initiative-progress",
        tone: attentionInitiative.status === "launch_ready" ? "success" : "error",
        icon: "initiative",
        title: attentionInitiative.status === "launch_ready"
          ? "商品立项已具备上市条件"
          : `商品立项需要处理：${milestone?.label ?? "当前里程碑"}`,
        description: attentionInitiative.status === "launch_ready"
          ? `${attentionInitiative.name} 的里程碑已完成，可进入商品立项中心确认上市。`
          : `${attentionInitiative.name} 的当前节点${milestone?.status === "blocked" ? "存在阻断" : "已逾期"}，请进入详情处理。`,
        action: "去处理",
        target: "product-initiative-panel",
        focusId: attentionInitiative.id,
      });
    } else if (progressInitiative && progressMilestone) {
      workItems.push({
        id: "initiative-progress",
        tone: "info",
        icon: "initiative",
        title: `推进商品立项：${progressMilestone.label}`,
        description: `${progressInitiative.name} 当前处于商品落地阶段，请继续维护里程碑和试销数据。`,
        action: "查看推进",
        target: "product-initiative-panel",
        focusId: progressInitiative.id,
      });
    }

    return {
      latestOpportunity,
      latestProject,
      latestSelection,
      latestInitiative,
      parsedValidRows,
      parsedInvalidRows,
      parsedTotalRows,
      evidenceTotalRecords,
      verifiedEvidenceRecords,
      warningEvidenceRecords,
      blockedEvidenceRecords,
      completedProjects,
      activeInitiativeCount,
      workflowStates: authoritativeWorkflowStates,
      workflowDetails,
      completedStages: authoritativeCompletedStages,
      primaryLifecycle,
      nextAction,
      scoreParts,
      improvementSuggestion,
      workItems,
      qualitySummary: data.qualitySummary,
    };
  }, [canApprove, canManage, data, primaryLifecycle]);

  if (loading) {
    return (
      <section className="business-overview business-overview-loading">
        <Skeleton active paragraph={{ rows: 6 }} />
      </section>
    );
  }

  const latestStatus = summary.primaryLifecycle
    ? {
        color: lifecycleHealthPresentation[summary.primaryLifecycle.health].color,
        label: `${summary.primaryLifecycle.stage_label} · ${lifecycleHealthPresentation[summary.primaryLifecycle.health].label}`,
      }
    : { color: "default", label: "尚未开始" };
  const score = summary.latestOpportunity?.score;
  const scoreColor = typeof score === "number" && score >= 80 ? "#00a870" : "#195bff";
  const qualityPercent = summary.evidenceTotalRecords
    ? Math.round((summary.verifiedEvidenceRecords / summary.evidenceTotalRecords) * 100)
    : 0;
  const qualitySummary = summary.qualitySummary;
  const pendingIndexRecords = qualitySummary?.pending_index_records ?? 0;
  const warningImport = qualitySummary?.problem_imports.find(
    (item) => item.warning_records > 0,
  );
  const blockedImport = qualitySummary?.problem_imports.find(
    (item) => item.blocked_records > 0,
  );
  const failedIndexImport = qualitySummary?.problem_imports.find(
    (item) => item.failed_index_records > 0,
  );
  const qualityProblemNames = qualitySummary?.problem_imports
    .slice(0, 2)
    .map((item) => item.filename)
    .join("、");
  const qualityProblemSuffix = qualitySummary && qualitySummary.problem_import_total > 2
    ? ` 等 ${qualitySummary.problem_import_total} 个批次`
    : "";
  const qualityAlertParts = qualitySummary
    ? [
        qualitySummary.failed_index_records > 0
          ? `${qualitySummary.failed_index_records.toLocaleString("zh-CN")} 条索引失败`
          : "",
        qualitySummary.blocked_records > 0
          ? `${qualitySummary.blocked_records.toLocaleString("zh-CN")} 条证据不可用`
          : "",
        qualitySummary.warning_records > 0
          ? `${qualitySummary.warning_records.toLocaleString("zh-CN")} 条质量需要注意`
          : "",
      ].filter(Boolean)
    : [];
  const qualityAlertImportId =
    failedIndexImport?.import_id ?? blockedImport?.import_id ?? warningImport?.import_id;
  const qualityAlertFocus = failedIndexImport
    ? { indexStatus: "failed" as const }
    : blockedImport
      ? { qualityStatus: "blocked" as const }
      : warningImport
        ? { qualityStatus: "warning" as const }
        : undefined;

  return (
    <section className="business-overview" id="business-overview">
      {error ? <Alert type="warning" showIcon title={error} closable /> : null}
      {qualitySummary &&
      (qualitySummary.warning_records > 0 ||
        qualitySummary.blocked_records > 0 ||
        qualitySummary.failed_index_records > 0) ? (
        <Alert
          type={
            qualitySummary.failed_index_records > 0 || qualitySummary.blocked_records > 0
              ? "error"
              : "warning"
          }
          showIcon
          title={
            `数据质量风险：${qualityAlertParts.join(" · ")}`
          }
          description={
            qualityProblemNames
              ? `主要涉及：${qualityProblemNames}${qualityProblemSuffix}。数据已保留在证据库中，建议进入明细继续处理。`
              : "部分证据缺少可定位的导入批次，请进入数据治理分析查看。"
          }
          action={
            <Button
              size="small"
              onClick={() => {
                scrollToSection("data-import-panel");
                if (qualityAlertFocus) {
                  focusDataImport(qualityAlertImportId, qualityAlertFocus);
                }
              }}
            >
              去处理
            </Button>
          }
        />
      ) : null}
      {pendingIndexRecords > 0 ? (
        <Alert
          type="info"
          showIcon
          title={`Milvus 索引处理中：${pendingIndexRecords.toLocaleString("zh-CN")} 条`}
          description="数据解析已经完成，向量索引仍在后台写入；索引完成后，Agent 才能稳定检索这些证据。"
          action={
            <Button size="small" onClick={() => scrollToSection("data-import-panel")}>
              查看进度
            </Button>
          }
        />
      ) : null}

      <section className="business-work-queue" aria-label="业务待办队列">
        <div className="business-work-queue-header">
          <div>
            <span className="business-section-kicker">WORK QUEUE</span>
            <h2>需要你处理的业务事项</h2>
            <p>按当前租户、角色和最新业务状态自动汇总，点击即可进入对应处理模块。</p>
          </div>
          <div className="business-work-queue-tools">
            <span className="business-sync-time">最近同步 {formatSyncTime(lastUpdatedAt)}</span>
            <Button
              size="small"
              icon={<ReloadOutlined />}
              loading={refreshing}
              onClick={() => void refreshDashboard(true)}
            >
              刷新驾驶舱
            </Button>
            <Tag color={summary.workItems.length > 0 ? "processing" : "success"}>
              {summary.workItems.length > 0 ? `${summary.workItems.length} 项待处理` : "当前已清空"}
            </Tag>
          </div>
        </div>
        <div className="business-work-queue-list">
          {summary.workItems.length > 0 ? summary.workItems.map((item) => (
              <button
                className={`business-work-item business-work-item-${item.tone}`}
                key={item.id}
                type="button"
                onClick={() => {
                  scrollToSection(item.target);
                  if (item.id === "data-quality" && qualityAlertFocus) {
                    focusDataImport(qualityAlertImportId, qualityAlertFocus);
                  }
                  if (item.id === "data-indexing") {
                    focusDataImport(item.focusId);
                  }
                  if (item.id === "planning-approval") {
                    focusApproval("planning", item.focusId);
                  }
                  if (item.id === "launch-review") {
                    focusApproval("launch-review", item.focusId);
                  }
                  if (item.id === "selected-product-validation") {
                    focusSelectedProducts("pending", item.focusId);
                  }
                  if (item.id === "selected-product-ready") {
                    if (item.target === "product-initiative-panel") {
                      focusInitiativeCreate(item.focusId);
                    } else {
                      focusSelectedProducts("ready", item.focusId);
                    }
                  }
                  if (item.id === "initiative-progress") {
                    focusInitiative(item.focusId);
                  }
                }}
              >
                <span className={`business-work-item-icon business-work-item-icon-${item.tone}`}>
                  {item.icon === "quality" ? <DatabaseOutlined /> : null}
                  {item.icon === "approval" ? <SafetyCertificateOutlined /> : null}
                  {item.icon === "launch" ? <FileSearchOutlined /> : null}
                  {item.icon === "validation" ? <ProductOutlined /> : null}
                  {item.icon === "selection" ? <CheckCircleFilled /> : null}
                  {item.icon === "initiative" ? <RocketOutlined /> : null}
                </span>
                <span className="business-work-item-copy">
                  <strong>{item.title}</strong>
                  <span>{item.description}</span>
                </span>
                <span className="business-work-item-action">
                  {item.action}
                  <ArrowRightOutlined />
                </span>
              </button>
            )) : (
              <div className="business-work-queue-empty">
                <CheckCircleFilled />
                <div>
                  <strong>当前没有需要立即处理的待办</strong>
                  <span>系统会持续监控数据治理、审批、验证和商品立项状态。</span>
                </div>
              </div>
            )}
        </div>
      </section>

      <div className="overview-hero">
        <div className="overview-hero-copy">
          <div className="overview-kicker">
            <span className="live-indicator" />
            实时业务驾驶舱
            <Tag color="blue">真实数据</Tag>
          </div>
          <h1>
            {summary.primaryLifecycle
              ? `“${summary.primaryLifecycle.project_name}”已推进到「${summary.primaryLifecycle.stage_label}」`
              : "从业务数据开始创建第一份商品规划"}
          </h1>
          <p>
            {summary.primaryLifecycle
              ? summary.primaryLifecycle.blockers[0]
                ?? `当前闭环完成度 ${summary.primaryLifecycle.progress_percent}%，下一步建议：${summary.nextAction.button}。`
              : summary.latestOpportunity && typeof score === "number"
              ? `${summary.latestOpportunity.project_name} 当前机会分 ${score}，预计毛利率 ${formatPercent(summary.latestOpportunity.margin_rate)}，已引用 ${summary.latestOpportunity.evidence_count} 条核心证据。`
              : "导入业务数据后，系统会自动组织多 Agent 分析、人工审批和规划结果输出。"}
          </p>
          <div className="overview-hero-actions">
            <Button
              type={summary.nextAction.actionable === false ? "default" : "primary"}
              size="large"
              icon={<ArrowRightOutlined />}
              onClick={() => {
                scrollToSection(summary.nextAction.target);
                if (summary.nextAction.focusType === "project") {
                  focusPlanningProject(summary.nextAction.focusId, summary.nextAction.focusRunId);
                }
                if (summary.nextAction.focusType === "planning-approval") {
                  focusApproval("planning", summary.nextAction.focusId);
                }
                if (summary.nextAction.focusType === "launch-review") {
                  focusApproval("launch-review", summary.nextAction.focusId);
                }
                if (summary.nextAction.focusType === "selected-product") {
                  focusSelectedProducts("pending", summary.nextAction.focusId);
                }
                if (summary.nextAction.focusType === "initiative-create") {
                  focusInitiativeCreate(summary.nextAction.focusId);
                }
                if (summary.nextAction.focusType === "initiative") {
                  focusInitiative(summary.nextAction.focusId);
                }
              }}
            >
              {summary.nextAction.button}
            </Button>
            <Button size="large" onClick={() => scrollToSection("opportunity-chart")}>
              查看机会对比
            </Button>
          </div>
        </div>

        <div className="next-action-card">
          <span>建议下一步</span>
          <strong>{summary.nextAction.title}</strong>
          <p>{summary.nextAction.description}</p>
          <div className="next-action-progress">
            <div>
              <span>当前流程</span>
              <b>{summary.completedStages}/{workflowDefinitions.length}</b>
            </div>
            <Progress
              percent={Math.round((summary.completedStages / workflowDefinitions.length) * 100)}
              showInfo={false}
              strokeColor="#ffffff"
              railColor="rgba(255,255,255,.18)"
            />
          </div>
        </div>
      </div>

      <div className="business-metrics-grid">
        <div className="business-metric">
          <div className="business-metric-icon blue"><DatabaseOutlined /></div>
          <div><span>可信业务证据</span><strong>{summary.verifiedEvidenceRecords.toLocaleString("zh-CN")}</strong><small>共 {summary.evidenceTotalRecords.toLocaleString("zh-CN")} 条证据已入库</small></div>
        </div>
        <div className="business-metric">
          <div className="business-metric-icon violet"><ProjectOutlined /></div>
          <div><span>商品规划项目</span><strong>{data.projectTotal}</strong><small>{summary.completedProjects} 个已形成正式结果</small></div>
        </div>
        <div className="business-metric">
          <div className="business-metric-icon orange"><SafetyCertificateOutlined /></div>
          <div>
            <span>待人工审批</span>
            <strong>{data.pendingApprovalCount + data.pendingLaunchReviewCount}</strong>
            <small>
              {data.pendingApprovalCount || data.pendingLaunchReviewCount
                ? `方案 ${data.pendingApprovalCount} 项 · 上市评审 ${data.pendingLaunchReviewCount} 项`
                : "审批队列已清空"}
            </small>
          </div>
        </div>
        <div className="business-metric">
          <div className="business-metric-icon green"><ProductOutlined /></div>
          <div><span>正式选品方案</span><strong>{data.selectedProductTotal}</strong><small>{data.selectedProductReady} 个已具备立项条件 · {summary.activeInitiativeCount} 个推进中或待上市</small></div>
        </div>
      </div>

      <section className="project-lifecycle-ledger" aria-label="项目闭环台账">
        <div className="project-lifecycle-header">
          <div>
            <span className="business-section-kicker">PROJECT LIFECYCLE</span>
            <h2>项目闭环台账</h2>
            <p>每张卡只串联同一个项目，从需求定义、Agent 分析、人工审批一直追踪到商品上市。</p>
          </div>
          <div className="project-lifecycle-header-tools">
            <Input.Search
              aria-label="搜索项目闭环台账"
              allowClear
              value={lifecycleKeywordInput}
              prefix={<SearchOutlined />}
              placeholder="搜索项目、品类或市场"
              enterButton="搜索"
              onChange={(event) => {
                setLifecycleKeywordInput(event.target.value);
                if (!event.target.value && lifecycleKeyword) {
                  setLifecycleLoading(true);
                  setLifecyclePage(1);
                  setLifecycleKeyword("");
                }
              }}
              onSearch={(value) => {
                const normalizedKeyword = value.trim();
                setLifecycleLoading(true);
                setLifecyclePage(1);
                setLifecycleKeywordInput(normalizedKeyword);
                if (normalizedKeyword === lifecycleKeyword) {
                  void refreshDashboard(true);
                  return;
                }
                setLifecycleKeyword(normalizedKeyword);
              }}
            />
            <Segmented<ProjectLifecycleSort>
              size="small"
              value={lifecycleSort}
              options={[
                { label: "待处理优先", value: "priority" },
                { label: "最近更新", value: "updated" },
              ]}
              onChange={(value) => {
                setLifecycleLoading(true);
                setLifecyclePage(1);
                setLifecycleSort(value);
              }}
            />
            <Tag color={lifecycleData.summary.total > 0 ? "processing" : "default"}>
              {lifecycleData.summary.total} 个项目
            </Tag>
          </div>
        </div>

        <div className="project-lifecycle-filters">
          <Segmented<ProjectLifecycleStatus>
            block
            value={lifecycleStatus}
            options={[
              { label: `全部 ${lifecycleData.summary.total}`, value: "all" },
              { label: `阻断 ${lifecycleData.summary.blocked}`, value: "blocked" },
              {
                label: `人工待办 ${lifecycleData.summary.waiting_human}`,
                value: "waiting_human",
              },
              { label: `推进中 ${lifecycleData.summary.active}`, value: "active" },
              { label: `已完成 ${lifecycleData.summary.complete}`, value: "complete" },
            ]}
            onChange={(value) => {
              setLifecycleLoading(true);
              setLifecyclePage(1);
              setLifecycleStatus(value);
            }}
          />
        </div>

        {lifecycleLoading ? (
          <Skeleton active paragraph={{ rows: 5 }} />
        ) : lifecycleData.items.length > 0 ? (
          <div className="project-lifecycle-list">
            {lifecycleData.items.map((item) => {
              const health = lifecycleHealthPresentation[item.health];
              const action = projectLifecycleActionPresentation(item, { canApprove, canManage });
              return (
                <article className={`project-lifecycle-card is-${item.health}`} key={item.project_id}>
                  <div className="project-lifecycle-card-header">
                    <div>
                      <span>{item.category} · {item.target_market}</span>
                      <h3>{item.project_name}</h3>
                      <p>
                        当前环节：{item.stage_label}
                        {item.current_milestone_label
                          ? ` · 正在推进“${item.current_milestone_label}”`
                          : item.selected_product_name
                            ? ` · 已形成“${item.selected_product_name}”`
                            : ""}
                      </p>
                    </div>
                    <Tag color={health.color}>{health.label}</Tag>
                  </div>

                  <div className="project-lifecycle-progress">
                    <span>闭环完成度</span>
                    <Progress
                      percent={item.progress_percent}
                      size="small"
                      status={item.health === "blocked" ? "exception" : undefined}
                      strokeColor={item.health === "complete" ? "#00a870" : undefined}
                    />
                  </div>

                  <div className="project-lifecycle-stages">
                    {item.stages.map((stage) => (
                      <button
                        type="button"
                        className={`project-lifecycle-stage is-${stage.status}`}
                        key={stage.key}
                        title={stage.entity_id ? `${stage.detail}，点击查看记录` : stage.detail}
                        disabled={!stage.entity_id}
                        onClick={() => openProjectLifecycleStage(item, stage)}
                      >
                        <span className="project-lifecycle-stage-marker">
                          {stage.status === "complete" ? (
                            <CheckCircleFilled />
                          ) : stage.status === "current" ? (
                            <LoadingOutlined />
                          ) : stage.status === "blocked" ? (
                            <SafetyCertificateOutlined />
                          ) : (
                            <span />
                          )}
                        </span>
                        <strong>{stage.label}</strong>
                      </button>
                    ))}
                  </div>

                  <div className="project-lifecycle-footer">
                    <div className={item.blockers.length > 0 ? "has-risk" : "is-clear"}>
                      <span>{item.blockers.length > 0 ? "需要处理" : "当前判断"}</span>
                      <strong>
                        {item.blockers.length > 0
                          ? item.blockers.slice(0, 2).join("；")
                          : item.health === "complete"
                            ? "业务链路已经完整闭环"
                            : "当前没有发现阻断项，可按计划继续推进"}
                      </strong>
                    </div>
                    <Button
                      type={action.actionable && (item.health === "blocked" || item.health === "attention") ? "primary" : "default"}
                      onClick={() => openProjectLifecycle(item, { canApprove, canManage })}
                    >
                      {action.label}
                      <ArrowRightOutlined />
                    </Button>
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <div className="project-lifecycle-empty">
            <ProjectOutlined />
            <div>
              <strong>{lifecycleKeyword ? "没有匹配的项目" : "还没有可追踪的项目"}</strong>
              <span>
                {lifecycleKeyword
                  ? `没有找到与“${lifecycleKeyword}”相关的项目，可调整关键词后重试。`
                  : lifecycleStatus === "all"
                  ? "先创建商品规划项目，系统会从启动 Agent 起自动形成闭环台账。"
                  : "当前筛选条件下没有项目，可切换其他状态继续查看。"}
              </span>
            </div>
            {lifecycleKeyword ? (
              <Button
                onClick={() => {
                  setLifecycleLoading(true);
                  setLifecyclePage(1);
                  setLifecycleKeywordInput("");
                  setLifecycleKeyword("");
                }}
              >
                清除搜索
              </Button>
            ) : lifecycleStatus === "all" ? (
              <Button
                type="primary"
                onClick={() => scrollToSection("planning-workspace")}
              >
                创建规划项目
              </Button>
            ) : (
              <Button onClick={() => setLifecycleStatus("all")}>查看全部项目</Button>
            )}
          </div>
        )}

        {lifecycleData.total > lifecyclePageSize ? (
          <div className="project-lifecycle-pagination">
            <Pagination
              current={lifecyclePage}
              pageSize={lifecyclePageSize}
              total={lifecycleData.total}
              showSizeChanger={false}
              onChange={(page) => {
                setLifecycleLoading(true);
                setLifecyclePage(page);
              }}
            />
          </div>
        ) : null}
      </section>

      <div className="workflow-card">
        <div className="workflow-card-header">
          <div>
            <h2>从数据到决策的完整链路</h2>
            <p>每一步都来自当前系统真实状态，点击上方建议可直接进入待处理环节。</p>
          </div>
          <Tag color={latestStatus.color}>{latestStatus.label}</Tag>
        </div>
        <div className="workflow-steps">
          {workflowDefinitions.map((stage, index) => {
            const state = summary.workflowStates[stage.key];
            return (
              <div className={`workflow-step ${state}`} key={stage.key}>
                <div className="workflow-step-marker">
                  {state === "complete" ? (
                    <CheckCircleFilled />
                  ) : state === "current" ? (
                    <LoadingOutlined />
                  ) : state === "error" ? (
                    <SafetyCertificateOutlined />
                  ) : (
                    stage.icon
                  )}
                </div>
                <div>
                  <span>步骤 {index + 1}</span>
                  <strong>{stage.label}</strong>
                  <small>{summary.workflowDetails[stage.key]}</small>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="overview-detail-grid">
        <article className="latest-opportunity-card">
          <div className="overview-card-heading">
            <div>
              <span>最新商品机会</span>
              <h2>{summary.latestOpportunity?.category ?? "暂无评分结果"}</h2>
              <p>{summary.latestOpportunity?.target_market ?? "完成一次 Agent 运行后显示"}</p>
            </div>
            <Tag color={latestStatus.color}>{latestStatus.label}</Tag>
          </div>
          {typeof score === "number" ? (
            <div className="opportunity-score-layout">
              <div className="opportunity-score-ring">
                <Progress
                  type="circle"
                  percent={score}
                  size={142}
                  strokeColor={scoreColor}
                  format={(percent) => (
                    <span className="score-ring-value"><strong>{percent}</strong><small>机会分</small></span>
                  )}
                />
              </div>
              <div className="score-breakdown-list">
                {summary.scoreParts.map(({ key, value }) => {
                  const percent = Math.round((value.score / value.maxScore) * 100);
                  return (
                    <div className="score-breakdown-item" key={key}>
                      <div><span>{scoreLabels[key] ?? key}</span><b>{value.score}/{value.maxScore}</b></div>
                      <Progress percent={percent} showInfo={false} size="small" />
                    </div>
                  );
                })}
              </div>
            </div>
          ) : (
            <div className="overview-empty-state">启动 Agent 后，这里会直接显示机会分和评分拆解。</div>
          )}
          <div className="opportunity-facts">
            <div><span>预计毛利率</span><strong>{formatPercent(summary.latestOpportunity?.margin_rate)}</strong></div>
            <div><span>核心证据</span><strong>{summary.latestOpportunity?.evidence_count ?? 0} 条</strong></div>
            <div><span>供应风险</span><strong>{supplierRiskLabel(summary.latestOpportunity?.supplier_risk)}</strong></div>
          </div>
        </article>

        <article className="decision-readiness-card">
          <div className="overview-card-heading">
            <div>
              <span>决策准备度</span>
              <h2>{qualityPercent}% 证据可信</h2>
              <p>可信证据可直接支持 Agent 分析；质量提醒和阻断记录需要先治理。</p>
            </div>
            <DatabaseOutlined className="readiness-heading-icon" />
          </div>
          <Progress percent={qualityPercent} strokeColor="#00a870" />
          <div className="readiness-checklist">
            <div><CheckCircleFilled /><span>导入数据</span><strong>{data.qualitySummary?.total_imports ?? 0} 批</strong></div>
            <div><CheckCircleFilled /><span>可信证据</span><strong>{summary.verifiedEvidenceRecords.toLocaleString("zh-CN")} 条</strong></div>
            <div className={summary.warningEvidenceRecords ? "warning" : ""}><CheckCircleFilled /><span>质量提醒</span><strong>{summary.warningEvidenceRecords.toLocaleString("zh-CN")} 条</strong></div>
            <div className={summary.blockedEvidenceRecords ? "warning" : ""}><CheckCircleFilled /><span>阻断证据</span><strong>{summary.blockedEvidenceRecords.toLocaleString("zh-CN")} 条</strong></div>
            <div><ProductOutlined /><span>正式选品</span><strong>{data.selectedProductTotal} 个</strong></div>
          </div>
          <div className="decision-suggestion">
            <FileSearchOutlined />
            <div><span>提升建议</span><p>{summary.improvementSuggestion}</p></div>
          </div>
        </article>
      </div>
    </section>
  );
}
