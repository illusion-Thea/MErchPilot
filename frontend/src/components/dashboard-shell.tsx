/**
 * 文件职责：管理身份状态、模块导航、页面级模块切换和跨模块精准定位。
 */

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRightOutlined,
  BellOutlined,
  ApiOutlined,
  CheckCircleOutlined,
  CompassOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  DownOutlined,
  FileSearchOutlined,
  ProductOutlined,
  ReloadOutlined,
  RocketOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  SwapOutlined,
  UpOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Alert, Button, Modal, Select, Space, Spin, Tag } from "antd";

import { ApprovalPanel } from "@/components/approval-panel";
import { AuditActivityFeed } from "@/components/audit-activity-feed";
import { BusinessOverview } from "@/components/business-overview";
import { DataImportPanel } from "@/components/data-import-panel";
import { DemoWorkspacePanel } from "@/components/demo-workspace-panel";
import { OpportunityChart } from "@/components/opportunity-chart";
import { NotificationCenter } from "@/components/notification-center";
import { McpIntegrationPanel } from "@/components/mcp-integration-panel";
import { PlanningWorkspace } from "@/components/planning-workspace";
import { ProductInitiativePanel } from "@/components/product-initiative-panel";
import { ProjectContextBar } from "@/components/project-context-bar";
import { RetrievalPlayground } from "@/components/retrieval-playground";
import { SelectedProductPanel } from "@/components/selected-product-panel";
import { SystemStatusPanel } from "@/components/system-status-panel";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { hasAnyRole, loadCurrentIdentity } from "@/store/identity-slice";
import { isLocalProfileAccessToken, setAccessToken } from "@/lib/http/identity";

/** 定义`roleLabels`展示映射，集中维护状态文案、颜色或选项。 */
const roleLabels: Record<string, string> = {
  admin: "管理员",
  planner: "规划人员",
  approver: "审批人员",
  viewer: "只读用户",
};

/** 定义`WorkbenchModule`允许的状态或联合类型，避免跨模块使用任意字符串。 */
type WorkbenchModule =
  | "overview"
  | "data"
  | "planning"
  | "approval"
  | "selection"
  | "initiative"
  | "integration"
  | "operations";

/** 定义`WorkbenchModuleDefinition`数据契约，约束组件属性或接口响应字段。 */
interface WorkbenchModuleDefinition {
  key: WorkbenchModule;
  label: string;
  description: string;
  workflow: string;
  roles?: readonly string[];
}

/** 定义当前身份在本地工作台中的主角色及其推荐业务路径。 */
interface RoleWorkflowGuide {
  role: string;
  label: string;
  title: string;
  description: string;
  journey: WorkbenchModule[];
  primaryModules: WorkbenchModule[];
}

/** 定义`workbenchModules`模块常量或配置，供当前文件中的多个流程复用。 */
const workbenchModules: WorkbenchModuleDefinition[] = [
  {
    key: "overview",
    label: "业务驾驶舱",
    description: "查看业务全局进度、待办和机会评分",
    workflow: "全局视角",
  },
  {
    key: "data",
    label: "数据治理",
    description: "导入数据、治理质量并验证检索证据",
    workflow: "数据准备",
  },
  {
    key: "planning",
    label: "规划执行",
    description: "配置项目、运行 Multi-Agent 并查看规划结果",
    workflow: "智能分析",
  },
  {
    key: "approval",
    label: "线上审批",
    description: "处理规划方案和上市准备评审",
    workflow: "人工决策",
  },
  {
    key: "selection",
    label: "正式选品",
    description: "维护选品台账、验证清单和推进状态",
    workflow: "商品决策",
  },
  {
    key: "initiative",
    label: "商品立项",
    description: "推进样品、成本、试销和确认上市",
    workflow: "落地执行",
  },
  {
    key: "integration",
    label: "Agent 集成",
    description: "查看 FastMCP 服务、验证当前身份并复制企业 Agent 连接配置",
    workflow: "能力开放",
  },
  {
    key: "operations",
    label: "运维审计",
    description: "查看服务健康、操作记录和审计台账",
    workflow: "企业保障",
    roles: ["admin"],
  },
];

/** 定义角色工作指引的本地记忆键，用户收起后刷新页面仍保持原选择。 */
const WORKFLOW_GUIDE_STORAGE_KEY = "merchpilot_workflow_guide_collapsed";

/** 定义四类本地身份的职责说明和推荐使用顺序。 */
const roleWorkflowGuides: Record<string, RoleWorkflowGuide> = {
  admin: {
    role: "admin",
    label: "管理员",
    title: "全链路管理与异常治理",
    description: "查看经营全局、处理关键业务、验证 Agent 集成，并在运维审计中定位服务或操作异常。",
    journey: ["overview", "data", "planning", "approval", "selection", "initiative", "integration", "operations"],
    primaryModules: ["overview", "approval", "operations"],
  },
  planner: {
    role: "planner",
    label: "规划人员",
    title: "从业务数据推进到商品上市",
    description: "准备可信数据、运行商品规划 Agent、维护正式选品验证，并持续推进商品立项。",
    journey: ["overview", "data", "planning", "selection", "initiative", "integration"],
    primaryModules: ["data", "planning", "selection", "initiative"],
  },
  approver: {
    role: "approver",
    label: "审批人员",
    title: "集中处理人工决策与风险门禁",
    description: "先从驾驶舱确认待办，再处理规划审批和上市评审，并查看决策后的选品与立项进展。",
    journey: ["overview", "approval", "selection", "initiative", "integration"],
    primaryModules: ["approval"],
  },
  viewer: {
    role: "viewer",
    label: "只读用户",
    title: "查看完整业务进度与决策依据",
    description: "以只读方式浏览经营全局、数据证据、Agent 结果、审批记录和上市落地状态。",
    journey: ["overview", "data", "planning", "approval", "selection", "initiative", "integration"],
    primaryModules: ["overview"],
  },
};

/** 定义身份切换后的推荐落点，避免新角色停留在不属于其主要职责的旧模块。 */
const roleLandingModules: Record<string, WorkbenchModule> = {
  admin: "overview",
  planner: "planning",
  approver: "approval",
  viewer: "overview",
};

/** 按权限优先级选取一个主角色，用于展示清晰且唯一的工作指引。 */
function primaryRoleForIdentity(roles: string[] | undefined): string {
  return ["admin", "planner", "approver", "viewer"].find((role) => roles?.includes(role)) ?? "viewer";
}

/** 返回模块对当前角色的职责标签，帮助用户区分主责操作、协同查看和只读入口。 */
function moduleResponsibilityLabel(
  moduleKey: WorkbenchModule,
  guide: RoleWorkflowGuide,
): string {
  if (guide.role === "viewer") return "只读查看";
  if (guide.primaryModules.includes(moduleKey)) return "主责处理";
  if (guide.role === "admin") return "全局管理";
  return "协同查看";
}

/** 判断`isWorkbenchModule`条件是否成立，供页面状态和操作权限复用。 */
function isWorkbenchModule(value: string | null): value is WorkbenchModule {
  return Boolean(value && workbenchModules.some((module) => module.key === value));
}

/** 实现`readModuleFromUrl`辅助逻辑，集中处理页面展示或状态转换规则。 */
function readModuleFromUrl(): WorkbenchModule | undefined {
  if (typeof window === "undefined") return undefined;
  const hashParams = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const moduleFromHash = hashParams.get("module");
  return isWorkbenchModule(moduleFromHash) ? moduleFromHash : undefined;
}

/** 定义`focusEventModules`模块常量或配置，供当前文件中的多个流程复用。 */
const focusEventModules: Record<string, WorkbenchModule> = {
  "merchpilot:focus-import": "data",
  "merchpilot:focus-planning-project": "planning",
  "merchpilot:focus-approval": "approval",
  "merchpilot:focus-selected-products": "selection",
  "merchpilot:focus-initiative-create": "initiative",
  "merchpilot:focus-initiative": "initiative",
};

/** 定义跨模块事件对应的目标面板，保证切页后仍能定位到具体业务区域。 */
const focusEventTargets: Record<string, string> = {
  "merchpilot:focus-import": "data-import-panel",
  "merchpilot:focus-planning-project": "planning-workspace",
  "merchpilot:focus-approval": "approval-panel",
  "merchpilot:focus-selected-products": "selected-product-panel",
  "merchpilot:focus-initiative-create": "product-initiative-panel",
  "merchpilot:focus-initiative": "product-initiative-panel",
};

/** 实现`moduleIcon`辅助逻辑，集中处理页面展示或状态转换规则。 */
function moduleIcon(moduleKey: WorkbenchModule) {
  if (moduleKey === "overview") return <DashboardOutlined />;
  if (moduleKey === "data") return <DatabaseOutlined />;
  if (moduleKey === "planning") return <ProductOutlined />;
  if (moduleKey === "approval") return <SafetyCertificateOutlined />;
  if (moduleKey === "selection") return <CheckCircleOutlined />;
  if (moduleKey === "initiative") return <RocketOutlined />;
  if (moduleKey === "integration") return <ApiOutlined />;
  return <SettingOutlined />;
}

/** 管理身份加载、模块导航、URL状态和跨模块精准定位。 */
export function DashboardShell() {
  const dispatch = useAppDispatch();
  const connection = useAppSelector((state) => state.run.connectionStatus);
  const identityState = useAppSelector((state) => state.identity);
  const identity = identityState.current;
  const canAudit = hasAnyRole(identity, ["admin"]);
  const roleText = identity?.roles.map((role) => roleLabels[role] ?? role).join(" / ");
  const [identityModalOpen, setIdentityModalOpen] = useState(false);
  const localProfiles = identity?.local_profiles ?? [];
  const [selectedLocalProfile, setSelectedLocalProfile] = useState("admin");
  const [activeModule, setActiveModule] = useState<WorkbenchModule>("overview");
  const [workflowGuideExpanded, setWorkflowGuideExpanded] = useState(true);
  const [pendingFocus, setPendingFocus] = useState<{
    eventName: string;
    detail: unknown;
    targetId: string;
  }>();
  const canResetLocalIdentity = isLocalProfileAccessToken();
  const isLocalAuth = identity?.auth_mode === "local";
  const moduleHydratedRef = useRef(false);
  const activeModuleRef = useRef<WorkbenchModule>(activeModule);
  const availableModules = useMemo(
    () =>
      workbenchModules.filter(
        (module) => !module.roles || module.roles.some((role) => identity?.roles.includes(role)),
      ),
    [identity?.roles],
  );
  const primaryRole = primaryRoleForIdentity(identity?.roles);
  const workflowGuide = roleWorkflowGuides[primaryRole];
  const selectedRoleGuide = roleWorkflowGuides[selectedLocalProfile] ?? roleWorkflowGuides.viewer;

  const activeModuleDefinition =
    availableModules.find((item) => item.key === activeModule) ?? availableModules[0];
  const renderedModule = activeModuleDefinition?.key ?? "overview";
  const activeModuleIndex = Math.max(
    0,
    availableModules.findIndex((module) => module.key === renderedModule),
  );
  const previousModule = availableModules[activeModuleIndex - 1];
  const nextModule = availableModules[activeModuleIndex + 1];
  const journeyModules = workflowGuide.journey
    .map((moduleKey) => availableModules.find((module) => module.key === moduleKey))
    .filter((module): module is WorkbenchModuleDefinition => Boolean(module));
  const currentJourneyIndex = journeyModules.findIndex((module) => module.key === renderedModule);
  const nextJourneyModule = currentJourneyIndex >= 0
    ? journeyModules[currentJourneyIndex + 1] ?? journeyModules[0]
    : journeyModules[0];

  const activateModule = useCallback(
    (moduleKey: WorkbenchModule, historyMode: "push" | "replace" = "push") => {
      if (!availableModules.some((module) => module.key === moduleKey)) return;
      if (historyMode === "push" && moduleKey === renderedModule) return;
      activeModuleRef.current = moduleKey;
      setActiveModule(moduleKey);
      if (typeof window !== "undefined") {
        const nextUrl = `${window.location.pathname}${window.location.search}#module=${moduleKey}`;
        if (historyMode === "push") {
          window.history.pushState(null, "", nextUrl);
        } else {
          window.history.replaceState(null, "", nextUrl);
        }
      }
    },
    [availableModules, renderedModule],
  );

  const navigateToModule = useCallback(
    (moduleKey: WorkbenchModule) => {
      setPendingFocus(undefined);
      activateModule(moduleKey);
      window.requestAnimationFrame(() => {
        window.scrollTo({ top: 0, behavior: "smooth" });
      });
    },
    [activateModule],
  );

  useEffect(() => {
    const preferenceTimer = window.setTimeout(() => {
      const guideCollapsed = window.localStorage.getItem(WORKFLOW_GUIDE_STORAGE_KEY) === "true";
      setWorkflowGuideExpanded(!guideCollapsed);
    }, 0);
    return () => window.clearTimeout(preferenceTimer);
  }, []);

  useEffect(() => {
    const hydrationTimer = window.setTimeout(() => {
      const savedModule = readModuleFromUrl() ?? window.localStorage.getItem("merchpilot_active_module");
      moduleHydratedRef.current = true;
      if (savedModule && availableModules.some((module) => module.key === savedModule)) {
        activateModule(savedModule as WorkbenchModule, "replace");
      }
    }, 0);
    return () => window.clearTimeout(hydrationTimer);
  }, [activateModule, availableModules]);

  useEffect(() => {
    activeModuleRef.current = renderedModule;
    if (moduleHydratedRef.current && typeof window !== "undefined") {
      window.localStorage.setItem("merchpilot_active_module", renderedModule);
      const moduleFromUrl = readModuleFromUrl();
      if (moduleFromUrl !== renderedModule) {
        window.history.replaceState(
          null,
          "",
          `${window.location.pathname}${window.location.search}#module=${renderedModule}`,
        );
      }
    }
  }, [availableModules, renderedModule]);

  useEffect(() => {
    const restoreModuleFromUrl = () => {
      const moduleFromUrl = readModuleFromUrl();
      if (moduleFromUrl && availableModules.some((module) => module.key === moduleFromUrl)) {
        activateModule(moduleFromUrl, "replace");
      }
    };
    window.addEventListener("popstate", restoreModuleFromUrl);
    window.addEventListener("hashchange", restoreModuleFromUrl);
    return () => {
      window.removeEventListener("popstate", restoreModuleFromUrl);
      window.removeEventListener("hashchange", restoreModuleFromUrl);
    };
  }, [activateModule, availableModules]);

  useEffect(() => {
    const handleFocusEvent = (event: Event) => {
      const targetModule = focusEventModules[event.type];
      if (!targetModule) return;
      if (targetModule === activeModuleRef.current) return;
      activateModule(targetModule);
      setPendingFocus({
        eventName: event.type,
        detail: (event as CustomEvent<unknown>).detail,
        targetId: focusEventTargets[event.type],
      });
    };
    Object.keys(focusEventModules).forEach((eventName) => {
      window.addEventListener(eventName, handleFocusEvent);
    });
    return () => {
      Object.keys(focusEventModules).forEach((eventName) => {
        window.removeEventListener(eventName, handleFocusEvent);
      });
    };
  }, [activateModule]);

  useEffect(() => {
    if (!pendingFocus) return;
    // 短暂延迟用于等待 React 完成目标模块挂载，再补发事件并定位到具体业务面板。
    const timer = window.setTimeout(() => {
      window.dispatchEvent(
        new CustomEvent(pendingFocus.eventName, { detail: pendingFocus.detail }),
      );
      window.requestAnimationFrame(() => {
        document
          .getElementById(pendingFocus.targetId)
          ?.scrollIntoView({ behavior: "smooth", block: "start" });
        setPendingFocus(undefined);
      });
    }, 180);
    return () => window.clearTimeout(timer);
  }, [pendingFocus]);

  useEffect(() => {
    if (identityState.status === "idle") {
      void dispatch(loadCurrentIdentity());
      return;
    }

    if (identityState.status !== "error") return;

    const retryTimer = window.setTimeout(() => {
      void dispatch(loadCurrentIdentity());
    }, 5_000);

    return () => window.clearTimeout(retryTimer);
  }, [dispatch, identityState.status]);

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <div className="brand-mark">M</div>
          <div>
            <div className="brand-title">品策智选 MerchPilot</div>
            <div className="brand-subtitle">企业级商品规划与智能选品平台</div>
          </div>
        </div>
        <div className="topbar-actions">
          <div className="topbar-identity">
            <Tag
              icon={<UserOutlined />}
              color={identityState.status === "error" ? "error" : "blue"}
              title={identityState.error}
              style={{ marginInlineEnd: 0 }}
            >
              {identity
                ? `${identity.user_id} · ${roleText || "已认证"} · ${identity.tenant_id}`
                : identityState.status === "error"
                  ? "身份连接失败"
                  : "身份加载中"}
            </Tag>
            {identityState.status === "error" ? (
              <>
                <Button
                  aria-label="重新加载身份"
                  size="small"
                  type="text"
                  icon={<ReloadOutlined />}
                  onClick={() => void dispatch(loadCurrentIdentity())}
                />
                {canResetLocalIdentity ? (
                  <Button
                    size="small"
                    type="text"
                    onClick={() => {
                      setAccessToken("");
                      window.location.reload();
                    }}
                  >
                    恢复默认身份
                  </Button>
                ) : null}
              </>
            ) : null}
            {isLocalAuth && localProfiles.length > 0 ? (
              <Button
                size="small"
                type="text"
                icon={<SwapOutlined />}
                onClick={() => {
                  setSelectedLocalProfile(
                    identity?.roles.find((role) => localProfiles.includes(role)) ?? localProfiles[0] ?? "admin",
                  );
                  setIdentityModalOpen(true);
                }}
              >
                切换本地身份
              </Button>
            ) : null}
          </div>
          <Tag
            color={connection === "connected" ? "success" : connection === "error" ? "error" : "default"}
          >
            实时连接 {connection === "idle" ? "待机" : connection}
          </Tag>
          {identityState.status === "ready" ? (
            <NotificationCenter connectionStatus={connection} />
          ) : (
            <Button
              shape="circle"
              disabled
              aria-label="身份确认后显示待办与提醒"
              icon={<BellOutlined />}
            />
          )}
        </div>
      </header>

      <Modal
        title="切换本地开发身份"
        open={identityModalOpen}
        okText="应用并刷新"
        cancelText="取消"
        onCancel={() => setIdentityModalOpen(false)}
        onOk={() => {
          const landingModule = roleLandingModules[selectedLocalProfile] ?? "overview";
          setAccessToken(`local-profile:${selectedLocalProfile}`);
          window.localStorage.setItem("merchpilot_active_module", landingModule);
          setIdentityModalOpen(false);
          window.history.replaceState(
            null,
            "",
            `${window.location.pathname}${window.location.search}#module=${landingModule}`,
          );
          window.location.reload();
        }}
      >
        <Space orientation="vertical" size={12} style={{ width: "100%" }}>
          <div className="muted-text">
            仅用于本地开发和 Docker 验收，不会替代企业 SSO。切换后页面会重新加载并按角色显示操作权限。
          </div>
          <Select
            value={selectedLocalProfile}
            onChange={setSelectedLocalProfile}
            style={{ width: "100%" }}
            options={localProfiles.map((profile) => ({
              value: profile,
              label: `${roleLabels[profile] ?? profile}（${profile}）`,
            }))}
          />
          <div className="identity-role-preview">
            <span>{selectedRoleGuide.label}进入后</span>
            <strong>{selectedRoleGuide.title}</strong>
            <p>{selectedRoleGuide.description}</p>
            <small>
              默认进入：{workbenchModules.find(
                (module) => module.key === (roleLandingModules[selectedLocalProfile] ?? "overview"),
              )?.label ?? "业务驾驶舱"}
            </small>
          </div>
        </Space>
      </Modal>

      {identityState.status === "ready" ? (
        <div className="page-content">
          <nav className="module-nav" aria-label="业务工作台模块">
            <div className="module-nav-heading">
              <div>
                <span>业务工作台</span>
                <strong>按模块处理完整商品规划链路</strong>
              </div>
              <div className="module-nav-heading-actions">
                <Tag color="blue">当前：{activeModuleDefinition.label}</Tag>
                <Button
                  size="small"
                  type="text"
                  icon={workflowGuideExpanded ? <UpOutlined /> : <DownOutlined />}
                  onClick={() => {
                    const nextExpanded = !workflowGuideExpanded;
                    setWorkflowGuideExpanded(nextExpanded);
                    window.localStorage.setItem(
                      WORKFLOW_GUIDE_STORAGE_KEY,
                      String(!nextExpanded),
                    );
                  }}
                >
                  {workflowGuideExpanded ? "收起工作指引" : "展开工作指引"}
                </Button>
              </div>
            </div>
            <div className="module-nav-list">
              {availableModules.map((module) => (
                <button
                  type="button"
                  key={module.key}
                  className={`module-nav-item ${renderedModule === module.key ? "module-nav-item-active" : ""}`}
                  aria-current={renderedModule === module.key ? "page" : undefined}
                  onClick={() => {
                    navigateToModule(module.key);
                  }}
                >
                  <span className="module-nav-icon">{moduleIcon(module.key)}</span>
                  <span className="module-nav-copy">
                    <strong>{module.label}</strong>
                    <small>
                      {module.workflow} · {moduleResponsibilityLabel(module.key, workflowGuide)}
                    </small>
                  </span>
                </button>
              ))}
            </div>
            {workflowGuideExpanded ? (
              <section className="role-workflow-guide" aria-label={`${workflowGuide.label}工作指引`}>
                <div className="role-workflow-summary">
                  <span className="role-workflow-icon"><CompassOutlined /></span>
                  <div>
                    <span>{workflowGuide.label}工作指引</span>
                    <strong>{workflowGuide.title}</strong>
                    <p>{workflowGuide.description}</p>
                  </div>
                </div>
                <div className="role-workflow-journey" aria-label="推荐业务路径">
                  {journeyModules.map((module, index) => (
                    <button
                      type="button"
                      key={module.key}
                      className={`role-workflow-step ${module.key === renderedModule ? "is-current" : ""}`}
                      aria-current={module.key === renderedModule ? "step" : undefined}
                      onClick={() => {
                        navigateToModule(module.key);
                      }}
                    >
                      <span>{index + 1}</span>
                      <strong>{module.label}</strong>
                    </button>
                  ))}
                </div>
                <div className="role-workflow-next">
                  <span>
                    {currentJourneyIndex >= 0
                      ? `当前位于推荐路径第 ${currentJourneyIndex + 1} / ${journeyModules.length} 步`
                      : "当前模块不在该角色主路径中，可返回推荐流程继续"}
                  </span>
                  {nextJourneyModule ? (
                    <Button
                      type="primary"
                      icon={<ArrowRightOutlined />}
                      onClick={() => {
                        navigateToModule(nextJourneyModule.key);
                      }}
                    >
                      {currentJourneyIndex === journeyModules.length - 1
                        ? `回到${nextJourneyModule.label}`
                        : `继续：${nextJourneyModule.label}`}
                    </Button>
                  ) : null}
                </div>
              </section>
            ) : null}
          </nav>

          <ProjectContextBar />

          <section className="module-context" aria-live="polite">
            <div className="module-context-copy">
              <span>当前业务模块</span>
              <h1>{activeModuleDefinition.label}</h1>
              <p>{activeModuleDefinition.description}</p>
            </div>
            <div className="module-context-actions">
              <span className="module-context-progress">
                模块 {activeModuleIndex + 1} / {availableModules.length}
              </span>
              <Space size={8}>
                <Button
                  size="small"
                  disabled={!previousModule}
                  onClick={() => {
                    if (!previousModule) return;
                    navigateToModule(previousModule.key);
                  }}
                >
                  上一个模块
                </Button>
                <Button
                  size="small"
                  type="primary"
                  disabled={!nextModule}
                  onClick={() => {
                    if (!nextModule) return;
                    navigateToModule(nextModule.key);
                  }}
                >
                  下一个模块
                  <ArrowRightOutlined />
                </Button>
              </Space>
              <FileSearchOutlined className="module-context-mark" />
            </div>
          </section>

          {renderedModule === "overview" ? (
            <>
              <DemoWorkspacePanel />
              <BusinessOverview />
              <section className="panel" id="opportunity-chart" style={{ marginTop: 20 }}>
                <div className="panel-header">
                  <div>
                    <h2 className="panel-title">机会评分概览</h2>
                    <p className="panel-description">AntV 展示各项目最新运行的真实机会分，结果来自证据、财务和供应规则</p>
                  </div>
                  <Tag color="success">真实运行数据</Tag>
                </div>
                <OpportunityChart />
              </section>
            </>
          ) : null}

          {renderedModule === "data" ? (
            <>
              <DataImportPanel />
              <RetrievalPlayground />
            </>
          ) : null}

          {renderedModule === "planning" ? (
            <PlanningWorkspace />
          ) : null}

          {renderedModule === "approval" ? (
            <ApprovalPanel />
          ) : null}

          {renderedModule === "selection" ? (
            <SelectedProductPanel />
          ) : null}

          {renderedModule === "initiative" ? (
            <ProductInitiativePanel />
          ) : null}

          {renderedModule === "integration" ? (
            <McpIntegrationPanel />
          ) : null}

          {renderedModule === "operations" ? (
            <section className="workspace-grid">
              <SystemStatusPanel />
              <article className="panel">
                <div className="panel-header">
                  <div>
                    <h2 className="panel-title">最近活动</h2>
                    <p className="panel-description">来自 PostgreSQL 的项目、运行、审批和导入审计记录</p>
                  </div>
                </div>
                {canAudit ? (
                  <AuditActivityFeed />
                ) : (
                  <div className="muted-text">审计台账仅对管理员开放。</div>
                )}
              </article>
            </section>
          ) : null}
        </div>
      ) : (
        <section className="identity-gate" aria-live="polite">
          {identityState.status === "error" ? (
            <Alert
              type="error"
              showIcon
              title="身份认证不可用"
              description={identityState.error ?? "暂时无法确认当前用户，请检查认证服务或本地开发凭证。"}
              action={
                <Space>
                  <Button size="small" onClick={() => void dispatch(loadCurrentIdentity())}>
                    重新连接
                  </Button>
                  {canResetLocalIdentity ? (
                    <Button
                      size="small"
                      onClick={() => {
                        setAccessToken("");
                        window.location.reload();
                      }}
                    >
                      恢复默认身份
                    </Button>
                  ) : null}
                </Space>
              }
            />
          ) : (
            <div className="identity-gate-loading">
              <Spin size="large" />
              <span>正在确认当前身份，业务数据将在认证完成后加载</span>
            </div>
          )}
        </section>
      )}
    </main>
  );
}
