/**
 * 文件职责：管理规划项目、Agent 启动、运行版本、实时进度和结果查看。
 */

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  EditOutlined,
  EyeOutlined,
  FileExcelOutlined,
  FolderOutlined,
  DownloadOutlined,
  PlusOutlined,
  RedoOutlined,
  ReloadOutlined,
  RollbackOutlined,
  RocketOutlined,
  SwapOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  message,
  Modal,
  Pagination,
  Select,
  Space,
  Tag,
} from "antd";

import { AgentMesh } from "@/components/agent-mesh";
import { AgentNodeDetailDrawer } from "@/components/agent-node-detail-drawer";
import {
  PlanningResultNextAction,
  PlanningResultView,
} from "@/components/planning-result-view";
import { RunVersionComparison } from "@/components/run-version-comparison";
import { RunExecutionTimeline } from "@/components/run-execution-timeline";
import { notifyBusinessDataChanged } from "@/lib/business-events";
import {
  buildProjectConstraints,
  ProjectFormFields,
  ProjectFormValues,
  projectToFormValues,
} from "@/components/project-form-fields";
import {
  archivePlanningProject,
  createPlanningProject,
  deleteRunValidationMaterial,
  downloadRunValidationMaterial,
  getProjectRun,
  getProjectRunEvents,
  getPlanningProject,
  listPlanningProjectsPage,
  listApprovalTasksPage,
  listProjectRunEvidencePage,
  listProjectRunsPage,
  ApprovalTask,
  PlanningProject,
  PlanningProjectPageSummary,
  PlanningRun,
  PlanningRunPageSummary,
  PlanningRunEvidence,
  retryProjectRun,
  restorePlanningProject,
  startProjectRun,
  uploadRunValidationMaterial,
  updateRunValidationPlan,
  updatePlanningProject,
  ValidationGateStatus,
} from "@/lib/http/planning";
import { RunSocket } from "@/lib/ws/run-socket";
import { AsyncTaskStatus, getAsyncTaskStatuses } from "@/lib/http/async-tasks";
import { listProductInitiativesPage, ProductInitiative } from "@/lib/http/product-initiatives";
import { listSelectedProductsPage, SelectedProduct } from "@/lib/http/selected-products";
import {
  createPlanningReport,
  downloadPlanningReport,
  getPlanningReport,
  listPlanningReportsPage,
  PlanningReport,
} from "@/lib/http/reports";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { hasAnyRole } from "@/store/identity-slice";
import { setProjectContext } from "@/store/project-context-slice";
import {
  hydrateRunState,
  hydrateRunEvents,
  receiveRunEvent,
  setActiveRun,
  setConnectionStatus,
} from "@/store/run-slice";

/** 定义`ProjectView`允许的状态或联合类型，避免跨模块使用任意字符串。 */
type ProjectView = "active" | "archived";

/** 定义`ProjectStatusFilter`允许的状态或联合类型，避免跨模块使用任意字符串。 */
type ProjectStatusFilter =
  | "all"
  | "draft"
  | "queued"
  | "running"
  | "approval_required"
  | "completed"
  | "failed"
  | "cancelled";

/** 定义`projectPageSize`服务端分页每页数量，保持页面负载稳定。 */
const projectPageSize = 8;
/** 定义`runPageSize`服务端分页每页数量，保持页面负载稳定。 */
const runPageSize = 5;
/** 定义`reportPageSize`服务端分页每页数量，保持页面负载稳定。 */
const reportPageSize = 5;
/** 定义`evidencePageSize`服务端分页每页数量，保持页面负载稳定。 */
const evidencePageSize = 8;

/** 定义`emptyProjectSummary`初始状态，避免加载期间出现空值分支。 */
const emptyProjectSummary: PlanningProjectPageSummary = {
  total: 0,
  draft: 0,
  queued: 0,
  running: 0,
  approval_required: 0,
  completed: 0,
  failed: 0,
  cancelled: 0,
};

/** 定义`emptyRunSummary`初始状态，避免加载期间出现空值分支。 */
const emptyRunSummary: PlanningRunPageSummary = {
  total: 0,
  queued: 0,
  running: 0,
  approval_required: 0,
  completed: 0,
  failed: 0,
  cancelled: 0,
  superseded: 0,
  active: 0,
};

/** 定义`runStatusPresentation`展示映射，集中维护状态文案、颜色或选项。 */
const runStatusPresentation: Record<string, { color: string; label: string }> = {
  queued: { color: "default", label: "排队中" },
  running: { color: "processing", label: "执行中" },
  approval_required: { color: "warning", label: "等待审批" },
  completed: { color: "success", label: "已完成" },
  failed: { color: "error", label: "失败" },
  cancelled: { color: "default", label: "已取消" },
  superseded: { color: "default", label: "已生成新版本" },
};

/** 定义`projectStatusPresentation`展示映射，集中维护状态文案、颜色或选项。 */
const projectStatusPresentation: Record<string, { color: string; label: string }> = {
  draft: { color: "default", label: "待启动" },
  queued: { color: "processing", label: "排队中" },
  running: { color: "processing", label: "分析中" },
  approval_required: { color: "warning", label: "待审批" },
  completed: { color: "success", label: "已完成" },
  failed: { color: "error", label: "运行失败" },
  cancelled: { color: "error", label: "未通过" },
};

/** 定义`approvalStatusPresentation`展示映射，集中维护状态文案、颜色或选项。 */
const approvalStatusPresentation: Record<string, { color: string; label: string }> = {
  pending: { color: "warning", label: "待审批" },
  approved: { color: "success", label: "已通过" },
  rejected: { color: "error", label: "已驳回" },
  revision_required: { color: "processing", label: "要求修订" },
};

/** 定义`reportStatusPresentation`展示映射，集中维护状态文案、颜色或选项。 */
const reportStatusPresentation: Record<string, { color: string; label: string }> = {
  queued: { color: "default", label: "排队中" },
  processing: { color: "processing", label: "生成中" },
  completed: { color: "success", label: "已完成" },
  failed: { color: "error", label: "生成失败" },
};

/** 实现`asyncTaskColor`辅助逻辑，集中处理页面展示或状态转换规则。 */
function asyncTaskColor(taskStatus?: AsyncTaskStatus): string {
  if (!taskStatus) return "default";
  if (["FAILURE", "REVOKED"].includes(taskStatus.state)) return "error";
  if (taskStatus.state === "SUCCESS") return "success";
  if (taskStatus.state === "UNKNOWN") return "warning";
  return "processing";
}

/** 定义`nodeOutputKeyById`模块常量或配置，供当前文件中的多个流程复用。 */
const nodeOutputKeyById: Record<string, string> = {
  requirement: "requirement",
  market: "market",
  competitor: "competitor",
  insight: "user_insight",
  concept: "concept",
  supplier: "supplier",
  finance: "finance",
  scoring: "scorecard",
  narrative: "narrative",
  approval: "approval",
};

/** 定义`constraintLabels`展示映射，集中维护状态文案、颜色或选项。 */
const constraintLabels: Record<string, string> = {
  target_margin: "目标毛利率",
  selling_price: "销售价格",
  unit_cost: "单位成本",
  supplier_name: "供应商",
  moq: "最小起订量",
  lead_time_days: "交期",
  max_lead_time_days: "最长交期",
  forecast_units: "预测销量",
  target_user: "目标用户",
  price_range: "价格区间",
};

/** 实现`asRecord`辅助逻辑，集中处理页面展示或状态转换规则。 */
function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};
}

/** 把formatPercent相关原始值格式化为页面可读文本。 */
function formatPercent(value: unknown): string {
  return typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "待计算";
}

/** 把formatDateTime相关原始值格式化为页面可读文本。 */
function formatDateTime(value?: string): string {
  if (!value) {
    return "未记录时间";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

/** 实现`saveBlob`辅助逻辑，集中处理页面展示或状态转换规则。 */
function saveBlob(blob: Blob, filename: string): void {
  const downloadUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = downloadUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(downloadUrl);
}

/** 把formatConstraintValue相关原始值格式化为页面可读文本。 */
function formatConstraintValue(key: string, value: unknown): string {
  if (value === undefined || value === null || value === "") {
    return "未设置";
  }
  if (key === "target_margin" && typeof value === "number") {
    return `${(value * 100).toFixed(1)}%`;
  }
  if (["selling_price", "unit_cost"].includes(key) && typeof value === "number") {
    return `¥${value.toFixed(2)}`;
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

/** 实现`constraintDiffs`辅助逻辑，集中处理页面展示或状态转换规则。 */
function constraintDiffs(task: ApprovalTask): Array<{
  key: string;
  label: string;
  before: string;
  after: string;
}> {
  const decision = asRecord(task.decision);
  const changes = asRecord(asRecord(decision.changes).constraints);
  const outputs = asRecord(asRecord(task.summary).outputs);
  const requirement = asRecord(outputs.requirement);
  const beforeConstraints = asRecord(requirement.constraints);
  const keys = new Set([...Object.keys(beforeConstraints), ...Object.keys(changes)]);

  return [...keys]
    .map((key) => {
      const before = beforeConstraints[key];
      const after = Object.prototype.hasOwnProperty.call(changes, key)
        ? changes[key]
        : before;
      return {
        key,
        label: constraintLabels[key] ?? key.replaceAll("_", " "),
        before: formatConstraintValue(key, before),
        after: formatConstraintValue(key, after),
        changed: JSON.stringify(before) !== JSON.stringify(after),
      };
    })
    .filter((item) => item.changed)
    .map((item) => ({
      key: item.key,
      label: item.label,
      before: item.before,
      after: item.after,
    }));
}

/** 实现`runOptionLabel`辅助逻辑，集中处理页面展示或状态转换规则。 */
function runOptionLabel(run: PlanningRun): string {
  const statusLabel = runStatusPresentation[run.status]?.label ?? run.status;
  const createdAt = new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(run.created_at));
  return `${createdAt} · 第 ${run.revision_no} 版 · ${statusLabel}`;
}

/** 管理规划项目、Agent运行、实时进度、版本与结果查看。 */
export function PlanningWorkspace() {
  const [projects, setProjects] = useState<PlanningProject[]>([]);
  const [projectView, setProjectView] = useState<ProjectView>("active");
  const [projectKeyword, setProjectKeyword] = useState("");
  const [projectStatusFilter, setProjectStatusFilter] = useState<ProjectStatusFilter>("all");
  const [projectPage, setProjectPage] = useState(1);
  const [projectTotal, setProjectTotal] = useState(0);
  const [projectSummary, setProjectSummary] = useState<PlanningProjectPageSummary>(
    emptyProjectSummary,
  );
  const [selectedProjectId, setSelectedProjectId] = useState<string>();
  const [selectedProjectDetails, setSelectedProjectDetails] = useState<PlanningProject>();
  const [projectRuns, setProjectRuns] = useState<PlanningRun[]>([]);
  const [runDetailsById, setRunDetailsById] = useState<Record<string, PlanningRun>>({});
  const [runPage, setRunPage] = useState(1);
  const [runFocusRevision, setRunFocusRevision] = useState(0);
  const [runTotal, setRunTotal] = useState(0);
  const [runSummary, setRunSummary] = useState<PlanningRunPageSummary>(emptyRunSummary);
  const [approvalTasks, setApprovalTasks] = useState<ApprovalTask[]>([]);
  const [selectedProducts, setSelectedProducts] = useState<SelectedProduct[]>([]);
  const [productInitiatives, setProductInitiatives] = useState<ProductInitiative[]>([]);
  const [activeRun, setActiveRunState] = useState<PlanningRun>();
  const activeRunRef = useRef<PlanningRun | undefined>(undefined);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [validationUpdating, setValidationUpdating] = useState(false);
  const [validationMaterialUpdating, setValidationMaterialUpdating] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [resultOpen, setResultOpen] = useState(false);
  const [nodeDetailOpen, setNodeDetailOpen] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string>();
  const [resultEvidence, setResultEvidence] = useState<PlanningRunEvidence[]>([]);
  const [resultEvidenceLoading, setResultEvidenceLoading] = useState(false);
  const [resultEvidencePage, setResultEvidencePage] = useState(1);
  const [resultEvidenceTotal, setResultEvidenceTotal] = useState(0);
  const [resultEvidenceUnavailableTotal, setResultEvidenceUnavailableTotal] = useState(0);
  const [reports, setReports] = useState<PlanningReport[]>([]);
  const [reportsLoading, setReportsLoading] = useState(false);
  const [reportPage, setReportPage] = useState(1);
  const [reportTotal, setReportTotal] = useState(0);
  const [reportDownloadingId, setReportDownloadingId] = useState<string>();
  const [runTaskStatus, setRunTaskStatus] = useState<AsyncTaskStatus>();
  const [reportTaskStatuses, setReportTaskStatuses] = useState<Record<string, AsyncTaskStatus>>({});
  const [comparisonOpen, setComparisonOpen] = useState(false);
  const [comparisonLeftRunId, setComparisonLeftRunId] = useState<string>();
  const [comparisonRightRunId, setComparisonRightRunId] = useState<string>();
  const [modalOpen, setModalOpen] = useState(false);
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [form] = Form.useForm<ProjectFormValues>();
  const [editForm] = Form.useForm<ProjectFormValues>();
  const [messageApi, contextHolder] = message.useMessage();
  const projectRequestRef = useRef(0);
  const runRequestRef = useRef(0);
  const focusedRunIdRef = useRef<string | undefined>(undefined);
  const rememberRuns = useCallback((runs: PlanningRun[]) => {
    if (runs.length === 0) return;
    setRunDetailsById((current) => {
      const next = { ...current };
      for (const run of runs) {
        next[run.id] = { ...next[run.id], ...run };
      }
      return next;
    });
  }, []);
  const dispatch = useAppDispatch();
  const runState = useAppSelector((state) => state.run);
  const identityState = useAppSelector((state) => state.identity);
  const projectContextState = useAppSelector((state) => state.projectContext);
  const currentProjectContextId = projectContextState.current?.projectId;
  const projectContextHydrated = projectContextState.hydrated;
  const projectContextRevision = projectContextState.revision;
  const canPlan = hasAnyRole(identityState.current, ["admin", "planner"]);
  const projectHasActiveRun = runSummary.active > 0;
  const runIsTerminal = ["completed", "failed", "cancelled", "superseded"].includes(
    activeRun?.status ?? "",
  );
  const reportsNeedPolling = reports.some((report) =>
    ["queued", "processing"].includes(report.status),
  );

  useEffect(() => {
    activeRunRef.current = activeRun;
  }, [activeRun]);

  const syncReportTaskStatuses = useCallback(async (items: PlanningReport[], merge = false) => {
    const taskIds = items.flatMap((item) => (item.celery_task_id ? [item.celery_task_id] : []));
    if (taskIds.length === 0) {
      if (!merge) {
        setReportTaskStatuses({});
      }
      return;
    }
    try {
      const statuses = await getAsyncTaskStatuses(taskIds);
      const nextStatuses = Object.fromEntries(statuses.map((item) => [item.task_id, item]));
      setReportTaskStatuses((current) => (merge ? { ...current, ...nextStatuses } : nextStatuses));
    } catch {
      if (!merge) {
        setReportTaskStatuses({});
      }
    }
  }, []);

  const loadProjects = useCallback(async () => {
    const requestId = ++projectRequestRef.current;
    setLoading(true);
    try {
      const result = await listPlanningProjectsPage({
        archivedOnly: projectView === "archived",
        status: projectStatusFilter,
        keyword: projectKeyword,
        page: projectPage,
        pageSize: projectPageSize,
      });
      if (requestId !== projectRequestRef.current) return;
      setProjects(result.items);
      setProjectTotal(result.total);
      setProjectSummary(result.summary);
      const pageCount = Math.max(1, Math.ceil(result.total / projectPageSize));
      if (projectPage > pageCount) setProjectPage(pageCount);
      setSelectedProjectId((current) => current ?? result.items[0]?.id);
      setSelectedProjectDetails((current) => {
        const refreshed = current
          ? result.items.find((project) => project.id === current.id)
          : undefined;
        return refreshed ?? current ?? result.items[0];
      });
    } catch (error) {
      if (requestId === projectRequestRef.current) {
        messageApi.error(error instanceof Error ? error.message : "无法加载规划项目");
      }
    } finally {
      if (requestId === projectRequestRef.current) setLoading(false);
    }
  }, [messageApi, projectKeyword, projectPage, projectStatusFilter, projectView]);

  const refreshProjects = async () => {
    await loadProjects();
  };

  useEffect(() => {
    const initialLoadTimer = window.setTimeout(() => void loadProjects(), 0);
    return () => {
      projectRequestRef.current += 1;
      window.clearTimeout(initialLoadTimer);
    };
  }, [loadProjects]);

  useEffect(() => {
    const handleFocusPlanningProject = (event: Event) => {
      const detail = (event as CustomEvent<{ projectId?: string; runId?: string }>).detail;
      if (!detail?.projectId) return;
      focusedRunIdRef.current = detail.runId;
      setRunFocusRevision((current) => current + 1);
      setProjectView("active");
      setProjectKeyword("");
      setProjectStatusFilter("all");
      setProjectPage(1);
      setRunPage(1);
      setRunTotal(0);
      setRunSummary(emptyRunSummary);
      setProjectRuns([]);
      setRunDetailsById({});
      setActiveRunState(undefined);
      dispatch(setActiveRun(undefined));
      setSelectedProjectId(detail.projectId);
      void getPlanningProject(detail.projectId)
        .then((project) => {
          setSelectedProjectDetails(project);
          dispatch(
            setProjectContext({
              projectId: project.id,
              projectName: project.name,
              category: project.category,
              targetMarket: project.target_market,
              tenantId: project.tenant_id,
              source: "planning",
            }),
          );
        })
        .catch(() => undefined);
    };
    window.addEventListener("merchpilot:focus-planning-project", handleFocusPlanningProject);
    return () => window.removeEventListener("merchpilot:focus-planning-project", handleFocusPlanningProject);
  }, [dispatch]);

  useEffect(() => {
    const projectId = currentProjectContextId;
    if (!projectContextHydrated || !projectId || projectId === selectedProjectId) return;
    const contextTimer = window.setTimeout(() => {
      focusedRunIdRef.current = undefined;
      setRunFocusRevision((current) => current + 1);
      setProjectView("active");
      setProjectKeyword("");
      setProjectStatusFilter("all");
      setProjectPage(1);
      setRunPage(1);
      setRunTotal(0);
      setRunSummary(emptyRunSummary);
      setProjectRuns([]);
      setRunDetailsById({});
      setActiveRunState(undefined);
      dispatch(setActiveRun(undefined));
      setSelectedProjectId(projectId);
      void getPlanningProject(projectId)
        .then(setSelectedProjectDetails)
        .catch(() => undefined);
    }, 0);
    return () => window.clearTimeout(contextTimer);
  }, [
    currentProjectContextId,
    dispatch,
    projectContextHydrated,
    projectContextRevision,
    selectedProjectId,
  ]);

  useEffect(() => {
    if (!selectedProjectId) {
      return;
    }
    let active = true;
    const refreshRuns = () => {
      const requestId = ++runRequestRef.current;
      void listProjectRunsPage(selectedProjectId, runPage, runPageSize)
        .then((result) => {
          if (!active || requestId !== runRequestRef.current) {
            return;
          }
          setProjectRuns(result.items);
          rememberRuns(result.items);
          setRunTotal(result.total);
          setRunSummary(result.summary);
          const pageCount = Math.max(1, Math.ceil(result.total / runPageSize));
          if (runPage > pageCount) {
            setRunPage(pageCount);
          }
          const focusedRunId = focusedRunIdRef.current;
          if (focusedRunId) {
            const focusedRun = result.items.find((run) => run.id === focusedRunId);
            if (focusedRun) {
              focusedRunIdRef.current = undefined;
              setActiveRunState(focusedRun);
              dispatch(setActiveRun(focusedRun.id));
              dispatch(
                hydrateRunState({
                  status: focusedRun.status,
                  outputKeys: Object.keys(asRecord(focusedRun.result_snapshot?.outputs)),
                  executionSnapshot: focusedRun.execution_snapshot,
                }),
              );
              return;
            }
            void getProjectRun(selectedProjectId, focusedRunId)
              .then((loadedRun) => {
                if (!active || focusedRunIdRef.current !== loadedRun.id) return;
                focusedRunIdRef.current = undefined;
                rememberRuns([loadedRun]);
                setActiveRunState(loadedRun);
                dispatch(setActiveRun(loadedRun.id));
                dispatch(
                  hydrateRunState({
                    status: loadedRun.status,
                    outputKeys: Object.keys(asRecord(loadedRun.result_snapshot?.outputs)),
                    executionSnapshot: loadedRun.execution_snapshot,
                  }),
                );
              })
              .catch(() => {
                if (focusedRunIdRef.current === focusedRunId) {
                  focusedRunIdRef.current = undefined;
                }
              });
          }
          const current = activeRunRef.current;
          const currentRun = current
            ? result.items.find((run) => run.id === current.id)
            : undefined;
          const latestRun = result.items[0];
          let nextRun: PlanningRun | undefined;
          if (
            currentRun?.status === "superseded" &&
            latestRun &&
            latestRun.id !== currentRun.id
          ) {
            nextRun = latestRun;
          } else if (currentRun) {
            nextRun = { ...current, ...currentRun };
          } else if (current?.project_id === selectedProjectId) {
            nextRun = current;
          } else {
            nextRun = latestRun;
          }
          activeRunRef.current = nextRun;
          setActiveRunState(nextRun);
          dispatch(setActiveRun(nextRun?.id));
          if (nextRun) {
            dispatch(
              hydrateRunState({
                status: nextRun.status,
                outputKeys: Object.keys(asRecord(nextRun.result_snapshot?.outputs)),
                executionSnapshot: nextRun.execution_snapshot,
              }),
            );
          }
        })
        .catch(() => undefined);
    };
    refreshRuns();
    const timer = window.setInterval(refreshRuns, 4_000);
    return () => {
      active = false;
      runRequestRef.current += 1;
      window.clearInterval(timer);
    };
  }, [dispatch, rememberRuns, runFocusRevision, runPage, selectedProjectId]);

  useEffect(() => {
    if (!selectedProjectId || !activeRun) {
      return;
    }
    let active = true;
    const loadRunLineage = async () => {
      const knownRuns: Record<string, PlanningRun> = {
        ...runDetailsById,
        ...Object.fromEntries(projectRuns.map((run) => [run.id, run])),
      };
      let parentRunId = activeRun.parent_run_id;
      while (parentRunId && !knownRuns[parentRunId]) {
        const parentRun = await getProjectRun(selectedProjectId, parentRunId);
        if (!active) return;
        knownRuns[parentRun.id] = parentRun;
        rememberRuns([parentRun]);
        parentRunId = parentRun.parent_run_id;
      }
    };
    void loadRunLineage().catch(() => undefined);
    return () => {
      active = false;
    };
  }, [activeRun, projectRuns, rememberRuns, runDetailsById, selectedProjectId]);

  useEffect(() => {
    if (!selectedProjectId) {
      return;
    }
    let active = true;
    const refreshApprovals = () => {
      void listApprovalTasksPage({
        status: "all",
        projectId: selectedProjectId,
        page: 1,
        pageSize: 100,
      })
        .then((result) => {
          if (active) {
            setApprovalTasks(result.items);
          }
        })
        .catch(() => undefined);
    };
    refreshApprovals();
    const timer = window.setInterval(refreshApprovals, 4_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [selectedProjectId]);

  useEffect(() => {
    if (!selectedProjectId) {
      return;
    }
    let active = true;
    const refreshBusinessProgress = () => {
      void Promise.all([
        listSelectedProductsPage({ projectId: selectedProjectId, page: 1, pageSize: 100 }),
        listProductInitiativesPage({ projectId: selectedProjectId, page: 1, pageSize: 100 }),
      ])
        .then(([products, initiatives]) => {
          if (!active) {
            return;
          }
          setSelectedProducts(products.items);
          setProductInitiatives(initiatives.items);
        })
        .catch(() => undefined);
    };
    refreshBusinessProgress();
    const timer = window.setInterval(refreshBusinessProgress, 8_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [selectedProjectId]);

  useEffect(() => {
    if (!activeRun?.id || runIsTerminal) {
      dispatch(setConnectionStatus("idle"));
      return;
    }
    const socket = new RunSocket({
      runId: activeRun.id,
      onEvent: (event) => {
        dispatch(receiveRunEvent(event));
        if (
          ["approval.required", "run.completed", "run.failed", "run.revision_created"].includes(
            event.event_type,
          )
        ) {
          notifyBusinessDataChanged();
        }
        const childRunId = event.payload?.child_run_id;
        if (event.event_type !== "run.revision_created" || typeof childRunId !== "string") {
          return;
        }
        void getProjectRun(activeRun.project_id, childRunId)
          .then((run) => {
            setProjectRuns((current) => [run, ...current.filter((item) => item.id !== run.id)]);
            rememberRuns([run]);
            setActiveRunState(run);
            if (run.celery_task_id) {
              void getAsyncTaskStatuses([run.celery_task_id])
                .then((statuses) => setRunTaskStatus(statuses[0]))
                .catch(() => setRunTaskStatus(undefined));
            } else {
              setRunTaskStatus(undefined);
            }
            dispatch(setActiveRun(run.id));
            dispatch(
              hydrateRunState({
                    status: run.status,
                    outputKeys: Object.keys(asRecord(run.result_snapshot?.outputs)),
                    executionSnapshot: run.execution_snapshot,
              }),
            );
          })
          .catch(() => undefined);
      },
      onStatus: (status) => dispatch(setConnectionStatus(status)),
    });
    socket.connect();
    return () => socket.disconnect();
  }, [activeRun?.id, activeRun?.project_id, dispatch, rememberRuns, runIsTerminal]);

  useEffect(() => {
    if (!activeRun?.id || !activeRun.project_id) {
      return;
    }
    let active = true;
    void getProjectRunEvents(activeRun.project_id, activeRun.id)
      .then((events) => {
        if (active) {
          dispatch(hydrateRunEvents(events));
        }
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [activeRun?.id, activeRun?.project_id, dispatch]);

  useEffect(() => {
    if (!activeRun?.id || !activeRun.project_id) {
      return;
    }
    let active = true;
    const refreshRun = () => {
      void getProjectRun(activeRun.project_id, activeRun.id)
        .then((run) => {
          if (active) {
            setActiveRunState(run);
            rememberRuns([run]);
            setProjectRuns((current) =>
              current.map((item) => (item.id === run.id ? { ...item, ...run } : item)),
            );
            const outputs = asRecord(run.result_snapshot?.outputs);
            dispatch(
              hydrateRunState({
                status: run.status,
                outputKeys: Object.keys(outputs),
                executionSnapshot: run.execution_snapshot,
              }),
            );
          }
        })
        .catch(() => undefined);
    };
    refreshRun();
    const timer = runIsTerminal ? undefined : window.setInterval(refreshRun, 3_000);
    return () => {
      active = false;
      if (timer !== undefined) {
        window.clearInterval(timer);
      }
    };
  }, [activeRun?.id, activeRun?.project_id, dispatch, rememberRuns, runIsTerminal]);

  useEffect(() => {
    const timer = window.setTimeout(() => setReportPage(1), 0);
    return () => window.clearTimeout(timer);
  }, [activeRun?.id]);

  useEffect(() => {
    let active = true;
    const reportProjectId = activeRun?.project_id;
    const reportRunId = activeRun?.id;
    const loadReports = async () => {
      if (!reportRunId || !reportProjectId) {
        setReports([]);
        setReportTotal(0);
        return;
      }
      setReportsLoading(true);
      try {
        const result = await listPlanningReportsPage(
          reportProjectId,
          reportRunId,
          reportPage,
          reportPageSize,
        );
        if (active) {
          const pageCount = Math.max(1, Math.ceil(result.total / reportPageSize));
          setReportTotal(result.total);
          if (reportPage > pageCount) {
            setReportPage(pageCount);
            return;
          }
          setReports(result.items);
          await syncReportTaskStatuses(result.items);
        }
      } catch {
        if (active) {
          setReports([]);
          setReportTaskStatuses({});
        }
      } finally {
        if (active) {
          setReportsLoading(false);
        }
      }
    };
    void loadReports();
    if (!reportProjectId || !reportRunId) {
      return () => {
        active = false;
      };
    }
    const timer = reportsNeedPolling ? window.setInterval(() => {
      void listPlanningReportsPage(reportProjectId, reportRunId, reportPage, reportPageSize)
        .then((result) => {
          if (!active) return;
          setReports(result.items);
          setReportTotal(result.total);
          void syncReportTaskStatuses(result.items);
        })
        .catch(() => undefined);
    }, 4_000) : undefined;
    return () => {
      active = false;
      if (timer !== undefined) {
        window.clearInterval(timer);
      }
    };
  }, [
    activeRun?.id,
    activeRun?.project_id,
    reportPage,
    reportsNeedPolling,
    syncReportTaskStatuses,
  ]);

  const selectedProject = selectedProjectDetails?.id === selectedProjectId
    ? selectedProjectDetails
    : projects.find((project) => project.id === selectedProjectId);
  const currentProjectPage = Math.min(
    projectPage,
    Math.max(1, Math.ceil(projectTotal / projectPageSize)),
  );
  const currentRunPage = Math.min(
    runPage,
    Math.max(1, Math.ceil(runTotal / runPageSize)),
  );
  const runCatalog = useMemo(
    () => Object.values({ ...runDetailsById, ...Object.fromEntries(projectRuns.map((run) => [run.id, run])) }),
    [projectRuns, runDetailsById],
  );
  const projectOptions = useMemo(() => {
    const filtered = projects.map((project) => ({
      value: project.id,
      label: `${project.name} · ${project.category} · ${projectStatusPresentation[project.status]?.label ?? project.status}`,
    }));
    if (selectedProject && !projects.some((project) => project.id === selectedProject.id)) {
      filtered.unshift({
        value: selectedProject.id,
        label: `${selectedProject.name} · ${selectedProject.category} · 当前选中`,
      });
    }
    return filtered;
  }, [projects, selectedProject]);
  const projectStatusOptions = useMemo(() => {
    const counts: Record<string, number> = {
      draft: projectSummary.draft,
      queued: projectSummary.queued,
      running: projectSummary.running,
      approval_required: projectSummary.approval_required,
      completed: projectSummary.completed,
      failed: projectSummary.failed,
      cancelled: projectSummary.cancelled,
    };
    return [
      { value: "all", label: `全部状态（${projectSummary.total}）` },
      ...Object.entries(projectStatusPresentation)
        .filter(([status]) => counts[status])
        .map(([status, presentation]) => ({
          value: status,
          label: `${presentation.label}（${counts[status]}）`,
        })),
    ];
  }, [projectSummary]);
  const projectArchived = Boolean(selectedProject?.archived_at);
  const resultOutputs = asRecord(activeRun?.result_snapshot?.outputs);
  const selectedNodeOutput = selectedNodeId
    ? resultOutputs[nodeOutputKeyById[selectedNodeId]]
    : undefined;
  const concept = asRecord(resultOutputs.concept);
  const scorecard = asRecord(resultOutputs.scorecard);
  const finance = asRecord(resultOutputs.finance);
  const supplier = asRecord(resultOutputs.supplier);
  const evidenceIds = Array.isArray(concept.evidence_ids) ? concept.evidence_ids : [];
  const currentConstraints = asRecord(activeRun?.input_snapshot?.constraints);
  const activeRunLineageIds = useMemo(() => {
    const ids = new Set<string>();
    let current = activeRun;
    while (current && !ids.has(current.id)) {
      ids.add(current.id);
      current = current.parent_run_id
        ? runCatalog.find((run) => run.id === current?.parent_run_id)
        : undefined;
    }
    return ids;
  }, [activeRun, runCatalog]);
  const activeRunApprovals = useMemo(
    () =>
      approvalTasks
        .filter((task) => activeRunLineageIds.has(task.run_id))
        .sort((left, right) => left.created_at.localeCompare(right.created_at)),
    [activeRunLineageIds, approvalTasks],
  );
  const activeRunApproval = [...activeRunApprovals].reverse().find(
    (task) => task.run_id === activeRun?.id,
  ) ?? activeRunApprovals.at(-1);
  const activeSelectedProduct = selectedProducts.find((product) =>
    activeRunLineageIds.has(product.run_id),
  );
  const activeProductInitiative = productInitiatives.find((initiative) =>
    activeSelectedProduct ? initiative.selected_product_id === activeSelectedProduct.id :
      activeRunLineageIds.has(initiative.run_id),
  );

  const runPresentation = useMemo(
    () => runStatusPresentation[activeRun?.status ?? runState.status] ?? {
      color: "default",
      label: activeRun?.status ?? runState.status,
    },
    [activeRun?.status, runState.status],
  );

  const handleNodeSelect = (nodeId: string) => {
    setSelectedNodeId(nodeId);
    setNodeDetailOpen(true);
  };

  const startRun = async (projectId: string) => {
    setSubmitting(true);
    try {
      const run = await startProjectRun(projectId);
      const switchingProject = selectedProjectId !== projectId;
      setSelectedProjectId(projectId);
      setActiveRunState(run);
      rememberRuns([run]);
      setRunPage(1);
      setRunTotal((current) => (switchingProject ? 1 : current + 1));
      setProjectRuns((current) =>
        switchingProject ? [run] : [run, ...current.filter((item) => item.id !== run.id)],
      );
      const project = selectedProject?.id === projectId
        ? selectedProject
        : projects.find((item) => item.id === projectId);
      if (project) {
        dispatch(
          setProjectContext({
            projectId: project.id,
            projectName: project.name,
            category: project.category,
            targetMarket: project.target_market,
            tenantId: project.tenant_id,
            source: "planning",
          }),
        );
      }
      dispatch(setActiveRun(run.id));
      notifyBusinessDataChanged();
      messageApi.success("规划任务已进入执行队列");
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "无法启动规划任务");
    } finally {
      setSubmitting(false);
    }
  };

  const retryRun = async () => {
    if (!activeRun?.project_id || !activeRun.id) {
      return;
    }
    setSubmitting(true);
    try {
      const run = await retryProjectRun(activeRun.project_id, activeRun.id);
      setActiveRunState(run);
      rememberRuns([run]);
      setProjectRuns((current) =>
        current.map((item) => (item.id === run.id ? run : item)),
      );
      dispatch(setActiveRun(run.id));
      dispatch(
        hydrateRunState({
          status: run.status,
          outputKeys: Object.keys(asRecord(run.result_snapshot?.outputs)),
          executionSnapshot: run.execution_snapshot,
        }),
      );
      notifyBusinessDataChanged();
      messageApi.success("已提交恢复任务，将复用已完成节点结果");
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "无法恢复规划任务");
    } finally {
      setSubmitting(false);
    }
  };

  const createAndRun = async (values: ProjectFormValues) => {
    setSubmitting(true);
    try {
      const project = await createPlanningProject({
        name: values.name,
        category: values.category,
        target_market: values.target_market,
        constraints: buildProjectConstraints(values),
      });
      setProjectView("active");
      setProjects((current) => [project, ...current]);
      setSelectedProjectDetails(project);
      notifyBusinessDataChanged();
      setModalOpen(false);
      form.resetFields();
      await startRun(project.id);
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "无法创建规划项目");
    } finally {
      setSubmitting(false);
    }
  };

  const openProjectEdit = () => {
    if (!selectedProject) {
      return;
    }
    editForm.resetFields();
    editForm.setFieldsValue(projectToFormValues(selectedProject));
    setEditModalOpen(true);
  };

  const updateProject = async (values: ProjectFormValues) => {
    if (!selectedProject) {
      return;
    }
    setSubmitting(true);
    try {
      const updated = await updatePlanningProject(selectedProject.id, {
        name: values.name,
        category: values.category,
        target_market: values.target_market,
        constraints: buildProjectConstraints(values, selectedProject.constraints),
      });
      setProjects((current) =>
        current.map((project) => (project.id === updated.id ? updated : project)),
      );
      setSelectedProjectDetails(updated);
      setEditModalOpen(false);
      notifyBusinessDataChanged();
      messageApi.success("项目参数已保存，可启动新一轮规划");
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "无法更新规划项目");
    } finally {
      setSubmitting(false);
    }
  };

  const archiveSelectedProject = () => {
    if (!selectedProject) return;
    Modal.confirm({
      title: "归档规划项目",
      content: `归档“${selectedProject.name}”后，它将从日常工作区和待办中隐藏，但运行、审批、证据和报告历史仍会保留。`,
      okText: "确认归档",
      cancelText: "取消",
      onOk: async () => {
        setSubmitting(true);
        try {
          await archivePlanningProject(selectedProject.id);
          notifyBusinessDataChanged();
          messageApi.success("项目已归档，可在已归档项目中查看和恢复");
          setActiveRunState(undefined);
          setProjectRuns([]);
          setApprovalTasks([]);
          setSelectedProjectId(undefined);
          setSelectedProjectDetails(undefined);
          dispatch(setActiveRun(undefined));
          await refreshProjects();
        } catch (error) {
          messageApi.error(error instanceof Error ? error.message : "无法归档项目");
          throw error;
        } finally {
          setSubmitting(false);
        }
      },
    });
  };

  const restoreSelectedProject = async () => {
    if (!selectedProject) return;
    setSubmitting(true);
    try {
      await restorePlanningProject(selectedProject.id);
      notifyBusinessDataChanged();
      messageApi.success("项目已恢复到当前项目列表");
      setActiveRunState(undefined);
      setProjectRuns([]);
      setApprovalTasks([]);
      setSelectedProjectId(undefined);
      setSelectedProjectDetails(undefined);
      dispatch(setActiveRun(undefined));
      await refreshProjects();
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "无法恢复项目");
    } finally {
      setSubmitting(false);
    }
  };

  const exportActiveRun = async () => {
    if (!selectedProject || !activeRun?.result_snapshot) {
      return;
    }
    setExporting(true);
    const messageKey = "planning-report";
    messageApi.open({ key: messageKey, type: "loading", content: "正在生成 XLSX 报告…", duration: 0 });
    try {
      let report = await createPlanningReport(selectedProject.id, activeRun.id);
      setReportPage(1);
      setReportTotal((current) => current + 1);
      setReports((current) =>
        [report, ...current.filter((item) => item.id !== report.id)].slice(0, reportPageSize),
      );
      if (report.celery_task_id) {
        void syncReportTaskStatuses([report], true);
      }
      for (let attempt = 0; attempt < 60 && ["queued", "processing"].includes(report.status); attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 1_000));
        report = await getPlanningReport(report.id);
        setReports((current) => current.map((item) => item.id === report.id ? report : item));
        if (report.celery_task_id) {
          void syncReportTaskStatuses([report], true);
        }
      }
      if (report.status !== "completed") {
        throw new Error(report.error_message ?? "报告生成超时，请稍后重试");
      }
      const { blob, filename } = await downloadPlanningReport(report.id);
      saveBlob(blob, filename);
      messageApi.open({ key: messageKey, type: "success", content: "规划报告已生成并下载" });
    } catch (error) {
      messageApi.open({
        key: messageKey,
        type: "error",
        content: error instanceof Error ? error.message : "规划报告导出失败",
      });
    } finally {
      setExporting(false);
    }
  };

  const downloadReport = async (report: PlanningReport) => {
    if (report.status !== "completed") {
      return;
    }
    setReportDownloadingId(report.id);
    try {
      const { blob, filename } = await downloadPlanningReport(report.id);
      saveBlob(blob, filename);
      messageApi.success("规划报告已下载");
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "规划报告下载失败");
    } finally {
      setReportDownloadingId(undefined);
    }
  };

  const openRunResult = async () => {
    if (!selectedProject || !activeRun?.result_snapshot) {
      return;
    }
    setResultOpen(true);
    setResultEvidencePage(1);
    setResultEvidenceLoading(true);
    try {
      const result = await listProjectRunEvidencePage(
        selectedProject.id,
        activeRun.id,
        1,
        evidencePageSize,
      );
      setResultEvidence(result.items);
      setResultEvidenceTotal(result.total);
      setResultEvidenceUnavailableTotal(result.unavailable_total);
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "无法加载证据详情");
      setResultEvidence([]);
      setResultEvidenceTotal(0);
      setResultEvidenceUnavailableTotal(0);
    } finally {
      setResultEvidenceLoading(false);
    }
  };

  const loadResultEvidencePage = async (pageValue: number) => {
    if (!selectedProject || !activeRun) return;
    setResultEvidenceLoading(true);
    try {
      const result = await listProjectRunEvidencePage(
        selectedProject.id,
        activeRun.id,
        pageValue,
        evidencePageSize,
      );
      setResultEvidence(result.items);
      setResultEvidencePage(result.page);
      setResultEvidenceTotal(result.total);
      setResultEvidenceUnavailableTotal(result.unavailable_total);
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "无法加载证据详情");
    } finally {
      setResultEvidenceLoading(false);
    }
  };

  const handleResultNextAction = (action: PlanningResultNextAction) => {
    setResultOpen(false);
    window.setTimeout(() => {
      const sectionId = action === "approval"
        ? "approval-panel"
        : action === "selected-products"
          ? "selected-product-panel"
          : "product-initiative-panel";
      document.getElementById(sectionId)?.scrollIntoView({ behavior: "smooth", block: "start" });
      if (action === "approval") {
        window.dispatchEvent(
          new CustomEvent("merchpilot:focus-approval", {
            detail: {
              kind: "planning",
              taskId: activeRunApproval?.id,
              status: activeRunApproval
                ? activeRunApproval.status === "pending" ? "pending" : "processed"
                : undefined,
            },
          }),
        );
      } else if (action === "selected-products") {
        window.dispatchEvent(
          new CustomEvent("merchpilot:focus-selected-products", {
            detail: {
              productId: activeSelectedProduct?.id,
              status: activeSelectedProduct?.status === "paused"
                ? "paused"
                : activeSelectedProduct?.status === "cancelled"
                  ? "cancelled"
                  : undefined,
              validation: activeSelectedProduct?.validation_status === "ready" ? "ready" : "pending",
            },
          }),
        );
      } else if (action === "initiative-create") {
        window.dispatchEvent(
          new CustomEvent("merchpilot:focus-initiative-create", {
            detail: { selectedProductId: activeSelectedProduct?.id },
          }),
        );
      } else {
        window.dispatchEvent(
          new CustomEvent("merchpilot:focus-initiative", {
            detail: { initiativeId: activeProductInitiative?.id },
          }),
        );
      }
    }, 150);
  };

  const updateValidationGate = async (
    candidateId: string,
    gateId: string,
    gateStatus: ValidationGateStatus,
    note: string,
  ) => {
    if (!selectedProject || !activeRun) {
      return;
    }
    setValidationUpdating(true);
    try {
      const updatedRun = await updateRunValidationPlan(
        selectedProject.id,
        activeRun.id,
        candidateId,
        [{ gate_id: gateId, status: gateStatus, note }],
      );
      setActiveRunState(updatedRun);
      setProjectRuns((current) => current.map((run) => (
        run.id === updatedRun.id ? updatedRun : run
      )));
      notifyBusinessDataChanged();
      messageApi.success("验证清单已保存");
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "验证清单保存失败");
    } finally {
      setValidationUpdating(false);
    }
  };

  const uploadValidationMaterial = async (
    candidateId: string,
    gateId: string,
    file: File,
    note: string,
  ) => {
    if (!selectedProject || !activeRun) {
      return;
    }
    setValidationMaterialUpdating(true);
    try {
      const updatedRun = await uploadRunValidationMaterial(
        selectedProject.id,
        activeRun.id,
        candidateId,
        gateId,
        file,
        note,
      );
      setActiveRunState(updatedRun);
      setProjectRuns((current) => current.map((run) => (
        run.id === updatedRun.id ? updatedRun : run
      )));
      notifyBusinessDataChanged();
      messageApi.success("验证材料已上传");
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "验证材料上传失败");
    } finally {
      setValidationMaterialUpdating(false);
    }
  };

  const deleteValidationMaterial = async (materialId: string) => {
    if (!selectedProject || !activeRun) {
      return;
    }
    setValidationMaterialUpdating(true);
    try {
      const updatedRun = await deleteRunValidationMaterial(
        selectedProject.id,
        activeRun.id,
        materialId,
      );
      setActiveRunState(updatedRun);
      setProjectRuns((current) => current.map((run) => (
        run.id === updatedRun.id ? updatedRun : run
      )));
      notifyBusinessDataChanged();
      messageApi.success("验证材料已删除");
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "验证材料删除失败");
    } finally {
      setValidationMaterialUpdating(false);
    }
  };

  const downloadValidationMaterial = async (materialId: string, filename: string) => {
    if (!selectedProject || !activeRun) {
      return;
    }
    setValidationMaterialUpdating(true);
    try {
      const blob = await downloadRunValidationMaterial(
        selectedProject.id,
        activeRun.id,
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
    } finally {
      setValidationMaterialUpdating(false);
    }
  };

  const openRunComparison = () => {
    if (!activeRun || runTotal < 2) {
      return;
    }
    const parentRun = activeRun.parent_run_id
      ? runCatalog.find((run) => run.id === activeRun.parent_run_id)
      : undefined;
    const childRun = runCatalog.find((run) => run.parent_run_id === activeRun.id);
    const otherRun = parentRun ?? childRun ?? runCatalog.find((run) => run.id !== activeRun.id);
    if (!otherRun) {
      return;
    }
    if (otherRun.revision_no < activeRun.revision_no) {
      setComparisonLeftRunId(otherRun.id);
      setComparisonRightRunId(activeRun.id);
    } else {
      setComparisonLeftRunId(activeRun.id);
      setComparisonRightRunId(otherRun.id);
    }
    setComparisonOpen(true);
  };

  return (
    <article className="panel planning-workspace" id="planning-workspace">
      {contextHolder}
      <div className="panel-header">
        <div>
          <h2 className="panel-title">Multi-Agent 商品规划</h2>
          <p className="panel-description">创建项目后实时追踪研究、概念、财务、评分和线上审批</p>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => void refreshProjects()} loading={loading}>
            刷新
          </Button>
          {identityState.status === "ready" && !canPlan && <Tag>只读模式</Tag>}
          <Button
            type="primary"
            icon={<PlusOutlined />}
            disabled={!canPlan}
            title={identityState.status === "ready" && !canPlan ? "需要规划人员或管理员角色" : undefined}
            onClick={() => {
              setProjectView("active");
              setModalOpen(true);
            }}
          >
            新建规划项目
          </Button>
        </Space>
      </div>

      <div className="planning-toolbar">
        <Select<ProjectView>
          value={projectView}
          options={[
            { value: "active", label: "当前项目" },
            { value: "archived", label: "已归档" },
          ]}
          onChange={(value) => {
            setProjectView(value);
            setProjectPage(1);
            setRunPage(1);
            setSelectedProjectId(undefined);
            setSelectedProjectDetails(undefined);
            setActiveRunState(undefined);
            setProjectRuns([]);
            setApprovalTasks([]);
            setLoading(true);
            dispatch(setActiveRun(undefined));
          }}
          className="project-view-select"
        />
        <Input
          value={projectKeyword}
          allowClear
          placeholder="搜索项目、品类或市场"
          onChange={(event) => {
            setProjectKeyword(event.target.value);
            setProjectPage(1);
          }}
          className="project-search"
        />
        <Select<ProjectStatusFilter>
          value={projectStatusFilter}
          options={projectStatusOptions}
          onChange={(value) => {
            setProjectStatusFilter(value);
            setProjectPage(1);
          }}
          className="project-status-filter"
        />
        <Select
          value={selectedProjectId}
          placeholder="选择规划项目"
          options={projectOptions}
          onChange={(projectId) => {
            setActiveRunState(undefined);
            setProjectRuns([]);
            setRunPage(1);
            setRunTotal(0);
            setRunSummary(emptyRunSummary);
            setRunDetailsById({});
            setApprovalTasks([]);
            dispatch(setActiveRun(undefined));
            const project = projects.find((item) => item.id === projectId);
            setSelectedProjectId(projectId);
            setSelectedProjectDetails(project);
            if (project) {
              dispatch(
                setProjectContext({
                  projectId: project.id,
                  projectName: project.name,
                  category: project.category,
                  targetMarket: project.target_market,
                  tenantId: project.tenant_id,
                  source: "planning",
                }),
              );
            }
          }}
          loading={loading}
          className="project-select"
          notFoundContent={
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={
                projects.length === 0
                  ? projectView === "archived" ? "暂无归档项目" : "暂无项目"
                  : "没有匹配的项目"
              }
            />
          }
        />
        <span className="project-filter-summary">
          显示 {projects.length} / {projectTotal} 个项目
        </span>
        <Pagination
          className="project-pagination"
          current={currentProjectPage}
          pageSize={projectPageSize}
          total={projectTotal}
          showSizeChanger={false}
          hideOnSinglePage
          showTotal={(total, range) => `${range[0]}-${range[1]} / ${total}`}
          onChange={setProjectPage}
        />
        <span className="run-history-summary">
          运行 {projectRuns.length} / {runTotal}
          {runSummary.active > 0 ? ` · 执行中 ${runSummary.active}` : ""}
        </span>
        <Select
          value={activeRun?.id}
          placeholder="运行历史"
          options={[
            ...(activeRun && !projectRuns.some((run) => run.id === activeRun.id)
              ? [{ value: activeRun.id, label: `${runOptionLabel(activeRun)} · 当前选中` }]
              : []),
            ...projectRuns.map((run) => ({ value: run.id, label: runOptionLabel(run) })),
          ]}
          onChange={(runId) => {
            const run = projectRuns.find((item) => item.id === runId);
            if (!run) {
              if (!selectedProjectId) return;
              void getProjectRun(selectedProjectId, runId)
                .then((loadedRun) => {
                  setActiveRunState(loadedRun);
                  dispatch(setActiveRun(loadedRun.id));
                  dispatch(
                    hydrateRunState({
                      status: loadedRun.status,
                      outputKeys: Object.keys(asRecord(loadedRun.result_snapshot?.outputs)),
                      executionSnapshot: loadedRun.execution_snapshot,
                    }),
                  );
                })
                .catch(() => messageApi.error("无法加载运行版本"));
              return;
            }
            setActiveRunState(run);
            dispatch(setActiveRun(run.id));
            dispatch(
              hydrateRunState({
                status: run.status,
                outputKeys: Object.keys(asRecord(run.result_snapshot?.outputs)),
                executionSnapshot: run.execution_snapshot,
              }),
            );
          }}
          disabled={projectRuns.length === 0}
          className="run-history-select"
        />
        <Pagination
          className="run-pagination"
          current={currentRunPage}
          pageSize={runPageSize}
          total={runTotal}
          showSizeChanger={false}
          hideOnSinglePage
          showTotal={(total, range) => `${range[0]}-${range[1]} / ${total}`}
          onChange={setRunPage}
        />
        <Button
          icon={<EditOutlined />}
          disabled={!canPlan || !selectedProject || projectHasActiveRun || projectArchived}
          title={identityState.status === "ready" && !canPlan ? "需要规划人员或管理员角色" : undefined}
          onClick={openProjectEdit}
        >
          编辑参数
        </Button>
        <Button
          icon={<RocketOutlined />}
          disabled={!canPlan || !selectedProjectId || projectHasActiveRun || projectArchived}
          title={identityState.status === "ready" && !canPlan ? "需要规划人员或管理员角色" : undefined}
          loading={submitting}
          onClick={() => selectedProjectId && void startRun(selectedProjectId)}
        >
          {activeRun ? "重新运行" : "启动 Agent"}
        </Button>
        <Button
          icon={<RedoOutlined />}
          disabled={!canPlan || activeRun?.status !== "failed" || projectArchived}
          loading={submitting}
          title="保留已完成节点结果，从失败节点继续"
          onClick={() => void retryRun()}
        >
          恢复失败任务
        </Button>
        <Button
          icon={<EyeOutlined />}
          disabled={!activeRun?.result_snapshot}
          onClick={() => void openRunResult()}
        >
          查看完整方案
        </Button>
        <Button
          icon={<SwapOutlined />}
          disabled={!activeRun || runTotal < 2}
          onClick={openRunComparison}
        >
          版本对比
        </Button>
        <Button
          icon={<FileExcelOutlined />}
          disabled={!canPlan || !activeRun?.result_snapshot}
          title={identityState.status === "ready" && !canPlan ? "需要规划人员或管理员角色" : undefined}
          loading={exporting}
          onClick={() => void exportActiveRun()}
        >
          导出 XLSX
        </Button>
        {projectView === "active" ? (
          <Button
            icon={<FolderOutlined />}
            disabled={!canPlan || !selectedProject || projectHasActiveRun}
            loading={submitting}
            onClick={archiveSelectedProject}
          >
            归档项目
          </Button>
        ) : (
          <Button
            type="primary"
            ghost
            icon={<RollbackOutlined />}
            disabled={!canPlan || !selectedProject}
            loading={submitting}
            onClick={() => void restoreSelectedProject()}
          >
            恢复项目
          </Button>
        )}
        {activeRun && <Tag color={runPresentation.color}>{runPresentation.label}</Tag>}
        {runTaskStatus ? <Tag color={asyncTaskColor(runTaskStatus)}>
          任务：{runTaskStatus.state_label}
        </Tag> : null}
        {projectArchived ? <Tag>已归档 · 只读</Tag> : null}
      </div>

      {selectedProject ? (
        <div className="run-overview">
          <Descriptions size="small" column={5} colon={false}>
            <Descriptions.Item label="项目">{selectedProject.name}</Descriptions.Item>
            <Descriptions.Item label="品类">{selectedProject.category}</Descriptions.Item>
            <Descriptions.Item label="目标市场">{selectedProject.target_market}</Descriptions.Item>
            <Descriptions.Item label="证据数量">{evidenceIds.length}</Descriptions.Item>
            <Descriptions.Item label="运行版本">
              第 {activeRun?.revision_no ?? 1} 版
              {activeRun?.parent_run_id ? ` · 基于 ${activeRun.parent_run_id.slice(-8)}` : ""}
            </Descriptions.Item>
          </Descriptions>
          {activeRun?.status === "cancelled" ? (
            <Alert
              type="warning"
              showIcon
              message="上一轮方案未通过审批"
              description="可以编辑项目参数后重新运行 Agent；历史运行和审批记录会继续保留。"
              className="run-state-alert"
            />
          ) : null}
          {activeRun?.status === "failed" ? (
            <Alert
              type="error"
              showIcon
              message="上一轮规划执行失败"
              description="请查看失败原因，修正参数或依赖服务后重新运行。"
              className="run-state-alert"
            />
          ) : null}
          {activeRun?.error_message && <div className="run-error">{activeRun.error_message}</div>}
          {activeRun && Object.keys(currentConstraints).length > 0 ? (
            <div className="run-constraint-summary">
              <span className="run-constraint-title">当前运行参数</span>
              <div className="run-constraint-tags">
                {Object.entries(currentConstraints).map(([key, value]) => (
                  <Tag key={key}>
                    {constraintLabels[key] ?? key}：{formatConstraintValue(key, value)}
                  </Tag>
                ))}
              </div>
            </div>
          ) : null}
          {activeRunApprovals.length > 0 ? (
            <div className="approval-history">
              <div className="approval-history-heading">
                <div>
                  <strong>审批轨迹</strong>
                  <span>当前版本及父版本的线上审批与修订记录</span>
                </div>
                <Tag>{activeRunApprovals.length} 轮</Tag>
              </div>
              <div className="approval-history-list">
                {activeRunApprovals.map((task, index) => {
                  const presentation =
                    approvalStatusPresentation[task.status] ?? {
                      color: "default",
                      label: task.status,
                    };
                  const decision = asRecord(task.decision);
                  const comment = typeof decision.comment === "string" ? decision.comment : "";
                  const diffs = constraintDiffs(task);
                  return (
                    <div className="approval-history-item" key={task.id}>
                      <div className="approval-history-meta">
          <strong>
                          第 {runCatalog.find((run) => run.id === task.run_id)?.revision_no ?? index + 1} 版审批
                        </strong>
                        <Tag color={presentation.color}>{presentation.label}</Tag>
                        <span>{formatDateTime(task.created_at)}</span>
                      </div>
                      {diffs.length > 0 ? (
                        <div className="approval-history-diff">
                          <span className="approval-history-label">本次修订参数</span>
                          <div className="constraint-diff-grid">
                            {diffs.map((diff) => (
                              <div className="constraint-diff-row" key={diff.key}>
                                <span>{diff.label}</span>
                                <b>{diff.before}</b>
                                <span className="constraint-diff-arrow">→</span>
                                <b>{diff.after}</b>
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : null}
                      {comment ? <div className="approval-history-comment">审批意见：{comment}</div> : null}
                      {task.status === "pending" ? (
                        <div className="approval-history-pending">等待业务负责人在线处理</div>
                      ) : (
                        <div className="approval-history-operator">
                          {task.decided_by ? `处理人：${task.decided_by}` : "处理人：系统记录"}
                          {task.decided_at ? ` · ${formatDateTime(task.decided_at)}` : ""}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ) : null}
        </div>
      ) : (
        <Empty description="创建第一个商品规划项目后开始运行 Agent" />
      )}

      <AgentMesh
        statuses={runState.nodeStatuses}
        details={runState.nodeDetails}
        onNodeSelect={handleNodeSelect}
      />

      <RunExecutionTimeline
        statuses={runState.nodeStatuses}
        details={runState.nodeDetails}
        events={runState.events}
      />

      <AgentNodeDetailDrawer
        open={nodeDetailOpen}
        nodeId={selectedNodeId}
        status={selectedNodeId ? runState.nodeStatuses[selectedNodeId] : undefined}
        execution={selectedNodeId ? runState.nodeDetails[selectedNodeId] : undefined}
        output={selectedNodeOutput}
        onClose={() => setNodeDetailOpen(false)}
      />

      {activeRun?.result_snapshot && (
        <div className="run-result-strip">
          <span>运行 ID：{activeRun.id}</span>
          <span>机会分：{typeof scorecard.score === "number" ? scorecard.score : "待计算"}</span>
          <span>结论状态：{typeof scorecard.status === "string" ? scorecard.status : "等待输出"}</span>
          <span>预计毛利率：{formatPercent(finance.margin_rate)}</span>
          <span>
            盈亏平衡：
            {typeof finance.break_even_units === "number"
              ? `${finance.break_even_units} 件`
              : "待计算"}
          </span>
          <span>
            供应风险：{typeof supplier.risk_level === "string" ? supplier.risk_level : "待评估"}
          </span>
        </div>
      )}

      {activeRun?.result_snapshot ? (
        <section className="report-history-panel" aria-label="规划报告历史">
          <div className="report-history-heading">
            <div>
              <strong>规划报告历史</strong>
              <span>当前运行版本的 XLSX 导出记录，可在生成完成后重复下载</span>
            </div>
            <Tag>{reportTotal} 份</Tag>
          </div>
          {reportsLoading ? (
            <div className="muted-text">正在加载报告记录…</div>
          ) : reports.length === 0 ? (
            <div className="muted-text">当前运行尚未生成报告，可点击上方“导出 XLSX”。</div>
          ) : (
            <div className="report-history-list">
              {reports.map((report) => {
                const presentation = reportStatusPresentation[report.status] ?? {
                  color: "default",
                  label: report.status,
                };
                const taskStatus = report.celery_task_id
                  ? reportTaskStatuses[report.celery_task_id]
                  : undefined;
                return (
                  <div className="report-history-item" key={report.id}>
                    <div>
                      <strong>{report.format.toUpperCase()} 商品规划报告</strong>
                      <span>
                        {formatDateTime(report.created_at)} · 创建人 {report.created_by}
                        {report.celery_task_id ? ` · 任务编号 ${report.celery_task_id}` : ""}
                      </span>
                      {report.status === "failed" && report.error_message ? (
                        <small>{report.error_message}</small>
                      ) : null}
                    </div>
                    <Space size={8}>
                      <Tag color={presentation.color}>{presentation.label}</Tag>
                      {taskStatus ? (
                        <Tag color={asyncTaskColor(taskStatus)}>
                          任务：{taskStatus.state_label}
                        </Tag>
                      ) : null}
                      <Button
                        size="small"
                        icon={<DownloadOutlined />}
                        disabled={report.status !== "completed"}
                        loading={reportDownloadingId === report.id}
                        onClick={() => void downloadReport(report)}
                      >
                        下载
                      </Button>
                    </Space>
                  </div>
                );
              })}
            </div>
          )}
          {reportTotal > reportPageSize ? (
            <Pagination
              current={reportPage}
              pageSize={reportPageSize}
              total={reportTotal}
              showSizeChanger={false}
              showTotal={(total) => `共 ${total} 份报告`}
              onChange={setReportPage}
            />
          ) : null}
        </section>
      ) : null}

      <Drawer
        title={selectedProject ? `规划方案｜${selectedProject.name}` : "规划方案"}
        size="min(1180px, 96vw)"
        open={resultOpen}
        onClose={() => setResultOpen(false)}
      >
          <PlanningResultView
          key={activeRun?.id}
          snapshot={activeRun?.result_snapshot}
          evidence={resultEvidence}
          evidenceLoading={resultEvidenceLoading}
          evidencePage={resultEvidencePage}
          evidencePageSize={evidencePageSize}
          evidenceTotal={resultEvidenceTotal}
          evidenceUnavailableTotal={resultEvidenceUnavailableTotal}
          onEvidencePageChange={(pageValue) => void loadResultEvidencePage(pageValue)}
          projectName={selectedProject?.name}
          category={selectedProject?.category}
          targetMarket={selectedProject?.target_market}
          approvalStatus={activeRunApproval?.status}
          selectedProductStatus={activeSelectedProduct?.status}
          selectedProductValidationStatus={activeSelectedProduct?.validation_status}
          initiativeStatus={activeProductInitiative?.status}
          onNextAction={handleResultNextAction}
          onValidationPlanUpdate={canPlan && !projectArchived ? updateValidationGate : undefined}
          validationUpdating={validationUpdating}
          onValidationMaterialUpload={canPlan && !projectArchived ? uploadValidationMaterial : undefined}
          onValidationMaterialDelete={canPlan && !projectArchived ? deleteValidationMaterial : undefined}
          onValidationMaterialDownload={downloadValidationMaterial}
          validationMaterialUpdating={validationMaterialUpdating}
        />
      </Drawer>

      <RunVersionComparison
        open={comparisonOpen}
        projectId={selectedProjectId}
        runs={runCatalog}
        leftRunId={comparisonLeftRunId}
        rightRunId={comparisonRightRunId}
        onLeftRunChange={setComparisonLeftRunId}
        onRightRunChange={setComparisonRightRunId}
        onClose={() => setComparisonOpen(false)}
      />

      <Modal
        title="新建商品规划项目"
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
        confirmLoading={submitting}
        okButtonProps={{ disabled: !canPlan }}
        okText="创建并启动"
        cancelText="取消"
        width={760}
      >
        <Form form={form} layout="vertical" onFinish={(values) => void createAndRun(values)}>
          <ProjectFormFields />
        </Form>
      </Modal>

      <Modal
        title="编辑商品规划参数"
        open={editModalOpen}
        onCancel={() => setEditModalOpen(false)}
        onOk={() => editForm.submit()}
        confirmLoading={submitting}
        okButtonProps={{ disabled: !canPlan }}
        okText="保存参数"
        cancelText="取消"
        width={760}
      >
        <Form form={editForm} layout="vertical" onFinish={(values) => void updateProject(values)}>
          <ProjectFormFields />
        </Form>
      </Modal>
    </article>
  );
}
