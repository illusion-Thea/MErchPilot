/**
 * 文件职责：按项目分页展示跨模块审计活动和业务轨迹。
 */

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, Empty, Input, Pagination, Select, Spin } from "antd";

import { AuditEvent, listAuditEventsPage } from "@/lib/http/audit";
import { listPlanningProjectsPage, PlanningProject } from "@/lib/http/planning";

/** 定义`auditPageSize`服务端分页每页数量，保持页面负载稳定。 */
const auditPageSize = 12;

/** 定义`entityTypeOptions`展示映射，集中维护状态文案、颜色或选项。 */
const entityTypeOptions = [
  { value: "planning_project", label: "规划项目" },
  { value: "planning_run", label: "Agent 运行" },
  { value: "approval_task", label: "审批任务" },
  { value: "selected_product", label: "正式选品" },
  { value: "product_initiative", label: "商品立项" },
  { value: "data_import", label: "数据导入" },
  { value: "evidence_record", label: "证据记录" },
  { value: "planning_report", label: "规划报告" },
];

/** 定义`actionTitles`模块常量或配置，供当前文件中的多个流程复用。 */
const actionTitles: Record<string, string> = {
  "project.created": "规划项目已创建",
  "project.updated": "规划参数已更新",
  "run.queued": "Agent 任务已进入队列",
  "run.running": "Agent 工作流开始执行",
  "run.approval_required": "规划方案等待审批",
  "run.completed": "规划任务已完成",
  "run.failed": "规划任务执行失败",
  "run.cancelled": "规划任务已取消",
  "run.dispatch_failed": "任务队列提交失败",
  "approval.created": "线上审批任务已创建",
  "approval.approved": "规划方案已通过",
  "approval.rejected": "规划方案已驳回",
  "approval.revision_required": "规划方案被要求修订",
  "selected_product.created": "正式选品已进入决策池",
  "selected_product.updated": "选品推进状态已更新",
  "selected_product.validation_synced": "选品验证状态已自动同步",
  "selected_product.initiated": "正式选品已转入商品立项",
  "product_initiative.created": "商品立项已创建",
  "product_initiative.updated": "商品立项状态已更新",
  "product_initiative.milestone_updated": "商品立项里程碑已更新",
  "product_initiative.pilot_sale_recorded": "试销经营数据已录入",
  "product_initiative.pilot_sale_updated": "试销经营数据已修订",
  "import.created": "企业数据导入已创建",
  "import.processing": "企业数据正在解析",
  "import.completed": "企业数据导入完成",
  "import.failed": "企业数据导入失败",
  "import.dispatch_failed": "导入任务队列提交失败",
  "import.retry_queued": "失败批次已重新提交",
  "import.reindex_queued": "证据索引已进入重建队列",
  "import.reindex_dispatch_failed": "索引重建提交失败",
  "import.withdrawn": "数据导入批次已撤回",
  "report.queued": "规划报告已进入生成队列",
  "report.processing": "规划报告正在生成",
  "report.completed": "规划报告生成完成",
  "report.failed": "规划报告生成失败",
  "report.dispatch_failed": "报告任务提交失败",
};

/** 定义`actionOptions`展示映射，集中维护状态文案、颜色或选项。 */
const actionOptions = Object.entries(actionTitles).map(([value, label]) => ({ value, label }));

/** 实现`detailText`辅助逻辑，集中处理页面展示或状态转换规则。 */
function detailText(event: AuditEvent): string {
  const detail = event.detail;
  if (event.action === "project.created") {
    const name = typeof detail.name === "string" ? detail.name : event.entity_id;
    return `${name} · ${typeof detail.category === "string" ? detail.category : "未指定品类"}`;
  }
  if (event.action === "project.updated") {
    const fields = Array.isArray(detail.changed_fields) ? detail.changed_fields.join("、") : "项目参数";
    return `已修改：${fields}`;
  }
  if (event.action.startsWith("approval.")) {
    const comment = typeof detail.comment === "string" && detail.comment ? detail.comment : "无审批备注";
    return comment;
  }
  if (event.action.startsWith("selected_product.")) {
    if (event.action === "selected_product.validation_synced") {
      const rate = typeof detail.completion_rate === "number" ? `${detail.completion_rate}%` : "待统计";
      return `落地验证完成度 ${rate}`;
    }
    const name = typeof detail.name === "string" ? detail.name : event.entity_id;
    const fields = Array.isArray(detail.changed_fields) ? detail.changed_fields.join("、") : "正式选品";
    return event.action === "selected_product.created" ? name : `已更新：${fields}`;
  }
  if (event.action.startsWith("product_initiative.")) {
    if (event.action === "product_initiative.milestone_updated") {
      return `${String(detail.milestone_label || "里程碑")} · ${String(detail.milestone_status || "已更新")}`;
    }
    if (event.action === "product_initiative.pilot_sale_recorded") {
      return `${String(detail.channel || "试销渠道")} · ${String(detail.period_start || "")} 至 ${String(detail.period_end || "")}`;
    }
    if (event.action === "product_initiative.pilot_sale_updated") {
      const fields = Array.isArray(detail.changed_fields) ? detail.changed_fields.join("、") : "试销数据";
      return `已修订：${fields}`;
    }
    return typeof detail.name === "string" ? detail.name : event.entity_id;
  }
  if (event.action.startsWith("import.")) {
    if (typeof detail.filename === "string") return detail.filename;
    if (typeof detail.total_rows === "number") {
      return `共 ${detail.total_rows} 行，有效 ${detail.valid_rows ?? 0} 行`;
    }
  }
  if (event.action.startsWith("report.")) {
    return typeof detail.error === "string" ? detail.error : `运行 ${detail.run_id ?? event.entity_id}`;
  }
  if (typeof detail.error === "string") return detail.error;
  return `${event.entity_type} · ${event.entity_id}`;
}

/** 实现`occurredAtText`辅助逻辑，集中处理页面展示或状态转换规则。 */
function occurredAtText(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

/** 分页展示当前租户的业务审计事件，并支持按实体类型筛选。 */
export function AuditActivityFeed() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [projectIdInput, setProjectIdInput] = useState("");
  const [projectId, setProjectId] = useState("");
  const [projects, setProjects] = useState<PlanningProject[]>([]);
  const [projectSearchLoading, setProjectSearchLoading] = useState(false);
  const [entityType, setEntityType] = useState<string>();
  const [action, setAction] = useState<string>();
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const projectSearchRequestRef = useRef(0);
  const projectSearchTimerRef = useRef<number | undefined>(undefined);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await listAuditEventsPage({
        project_id: projectId || undefined,
        entity_type: entityType,
        action,
        limit: auditPageSize,
        offset: (page - 1) * auditPageSize,
      });
      setEvents(result.items);
      setTotal(result.total);
      setError(undefined);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "无法加载审计活动");
    } finally {
      setLoading(false);
    }
  }, [action, entityType, page, projectId]);

  const loadProjectOptions = useCallback(async (keyword = "") => {
    const requestId = ++projectSearchRequestRef.current;
    setProjectSearchLoading(true);
    try {
      const [activePage, archivedPage] = await Promise.all([
        listPlanningProjectsPage({ keyword, page: 1, pageSize: 20 }),
        listPlanningProjectsPage({ archivedOnly: true, keyword, page: 1, pageSize: 20 }),
      ]);
      if (requestId !== projectSearchRequestRef.current) {
        return;
      }
      setProjects((current) => {
        const selected = current.find((project) => project.id === projectId);
        return Array.from(
          new Map(
            [...(selected ? [selected] : []), ...activePage.items, ...archivedPage.items].map(
              (project) => [project.id, project],
            ),
          ).values(),
        );
      });
    } catch {
      if (requestId === projectSearchRequestRef.current) {
        setProjects((current) => current.filter((project) => project.id === projectId));
      }
    } finally {
      if (requestId === projectSearchRequestRef.current) {
        setProjectSearchLoading(false);
      }
    }
  }, [projectId]);

  const scheduleProjectSearch = useCallback((keyword: string) => {
    if (projectSearchTimerRef.current) {
      window.clearTimeout(projectSearchTimerRef.current);
    }
    projectSearchTimerRef.current = window.setTimeout(() => {
      void loadProjectOptions(keyword.trim());
    }, 250);
  }, [loadProjectOptions]);

  useEffect(() => {
    const projectLoad = window.setTimeout(() => void loadProjectOptions(), 0);
    return () => {
      window.clearTimeout(projectLoad);
      if (projectSearchTimerRef.current) {
        window.clearTimeout(projectSearchTimerRef.current);
      }
      projectSearchRequestRef.current += 1;
    };
  }, [loadProjectOptions]);

  useEffect(() => {
    const initialLoad = window.setTimeout(() => void load(), 0);
    const timer = window.setInterval(() => void load(), 5_000);
    return () => {
      window.clearTimeout(initialLoad);
      window.clearInterval(timer);
    };
  }, [load]);

  const resetToFirstPage = () => setPage(1);

  if (loading && events.length === 0) return <Spin size="small" />;

  const projectOptions = projects.map((project) => ({
    value: project.id,
    label: `${project.name} · ${project.category} · ${project.target_market}`,
  }));

  return (
    <div className="audit-feed">
      <div className="audit-filter-toolbar">
        <Select
          allowClear
          showSearch
          filterOption={false}
          value={projectId || undefined}
          placeholder="选择规划项目"
          options={projectOptions}
          loading={projectSearchLoading}
          onSearch={scheduleProjectSearch}
          onOpenChange={(open) => {
            if (open) {
              scheduleProjectSearch("");
            }
          }}
          onChange={(value) => {
            setProjectId(value ?? "");
            setProjectIdInput("");
            resetToFirstPage();
          }}
          notFoundContent={projects.length === 0 ? "暂未加载项目" : "没有匹配项目"}
        />
        <Input
          placeholder="或输入项目 ID"
          value={projectIdInput}
          allowClear
          onChange={(event) => setProjectIdInput(event.target.value)}
          onPressEnter={() => {
            setProjectId(projectIdInput.trim());
            resetToFirstPage();
          }}
        />
        <Select
          allowClear
          value={entityType}
          placeholder="对象类型"
          options={entityTypeOptions}
          onChange={(value) => {
            setEntityType(value);
            resetToFirstPage();
          }}
        />
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          value={action}
          placeholder="操作动作"
          options={actionOptions}
          onChange={(value) => {
            setAction(value);
            resetToFirstPage();
          }}
        />
        <Button
          onClick={() => {
            setProjectId(projectIdInput.trim());
            resetToFirstPage();
          }}
          loading={loading}
        >
          筛选
        </Button>
        <Button onClick={() => void load()} loading={loading}>刷新</Button>
      </div>
      {error ? (
        <Alert
          type="warning"
          showIcon
          title="审计记录加载不完整"
          description={error}
          style={{ marginBottom: 12 }}
        />
      ) : null}
      {events.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的审计记录" />
      ) : (
        <div className="activity-feed">
          {events.map((event) => (
            <div className="activity-item" key={event.id}>
              <span className="activity-marker" />
              <div className="activity-text">
                <strong>{actionTitles[event.action] ?? event.action}</strong>
                {detailText(event)}
              </div>
              <span>{occurredAtText(event.occurred_at)}</span>
            </div>
          ))}
        </div>
      )}
      {total > auditPageSize ? (
        <div className="audit-pagination">
          <Pagination
            current={page}
            pageSize={auditPageSize}
            total={total}
            showSizeChanger={false}
            showTotal={(value, range) => `${range[0]}-${range[1]} / ${value}`}
            onChange={setPage}
          />
        </div>
      ) : null}
    </div>
  );
}
