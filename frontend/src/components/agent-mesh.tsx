/**
 * 文件职责：使用 AntV X6 展示 LLM Agent、业务工具和审批门禁的实时执行状态。
 */

"use client";

import { useEffect, useRef } from "react";
import type { Graph } from "@antv/x6";

/** 定义`AgentNodeStatus`允许的状态或联合类型，避免跨模块使用任意字符串。 */
export type AgentNodeStatus = "completed" | "running" | "waiting" | "retrying" | "failed";

/** 定义`AgentNodeKind`节点执行类型，区分 LLM 推理、确定性工具和人工门禁。 */
type AgentNodeKind = "llm_agent" | "prompt_agent" | "deterministic_tool" | "human_gate";

/** 定义`AgentNodeExecution`数据契约，约束组件属性或接口响应字段。 */
export interface AgentNodeExecution {
  status: AgentNodeStatus;
  attempt?: number;
  max_attempts?: number;
  error?: string | null;
  reused?: boolean;
}

/** 定义`AgentMeshProps`数据契约，约束组件属性或接口响应字段。 */
export interface AgentMeshProps {
  statuses?: Record<string, AgentNodeStatus>;
  details?: Record<string, AgentNodeExecution>;
  onNodeSelect?: (nodeId: string) => void;
}

/** 定义`MeshNodeDefinition`数据契约，约束组件属性或接口响应字段。 */
interface MeshNodeDefinition {
  id: string;
  label: string;
  kind: AgentNodeKind;
  x: number;
  y: number;
  status: AgentNodeStatus;
}

/** 定义`nodes`模块常量或配置，供当前文件中的多个流程复用。 */
const nodes: MeshNodeDefinition[] = [
  { id: "requirement", label: "需求分析", kind: "llm_agent", x: 28, y: 190, status: "waiting" },
  { id: "researchPlan", label: "研究规划", kind: "llm_agent", x: 212, y: 190, status: "waiting" },
  { id: "market", label: "市场研究", kind: "deterministic_tool", x: 402, y: 68, status: "waiting" },
  { id: "competitor", label: "竞品分析", kind: "deterministic_tool", x: 402, y: 190, status: "waiting" },
  { id: "insight", label: "用户洞察", kind: "deterministic_tool", x: 402, y: 312, status: "waiting" },
  { id: "researchSynthesis", label: "证据治理", kind: "deterministic_tool", x: 592, y: 190, status: "waiting" },
  { id: "concept", label: "概念方案", kind: "llm_agent", x: 782, y: 190, status: "waiting" },
  { id: "supplier", label: "供应商评估", kind: "deterministic_tool", x: 972, y: 110, status: "waiting" },
  { id: "finance", label: "财务测算", kind: "deterministic_tool", x: 972, y: 270, status: "waiting" },
  { id: "scoring", label: "机会评分", kind: "deterministic_tool", x: 1162, y: 190, status: "waiting" },
  { id: "critic", label: "方案审查", kind: "llm_agent", x: 1352, y: 190, status: "waiting" },
  { id: "narrative", label: "规划建议", kind: "llm_agent", x: 1542, y: 190, status: "waiting" },
  { id: "approval", label: "线上审批", kind: "human_gate", x: 1732, y: 190, status: "waiting" },
];

/** 定义`edges`模块常量或配置，供当前文件中的多个流程复用。 */
const edges = [
  ["requirement", "researchPlan"],
  ["researchPlan", "market"],
  ["researchPlan", "competitor"],
  ["researchPlan", "insight"],
  ["market", "researchSynthesis"],
  ["competitor", "researchSynthesis"],
  ["insight", "researchSynthesis"],
  ["researchSynthesis", "concept"],
  ["concept", "supplier"],
  ["concept", "finance"],
  ["supplier", "scoring"],
  ["finance", "scoring"],
  ["scoring", "critic"],
  ["critic", "narrative"],
  ["narrative", "approval"],
];

/** 定义`nodeColors`展示映射，集中维护状态文案、颜色或选项。 */
const nodeColors: Record<AgentNodeStatus, { fill: string; stroke: string }> = {
  completed: { fill: "#eaf9f3", stroke: "#00a870" },
  running: { fill: "#eaf0ff", stroke: "#195bff" },
  waiting: { fill: "#f8fafc", stroke: "#a8b5c7" },
  retrying: { fill: "#fff7e6", stroke: "#d48806" },
  failed: { fill: "#fff1f0", stroke: "#cf1322" },
};

/** 定义`statusLabels`展示映射，集中维护状态文案、颜色或选项。 */
const statusLabels: Record<AgentNodeStatus, string> = {
  completed: "已完成",
  running: "执行中",
  waiting: "等待中",
  retrying: "重试中",
  failed: "失败",
};

/** 定义`kindLabels`节点类型文案，保持页面与架构图的分类口径一致。 */
const kindLabels: Record<AgentNodeKind, string> = {
  llm_agent: "LLM Agent",
  prompt_agent: "LLM Agent",
  deterministic_tool: "确定性工具/引擎",
  human_gate: "人工审批门禁",
};

/** 定义`nodeWidth`模块常量或配置，供当前文件中的多个流程复用。 */
const nodeWidth = 138;
/** 定义`nodeHeight`模块常量或配置，供当前文件中的多个流程复用。 */
const nodeHeight = 58;

/** 实现`getNodeStatus`辅助逻辑，集中处理页面展示或状态转换规则。 */
function getNodeStatus(
  node: MeshNodeDefinition,
  statuses: Record<string, AgentNodeStatus>,
): AgentNodeStatus {
  return statuses[node.id] ?? node.status;
}

/** 实现`getNodeSubtitle`辅助逻辑，集中处理页面展示或状态转换规则。 */
function getNodeSubtitle(
  node: MeshNodeDefinition,
  status: AgentNodeStatus,
  details: Record<string, AgentNodeExecution>,
): string {
  if (node.id === "approval") {
    if (status === "waiting") {
      return "等待人工决策";
    }
    if (status === "completed") {
      return "人工已处理";
    }
  }
  const detail = details[node.id];
  if (detail?.reused) {
    return "结果已复用";
  }
  if (detail?.attempt) {
    return `${statusLabels[status]} · ${detail.attempt}/${detail.max_attempts ?? "?"}`;
  }
  return statusLabels[status];
}

/** 实现`applyNodePresentation`辅助逻辑，集中处理页面展示或状态转换规则。 */
function applyNodePresentation(
  graph: Graph,
  statuses: Record<string, AgentNodeStatus>,
  details: Record<string, AgentNodeExecution>,
): void {
  nodes.forEach((node) => {
    const cell = graph.getCellById(node.id);
    if (!cell) {
      return;
    }
    const status = getNodeStatus(node, statuses);
    const color = nodeColors[status];
    const isHumanGate = node.id === "approval";
    const presentationColor = isHumanGate && status === "waiting" ? nodeColors.retrying : color;
    cell.attr({
      body: {
        fill: presentationColor.fill,
        stroke: presentationColor.stroke,
        strokeWidth: isHumanGate || status === "running" || status === "retrying" ? 2 : 1.2,
        ...(isHumanGate ? { strokeDasharray: "6 4" } : {}),
      },
      label: {
        text: isHumanGate ? "线上审批 · 人工" : node.label,
      },
      kindLabel: {
        text: kindLabels[node.kind],
        fill: isHumanGate ? presentationColor.stroke : "#5d6b7e",
      },
      statusLabel: {
        text: getNodeSubtitle(node, status, details),
        fill: presentationColor.stroke,
      },
    });
  });
}

/** 渲染可缩放的Agent Mesh画布，并同步节点状态、重试和点击详情。 */
export function AgentMesh({ statuses = {}, details = {}, onNodeSelect }: AgentMeshProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<Graph | null>(null);
  const latestPropsRef = useRef({ statuses, details });
  const onNodeSelectRef = useRef(onNodeSelect);
  const completedCount = nodes.filter((node) => getNodeStatus(node, statuses) === "completed").length;
  const runningCount = nodes.filter((node) => {
    const status = getNodeStatus(node, statuses);
    return status === "running" || status === "retrying";
  }).length;
  const failedCount = nodes.filter((node) => getNodeStatus(node, statuses) === "failed").length;

  useEffect(() => {
    let disposed = false;
    let resizeObserver: ResizeObserver | undefined;
    let lastWidth = 0;
    let lastHeight = 0;

    void import("@antv/x6").then(({ Graph }) => {
      if (disposed || !containerRef.current) {
        return;
      }

      const graph = new Graph({
        container: containerRef.current,
        autoResize: false,
        panning: true,
        mousewheel: { enabled: true, minScale: 0.72, maxScale: 1.25 },
        interacting: {
          nodeMovable: false,
          edgeMovable: false,
          magnetConnectable: false,
          arrowheadMovable: false,
          vertexMovable: false,
          vertexAddable: false,
          useEdgeTools: false,
        },
        background: { color: "transparent" },
      });
      graphRef.current = graph;

      nodes.forEach((node) => {
        graph.addNode({
          id: node.id,
          x: node.x,
          y: node.y,
          width: nodeWidth,
          height: nodeHeight,
          markup: [
            { tagName: "rect", selector: "body" },
            { tagName: "text", selector: "label" },
            { tagName: "text", selector: "kindLabel" },
            { tagName: "text", selector: "statusLabel" },
          ],
          attrs: {
            body: {
              fill: nodeColors[node.status].fill,
              stroke: nodeColors[node.status].stroke,
              strokeWidth: 1.2,
              rx: 13,
              ry: 13,
            },
            label: {
              text: node.label,
              fill: "#10223b",
              fontSize: 13,
              fontWeight: 650,
              refX: nodeWidth / 2,
              refY: 16,
              textAnchor: "middle",
              textVerticalAnchor: "middle",
            },
            kindLabel: {
              text: kindLabels[node.kind],
              fill: "#5d6b7e",
              fontSize: 9,
              fontWeight: 550,
              refX: nodeWidth / 2,
              refY: 33,
              textAnchor: "middle",
              textVerticalAnchor: "middle",
            },
            statusLabel: {
              text: statusLabels[node.status],
              fill: nodeColors[node.status].stroke,
              fontSize: 10,
              refX: nodeWidth / 2,
              refY: 50,
              textAnchor: "middle",
              textVerticalAnchor: "middle",
            },
          },
        });
      });

      edges.forEach(([source, target]) => {
        graph.addEdge({
          source,
          target,
          router: { name: "manhattan", args: { padding: 18 } },
          connector: { name: "rounded", args: { radius: 12 } },
          attrs: {
            line: {
              stroke: "#aab7c9",
              strokeWidth: 1.4,
              targetMarker: { name: "block", width: 8, height: 6 },
            },
          },
        });
      });

      graph.on("node:click", ({ node }) => {
        onNodeSelectRef.current?.(String(node.id));
      });

      const resizeGraph = () => {
        const container = containerRef.current;
        if (!container || disposed) {
          return;
        }
        const width = Math.max(1, container.clientWidth);
        const height = Math.max(1, container.clientHeight);
        if (lastWidth !== width || lastHeight !== height) {
          lastWidth = width;
          lastHeight = height;
          graph.resize(width, height);
        }
      };
      resizeObserver = new ResizeObserver(resizeGraph);
      resizeObserver.observe(containerRef.current);
      resizeGraph();
      applyNodePresentation(graph, latestPropsRef.current.statuses, latestPropsRef.current.details);
    });

    return () => {
      disposed = true;
      resizeObserver?.disconnect();
      graphRef.current?.dispose();
      graphRef.current = null;
    };
  }, []);

  useEffect(() => {
    latestPropsRef.current = { statuses, details };
    onNodeSelectRef.current = onNodeSelect;
    if (graphRef.current) {
      applyNodePresentation(graphRef.current, statuses, details);
    }
  }, [details, onNodeSelect, statuses]);

  const activeDetails = nodes
    .map((node) => ({ node, status: getNodeStatus(node, statuses), detail: details[node.id] }))
    .filter(({ status, detail }) => status === "retrying" || status === "failed" || detail?.reused);

  return (
    <div className="agent-mesh-panel">
      <div className="agent-mesh-header">
        <div>
          <strong>商品规划执行流程</strong>
          <span>节点状态实时同步；点击节点查看产出、证据与执行详情，可拖动画布查看完整链路</span>
        </div>
        <div className="agent-mesh-summary" aria-label="Agent 执行汇总">
          <span className="agent-mesh-summary-completed">已完成 {completedCount}</span>
          <span className="agent-mesh-summary-running">执行中 {runningCount}</span>
          {failedCount > 0 ? (
            <span className="agent-mesh-summary-failed">失败 {failedCount}</span>
          ) : null}
        </div>
      </div>
      <div className="agent-mesh-human-gate" role="note">
        <strong>人在环决策门</strong>
        <span>LLM Agent 只提供理解和建议，确定性工具负责计算与校验，审批人在线确认后才会进入正式选品。</span>
      </div>
      <div className="agent-mesh-legend" aria-label="执行节点类型图例">
        <span className="agent-mesh-legend-item agent-mesh-legend-prompt"><i />LLM Agent</span>
        <span className="agent-mesh-legend-item agent-mesh-legend-tool"><i />确定性工具/引擎</span>
        <span className="agent-mesh-legend-item agent-mesh-legend-human"><i />人工审批门禁</span>
        <span className="agent-mesh-legend-note">规划流程：13 个节点 · 5 个 LLM Agent · 7 个确定性工具/引擎 · 1 个人工门禁</span>
      </div>
      <div className="mesh-viewport">
        <div ref={containerRef} className="mesh-canvas" aria-label="Multi-Agent Mesh workflow" />
      </div>
      {activeDetails.length > 0 ? (
        <div className="agent-mesh-alerts">
          {activeDetails.map(({ node, status, detail }) => (
            <div className={`agent-mesh-alert agent-mesh-alert-${status}`} key={node.id}>
              <strong>{node.label}</strong>
              <span>
                {status === "failed"
                  ? detail?.error || "节点执行失败，可点击恢复"
                  : detail?.reused
                    ? "恢复执行时复用已完成结果"
                    : `正在进行第 ${detail?.attempt ?? 1}/${detail?.max_attempts ?? "?"} 次尝试`}
              </span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
