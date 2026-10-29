/**
 * 文件职责：将机会分析指标绘制为面向业务人员的图表。
 */

"use client";

import { useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { Empty, Spin } from "antd";

import { BUSINESS_DATA_CHANGED_EVENT } from "@/lib/business-events";
import { listOpportunitiesPage, OpportunitySummary } from "@/lib/http/analytics";

/** 定义`Column`模块常量或配置，供当前文件中的多个流程复用。 */
const Column = dynamic(() => import("@ant-design/charts").then((module) => module.Column), {
  ssr: false,
});

/** 把机会评分和指标转换为业务人员可读的图表。 */
export function OpportunityChart() {
  const [opportunities, setOpportunities] = useState<OpportunitySummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    const load = () => {
      void listOpportunitiesPage(1, 12)
        .then((result) => {
          if (active) {
            setOpportunities(result.items);
            setLoading(false);
          }
        })
        .catch(() => {
          if (active) setLoading(false);
        });
    };
    load();
    const timer = window.setInterval(load, 10_000);
    window.addEventListener(BUSINESS_DATA_CHANGED_EVENT, load);
    return () => {
      active = false;
      window.clearInterval(timer);
      window.removeEventListener(BUSINESS_DATA_CHANGED_EVENT, load);
    };
  }, []);

  const data = useMemo(
    () =>
      opportunities.flatMap((item) =>
        typeof item.score === "number"
          ? [
              {
                project: item.project_name,
                score: item.score,
                category: item.category,
                target_market: item.target_market,
                evidence_count: item.evidence_count,
                margin_rate:
                  typeof item.margin_rate === "number"
                    ? `${(item.margin_rate * 100).toFixed(1)}%`
                    : "待计算",
                supplier_risk: item.supplier_risk ?? "待评估",
              },
            ]
          : [],
      ),
    [opportunities],
  );

  if (loading) {
    return (
      <div className="chart-empty-state">
        <Spin />
      </div>
    );
  }
  if (data.length === 0) {
    return (
      <div className="chart-empty-state">
        <Empty description="完成一次 Agent 运行后展示真实机会评分" />
      </div>
    );
  }
  return (
    <div style={{ height: 320 }}>
      <Column
        data={data}
        xField="project"
        yField="score"
        color="#195bff"
        axis={{
          x: { title: "规划项目" },
          y: { title: "机会分" },
        }}
        scale={{ y: { domain: [0, 100] } }}
        label={{ text: "score", position: "top", style: { fill: "#10223b" } }}
        tooltip={{ channel: "y" }}
      />
    </div>
  );
}
