/**
 * 文件职责：为首次使用者提供一键演示初始化和四条可直接打开的业务场景。
 */

"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ArrowRightOutlined,
  CheckCircleOutlined,
  ExperimentOutlined,
  LoadingOutlined,
  PlayCircleOutlined,
  RocketOutlined,
  SafetyCertificateOutlined,
} from "@ant-design/icons";
import { Alert, Button, Tag } from "antd";

import { notifyBusinessDataChanged } from "@/lib/business-events";
import {
  createLocalDemoWorkspace,
  getLocalDemoWorkspace,
} from "@/lib/http/demo-workspace";
import type { LocalDemoProject, LocalDemoWorkspace } from "@/lib/http/demo-workspace";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { hasAnyRole } from "@/store/identity-slice";
import { setProjectContext } from "@/store/project-context-slice";

/** 定义四个演示场景的用户说明和图标。 */
const scenarioPresentation = {
  planning_approval: {
    icon: <SafetyCertificateOutlined />,
    title: "处理规划审批",
    description: "查看研究规划、候选方案、证据、财务和供应风险。",
    button: "打开待审批方案",
  },
  validation: {
    icon: <ExperimentOutlined />,
    title: "推进选品验证",
    description: "查看正式选品、四道验证门、材料记录和下一步要求。",
    button: "打开验证中选品",
  },
  launch_review: {
    icon: <RocketOutlined />,
    title: "复核上市准备",
    description: "查看商品立项、试销经营、五阶段里程碑和待审单。",
    button: "打开待上市评审",
  },
  launched: {
    icon: <CheckCircleOutlined />,
    title: "查看上市复盘",
    description: "查看已上市项目、试销表现、审批结论和完整时间线。",
    button: "打开上市结果",
  },
} as const;

/** 根据场景发送现有模块已经支持的精确定位事件。 */
function openDemoScenario(project: LocalDemoProject) {
  window.setTimeout(() => {
    if (project.scenario === "planning_approval") {
      window.dispatchEvent(
        new CustomEvent("merchpilot:focus-approval", {
          detail: { kind: "planning", taskId: project.approval_task_id },
        }),
      );
      return;
    }
    if (project.scenario === "validation") {
      window.dispatchEvent(
        new CustomEvent("merchpilot:focus-selected-products", {
          detail: { validation: "pending", productId: project.selected_product_id },
        }),
      );
      return;
    }
    if (project.scenario === "launch_review") {
      window.dispatchEvent(
        new CustomEvent("merchpilot:focus-approval", {
          detail: { kind: "launch-review", reviewId: project.launch_review_id },
        }),
      );
      return;
    }
    window.dispatchEvent(
      new CustomEvent("merchpilot:focus-initiative", {
        detail: { initiativeId: project.initiative_id },
      }),
    );
  }, 80);
}

/** 展示本地演示工作区状态，并把初始化与导航操作保持在一个清晰入口中。 */
export function DemoWorkspacePanel() {
  const dispatch = useAppDispatch();
  const identity = useAppSelector((state) => state.identity.current);
  const canInitialize = hasAnyRole(identity, ["admin"]);
  const isLocalAuth = identity?.auth_mode === "local";
  const [workspace, setWorkspace] = useState<LocalDemoWorkspace | null>();
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<string>();

  const loadWorkspace = useCallback(async () => {
    if (!isLocalAuth) {
      setLoading(false);
      return;
    }
    try {
      setWorkspace(await getLocalDemoWorkspace());
      setError(undefined);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "无法读取演示工作区状态");
    } finally {
      setLoading(false);
    }
  }, [isLocalAuth]);

  useEffect(() => {
    // 将首次读取放到浏览器任务队列，避免 effect 执行期间同步触发级联渲染。
    const timer = window.setTimeout(() => void loadWorkspace(), 0);
    return () => window.clearTimeout(timer);
  }, [loadWorkspace]);

  useEffect(() => {
    if (!workspace || !["pending", "indexing"].includes(workspace.index_status)) return;
    // 证据索引由 Celery 异步完成，短轮询仅在未完成期间运行并在完成后自动停止。
    const timer = window.setInterval(() => void loadWorkspace(), 2500);
    return () => window.clearInterval(timer);
  }, [loadWorkspace, workspace]);

  if (!isLocalAuth) return null;

  const initialize = async () => {
    setCreating(true);
    setError(undefined);
    setNotice(undefined);
    try {
      const result = await createLocalDemoWorkspace();
      setWorkspace(result);
      setNotice(result.message);
      notifyBusinessDataChanged();
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : "演示工作区初始化失败");
    } finally {
      setCreating(false);
    }
  };

  const enterScenario = (project: LocalDemoProject) => {
    dispatch(
      setProjectContext({
        projectId: project.project_id,
        projectName: project.project_name,
        category: project.category,
        targetMarket: project.target_market,
        tenantId: workspace?.tenant_id ?? identity?.tenant_id,
        source: "demo",
      }),
    );
    openDemoScenario(project);
  };

  return (
    <section className="demo-workspace-panel" aria-live="polite">
      <div className="demo-workspace-header">
        <div>
          <span className="demo-workspace-kicker">
            <PlayCircleOutlined /> 本地完整演示
          </span>
          <h2>第一次打开？一键准备可操作的业务闭环</h2>
          <p>
            系统会在当前租户中生成真实 PostgreSQL 业务记录和 Milvus 证据索引，不覆盖你已经导入的数据。
          </p>
        </div>
        {workspace?.index_status === "indexed" ? (
          <Tag color="success" icon={<CheckCircleOutlined />}>业务数据与检索已就绪</Tag>
        ) : workspace ? (
          <Tag
            color={workspace.index_status === "failed" ? "error" : "processing"}
            icon={workspace.index_status === "failed" ? <SafetyCertificateOutlined /> : <LoadingOutlined />}
          >
            {workspace.index_status === "failed" ? "业务数据已就绪 · 索引需重试" : "业务数据已就绪 · 证据索引中"}
          </Tag>
        ) : (
          <Tag color="processing" icon={loading ? <LoadingOutlined /> : <PlayCircleOutlined />}>
            {loading ? "正在检查" : "尚未初始化"}
          </Tag>
        )}
      </div>

      {error ? <Alert type="warning" showIcon title={error} closable /> : null}
      {notice ? <Alert type="success" showIcon title={notice} closable /> : null}

      {!workspace ? (
        <div className="demo-workspace-empty">
          <div>
            <strong>自动准备 15 条可信证据和 4 条不同阶段项目</strong>
            <span>覆盖待规划审批、选品验证中、待上市评审和已上市复盘。</span>
          </div>
          {canInitialize ? (
            <Button
              type="primary"
              size="large"
              icon={<PlayCircleOutlined />}
              loading={creating || loading}
              onClick={() => void initialize()}
            >
              生成本地演示工作区
            </Button>
          ) : (
            <span className="demo-workspace-permission">请切换到管理员身份完成首次初始化。</span>
          )}
        </div>
      ) : (
        <>
          <div className="demo-workspace-summary">
            <span>可信证据 <strong>{workspace.evidence_count}</strong> 条</span>
            <span>
              Milvus 已索引 <strong>{workspace.indexed_evidence_count}</strong> / {workspace.evidence_count}
            </span>
            <span>业务场景 <strong>{workspace.projects.length}</strong> 条</span>
            <span>当前租户 <strong>{workspace.tenant_id}</strong></span>
          </div>
          {workspace.index_status === "failed" ? (
            <Alert
              type="warning"
              showIcon
              title={`有 ${workspace.failed_evidence_count} 条证据索引失败，业务场景仍可查看；管理员可点击下方按钮重试。`}
            />
          ) : null}
          <div className="demo-scenario-grid">
            {workspace.projects.map((project) => {
              const presentation = scenarioPresentation[project.scenario];
              return (
                <article className={`demo-scenario-card is-${project.scenario}`} key={project.project_id}>
                  <div className="demo-scenario-icon">{presentation.icon}</div>
                  <div className="demo-scenario-copy">
                    <Tag>{project.scenario_label}</Tag>
                    <strong>{presentation.title}</strong>
                    <p>{presentation.description}</p>
                    <small>{project.project_name}</small>
                  </div>
                  <Button onClick={() => enterScenario(project)}>
                    {presentation.button} <ArrowRightOutlined />
                  </Button>
                </article>
              );
            })}
          </div>
          {canInitialize ? (
            <div className="demo-workspace-footer">
              <span>重复执行只会补齐缺失数据，不会创建重复项目。</span>
              <Button loading={creating} onClick={() => void initialize()}>
                {workspace.index_status === "failed" ? "重试索引并修复数据" : "检查并修复演示数据"}
              </Button>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}
