/**
 * 文件职责：提供规划审批与上市评审的分页工作台和人工决策交互。
 */

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRightOutlined,
  CheckOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseOutlined,
  EditOutlined,
  LoadingOutlined,
  ReloadOutlined,
  UnlockOutlined,
  UserAddOutlined,
  UserSwitchOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Divider,
  Drawer,
  Form,
  Input,
  InputNumber,
  message,
  Modal,
  Select,
  Space,
  Table,
  Tag,
} from "antd";
import type { TableProps } from "antd";

import { PlanningResultView } from "@/components/planning-result-view";
import {
  ApprovalAction,
  ApprovalTask,
  assignApprovalTask,
  claimApprovalTask,
  decideApprovalTask,
  downloadRunValidationMaterial,
  getApprovalTask,
  getProjectRun,
  listApprovalTasksPage,
  listProjectRunEvidencePage,
  PlanningRunEvidence,
  PlanningRun,
  releaseApprovalTask,
} from "@/lib/http/planning";
import {
  decideProductLaunchReview,
  listTenantProductLaunchReviewsPage,
  getTenantProductLaunchReview,
  ProductLaunchReadinessCheckStatus,
  ProductLaunchReview,
  ProductLaunchReviewStatus,
} from "@/lib/http/product-initiatives";
import { notifyBusinessDataChanged } from "@/lib/business-events";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { hasAnyRole } from "@/store/identity-slice";
import { clearProjectContext, setProjectContext } from "@/store/project-context-slice";

/** 定义`statusPresentation`展示映射，集中维护状态文案、颜色或选项。 */
const statusPresentation: Record<string, { color: string; label: string }> = {
  pending: { color: "warning", label: "待审批" },
  approved: { color: "success", label: "已通过" },
  rejected: { color: "error", label: "已驳回" },
  revision_required: { color: "processing", label: "要求修订" },
  cancelled: { color: "default", label: "已取消" },
};

/** 定义`evidencePageSize`服务端分页每页数量，保持页面负载稳定。 */
const evidencePageSize = 8;

/** 定义`actionPresentation`展示映射，集中维护状态文案、颜色或选项。 */
const actionPresentation: Record<ApprovalAction, { title: string; okText: string }> = {
  approved: { title: "通过规划方案", okText: "确认通过" },
  rejected: { title: "驳回规划方案", okText: "确认驳回" },
  revision_required: { title: "要求 Agent 修订", okText: "提交修订" },
};

/** 定义`launchReviewPresentation`展示映射，集中维护状态文案、颜色或选项。 */
const launchReviewPresentation: Record<
  ProductLaunchReviewStatus,
  { color: string; label: string }
> = {
  pending: { color: "warning", label: "待审批" },
  approved: { color: "success", label: "已通过" },
  revision_required: { color: "processing", label: "要求修订" },
  rejected: { color: "error", label: "已驳回" },
};

/** 定义`readinessCheckPresentation`展示映射，集中维护状态文案、颜色或选项。 */
const readinessCheckPresentation: Record<
  ProductLaunchReadinessCheckStatus,
  { color: string; label: string }
> = {
  passed: { color: "success", label: "已满足" },
  pending: { color: "default", label: "待处理" },
  warning: { color: "warning", label: "需复核" },
  blocked: { color: "error", label: "阻断" },
};

/** 实现`summaryValue`辅助逻辑，集中处理页面展示或状态转换规则。 */
function summaryValue(task: ApprovalTask, key: string): string {
  const value = task.summary[key];
  return typeof value === "string" ? value : "-";
}

/** 读取可用于业务上下文的审批摘要字段，缺失时返回空值以触发项目详情自动补全。 */
function optionalSummaryValue(task: ApprovalTask, key: string): string | undefined {
  const value = task.summary[key];
  return typeof value === "string" && value.trim() ? value : undefined;
}

/** 实现`asRecord`辅助逻辑，集中处理页面展示或状态转换规则。 */
function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};
}

/** 实现`percentValue`辅助逻辑，集中处理页面展示或状态转换规则。 */
function percentValue(value: unknown): number | undefined {
  return typeof value === "number" ? Number((value * 100).toFixed(2)) : undefined;
}

/** 实现`decisionComment`辅助逻辑，集中处理页面展示或状态转换规则。 */
function decisionComment(task: ApprovalTask): string | undefined {
  const value = asRecord(task.decision).comment;
  return typeof value === "string" && value.trim() ? value : undefined;
}

/** 实现`decisionChangeCount`辅助逻辑，集中处理页面展示或状态转换规则。 */
function decisionChangeCount(task: ApprovalTask): number {
  const changes = asRecord(task.decision).changes;
  const constraintCount = Object.keys(asRecord(asRecord(changes).constraints)).length;
  return constraintCount + (typeof asRecord(changes).selected_candidate_id === "string" ? 1 : 0);
}

/** 实现`candidateConcepts`辅助逻辑，集中处理页面展示或状态转换规则。 */
function candidateConcepts(task: ApprovalTask): Record<string, unknown>[] {
  const outputs = asRecord(task.summary.outputs);
  const concept = asRecord(outputs.concept);
  return Array.isArray(concept.candidates) ? concept.candidates.map(asRecord) : [];
}

/** 实现`decisionCandidateName`辅助逻辑，集中处理页面展示或状态转换规则。 */
function decisionCandidateName(task: ApprovalTask): string | undefined {
  const changes = asRecord(task.decision).changes;
  const name = asRecord(changes).selected_candidate_name;
  return typeof name === "string" && name.trim() ? name : undefined;
}

/** 定义`DecisionFormValues`数据契约，约束组件属性或接口响应字段。 */
interface DecisionFormValues {
  comment?: string;
  selected_candidate_id?: string;
  target_margin?: number;
  selling_price?: number;
  unit_cost?: number;
  supplier_name?: string;
  moq?: number;
  lead_time_days?: number;
}

/** 定义`LaunchReviewDecisionFormValues`数据契约，约束组件属性或接口响应字段。 */
interface LaunchReviewDecisionFormValues {
  decision_note?: string;
}

/** 定义`ApprovalStatusFilter`允许的状态或联合类型，避免跨模块使用任意字符串。 */
type ApprovalStatusFilter = "pending" | "overdue" | "processed" | "all";
/** 定义`ApprovalAssigneeFilter`允许的状态或联合类型，避免跨模块使用任意字符串。 */
type ApprovalAssigneeFilter = "all" | "mine" | "unassigned";
/** 定义`LaunchReviewStatusFilter`允许的状态或联合类型，避免跨模块使用任意字符串。 */
type LaunchReviewStatusFilter = "pending" | "processed" | "all";

/** 定义`dueSoonMilliseconds`模块常量或配置，供当前文件中的多个流程复用。 */
const dueSoonMilliseconds = 4 * 60 * 60 * 1_000;
/** 定义`approvalTaskPageSize`服务端分页每页数量，保持页面负载稳定。 */
const approvalTaskPageSize = 5;
/** 定义`launchReviewPageSize`服务端分页每页数量，保持页面负载稳定。 */
const launchReviewPageSize = 5;

/** 实现`approvalDueDate`辅助逻辑，集中处理页面展示或状态转换规则。 */
function approvalDueDate(task: ApprovalTask): Date | undefined {
  if (!task.due_at) return undefined;
  const dueAt = new Date(task.due_at);
  return Number.isNaN(dueAt.getTime()) ? undefined : dueAt;
}

/** 判断`isApprovalOverdue`条件是否成立，供页面状态和操作权限复用。 */
function isApprovalOverdue(task: ApprovalTask): boolean {
  const dueAt = approvalDueDate(task);
  return task.status === "pending" && Boolean(dueAt && dueAt.getTime() < Date.now());
}

/** 判断`isApprovalDueSoon`条件是否成立，供页面状态和操作权限复用。 */
function isApprovalDueSoon(task: ApprovalTask): boolean {
  const dueAt = approvalDueDate(task);
  if (task.status !== "pending" || !dueAt) return false;
  const remaining = dueAt.getTime() - Date.now();
  return remaining >= 0 && remaining <= dueSoonMilliseconds;
}

/** 把formatApprovalDeadline相关原始值格式化为页面可读文本。 */
function formatApprovalDeadline(task: ApprovalTask): string {
  const dueAt = approvalDueDate(task);
  if (!dueAt) return "未设置";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(dueAt);
}

/** 定义`ApprovalFollowUp`数据契约，持久化审批后的 Agent 运行跟进状态。 */
interface ApprovalFollowUp {
  taskId: string;
  projectId: string;
  projectName: string;
  runId: string;
  action: ApprovalAction;
  status: "processing" | "completed" | "failed" | "cancelled";
  runStatus: string;
  updatedAt: string;
}

/** 定义`approvalFollowUpStorageKey`浏览器本地持久化键前缀，刷新页面后仍能恢复跟进。 */
const approvalFollowUpStorageKey = "merchpilot:approval-follow-ups";

/** 按租户生成本地跟进键，避免同一浏览器切换身份时看到其他租户的业务记录。 */
function approvalFollowUpStorageKeyFor(tenantId?: string): string {
  return `${approvalFollowUpStorageKey}:${tenantId?.trim() || "anonymous"}`;
}

/** 从浏览器本地存储读取最近审批跟进，损坏数据不会阻断审批中心加载。 */
function readApprovalFollowUps(tenantId?: string): ApprovalFollowUp[] {
  if (typeof window === "undefined") return [];
  try {
    const parsed = JSON.parse(
      window.localStorage.getItem(approvalFollowUpStorageKeyFor(tenantId)) ?? "[]",
    );
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (item): item is ApprovalFollowUp =>
        typeof item === "object"
        && item !== null
        && typeof item.taskId === "string"
        && typeof item.projectId === "string"
        && typeof item.projectName === "string"
        && typeof item.runId === "string"
        && ["approved", "rejected", "revision_required"].includes(item.action)
        && ["processing", "completed", "failed", "cancelled"].includes(item.status)
        && typeof item.runStatus === "string"
        && typeof item.updatedAt === "string",
    ).slice(0, 8);
  } catch {
    return [];
  }
}

/** 把运行状态转换为业务人员能理解的审批跟进文案。 */
function approvalFollowUpLabel(followUp: ApprovalFollowUp): string {
  if (followUp.status === "processing") {
    if (followUp.runStatus === "queued") return "已排队，等待 Agent 执行";
    if (followUp.runStatus === "running") return "Agent 正在处理审批结果";
    return "审批结果已提交，正在同步运行状态";
  }
  if (followUp.status === "failed") return "Agent 处理失败，请查看运行详情";
  if (followUp.status === "cancelled") return "审批已完成，规划运行已取消";
  if (followUp.action === "revision_required") return "已创建修订运行，可继续查看新版本";
  if (followUp.action === "approved") return "审批已完成，正式选品已生成";
  return "审批已完成，方案已驳回";
}

/** 把审批决定转换为跟进卡片中的简短动作名称。 */
function approvalFollowUpActionLabel(action: ApprovalAction): string {
  if (action === "approved") return "通过";
  if (action === "revision_required") return "要求修订";
  return "驳回";
}

/** 将审批跟进状态转换为标签颜色，帮助业务人员快速识别是否需要介入。 */
function approvalFollowUpColor(followUp: ApprovalFollowUp): string {
  if (followUp.status === "failed") return "error";
  if (followUp.status === "cancelled") return "default";
  if (followUp.status === "completed") return "success";
  return "processing";
}

/** 将审批跟进状态写入浏览器，保留最近记录并避免单条异常阻断页面。 */
function writeApprovalFollowUps(followUps: ApprovalFollowUp[], tenantId?: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      approvalFollowUpStorageKeyFor(tenantId),
      JSON.stringify(followUps.slice(0, 8)),
    );
  } catch {
    // 浏览器禁用本地存储时，页面内存状态仍然可以继续工作。
  }
}

/** 提供规划审批与上市评审的分页、领取、决策和跨模块定位工作台。 */
export function ApprovalPanel() {
  const dispatch = useAppDispatch();
  const identityState = useAppSelector((state) => state.identity);
  const projectContextState = useAppSelector((state) => state.projectContext);
  const identityTenantId = identityState.current?.tenant_id;
  const [tasks, setTasks] = useState<ApprovalTask[]>([]);
  const [launchReviews, setLaunchReviews] = useState<ProductLaunchReview[]>([]);
  const [loading, setLoading] = useState(true);
  const [launchReviewsLoading, setLaunchReviewsLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [assignmentTaskId, setAssignmentTaskId] = useState<string>();
  const [assignmentTarget, setAssignmentTarget] = useState<ApprovalTask>();
  const [assigning, setAssigning] = useState(false);
  const [decision, setDecision] = useState<{ task: ApprovalTask; action: ApprovalAction }>();
  const [decisionRequestId, setDecisionRequestId] = useState<string>();
  const [approvalFollowUpStore, setApprovalFollowUpStore] = useState<
    Record<string, ApprovalFollowUp[]>
  >({});
  const [launchReviewDecision, setLaunchReviewDecision] = useState<{
    review: ProductLaunchReview;
    action: "approved" | "rejected" | "revision_required";
  }>();
  const [launchReviewPreview, setLaunchReviewPreview] = useState<ProductLaunchReview>();
  const [launchReviewSubmitting, setLaunchReviewSubmitting] = useState(false);
  const [statusFilter, setStatusFilter] = useState<ApprovalStatusFilter>("pending");
  const [assigneeFilter, setAssigneeFilter] = useState<ApprovalAssigneeFilter>("all");
  const [launchReviewStatusFilter, setLaunchReviewStatusFilter] =
    useState<LaunchReviewStatusFilter>("pending");
  const [projectFilter, setProjectFilter] = useState<string>("all");
  const [taskTotal, setTaskTotal] = useState(0);
  const [taskSummary, setTaskSummary] = useState({
    total: 0,
    pending: 0,
    approved: 0,
    rejected: 0,
    revision_required: 0,
    cancelled: 0,
    processed: 0,
    overdue: 0,
    due_soon: 0,
    mine_pending: 0,
    unassigned_pending: 0,
  });
  const [projectOptions, setProjectOptions] = useState<Array<{ value: string; label: string }>>([]);
  const [launchReviewTotal, setLaunchReviewTotal] = useState(0);
  const [launchReviewSummary, setLaunchReviewSummary] = useState({
    total: 0,
    pending: 0,
    approved: 0,
    rejected: 0,
    revision_required: 0,
    processed: 0,
  });
  const requestRef = useRef(0);
  const [focusedApprovalTaskId, setFocusedApprovalTaskId] = useState<string>();
  const [currentTaskPage, setCurrentTaskPage] = useState(1);
  const [focusedLaunchReviewId, setFocusedLaunchReviewId] = useState<string>();
  const [currentLaunchReviewPage, setCurrentLaunchReviewPage] = useState(1);
  const [previewTask, setPreviewTask] = useState<ApprovalTask>();
  const [previewRun, setPreviewRun] = useState<PlanningRun>();
  const [previewEvidence, setPreviewEvidence] = useState<PlanningRunEvidence[]>([]);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewEvidencePage, setPreviewEvidencePage] = useState(1);
  const [previewEvidenceTotal, setPreviewEvidenceTotal] = useState(0);
  const [previewEvidenceUnavailableTotal, setPreviewEvidenceUnavailableTotal] = useState(0);
  const [form] = Form.useForm<DecisionFormValues>();
  const [launchReviewForm] = Form.useForm<LaunchReviewDecisionFormValues>();
  const [assignmentForm] = Form.useForm<{ assignee_id: string }>();
  const [messageApi, contextHolder] = message.useMessage();
  const currentProjectContextId = projectContextState.current?.projectId;
  const currentProjectContextName = projectContextState.current?.projectName;
  const currentProjectContextSource = projectContextState.current?.source;
  const projectContextHydrated = projectContextState.hydrated;
  const projectContextRevision = projectContextState.revision;
  const canApprove = hasAnyRole(identityState.current, ["admin", "approver"]);
  const isAdmin = hasAnyRole(identityState.current, ["admin"]);
  const currentUserId = identityState.current?.user_id;
  const pendingCount = taskSummary.pending;
  const pendingLaunchReviewCount = launchReviewSummary.pending;
  const overdueCount = taskSummary.overdue;
  const dueSoonCount = taskSummary.due_soon;
  const myPendingCount = taskSummary.mine_pending;
  const unassignedPendingCount = taskSummary.unassigned_pending;
  const visibleTasks = tasks;
  const visibleLaunchReviews = launchReviews;
  const decisionCandidates = decision ? candidateConcepts(decision.task) : [];
  const approvalFollowUpTenantKey = approvalFollowUpStorageKeyFor(identityTenantId);
  const approvalFollowUps = useMemo(
    () => approvalFollowUpStore[approvalFollowUpTenantKey] ?? [],
    [approvalFollowUpStore, approvalFollowUpTenantKey],
  );

  /** 更新审批跟进记录并同步浏览器持久化状态，避免页面刷新后丢失进度。 */
  const updateApprovalFollowUp = useCallback(
    (taskId: string, patch: Partial<ApprovalFollowUp>) => {
      setApprovalFollowUpStore((current) => {
        const currentFollowUps = current[approvalFollowUpTenantKey]
          ?? readApprovalFollowUps(identityTenantId);
        const next = currentFollowUps.map((followUp) => {
          if (followUp.taskId !== taskId) return followUp;
          const changed = Object.entries(patch).some(
            ([key, value]) => followUp[key as keyof ApprovalFollowUp] !== value,
          );
          return changed ? { ...followUp, ...patch } : followUp;
        });
        writeApprovalFollowUps(next, identityTenantId);
        return { ...current, [approvalFollowUpTenantKey]: next };
      });
    },
    [approvalFollowUpTenantKey, identityTenantId],
  );

  /** 记录一次新的审批后运行跟进，重复提交同一任务时只保留最新记录。 */
  const trackApprovalFollowUp = useCallback((followUp: ApprovalFollowUp) => {
    setApprovalFollowUpStore((current) => {
      const currentFollowUps = current[approvalFollowUpTenantKey]
        ?? readApprovalFollowUps(identityTenantId);
      const next = [followUp, ...currentFollowUps.filter((item) => item.taskId !== followUp.taskId)];
      writeApprovalFollowUps(next, identityTenantId);
      return { ...current, [approvalFollowUpTenantKey]: next };
    });
  }, [approvalFollowUpTenantKey, identityTenantId]);

  /** 在客户端挂载后恢复本租户的跟进记录，避免服务端渲染与浏览器状态不一致。 */
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setApprovalFollowUpStore((current) => {
        if (Object.prototype.hasOwnProperty.call(current, approvalFollowUpTenantKey)) {
          return current;
        }
        return {
          ...current,
          [approvalFollowUpTenantKey]: readApprovalFollowUps(identityTenantId),
        };
      });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [approvalFollowUpTenantKey, identityTenantId]);

  /** 轮询审批后的规划运行，直到 Worker 完成、失败、取消或创建修订版本。 */
  useEffect(() => {
    const processingFollowUps = approvalFollowUps.filter((item) => item.status === "processing");
    if (processingFollowUps.length === 0) return;
    let active = true;
    const refreshFollowUps = async () => {
      await Promise.all(processingFollowUps.map(async (followUp) => {
        try {
          const run = await getProjectRun(followUp.projectId, followUp.runId);
          if (!active) return;
          const nextStatus: ApprovalFollowUp["status"] = run.status === "failed"
            ? "failed"
            : run.status === "cancelled"
              ? "cancelled"
              : ["completed", "superseded"].includes(run.status)
                ? "completed"
                : "processing";
          if (nextStatus !== followUp.status || run.status !== followUp.runStatus) {
            updateApprovalFollowUp(followUp.taskId, {
              status: nextStatus,
              runStatus: run.status,
              updatedAt: new Date().toISOString(),
            });
          }
        } catch {
          // 短暂网络波动不改变业务状态，下一轮轮询继续获取服务端结果。
        }
      }));
    };
    void refreshFollowUps();
    const timer = window.setInterval(() => void refreshFollowUps(), 2500);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [approvalFollowUps, updateApprovalFollowUp]);

  const getApprovalTaskForFocus = useCallback(async (taskId: string) => {
    try {
      const task = await getApprovalTask(taskId);
      setTasks((current) => current.some((item) => item.id === task.id) ? current : [task, ...current]);
      setFocusedApprovalTaskId(task.id);
      setCurrentTaskPage(1);
      setCurrentLaunchReviewPage(1);
      setProjectFilter(task.project_id);
      dispatch(
        setProjectContext({
          projectId: task.project_id,
          projectName: optionalSummaryValue(task, "project_name"),
          category: optionalSummaryValue(task, "category"),
          targetMarket: optionalSummaryValue(task, "target_market"),
          tenantId: identityTenantId,
          source: "approval",
        }),
      );
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "无法加载审批任务");
    }
  }, [dispatch, identityTenantId, messageApi]);

  const getLaunchReviewForFocus = useCallback(async (reviewId: string) => {
    try {
      const review = await getTenantProductLaunchReview(reviewId);
      setLaunchReviews((current) => current.some((item) => item.id === review.id) ? current : [review, ...current]);
      setFocusedLaunchReviewId(review.id);
      if (review.project_id) {
        setCurrentTaskPage(1);
        setCurrentLaunchReviewPage(1);
        setProjectFilter(review.project_id);
        dispatch(
          setProjectContext({
            projectId: review.project_id,
            category: review.category,
            targetMarket: review.target_market,
            tenantId: review.tenant_id,
            source: "approval",
          }),
        );
      }
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "无法加载上市评审");
    }
  }, [dispatch, messageApi]);

  const refresh = useCallback(async (silent = false) => {
    const requestId = ++requestRef.current;
    if (!silent) {
      setLoading(true);
      setLaunchReviewsLoading(true);
    }
    try {
      const [taskItems, reviewItems] = await Promise.all([
        listApprovalTasksPage({
          status: statusFilter,
          assignee: assigneeFilter,
          projectId: projectFilter,
          page: currentTaskPage,
          pageSize: approvalTaskPageSize,
        }),
        listTenantProductLaunchReviewsPage(
          launchReviewStatusFilter,
          currentLaunchReviewPage,
          launchReviewPageSize,
          undefined,
          projectFilter === "all" ? undefined : projectFilter,
        ),
      ]);
      if (requestId !== requestRef.current) {
        return;
      }
      setTasks(taskItems.items);
      setTaskTotal(taskItems.total);
      setTaskSummary(taskItems.summary);
      setProjectOptions([
        { value: "all", label: "全部项目" },
        ...(currentProjectContextId
          && !taskItems.project_options.some(
            (item) => item.value === currentProjectContextId,
          )
          ? [{
              value: currentProjectContextId,
              label: currentProjectContextName ?? currentProjectContextId,
            }]
          : []),
        ...taskItems.project_options,
      ]);
      setLaunchReviews(reviewItems.items);
      setLaunchReviewTotal(reviewItems.total);
      setLaunchReviewSummary(reviewItems.summary);
      const taskPageCount = Math.max(1, Math.ceil(taskItems.total / approvalTaskPageSize));
      if (currentTaskPage > taskPageCount) {
        setCurrentTaskPage(taskPageCount);
      }
      const reviewPageCount = Math.max(1, Math.ceil(reviewItems.total / launchReviewPageSize));
      if (currentLaunchReviewPage > reviewPageCount) {
        setCurrentLaunchReviewPage(reviewPageCount);
      }
    } catch (error) {
      if (!silent && requestId === requestRef.current) {
        messageApi.error(error instanceof Error ? error.message : "无法加载审批任务");
      }
    } finally {
      if (!silent && requestId === requestRef.current) {
        setLoading(false);
        setLaunchReviewsLoading(false);
      }
    }
  }, [
    assigneeFilter,
    currentLaunchReviewPage,
    currentProjectContextId,
    currentProjectContextName,
    currentTaskPage,
    launchReviewStatusFilter,
    messageApi,
    projectFilter,
    statusFilter,
  ]);

  useEffect(() => {
    const initialLoad = window.setTimeout(() => {
      void refresh();
    }, 0);
    const timer = window.setInterval(() => {
      void refresh(true);
    }, 4_000);
    return () => {
      requestRef.current += 1;
      window.clearTimeout(initialLoad);
      window.clearInterval(timer);
    };
  }, [refresh]);

  useEffect(() => {
    const handleFocusApproval = (event: Event) => {
      const detail = (event as CustomEvent<{
        kind?: "planning" | "launch-review";
        status?: ApprovalStatusFilter;
        taskId?: string;
        reviewId?: string;
        projectId?: string;
      }>).detail;
      if (detail?.kind === "launch-review") {
        setFocusedApprovalTaskId(undefined);
        setStatusFilter("pending");
        setAssigneeFilter("all");
        setProjectFilter(detail.projectId ?? "all");
        if (detail.reviewId) {
          setLaunchReviewStatusFilter("all");
          void getLaunchReviewForFocus(detail.reviewId);
        } else {
          setLaunchReviewStatusFilter("pending");
        }
        return;
      }
      if (detail?.kind === "planning") {
        setFocusedLaunchReviewId(undefined);
        if (detail.taskId) {
          setStatusFilter("all");
          void getApprovalTaskForFocus(detail.taskId);
        } else {
          setStatusFilter(detail.status ?? "pending");
        }
        setAssigneeFilter("all");
        setProjectFilter(detail.projectId ?? "all");
      }
    };
    window.addEventListener("merchpilot:focus-approval", handleFocusApproval);
    return () => window.removeEventListener("merchpilot:focus-approval", handleFocusApproval);
  }, [getApprovalTaskForFocus, getLaunchReviewForFocus]);

  useEffect(() => {
    if (!projectContextHydrated || currentProjectContextSource === "approval") {
      return;
    }
    const contextTimer = window.setTimeout(() => {
      setFocusedApprovalTaskId(undefined);
      setFocusedLaunchReviewId(undefined);
      setCurrentTaskPage(1);
      setCurrentLaunchReviewPage(1);
      setStatusFilter("all");
      setLaunchReviewStatusFilter("all");
      setAssigneeFilter("all");
      setProjectFilter(currentProjectContextId ?? "all");
    }, 0);
    return () => window.clearTimeout(contextTimer);
  }, [
    currentProjectContextId,
    currentProjectContextSource,
    projectContextHydrated,
    projectContextRevision,
  ]);

  const taskPageCount = Math.max(1, Math.ceil(taskTotal / approvalTaskPageSize));
  const effectiveTaskPage = Math.min(currentTaskPage, taskPageCount);
  const launchReviewPageCount = Math.max(1, Math.ceil(launchReviewTotal / launchReviewPageSize));
  const effectiveLaunchReviewPage = Math.min(currentLaunchReviewPage, launchReviewPageCount);

  useEffect(() => {
    if (!focusedApprovalTaskId || !visibleTasks.some((task) => task.id === focusedApprovalTaskId)) {
      return;
    }
    const scrollTimer = window.setTimeout(() => {
      const row = [...document.querySelectorAll<HTMLElement>("tr[data-row-key]")].find(
        (item) => item.getAttribute("data-row-key") === focusedApprovalTaskId,
      );
      row?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 100);
    const clearTimer = window.setTimeout(() => setFocusedApprovalTaskId(undefined), 6_000);
    return () => {
      window.clearTimeout(scrollTimer);
      window.clearTimeout(clearTimer);
    };
  }, [effectiveTaskPage, focusedApprovalTaskId, visibleTasks]);

  useEffect(() => {
    if (
      !focusedLaunchReviewId ||
      !visibleLaunchReviews.some((review) => review.id === focusedLaunchReviewId)
    ) {
      return;
    }
    const scrollTimer = window.setTimeout(() => {
      const row = [...document.querySelectorAll<HTMLElement>("tr[data-row-key]")].find(
        (item) => item.getAttribute("data-row-key") === focusedLaunchReviewId,
      );
      row?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 100);
    const clearTimer = window.setTimeout(() => setFocusedLaunchReviewId(undefined), 6_000);
    return () => {
      window.clearTimeout(scrollTimer);
      window.clearTimeout(clearTimer);
    };
  }, [effectiveLaunchReviewPage, focusedLaunchReviewId, visibleLaunchReviews]);

  const openDecision = (task: ApprovalTask, action: ApprovalAction) => {
    dispatch(
      setProjectContext({
        projectId: task.project_id,
        projectName: optionalSummaryValue(task, "project_name"),
        category: optionalSummaryValue(task, "category"),
        targetMarket: optionalSummaryValue(task, "target_market"),
        tenantId: identityState.current?.tenant_id,
        source: "approval",
      }),
    );
    form.resetFields();
    const candidates = candidateConcepts(task);
    const firstCandidateId = candidates[0]?.id;
    if (action !== "rejected" && typeof firstCandidateId === "string") {
      form.setFieldsValue({ selected_candidate_id: firstCandidateId });
    }
    if (action === "revision_required") {
      const outputs = asRecord(task.summary.outputs);
      const finance = asRecord(outputs.finance);
      const supplier = asRecord(outputs.supplier);
      form.setFieldsValue({
        target_margin: percentValue(finance.target_margin),
        selling_price:
          typeof finance.selling_price === "number" ? finance.selling_price : undefined,
        unit_cost: typeof finance.unit_cost === "number" ? finance.unit_cost : undefined,
        supplier_name:
          typeof supplier.supplier_name === "string" ? supplier.supplier_name : undefined,
        moq: typeof supplier.moq === "number" ? supplier.moq : undefined,
        lead_time_days:
          typeof supplier.lead_time_days === "number" ? supplier.lead_time_days : undefined,
      });
    }
    setDecisionRequestId(crypto.randomUUID());
    setDecision({ task, action });
  };

  const openPreview = async (task: ApprovalTask) => {
    dispatch(
      setProjectContext({
        projectId: task.project_id,
        projectName: optionalSummaryValue(task, "project_name"),
        category: optionalSummaryValue(task, "category"),
        targetMarket: optionalSummaryValue(task, "target_market"),
        tenantId: identityState.current?.tenant_id,
        source: "approval",
      }),
    );
    setPreviewTask(task);
    setPreviewRun(undefined);
    setPreviewEvidence([]);
    setPreviewEvidencePage(1);
    setPreviewEvidenceTotal(0);
    setPreviewEvidenceUnavailableTotal(0);
    setPreviewLoading(true);
    try {
      const [latestRun, evidenceResult] = await Promise.all([
        getProjectRun(task.project_id, task.run_id),
        listProjectRunEvidencePage(task.project_id, task.run_id, 1, evidencePageSize),
      ]);
      setPreviewRun(latestRun);
      setPreviewEvidence(evidenceResult.items);
      setPreviewEvidenceTotal(evidenceResult.total);
      setPreviewEvidenceUnavailableTotal(evidenceResult.unavailable_total);
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "无法加载证据详情");
      setPreviewEvidence([]);
    } finally {
      setPreviewLoading(false);
    }
  };

  const loadPreviewEvidencePage = async (pageValue: number) => {
    if (!previewTask) return;
    setPreviewLoading(true);
    try {
      const result = await listProjectRunEvidencePage(
        previewTask.project_id,
        previewTask.run_id,
        pageValue,
        evidencePageSize,
      );
      setPreviewEvidence(result.items);
      setPreviewEvidencePage(result.page);
      setPreviewEvidenceTotal(result.total);
      setPreviewEvidenceUnavailableTotal(result.unavailable_total);
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "无法加载证据详情");
    } finally {
      setPreviewLoading(false);
    }
  };

  const replaceTask = (updatedTask: ApprovalTask) => {
    setTasks((current) =>
      current.map((task) => (task.id === updatedTask.id ? updatedTask : task)),
    );
  };

  const claimTask = async (task: ApprovalTask) => {
    setAssignmentTaskId(task.id);
    try {
      replaceTask(await claimApprovalTask(task.id));
      notifyBusinessDataChanged();
      messageApi.success("审批任务已领取，可开始处理");
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "审批任务领取失败");
      await refresh();
    } finally {
      setAssignmentTaskId(undefined);
    }
  };

  const releaseTask = async (task: ApprovalTask) => {
    setAssignmentTaskId(task.id);
    try {
      replaceTask(await releaseApprovalTask(task.id));
      notifyBusinessDataChanged();
      messageApi.success("审批任务已释放，其他审批人可以领取");
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "审批任务释放失败");
      await refresh();
    } finally {
      setAssignmentTaskId(undefined);
    }
  };

  const openAssignment = (task: ApprovalTask) => {
    assignmentForm.setFieldsValue({ assignee_id: task.assignee_id ?? "" });
    setAssignmentTarget(task);
  };

  const submitAssignment = async ({ assignee_id }: { assignee_id: string }) => {
    if (!assignmentTarget) return;
    setAssigning(true);
    try {
      replaceTask(await assignApprovalTask(assignmentTarget.id, assignee_id.trim()));
      notifyBusinessDataChanged();
      messageApi.success("审批任务已转派");
      setAssignmentTarget(undefined);
      assignmentForm.resetFields();
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "审批任务转派失败");
      await refresh();
    } finally {
      setAssigning(false);
    }
  };

  const downloadPreviewMaterial = async (materialId: string, filename: string) => {
    if (!previewTask || !previewRun) {
      return;
    }
    try {
      const blob = await downloadRunValidationMaterial(
        previewTask.project_id,
        previewRun.id,
        materialId,
      );
      const downloadUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = downloadUrl;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(downloadUrl);
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "验证材料下载失败");
    }
  };

  const submitDecision = async (values: DecisionFormValues) => {
    if (!decision) {
      return;
    }
    const decisionChanges: Record<string, unknown> = {};
    if (decision.action !== "rejected" && values.selected_candidate_id) {
      decisionChanges.selected_candidate_id = values.selected_candidate_id;
    }
    const constraintChanges: Record<string, unknown> = {};
    if (decision.action === "revision_required") {
      if (values.target_margin !== undefined) {
        constraintChanges.target_margin = values.target_margin / 100;
      }
      for (const key of ["selling_price", "unit_cost", "moq", "lead_time_days"] as const) {
        if (values[key] !== undefined) {
          constraintChanges[key] = values[key];
        }
      }
      if (values.supplier_name) {
        constraintChanges.supplier_name = values.supplier_name;
      }
    }
    setSubmitting(true);
    try {
      const requestId = decisionRequestId ?? crypto.randomUUID();
      if (!decisionRequestId) {
        setDecisionRequestId(requestId);
      }
      await decideApprovalTask(decision.task.id, {
        action: decision.action,
        comment: values.comment ?? "",
        changes: {
          ...decisionChanges,
          ...(decision.action === "revision_required" ? { constraints: constraintChanges } : {}),
        },
      }, requestId);
      trackApprovalFollowUp({
        taskId: decision.task.id,
        projectId: decision.task.project_id,
        projectName: optionalSummaryValue(decision.task, "project_name") ?? decision.task.project_id,
        runId: decision.task.run_id,
        action: decision.action,
        status: "processing",
        runStatus: "approval_required",
        updatedAt: new Date().toISOString(),
      });
      notifyBusinessDataChanged();
      messageApi.success(
        decision.action === "revision_required"
          ? "已要求 Agent 重新修订，可在审批后跟进中查看进度"
          : "审批决定已提交，可在审批后跟进中查看进度",
      );
      setDecision(undefined);
      setDecisionRequestId(undefined);
      form.resetFields();
      await refresh();
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "审批提交失败");
    } finally {
      setSubmitting(false);
    }
  };

  /** 根据审批动作进入对应业务模块，避免用户提交后还要自行寻找下一步。 */
  const openApprovalFollowUp = (followUp: ApprovalFollowUp) => {
    const completedApproval = followUp.status === "completed" && followUp.action === "approved";
    dispatch(
      setProjectContext({
        projectId: followUp.projectId,
        projectName: followUp.projectName,
        tenantId: identityState.current?.tenant_id,
        source: completedApproval ? "selection" : "planning",
      }),
    );
    window.setTimeout(() => {
      if (completedApproval) {
        window.dispatchEvent(
          new CustomEvent("merchpilot:focus-selected-products", {
            detail: { projectId: followUp.projectId, validation: "pending" },
          }),
        );
        document
          .getElementById("selected-product-panel")
          ?.scrollIntoView({ behavior: "smooth", block: "start" });
        return;
      }
      window.dispatchEvent(
        new CustomEvent("merchpilot:focus-planning-project", {
          detail: { projectId: followUp.projectId, runId: followUp.runId },
        }),
      );
      document
        .getElementById("planning-workspace")
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 150);
  };

  const openLaunchReviewDetail = (review: ProductLaunchReview) => {
    if (review.project_id) {
      dispatch(
        setProjectContext({
          projectId: review.project_id,
          category: review.category,
          targetMarket: review.target_market,
          tenantId: review.tenant_id,
          source: "approval",
        }),
      );
    }
    window.dispatchEvent(
      new CustomEvent("merchpilot:focus-initiative", {
        detail: { initiativeId: review.initiative_id },
      }),
    );
    window.setTimeout(() => {
      document
        .getElementById("product-initiative-panel")
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 100);
  };

  const openLaunchReviewDecision = (
    review: ProductLaunchReview,
    action: "approved" | "rejected" | "revision_required",
  ) => {
    if (review.project_id) {
      dispatch(
        setProjectContext({
          projectId: review.project_id,
          category: review.category,
          targetMarket: review.target_market,
          tenantId: review.tenant_id,
          source: "approval",
        }),
      );
    }
    launchReviewForm.resetFields();
    setLaunchReviewDecision({ review, action });
  };

  const openLaunchReviewPreview = (review: ProductLaunchReview) => {
    if (review.project_id) {
      dispatch(
        setProjectContext({
          projectId: review.project_id,
          category: review.category,
          targetMarket: review.target_market,
          tenantId: review.tenant_id,
          source: "approval",
        }),
      );
    }
    setLaunchReviewPreview(review);
  };

  const submitLaunchReviewDecision = async (
    values: LaunchReviewDecisionFormValues,
  ) => {
    if (!launchReviewDecision) return;
    setLaunchReviewSubmitting(true);
    try {
      await decideProductLaunchReview(
        launchReviewDecision.review.initiative_id,
        launchReviewDecision.review.id,
        {
          action: launchReviewDecision.action,
          decision_note: values.decision_note?.trim() ?? "",
        },
      );
      notifyBusinessDataChanged();
      messageApi.success(
        launchReviewDecision.action === "approved" ? "上市准备评审已通过" : "上市准备评审已处理",
      );
      setLaunchReviewDecision(undefined);
      launchReviewForm.resetFields();
      await refresh();
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "上市评审处理失败");
    } finally {
      setLaunchReviewSubmitting(false);
    }
  };

  const columns: TableProps<ApprovalTask>["columns"] = [
    {
      title: "审批事项",
      key: "summary",
      render: (_, task) => (
        <div className="approval-summary">
          <strong>{summaryValue(task, "title")}</strong>
          <span>
            {summaryValue(task, "project_name")} · {summaryValue(task, "category")} · {summaryValue(task, "target_market")}
          </span>
          {candidateConcepts(task).length > 0 ? (
            <span>{candidateConcepts(task).length} 个候选方案待确认</span>
          ) : null}
        </div>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 110,
      render: (value: string) => {
        const presentation = statusPresentation[value] ?? { color: "default", label: value };
        return <Tag color={presentation.color}>{presentation.label}</Tag>;
      },
    },
    {
      title: "处理人",
      key: "assignee",
      width: 140,
      render: (_, task) => {
        if (!task.assignee_id) {
          return <Tag>未领取</Tag>;
        }
        if (task.assignee_id === currentUserId) {
          return <Tag color="processing">我已领取</Tag>;
        }
        return <Tag color="gold">{task.assignee_id}</Tag>;
      },
    },
    {
      title: "审批时效",
      key: "due_at",
      width: 170,
      render: (_, task) => {
        if (task.status !== "pending") {
          return <span className="muted-text">已结束</span>;
        }
        if (isApprovalOverdue(task)) {
          return (
            <Space size={4} direction="vertical">
              <Tag color="error" icon={<ClockCircleOutlined />}>已超时</Tag>
              <span className="muted-text">截止 {formatApprovalDeadline(task)}</span>
            </Space>
          );
        }
        if (isApprovalDueSoon(task)) {
          return (
            <Space size={4} direction="vertical">
              <Tag color="warning" icon={<ClockCircleOutlined />}>即将到期</Tag>
              <span className="muted-text">截止 {formatApprovalDeadline(task)}</span>
            </Space>
          );
        }
        return (
          <Space size={4} direction="vertical">
            <Tag color="success">时效正常</Tag>
            <span className="muted-text">截止 {formatApprovalDeadline(task)}</span>
          </Space>
        );
      },
    },
    {
      title: "操作",
      key: "actions",
      width: 560,
      render: (_, task) => {
        const assignedToOther = Boolean(
          task.assignee_id && task.assignee_id !== currentUserId && !isAdmin,
        );
        const decisionDisabled = !canApprove || assignedToOther;
        const decisionTitle = !canApprove
          ? "需要审批人员或管理员角色"
          : assignedToOther
            ? `该任务已由 ${task.assignee_id} 领取`
            : undefined;
        return task.status === "pending" ? (
          <Space wrap>
            <Button size="small" onClick={() => void openPreview(task)}>
              查看方案
            </Button>
            {!task.assignee_id && canApprove ? (
              <Button
                size="small"
                icon={<UserAddOutlined />}
                loading={assignmentTaskId === task.id}
                onClick={() => void claimTask(task)}
              >
                领取
              </Button>
            ) : null}
            {task.assignee_id &&
            canApprove &&
            (task.assignee_id === currentUserId || isAdmin) ? (
              <Button
                size="small"
                icon={<UnlockOutlined />}
                loading={assignmentTaskId === task.id}
                onClick={() => void releaseTask(task)}
              >
                释放
              </Button>
            ) : null}
            {isAdmin ? (
              <Button
                size="small"
                icon={<UserSwitchOutlined />}
                onClick={() => openAssignment(task)}
              >
                转派
              </Button>
            ) : null}
            <Button
              size="small"
              type="primary"
              icon={<CheckOutlined />}
              disabled={decisionDisabled}
              title={decisionTitle}
              onClick={() => openDecision(task, "approved")}
            >
              通过
            </Button>
            <Button
              size="small"
              icon={<EditOutlined />}
              disabled={decisionDisabled}
              title={decisionTitle}
              onClick={() => openDecision(task, "revision_required")}
            >
              要求修订
            </Button>
            <Button
              size="small"
              danger
              icon={<CloseOutlined />}
              disabled={decisionDisabled}
              title={decisionTitle}
              onClick={() => openDecision(task, "rejected")}
            >
              驳回
            </Button>
          </Space>
        ) : (
          <Space>
            <Button size="small" onClick={() => void openPreview(task)}>
              查看方案
            </Button>
            <div className="approval-decision-result">
              <span className="muted-text">
                {task.decided_by ? `由 ${task.decided_by} 处理` : "已处理"}
              </span>
              {decisionComment(task) ? (
                <span title={decisionComment(task)}>{decisionComment(task)}</span>
              ) : null}
              {decisionChangeCount(task) > 0 ? (
                <span>已调整 {decisionChangeCount(task)} 项参数</span>
              ) : null}
              {decisionCandidateName(task) ? <span>已选 {decisionCandidateName(task)}</span> : null}
            </div>
          </Space>
        );
      },
    },
  ];

  const needsComment = decision?.action !== "approved";
  const launchReviewNeedsNote = launchReviewDecision?.action !== "approved";

  const launchReviewColumns: TableProps<ProductLaunchReview>["columns"] = [
    {
      title: "评审事项",
      key: "initiative",
      render: (_, review) => (
        <div className="approval-summary">
          <strong>{review.initiative_name || review.initiative_id}</strong>
          <span>上市准备评审 · 提交人 {review.submitted_by}</span>
          <span>{review.submission_note || "暂无提交说明"}</span>
        </div>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 110,
      render: (value: ProductLaunchReviewStatus) => {
        const presentation = launchReviewPresentation[value];
        return <Tag color={presentation.color}>{presentation.label}</Tag>;
      },
    },
    {
      title: "提交时间",
      dataIndex: "submitted_at",
      key: "submitted_at",
      width: 150,
      render: (value: string) => formatApprovalDeadline({ status: "processed", due_at: value } as ApprovalTask),
    },
    {
      title: "操作",
      key: "actions",
      width: 510,
      render: (_, review) => (
        <Space wrap>
          <Button size="small" onClick={() => openLaunchReviewPreview(review)}>
            查看预检
          </Button>
          <Button size="small" onClick={() => openLaunchReviewDetail(review)}>
            查看立项
          </Button>
          {review.status === "pending" && canApprove ? (
            <>
              <Button
                size="small"
                type="primary"
                icon={<CheckOutlined />}
                onClick={() => openLaunchReviewDecision(review, "approved")}
              >
                通过
              </Button>
              <Button
                size="small"
                icon={<EditOutlined />}
                onClick={() => openLaunchReviewDecision(review, "revision_required")}
              >
                退回修订
              </Button>
              <Button
                size="small"
                danger
                icon={<CloseOutlined />}
                onClick={() => openLaunchReviewDecision(review, "rejected")}
              >
                驳回
              </Button>
            </>
          ) : null}
        </Space>
      ),
    },
  ];

  return (
    <section className="panel approval-panel" id="approval-panel">
      {contextHolder}
      <div className="panel-header">
        <div>
          <h2 className="panel-title">线上审批中心</h2>
          <p className="panel-description">业务人员在系统内审核方案，审批后自动恢复或重新执行 Agent 工作流</p>
        </div>
        <Space>
          <Tag color={pendingCount ? "warning" : "success"}>{pendingCount} 项待审批</Tag>
          {overdueCount > 0 ? <Tag color="error">{overdueCount} 项已超时</Tag> : null}
          {dueSoonCount > 0 ? <Tag color="warning">{dueSoonCount} 项即将到期</Tag> : null}
          {canApprove ? <Tag color="processing">我的待办 {myPendingCount}</Tag> : null}
          {identityState.status === "ready" && !canApprove && <Tag>只读审批</Tag>}
          <Button icon={<ReloadOutlined />} onClick={() => void refresh()} loading={loading}>
            刷新
          </Button>
        </Space>
      </div>
      <div className="approval-filter-toolbar">
        <Select
          value={statusFilter}
          onChange={(value) => {
            setCurrentTaskPage(1);
            setStatusFilter(value);
          }}
          options={[
            { value: "pending", label: `待审批 (${pendingCount})` },
            { value: "overdue", label: `已超时 (${overdueCount})` },
            { value: "processed", label: `已处理 (${taskSummary.processed})` },
            { value: "all", label: `全部 (${taskSummary.total})` },
          ]}
        />
        <Select
          value={projectFilter}
          onChange={(value) => {
            setCurrentTaskPage(1);
            setProjectFilter(value);
            if (value === "all") {
              dispatch(clearProjectContext());
              return;
            }
            const option = projectOptions.find((item) => item.value === value);
            dispatch(
              setProjectContext({
                projectId: value,
                projectName: option?.label,
                tenantId: identityState.current?.tenant_id,
                source: "approval",
              }),
            );
          }}
          options={projectOptions}
          showSearch
          optionFilterProp="label"
        />
        <Select
          value={assigneeFilter}
          onChange={(value) => {
            setCurrentTaskPage(1);
            setAssigneeFilter(value);
          }}
          options={[
            { value: "all", label: "全部处理人" },
            { value: "mine", label: `我领取的 (${myPendingCount})` },
            { value: "unassigned", label: `未领取 (${unassignedPendingCount})` },
          ]}
        />
        <span>当前显示 {visibleTasks.length} / {taskTotal} 条审批记录</span>
      </div>
      {approvalFollowUps.length > 0 ? (
        <div className="approval-follow-up-panel">
          <div className="approval-follow-up-header">
            <div>
              <strong>审批后跟进</strong>
              <span>审批决定已经提交，系统会持续同步 Agent 运行状态。</span>
            </div>
            <Tag color="processing">最近 {approvalFollowUps.length} 条</Tag>
          </div>
          <div className="approval-follow-up-list">
            {approvalFollowUps.map((followUp) => {
              const statusLabel = approvalFollowUpLabel(followUp);
              const isProcessing = followUp.status === "processing";
              const actionLabel = followUp.status === "failed"
                ? "查看运行"
                : followUp.status === "completed" && followUp.action === "approved"
                  ? "进入验证"
                  : "查看规划";
              return (
                <div className="approval-follow-up-item" key={followUp.taskId}>
                  <div className="approval-follow-up-item-main">
                    <div className="approval-follow-up-item-title">
                      {isProcessing ? <LoadingOutlined /> : followUp.status === "failed" ? <WarningOutlined /> : <CheckCircleOutlined />}
                      <strong>{followUp.projectName}</strong>
                      <Tag color={approvalFollowUpColor(followUp)}>
                        审批{approvalFollowUpActionLabel(followUp.action)}
                      </Tag>
                    </div>
                    <span>{statusLabel}</span>
                  </div>
                  <Space wrap>
                    <span className="muted-text">运行状态：{followUp.runStatus}</span>
                    <Button
                      size="small"
                      type={followUp.status === "completed" ? "primary" : "default"}
                      icon={<ArrowRightOutlined />}
                      onClick={() => openApprovalFollowUp(followUp)}
                    >
                      {actionLabel}
                    </Button>
                  </Space>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
      <Table<ApprovalTask>
        rowKey="id"
        columns={columns}
        dataSource={visibleTasks}
        loading={loading}
        pagination={{
          current: effectiveTaskPage,
          pageSize: approvalTaskPageSize,
          total: taskTotal,
          hideOnSinglePage: true,
          onChange: setCurrentTaskPage,
        }}
        scroll={{ x: 1120 }}
        rowClassName={(task) => (
          task.id === focusedApprovalTaskId ? "approval-task-row-focused" : ""
        )}
      />

      <Divider plain>
        <Space>
          上市准备评审
          <Tag color={pendingLaunchReviewCount ? "warning" : "default"}>
            {pendingLaunchReviewCount} 项待处理
          </Tag>
        </Space>
      </Divider>
      <div className="approval-filter-toolbar launch-review-filter-toolbar">
        <Select
          value={launchReviewStatusFilter}
          onChange={(value) => {
            setCurrentLaunchReviewPage(1);
            setLaunchReviewStatusFilter(value);
          }}
          options={[
            { value: "pending", label: `待处理 (${pendingLaunchReviewCount})` },
            {
              value: "processed",
              label: `已处理 (${launchReviewSummary.processed})`,
            },
            { value: "all", label: `全部 (${launchReviewSummary.total})` },
          ]}
        />
        <span>当前显示 {visibleLaunchReviews.length} / {launchReviewTotal} 条上市评审记录</span>
      </div>
      <Table<ProductLaunchReview>
        rowKey="id"
        columns={launchReviewColumns}
        dataSource={visibleLaunchReviews}
        loading={launchReviewsLoading}
        pagination={{
          current: effectiveLaunchReviewPage,
          pageSize: launchReviewPageSize,
          total: launchReviewTotal,
          hideOnSinglePage: true,
          onChange: setCurrentLaunchReviewPage,
        }}
        scroll={{ x: 920 }}
        rowClassName={(review) => (
          review.id === focusedLaunchReviewId ? "launch-review-row-focused" : ""
        )}
        locale={{
          emptyText:
            launchReviewStatusFilter === "pending" ? "暂无待处理上市评审" : "暂无上市准备评审记录",
        }}
      />

      <Modal
        title={
          launchReviewPreview
            ? `${launchReviewPreview.initiative_name || launchReviewPreview.initiative_id} · 上市准备预检`
            : "上市准备预检"
        }
        open={Boolean(launchReviewPreview)}
        onCancel={() => setLaunchReviewPreview(undefined)}
        footer={null}
        width={720}
      >
        {launchReviewPreview ? (
          <Space direction="vertical" size={16} style={{ width: "100%" }}>
            <Space wrap>
              <Tag color={launchReviewPresentation[launchReviewPreview.status].color}>
                评审{launchReviewPresentation[launchReviewPreview.status].label}
              </Tag>
              <Tag
                color={
                  launchReviewPreview.readiness_snapshot.readiness_status === "ready"
                    ? "success"
                    : launchReviewPreview.readiness_snapshot.readiness_status === "review"
                      ? "warning"
                      : "error"
                }
              >
                {launchReviewPreview.readiness_snapshot.readiness_label}
              </Tag>
              <span className="muted-text">提交人：{launchReviewPreview.submitted_by}</span>
            </Space>
            <div className="approval-review-check-list">
              {launchReviewPreview.readiness_snapshot.checks.map((check) => {
                const presentation = readinessCheckPresentation[check.status];
                return (
                  <div key={check.id}>
                    <Tag color={presentation.color}>{presentation.label}</Tag>
                    <div>
                      <strong>{check.label}</strong>
                      <span>{check.detail}</span>
                    </div>
                  </div>
                );
              })}
            </div>
            {launchReviewPreview.readiness_snapshot.blockers.length > 0 ? (
              <Alert
                type="error"
                showIcon
                message={`阻断项（${launchReviewPreview.readiness_snapshot.blockers.length}）`}
                description={launchReviewPreview.readiness_snapshot.blockers.join("；")}
              />
            ) : null}
            {launchReviewPreview.readiness_snapshot.warnings.length > 0 ? (
              <Alert
                type="warning"
                showIcon
                message={`风险提示（${launchReviewPreview.readiness_snapshot.warnings.length}）`}
                description={launchReviewPreview.readiness_snapshot.warnings.join("；")}
              />
            ) : null}
            {launchReviewPreview.readiness_snapshot.recommendations.length > 0 ? (
              <Alert
                type="info"
                showIcon
                message="系统建议"
                description={launchReviewPreview.readiness_snapshot.recommendations.join("；")}
              />
            ) : null}
            {launchReviewPreview.submission_note ? (
              <div className="approval-review-note">
                <strong>提交说明</strong>
                <span>{launchReviewPreview.submission_note}</span>
              </div>
            ) : null}
          </Space>
        ) : null}
      </Modal>

      <Modal
        title={decision ? actionPresentation[decision.action].title : "审批"}
        open={Boolean(decision)}
        onCancel={() => {
          setDecision(undefined);
          setDecisionRequestId(undefined);
        }}
        onOk={() => form.submit()}
        okText={decision ? actionPresentation[decision.action].okText : "提交"}
        confirmLoading={submitting}
        okButtonProps={{ danger: decision?.action === "rejected", disabled: !canApprove }}
        width={decision?.action === "revision_required" ? 720 : 520}
      >
        <Form form={form} layout="vertical" onFinish={(values) => void submitDecision(values)}>
          <Form.Item
            name="comment"
            label="审批意见"
            rules={needsComment ? [{ required: true, message: "请填写审批意见" }] : undefined}
          >
            <Input.TextArea rows={4} placeholder="说明通过理由、驳回原因或需要修改的内容" maxLength={2000} showCount />
          </Form.Item>
          {decision && decision.action !== "rejected" && decisionCandidates.length > 0 ? (
            <Form.Item
              name="selected_candidate_id"
              label="确认候选商品方案"
              rules={[{ required: true, message: "请选择一个候选商品方案" }]}
            >
              <Select
                options={decisionCandidates.map((candidate, index) => ({
                  value: candidate.id,
                  label: `${index + 1}. ${typeof candidate.name === "string" ? candidate.name : "未命名方案"}`,
                }))}
              />
            </Form.Item>
          ) : null}
          {decision?.action === "revision_required" && (
            <>
              <Divider titlePlacement="start">调整后参数</Divider>
              <div className="form-grid-three">
                <Form.Item name="target_margin" label="目标毛利率 (%)">
                  <InputNumber min={0} max={100} precision={2} className="full-width" />
                </Form.Item>
                <Form.Item name="selling_price" label="计划售价">
                  <InputNumber min={0.01} precision={2} className="full-width" />
                </Form.Item>
                <Form.Item name="unit_cost" label="单位采购成本">
                  <InputNumber min={0} precision={2} className="full-width" />
                </Form.Item>
              </div>
              <Form.Item name="supplier_name" label="供应商名称">
                <Input placeholder="可指定或调整供应商" />
              </Form.Item>
              <div className="form-grid-two">
                <Form.Item name="moq" label="最小起订量 (MOQ)">
                  <InputNumber min={1} precision={0} className="full-width" />
                </Form.Item>
                <Form.Item name="lead_time_days" label="预计交期 (天)">
                  <InputNumber min={1} precision={0} className="full-width" />
                </Form.Item>
              </div>
            </>
          )}
        </Form>
      </Modal>

      <Modal
        title={
          launchReviewDecision?.action === "approved"
            ? "通过上市准备评审"
            : launchReviewDecision?.action === "revision_required"
              ? "退回上市准备评审"
              : "驳回上市准备评审"
        }
        open={Boolean(launchReviewDecision)}
        onCancel={() => {
          setLaunchReviewDecision(undefined);
          launchReviewForm.resetFields();
        }}
        onOk={() => launchReviewForm.submit()}
        okText={launchReviewDecision?.action === "approved" ? "确认通过" : "确认处理"}
        confirmLoading={launchReviewSubmitting}
        okButtonProps={{ danger: launchReviewDecision?.action === "rejected", disabled: !canApprove }}
      >
        <Form
          form={launchReviewForm}
          layout="vertical"
          onFinish={(values) => void submitLaunchReviewDecision(values)}
        >
          <p className="muted-text">
            处理结果会同步到商品立项的“上市准备评审”里程碑，并写入立项时间线。
          </p>
          <Form.Item
            name="decision_note"
            label="处理意见"
            rules={launchReviewNeedsNote ? [{ required: true, message: "请填写处理意见" }] : undefined}
          >
            <Input.TextArea rows={5} maxLength={2000} showCount placeholder="请输入审批意见" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="转派审批任务"
        open={Boolean(assignmentTarget)}
        onCancel={() => {
          setAssignmentTarget(undefined);
          assignmentForm.resetFields();
        }}
        onOk={() => assignmentForm.submit()}
        okText="确认转派"
        confirmLoading={assigning}
      >
        <Form
          form={assignmentForm}
          layout="vertical"
          onFinish={(values) => void submitAssignment(values)}
        >
          <Form.Item
            name="assignee_id"
            label="新处理人账号"
            rules={[
              { required: true, whitespace: true, message: "请输入处理人账号" },
              { max: 64, message: "处理人账号不能超过 64 个字符" },
            ]}
          >
            <Input placeholder="例如：approver-zhang" autoComplete="off" />
          </Form.Item>
          <p className="muted-text">当前先使用账号标识；接入企业 SSO 后可替换为组织人员选择器。</p>
        </Form>
      </Modal>

      <Drawer
        title="商品规划方案与证据"
        size="min(1180px, 96vw)"
        open={Boolean(previewTask)}
        onClose={() => {
          setPreviewTask(undefined);
          setPreviewRun(undefined);
          setPreviewEvidence([]);
          setPreviewEvidencePage(1);
          setPreviewEvidenceTotal(0);
          setPreviewEvidenceUnavailableTotal(0);
        }}
      >
        {previewTask ? (
          <PlanningResultView
            key={previewRun?.id ?? previewTask.run_id}
            snapshot={previewRun?.result_snapshot ?? { outputs: previewTask.summary.outputs }}
            evidence={previewEvidence}
            evidenceLoading={previewLoading}
            evidencePage={previewEvidencePage}
            evidencePageSize={evidencePageSize}
            evidenceTotal={previewEvidenceTotal}
            evidenceUnavailableTotal={previewEvidenceUnavailableTotal}
            onEvidencePageChange={(pageValue) => void loadPreviewEvidencePage(pageValue)}
            projectName={summaryValue(previewTask, "project_name")}
            category={summaryValue(previewTask, "category")}
            targetMarket={summaryValue(previewTask, "target_market")}
            approvalStatus={previewTask.status}
            onValidationMaterialDownload={downloadPreviewMaterial}
          />
        ) : null}
      </Drawer>
    </section>
  );
}
