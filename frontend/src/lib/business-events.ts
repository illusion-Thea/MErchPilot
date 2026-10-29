/**
 * 文件职责：定义跨组件业务数据变更事件，触发相关模块刷新。
 */

export const BUSINESS_DATA_CHANGED_EVENT = "merchpilot:business-data-changed";

/** 实现`notifyBusinessDataChanged`辅助逻辑，集中处理页面展示或状态转换规则。 */
export function notifyBusinessDataChanged() {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(BUSINESS_DATA_CHANGED_EVENT));
}
