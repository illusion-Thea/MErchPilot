/**
 * 文件职责：展示规划结论、评分、财务、供应链、证据和报告操作。
 */

"use client";

import { useState } from "react";

import { Alert, Button, Descriptions, Divider, Empty, Input, List, Progress, Select, Space, Steps, Table, Tag, Upload } from "antd";
import type { TableProps } from "antd";

import type { PlanningRunEvidence, ValidationGateStatus } from "@/lib/http/planning";

/** 定义`PlanningResultViewProps`数据契约，约束组件属性或接口响应字段。 */
interface PlanningResultViewProps {
  snapshot?: Record<string, unknown>;
  evidence: PlanningRunEvidence[];
  evidenceLoading?: boolean;
  evidenceTotal?: number;
  evidencePage?: number;
  evidencePageSize?: number;
  evidenceUnavailableTotal?: number;
  onEvidencePageChange?: (page: number) => void;
  projectName?: string;
  category?: string;
  targetMarket?: string;
  approvalStatus?: string;
  selectedProductStatus?: string;
  selectedProductValidationStatus?: string;
  initiativeStatus?: string;
  onNextAction?: (action: PlanningResultNextAction) => void;
  onValidationPlanUpdate?: (
    candidateId: string,
    gateId: string,
    status: ValidationGateStatus,
    note: string,
  ) => Promise<void>;
  validationUpdating?: boolean;
  onValidationMaterialUpload?: (
    candidateId: string,
    gateId: string,
    file: File,
    note: string,
  ) => Promise<void>;
  onValidationMaterialDelete?: (materialId: string) => Promise<void>;
  onValidationMaterialDownload?: (materialId: string, filename: string) => Promise<void>;
  validationMaterialUpdating?: boolean;
}

/** 定义`PlanningResultNextAction`允许的状态或联合类型，避免跨模块使用任意字符串。 */
export type PlanningResultNextAction =
  | "approval"
  | "selected-products"
  | "initiative-create"
  | "initiative";

/** 定义`qualityPresentation`展示映射，集中维护状态文案、颜色或选项。 */
const qualityPresentation: Record<
  Exclude<PlanningRunEvidence["quality_status"], null>,
  { color: string; label: string }
> = {
  verified: { color: "success", label: "质量通过" },
  warning: { color: "warning", label: "需要注意" },
  blocked: { color: "error", label: "不可用" },
};

/** 定义`topicKeys`模块常量或配置，供当前文件中的多个流程复用。 */
const topicKeys = [
  { key: "market", label: "市场研究" },
  { key: "competitor", label: "竞品研究" },
  { key: "user_insight", label: "用户洞察" },
];

/** 定义`scoreKeys`模块常量或配置，供当前文件中的多个流程复用。 */
const scoreKeys = [
  { key: "evidence", label: "证据" },
  { key: "finance", label: "财务" },
  { key: "supplier", label: "供应" },
  { key: "completeness", label: "完整度" },
];

/** 实现`asRecord`辅助逻辑，集中处理页面展示或状态转换规则。 */
function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};
}

/** 实现`numberValue`辅助逻辑，集中处理页面展示或状态转换规则。 */
function numberValue(value: unknown): number | undefined {
  return typeof value === "number" ? value : undefined;
}

/** 实现`textValue`辅助逻辑，集中处理页面展示或状态转换规则。 */
function textValue(value: unknown, fallback = "-"): string {
  return typeof value === "string" && value ? value : fallback;
}

/** 实现`stringList`辅助逻辑，集中处理页面展示或状态转换规则。 */
function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && Boolean(item.trim()))
    : [];
}

/** 把formatPercent相关原始值格式化为页面可读文本。 */
function formatPercent(value: unknown): string {
  return typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "待计算";
}

/** 把formatMoney相关原始值格式化为页面可读文本。 */
function formatMoney(value: unknown): string {
  return typeof value === "number" ? `¥${value.toFixed(2)}` : "待计算";
}

/** 把formatBytes相关原始值格式化为页面可读文本。 */
function formatBytes(value: unknown): string {
  if (typeof value !== "number" || value < 0) {
    return "大小未知";
  }
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

/** 实现`candidateScoreStatus`辅助逻辑，集中处理页面展示或状态转换规则。 */
function candidateScoreStatus(value: unknown): string {
  if (value === "ready") {
    return "数据充分";
  }
  if (value === "partial") {
    return "需补充数据";
  }
  return "待评估";
}

/** 实现`validationStatusLabel`辅助逻辑，集中处理页面展示或状态转换规则。 */
function validationStatusLabel(value: unknown): string {
  if (value === "ready") {
    return "可进入小批量验证";
  }
  if (value === "partial") {
    return "部分具备，需补齐验证";
  }
  if (value === "blocked") {
    return "存在阻塞项";
  }
  return "待验证";
}

/** 实现`validationGateLabel`辅助逻辑，集中处理页面展示或状态转换规则。 */
function validationGateLabel(value: unknown): string {
  if (value === "ready") {
    return "已通过";
  }
  if (value === "blocked") {
    return "阻塞";
  }
  return "待完成";
}

/** 实现`validationGateColor`辅助逻辑，集中处理页面展示或状态转换规则。 */
function validationGateColor(value: unknown): string {
  if (value === "ready") {
    return "success";
  }
  if (value === "blocked") {
    return "error";
  }
  return "warning";
}

/** 实现`validationGateStatus`辅助逻辑，集中处理页面展示或状态转换规则。 */
function validationGateStatus(value: unknown): ValidationGateStatus {
  if (value === "ready" || value === "blocked") {
    return value;
  }
  return "pending";
}

/** 实现`statusTag`辅助逻辑，集中处理页面展示或状态转换规则。 */
function statusTag(status: unknown): React.ReactNode {
  if (status === "ready") {
    return <Tag color="success">正常</Tag>;
  }
  if (status === "partial") {
    return <Tag color="warning">部分降级</Tag>;
  }
  if (status === "degraded") {
    return <Tag color="error">降级</Tag>;
  }
  return <Tag>未运行</Tag>;
}

/** 展示规划结论、证据、财务、供应商、评分和报告操作。 */
export function PlanningResultView({
  snapshot,
  evidence,
  evidenceLoading = false,
  evidenceTotal,
  evidencePage = 1,
  evidencePageSize = 8,
  evidenceUnavailableTotal,
  onEvidencePageChange,
  projectName,
  category,
  targetMarket,
  approvalStatus,
  selectedProductStatus,
  selectedProductValidationStatus,
  initiativeStatus,
  onNextAction,
  onValidationPlanUpdate,
  validationUpdating = false,
  onValidationMaterialUpload,
  onValidationMaterialDelete,
  onValidationMaterialDownload,
  validationMaterialUpdating = false,
}: PlanningResultViewProps) {
  const [validationNotes, setValidationNotes] = useState<Record<string, string>>({});
  const [validationCandidateId, setValidationCandidateId] = useState<string>();
  const [comparisonCandidateIds, setComparisonCandidateIds] = useState<string[]>([]);
  const outputs = asRecord(snapshot?.outputs);
  const researchPlan = asRecord(outputs.research_plan);
  const researchSynthesis = asRecord(outputs.research_synthesis);
  const concept = asRecord(outputs.concept);
  const critic = asRecord(outputs.critic);
  const scorecard = asRecord(outputs.scorecard);
  const baselineFinance = asRecord(outputs.finance);
  const selectedCandidateFinance = asRecord(outputs.selected_candidate_finance);
  const finance = Object.keys(selectedCandidateFinance).length > 0
    ? selectedCandidateFinance
    : baselineFinance;
  const supplier = asRecord(outputs.supplier);
  const narrative = asRecord(outputs.narrative);
  const planningMetrics = asRecord(snapshot?.metrics);
  const metricsCoverage = asRecord(planningMetrics.coverage);
  const supplierResolution = asRecord(supplier.resolution);
  const candidateConcepts = Array.isArray(concept.candidates)
    ? concept.candidates.map(asRecord)
    : [];
  const selectedCandidateId = typeof concept.selected_candidate_id === "string"
    ? concept.selected_candidate_id
    : undefined;
  const recommendedCandidateId = typeof concept.recommended_candidate_id === "string"
    ? concept.recommended_candidate_id
    : undefined;
  const activeCandidate = candidateConcepts.find((candidate) => candidate.id === validationCandidateId)
    ?? candidateConcepts.find((candidate) => candidate.id === selectedCandidateId)
    ?? candidateConcepts.find((candidate) => candidate.id === recommendedCandidateId)
    ?? candidateConcepts[0];
  const activeValidationPlan = asRecord(activeCandidate?.validation_plan);
  const activeValidationGates = Array.isArray(activeValidationPlan.gates)
    ? activeValidationPlan.gates.map(asRecord)
    : [];
  const activeValidationActions = stringList(activeValidationPlan.next_actions);
  const activeCandidateId = typeof activeCandidate?.id === "string" ? activeCandidate.id : "";
  const candidateIds = candidateConcepts
    .map((candidate) => (typeof candidate.id === "string" ? candidate.id : undefined))
    .filter((candidateId): candidateId is string => Boolean(candidateId));
  const defaultComparisonCandidateIds = candidateIds.slice(0, Math.min(3, candidateIds.length));
  const visibleComparisonCandidateIds = (comparisonCandidateIds.length > 0
    ? comparisonCandidateIds
    : defaultComparisonCandidateIds
  ).filter((candidateId) => candidateIds.includes(candidateId));
  const comparisonCandidates = candidateConcepts.filter(
    (candidate) => typeof candidate.id === "string" && visibleComparisonCandidateIds.includes(candidate.id),
  );
  const comparisonMetrics = comparisonCandidates.map((candidate) => {
    const candidateId = candidate.id as string;
    const priceReference = asRecord(candidate.price_reference);
    const financialScenario = asRecord(candidate.financial_scenario);
    const candidateScorecard = asRecord(candidate.scorecard);
    const validationPlan = asRecord(candidate.validation_plan);
    const candidateRisks = stringList(candidate.risks);
    const evidenceIds = stringList(candidate.evidence_ids);
    const candidateIndex = candidateConcepts.findIndex((item) => item.id === candidateId);
    const isRecommended = candidateId === recommendedCandidateId || (!recommendedCandidateId && candidateIndex === 0);
    return {
      id: candidateId,
      role: candidateId === selectedCandidateId ? "已被审批选中" : isRecommended ? "系统优先验证" : "备选方案",
      score: numberValue(candidateScorecard.total_score)?.toFixed(0) ?? "待计算",
      price: formatMoney(financialScenario.selling_price ?? priceReference.suggested_price),
      margin: formatPercent(financialScenario.margin_rate),
      profit: formatMoney(financialScenario.estimated_profit),
      evidence: `${evidenceIds.length} 条`,
      validation: `${numberValue(validationPlan.completed_gates) ?? 0}/${numberValue(validationPlan.total_gates) ?? 0}`,
      risks: `${candidateRisks.length} 项`,
      recommendation: textValue(candidate.recommendation, "待补充"),
    };
  });
  const comparisonRows: Array<Record<string, string>> = [
    { key: "role", label: "当前角色", ...Object.fromEntries(comparisonMetrics.map((metric) => [metric.id, metric.role])) },
    { key: "score", label: "方案分", ...Object.fromEntries(comparisonMetrics.map((metric) => [metric.id, metric.score])) },
    { key: "price", label: "建议售价", ...Object.fromEntries(comparisonMetrics.map((metric) => [metric.id, metric.price])) },
    { key: "margin", label: "参考毛利率", ...Object.fromEntries(comparisonMetrics.map((metric) => [metric.id, metric.margin])) },
    { key: "profit", label: "预计利润", ...Object.fromEntries(comparisonMetrics.map((metric) => [metric.id, metric.profit])) },
    { key: "evidence", label: "证据数量", ...Object.fromEntries(comparisonMetrics.map((metric) => [metric.id, metric.evidence])) },
    { key: "validation", label: "验证完成度", ...Object.fromEntries(comparisonMetrics.map((metric) => [metric.id, metric.validation])) },
    { key: "risks", label: "风险数量", ...Object.fromEntries(comparisonMetrics.map((metric) => [metric.id, metric.risks])) },
    { key: "recommendation", label: "方案建议", ...Object.fromEntries(comparisonMetrics.map((metric) => [metric.id, metric.recommendation])) },
  ];
  const comparisonColumns: TableProps<Record<string, string>>["columns"] = [
    { title: "决策指标", dataIndex: "label", key: "label", fixed: "left", width: 140 },
    ...comparisonCandidates.map((candidate) => ({
      title: textValue(candidate.name, "未命名方案"),
      dataIndex: candidate.id as string,
      key: candidate.id as string,
      width: 190,
    })),
  ];

  const saveValidationGate = async (
    gate: Record<string, unknown>,
    status: ValidationGateStatus = validationGateStatus(gate.status),
  ) => {
    if (!onValidationPlanUpdate || !activeCandidateId || typeof gate.id !== "string") {
      return;
    }
    const noteKey = `${activeCandidateId}:${gate.id}`;
    await onValidationPlanUpdate(
      activeCandidateId,
      gate.id,
      status,
      validationNotes[noteKey] ?? (typeof gate.note === "string" ? gate.note : ""),
    );
  };
  const dataBackedFields = stringList(finance.data_backed_fields);
  const recommendations = stringList(narrative.recommendations);
  const risks = stringList(narrative.risks);
  const breakdown = asRecord(scorecard.breakdown);
  const score = numberValue(scorecard.score);
  const scorePercent = score === undefined ? 0 : Math.max(0, Math.min(100, score));
  const evidenceCount = numberValue(scorecard.evidence_count) ?? evidenceTotal ?? evidence.length;
  const hasCandidates = candidateConcepts.length > 0;
  const approvalCompleted = approvalStatus === "approved";
  const approvalBlocked = approvalStatus === "rejected" || approvalStatus === "revision_required";
  const selectionCancelled = selectedProductStatus === "cancelled";
  const selectionPaused = selectedProductStatus === "paused";
  const selectionCompleted = Boolean(selectedProductStatus) && !selectionCancelled;
  const validationCompleted =
    !selectionCancelled &&
    (selectedProductValidationStatus === "ready" ||
      selectedProductStatus === "ready" ||
      selectedProductStatus === "initiated" ||
      selectedProductStatus === "launched");
  const initiativeCancelled = initiativeStatus === "cancelled";
  const initiativePaused = initiativeStatus === "paused";
  const initiativeCompleted = Boolean(initiativeStatus) && !initiativeCancelled;
  const businessStages = [
    {
      title: "候选方案",
      description: hasCandidates ? `${candidateConcepts.length} 个候选方案` : "等待 Agent 输出",
    },
    {
      title: "线上审批",
      description: approvalCompleted
        ? "方案已通过"
        : approvalBlocked
          ? approvalStatus === "rejected" ? "方案已驳回" : "等待修订"
          : approvalStatus === "pending" ? "等待审批处理" : "尚未提交审批",
    },
    {
      title: "正式选品",
      description: selectionCancelled
        ? "选品已终止"
        : selectionPaused
          ? "选品已暂缓"
          : selectionCompleted ? "已进入正式选品池" : "审批通过后自动生成",
    },
    {
      title: "落地验证",
      description: selectionCancelled
        ? "选品已终止"
        : selectionPaused
          ? "等待恢复推进"
          : validationCompleted
            ? "验证已通过"
            : selectionCompleted ? "正在补齐验证" : "等待正式选品",
    },
    {
      title: "商品立项",
      description: initiativeCancelled
        ? "立项已取消"
        : initiativePaused
          ? "立项已暂停"
          : initiativeCompleted
            ? initiativeStatus === "launched" ? "已上市" : "已进入立项中心"
            : "验证通过后可发起",
    },
  ];
  const businessStageStates = [
    hasCandidates ? "finish" : "process",
    approvalBlocked ? "error" : approvalCompleted ? "finish" : hasCandidates ? "process" : "wait",
    selectionCancelled ? "error" : selectionPaused ? "process" : selectionCompleted ? "finish" : approvalCompleted ? "process" : "wait",
    selectionCancelled || initiativeCancelled
      ? "error"
      : selectionPaused || initiativePaused
        ? "process"
        : validationCompleted ? "finish" : selectionCompleted ? "process" : "wait",
    initiativeCancelled ? "error" : initiativePaused ? "process" : initiativeCompleted ? "finish" : validationCompleted ? "process" : "wait",
  ] as const;
  const activeBusinessStage = businessStageStates.findIndex(
    (stage) => stage === "process" || stage === "error",
  );
  const currentBusinessStage = activeBusinessStage === -1
    ? businessStageStates.length - 1
    : activeBusinessStage;
  const nextAction: { label: string; action: PlanningResultNextAction } = approvalBlocked
    ? { label: "查看审批记录", action: "approval" }
    : initiativeCancelled
      ? { label: "查看取消立项记录", action: "initiative" }
      : selectionCancelled
        ? { label: "查看终止选品记录", action: "selected-products" }
        : initiativeCompleted || selectedProductStatus === "initiated" || selectedProductStatus === "launched"
          ? { label: "查看商品立项", action: "initiative" }
          : validationCompleted
            ? { label: "去建立商品立项", action: "initiative-create" }
            : selectionPaused
              ? { label: "查看暂缓选品", action: "selected-products" }
              : selectionCompleted
                ? { label: "去补齐落地验证", action: "selected-products" }
                : approvalStatus !== "approved"
                  ? { label: "去线上审批", action: "approval" }
                  : { label: "查看正式选品", action: "selected-products" };

  const evidenceColumns: TableProps<PlanningRunEvidence>["columns"] = [
    {
      title: "业务主题",
      dataIndex: "topics",
      key: "topics",
      width: 140,
      render: (topics: string[]) => (
        <Space size={[4, 4]} wrap>
          {topics.map((topic) => <Tag key={topic}>{topic}</Tag>)}
        </Space>
      ),
    },
    {
      title: "证据内容",
      dataIndex: "content",
      key: "content",
      render: (content: string, record) => (
        <div className="planning-evidence-content">
          <strong>{record.source_id ?? record.evidence_id}</strong>
          <span>{content || "未提供证据摘要"}</span>
        </div>
      ),
    },
    {
      title: "来源追溯",
      key: "lineage",
      width: 210,
      render: (_, record) => (
        <div className="planning-evidence-lineage">
          <strong>{record.source_name ?? "未知来源"}</strong>
          <span>{record.source_row === null ? "历史快照" : `第 ${record.source_row} 行`}</span>
          {record.observed_at ? <span>{new Date(record.observed_at).toLocaleDateString("zh-CN")}</span> : null}
        </div>
      ),
    },
    {
      title: "质量 / 治理",
      key: "governance",
      width: 170,
      render: (_, record) => (
        <Space size={[4, 4]} wrap>
          {record.quality_status ? (
            <Tag color={qualityPresentation[record.quality_status].color}>
              {qualityPresentation[record.quality_status].label}
            </Tag>
          ) : null}
          {record.is_canonical ? <Tag color="green">主记录</Tag> : null}
          {!record.available ? <Tag color="default">历史快照</Tag> : null}
        </Space>
      ),
    },
    {
      title: "相关度",
      key: "score",
      width: 100,
      render: (_, record) => (
        <div className="planning-evidence-score">
          <strong>{record.retrieval_score?.toFixed(3) ?? "-"}</strong>
          {record.vector_score !== null ? <span>向量 {record.vector_score.toFixed(3)}</span> : null}
        </div>
      ),
    },
  ];

  if (!snapshot) {
    return <Empty description="当前运行还没有可展示的规划结果" />;
  }

  return (
    <div className="planning-result-view">
      <div className="planning-result-hero">
        <Progress
          type="circle"
          percent={scorePercent}
          size={116}
          format={() => (score === undefined ? "-" : score.toFixed(0))}
          status={score !== undefined && score < 60 ? "exception" : "normal"}
        />
        <div>
          <Space wrap>
            <Tag color="blue">{textValue(scorecard.status, "等待结论")}</Tag>
            <span className="muted-text">证据 {evidenceCount} 条</span>
          </Space>
          <h2>{textValue(concept.name, `${category ?? "商品"}候选方案`)}</h2>
          <p>{textValue(scorecard.reason, "系统已完成机会、财务和供应风险综合评估。")}</p>
        </div>
      </div>

      <div className="business-progress-panel">
        <div className="business-progress-heading">
          <div>
            <strong>业务推进进度</strong>
            <span>从 Agent 方案到商品上市的实际业务状态</span>
          </div>
          <Tag
            color={
              approvalBlocked || selectionCancelled || initiativeCancelled
                ? "error"
                : selectionPaused || initiativePaused
                  ? "warning"
                  : initiativeStatus === "launched" ? "success" : "processing"
            }
          >
            {approvalBlocked
              ? "当前需修订"
              : selectionCancelled || initiativeCancelled
                ? "流程已终止"
                : selectionPaused || initiativePaused
                  ? "当前已暂停"
                  : initiativeStatus === "launched" ? "已上市" : "持续推进中"}
          </Tag>
        </div>
        <Steps
          current={currentBusinessStage}
          status={
            approvalBlocked || selectionCancelled || initiativeCancelled
              ? "error"
              : "process"
          }
          responsive
          items={businessStages.map((stage, index) => ({
            ...stage,
            status: businessStageStates[index],
          }))}
        />
        <div className="business-progress-note">
          {approvalBlocked
            ? "当前方案需要根据审批意见修订后重新运行 Agent。"
            : initiativeCancelled
              ? "商品立项已取消，当前结果仅保留历史追溯，不能继续推进。"
              : selectionCancelled
                ? "正式选品已终止，当前结果仅保留历史追溯，不能继续推进。"
                : initiativePaused
                  ? "商品立项已暂停，恢复后才能继续推进里程碑。"
                  : selectionPaused
                    ? "正式选品已暂缓，恢复后才能继续补齐落地验证。"
                    : initiativeCompleted
              ? "该候选方案已经进入商品立项流程，可继续推进里程碑和上市评审。"
              : validationCompleted
                ? "验证已通过，可以在商品立项中心发起立项。"
                : selectionCompleted
                  ? "正式选品已生成，请继续补齐落地验证清单。"
                  : approvalCompleted
                    ? "审批已通过，系统正在生成正式选品记录。"
                    : "请按当前阶段处理方案，系统会自动同步后续状态。"}
          {onNextAction ? (
            <Button
              size="small"
              type={approvalBlocked || selectionCancelled || initiativeCancelled ? "default" : "primary"}
              onClick={() => onNextAction(nextAction.action)}
            >
              {nextAction.label}
            </Button>
          ) : null}
        </div>
      </div>

      <Descriptions bordered size="small" column={3}>
        <Descriptions.Item label="项目">{projectName ?? "-"}</Descriptions.Item>
        <Descriptions.Item label="品类">{category ?? "-"}</Descriptions.Item>
        <Descriptions.Item label="目标市场">{targetMarket ?? textValue(concept.target_market)}</Descriptions.Item>
        <Descriptions.Item label="计划售价">{formatMoney(finance.selling_price)}</Descriptions.Item>
        <Descriptions.Item label="预计毛利率">{formatPercent(finance.margin_rate)}</Descriptions.Item>
        <Descriptions.Item label="财务口径">
          {finance.scenario_type === "candidate" ? `已选方案：${textValue(finance.candidate_name)}` : "项目综合测算"}
        </Descriptions.Item>
        <Descriptions.Item label="单位贡献毛利">
          {formatMoney(finance.contribution_margin_per_unit)}
        </Descriptions.Item>
        <Descriptions.Item label="盈亏平衡销量">
          {typeof finance.break_even_units === "number" ? `${finance.break_even_units} 件` : "待计算"}
        </Descriptions.Item>
        <Descriptions.Item label="供应商">{textValue(supplier.supplier_name, "待补充")}</Descriptions.Item>
        <Descriptions.Item label="供应风险">{textValue(supplier.risk_level, "待评估")}</Descriptions.Item>
        <Descriptions.Item label="结构化数据">
          {typeof planningMetrics.record_count === "number"
            ? `${planningMetrics.record_count.toLocaleString("zh-CN")} 条`
            : "未命中"}
        </Descriptions.Item>
        <Descriptions.Item label="供应商来源">
          {supplierResolution.mode === "recommended"
            ? "系统推荐候选"
            : supplierResolution.mode === "matched"
              ? "已匹配证据"
              : "项目参数"}
        </Descriptions.Item>
      </Descriptions>

      {planningMetrics.record_count ? (
        <div className="planning-data-basis">
          <span>本次决策数据覆盖</span>
          <Space size={[6, 6]} wrap>
            <Tag color="blue">竞品 {String(metricsCoverage.competitor ?? 0)}</Tag>
            <Tag color="processing">评论 {String(metricsCoverage.user_reviews ?? 0)}</Tag>
            <Tag>趋势 {String(metricsCoverage.market_trend ?? 0)}</Tag>
            <Tag color="success">供应商 {String(metricsCoverage.supplier ?? 0)}</Tag>
            <Tag color="warning">成本 {String(metricsCoverage.cost ?? 0)}</Tag>
          </Space>
          {dataBackedFields.length > 0 ? (
            <span>财务参数来自数据：{dataBackedFields.join("、")}</span>
          ) : null}
        </div>
      ) : null}

      {candidateConcepts.length > 0 ? (
        <>
          <Divider titlePlacement="start">候选商品方案</Divider>
          <div className="concept-candidate-grid">
            {candidateConcepts.map((candidate, index) => {
              const priceReference = asRecord(candidate.price_reference);
              const financialScenario = asRecord(candidate.financial_scenario);
              const candidateScorecard = asRecord(candidate.scorecard);
              const candidateBreakdown = asRecord(candidateScorecard.breakdown);
              const commercialBreakdown = asRecord(candidateBreakdown.commercial);
              const evidenceFeatures = stringList(candidate.evidence_features);
              const painPoints = stringList(candidate.pain_points_addressed);
              const featureHypotheses = stringList(candidate.feature_hypotheses);
              const candidateRisks = stringList(candidate.risks);
              const evidenceIds = stringList(candidate.evidence_ids);
              const validationPlan = asRecord(candidate.validation_plan);
              const isSelected = candidate.id === selectedCandidateId;
              const isRecommended = candidate.id === recommendedCandidateId || (!recommendedCandidateId && index === 0);
              const isValidationActive = candidate.id === activeCandidateId;
              return (
                <div
                  className={`concept-candidate-card ${isRecommended ? "concept-candidate-card-primary" : ""} ${isSelected ? "concept-candidate-card-selected" : ""} ${isValidationActive ? "concept-candidate-card-validation-active" : ""}`}
                  key={textValue(candidate.id, `candidate-${index}`)}
                >
                  <div className="concept-candidate-header">
                    <div>
                      <span>候选 {index + 1}</span>
                      <strong>{textValue(candidate.name)}</strong>
                    </div>
                    <Tag color={isSelected ? "success" : isRecommended ? "blue" : "default"}>
                      {isSelected ? "已选方案" : isRecommended ? "优先验证" : textValue(candidate.confidence, "待评估")}
                    </Tag>
                  </div>
                  <p>{textValue(candidate.positioning)}</p>
                  <div className="concept-candidate-metrics">
                    <span>方案分 <strong>{numberValue(candidateScorecard.total_score) ?? "待计算"}</strong></span>
                    <span>建议售价 <strong>{formatMoney(financialScenario.selling_price ?? priceReference.suggested_price)}</strong></span>
                    <span>参考毛利率 <strong>{formatPercent(financialScenario.margin_rate)}</strong></span>
                    <span>预计利润 <strong>{formatMoney(financialScenario.estimated_profit)}</strong></span>
                  </div>
                  <div className="concept-candidate-validation-summary">
                    <span>
                      落地验证 <strong>{numberValue(validationPlan.completed_gates) ?? 0}/{numberValue(validationPlan.total_gates) ?? 0}</strong>
                    </span>
                    <Tag color={validationGateColor(validationPlan.status)}>
                      {textValue(validationPlan.status_label, validationStatusLabel(validationPlan.status))}
                    </Tag>
                  </div>
                  {typeof candidateScorecard.status === "string" ? (
                    <small>
                      {textValue(candidate.recommendation, "备选验证")} · {candidateScoreStatus(candidateScorecard.status)} · 成本参考 {formatMoney(candidate.unit_cost_reference)} · 证据 {evidenceIds.length} 条 · {textValue(commercialBreakdown.reason)}
                    </small>
                  ) : null}
                  {evidenceFeatures.length > 0 ? (
                    <div className="concept-candidate-section">
                      <span>证据特征</span>
                      <Space size={[4, 4]} wrap>{evidenceFeatures.map((item) => <Tag key={item}>{item}</Tag>)}</Space>
                    </div>
                  ) : null}
                  {painPoints.length > 0 ? (
                    <div className="concept-candidate-section">
                      <span>待解决痛点</span>
                      <Space size={[4, 4]} wrap>{painPoints.map((item) => <Tag color="warning" key={item}>{item}</Tag>)}</Space>
                    </div>
                  ) : null}
                  <div className="concept-candidate-section">
                    <span>功能假设</span>
                    <Space size={[4, 4]} wrap>{featureHypotheses.map((item) => <Tag color="processing" key={item}>{item}</Tag>)}</Space>
                  </div>
                  <small>{textValue(candidate.differentiation_hypothesis)}</small>
                  {candidateRisks.length > 0 ? (
                    <div className="concept-candidate-risk">验证风险：{candidateRisks.join("；")}</div>
                  ) : null}
                  {typeof candidate.id === "string" ? (
                    <Button
                      size="small"
                      type={isValidationActive ? "primary" : "default"}
                      onClick={() => setValidationCandidateId(candidate.id as string)}
                    >
                      {isValidationActive ? "当前验证方案" : "查看验证清单"}
                    </Button>
                  ) : null}
                </div>
              );
            })}
          </div>
          {candidateConcepts.length > 1 ? (
            <div className="candidate-comparison-panel">
              <div className="candidate-comparison-heading">
                <div>
                  <strong>候选商品对比</strong>
                  <span>横向比较关键指标后，在“线上审批”中确定正式选品</span>
                </div>
                <Select<string[]>
                  mode="multiple"
                  value={visibleComparisonCandidateIds}
                  maxTagCount="responsive"
                  placeholder="选择要比较的方案"
                  options={candidateConcepts
                    .filter((candidate) => typeof candidate.id === "string")
                    .map((candidate, index) => ({
                      value: candidate.id as string,
                      label: `${index + 1}. ${textValue(candidate.name, "未命名方案")}`,
                    }))}
                  onChange={setComparisonCandidateIds}
                  style={{ minWidth: 300, maxWidth: "100%" }}
                />
              </div>
              <Table<Record<string, string>>
                rowKey="key"
                size="small"
                pagination={false}
                columns={comparisonColumns}
                dataSource={comparisonRows}
                scroll={{ x: 140 + comparisonCandidates.length * 190 }}
              />
              <Alert
                type="info"
                showIcon
                message={selectedCandidateId
                  ? `当前审批选中的方案：${textValue(candidateConcepts.find((candidate) => candidate.id === selectedCandidateId)?.name, "未命名方案")}`
                  : `系统建议优先验证：${textValue(candidateConcepts.find((candidate) => candidate.id === (recommendedCandidateId ?? candidateIds[0]))?.name, "未命名方案")}`}
                description="此处仅用于方案比较和验证准备，不会直接创建正式选品；正式选品必须在审批通过后由系统自动生成。"
              />
            </div>
          ) : null}
          {activeCandidate && Object.keys(activeValidationPlan).length > 0 ? (
            <div className="concept-validation-panel">
              <div className="concept-validation-header">
                <div>
                  <span>当前方案</span>
                  <Select
                    size="small"
                    value={activeCandidateId || undefined}
                    onChange={setValidationCandidateId}
                    options={candidateConcepts
                      .filter((candidate) => typeof candidate.id === "string")
                      .map((candidate, index) => {
                        const candidatePlan = asRecord(candidate.validation_plan);
                        const completedGates = numberValue(candidatePlan.completed_gates) ?? 0;
                        const totalGates = numberValue(candidatePlan.total_gates) ?? 0;
                        return {
                          value: candidate.id as string,
                          label: `${index + 1}. ${textValue(candidate.name, "未命名方案")} · ${completedGates}/${totalGates}`,
                        };
                      })}
                    style={{ minWidth: 250 }}
                  />
                </div>
                <Tag color={validationGateColor(activeValidationPlan.status)}>
                  {textValue(activeValidationPlan.status_label, validationStatusLabel(activeValidationPlan.status))}
                </Tag>
              </div>
              <div className="concept-validation-progress">
                <span>验证完成度</span>
                <Progress
                  percent={numberValue(activeValidationPlan.completion_rate) ?? 0}
                  size="small"
                  status={activeValidationPlan.status === "blocked" ? "exception" : "normal"}
                />
              </div>
              <div className="concept-validation-gates">
                {activeValidationGates.map((gate, index) => {
                  const gateId = typeof gate.id === "string" ? gate.id : `gate-${index}`;
                  const noteKey = `${activeCandidateId}:${gateId}`;
                  const gateStatus = validationGateStatus(gate.status);
                  return (
                    <div className="concept-validation-gate-row" key={gateId}>
                      <div className="concept-validation-gate-heading">
                        <Space size={6} wrap>
                          <Tag color={validationGateColor(gateStatus)}>
                            {textValue(gate.label)} · {validationGateLabel(gateStatus)}
                          </Tag>
                          <span>{textValue(gate.owner, "责任人待指定")}</span>
                        </Space>
                        <small>{textValue(gate.criteria)}</small>
                      </div>
                      {onValidationPlanUpdate ? (
                        <Space className="concept-validation-gate-controls" size={6} wrap>
                          <Select<ValidationGateStatus>
                            size="small"
                            value={gateStatus}
                            disabled={validationUpdating}
                            options={[
                              { value: "ready", label: "已通过" },
                              { value: "pending", label: "待完成" },
                              { value: "blocked", label: "阻塞" },
                            ]}
                            onChange={(value) => void saveValidationGate(gate, value)}
                          />
                          <Input
                            size="small"
                            className="concept-validation-note"
                            placeholder="记录验证备注"
                            value={validationNotes[noteKey] ?? (typeof gate.note === "string" ? gate.note : "")}
                            disabled={validationUpdating}
                            onChange={(event) => setValidationNotes((current) => ({
                              ...current,
                              [noteKey]: event.target.value,
                            }))}
                          />
                          <Button
                            size="small"
                            loading={validationUpdating}
                            onClick={() => void saveValidationGate(gate)}
                          >
                            保存
                          </Button>
                          {onValidationMaterialUpload ? (
                            <Upload
                              showUploadList={false}
                              accept=".pdf,.doc,.docx,.xls,.xlsx,.csv,.png,.jpg,.jpeg,.txt,.zip"
                              beforeUpload={(file) => {
                                void onValidationMaterialUpload(
                                  activeCandidateId,
                                  gateId,
                                  file as File,
                                  validationNotes[noteKey] ?? (typeof gate.note === "string" ? gate.note : ""),
                                );
                                return false;
                              }}
                            >
                              <Button size="small" loading={validationMaterialUpdating}>
                                上传材料
                              </Button>
                            </Upload>
                          ) : null}
                        </Space>
                      ) : null}
                      {Array.isArray(gate.materials) && gate.materials.length > 0 ? (
                        <div className="concept-validation-materials">
                          {gate.materials.map((materialValue, materialIndex) => {
                            const material = asRecord(materialValue);
                            const materialId = typeof material.id === "string" ? material.id : `material-${materialIndex}`;
                            const filename = textValue(material.filename, "验证材料");
                            const inherited = typeof material.source_run_id === "string";
                            const unavailable = material.source_missing === true || !material.storage_key;
                            return (
                              <div className="concept-validation-material" key={materialId}>
                                <div>
                                  <span>{filename} · {formatBytes(material.size)}</span>
                                  <Space size={4} wrap>
                                    {inherited ? <Tag color="blue">继承材料</Tag> : null}
                                    {unavailable ? <Tag color="error">源文件不可用</Tag> : null}
                                    {typeof material.note === "string" && material.note ? (
                                      <small>{material.note}</small>
                                    ) : null}
                                  </Space>
                                </div>
                                <Space size={4}>
                                  {onValidationMaterialDownload && !unavailable ? (
                                    <Button
                                      type="link"
                                      size="small"
                                      loading={validationMaterialUpdating}
                                      onClick={() => void onValidationMaterialDownload(materialId, filename)}
                                    >
                                      下载
                                    </Button>
                                  ) : null}
                                  {onValidationMaterialDelete ? (
                                    <Button
                                      type="link"
                                      danger
                                      size="small"
                                      loading={validationMaterialUpdating}
                                      onClick={() => void onValidationMaterialDelete(materialId)}
                                    >
                                      删除
                                    </Button>
                                  ) : null}
                                </Space>
                              </div>
                            );
                          })}
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
              {activeValidationActions.length > 0 ? (
                <List
                  className="concept-validation-actions"
                  size="small"
                  header="下一步动作"
                  bordered
                  dataSource={activeValidationActions}
                  renderItem={(item) => <List.Item>{item}</List.Item>}
                />
              ) : null}
            </div>
          ) : null}
        </>
      ) : null}

      <Divider titlePlacement="start">评分拆解</Divider>
      <div className="planning-score-grid">
        {scoreKeys.map(({ key, label }) => {
          const part = asRecord(breakdown[key]);
          const partScore = numberValue(part.score) ?? 0;
          const maxScore = numberValue(part.max_score) ?? 0;
          const percent = maxScore > 0 ? Math.round((partScore / maxScore) * 100) : 0;
          return (
            <div key={key}>
              <span>{label}</span>
              <strong>{maxScore > 0 ? `${partScore} / ${maxScore}` : "待计算"}</strong>
              <Progress percent={percent} showInfo={false} />
            </div>
          );
        })}
      </div>

      <Divider titlePlacement="start">规划建议</Divider>
      <Alert
        type={narrative.status === "degraded" ? "warning" : "success"}
        showIcon
        message={
          narrative.status === "degraded"
            ? "当前使用本地规则生成建议"
            : "已使用规划模型生成建议"
        }
        description={textValue(narrative.summary, "当前运行尚未生成规划摘要。")}
      />
      {recommendations.length > 0 ? (
        <List
          size="small"
          header="建议动作"
          bordered
          dataSource={recommendations}
          renderItem={(item) => <List.Item>{item}</List.Item>}
        />
      ) : null}
      {risks.length > 0 ? (
        <List
          size="small"
          header="风险提示"
          bordered
          dataSource={risks}
          renderItem={(item) => <List.Item>{item}</List.Item>}
        />
      ) : null}

      <Divider titlePlacement="start">研究 Agent 状态</Divider>
      <Alert
        type={researchSynthesis.status === "ready" ? "success" : "warning"}
        showIcon
        message={`研究策略：${textValue(researchPlan.generation && asRecord(researchPlan.generation).status, "确定性降级")}`}
        description={textValue(researchSynthesis.summary, "研究治理结果尚未生成。")}
      />
      <div className="planning-research-grid">
        {topicKeys.map(({ key, label }) => {
          const result = asRecord(outputs[key]);
          const hits = Array.isArray(result.hits) ? result.hits : [];
          const governance = asRecord(result.governance);
          const suppressed = Array.isArray(governance.suppressed_evidence_ids)
            ? governance.suppressed_evidence_ids.length
            : 0;
          return (
            <div key={key}>
              <Space wrap>
                <strong>{label}</strong>
                {statusTag(result.status)}
              </Space>
              <span>返回 {hits.length} 条证据{suppressed ? `，治理过滤 ${suppressed} 条` : ""}</span>
              {typeof result.reason === "string" && result.reason ? <p>{result.reason}</p> : null}
            </div>
          );
        })}
      </div>
      {Object.keys(researchSynthesis).length > 0 ? (
        <div className="planning-research-governance">
          <Space wrap>
            <Tag color={researchSynthesis.status === "ready" ? "success" : "warning"}>
              总体状态：{textValue(researchSynthesis.status, "待评估")}
            </Tag>
            <Tag>冲突 {numberValue(researchSynthesis.conflict_count) ?? 0} 条</Tag>
            <Tag>补充动作 {Array.isArray(researchSynthesis.follow_up_actions) ? researchSynthesis.follow_up_actions.length : 0} 条</Tag>
          </Space>
          {Array.isArray(researchSynthesis.conflicts) && researchSynthesis.conflicts.length > 0 ? (
            <List
              size="small"
              header="证据冲突"
              bordered
              dataSource={researchSynthesis.conflicts as unknown[]}
              renderItem={(item) => {
                const conflict = asRecord(item);
                return (
                  <List.Item>
                    {textValue(conflict.reason, `${textValue(conflict.entity)} 的 ${textValue(conflict.field)} 存在口径差异`)}
                  </List.Item>
                );
              }}
            />
          ) : null}
          {Array.isArray(researchSynthesis.follow_up_actions) && researchSynthesis.follow_up_actions.length > 0 ? (
            <List
              size="small"
              header="补充研究动作"
              bordered
              dataSource={researchSynthesis.follow_up_actions as string[]}
              renderItem={(item) => <List.Item>{item}</List.Item>}
            />
          ) : null}
        </div>
      ) : null}

      <Divider titlePlacement="start">方案审查 Agent</Divider>
      <Alert
        type={critic.status === "blocked" ? "error" : critic.status === "ready" ? "success" : "warning"}
        showIcon
        message={`审查状态：${textValue(critic.status, "待生成")}`}
        description={textValue(critic.summary, "方案审查结果尚未生成。")}
      />
      {Array.isArray(critic.findings) && critic.findings.length > 0 ? (
        <List
          size="small"
          header="审查发现"
          bordered
          dataSource={critic.findings as unknown[]}
          renderItem={(item) => {
            const finding = asRecord(item);
            const severity = textValue(finding.severity, "warning");
            return (
              <List.Item>
                <Space wrap>
                  <Tag color={severity === "blocker" ? "error" : severity === "warning" ? "warning" : "processing"}>
                    {severity}
                  </Tag>
                  <span>{textValue(finding.issue, "未提供问题描述")}</span>
                  {typeof finding.recommendation === "string" ? <span>建议：{finding.recommendation}</span> : null}
                </Space>
              </List.Item>
            );
          }}
        />
      ) : null}

      <Divider titlePlacement="start">证据引用与来源追溯</Divider>
      {(evidenceUnavailableTotal ?? evidence.filter((item) => !item.available).length) > 0 ? (
        <Alert
          type="info"
          showIcon
          message={`${evidenceUnavailableTotal ?? evidence.filter((item) => !item.available).length} 条原始证据已撤回，页面继续使用运行时快照展示历史引用。`}
          className="planning-evidence-alert"
        />
      ) : null}
      <Table<PlanningRunEvidence>
        rowKey="evidence_id"
        columns={evidenceColumns}
        dataSource={evidence}
        loading={evidenceLoading}
        pagination={onEvidencePageChange ? {
          current: evidencePage,
          pageSize: evidencePageSize,
          total: evidenceTotal ?? evidence.length,
          showSizeChanger: false,
          hideOnSinglePage: true,
          showTotal: (total) => `共 ${total} 条引用证据`,
          onChange: onEvidencePageChange,
        } : { pageSize: evidencePageSize, hideOnSinglePage: true }}
        locale={{ emptyText: <Empty description="当前运行未检索到可用证据" /> }}
        scroll={{ x: 980 }}
      />
    </div>
  );
}
