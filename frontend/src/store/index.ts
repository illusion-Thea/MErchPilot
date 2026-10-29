/**
 * 文件职责：创建 Redux Store 并组合运行与身份状态。
 */

import { configureStore } from "@reduxjs/toolkit";

import identityReducer from "@/store/identity-slice";
import projectContextReducer from "@/store/project-context-slice";
import runReducer from "@/store/run-slice";

/** 定义`makeStore` Redux状态、动作或选择器配置。 */
export const makeStore = () =>
  configureStore({
    reducer: {
      identity: identityReducer,
      projectContext: projectContextReducer,
      run: runReducer,
    },
  });

/** 定义`AppStore`允许的状态或联合类型，避免跨模块使用任意字符串。 */
export type AppStore = ReturnType<typeof makeStore>;
/** 定义`RootState`允许的状态或联合类型，避免跨模块使用任意字符串。 */
export type RootState = ReturnType<AppStore["getState"]>;
/** 定义`AppDispatch`允许的状态或联合类型，避免跨模块使用任意字符串。 */
export type AppDispatch = AppStore["dispatch"];
