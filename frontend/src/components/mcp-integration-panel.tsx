/**
 * 文件职责：展示 FastMCP 服务状态、工具目录、活动和客户端接入说明。
 */

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiOutlined,
  CheckCircleOutlined,
  CopyOutlined,
  ProductOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
} from "@ant-design/icons";
import { Alert, Button, Empty, Pagination, Spin, Tag, message } from "antd";

import {
  getMcpActivities,
  getMcpIntegration,
  McpActivityPage,
  McpIntegration,
  McpVerification,
  verifyMcpIntegration,
} from "@/lib/http/mcp-integration";

/** 定义`PAGE_SIZE`模块常量或配置，供当前文件中的多个流程复用。 */
const PAGE_SIZE = 6;
/** 定义`ACTIVITY_PAGE_SIZE`模块常量或配置，供当前文件中的多个流程复用。 */
const ACTIVITY_PAGE_SIZE = 5;

/** 定义`tagLabels`展示映射，集中维护状态文案、颜色或选项。 */
const tagLabels: Record<string, string> = {
  planning: "规划",
  evidence: "证据",
  retrieval: "检索",
  approval: "审批",
  products: "商品",
  analytics: "经营分析",
  readonly: "只读",
  "controlled-write": "受控写入",
  idempotent: "幂等",
  "confirmation-required": "明确确认",
  "launch-review": "上市评审",
  "human-approval-required": "人工审批",
};

/** 定义`projectStatusPresentation`展示映射，集中维护状态文案、颜色或选项。 */
const projectStatusPresentation: Record<string, { label: string; color: string; action: string }> = {
  draft: { label: "待人工复核", color: "gold", action: "复核并启动" },
  running: { label: "Agent 分析中", color: "processing", action: "查看执行进度" },
  approval_required: { label: "待线上审批", color: "warning", action: "查看审批结果" },
  completed: { label: "规划已完成", color: "success", action: "查看规划结果" },
  failed: { label: "执行失败", color: "error", action: "查看失败原因" },
  cancelled: { label: "已取消", color: "default", action: "查看项目" },
};

/** 定义`runStatusPresentation`展示映射，集中维护状态文案、颜色或选项。 */
const runStatusPresentation: Record<string, { label: string; color: string }> = {
  queued: { label: "已排队", color: "default" },
  running: { label: "执行中", color: "processing" },
  approval_required: { label: "待审批", color: "warning" },
  completed: { label: "已完成", color: "success" },
  failed: { label: "失败", color: "error" },
  cancelled: { label: "已取消", color: "default" },
  superseded: { label: "已被修订替代", color: "default" },
};

/** 定义`approvalEventPresentation`展示映射，集中维护状态文案、颜色或选项。 */
const approvalEventPresentation: Record<string, { label: string; color: string }> = {
  claimed: { label: "已领取", color: "blue" },
  approved: { label: "已通过", color: "success" },
  rejected: { label: "已驳回", color: "error" },
  revision_required: { label: "要求修订", color: "warning" },
};

/** 定义`validationStatusPresentation`展示映射，集中维护状态文案、颜色或选项。 */
const validationStatusPresentation: Record<string, { label: string; color: string }> = {
  ready: { label: "验证通过", color: "success" },
  partial: { label: "部分完成", color: "warning" },
  blocked: { label: "存在阻塞", color: "error" },
};

/** 定义`launchReviewStatusPresentation`展示映射，集中维护状态文案、颜色或选项。 */
const launchReviewStatusPresentation: Record<string, { label: string; color: string }> = {
  pending: { label: "等待人工审批", color: "warning" },
  approved: { label: "人工审批通过", color: "success" },
  rejected: { label: "人工审批驳回", color: "error" },
  revision_required: { label: "需要补充修订", color: "warning" },
};

/** 定义`activitySourcePresentation`展示映射，集中维护状态文案、颜色或选项。 */
const activitySourcePresentation: Record<McpActivityPage["items"][number]["activity_type"], { label: string; color: string }> = {
  mcp_created: { label: "MCP 创建", color: "purple" },
  mcp_started: { label: "MCP 启动", color: "cyan" },
  mcp_approval_claimed: { label: "MCP 审批", color: "geekblue" },
  mcp_approval_decided: { label: "MCP 审批", color: "geekblue" },
  mcp_validation_updated: { label: "MCP 验证", color: "green" },
  mcp_launch_review_submitted: { label: "MCP 上市评审", color: "volcano" },
};

/** 把formatDateTime相关原始值格式化为页面可读文本。 */
function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

/** 实现`statusLabel`辅助逻辑，集中处理页面展示或状态转换规则。 */
function statusLabel(value: McpIntegration["status"]): string {
  if (value === "ready") return "可用";
  if (value === "degraded") return "身份未验证";
  return "服务不可用";
}

/** 展示FastMCP服务状态、工具权限、活动记录和客户端接入信息。 */
export function McpIntegrationPanel() {
  const [messageApi, contextHolder] = message.useMessage();
  const [integration, setIntegration] = useState<McpIntegration>();
  const [verification, setVerification] = useState<McpVerification>();
  const [page, setPage] = useState(1);
  const [activityPage, setActivityPage] = useState(1);
  const [activities, setActivities] = useState<McpActivityPage>();
  const [loading, setLoading] = useState(true);
  const [activityLoading, setActivityLoading] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState<string>();
  const [activityError, setActivityError] = useState<string>();

  const loadIntegration = useCallback(async (targetPage: number) => {
    setLoading(true);
    try {
      const value = await getMcpIntegration(targetPage, PAGE_SIZE);
      setIntegration(value);
      setError(undefined);
    } catch (loadError) {
      setIntegration(undefined);
      setError(loadError instanceof Error ? loadError.message : "无法读取 MCP 集成状态");
    } finally {
      setLoading(false);
    }
  }, []);

  const canViewActivities = Boolean(
    integration?.roles.some((role) => role === "admin" || role === "planner" || role === "approver"),
  );

  const loadActivities = useCallback(async (targetPage: number) => {
    setActivityLoading(true);
    try {
      const value = await getMcpActivities(targetPage, ACTIVITY_PAGE_SIZE);
      setActivities(value);
      setActivityError(undefined);
    } catch (loadError) {
      setActivities(undefined);
      setActivityError(loadError instanceof Error ? loadError.message : "无法读取 Agent 全链路活动");
    } finally {
      setActivityLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    void getMcpIntegration(page, PAGE_SIZE)
      .then((value) => {
        if (!active) return;
        setIntegration(value);
        setError(undefined);
      })
      .catch((loadError) => {
        if (!active) return;
        setIntegration(undefined);
        setError(loadError instanceof Error ? loadError.message : "无法读取 MCP 集成状态");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [page]);

  useEffect(() => {
    if (!canViewActivities) return;
    const timer = window.setTimeout(() => void loadActivities(activityPage), 0);
    return () => window.clearTimeout(timer);
  }, [activityPage, canViewActivities, loadActivities]);

  const configurationText = useMemo(
    () => JSON.stringify(integration?.client_configuration ?? {}, null, 2),
    [integration?.client_configuration],
  );

  const copyConfiguration = async () => {
    try {
      await navigator.clipboard.writeText(configurationText);
      messageApi.success("MCP 客户端配置已复制");
    } catch {
      messageApi.error("浏览器未允许复制，请手动选择配置内容");
    }
  };

  const verifyCurrentIdentity = async () => {
    setVerifying(true);
    try {
      const value = await verifyMcpIntegration();
      setVerification(value);
      messageApi.success("当前身份已通过 MCP 业务工具验证");
    } catch (verifyError) {
      setVerification(undefined);
      messageApi.error(verifyError instanceof Error ? verifyError.message : "MCP 验证失败");
    } finally {
      setVerifying(false);
    }
  };

  const focusPlanningProject = (projectId: string) => {
    window.dispatchEvent(
      new CustomEvent("merchpilot:focus-planning-project", {
        detail: { projectId },
      }),
    );
  };

  const focusProductInitiative = (initiativeId: string) => {
    window.dispatchEvent(
      new CustomEvent("merchpilot:focus-initiative", {
        detail: { initiativeId },
      }),
    );
  };

  return (
    <section className="mcp-integration-layout" id="mcp-integration-panel">
      {contextHolder}
      <article className="panel mcp-integration-hero">
        <div className="panel-header">
          <div>
            <h2 className="panel-title">企业 Agent 集成</h2>
            <p className="panel-description">
              使用 FastMCP 将商品规划、证据、审批和商品推进数据安全开放给 IDE 助手与企业 Agent
            </p>
          </div>
          <div className="mcp-header-actions">
            {integration ? (
              <Tag color={integration.status === "ready" ? "success" : integration.status === "degraded" ? "warning" : "error"}>
                {statusLabel(integration.status)}
              </Tag>
            ) : null}
            <Button
              icon={<ReloadOutlined />}
              loading={loading || activityLoading}
              onClick={() => {
                void loadIntegration(page);
                if (canViewActivities) void loadActivities(activityPage);
              }}
            >
              刷新状态
            </Button>
          </div>
        </div>

        {error ? <Alert type="error" showIcon message="无法读取 Agent 集成状态" description={error} /> : null}
        {integration?.error ? (
          <Alert
            type={integration.health_ready ? "warning" : "error"}
            showIcon
            message={integration.health_ready ? "MCP 服务已启动，但当前身份尚未通过验证" : "FastMCP 服务当前不可用"}
            description={integration.error}
          />
        ) : null}

        <Spin spinning={loading && !integration}>
          {integration ? (
            <div className="mcp-overview-grid">
              <div className="mcp-overview-card">
                <span>服务状态</span>
                <strong>{integration.health_ready ? "运行正常" : "未连接"}</strong>
                <small>{integration.service_name} · v{integration.service_version}</small>
              </div>
              <div className="mcp-overview-card">
                <span>当前身份</span>
                <strong>{integration.authenticated ? "协议已验证" : "等待验证"}</strong>
                <small>{integration.user_id} · {integration.roles.join(" / ")}</small>
              </div>
              <div className="mcp-overview-card">
                <span>租户边界</span>
                <strong>{integration.tenant_id}</strong>
                <small>所有工具继续执行 FastAPI 多租户隔离</small>
              </div>
              <div className="mcp-overview-card">
                <span>工具能力</span>
                <strong>{integration.total} 个可用工具</strong>
                <small>{integration.read_only_total} 个只读 · {integration.controlled_write_total} 个受控写入</small>
              </div>
            </div>
          ) : null}
        </Spin>
      </article>

      {integration ? (
        <div className="mcp-content-grid">
          <article className="panel mcp-configuration-panel">
            <div className="panel-header">
              <div>
                <h3 className="panel-title">客户端连接配置</h3>
                <p className="panel-description">复制到支持 Streamable HTTP 的 MCP 客户端，本地身份会与当前页面角色保持一致</p>
              </div>
              <Button icon={<CopyOutlined />} onClick={() => void copyConfiguration()}>
                复制配置
              </Button>
            </div>
            <div className="mcp-endpoint-row">
              <span>服务地址</span>
              <code>{integration.endpoint}</code>
              <Tag color="blue">{integration.auth_mode}</Tag>
            </div>
            <pre className="mcp-config-code" tabIndex={0}>{configurationText}</pre>
            <Alert
              type="info"
              showIcon
              message="凭证只用于当前身份"
              description="生产环境接入企业 SSO 后应使用短期访问令牌或网关托管凭证，不应把个人长期 Token 固化在配置文件中。"
            />
          </article>

          <article className="panel mcp-verification-panel">
            <div className="panel-header">
              <div>
                <h3 className="panel-title">当前身份业务验证</h3>
                <p className="panel-description">调用经营驾驶舱工具，确认协议鉴权、租户隔离和真实业务 API 同时可用</p>
              </div>
              <Button
                type="primary"
                icon={<CheckCircleOutlined />}
                loading={verifying}
                disabled={!integration.authenticated}
                onClick={() => void verifyCurrentIdentity()}
              >
                立即验证
              </Button>
            </div>
            {verification ? (
              <>
                <div className="mcp-verification-status">
                  <SafetyCertificateOutlined />
                  <div>
                    <strong>验证通过</strong>
                    <span>{formatDateTime(verification.verified_at)} · {verification.tenant_id}</span>
                  </div>
                </div>
                <div className="mcp-verification-metrics">
                  <div><span>项目总数</span><strong>{verification.project_total}</strong></div>
                  <div><span>活跃项目</span><strong>{verification.active_project_total}</strong></div>
                  <div><span>待审批</span><strong>{verification.pending_approval_total}</strong></div>
                  <div><span>正式选品</span><strong>{verification.selected_product_total}</strong></div>
                  <div><span>进行中立项</span><strong>{verification.active_initiative_total}</strong></div>
                </div>
              </>
            ) : (
              <div className="mcp-verification-empty">
                <ApiOutlined />
                <strong>尚未执行当前身份验证</strong>
                <span>验证只读取汇总数据，不会创建项目、审批或修改商品状态。</span>
              </div>
            )}
          </article>
        </div>
      ) : null}

      {integration?.controlled_write_total ? (
        <Alert
          type="warning"
          showIcon
          message="受控写入已启用人工复核、明确确认与幂等门禁"
          description="规划写入分为创建草稿和明确启动；审批写入必须先领取任务后复核提交；验证门禁每次只能更新一项，标记通过前必须已有人工上传材料；上市评审只能创建待审单，最终决定仍由人员在线处理。业务状态或材料变化后旧令牌立即失效，任何 Agent 都不能绕过租户、角色或线上审批边界。"
        />
      ) : null}

      {canViewActivities ? (
        <article className="panel mcp-activity-panel">
          <div className="panel-header">
            <div>
              <h3 className="panel-title">Agent 全链路活动</h3>
              <p className="panel-description">按项目追踪 MCP 创建、启动、审批、验证门禁和上市评审，并转到业务模块继续处理</p>
            </div>
            <div className="mcp-header-actions">
              {activities ? <Tag color="blue">共 {activities.total} 个项目</Tag> : null}
              <Button
                size="small"
                icon={<ReloadOutlined />}
                loading={activityLoading}
                onClick={() => void loadActivities(activityPage)}
              >
                刷新记录
              </Button>
            </div>
          </div>
          {activityError ? <Alert type="error" showIcon message="无法读取 Agent 全链路活动" description={activityError} /> : null}
          <Spin spinning={activityLoading && !activities}>
            {activities?.items.length ? (
              <div className="mcp-activity-list">
                {activities.items.map((activity) => {
                  const presentation = projectStatusPresentation[activity.project_status] ?? {
                    label: activity.project_status,
                    color: "blue",
                    action: "查看项目",
                  };
                  const sourcePresentation = activitySourcePresentation[activity.activity_type];
                  return (
                    <div className="mcp-activity-card" key={activity.id}>
                      <div className="mcp-activity-main">
                        <div className="mcp-activity-title-row">
                          <strong>{activity.project_name}</strong>
                          <Tag color={presentation.color}>{presentation.label}</Tag>
                          <Tag color={sourcePresentation.color}>
                            {sourcePresentation.label}
                          </Tag>
                        </div>
                        <div className="mcp-activity-meta">
                          <span>{activity.category} · {activity.target_market}</span>
                          <span>
                            项目创建：{activity.project_created_by} · {formatDateTime(activity.project_created_at)}
                          </span>
                        </div>
                        {activity.mcp_creation_request_id ? (
                          <div className="mcp-activity-request">
                            <span>
                              MCP 创建：{activity.mcp_creation_actor_id} · {activity.mcp_created_at ? formatDateTime(activity.mcp_created_at) : "--"}
                            </span>
                            <code>{activity.mcp_creation_request_id}</code>
                          </div>
                        ) : (
                          <div className="mcp-activity-start mcp-activity-start-empty">
                            该项目由 Web 创建，之后由 MCP 复核并接管 Agent 启动。
                          </div>
                        )}
                        {activity.latest_start_request_id ? (
                          <div className="mcp-activity-start">
                            <div className="mcp-activity-start-title">
                              <strong>最近一次 MCP 启动</strong>
                              {activity.latest_run_status ? (
                                <Tag color={(runStatusPresentation[activity.latest_run_status] ?? { color: "blue" }).color}>
                                  {(runStatusPresentation[activity.latest_run_status] ?? { label: activity.latest_run_status }).label}
                                </Tag>
                              ) : null}
                            </div>
                            <div className="mcp-activity-meta">
                              <span>
                                启动：{activity.latest_start_actor_id} · {activity.latest_start_at ? formatDateTime(activity.latest_start_at) : "--"}
                              </span>
                              {activity.latest_run_id ? <span>运行：<code>{activity.latest_run_id}</code></span> : null}
                            </div>
                            <div className="mcp-activity-request">
                              <span>启动请求</span>
                              <code>{activity.latest_start_request_id}</code>
                            </div>
                          </div>
                        ) : (
                          <div className="mcp-activity-start mcp-activity-start-empty">
                            尚未通过 MCP 启动，复核项目参数后可明确确认进入 Agent 分析。
                          </div>
                        )}
                        {activity.latest_approval_request_id ? (
                          <div className="mcp-activity-start mcp-activity-approval">
                            <div className="mcp-activity-start-title">
                              <strong>最近一次 MCP 审批操作</strong>
                              <Tag color={(approvalEventPresentation[activity.latest_approval_event ?? ""] ?? { color: "blue" }).color}>
                                {(approvalEventPresentation[activity.latest_approval_event ?? ""] ?? { label: activity.latest_approval_status ?? "审批处理中" }).label}
                              </Tag>
                            </div>
                            <div className="mcp-activity-meta">
                              <span>
                                处理人：{activity.latest_approval_actor_id} · {activity.latest_approval_at ? formatDateTime(activity.latest_approval_at) : "--"}
                              </span>
                              {activity.latest_approval_task_id ? <span>任务：<code>{activity.latest_approval_task_id}</code></span> : null}
                            </div>
                            <div className="mcp-activity-request">
                              <span>审批请求</span>
                              <code>{activity.latest_approval_request_id}</code>
                            </div>
                          </div>
                        ) : null}
                        {activity.latest_validation_request_id ? (
                          <div className="mcp-activity-start mcp-activity-validation">
                            <div className="mcp-activity-start-title">
                              <strong>最近一次 MCP 验证更新</strong>
                              <Tag color={(validationStatusPresentation[activity.latest_validation_status ?? ""] ?? { color: "blue" }).color}>
                                {(validationStatusPresentation[activity.latest_validation_status ?? ""] ?? { label: activity.latest_validation_status ?? "已更新" }).label}
                              </Tag>
                              {activity.latest_validation_completion_rate !== null ? (
                                <Tag>{activity.latest_validation_completion_rate}%</Tag>
                              ) : null}
                            </div>
                            <div className="mcp-activity-meta">
                              <span>
                                更新人：{activity.latest_validation_actor_id} · {activity.latest_validation_at ? formatDateTime(activity.latest_validation_at) : "--"}
                              </span>
                              {activity.latest_validation_run_id ? <span>运行：<code>{activity.latest_validation_run_id}</code></span> : null}
                              {activity.latest_validation_candidate_id ? <span>方案：<code>{activity.latest_validation_candidate_id}</code></span> : null}
                            </div>
                            <div className="mcp-activity-request">
                              <span>
                                门禁：{activity.latest_validation_gate_ids.length ? activity.latest_validation_gate_ids.join("、") : "--"}
                              </span>
                              <code>{activity.latest_validation_request_id}</code>
                            </div>
                          </div>
                        ) : null}
                        {activity.latest_launch_review_request_id ? (
                          <div className="mcp-activity-start mcp-activity-launch-review">
                            <div className="mcp-activity-start-title">
                              <strong>最近一次 MCP 上市评审提交</strong>
                              <Tag color={(launchReviewStatusPresentation[activity.latest_launch_review_status ?? ""] ?? { color: "blue" }).color}>
                                {(launchReviewStatusPresentation[activity.latest_launch_review_status ?? ""] ?? { label: activity.latest_launch_review_status ?? "评审处理中" }).label}
                              </Tag>
                              {activity.latest_launch_review_readiness_status ? (
                                <Tag color={activity.latest_launch_review_readiness_status === "ready" ? "success" : "warning"}>
                                  {activity.latest_launch_review_readiness_status === "ready" ? "预检通过" : "带风险复核"}
                                </Tag>
                              ) : null}
                            </div>
                            <div className="mcp-activity-meta">
                              <span>
                                提交人：{activity.latest_launch_review_actor_id} · {activity.latest_launch_review_at ? formatDateTime(activity.latest_launch_review_at) : "--"}
                              </span>
                              {activity.latest_launch_review_initiative_name ? <span>立项：{activity.latest_launch_review_initiative_name}</span> : null}
                              {activity.latest_launch_review_id ? <span>评审：<code>{activity.latest_launch_review_id}</code></span> : null}
                            </div>
                            <div className="mcp-activity-request">
                              <span>MCP 只创建待审单，不会自动批准或确认上市</span>
                              <code>{activity.latest_launch_review_request_id}</code>
                            </div>
                          </div>
                        ) : null}
                      </div>
                      <Button
                        type="primary"
                        ghost
                        icon={<ProductOutlined />}
                        onClick={() => activity.activity_type === "mcp_launch_review_submitted" && activity.latest_launch_review_initiative_id
                          ? focusProductInitiative(activity.latest_launch_review_initiative_id)
                          : focusPlanningProject(activity.project_id)}
                      >
                        {activity.activity_type === "mcp_launch_review_submitted" && activity.latest_launch_review_initiative_id
                          ? "查看商品立项"
                          : presentation.action}
                      </Button>
                    </div>
                  );
                })}
              </div>
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={activityLoading ? "正在读取 Agent 全链路活动" : "当前租户还没有 MCP 创建、启动、审批、验证或上市评审活动"}
              />
            )}
          </Spin>
          {activities && activities.total > ACTIVITY_PAGE_SIZE ? (
            <div className="mcp-pagination">
              <Pagination
                current={activityPage}
                pageSize={ACTIVITY_PAGE_SIZE}
                total={activities.total}
                showSizeChanger={false}
                onChange={setActivityPage}
                showTotal={(total) => `共 ${total} 个 Agent 协同项目`}
              />
            </div>
          ) : null}
        </article>
      ) : null}

      <article className="panel">
        <div className="panel-header">
          <div>
            <h3 className="panel-title">可用工具目录</h3>
            <p className="panel-description">工具按页加载，参数容量受限，防止一次把全部企业数据写入模型上下文</p>
          </div>
          {integration ? <Tag>{integration.total} 个工具</Tag> : null}
        </div>
        <Spin spinning={loading}>
          {integration?.tools.length ? (
            <div className="mcp-tool-grid">
              {integration.tools.map((tool) => (
                <div className="mcp-tool-card" key={tool.name}>
                  <div className="mcp-tool-card-header">
                    <code>{tool.name}</code>
                    <Tag color={tool.read_only ? "success" : "warning"}>{tool.read_only ? "只读" : "受控写入"}</Tag>
                  </div>
                  <strong>{tool.title}</strong>
                  <p>{tool.description}</p>
                  <div className="mcp-tool-tags">
                    {tool.tags.filter((tag) => tag !== "readonly").map((tag) => (
                      <Tag key={tag}>{tagLabels[tag] ?? tag}</Tag>
                    ))}
                  </div>
                  <div className="mcp-tool-contract">
                    <span>必填参数：{tool.required_fields.length ? tool.required_fields.join("、") : "无"}</span>
                    <span>{tool.max_page_size ? `最大分页：${tool.max_page_size} 条` : "单次汇总结果"}</span>
                    {!tool.read_only ? <span>{tool.idempotent ? "支持幂等安全重试" : "调用前需人工确认"}</span> : null}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={integration?.health_ready ? "当前身份未获取到工具" : "MCP 服务恢复后显示工具目录"} />
          )}
        </Spin>
        {integration && integration.total > PAGE_SIZE ? (
          <div className="mcp-pagination">
            <Pagination
              current={page}
              pageSize={PAGE_SIZE}
              total={integration.total}
              showSizeChanger={false}
              onChange={(nextPage) => {
                setLoading(true);
                setPage(nextPage);
              }}
              showTotal={(total) => `共 ${total} 个工具`}
            />
          </div>
        ) : null}
      </article>
    </section>
  );
}
