/**
 * 文件职责：持久化当前 Agent 运行、节点状态、事件和恢复信息。
 */

import { createSlice, PayloadAction } from "@reduxjs/toolkit";

import type { RunEvent } from "@/lib/ws/run-socket";

/** 定义`ConnectionStatus`允许的状态或联合类型，避免跨模块使用任意字符串。 */
type ConnectionStatus = "idle" | "connecting" | "connected" | "disconnected" | "error";
/** 定义`AgentNodeStatus`允许的状态或联合类型，避免跨模块使用任意字符串。 */
export type AgentNodeStatus = "completed" | "running" | "waiting" | "retrying" | "failed";

/** 定义`AgentNodeExecution`数据契约，约束组件属性或接口响应字段。 */
export interface AgentNodeExecution {
  status: AgentNodeStatus;
  attempt?: number;
  max_attempts?: number;
  error?: string | null;
  reused?: boolean;
  started_at?: string;
  completed_at?: string;
  updated_at?: string;
  trace?: Record<string, unknown>;
}

/** 定义`RunState`数据契约，约束组件属性或接口响应字段。 */
interface RunState {
  activeRunId?: string;
  connectionStatus: ConnectionStatus;
  status: string;
  events: RunEvent[];
  nodeStatuses: Record<string, AgentNodeStatus>;
  nodeDetails: Record<string, AgentNodeExecution>;
}

/** 定义`RunHydration`数据契约，约束组件属性或接口响应字段。 */
interface RunHydration {
  status: string;
  outputKeys: string[];
  executionSnapshot?: Record<string, unknown>;
}

/** 定义`waitingNodeStatuses` Redux状态、动作或选择器配置。 */
const waitingNodeStatuses = () => ({
  requirement: "waiting" as const,
  researchPlan: "waiting" as const,
  market: "waiting" as const,
  competitor: "waiting" as const,
  insight: "waiting" as const,
  researchSynthesis: "waiting" as const,
  concept: "waiting" as const,
  supplier: "waiting" as const,
  finance: "waiting" as const,
  scoring: "waiting" as const,
  critic: "waiting" as const,
  narrative: "waiting" as const,
  approval: "waiting" as const,
});

/** 定义`initialState`初始状态，避免加载期间出现空值分支。 */
const initialState: RunState = {
  connectionStatus: "idle",
  status: "idle",
  events: [],
  nodeStatuses: waitingNodeStatuses(),
  nodeDetails: {},
};

/** 定义`nodeIdByEventName` Redux状态、动作或选择器配置。 */
// 后端使用稳定的 Agent 函数名，前端使用更短的画布节点 ID；映射集中维护可防止状态漂移。
const nodeIdByEventName: Record<string, string> = {
  requirement_agent: "requirement",
  research_planning_agent: "researchPlan",
  market_agent: "market",
  competitor_agent: "competitor",
  user_insight_agent: "insight",
  research_synthesis_agent: "researchSynthesis",
  concept_agent: "concept",
  supplier_agent: "supplier",
  finance_agent: "finance",
  scoring_agent: "scoring",
  critic_agent: "critic",
  narrative_agent: "narrative",
  review_agent: "approval",
};

/** 定义`nodeIdByOutputKey` Redux状态、动作或选择器配置。 */
const nodeIdByOutputKey: Record<string, string> = {
  requirement: "requirement",
  research_plan: "researchPlan",
  market: "market",
  competitor: "competitor",
  user_insight: "insight",
  research_synthesis: "researchSynthesis",
  concept: "concept",
  supplier: "supplier",
  finance: "finance",
  scorecard: "scoring",
  critic: "critic",
  narrative: "narrative",
  approval: "approval",
};

/** 定义`workflowNodeIds` Redux状态、动作或选择器配置。 */
const workflowNodeIds = Object.values(nodeIdByEventName);

/** 实现`activateNextNodes`辅助逻辑，集中处理页面展示或状态转换规则。 */
function activateNextNodes(state: RunState, completedNode: string): void {
  if (completedNode === "requirement") {
    if (state.nodeStatuses.researchPlan === "waiting") state.nodeStatuses.researchPlan = "running";
  } else if (completedNode === "researchPlan") {
    if (state.nodeStatuses.market === "waiting") state.nodeStatuses.market = "running";
    if (state.nodeStatuses.competitor === "waiting") state.nodeStatuses.competitor = "running";
    if (state.nodeStatuses.insight === "waiting") state.nodeStatuses.insight = "running";
  } else if (
    ["market", "competitor", "insight"].includes(completedNode) &&
    state.nodeStatuses.market === "completed" &&
    state.nodeStatuses.competitor === "completed" &&
    state.nodeStatuses.insight === "completed"
  ) {
    if (state.nodeStatuses.researchSynthesis === "waiting") state.nodeStatuses.researchSynthesis = "running";
  } else if (completedNode === "researchSynthesis") {
    if (state.nodeStatuses.concept === "waiting") state.nodeStatuses.concept = "running";
  } else if (completedNode === "concept") {
    if (state.nodeStatuses.supplier === "waiting") state.nodeStatuses.supplier = "running";
    if (state.nodeStatuses.finance === "waiting") state.nodeStatuses.finance = "running";
  } else if (
    ["supplier", "finance"].includes(completedNode) &&
    state.nodeStatuses.supplier === "completed" &&
    state.nodeStatuses.finance === "completed"
  ) {
    if (state.nodeStatuses.scoring === "waiting") state.nodeStatuses.scoring = "running";
  } else if (completedNode === "scoring") {
    if (state.nodeStatuses.critic === "waiting") state.nodeStatuses.critic = "running";
  } else if (completedNode === "critic") {
    if (state.nodeStatuses.narrative === "waiting") state.nodeStatuses.narrative = "running";
  } else if (completedNode === "narrative") {
    if (state.nodeStatuses.approval === "waiting") state.nodeStatuses.approval = "running";
  }
}

/** 实现`readExecutionNodes`辅助逻辑，集中处理页面展示或状态转换规则。 */
function readExecutionNodes(
  snapshot?: Record<string, unknown>,
): Record<string, AgentNodeExecution> {
  const nodes = snapshot?.nodes;
  if (typeof nodes !== "object" || nodes === null || Array.isArray(nodes)) {
    return {};
  }
  const result: Record<string, AgentNodeExecution> = {};
  for (const [nodeName, value] of Object.entries(nodes)) {
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      continue;
    }
    const detail = value as Record<string, unknown>;
    const nodeId = nodeIdByEventName[nodeName];
    if (!nodeId) {
      continue;
    }
    const rawStatus = detail.status;
    const executionStatus: AgentNodeStatus =
      rawStatus === "waiting" || rawStatus === "retrying" || rawStatus === "failed" || rawStatus === "running"
        ? rawStatus
        : "completed";
    result[nodeId] = {
      status: executionStatus,
      attempt: typeof detail.attempt === "number" ? detail.attempt : undefined,
      max_attempts: typeof detail.max_attempts === "number" ? detail.max_attempts : undefined,
      error: typeof detail.error === "string" ? detail.error : null,
      reused: detail.reused === true,
      started_at: typeof detail.started_at === "string" ? detail.started_at : undefined,
      completed_at: typeof detail.completed_at === "string" ? detail.completed_at : undefined,
      updated_at: typeof detail.updated_at === "string" ? detail.updated_at : undefined,
      trace: typeof detail.trace === "object" && detail.trace !== null && !Array.isArray(detail.trace)
        ? (detail.trace as Record<string, unknown>)
        : undefined,
    };
  }
  return result;
}

/** 实现`eventKey`辅助逻辑，集中处理页面展示或状态转换规则。 */
function eventKey(event: RunEvent): string {
  if (event.event_id) {
    return event.event_id;
  }
  return `${event.event_type}:${event.occurred_at ?? ""}:${JSON.stringify(event.payload ?? {})}`;
}

/** 实现`mergeRunEvents`辅助逻辑，集中处理页面展示或状态转换规则。 */
function mergeRunEvents(current: RunEvent[], incoming: RunEvent[]): RunEvent[] {
  // REST 历史与 WebSocket 增量可能重复到达，先按事件 ID 去重再排序，最后限制内存上限。
  const byKey = new Map<string, RunEvent>();
  for (const event of [...current, ...incoming]) {
    byKey.set(eventKey(event), event);
  }
  return [...byKey.values()]
    .sort((left, right) => {
      const leftTime = left.occurred_at ?? "";
      const rightTime = right.occurred_at ?? "";
      return leftTime.localeCompare(rightTime) || (left.event_id ?? "").localeCompare(right.event_id ?? "");
    })
    .slice(-200);
}

/** 定义`runSlice` Redux状态、动作或选择器配置。 */
const runSlice = createSlice({
  name: "run",
  initialState,
  reducers: {
    setActiveRun(state, action: PayloadAction<string | undefined>) {
      state.activeRunId = action.payload;
      state.events = [];
      state.status = action.payload ? "queued" : "idle";
      state.nodeStatuses = waitingNodeStatuses();
      state.nodeDetails = {};
      if (action.payload) {
        state.nodeStatuses.requirement = "running";
      }
    },
    setRunStatus(state, action: PayloadAction<string>) {
      state.status = action.payload;
    },
    hydrateRunState(state, action: PayloadAction<RunHydration>) {
      state.status = action.payload.status;
      state.nodeStatuses = waitingNodeStatuses();
      state.nodeDetails = readExecutionNodes(action.payload.executionSnapshot);
      for (const [nodeId, detail] of Object.entries(state.nodeDetails)) {
        state.nodeStatuses[nodeId] = detail.status;
      }
      for (const outputKey of action.payload.outputKeys) {
        const nodeId = nodeIdByOutputKey[outputKey];
        if (nodeId) {
          state.nodeStatuses[nodeId] = "completed";
        }
      }

      if (action.payload.status === "approval_required") {
        for (const nodeId of workflowNodeIds) {
          if (nodeId !== "approval" && state.nodeStatuses[nodeId] !== "failed") {
            state.nodeStatuses[nodeId] = "completed";
          }
        }
        state.nodeStatuses.approval = "waiting";
        state.nodeDetails.approval = {
          ...state.nodeDetails.approval,
          status: "waiting",
        };
      } else if (["completed", "cancelled"].includes(action.payload.status)) {
        for (const nodeId of workflowNodeIds) {
          if (state.nodeStatuses[nodeId] !== "failed") {
            state.nodeStatuses[nodeId] = "completed";
          }
        }
      } else if (action.payload.status === "queued") {
        state.nodeStatuses.requirement = "running";
      } else if (action.payload.status === "running") {
        const completedNodes = workflowNodeIds.filter(
          (nodeId) => state.nodeStatuses[nodeId] === "completed",
        );
        if (completedNodes.length === 0) {
          state.nodeStatuses.requirement = "running";
        } else {
          for (const nodeId of completedNodes) {
            activateNextNodes(state, nodeId);
          }
        }
      }
    },
    setConnectionStatus(state, action: PayloadAction<ConnectionStatus>) {
      state.connectionStatus = action.payload;
    },
    hydrateRunEvents(state, action: PayloadAction<RunEvent[]>) {
      state.events = mergeRunEvents(state.events, action.payload);
    },
    receiveRunEvent(state, action: PayloadAction<RunEvent>) {
      state.events = mergeRunEvents(state.events, [action.payload]);
      if (["run.started", "run.resumed"].includes(action.payload.event_type)) {
        state.status = "running";
        if (action.payload.event_type === "run.started") {
          state.nodeStatuses.requirement = "running";
        }
      } else if (action.payload.event_type === "run.revision_requested") {
        state.status = "queued";
        state.nodeStatuses = waitingNodeStatuses();
        state.nodeStatuses.requirement = "running";
      } else if (action.payload.event_type === "agent.node.completed") {
        const nodeName = action.payload.payload?.node;
        if (typeof nodeName === "string") {
          const nodeId = nodeIdByEventName[nodeName];
          if (nodeId) {
            state.nodeStatuses[nodeId] = "completed";
            state.nodeDetails[nodeId] = {
              status: "completed",
              attempt:
                typeof action.payload.payload?.attempt === "number"
                  ? action.payload.payload.attempt
                  : state.nodeDetails[nodeId]?.attempt,
              max_attempts:
                typeof action.payload.payload?.max_attempts === "number"
                  ? action.payload.payload.max_attempts
                  : state.nodeDetails[nodeId]?.max_attempts,
              reused: action.payload.payload?.reused === true,
              updated_at: action.payload.occurred_at,
            };
            activateNextNodes(state, nodeId);
          }
        }
      } else if (
        ["agent.node.started", "agent.node.retrying", "agent.node.failed", "agent.node.skipped"].includes(
          action.payload.event_type,
        )
      ) {
        const nodeName = action.payload.payload?.node;
        if (typeof nodeName === "string") {
          const nodeId = nodeIdByEventName[nodeName];
          if (nodeId) {
            const eventType = action.payload.event_type;
            const status: AgentNodeStatus =
              eventType === "agent.node.retrying"
                ? "retrying"
                : eventType === "agent.node.failed"
                  ? "failed"
                  : eventType === "agent.node.skipped"
                    ? "completed"
                    : "running";
            state.nodeStatuses[nodeId] = status;
            state.nodeDetails[nodeId] = {
              status,
              attempt:
                typeof action.payload.payload?.attempt === "number"
                  ? action.payload.payload.attempt
                  : state.nodeDetails[nodeId]?.attempt,
              max_attempts:
                typeof action.payload.payload?.max_attempts === "number"
                  ? action.payload.payload.max_attempts
                  : state.nodeDetails[nodeId]?.max_attempts,
              error:
                typeof action.payload.payload?.error === "string"
                  ? action.payload.payload.error
                  : state.nodeDetails[nodeId]?.error ?? null,
              reused: eventType === "agent.node.skipped" || state.nodeDetails[nodeId]?.reused,
              updated_at: action.payload.occurred_at,
            };
          }
        }
      } else if (action.payload.event_type === "approval.required") {
        state.status = "approval_required";
        state.nodeStatuses.approval = "waiting";
        state.nodeDetails.approval = {
          ...state.nodeDetails.approval,
          status: "waiting",
          updated_at: action.payload.occurred_at,
        };
      } else if (action.payload.event_type === "approval.completed") {
        const eventStatus = action.payload.payload?.status;
        state.status =
          eventStatus === "cancelled" || eventStatus === "completed" ? eventStatus : "completed";
        state.nodeStatuses.approval = "completed";
        state.nodeDetails.approval = {
          ...state.nodeDetails.approval,
          status: "completed",
          updated_at: action.payload.occurred_at,
        };
      } else if (action.payload.event_type === "run.completed") {
        state.status = "completed";
      } else if (action.payload.event_type === "run.failed") {
        state.status = "failed";
      }
    },
  },
});

export const {
  hydrateRunState,
  hydrateRunEvents,
  receiveRunEvent,
  setActiveRun,
  setConnectionStatus,
  setRunStatus,
} = runSlice.actions;
export default runSlice.reducer;
