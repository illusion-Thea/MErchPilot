/**
 * 文件职责：保存跨模块共享的当前项目上下文，并区分首次恢复与用户主动清除。
 */

import { createSlice, PayloadAction } from "@reduxjs/toolkit";

/** 定义当前项目上下文携带的最小业务信息，供规划、审批、选品和立项共同使用。 */
export interface ProjectContextValue {
  projectId: string;
  projectName?: string;
  category?: string;
  targetMarket?: string;
  tenantId?: string;
  source?: "url" | "restored" | "context-bar" | "planning" | "approval" | "selection" | "initiative" | "demo";
}

/** 定义项目上下文 Redux 状态，revision 用于识别用户主动切换或清除操作。 */
interface ProjectContextState {
  current?: ProjectContextValue;
  hydrated: boolean;
  revision: number;
}

/** 定义项目上下文初始状态，页面恢复前不主动清空各模块已有选择。 */
const initialState: ProjectContextState = {
  hydrated: false,
  revision: 0,
};

/** 定义跨模块项目上下文的 Redux reducer 与动作。 */
const projectContextSlice = createSlice({
  name: "projectContext",
  initialState,
  reducers: {
    hydrateProjectContext(state, action: PayloadAction<ProjectContextValue | undefined>) {
      state.current = action.payload;
      state.hydrated = true;
    },
    setProjectContext(state, action: PayloadAction<ProjectContextValue>) {
      const projectChanged = state.current?.projectId !== action.payload.projectId;
      state.current = action.payload;
      state.hydrated = true;
      if (projectChanged) state.revision += 1;
    },
    clearProjectContext(state) {
      state.current = undefined;
      state.hydrated = true;
      state.revision += 1;
    },
  },
});

export const { clearProjectContext, hydrateProjectContext, setProjectContext } =
  projectContextSlice.actions;

export default projectContextSlice.reducer;
