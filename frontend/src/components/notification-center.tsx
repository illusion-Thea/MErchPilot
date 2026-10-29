/**
 * 文件职责：汇总审批、数据质量、选品和立项提醒并跳转到对应记录。
 */

"use client";

import { useEffect, useMemo, useState } from "react";
import {
  BellOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  ReloadOutlined,
  RightOutlined,
} from "@ant-design/icons";
import { Badge, Button, Drawer, Empty, List, Space, Spin, Tag } from "antd";

import { BUSINESS_DATA_CHANGED_EVENT } from "@/lib/business-events";
import {
  getNotificationSnapshot,
  NotificationEntityReference,
  NotificationSnapshot,
} from "@/lib/http/analytics";
import {
  DataImportQualitySummary,
  EvidenceIndexStatus,
  getDataImportQualitySummary,
} from "@/lib/http/data-imports";
import { getSystemReadiness, SystemReadiness } from "@/lib/http/system";
import { useAppSelector } from "@/store/hooks";
import { hasAnyRole } from "@/store/identity-slice";

/** 定义`ReminderLevel`允许的状态或联合类型，避免跨模块使用任意字符串。 */
type ReminderLevel = "error" | "warning" | "info" | "success";
/** 定义`ReminderTargetType`允许的状态或联合类型，避免跨模块使用任意字符串。 */
type ReminderTargetType =
  | "initiative"
  | "planning-approval"
  | "launch-review"
  | "selected-product"
  | "initiative-create"
  | "planning-project";

/** 定义`ImportFocus`数据契约，约束组件属性或接口响应字段。 */
interface ImportFocus {
  importId?: string;
  qualityStatus?: "warning" | "blocked";
  indexStatus?: EvidenceIndexStatus;
}

/** 定义`ReminderItem`数据契约，约束组件属性或接口响应字段。 */
interface ReminderItem {
  id: string;
  level: ReminderLevel;
  title: string;
  description: string;
  sectionId?: string;
  targetId?: string;
  targetType?: ReminderTargetType;
  actionLabel?: string;
  importFocus?: ImportFocus;
}

/** 定义`ReminderData`数据契约，约束组件属性或接口响应字段。 */
interface ReminderData {
  snapshot: NotificationSnapshot | null;
  readiness?: SystemReadiness;
  qualitySummary: DataImportQualitySummary | null;
}

/** 定义`NotificationCenterProps`数据契约，约束组件属性或接口响应字段。 */
interface NotificationCenterProps {
  connectionStatus: string;
}

/** 定义`ReminderResults`允许的状态或联合类型，避免跨模块使用任意字符串。 */
type ReminderResults = [
  PromiseSettledResult<NotificationSnapshot>,
  PromiseSettledResult<SystemReadiness>,
  PromiseSettledResult<DataImportQualitySummary>,
];

/** 定义`emptyData`初始状态，避免加载期间出现空值分支。 */
const emptyData: ReminderData = {
  snapshot: null,
  qualitySummary: null,
};

/** 定义`levelPresentation`展示映射，集中维护状态文案、颜色或选项。 */
const levelPresentation: Record<ReminderLevel, { color: string; label: string }> = {
  error: { color: "error", label: "需处理" },
  warning: { color: "warning", label: "待办" },
  info: { color: "processing", label: "进行中" },
  success: { color: "success", label: "正常" },
};

/** 定义`serviceLabels`展示映射，集中维护状态文案、颜色或选项。 */
const serviceLabels: Record<string, string> = {
  postgres: "PostgreSQL",
  redis: "Redis",
  worker: "Celery Worker",
  milvus: "Milvus",
  embedding: "Embedding",
  reranker: "Reranker",
};

/** 定义`coreServiceKeys`模块常量或配置，供当前文件中的多个流程复用。 */
const coreServiceKeys = new Set(["postgres", "redis", "worker", "milvus"]);

/** 从并行请求结果中提取成功值，失败时保留调用方提供的回退数据。 */
function settledValue<T>(result: PromiseSettledResult<T>, fallback: T): T {
  return result.status === "fulfilled" ? result.value : fallback;
}

/** 实现`referenceSummary`辅助逻辑，集中处理页面展示或状态转换规则。 */
function referenceSummary(
  reference: NotificationEntityReference | null | undefined,
  count: number,
  unit: string,
): string {
  if (!reference) return `共 ${count} ${unit}`;
  return count > 1 ? `${reference.label} 等 ${count} ${unit}` : reference.label;
}

/** 加载`fetchReminderSources`所需数据，并处理并发请求、回退值和页面状态同步。 */
async function fetchReminderSources(): Promise<ReminderResults> {
  return Promise.allSettled([
    getNotificationSnapshot(),
    getSystemReadiness(),
    getDataImportQualitySummary(),
  ]);
}

/** 实现`mergeReminderData`辅助逻辑，集中处理页面展示或状态转换规则。 */
function mergeReminderData(current: ReminderData, results: ReminderResults): ReminderData {
  return {
    snapshot: settledValue(results[0], current.snapshot),
    readiness: settledValue(results[1], current.readiness),
    qualitySummary: settledValue(results[2], current.qualitySummary),
  };
}

/** 聚合需要当前用户处理的业务提醒，并跳转到具体记录。 */
export function NotificationCenter({ connectionStatus }: NotificationCenterProps) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<ReminderData>(emptyData);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [partialError, setPartialError] = useState(false);
  const [refreshedAt, setRefreshedAt] = useState<Date>();
  const identityState = useAppSelector((state) => state.identity);
  const canApprove = hasAnyRole(identityState.current, ["admin", "approver"]);
  const canPlan = hasAnyRole(identityState.current, ["admin", "planner"]);

  const refresh = async () => {
    setRefreshing(true);
    const results = await fetchReminderSources();
    setData((current) => mergeReminderData(current, results));
    setPartialError(results.some((result) => result.status === "rejected"));
    setRefreshedAt(new Date());
    setLoading(false);
    setRefreshing(false);
  };

  useEffect(() => {
    let active = true;
    const load = () => {
      void fetchReminderSources().then((results) => {
        if (!active) return;
        setData((current) => mergeReminderData(current, results));
        setPartialError(results.some((result) => result.status === "rejected"));
        setRefreshedAt(new Date());
        setLoading(false);
      });
    };
    load();
    const timer = window.setInterval(load, 10_000);
    window.addEventListener(BUSINESS_DATA_CHANGED_EVENT, load);
    return () => {
      active = false;
      window.clearInterval(timer);
      window.removeEventListener(BUSINESS_DATA_CHANGED_EVENT, load);
    };
  }, []);

  const reminders = useMemo(() => {
    const items: ReminderItem[] = [];
    const snapshot = data.snapshot;
    const warningImport = data.qualitySummary?.problem_imports.find(
      (item) => item.warning_records > 0,
    );
    const blockedImport = data.qualitySummary?.problem_imports.find(
      (item) => item.blocked_records > 0,
    );
    const failedIndexImport = data.qualitySummary?.problem_imports.find(
      (item) => item.failed_index_records > 0,
    );
    const warningImportNames = data.qualitySummary?.problem_imports
      .filter((item) => item.warning_records > 0)
      .slice(0, 2)
      .map((item) => item.filename)
      .join("、");
    const blockedImportNames = data.qualitySummary?.problem_imports
      .filter((item) => item.blocked_records > 0)
      .slice(0, 2)
      .map((item) => item.filename)
      .join("、");
    const failedIndexImportNames = data.qualitySummary?.problem_imports
      .filter((item) => item.failed_index_records > 0)
      .slice(0, 2)
      .map((item) => item.filename)
      .join("、");
    const activeApprovalCount = Math.max(
      0,
      (snapshot?.actionable_approval_count ?? 0)
        - (snapshot?.overdue_actionable_approval_count ?? 0),
    );
    const unhealthyCoreServices = Object.entries(
      data.readiness?.core_components ?? data.readiness?.components ?? {},
    )
      .filter(([name, ready]) => coreServiceKeys.has(name) && ready === false)
      .map(([name]) => serviceLabels[name] ?? name);
    const unavailableOptionalServices = Object.entries(
      data.readiness?.optional_components ?? {},
    )
      .filter(([, ready]) => ready === false)
      .map(([name]) => serviceLabels[name] ?? name);
    if (unhealthyCoreServices.length > 0) {
      items.push({
        id: "services-unhealthy",
        level: "error",
        title: `${unhealthyCoreServices.length} 项核心服务异常`,
        description: `${unhealthyCoreServices.join("、")} 当前不可用，请先恢复服务再继续规划。`,
        sectionId: "system-status-panel",
        actionLabel: "查看服务",
      });
    }
    if (unavailableOptionalServices.length > 0) {
      items.push({
        id: "optional-models-unavailable",
        level: "warning",
        title: `${unavailableOptionalServices.length} 项可选模型未就绪`,
        description: `${unavailableOptionalServices.join("、")} 暂不可用，检索链路可能降级。`,
        sectionId: "system-status-panel",
        actionLabel: "查看服务",
      });
    }
    if (identityState.status === "error") {
      items.push({
        id: "identity-unavailable",
        level: "error",
        title: "当前身份不可用",
        description: identityState.error ?? "无法确认当前用户权限，写入和审批操作可能受限。",
      });
    }
    if (connectionStatus === "error") {
      items.push({
        id: "websocket-error",
        level: "warning",
        title: "实时进度连接异常",
        description: "页面仍可刷新查看结果，但 Agent 实时进度可能延迟。",
        sectionId: "planning-workspace",
        actionLabel: "查看运行",
      });
    }
    if (canApprove && (snapshot?.overdue_actionable_approval_count ?? 0) > 0) {
      const approval = snapshot?.latest_overdue_approval;
      items.push({
        id: "overdue-approvals",
        level: "error",
        title: `${snapshot?.overdue_actionable_approval_count ?? 0} 项商品方案审批已超时`,
        description: approval
          ? String(approval.summary.project_name ?? approval.project_id)
          : "请进入审批中心处理超时任务。",
        sectionId: "approval-panel",
        targetId: approval?.id,
        targetType: "planning-approval",
        actionLabel: "立即处理",
      });
    }
    if (canApprove && activeApprovalCount > 0) {
      const approval = snapshot?.latest_actionable_approval;
      items.push({
        id: "pending-approvals",
        level: "warning",
        title: `${activeApprovalCount} 项商品方案可处理`,
        description: approval
          ? String(approval.summary.project_name ?? approval.project_id)
          : "请进入审批中心查看待处理方案。",
        sectionId: "approval-panel",
        targetId: approval?.id,
        targetType: "planning-approval",
        actionLabel: "去审批",
      });
    }
    if (canApprove && (snapshot?.pending_launch_review_count ?? 0) > 0) {
      const review = snapshot?.latest_launch_review;
      items.push({
        id: "pending-launch-reviews",
        level: "warning",
        title: `${snapshot?.pending_launch_review_count ?? 0} 项上市准备评审待处理`,
        description: review?.initiative_name || review?.initiative_id || "请进入审批中心处理上市评审。",
        sectionId: "approval-panel",
        targetId: review?.id,
        targetType: "launch-review",
        actionLabel: "去处理",
      });
    }
    if (canPlan && (snapshot?.new_selection_count ?? 0) > 0) {
      items.push({
        id: "selected-products-to-validate",
        level: "info",
        title: `${snapshot?.new_selection_count ?? 0} 个正式选品等待启动验证`,
        description: referenceSummary(
          snapshot?.latest_new_selection,
          snapshot?.new_selection_count ?? 0,
          "个选品",
        ),
        sectionId: "selected-product-panel",
        targetId: snapshot?.latest_new_selection?.id,
        targetType: "selected-product",
        actionLabel: "推进选品",
      });
    }
    if (canPlan && (snapshot?.ready_selection_count ?? 0) > 0) {
      items.push({
        id: "selected-products-ready-to-initiate",
        level: "info",
        title: `${snapshot?.ready_selection_count ?? 0} 个正式选品已具备立项条件`,
        description: referenceSummary(
          snapshot?.latest_ready_selection,
          snapshot?.ready_selection_count ?? 0,
          "个选品",
        ),
        sectionId: "product-initiative-panel",
        targetId: snapshot?.latest_ready_selection?.id,
        targetType: "initiative-create",
        actionLabel: "发起立项",
      });
    }
    if (canPlan && (snapshot?.failed_project_count ?? 0) > 0) {
      items.push({
        id: "failed-projects",
        level: "error",
        title: `${snapshot?.failed_project_count ?? 0} 个规划项目运行失败`,
        description: `${referenceSummary(snapshot?.latest_failed_project, snapshot?.failed_project_count ?? 0, "个项目")}，可进入规划工作台查看错误并恢复任务。`,
        sectionId: "planning-workspace",
        targetId: snapshot?.latest_failed_project?.id,
        targetType: "planning-project",
        actionLabel: "处理失败任务",
      });
    }
    if (canPlan && (snapshot?.cancelled_project_count ?? 0) > 0) {
      items.push({
        id: "cancelled-projects",
        level: "warning",
        title: `${snapshot?.cancelled_project_count ?? 0} 个项目审批未通过`,
        description: `${referenceSummary(snapshot?.latest_cancelled_project, snapshot?.cancelled_project_count ?? 0, "个项目")}，可调整项目参数后重新运行。`,
        sectionId: "planning-workspace",
        targetId: snapshot?.latest_cancelled_project?.id,
        targetType: "planning-project",
        actionLabel: "调整项目",
      });
    }
    if (!canApprove && (snapshot?.awaiting_approval_project_count ?? 0) > 0) {
      items.push({
        id: "projects-awaiting-approval",
        level: "info",
        title: `${snapshot?.awaiting_approval_project_count ?? 0} 个项目正在等待审批`,
        description: referenceSummary(
          snapshot?.latest_awaiting_approval_project,
          snapshot?.awaiting_approval_project_count ?? 0,
          "个项目",
        ),
        sectionId: "planning-workspace",
        targetId: snapshot?.latest_awaiting_approval_project?.id,
        targetType: "planning-project",
        actionLabel: "查看项目",
      });
    }
    if (canPlan && (snapshot?.failed_import_count ?? 0) > 0) {
      items.push({
        id: "failed-imports",
        level: "error",
        title: `${snapshot?.failed_import_count ?? 0} 个数据批次导入失败`,
        description: `${referenceSummary(snapshot?.latest_failed_import, snapshot?.failed_import_count ?? 0, "个批次")}，请检查失败原因后重新上传。`,
        sectionId: "data-import-panel",
        importFocus: { importId: snapshot?.latest_failed_import?.id },
        actionLabel: "处理数据",
      });
    }
    if (canPlan && (snapshot?.invalid_import_count ?? 0) > 0) {
      items.push({
        id: "invalid-import-rows",
        level: "warning",
        title: `${snapshot?.invalid_import_rows ?? 0} 行采集数据未通过校验`,
        description: `${referenceSummary(snapshot?.latest_invalid_import, snapshot?.invalid_import_count ?? 0, "个批次")}，建议下载质量报告并补齐关键字段。`,
        sectionId: "data-import-panel",
        importFocus: { importId: snapshot?.latest_invalid_import?.id },
        actionLabel: "查看质量",
      });
    }
    if (canPlan && data.qualitySummary?.warning_records) {
      items.push({
        id: "warning-quality-records",
        level: "warning",
        title: `${data.qualitySummary.warning_records.toLocaleString("zh-CN")} 条证据质量需要注意`,
        description: `数据已进入证据库，但上下文或关键字段存在风险${warningImportNames ? `，主要批次：${warningImportNames}` : ""}，建议筛选后处理。`,
        sectionId: "data-import-panel",
        actionLabel: "查看质量",
        importFocus: { importId: warningImport?.import_id, qualityStatus: "warning" },
      });
    }
    if (canPlan && data.qualitySummary?.blocked_records) {
      items.push({
        id: "blocked-quality-records",
        level: "error",
        title: `${data.qualitySummary.blocked_records.toLocaleString("zh-CN")} 条证据不可用`,
        description: `这些记录未达到可用标准，Agent 不应直接引用${blockedImportNames ? `，主要批次：${blockedImportNames}` : ""}，建议补齐来源或关键字段后重新导入。`,
        sectionId: "data-import-panel",
        actionLabel: "处理不可用数据",
        importFocus: { importId: blockedImport?.import_id, qualityStatus: "blocked" },
      });
    }
    if (canPlan && data.qualitySummary?.failed_index_records) {
      items.push({
        id: "failed-index-records",
        level: "error",
        title: `${data.qualitySummary.failed_index_records.toLocaleString("zh-CN")} 条证据索引失败`,
        description: `相关证据可能无法被 Agent 检索${failedIndexImportNames ? `，主要批次：${failedIndexImportNames}` : ""}，建议进入数据导入明细处理索引。`,
        sectionId: "data-import-panel",
        actionLabel: "处理索引",
        importFocus: { importId: failedIndexImport?.import_id, indexStatus: "failed" },
      });
    }
    const pendingIndexRecords = data.qualitySummary?.pending_index_records ?? 0;
    if (pendingIndexRecords > 0) {
      items.push({
        id: "pending-index-records",
        level: "info",
        title: `Milvus 索引处理中：${pendingIndexRecords.toLocaleString("zh-CN")} 条`,
        description: snapshot?.pending_index_import
          ? `${snapshot.pending_index_import.label}，数据解析已完成，向量索引完成后即可稳定检索。`
          : "数据解析已完成，向量索引完成后即可稳定检索。",
        sectionId: "data-import-panel",
        importFocus: {
          importId: snapshot?.pending_index_import?.id,
          indexStatus: "indexing",
        },
        actionLabel: "查看进度",
      });
    }
    if (partialError) {
      items.push({
        id: "partial-refresh-error",
        level: "warning",
        title: "部分待办数据刷新失败",
        description: "当前继续展示最近一次可用结果，系统会自动重试。",
      });
    }
    return items;
  }, [canApprove, canPlan, connectionStatus, data, identityState, partialError]);

  const actionableCount = reminders.filter((item) => item.level !== "success").length;

  const navigateTo = (
    sectionId?: string,
    targetId?: string,
    targetType?: ReminderTargetType,
    importFocus?: ImportFocus,
  ) => {
    if (!sectionId) return;
    setOpen(false);
    window.setTimeout(() => {
      if (targetId && targetType === "planning-approval") {
        window.dispatchEvent(
          new CustomEvent("merchpilot:focus-approval", {
            detail: { kind: "planning", taskId: targetId },
          }),
        );
      } else if (targetId && targetType === "launch-review") {
        window.dispatchEvent(
          new CustomEvent("merchpilot:focus-approval", {
            detail: { kind: "launch-review", reviewId: targetId },
          }),
        );
      } else if (targetId && targetType === "selected-product") {
        window.dispatchEvent(
          new CustomEvent("merchpilot:focus-selected-products", {
            detail: { productId: targetId },
          }),
        );
      } else if (targetId && targetType === "initiative-create") {
        window.dispatchEvent(
          new CustomEvent("merchpilot:focus-initiative-create", {
            detail: { selectedProductId: targetId },
          }),
        );
      } else if (targetId && targetType === "planning-project") {
        window.dispatchEvent(
          new CustomEvent("merchpilot:focus-planning-project", {
            detail: { projectId: targetId },
          }),
        );
      } else if (targetId && targetType === "initiative") {
        window.dispatchEvent(
          new CustomEvent("merchpilot:focus-initiative", {
            detail: { initiativeId: targetId },
          }),
        );
      }
      if (importFocus) {
        window.dispatchEvent(
          new CustomEvent("merchpilot:focus-import", {
            detail: { ...importFocus },
          }),
        );
      }
      document.getElementById(sectionId)?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 150);
  };

  return (
    <>
      <Badge count={actionableCount} overflowCount={99} size="small">
        <Button
          shape="circle"
          aria-label={`待办与提醒${actionableCount ? `，共 ${actionableCount} 项` : ""}`}
          icon={<BellOutlined />}
          onClick={() => setOpen(true)}
        />
      </Badge>
      <Drawer
        title="待办与提醒"
        open={open}
        onClose={() => setOpen(false)}
        size="min(460px, 94vw)"
        extra={
          <Button
            size="small"
            icon={<ReloadOutlined />}
            loading={refreshing}
            onClick={() => void refresh()}
          >
            刷新
          </Button>
        }
      >
        <div className="notification-summary">
          <div>
            <strong>{actionableCount}</strong>
            <span>项需要关注</span>
          </div>
          <small>
            {refreshedAt
              ? `最近刷新 ${refreshedAt.toLocaleTimeString("zh-CN", { hour12: false })}`
              : "正在汇总业务状态"}
          </small>
        </div>
        {loading ? (
          <div className="notification-loading"><Spin /></div>
        ) : reminders.length > 0 ? (
          <List
            className="notification-list"
            dataSource={reminders}
            renderItem={(item) => {
              const presentation = levelPresentation[item.level];
              return (
                <List.Item
                  actions={item.sectionId ? [
                    <Button
                      type="link"
                      size="small"
                      key="action"
                      onClick={() => navigateTo(
                        item.sectionId,
                        item.targetId,
                        item.targetType,
                        item.importFocus,
                      )}
                    >
                      {item.actionLabel ?? "查看"} <RightOutlined />
                    </Button>,
                  ] : undefined}
                >
                  <List.Item.Meta
                    avatar={
                      item.level === "success"
                        ? <CheckCircleOutlined className="notification-icon success" />
                        : <ExclamationCircleOutlined className={`notification-icon ${item.level}`} />
                    }
                    title={
                      <Space size={6} wrap>
                        <span>{item.title}</span>
                        <Tag color={presentation.color}>{presentation.label}</Tag>
                      </Space>
                    }
                    description={item.description}
                  />
                </List.Item>
              );
            }}
          />
        ) : (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="当前没有待办，核心服务和业务流程均正常"
          />
        )}
      </Drawer>
    </>
  );
}
