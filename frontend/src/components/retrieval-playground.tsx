/**
 * 文件职责：提供语义检索调试界面，解释召回、重排和证据治理结果。
 */

"use client";

import { useState } from "react";
import {
  BulbOutlined,
  FolderOpenOutlined,
  LinkOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import { Alert, Button, Empty, Input, Select, Space, Tag } from "antd";

import {
  RetrievalSearchResult,
  searchEvidence,
} from "@/lib/http/retrieval";

/** 定义`statusPresentation`展示映射，集中维护状态文案、颜色或选项。 */
const statusPresentation: Record<
  RetrievalSearchResult["status"],
  { color: string; label: string }
> = {
  ready: { color: "success", label: "检索正常" },
  partial: { color: "warning", label: "部分可用" },
  degraded: { color: "error", label: "链路降级" },
};

/** 定义`qualityLabels`展示映射，集中维护状态文案、颜色或选项。 */
const qualityLabels: Record<string, string> = {
  verified: "质量通过",
  warning: "需要注意",
};

/** 把formatObservedAt相关原始值格式化为页面可读文本。 */
function formatObservedAt(value?: string): string | null {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? null
    : new Intl.DateTimeFormat("zh-CN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }).format(date);
}

/** 提供语义检索调试界面，解释召回、治理和重排结果。 */
export function RetrievalPlayground() {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [targetMarket, setTargetMarket] = useState("");
  const [topK, setTopK] = useState(5);
  const [result, setResult] = useState<RetrievalSearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSearch = async () => {
    const normalizedQuery = query.trim();
    if (normalizedQuery.length < 2) {
      setError("请输入至少 2 个字的业务问题");
      setResult(null);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const nextResult = await searchEvidence({
        query: normalizedQuery,
        category: category.trim() || undefined,
        target_market: targetMarket.trim() || undefined,
        top_k: topK,
      });
      setResult(nextResult);
    } catch (requestError) {
      setResult(null);
      setError(requestError instanceof Error ? requestError.message : "检索失败");
    } finally {
      setLoading(false);
    }
  };

  const presentation = result ? statusPresentation[result.status] : null;

  return (
    <section className="panel retrieval-playground" id="retrieval-playground">
      <div className="panel-header">
        <div>
          <h2 className="panel-title">检索试用台</h2>
          <p className="panel-description">
            用真实业务问题验证 PostgreSQL 状态、Milvus 召回、重排和重复治理是否生效
          </p>
        </div>
        <Tag icon={<BulbOutlined />} color="blue">
          当前租户数据
        </Tag>
      </div>

      <div className="retrieval-search-form">
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onPressEnter={() => void handleSearch()}
          placeholder="例如：保温杯在中国市场的价格带和用户痛点是什么？"
          prefix={<SearchOutlined />}
          maxLength={500}
          allowClear
        />
        <Input
          value={category}
          onChange={(event) => setCategory(event.target.value)}
          placeholder="品类（可选）"
          maxLength={128}
          allowClear
        />
        <Input
          value={targetMarket}
          onChange={(event) => setTargetMarket(event.target.value)}
          placeholder="目标市场（可选）"
          maxLength={128}
          allowClear
        />
        <Select
          value={topK}
          onChange={setTopK}
          options={[5, 8, 10, 15, 20].map((value) => ({
            label: `返回 ${value} 条`,
            value,
          }))}
          aria-label="返回条数"
        />
        <Button
          type="primary"
          icon={<SearchOutlined />}
          loading={loading}
          onClick={() => void handleSearch()}
        >
          开始检索
        </Button>
      </div>

      {error ? <Alert type="error" showIcon message={error} /> : null}

      {result ? (
        <div className="retrieval-result-panel">
          <div className="retrieval-result-header">
            <Space wrap>
              <Tag color={presentation?.color}>{presentation?.label}</Tag>
              <span>问题：{result.query}</span>
              <span className="muted-text">命中 {result.hits.length} 条证据</span>
            </Space>
            {result.governance.suppressed_evidence_ids.length > 0 ? (
              <Tag color="purple">
                已抑制重复证据 {result.governance.suppressed_evidence_ids.length} 条
              </Tag>
            ) : null}
          </div>

          {result.reason ? (
            <Alert
              type={result.status === "degraded" ? "error" : "warning"}
              showIcon
              message="检索链路提示"
              description={result.reason}
              className="retrieval-reason"
            />
          ) : null}

          {result.hits.length === 0 ? (
            <Empty description="没有找到当前可检索的证据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            <div className="retrieval-hit-list">
              {result.hits.map((hit, index) => (
                <article className="retrieval-hit" key={hit.evidence_id}>
                  <div className="retrieval-hit-heading">
                    <Space wrap>
                      <span className="retrieval-hit-rank">#{index + 1}</span>
                      {hit.source_name ? <Tag>{hit.source_name}</Tag> : null}
                      {hit.category ? <Tag color="blue">{hit.category}</Tag> : null}
                      {hit.target_market ? <Tag color="cyan">{hit.target_market}</Tag> : null}
                      {hit.quality_status ? (
                        <Tag color={hit.quality_status === "verified" ? "success" : "warning"}>
                          {qualityLabels[hit.quality_status] ?? hit.quality_status}
                        </Tag>
                      ) : null}
                    </Space>
                    <span className="retrieval-hit-score">
                      重排分数 {hit.score.toFixed(3)}
                      {typeof hit.vector_score === "number"
                        ? ` · 向量 ${hit.vector_score.toFixed(3)}`
                        : ""}
                    </span>
                  </div>
                  <p>{hit.content}</p>
                  <div className="retrieval-hit-source">
                    <small>证据编号：{hit.evidence_id}</small>
                    {hit.source_id ? <small>来源 ID：{hit.source_id}</small> : null}
                    {hit.source_row ? <small>原文件第 {hit.source_row} 行</small> : null}
                    {formatObservedAt(hit.observed_at) ? (
                      <small>采集日期：{formatObservedAt(hit.observed_at)}</small>
                    ) : null}
                    {hit.source_url ? (
                      <a
                        href={hit.source_url}
                        target="_blank"
                        rel="noreferrer"
                        className="retrieval-source-link"
                      >
                        <LinkOutlined />
                        查看原始来源
                      </a>
                    ) : null}
                    {hit.import_job_id ? (
                      <Button
                        type="link"
                        size="small"
                        icon={<FolderOpenOutlined />}
                        className="retrieval-locate-button"
                        onClick={() => {
                          window.dispatchEvent(
                            new CustomEvent("merchpilot:focus-import", {
                              detail: {
                                importId: hit.import_job_id,
                                evidenceId: hit.evidence_id,
                              },
                            }),
                          );
                          document.getElementById("data-import-panel")?.scrollIntoView({
                            behavior: "smooth",
                            block: "start",
                          });
                        }}
                      >
                        定位原记录
                      </Button>
                    ) : null}
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="retrieval-empty-state">
          输入一个业务问题后，系统会展示可直接引用的证据；被撤回或人工阻断的记录不会出现在结果中。
        </div>
      )}
    </section>
  );
}
