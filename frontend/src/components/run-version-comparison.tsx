/**
 * 文件职责：比较同一规划项目不同运行版本的指标和方案差异。
 */

"use client";

import { useEffect, useMemo, useState } from "react";
import { Alert, Drawer, Empty, Select, Spin, Tag } from "antd";

import { getProjectRun, PlanningRun } from "@/lib/http/planning";

/** 定义`RunVersionComparisonProps`数据契约，约束组件属性或接口响应字段。 */
interface RunVersionComparisonProps {
  open: boolean;
  projectId?: string;
  runs: PlanningRun[];
  leftRunId?: string;
  rightRunId?: string;
  onLeftRunChange: (runId: string) => void;
  onRightRunChange: (runId: string) => void;
  onClose: () => void;
}

/** 定义`ComparisonMetric`数据契约，约束组件属性或接口响应字段。 */
interface ComparisonMetric {
  key: string;
  label: string;
  left: string;
  right: string;
  trend?: "up" | "down" | "same";
}

/** 定义`statusPresentation`展示映射，集中维护状态文案、颜色或选项。 */
const statusPresentation: Record<string, { color: string; label: string }> = {
  queued: { color: "default", label: "排队中" },
  running: { color: "processing", label: "执行中" },
  approval_required: { color: "warning", label: "等待审批" },
  completed: { color: "success", label: "已完成" },
  failed: { color: "error", label: "失败" },
  cancelled: { color: "default", label: "已取消" },
  superseded: { color: "default", label: "已生成新版本" },
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
  fixed_cost: "固定投入",
  logistics_cost: "单件物流成本",
  platform_fee_rate: "平台费率",
  tax_rate: "税费率",
  marketing_rate: "营销费率",
};

/** 实现`asRecord`辅助逻辑，集中处理页面展示或状态转换规则。 */
function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};
}

/** 实现`numberValue`辅助逻辑，集中处理页面展示或状态转换规则。 */
function numberValue(value: unknown): number | undefined {
  return typeof value === "number" ? value : undefined;
}

/** 把formatDateTime相关原始值格式化为页面可读文本。 */
function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

/** 把formatConstraintValue相关原始值格式化为页面可读文本。 */
function formatConstraintValue(key: string, value: unknown): string {
  if (value === undefined || value === null || value === "") {
    return "未设置";
  }
  if (["target_margin", "platform_fee_rate", "tax_rate", "marketing_rate"].includes(key)) {
    return typeof value === "number" ? `${(value * 100).toFixed(1)}%` : String(value);
  }
  if (["selling_price", "unit_cost", "fixed_cost", "logistics_cost"].includes(key)) {
    return typeof value === "number" ? `¥${value.toFixed(2)}` : String(value);
  }
  if (key === "lead_time_days" || key === "max_lead_time_days") {
    return typeof value === "number" ? `${value} 天` : String(value);
  }
  if (key === "moq" || key === "forecast_units") {
    return typeof value === "number" ? `${value.toLocaleString("zh-CN")} 件` : String(value);
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

/** 实现`riskLabel`辅助逻辑，集中处理页面展示或状态转换规则。 */
function riskLabel(value: unknown): string {
  if (value === "low") return "低风险";
  if (value === "medium") return "中风险";
  if (value === "high") return "高风险";
  return "待评估";
}

/** 实现`trend`辅助逻辑，集中处理页面展示或状态转换规则。 */
function trend(left: number | undefined, right: number | undefined): ComparisonMetric["trend"] {
  if (left === undefined || right === undefined) return undefined;
  if (right > left) return "up";
  if (right < left) return "down";
  return "same";
}

/** 实现`resultMetrics`辅助逻辑，集中处理页面展示或状态转换规则。 */
function resultMetrics(leftRun: PlanningRun, rightRun: PlanningRun): ComparisonMetric[] {
  const leftOutputs = asRecord(leftRun.result_snapshot?.outputs);
  const rightOutputs = asRecord(rightRun.result_snapshot?.outputs);
  const leftScore = asRecord(leftOutputs.scorecard);
  const rightScore = asRecord(rightOutputs.scorecard);
  const leftFinance = asRecord(leftOutputs.finance);
  const rightFinance = asRecord(rightOutputs.finance);
  const leftSupplier = asRecord(leftOutputs.supplier);
  const rightSupplier = asRecord(rightOutputs.supplier);

  const leftOpportunityScore = numberValue(leftScore.score);
  const rightOpportunityScore = numberValue(rightScore.score);
  const leftEvidenceCount = numberValue(leftScore.evidence_count);
  const rightEvidenceCount = numberValue(rightScore.evidence_count);
  const leftMargin = numberValue(leftFinance.margin_rate);
  const rightMargin = numberValue(rightFinance.margin_rate);
  const leftProfit = numberValue(leftFinance.estimated_profit);
  const rightProfit = numberValue(rightFinance.estimated_profit);
  const leftBreakEven = numberValue(leftFinance.break_even_units);
  const rightBreakEven = numberValue(rightFinance.break_even_units);

  return [
    {
      key: "score",
      label: "机会分",
      left: leftOpportunityScore === undefined ? "待计算" : String(leftOpportunityScore),
      right: rightOpportunityScore === undefined ? "待计算" : String(rightOpportunityScore),
      trend: trend(leftOpportunityScore, rightOpportunityScore),
    },
    {
      key: "evidence",
      label: "核心证据",
      left: leftEvidenceCount === undefined ? "待计算" : `${leftEvidenceCount} 条`,
      right: rightEvidenceCount === undefined ? "待计算" : `${rightEvidenceCount} 条`,
      trend: trend(leftEvidenceCount, rightEvidenceCount),
    },
    {
      key: "margin",
      label: "预计毛利率",
      left: leftMargin === undefined ? "待计算" : `${(leftMargin * 100).toFixed(1)}%`,
      right: rightMargin === undefined ? "待计算" : `${(rightMargin * 100).toFixed(1)}%`,
      trend: trend(leftMargin, rightMargin),
    },
    {
      key: "profit",
      label: "预计利润",
      left: leftProfit === undefined ? "待计算" : `¥${leftProfit.toLocaleString("zh-CN")}`,
      right: rightProfit === undefined ? "待计算" : `¥${rightProfit.toLocaleString("zh-CN")}`,
      trend: trend(leftProfit, rightProfit),
    },
    {
      key: "break_even",
      label: "盈亏平衡",
      left: leftBreakEven === undefined ? "待计算" : `${leftBreakEven} 件`,
      right: rightBreakEven === undefined ? "待计算" : `${rightBreakEven} 件`,
      trend:
        leftBreakEven === undefined || rightBreakEven === undefined
          ? undefined
          : trend(rightBreakEven, leftBreakEven),
    },
    {
      key: "supplier_risk",
      label: "供应风险",
      left: riskLabel(leftSupplier.risk_level),
      right: riskLabel(rightSupplier.risk_level),
    },
  ];
}

/** 比较同一规划项目不同运行版本的指标、候选方案和结论变化。 */
export function RunVersionComparison({
  open,
  projectId,
  runs,
  leftRunId,
  rightRunId,
  onLeftRunChange,
  onRightRunChange,
  onClose,
}: RunVersionComparisonProps) {
  const [loadedRuns, setLoadedRuns] = useState<Record<string, PlanningRun>>({});
  const [error, setError] = useState<string>();

  useEffect(() => {
    if (!open || !projectId || !leftRunId || !rightRunId || leftRunId === rightRunId) {
      return;
    }
    let active = true;
    void Promise.all([
      getProjectRun(projectId, leftRunId),
      getProjectRun(projectId, rightRunId),
    ])
      .then(([leftRun, rightRun]) => {
        if (active) {
          setLoadedRuns((current) => ({
            ...current,
            [leftRun.id]: leftRun,
            [rightRun.id]: rightRun,
          }));
          setError(undefined);
        }
      })
      .catch((loadError: unknown) => {
        if (active) {
          setError(loadError instanceof Error ? loadError.message : "无法加载运行版本");
        }
      });
    return () => {
      active = false;
    };
  }, [leftRunId, open, projectId, rightRunId]);

  const leftRun = leftRunId ? loadedRuns[leftRunId] : undefined;
  const rightRun = rightRunId ? loadedRuns[rightRunId] : undefined;
  const loading = Boolean(
    open && leftRunId && rightRunId && (!leftRun || !rightRun),
  );
  const constraintChanges = useMemo(() => {
    if (!leftRun || !rightRun) return [];
    const leftConstraints = asRecord(leftRun.input_snapshot?.constraints);
    const rightConstraints = asRecord(rightRun.input_snapshot?.constraints);
    const keys = new Set([...Object.keys(leftConstraints), ...Object.keys(rightConstraints)]);
    return [...keys]
      .filter((key) => JSON.stringify(leftConstraints[key]) !== JSON.stringify(rightConstraints[key]))
      .map((key) => ({
        key,
        label: constraintLabels[key] ?? key.replaceAll("_", " "),
        left: formatConstraintValue(key, leftConstraints[key]),
        right: formatConstraintValue(key, rightConstraints[key]),
      }));
  }, [leftRun, rightRun]);
  const metrics = useMemo(
    () => (leftRun && rightRun ? resultMetrics(leftRun, rightRun) : []),
    [leftRun, rightRun],
  );

  const runOptions = runs.map((run) => ({
    value: run.id,
    label: `第 ${run.revision_no} 版 · ${statusPresentation[run.status]?.label ?? run.status}`,
  }));

  return (
    <Drawer
      title="运行版本对比"
      size="min(1120px, 96vw)"
      open={open}
      onClose={onClose}
    >
      <div className="run-comparison-toolbar">
        <Select
          value={leftRunId}
          options={runOptions.map((option) => ({
            ...option,
            disabled: option.value === rightRunId,
          }))}
          onChange={onLeftRunChange}
          placeholder="选择较早版本"
        />
        <span>对比</span>
        <Select
          value={rightRunId}
          options={runOptions.map((option) => ({
            ...option,
            disabled: option.value === leftRunId,
          }))}
          onChange={onRightRunChange}
          placeholder="选择较新版本"
        />
      </div>

      {error ? <Alert type="error" showIcon message={error} className="run-comparison-alert" /> : null}
      {loading ? (
        <div className="run-comparison-loading"><Spin tip="正在加载版本数据" /></div>
      ) : leftRun && rightRun ? (
        <div className="run-comparison-content">
          <div className="run-comparison-versions">
            {[leftRun, rightRun].map((run) => {
              const presentation = statusPresentation[run.status] ?? {
                color: "default",
                label: run.status,
              };
              return (
                <article key={run.id}>
                  <div>
                    <strong>第 {run.revision_no} 版</strong>
                    <Tag color={presentation.color}>{presentation.label}</Tag>
                  </div>
                  <span>{formatDateTime(run.created_at)}</span>
                  <small>{run.id}</small>
                </article>
              );
            })}
          </div>

          <section className="run-comparison-section">
            <div className="run-comparison-heading">
              <div><strong>关键结果变化</strong><span>对比两轮规划的决策指标</span></div>
            </div>
            <div className="run-comparison-metrics">
              {metrics.map((metric) => (
                <article key={metric.key}>
                  <span>{metric.label}</span>
                  <div>
                    <b>{metric.left}</b>
                    <span className={`run-comparison-trend ${metric.trend ?? "neutral"}`}>→</span>
                    <b>{metric.right}</b>
                  </div>
                </article>
              ))}
            </div>
          </section>

          <section className="run-comparison-section">
            <div className="run-comparison-heading">
              <div><strong>参数差异</strong><span>仅展示两轮之间发生变化的约束条件</span></div>
              <Tag>{constraintChanges.length} 项变化</Tag>
            </div>
            {constraintChanges.length ? (
              <div className="run-comparison-diffs">
                {constraintChanges.map((item) => (
                  <div key={item.key}>
                    <span>{item.label}</span>
                    <b>{item.left}</b>
                    <span>→</span>
                    <b>{item.right}</b>
                  </div>
                ))}
              </div>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="两轮运行参数没有变化" />
            )}
          </section>
        </div>
      ) : (
        <Empty description="请选择两个不同运行版本" />
      )}
    </Drawer>
  );
}
