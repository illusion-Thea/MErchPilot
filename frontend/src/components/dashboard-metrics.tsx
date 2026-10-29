/**
 * 文件职责：展示数据、项目、审批与运行等首页概览指标。
 */

"use client";

import { useEffect, useState } from "react";

import { getDashboardSnapshot } from "@/lib/http/analytics";
import { getDataImportQualitySummary } from "@/lib/http/data-imports";

/** 定义`MetricItem`数据契约，约束组件属性或接口响应字段。 */
interface MetricItem {
  label: string;
  value: string;
  caption: string;
}

/** 定义`loadingMetrics`模块常量或配置，供当前文件中的多个流程复用。 */
const loadingMetrics: MetricItem[] = [
  { label: "进行中项目", value: "—", caption: "正在读取项目状态" },
  { label: "待审批事项", value: "—", caption: "正在读取审批队列" },
  { label: "规划项目总数", value: "—", caption: "正在读取项目台账" },
  { label: "可用证据记录", value: "—", caption: "正在读取导入质量" },
];

/** 展示数据、项目、审批和运行状态的概览指标。 */
export function DashboardMetrics() {
  const [metrics, setMetrics] = useState<MetricItem[]>(loadingMetrics);

  useEffect(() => {
    let active = true;
    const load = () => {
      void Promise.all([getDashboardSnapshot(), getDataImportQualitySummary()])
        .then(([snapshot, qualitySummary]) => {
          if (!active) {
            return;
          }
          setMetrics([
            { label: "进行中项目", value: String(snapshot.active_project_total), caption: "运行中及等待审批" },
            { label: "待审批事项", value: String(snapshot.pending_approval_count + snapshot.pending_launch_review_count), caption: "系统内线上审批队列" },
            { label: "规划项目总数", value: String(snapshot.project_total), caption: "PostgreSQL 项目台账" },
            { label: "可用证据记录", value: String(qualitySummary.verified_records), caption: "通过质量校验的证据" },
          ]);
        })
        .catch(() => undefined);
    };
    load();
    const timer = window.setInterval(load, 10_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  return (
    <section className="metrics-grid">
      {metrics.map((metric) => (
        <article className="metric-card" key={metric.label}>
          <div className="metric-label">{metric.label}</div>
          <div className="metric-value">{metric.value}</div>
          <div className="metric-caption">{metric.caption}</div>
        </article>
      ))}
    </section>
  );
}
