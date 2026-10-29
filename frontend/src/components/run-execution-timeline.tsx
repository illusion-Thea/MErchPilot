/**
 * 文件职责：按时间和节点展示 Agent 执行、重试、复用和失败事件。
 */

"use client";

import { useMemo } from "react";

import type { RunEvent } from "@/lib/ws/run-socket";
import type { AgentNodeExecution, AgentNodeStatus } from "@/store/run-slice";

/** 定义`RunExecutionTimelineProps`数据契约，约束组件属性或接口响应字段。 */
interface RunExecutionTimelineProps {
  statuses: Record<string, AgentNodeStatus>;
  details: Record<string, AgentNodeExecution>;
  events: RunEvent[];
}

/** 定义`TimelineNode`数据契约，约束组件属性或接口响应字段。 */
interface TimelineNode {
  id: string;
  label: string;
  description: string;
}

/** 定义`timelineNodes`模块常量或配置，供当前文件中的多个流程复用。 */
const timelineNodes: TimelineNode[] = [
  { id: "requirement", label: "需求分析", description: "规范化品类、市场和规划约束" },
  { id: "researchPlan", label: "研究规划", description: "为三类证据选择检索策略和字段" },
  { id: "market", label: "市场研究", description: "检索市场规模、趋势和价格带证据" },
  { id: "competitor", label: "竞品分析", description: "提取竞品、卖点、品牌和定价信息" },
  { id: "insight", label: "用户洞察", description: "归纳目标用户、痛点和使用场景" },
  { id: "researchSynthesis", label: "证据治理", description: "检查覆盖度、质量和证据冲突" },
  { id: "concept", label: "概念方案", description: "汇总证据并生成候选商品概念" },
  { id: "supplier", label: "供应商评估", description: "评估供应商、MOQ、交期和供应风险" },
  { id: "finance", label: "财务测算", description: "计算毛利、利润和盈亏平衡" },
  { id: "scoring", label: "机会评分", description: "输出证据、财务、供应和完整度评分" },
  { id: "critic", label: "方案审查", description: "反驳方案并识别幻觉、矛盾和阻塞项" },
  { id: "narrative", label: "规划建议", description: "生成摘要、建议动作和风险提示" },
  { id: "approval", label: "线上审批", description: "创建内部审批任务并等待业务决策" },
];

/** 定义`statusLabels`展示映射，集中维护状态文案、颜色或选项。 */
const statusLabels: Record<AgentNodeStatus, string> = {
  completed: "已完成",
  running: "执行中",
  waiting: "等待中",
  retrying: "重试中",
  failed: "失败",
};

/** 定义`statusClassNames`模块常量或配置，供当前文件中的多个流程复用。 */
const statusClassNames: Record<AgentNodeStatus, string> = {
  completed: "completed",
  running: "running",
  waiting: "waiting",
  retrying: "retrying",
  failed: "failed",
};

/** 定义`eventNodeLabels`展示映射，集中维护状态文案、颜色或选项。 */
const eventNodeLabels: Record<string, string> = {
  requirement_agent: "需求分析",
  research_planning_agent: "研究规划",
  market_agent: "市场研究",
  competitor_agent: "竞品分析",
  user_insight_agent: "用户洞察",
  research_synthesis_agent: "证据治理",
  concept_agent: "概念方案",
  supplier_agent: "供应商评估",
  finance_agent: "财务测算",
  scoring_agent: "机会评分",
  critic_agent: "方案审查",
  narrative_agent: "规划建议",
  review_agent: "线上审批",
};

/** 定义`eventLabels`展示映射，集中维护状态文案、颜色或选项。 */
const eventLabels: Record<string, string> = {
  "run.started": "运行开始",
  "run.resumed": "运行恢复",
  "run.completed": "运行完成",
  "run.failed": "运行失败",
  "approval.required": "等待审批",
  "approval.completed": "审批完成",
  "run.revision_created": "创建修订版本",
  "agent.node.started": "节点开始",
  "agent.node.retrying": "节点重试",
  "agent.node.failed": "节点失败",
  "agent.node.skipped": "复用已有结果",
  "agent.node.completed": "节点完成",
};

/** 把formatDateTime相关原始值格式化为页面可读文本。 */
function formatDateTime(value?: string): string {
  if (!value) {
    return "时间未记录";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "时间未记录";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

/** 把formatEventDetail相关原始值格式化为页面可读文本。 */
function formatEventDetail(event: RunEvent): string {
  const payload = event.payload ?? {};
  const node = typeof payload.node === "string" ? payload.node : "";
  const nodeLabel = eventNodeLabels[node] ?? node;
  const attempt = typeof payload.attempt === "number" ? `第 ${payload.attempt} 次` : "";
  const error = typeof payload.error === "string" ? payload.error : "";
  if (error) {
    return `${nodeLabel || "运行"}${attempt ? ` · ${attempt}` : ""}：${error}`;
  }
  if (node) {
    return `${nodeLabel}${attempt ? ` · ${attempt}` : ""}`;
  }
  return "实时事件已同步";
}

/** 按节点和时间展示Agent执行、重试、复用和失败事件。 */
export function RunExecutionTimeline({
  statuses,
  details,
  events,
}: RunExecutionTimelineProps) {
  const recentEvents = useMemo(
    () => events.filter((event) => event.event_type !== "heartbeat").slice(-6).reverse(),
    [events],
  );

  return (
    <section className="run-execution-panel" aria-label="Agent 执行明细">
      <div className="run-execution-heading">
        <div>
          <strong>执行明细</strong>
          <span>状态会写入运行快照，刷新页面后仍可追溯</span>
        </div>
        {recentEvents.length > 0 ? <span className="run-execution-live">实时更新中</span> : null}
      </div>
      <div className="run-execution-layout">
        <div className="run-execution-timeline">
          {timelineNodes.map((node) => {
            const status = statuses[node.id] ?? "waiting";
            const detail = details[node.id];
            const attempt = detail?.attempt && detail.max_attempts
              ? `尝试 ${detail.attempt}/${detail.max_attempts}`
              : detail?.attempt
                ? `尝试 ${detail.attempt}`
                : "";
            return (
              <div className={`run-execution-item run-execution-item-${statusClassNames[status]}`} key={node.id}>
                <div className="run-execution-marker" />
                <div className="run-execution-content">
                  <div className="run-execution-item-header">
                    <strong>{node.label}</strong>
                    <span>{statusLabels[status]}</span>
                  </div>
                  <p>{node.description}</p>
                  <div className="run-execution-meta">
                    {detail?.reused ? <em>已复用</em> : null}
                    {attempt ? <em>{attempt}</em> : null}
                    {detail?.updated_at ? <small>{formatDateTime(detail.updated_at)}</small> : null}
                  </div>
                  {detail?.error ? <div className="run-execution-error">{detail.error}</div> : null}
                </div>
              </div>
            );
          })}
        </div>
        <div className="run-event-feed">
          <div className="run-event-feed-heading">
            <strong>最近事件</strong>
            <span>{recentEvents.length} 条</span>
          </div>
          {recentEvents.length > 0 ? (
            <div className="run-event-list">
              {recentEvents.map((event, index) => (
                <div className="run-event-item" key={`${event.event_id ?? event.occurred_at ?? "event"}-${index}`}>
                  <div>
                    <strong>{eventLabels[event.event_type] ?? event.event_type}</strong>
                    <small>{formatDateTime(event.occurred_at)}</small>
                  </div>
                  <span>{formatEventDetail(event)}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="run-event-empty">连接后会在这里显示实时事件</div>
          )}
        </div>
      </div>
    </section>
  );
}
