/**
 * 文件职责：提供跨模块当前项目选择、持久化、信息补全和连续业务跳转入口。
 */

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRightOutlined,
  CloseOutlined,
  DeploymentUnitOutlined,
  LinkOutlined,
  ProductOutlined,
  ProjectOutlined,
  RocketOutlined,
  SafetyCertificateOutlined,
} from "@ant-design/icons";
import { Button, Progress, Select, Tag } from "antd";

import { BUSINESS_DATA_CHANGED_EVENT } from "@/lib/business-events";
import {
  listProjectLifecyclesPage,
  ProjectLifecycle,
  ProjectLifecycleStage,
} from "@/lib/http/analytics";
import {
  getPlanningProject,
  listPlanningProjectsPage,
  PlanningProject,
} from "@/lib/http/planning";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { hasAnyRole } from "@/store/identity-slice";
import {
  clearProjectContext,
  hydrateProjectContext,
  ProjectContextValue,
  setProjectContext,
} from "@/store/project-context-slice";

/** 定义当前项目在浏览器中的持久化键，刷新或切换模块后仍能继续同一业务主线。 */
const PROJECT_CONTEXT_STORAGE_KEY = "merchpilot_project_context";
/** 定义项目下拉单次远程搜索数量，避免将全部项目加载到浏览器。 */
const projectContextOptionLimit = 20;

/** 从网址查询参数读取当前项目，供分享链接和浏览器前进后退恢复使用。 */
function readProjectIdFromUrl(): string | undefined {
  if (typeof window === "undefined") return undefined;
  return new URLSearchParams(window.location.search).get("project_id")?.trim() || undefined;
}

/** 将当前项目写入网址查询参数，同时保留现有模块 hash 和其他查询参数。 */
function syncProjectIdToUrl(
  projectId?: string,
  historyMode: "push" | "replace" = "replace",
) {
  if (typeof window === "undefined") return;
  const searchParams = new URLSearchParams(window.location.search);
  if (projectId) searchParams.set("project_id", projectId);
  else searchParams.delete("project_id");
  const search = searchParams.toString();
  const nextUrl = `${window.location.pathname}${search ? `?${search}` : ""}${window.location.hash}`;
  const currentUrl = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (nextUrl === currentUrl) return;
  if (historyMode === "push") window.history.pushState(null, "", nextUrl);
  else window.history.replaceState(null, "", nextUrl);
}

/** 优先从分享网址恢复项目，其次读取当前租户的浏览器本地上下文。 */
function readInitialProjectContext(tenantId?: string): ProjectContextValue | undefined {
  const projectId = readProjectIdFromUrl();
  if (projectId) return { projectId, tenantId, source: "url" };
  return readStoredProjectContext(tenantId);
}

/** 生成包含当前项目和模块位置的可分享链接。 */
function currentProjectLink(projectId: string): string {
  const url = new URL(window.location.href);
  url.searchParams.set("project_id", projectId);
  return url.toString();
}

/** 定义闭环健康状态的中文展示和 Ant Design 色彩。 */
const lifecycleHealthPresentation: Record<
  ProjectLifecycle["health"],
  { color: string; label: string; strokeColor: string }
> = {
  on_track: { color: "processing", label: "推进正常", strokeColor: "#195bff" },
  attention: { color: "warning", label: "等待处理", strokeColor: "#d97706" },
  blocked: { color: "error", label: "存在阻断", strokeColor: "#dc2626" },
  complete: { color: "success", label: "闭环完成", strokeColor: "#159957" },
};

/** 安全解析本地项目上下文，忽略旧版本、损坏内容和其他租户数据。 */
function readStoredProjectContext(tenantId?: string): ProjectContextValue | undefined {
  if (typeof window === "undefined") return undefined;
  try {
    const rawValue = window.localStorage.getItem(PROJECT_CONTEXT_STORAGE_KEY);
    if (!rawValue) return undefined;
    const value = JSON.parse(rawValue) as ProjectContextValue;
    if (!value.projectId || (value.tenantId && tenantId && value.tenantId !== tenantId)) {
      return undefined;
    }
    return { ...value, tenantId, source: "restored" };
  } catch {
    return undefined;
  }
}

/** 把规划项目转换为跨模块共享上下文，统一字段命名和来源标记。 */
function projectContextFromProject(
  project: PlanningProject,
  tenantId: string | undefined,
): ProjectContextValue {
  return {
    projectId: project.id,
    projectName: project.name,
    category: project.category,
    targetMarket: project.target_market,
    tenantId,
    source: "context-bar",
  };
}

/** 发送当前项目的跨模块定位事件，由 DashboardShell 负责切换和首次挂载补发。 */
function openProjectContextModule(
  moduleKey: "planning" | "approval" | "selection" | "initiative",
  projectId: string,
) {
  if (moduleKey === "planning") {
    window.dispatchEvent(
      new CustomEvent("merchpilot:focus-planning-project", { detail: { projectId } }),
    );
    return;
  }
  if (moduleKey === "approval") {
    window.dispatchEvent(
      new CustomEvent("merchpilot:focus-approval", {
        detail: { kind: "planning", projectId, status: "all" },
      }),
    );
    return;
  }
  if (moduleKey === "selection") {
    window.dispatchEvent(
      new CustomEvent("merchpilot:focus-selected-products", {
        detail: { projectId, status: "all" },
      }),
    );
    return;
  }
  window.dispatchEvent(
    new CustomEvent("merchpilot:focus-initiative", { detail: { projectId } }),
  );
}

/** 根据当前角色返回闭环下一步按钮文案，保留无操作权限角色的只读查看入口。 */
function lifecycleActionLabel(
  lifecycle: ProjectLifecycle,
  canManage: boolean,
  canApprove: boolean,
): string {
  if (lifecycle.next_action_type === "planning-project") {
    return canManage ? lifecycle.next_action_label : "查看规划详情";
  }
  if (lifecycle.next_action_type === "planning-approval") {
    return canApprove ? "处理规划审批" : "查看审批状态";
  }
  if (lifecycle.next_action_type === "selected-product") {
    return canManage ? lifecycle.next_action_label : "查看选品验证";
  }
  if (lifecycle.next_action_type === "initiative-create") {
    return canManage ? lifecycle.next_action_label : "查看待立项选品";
  }
  if (lifecycle.next_action_type === "launch-review") {
    return canApprove ? "处理上市评审" : "查看上市评审";
  }
  return canManage ? lifecycle.next_action_label : "查看上市推进";
}

/** 打开当前项目推导出的角色化下一步，继续复用各模块已有的精确定位事件。 */
function openLifecycleNextAction(
  lifecycle: ProjectLifecycle,
  canManage: boolean,
) {
  if (lifecycle.next_action_type === "planning-project") {
    window.dispatchEvent(new CustomEvent("merchpilot:focus-planning-project", {
      detail: { projectId: lifecycle.project_id, runId: lifecycle.run_id ?? undefined },
    }));
    return;
  }
  if (lifecycle.next_action_type === "planning-approval") {
    window.dispatchEvent(new CustomEvent("merchpilot:focus-approval", {
      detail: { kind: "planning", taskId: lifecycle.next_action_id },
    }));
    return;
  }
  if (lifecycle.next_action_type === "selected-product") {
    window.dispatchEvent(new CustomEvent("merchpilot:focus-selected-products", {
      detail: {
        productId: lifecycle.next_action_id,
        validation: lifecycle.validation_status === "ready" ? "ready" : "pending",
      },
    }));
    return;
  }
  if (lifecycle.next_action_type === "initiative-create") {
    if (!canManage) {
      window.dispatchEvent(new CustomEvent("merchpilot:focus-selected-products", {
        detail: { productId: lifecycle.selected_product_id ?? lifecycle.next_action_id },
      }));
      return;
    }
    window.dispatchEvent(new CustomEvent("merchpilot:focus-initiative-create", {
      detail: { selectedProductId: lifecycle.next_action_id },
    }));
    return;
  }
  if (lifecycle.next_action_type === "launch-review") {
    window.dispatchEvent(new CustomEvent("merchpilot:focus-approval", {
      detail: { kind: "launch-review", reviewId: lifecycle.next_action_id },
    }));
    return;
  }
  window.dispatchEvent(new CustomEvent("merchpilot:focus-initiative", {
    detail: { initiativeId: lifecycle.next_action_id },
  }));
}

/** 从顶部闭环进度节点打开该阶段对应的具体业务记录。 */
function openLifecycleStage(lifecycle: ProjectLifecycle, stage: ProjectLifecycleStage) {
  if (!stage.entity_id) return;
  if (stage.key === "project") {
    openProjectContextModule("planning", lifecycle.project_id);
    return;
  }
  if (stage.key === "agent") {
    window.dispatchEvent(new CustomEvent("merchpilot:focus-planning-project", {
      detail: { projectId: lifecycle.project_id, runId: stage.entity_id },
    }));
    return;
  }
  if (stage.key === "approval") {
    window.dispatchEvent(new CustomEvent("merchpilot:focus-approval", {
      detail: { kind: "planning", taskId: stage.entity_id },
    }));
    return;
  }
  if (stage.key === "selection" || stage.key === "validation") {
    window.dispatchEvent(new CustomEvent("merchpilot:focus-selected-products", {
      detail: { productId: stage.entity_id },
    }));
    return;
  }
  if (stage.key === "launch_review") {
    window.dispatchEvent(new CustomEvent("merchpilot:focus-approval", {
      detail: { kind: "launch-review", reviewId: stage.entity_id },
    }));
    return;
  }
  window.dispatchEvent(new CustomEvent("merchpilot:focus-initiative", {
    detail: { initiativeId: stage.entity_id },
  }));
}

/** 渲染全局当前项目选择与连续业务入口。 */
export function ProjectContextBar() {
  const dispatch = useAppDispatch();
  const identity = useAppSelector((state) => state.identity.current);
  const projectContextState = useAppSelector((state) => state.projectContext);
  const current = projectContextState.current;
  const currentProjectId = current?.projectId;
  const canManage = hasAnyRole(identity, ["admin", "planner"]);
  const canApprove = hasAnyRole(identity, ["admin", "approver"]);
  const [options, setOptions] = useState<PlanningProject[]>([]);
  const [loading, setLoading] = useState(false);
  const [lifecycle, setLifecycle] = useState<ProjectLifecycle>();
  const [lifecycleLoading, setLifecycleLoading] = useState(false);
  const [lifecycleError, setLifecycleError] = useState<string>();
  const [contextNotice, setContextNotice] = useState<string>();
  const [linkCopied, setLinkCopied] = useState(false);
  const searchTimerRef = useRef<number | undefined>(undefined);
  const requestRef = useRef(0);
  const lifecycleRequestRef = useRef(0);
  const validatedProjectRef = useRef<string | undefined>(undefined);
  const copiedTimerRef = useRef<number | undefined>(undefined);

  const loadOptions = useCallback(async (keyword = "") => {
    const requestId = ++requestRef.current;
    setLoading(true);
    try {
      const result = await listPlanningProjectsPage({
        keyword,
        page: 1,
        pageSize: projectContextOptionLimit,
      });
      if (requestId !== requestRef.current) return;
      setOptions(result.items);
    } catch {
      if (requestId === requestRef.current) setOptions([]);
    } finally {
      if (requestId === requestRef.current) setLoading(false);
    }
  }, []);

  const loadLifecycle = useCallback(async () => {
    const requestId = ++lifecycleRequestRef.current;
    if (!currentProjectId) {
      setLifecycle(undefined);
      setLifecycleError(undefined);
      setLifecycleLoading(false);
      return;
    }
    setLifecycleLoading(true);
    setLifecycle((value) => value?.project_id === currentProjectId ? value : undefined);
    setLifecycleError(undefined);
    try {
      const result = await listProjectLifecyclesPage(
        1,
        1,
        undefined,
        "priority",
        "all",
        currentProjectId,
      );
      if (requestId !== lifecycleRequestRef.current) return;
      const nextLifecycle = result.items[0];
      setLifecycle(nextLifecycle);
      if (!nextLifecycle) {
        setContextNotice("当前项目已归档或不可用，已恢复为全局视角");
        dispatch(clearProjectContext());
      }
      setLifecycleError(nextLifecycle ? undefined : "当前项目暂时没有可展示的闭环信息");
    } catch {
      if (requestId === lifecycleRequestRef.current) {
        setLifecycleError("项目进度暂时无法同步，模块操作仍可继续使用");
      }
    } finally {
      if (requestId === lifecycleRequestRef.current) setLifecycleLoading(false);
    }
  }, [currentProjectId, dispatch]);

  useEffect(() => {
    if (!identity || projectContextState.hydrated) return;
    dispatch(hydrateProjectContext(readInitialProjectContext(identity.tenant_id)));
  }, [dispatch, identity, projectContextState.hydrated]);

  useEffect(() => {
    if (!projectContextState.hydrated || typeof window === "undefined") return;
    if (!current) {
      window.localStorage.removeItem(PROJECT_CONTEXT_STORAGE_KEY);
      syncProjectIdToUrl();
      return;
    }
    window.localStorage.setItem(PROJECT_CONTEXT_STORAGE_KEY, JSON.stringify(current));
    syncProjectIdToUrl(current.projectId);
  }, [current, projectContextState.hydrated]);

  useEffect(() => {
    const restoreProjectFromUrl = () => {
      const projectId = readProjectIdFromUrl();
      if (!projectId) {
        if (currentProjectId) dispatch(clearProjectContext());
        return;
      }
      if (projectId === currentProjectId) return;
      validatedProjectRef.current = undefined;
      setContextNotice(undefined);
      dispatch(
        setProjectContext({
          projectId,
          tenantId: identity?.tenant_id,
          source: "url",
        }),
      );
    };
    window.addEventListener("popstate", restoreProjectFromUrl);
    return () => window.removeEventListener("popstate", restoreProjectFromUrl);
  }, [currentProjectId, dispatch, identity?.tenant_id]);

  useEffect(() => {
    const initialLoadTimer = window.setTimeout(() => void loadOptions(), 0);
    return () => {
      requestRef.current += 1;
      if (searchTimerRef.current !== undefined) window.clearTimeout(searchTimerRef.current);
      if (copiedTimerRef.current !== undefined) window.clearTimeout(copiedTimerRef.current);
      window.clearTimeout(initialLoadTimer);
    };
  }, [loadOptions]);

  useEffect(() => {
    const initialLoadTimer = window.setTimeout(() => void loadLifecycle(), 0);
    const refreshTimer = window.setInterval(() => void loadLifecycle(), 10_000);
    const handleBusinessDataChanged = () => void loadLifecycle();
    window.addEventListener(BUSINESS_DATA_CHANGED_EVENT, handleBusinessDataChanged);
    return () => {
      lifecycleRequestRef.current += 1;
      window.clearTimeout(initialLoadTimer);
      window.clearInterval(refreshTimer);
      window.removeEventListener(BUSINESS_DATA_CHANGED_EVENT, handleBusinessDataChanged);
    };
  }, [loadLifecycle]);

  useEffect(() => {
    if (!current?.projectId) return;
    const restoredContext = current.source === "url" || current.source === "restored";
    const hasCompleteDetails = Boolean(
      current.projectName && current.category && current.targetMarket,
    );
    if (hasCompleteDetails && (!restoredContext || validatedProjectRef.current === current.projectId)) {
      return;
    }
    let active = true;
    void getPlanningProject(current.projectId)
      .then((project) => {
        if (!active) return;
        if (project.archived_at) {
          setContextNotice("链接或历史项目已归档，已恢复为全局视角");
          dispatch(clearProjectContext());
          return;
        }
        validatedProjectRef.current = project.id;
        setContextNotice(undefined);
        setOptions((items) => items.some((item) => item.id === project.id) ? items : [project, ...items]);
        dispatch(
          setProjectContext({
            ...projectContextFromProject(project, identity?.tenant_id),
            source: current.source,
          }),
        );
      })
      .catch(() => {
        if (!active) return;
        validatedProjectRef.current = undefined;
        if (restoredContext) {
          setContextNotice("链接或历史项目不可用，已恢复为全局视角");
          dispatch(clearProjectContext());
        } else {
          setContextNotice("项目详情暂时无法同步，请稍后重试");
        }
      });
    return () => {
      active = false;
    };
  }, [
    current?.category,
    current?.projectId,
    current?.projectName,
    current?.source,
    current?.targetMarket,
    dispatch,
    identity?.tenant_id,
  ]);

  const selectOptions = useMemo(() => {
    const merged = [...options];
    if (current?.projectId && !merged.some((item) => item.id === current.projectId)) {
      merged.unshift({
        id: current.projectId,
        tenant_id: current.tenantId ?? identity?.tenant_id ?? "",
        name: current.projectName ?? current.projectId,
        category: current.category ?? "待加载",
        target_market: current.targetMarket ?? "待加载",
        status: "",
        constraints: {},
        created_at: "",
        updated_at: "",
      });
    }
    return merged.map((project) => ({
      value: project.id,
      label: `${project.name} · ${project.category} · ${project.target_market}`,
    }));
  }, [current, identity?.tenant_id, options]);

  /** 复制同时包含项目与当前模块位置的分享链接，并提供短暂成功反馈。 */
  const copyCurrentProjectLink = async () => {
    if (!currentProjectId) return;
    try {
      await navigator.clipboard.writeText(currentProjectLink(currentProjectId));
      setLinkCopied(true);
      if (copiedTimerRef.current !== undefined) window.clearTimeout(copiedTimerRef.current);
      copiedTimerRef.current = window.setTimeout(() => setLinkCopied(false), 2_000);
    } catch {
      setContextNotice("浏览器未允许自动复制，请从地址栏复制当前链接");
    }
  };

  return (
    <section className="project-context-bar" aria-label="当前项目连续操作">
      <div className="project-context-heading">
        <span className="project-context-icon"><DeploymentUnitOutlined /></span>
        <div>
          <span>跨模块当前项目</span>
          <strong>{current?.projectName ?? (current ? "正在加载项目..." : "尚未选择项目")}</strong>
          <small>
            {current
              ? [current.category, current.targetMarket].filter(Boolean).join(" · ") || current.projectId
              : contextNotice ?? "选择一次后，规划、审批、选品和立项会自动保持同一项目视角"}
          </small>
        </div>
      </div>

      <div className="project-context-selector">
        <Select
          showSearch
          allowClear
          filterOption={false}
          value={current?.projectId}
          loading={loading}
          placeholder="选择要连续推进的项目"
          options={selectOptions}
          onSearch={(value) => {
            if (searchTimerRef.current !== undefined) window.clearTimeout(searchTimerRef.current);
            searchTimerRef.current = window.setTimeout(() => void loadOptions(value.trim()), 280);
          }}
          onClear={() => {
            setContextNotice(undefined);
            syncProjectIdToUrl(undefined, "push");
            dispatch(clearProjectContext());
          }}
          onChange={(projectId) => {
            if (!projectId) return;
            validatedProjectRef.current = undefined;
            setContextNotice(undefined);
            syncProjectIdToUrl(projectId, "push");
            const project = options.find((item) => item.id === projectId);
            if (project) {
              dispatch(setProjectContext(projectContextFromProject(project, identity?.tenant_id)));
              return;
            }
            dispatch(
              setProjectContext({
                projectId,
                tenantId: identity?.tenant_id,
                source: "context-bar",
              }),
            );
          }}
          onOpenChange={(open) => {
            if (open && options.length === 0) void loadOptions();
          }}
        />
        {current ? (
          <Button
            aria-label="清除当前项目"
            type="text"
            icon={<CloseOutlined />}
            onClick={() => {
              setContextNotice(undefined);
              syncProjectIdToUrl(undefined, "push");
              dispatch(clearProjectContext());
            }}
          />
        ) : null}
      </div>

      <div className="project-context-actions">
        <Tag color={current ? "processing" : "default"}>{current ? "项目视角已锁定" : "全局视角"}</Tag>
        <Button
          icon={<ProjectOutlined />}
          disabled={!current}
          onClick={() => current && openProjectContextModule("planning", current.projectId)}
        >
          规划
        </Button>
        <Button
          icon={<SafetyCertificateOutlined />}
          disabled={!current}
          onClick={() => current && openProjectContextModule("approval", current.projectId)}
        >
          审批
        </Button>
        <Button
          icon={<ProductOutlined />}
          disabled={!current}
          onClick={() => current && openProjectContextModule("selection", current.projectId)}
        >
          选品
        </Button>
        <Button
          icon={<RocketOutlined />}
          disabled={!current}
          onClick={() => current && openProjectContextModule("initiative", current.projectId)}
        >
          立项
        </Button>
        <Button
          icon={<LinkOutlined />}
          disabled={!current}
          onClick={() => void copyCurrentProjectLink()}
        >
          {linkCopied ? "已复制" : "复制项目链接"}
        </Button>
      </div>

      {current ? (
        <div className="project-context-lifecycle" aria-live="polite">
          <div className="project-context-lifecycle-header">
            <div>
              <span>当前项目闭环</span>
              <strong>
                {lifecycleLoading && !lifecycle
                  ? "正在同步项目进度..."
                  : lifecycle?.stage_label ?? "等待进度数据"}
              </strong>
            </div>
            {lifecycle ? (
              <Tag color={lifecycleHealthPresentation[lifecycle.health].color}>
                {lifecycleHealthPresentation[lifecycle.health].label} · {lifecycle.progress_percent}%
              </Tag>
            ) : null}
          </div>

          {lifecycle ? (
            <>
              <Progress
                percent={lifecycle.progress_percent}
                showInfo={false}
                strokeColor={lifecycleHealthPresentation[lifecycle.health].strokeColor}
              />
              <div className="project-context-stages" aria-label="当前项目八阶段进度">
                {lifecycle.stages.map((stage, index) => (
                  <button
                    key={stage.key}
                    type="button"
                    className={`project-context-stage is-${stage.status}`}
                    disabled={!stage.entity_id}
                    title={stage.detail}
                    onClick={() => openLifecycleStage(lifecycle, stage)}
                  >
                    <span>{index + 1}</span>
                    <small>{stage.label}</small>
                  </button>
                ))}
              </div>
              <div className="project-context-next-action">
                <div>
                  <span>{lifecycle.blockers[0] ? "当前阻断" : "建议下一步"}</span>
                  <strong>{lifecycle.blockers[0] ?? lifecycle.next_action_label}</strong>
                </div>
                <Button
                  type="primary"
                  icon={<ArrowRightOutlined />}
                  onClick={() => openLifecycleNextAction(lifecycle, canManage)}
                >
                  {lifecycleActionLabel(lifecycle, canManage, canApprove)}
                </Button>
              </div>
            </>
          ) : (
            <div className="project-context-lifecycle-empty">
              {lifecycleError ?? "正在准备当前项目的完整业务进度"}
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}
