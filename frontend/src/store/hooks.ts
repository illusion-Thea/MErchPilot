/**
 * 文件职责：导出带 Redux 类型约束的 dispatch、selector 和 store hooks。
 */

import { useDispatch, useSelector, useStore } from "react-redux";

import type { AppDispatch, AppStore, RootState } from "@/store";

/** 定义`useAppDispatch` Redux状态、动作或选择器配置。 */
export const useAppDispatch = useDispatch.withTypes<AppDispatch>();
/** 定义`useAppSelector` Redux状态、动作或选择器配置。 */
export const useAppSelector = useSelector.withTypes<RootState>();
/** 定义`useAppStore` Redux状态、动作或选择器配置。 */
export const useAppStore = useStore.withTypes<AppStore>();
