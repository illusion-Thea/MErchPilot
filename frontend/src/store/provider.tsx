/**
 * 文件职责：向 React 组件树注入 Redux Store。
 */

"use client";

import { useState } from "react";
import { Provider } from "react-redux";

import { makeStore } from "@/store";
import type { AppStore } from "@/store";

/** 渲染`StoreProvider` React组件，并管理该业务模块的页面交互。 */
export function StoreProvider({ children }: Readonly<{ children: React.ReactNode }>) {
  const [store] = useState<AppStore>(makeStore);
  return <Provider store={store}>{children}</Provider>;
}
