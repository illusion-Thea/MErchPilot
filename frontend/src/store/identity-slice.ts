/**
 * 文件职责：管理当前用户身份加载状态和角色判断。
 */

import { createAsyncThunk, createSlice } from "@reduxjs/toolkit";

import { CurrentIdentity, getCurrentIdentity } from "@/lib/http/identity";

/** 定义`IdentityLoadStatus`允许的状态或联合类型，避免跨模块使用任意字符串。 */
export type IdentityLoadStatus = "idle" | "loading" | "ready" | "error";

/** 定义`IdentityState`数据契约，约束组件属性或接口响应字段。 */
interface IdentityState {
  current?: CurrentIdentity;
  status: IdentityLoadStatus;
  error?: string;
}

/** 定义`initialState`初始状态，避免加载期间出现空值分支。 */
const initialState: IdentityState = {
  status: "idle",
};

/** 定义`loadCurrentIdentity` Redux状态、动作或选择器配置。 */
export const loadCurrentIdentity = createAsyncThunk(
  "identity/loadCurrent",
  getCurrentIdentity,
);

/** 定义`identitySlice` Redux状态、动作或选择器配置。 */
const identitySlice = createSlice({
  name: "identity",
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(loadCurrentIdentity.pending, (state) => {
        state.status = "loading";
        state.error = undefined;
      })
      .addCase(loadCurrentIdentity.fulfilled, (state, action) => {
        state.current = action.payload;
        state.status = "ready";
      })
      .addCase(loadCurrentIdentity.rejected, (state, action) => {
        state.current = undefined;
        state.status = "error";
        state.error = action.error.message ?? "无法加载当前身份";
      });
  },
});

/** 判断`hasAnyRole`条件是否成立，供页面状态和操作权限复用。 */
export function hasAnyRole(
  identity: CurrentIdentity | undefined,
  allowedRoles: readonly string[],
): boolean {
  return Boolean(identity?.roles.some((role) => allowedRoles.includes(role)));
}

export default identitySlice.reducer;
