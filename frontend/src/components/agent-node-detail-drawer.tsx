/**
 * 文件职责：展示单个规划执行节点的输入、输出、证据和失败详情。
 */

"use client";

import { Descriptions, Drawer, Empty, List, Progress, Space, Tag } from "antd";

import type { AgentNodeExecution, AgentNodeStatus } from "@/store/run-slice";

/** 定义`AgentNodeDetailDrawerProps`数据契约，约束组件属性或接口响应字段。 */
interface AgentNodeDetailDrawerProps {
  open: boolean;
  nodeId?: string;
  status?: AgentNodeStatus;
  execution?: AgentNodeExecution;
  output?: unknown;
  onClose: () => void;
}

/** 定义`NodeDefinition`数据契约，约束组件属性或接口响应字段。 */
interface NodeDefinition {
  label: string;
  description: string;
  executionType: "llm_agent" | "prompt_agent" | "deterministic_tool" | "human_gate";
  boundary: string;
}

/** 定义`nodeDefinitions`展示映射，集中维护状态文案、颜色或选项。 */
const nodeDefinitions: Record<string, NodeDefinition> = {
  requirement: { label: "需求分析", description: "规范化品类、目标市场和规划约束", executionType: "llm_agent", boundary: "不补充未经证实的业务事实" },
  researchPlan: { label: "研究规划", description: "选择市场、竞品和用户洞察的检索策略", executionType: "llm_agent", boundary: "只规划证据获取，不直接下结论" },
  market: { label: "市场研究", description: "检索市场规模、趋势、销量和价格带证据", executionType: "deterministic_tool", boundary: "只返回带来源的检索结果" },
  competitor: { label: "竞品分析", description: "检索竞品、品牌、卖点、定价和销量证据", executionType: "deterministic_tool", boundary: "只返回带来源的检索结果" },
  insight: { label: "用户洞察", description: "检索目标用户、需求、痛点和使用场景证据", executionType: "deterministic_tool", boundary: "不把无证据推断当作用户事实" },
  researchSynthesis: { label: "证据治理", description: "检查覆盖度、证据质量和数据冲突", executionType: "deterministic_tool", boundary: "不把缺失字段补成事实" },
  concept: { label: "概念方案", description: "整合研究结果并生成候选商品概念", executionType: "llm_agent", boundary: "不虚构价格、成本、供应商或销量" },
  supplier: { label: "供应商评估", description: "评估供应商完整度、MOQ、交期和风险", executionType: "deterministic_tool", boundary: "不替供应商做事实承诺" },
  finance: { label: "财务测算", description: "测算毛利率、预计利润和盈亏平衡", executionType: "deterministic_tool", boundary: "关键财务数字由确定性规则计算" },
  scoring: { label: "机会评分", description: "输出证据、财务、供应和完整度评分", executionType: "deterministic_tool", boundary: "评分必须能由输入数据复算" },
  critic: { label: "方案审查", description: "反驳候选方案并识别阻塞项和逻辑矛盾", executionType: "llm_agent", boundary: "不能因模型自报 ready 而绕过守门" },
  narrative: { label: "规划建议", description: "生成摘要、建议动作和风险提示", executionType: "llm_agent", boundary: "不替审批人做业务决策" },
  approval: { label: "线上审批", description: "创建内部审批任务并记录业务决策", executionType: "human_gate", boundary: "只能等待人工决定，不能自动放行" },
};

const executionTypeLabels: Record<NodeDefinition["executionType"], string> = {
  llm_agent: "LLM Agent",
  prompt_agent: "LLM Agent",
  deterministic_tool: "确定性工具/引擎",
  human_gate: "人工审批门禁",
};

/** 定义`statusLabels`展示映射，集中维护状态文案、颜色或选项。 */
const statusLabels: Record<AgentNodeStatus, string> = {
  completed: "已完成",
  running: "执行中",
  waiting: "等待中",
  retrying: "重试中",
  failed: "失败",
};

/** 定义`statusColors`展示映射，集中维护状态文案、颜色或选项。 */
const statusColors: Record<AgentNodeStatus, string> = {
  completed: "success",
  running: "processing",
  waiting: "default",
  retrying: "warning",
  failed: "error",
};

/** 实现`asRecord`辅助逻辑，集中处理页面展示或状态转换规则。 */
function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

/** 实现`stringList`辅助逻辑，集中处理页面展示或状态转换规则。 */
function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && Boolean(item.trim()))
    : [];
}

/** 把formatValue相关原始值格式化为页面可读文本。 */
function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "未提供";
  }
  if (typeof value === "boolean") {
    return value ? "是" : "否";
  }
  if (typeof value === "number") {
    return value.toLocaleString("zh-CN");
  }
  if (typeof value === "string") {
    return value;
  }
  return JSON.stringify(value, null, 2);
}

/** 把formatPercent相关原始值格式化为页面可读文本。 */
function formatPercent(value: unknown): string {
  return typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "未提供";
}

/** 把formatMoney相关原始值格式化为页面可读文本。 */
function formatMoney(value: unknown): string {
  return typeof value === "number" ? `¥${value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}` : "未提供";
}

/** 从节点执行追踪中提取指定字段，避免把未知运行数据直接当成对象访问。 */
function traceValue(trace: Record<string, unknown> | undefined, field: string): unknown {
  if (!trace) {
    return undefined;
  }
  for (const value of Object.values(trace)) {
    const record = asRecord(value);
    if (record[field] !== undefined && record[field] !== null && record[field] !== "") {
      return record[field];
    }
  }
  return undefined;
}

/** 实现`statusTag`辅助逻辑，集中处理页面展示或状态转换规则。 */
function statusTag(value: unknown): React.ReactNode {
  if (value === "ready") {
    return <Tag color="success">正常</Tag>;
  }
  if (value === "partial") {
    return <Tag color="warning">部分结果</Tag>;
  }
  if (value === "degraded") {
    return <Tag color="error">降级</Tag>;
  }
  if (value === "requires_supplier_data" || value === "requires_cost_data") {
    return <Tag color="warning">需要补充数据</Tag>;
  }
  return <Tag>{formatValue(value)}</Tag>;
}

/** 实现`renderResearchOutput`辅助逻辑，集中处理页面展示或状态转换规则。 */
function renderResearchOutput(output: Record<string, unknown>) {
  const hits = Array.isArray(output.hits) ? output.hits : [];
  return (
    <div className="agent-node-detail-body">
      <div className="agent-node-stat-grid">
        <div><span>检索状态</span><strong>{statusTag(output.status)}</strong></div>
        <div><span>证据数量</span><strong>{formatValue(output.evidence_ids && Array.isArray(output.evidence_ids) ? output.evidence_ids.length : 0)} 条</strong></div>
        <div><span>命中数量</span><strong>{hits.length} 条</strong></div>
      </div>
      {hits.length > 0 ? (
        <List
          className="agent-node-evidence-list"
          size="small"
          dataSource={hits}
          renderItem={(item, index) => {
            const hit = asRecord(item);
            return (
              <List.Item>
                <div className="agent-node-evidence-item">
                  <div className="agent-node-evidence-heading">
                    <strong>#{index + 1} {formatValue(hit.source_name ?? hit.id)}</strong>
                    <Space size={4}>
                      {hit.quality_status ? <Tag color={hit.quality_status === "verified" ? "success" : "warning"}>{formatValue(hit.quality_status)}</Tag> : null}
                      {typeof hit.score === "number" ? <Tag>相关度 {hit.score.toFixed(2)}</Tag> : null}
                    </Space>
                  </div>
                  <p>{formatValue(hit.content)}</p>
                  <span>{formatValue(hit.target_market)} · {formatValue(hit.category)}</span>
                </div>
              </List.Item>
            );
          }}
        />
      ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无检索命中" />}
    </div>
  );
}

/** 实现`renderStructuredOutput`辅助逻辑，集中处理页面展示或状态转换规则。 */
function renderStructuredOutput(nodeId: string, output: Record<string, unknown>) {
  if (["market", "competitor", "insight"].includes(nodeId)) {
    return renderResearchOutput(output);
  }

  if (nodeId === "researchPlan") {
    return (
      <div className="agent-node-detail-body">
        <Descriptions bordered size="small" column={1} items={[
          { key: "market", label: "市场查询", children: formatValue(output.market_query) },
          { key: "competitor", label: "竞品查询", children: formatValue(output.competitor_query) },
          { key: "insight", label: "用户查询", children: formatValue(output.user_insight_query) },
          { key: "rationale", label: "策略说明", children: formatValue(output.rationale) },
        ]} />
      </div>
    );
  }

  if (nodeId === "researchSynthesis") {
    const actions = stringList(output.follow_up_actions);
    const conflicts = Array.isArray(output.conflicts) ? output.conflicts.map(asRecord) : [];
    return (
      <div className="agent-node-detail-body">
        <div className="agent-node-stat-grid">
          <div><span>治理状态</span><strong>{statusTag(output.status)}</strong></div>
          <div><span>冲突数量</span><strong>{formatValue(output.conflict_count)} 条</strong></div>
          <div><span>补检索主题</span><strong>{formatValue(output.supplemented_count)} 个</strong></div>
        </div>
        {conflicts.length > 0 ? <List size="small" header="证据冲突" bordered dataSource={conflicts} renderItem={(item) => <List.Item>{formatValue(item.reason)}</List.Item>} /> : null}
        {actions.length > 0 ? <List size="small" header="后续动作" bordered dataSource={actions} renderItem={(item) => <List.Item>{item}</List.Item>} /> : null}
      </div>
    );
  }

  if (nodeId === "critic") {
    const findings = Array.isArray(output.findings) ? output.findings.map(asRecord) : [];
    return (
      <div className="agent-node-detail-body">
        <div className="agent-node-summary-box"><span>审查结论</span><p>{formatValue(output.summary)}</p></div>
        {findings.length > 0 ? <List size="small" header="审查发现" bordered dataSource={findings} renderItem={(item) => <List.Item><Space wrap><Tag color={item.severity === "blocker" ? "error" : "warning"}>{formatValue(item.severity)}</Tag><span>{formatValue(item.issue)}</span></Space></List.Item>} /> : null}
      </div>
    );
  }

  if (nodeId === "concept") {
    const candidates = Array.isArray(output.candidates) ? output.candidates.map(asRecord) : [];
    return (
      <div className="agent-node-detail-body">
        <div className="agent-node-stat-grid">
          <div><span>候选方案</span><strong>{formatValue(output.candidate_count)} 个</strong></div>
          <div><span>生成方式</span><strong>{formatValue(output.generation_mode)}</strong></div>
          <div><span>状态</span><strong><Tag color="warning">需要验证</Tag></strong></div>
        </div>
        {candidates.length > 0 ? (
          <div className="agent-concept-candidate-list">
            {candidates.map((candidate, index) => {
              const priceReference = asRecord(candidate.price_reference);
              const financialScenario = asRecord(candidate.financial_scenario);
              const scorecard = asRecord(candidate.scorecard);
              const features = stringList(candidate.evidence_features);
              const painPoints = stringList(candidate.pain_points_addressed);
              const risks = stringList(candidate.risks);
              const validationPlan = asRecord(candidate.validation_plan);
              const validationGates = Array.isArray(validationPlan.gates)
                ? validationPlan.gates.map(asRecord)
                : [];
              return (
                <div className="agent-concept-candidate" key={formatValue(candidate.id)}>
                  <div className="agent-concept-candidate-header">
                    <strong>{index + 1}. {formatValue(candidate.name)}</strong>
                    <Tag color={index === 0 ? "blue" : "default"}>{index === 0 ? "优先验证" : formatValue(candidate.confidence)}</Tag>
                  </div>
                  <p>{formatValue(candidate.positioning)}</p>
                  <div className="agent-node-detail-tags">
                    <span>方案分</span><Tag color={candidate.recommendation === "优先验证" ? "blue" : "default"}>{formatValue(scorecard.total_score)}</Tag>
                    <span>建议</span><Tag color={candidate.recommendation === "优先验证" ? "processing" : "default"}>{formatValue(candidate.recommendation)}</Tag>
                    <span>售价</span><Tag>{formatMoney(financialScenario.selling_price ?? priceReference.suggested_price)}</Tag>
                    <span>毛利率</span><Tag>{formatPercent(financialScenario.margin_rate)}</Tag>
                    <span>预计利润</span><Tag>{formatMoney(financialScenario.estimated_profit)}</Tag>
                    <span>证据</span><Tag>{stringList(candidate.evidence_ids).length} 条</Tag>
                  </div>
                  <div className="agent-node-detail-tags">
                    <span>落地验证</span>
                    <Tag color={validationPlan.status === "ready" ? "success" : validationPlan.status === "blocked" ? "error" : "warning"}>
                      {formatValue(validationPlan.status_label || validationPlan.status)} · {formatValue(validationPlan.completed_gates)}/{formatValue(validationPlan.total_gates)}
                    </Tag>
                  </div>
                  {validationGates.length > 0 ? (
                    <div className="agent-node-detail-tags">
                      <span>验证门槛</span>
                      {validationGates.map((gate, gateIndex) => (
                        <Tag
                          color={gate.status === "ready" ? "success" : gate.status === "blocked" ? "error" : "warning"}
                          key={formatValue(gate.id || gateIndex)}
                        >
                          {formatValue(gate.label)} · {gate.status === "ready" ? "已通过" : gate.status === "blocked" ? "阻塞" : "待完成"}
                        </Tag>
                      ))}
                    </div>
                  ) : null}
                  {stringList(validationPlan.next_actions).length > 0 ? (
                    <div className="agent-node-detail-tags">
                      <span>下一动作</span>
                      <span>{stringList(validationPlan.next_actions).join("；")}</span>
                    </div>
                  ) : null}
                  {features.length > 0 ? <div className="agent-node-detail-tags"><span>特征</span>{features.map((item) => <Tag key={item}>{item}</Tag>)}</div> : null}
                  {painPoints.length > 0 ? <div className="agent-node-detail-tags"><span>痛点</span>{painPoints.map((item) => <Tag color="warning" key={item}>{item}</Tag>)}</div> : null}
                  {risks.length > 0 ? <div className="agent-node-detail-tags"><span>风险</span><span>{risks.join("；")}</span></div> : null}
                </div>
              );
            })}
          </div>
        ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无候选方案" />}
      </div>
    );
  }

  if (nodeId === "finance") {
    const fields: Array<[string, React.ReactNode]> = [
      ["状态", statusTag(output.status)],
      ["销售价格", formatMoney(output.selling_price)],
      ["单位成本", formatMoney(output.unit_cost)],
      ["单位贡献毛利", formatMoney(output.contribution_margin_per_unit)],
      ["毛利率", formatPercent(output.margin_rate)],
      ["预计收入", formatMoney(output.estimated_revenue)],
      ["预计利润", formatMoney(output.estimated_profit)],
      ["盈亏平衡", typeof output.break_even_units === "number" ? `${output.break_even_units.toLocaleString("zh-CN")} 件` : "未提供"],
      ["目标毛利达标", output.passed_target_margin === undefined ? "未判断" : formatValue(output.passed_target_margin)],
      ["数据指标记录", typeof output.metrics_record_count === "number" ? `${output.metrics_record_count.toLocaleString("zh-CN")} 条` : "未接入"],
      ["数据补全字段", stringList(output.data_backed_fields).join("、") || "无"],
    ];
    return <Descriptions className="agent-node-descriptions" bordered size="small" column={2} items={fields.map(([label, children]) => ({ key: label, label, children }))} />;
  }

  if (nodeId === "supplier") {
    const riskFlags = stringList(output.risk_flags);
    const missingFields = stringList(output.missing_fields);
    return (
      <div className="agent-node-detail-body">
        <Descriptions className="agent-node-descriptions" bordered size="small" column={2} items={[
          { key: "status", label: "状态", children: statusTag(output.status) },
          { key: "risk", label: "供应风险", children: <Tag color={output.risk_level === "low" ? "success" : output.risk_level === "high" ? "error" : "warning"}>{formatValue(output.risk_level)}</Tag> },
          { key: "supplier", label: "供应商", children: formatValue(output.supplier_name) },
          { key: "moq", label: "MOQ", children: formatValue(output.moq) },
          { key: "lead", label: "交期", children: output.lead_time_days ? `${formatValue(output.lead_time_days)} 天` : "未提供" },
          { key: "maxLead", label: "最长交期", children: output.max_lead_time_days ? `${formatValue(output.max_lead_time_days)} 天` : "未设置" },
          { key: "resolution", label: "数据来源", children: output.resolution && asRecord(output.resolution).mode === "recommended" ? "系统推荐候选" : asRecord(output.resolution).mode === "matched" ? "已匹配证据" : "项目参数" },
        ]} />
        {riskFlags.length > 0 ? <div className="agent-node-detail-tags"><span>风险标记</span>{riskFlags.map((flag) => <Tag color="warning" key={flag}>{flag}</Tag>)}</div> : null}
        {missingFields.length > 0 ? <div className="agent-node-detail-tags"><span>缺失字段</span>{missingFields.map((field) => <Tag key={field}>{field}</Tag>)}</div> : null}
      </div>
    );
  }

  if (nodeId === "scoring") {
    const breakdown = asRecord(output.breakdown);
    const score = typeof output.score === "number" ? output.score : 0;
    return (
      <div className="agent-node-detail-body">
        <div className="agent-node-score-card">
          <div><span>综合机会分</span><strong>{typeof output.score === "number" ? output.score : "待计算"}</strong></div>
          <Progress percent={Math.max(0, Math.min(100, score))} showInfo={false} strokeColor="#195bff" />
          <span>{formatValue(output.reason)}</span>
        </div>
        <div className="agent-node-breakdown-list">
          {Object.entries(breakdown).map(([key, value]) => {
            const item = asRecord(value);
            const current = typeof item.score === "number" ? item.score : 0;
            const max = typeof item.max_score === "number" ? item.max_score : 100;
            return <div key={key}><span>{key}</span><Progress percent={max > 0 ? (current / max) * 100 : 0} format={() => `${current}/${max}`} /></div>;
          })}
        </div>
      </div>
    );
  }

  if (nodeId === "narrative") {
    const recommendations = stringList(output.recommendations);
    const risks = stringList(output.risks);
    return (
      <div className="agent-node-detail-body">
        <div className="agent-node-summary-box"><span>方案摘要</span><p>{formatValue(output.summary)}</p></div>
        {recommendations.length > 0 ? <div className="agent-node-detail-tags"><span>建议动作</span>{recommendations.map((item, index) => <Tag color="processing" key={`${index}-${item}`}>{item}</Tag>)}</div> : null}
        {risks.length > 0 ? <div className="agent-node-detail-tags"><span>风险提示</span>{risks.map((item, index) => <Tag color="warning" key={`${index}-${item}`}>{item}</Tag>)}</div> : null}
        <Descriptions className="agent-node-descriptions" bordered size="small" column={2} items={[
          { key: "provider", label: "提供方", children: formatValue(output.provider) },
          { key: "model", label: "模型", children: formatValue(output.model) },
        ]} />
      </div>
    );
  }

  const rows = Object.entries(output).filter(([key]) => !["hits", "evidence_ids", "recommendations", "risks"].includes(key));
  return rows.length > 0 ? (
    <Descriptions className="agent-node-descriptions" bordered size="small" column={1} items={rows.map(([key, value]) => ({ key, label: key, children: <pre>{formatValue(value)}</pre> }))} />
  ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无结构化产出" />;
}

/** 展示单个Agent节点的职责、输入、结构化产出、证据和失败上下文。 */
export function AgentNodeDetailDrawer({
  open,
  nodeId,
  status = "waiting",
  execution,
  output,
  onClose,
}: AgentNodeDetailDrawerProps) {
  const definition = nodeDefinitions[nodeId ?? ""] ?? { label: "执行节点", description: "暂无节点说明" };
  const outputRecord = asRecord(output);
  const hasOutput = Object.keys(outputRecord).length > 0;

  return (
    <Drawer
      title={definition.label}
      open={open}
      onClose={onClose}
      size="min(780px, 94vw)"
      className="agent-node-detail-drawer"
    >
      <div className="agent-node-detail-header">
        <div>
          <strong>{definition.label}</strong>
          <span>{definition.description}</span>
        </div>
        <Space wrap>
          <Tag color={definition.executionType === "llm_agent" || definition.executionType === "prompt_agent" ? "blue" : definition.executionType === "human_gate" ? "orange" : "cyan"}>
            {executionTypeLabels[definition.executionType]}
          </Tag>
          <Tag color={statusColors[status]}>{statusLabels[status]}</Tag>
          {execution?.reused ? <Tag color="processing">结果已复用</Tag> : null}
          {execution?.attempt ? <Tag>尝试 {execution.attempt}/{execution.max_attempts ?? "?"}</Tag> : null}
        </Space>
      </div>
      <Descriptions className="agent-node-descriptions" bordered size="small" column={1} items={[
        { key: "boundary", label: "业务边界", children: definition.boundary },
      ]} />
      {execution?.error ? <div className="agent-node-detail-error">{execution.error}</div> : null}
      {execution?.trace ? (
        <Descriptions className="agent-node-descriptions" bordered size="small" column={2} items={[
          { key: "provider", label: "提供方", children: formatValue(traceValue(execution.trace, "provider")) },
          { key: "model", label: "模型", children: formatValue(traceValue(execution.trace, "model")) },
          { key: "prompt", label: "Prompt 版本", children: formatValue(traceValue(execution.trace, "prompt_version")) },
          { key: "reason", label: "降级原因", children: formatValue(traceValue(execution.trace, "reason")) },
        ]} />
      ) : null}
      {hasOutput ? renderStructuredOutput(nodeId ?? "", outputRecord) : <Empty description={status === "waiting" ? "节点尚未执行" : "暂无节点产出"} />}
    </Drawer>
  );
}
