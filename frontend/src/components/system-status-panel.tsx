/**
 * 文件职责：展示 PostgreSQL、Redis、Milvus、Celery、模型及企业适配器状态。
 */

"use client";

import { useEffect, useState } from "react";
import { Alert, Button, Space, Tag } from "antd";
import { ReloadOutlined } from "@ant-design/icons";

import { getSystemReadiness, SystemReadiness } from "@/lib/http/system";

/** 定义`serviceDefinitions`展示映射，集中维护状态文案、颜色或选项。 */
const serviceDefinitions = [
  { key: "api", name: "FastAPI API", detail: "业务接口与审批服务", group: "核心依赖" },
  { key: "postgres", name: "PostgreSQL", detail: "项目、运行、审批和审计权威数据", group: "核心依赖" },
  { key: "redis", name: "Redis", detail: "任务队列、Checkpoint 与事件流", group: "核心依赖" },
  { key: "worker", name: "Celery Worker", detail: "异步导入、Agent 和报告任务执行", group: "核心依赖" },
  { key: "milvus", name: "Milvus", detail: "证据向量索引与租户过滤", group: "核心依赖" },
  { key: "embedding", name: "BGE-M3", detail: "Embedding 模型服务，可降级为规则流程", group: "可选模型" },
  { key: "reranker", name: "BGE Reranker", detail: "证据重排模型服务，可降级为原始排序", group: "可选模型" },
  { key: "mcp", name: "FastMCP", detail: "企业 Agent 与 IDE 助手的角色化业务工具服务", group: "Agent 接入" },
];

/** 定义`integrationDefinitions`展示映射，集中维护状态文案、颜色或选项。 */
const integrationDefinitions = [
  { key: "identity", name: "身份认证", detail: "当前用户、租户和角色解析", modeLabel: "认证模式" },
  { key: "object_storage", name: "对象存储", detail: "导入文件、报告和验证材料存储", modeLabel: "存储模式" },
  { key: "approval", name: "审批适配", detail: "系统内审批与未来 OA 同步出口", modeLabel: "审批模式" },
  { key: "telemetry", name: "监控遥测", detail: "审计事件与运行指标输出", modeLabel: "监控模式" },
];

/** 定义`coreServiceKeys`模块常量或配置，供当前文件中的多个流程复用。 */
const coreServiceKeys = new Set(["api", "postgres", "redis", "worker", "milvus"]);

/** 展示PostgreSQL、Redis、Milvus、Celery、模型与企业适配器健康状态。 */
export function SystemStatusPanel() {
  const [readiness, setReadiness] = useState<SystemReadiness>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();

  const refresh = async () => {
    setLoading(true);
    try {
      const value = await getSystemReadiness();
      setReadiness(value);
      setError(undefined);
    } catch {
      setReadiness(undefined);
      setError("无法连接后端 API，当前无法判断各服务状态。");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let active = true;
    const load = () => {
      void getSystemReadiness()
        .then((value) => {
          if (active) {
            setReadiness(value);
            setError(undefined);
          }
        })
        .catch(() => {
          if (active) {
            setReadiness(undefined);
            setError("无法连接后端 API，当前无法判断各服务状态。");
          }
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    };
    load();
    const timer = window.setInterval(load, 10_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  return (
    <article className="panel" id="system-status-panel">
      <div className="panel-header">
        <div>
          <h2 className="panel-title">运行基础设施</h2>
          <p className="panel-description">后端实时探测 Docker 核心服务与可选模型服务</p>
        </div>
        <div className="system-status-header-actions">
          {readiness ? (
            <Space size={6}>
              <Tag color={readiness.status === "ok" ? "success" : "error"}>
                核心服务 {readiness.status === "ok" ? "正常" : "异常"}
              </Tag>
              <Tag color={readiness.integration_status === "ok" ? "success" : "error"}>
                企业适配 {readiness.integration_status === "ok" ? "已就绪" : "未就绪"}
              </Tag>
            </Space>
          ) : null}
          <Button
            size="small"
            icon={<ReloadOutlined />}
            loading={loading}
            onClick={() => void refresh()}
          >
            刷新
          </Button>
        </div>
      </div>
      {error ? (
        <Alert
          type="warning"
          showIcon
          message={error}
          description="PostgreSQL、Redis、Milvus 会在 API 恢复后重新检测，这不代表它们已经停止。"
          style={{ marginBottom: 12 }}
        />
      ) : null}
      {readiness && Object.values(readiness.core_components ?? {}).some((ready) => !ready) ? (
        <Alert
          type="error"
          showIcon
          message="核心运行服务异常，新的异步任务可能无法执行"
          description="请先恢复 PostgreSQL、Redis、Celery Worker 或 Milvus，再继续导入数据、启动 Agent 和生成报告。"
          style={{ marginBottom: 12 }}
        />
      ) : null}
      {readiness && ["embedding", "reranker"].some((key) => readiness.optional_components?.[key] === false) ? (
        <Alert
          type="warning"
          showIcon
          message="可选模型服务未就绪，检索链路可能降级"
          description="数据导入、审批和已有结果仍可查看；Embedding 或 Reranker 恢复后可继续重建索引。"
          style={{ marginBottom: 12 }}
        />
      ) : null}
      {readiness?.optional_components?.mcp === false ? (
        <Alert
          type="warning"
          showIcon
          message="FastMCP 服务未就绪，企业 Agent 暂时无法连接"
          description="Web 端业务不受影响；恢复 MCP 容器后可在“Agent 集成”模块验证当前身份并复制客户端配置。"
          style={{ marginBottom: 12 }}
        />
      ) : null}
      {readiness && Object.values(readiness.integration_components ?? {}).some((ready) => !ready) ? (
        <Alert
          type="error"
          showIcon
          message="企业适配器未就绪，部分集成能力不可用"
          description="请检查身份认证、对象存储、OA 审批或监控 provider 配置；本地 provider 不会自动替代错误配置。"
          style={{ marginBottom: 12 }}
        />
      ) : null}
      <div className="status-list">
        {serviceDefinitions.map((service, index) => {
          const detected = Boolean(readiness);
          const ready = service.key === "api" ? detected : readiness?.components[service.key];
          const status = ready === true ? "ready" : ready === false ? "unavailable" : "pending";
          const statusText = ready === true
            ? "正常"
            : ready === false
              ? coreServiceKeys.has(service.key) ? "异常" : "未就绪"
              : "未检测";
          return (
            <div key={service.key}>
              {index === 0 || serviceDefinitions[index - 1]?.group !== service.group ? (
                <div className="status-group-title">{service.group}</div>
              ) : null}
              <div className="status-item">
              <div>
                <div className="status-name">{service.name}</div>
                <div className="status-detail">{service.detail}</div>
              </div>
              <div className="status-result">
                <span className={`status-dot ${status}`} />
                <Tag color={ready === true ? "success" : ready === false ? coreServiceKeys.has(service.key) ? "error" : "warning" : "default"}>
                  {statusText}
                </Tag>
              </div>
              </div>
            </div>
          );
        })}
        <div className="status-group-title">企业适配器</div>
        {integrationDefinitions.map((integration) => {
          const ready = readiness?.integration_components?.[integration.key];
          const mode = readiness?.provider_modes?.[integration.key];
          const status = ready === true ? "ready" : ready === false ? "unavailable" : "pending";
          const statusText = ready === true ? "已就绪" : ready === false ? "未就绪" : "未检测";
          return (
            <div className="status-item" key={integration.key}>
              <div>
                <div className="status-name">{integration.name}</div>
                <div className="status-detail">
                  {integration.detail}{mode ? ` · ${integration.modeLabel}：${mode}` : ""}
                </div>
              </div>
              <div className="status-result">
                <span className={`status-dot ${status}`} />
                <Tag color={ready === true ? "success" : ready === false ? "error" : "default"}>
                  {statusText}
                </Tag>
              </div>
            </div>
          );
        })}
      </div>
    </article>
  );
}
