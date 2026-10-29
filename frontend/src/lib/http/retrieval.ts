/**
 * 文件职责：声明语义检索 API 的请求、响应类型和调用方法。
 */

import { httpClient } from "@/lib/http/client";

/** 定义`RetrievalSearchRequest`数据契约，约束组件属性或接口响应字段。 */
export interface RetrievalSearchRequest {
  query: string;
  category?: string;
  target_market?: string;
  top_k?: number;
}

/** 定义`RetrievalHit`数据契约，约束组件属性或接口响应字段。 */
export interface RetrievalHit {
  evidence_id: string;
  score: number;
  vector_score?: number;
  import_job_id?: string;
  source_name?: string;
  source_row?: number;
  source_id?: string;
  source_url?: string;
  observed_at?: string;
  category?: string;
  target_market?: string;
  quality_status?: string;
  content: string;
  metadata: Record<string, unknown>;
  governance?: Record<string, unknown>;
}

/** 定义`RetrievalSearchResult`数据契约，约束组件属性或接口响应字段。 */
export interface RetrievalSearchResult {
  status: "ready" | "partial" | "degraded";
  reason?: string;
  query: string;
  evidence_ids: string[];
  hits: RetrievalHit[];
  governance: {
    canonical_evidence_ids: string[];
    suppressed_evidence_ids: string[];
    applied_review_ids: string[];
    conflicting_review_ids: string[];
  };
}

/** 调用后端`searchEvidence`接口并返回类型化响应。 */
export async function searchEvidence(
  payload: RetrievalSearchRequest,
): Promise<RetrievalSearchResult> {
  const response = await httpClient.post<RetrievalSearchResult>(
    "/retrieval/search",
    payload,
  );
  return response.data;
}
