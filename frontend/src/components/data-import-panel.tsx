/**
 * 文件职责：提供数据上传、质量治理、重复审核和索引状态工作台。
 */

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BarChartOutlined,
  CheckCircleOutlined,
  DatabaseOutlined,
  DeleteOutlined,
  DownloadOutlined,
  EyeOutlined,
  FileExcelOutlined,
  InboxOutlined,
  RedoOutlined,
  ReloadOutlined,
  SearchOutlined,
  SyncOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Divider,
  Drawer,
  Empty,
  Input,
  message,
  Modal,
  Pagination,
  Popconfirm,
  Progress,
  Radio,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Upload,
} from "antd";
import type { TableProps, UploadProps } from "antd";

import { notifyBusinessDataChanged } from "@/lib/business-events";
import {
  compareDataImports,
  DataCoverage,
  DataDuplicateGroupPageSummary,
  DataDuplicateGroupRecordPage,
  DataDuplicateGroupSummary,
  DataDuplicateRecord,
  DuplicateReviewDecision,
  DataImportComparison,
  DataImportJob,
  DataImportPageSummary,
  DataImportQualitySummary,
  EvidenceIndexStatus,
  downloadDataCollectionTemplate,
  downloadImportQualityReport,
  EvidenceQualityIssue,
  EvidenceQualityIssueSummary,
  EvidenceQualityStatus,
  EvidenceRecord,
  getDataCoverage,
  getDataImport,
  getDataImportQualitySummary,
  getDuplicateEvidenceGroup,
  getImportQualityIssuesSummary,
  listDuplicateEvidenceGroupsPage,
  listDataImportsPage,
  listImportEvidencePage,
  reindexDataImport,
  reviewImportEvidence,
  reviewDuplicateEvidenceGroup,
  retryDataImport,
  uploadDataFile,
  withdrawDataImport,
} from "@/lib/http/data-imports";
import { AsyncTaskStatus, getAsyncTaskStatuses } from "@/lib/http/async-tasks";
import { useAppSelector } from "@/store/hooks";
import { hasAnyRole } from "@/store/identity-slice";

/** 定义`statusPresentation`展示映射，集中维护状态文案、颜色或选项。 */
const statusPresentation: Record<
  DataImportJob["status"],
  { color: string; label: string }
> = {
  queued: { color: "default", label: "等待处理" },
  processing: { color: "processing", label: "解析中" },
  completed: { color: "success", label: "已完成" },
  failed: { color: "error", label: "失败" },
};

/** 将文件扩展名转换为用户可理解的导入类型。 */
function recordSourceTypeLabel(filename: string): string {
  const suffix = filename.split(".").pop()?.toLowerCase() ?? "file";
  const labels: Record<string, string> = {
    csv: "表格 / CSV",
    xlsx: "表格 / XLSX",
    xlsm: "表格 / XLSM",
    pdf: "文档 / PDF + OCR",
    pptx: "演示文稿 / PPTX + OCR",
    docx: "文档 / DOCX + OCR",
    png: "图片 / Qwen-VL",
    jpg: "图片 / Qwen-VL",
    jpeg: "图片 / Qwen-VL",
    webp: "图片 / Qwen-VL",
    bmp: "图片 / Qwen-VL",
    tif: "图片 / Qwen-VL",
    tiff: "图片 / Qwen-VL",
  };
  return labels[suffix] ?? "文件 / 多模态解析";
}

/** 定义`duplicatePageSize`服务端分页每页数量，保持页面负载稳定。 */
const duplicatePageSize = 6;
/** 定义`duplicateRecordPageSize`服务端分页每页数量，保持页面负载稳定。 */
const duplicateRecordPageSize = 20;

/** 定义`retrievalStatusPresentation`展示映射，集中维护状态文案、颜色或选项。 */
const retrievalStatusPresentation: Record<
  DataImportJob["retrieval_status"],
  { color: string; label: string }
> = {
  ready: { color: "success", label: "可检索" },
  indexing: { color: "processing", label: "索引处理中" },
  failed: { color: "error", label: "索引异常" },
  empty: { color: "default", label: "暂无可检索记录" },
  unavailable: { color: "default", label: "暂不可检索" },
};

/** 定义`evidenceQualityPresentation`展示映射，集中维护状态文案、颜色或选项。 */
const evidenceQualityPresentation: Record<
  EvidenceRecord["quality_status"],
  { color: string; label: string }
> = {
  verified: { color: "success", label: "质量通过" },
  warning: { color: "warning", label: "需要注意" },
  blocked: { color: "error", label: "不可用" },
};

/** 定义`indexStatusPresentation`展示映射，集中维护状态文案、颜色或选项。 */
const indexStatusPresentation: Record<
  EvidenceRecord["index_status"],
  { color: string; label: string }
> = {
  pending: { color: "processing", label: "等待索引" },
  indexing: { color: "processing", label: "正在索引" },
  indexed: { color: "success", label: "已写入 Milvus" },
  failed: { color: "error", label: "索引失败" },
};

/** 定义`duplicateDecisionPresentation`展示映射，集中维护状态文案、颜色或选项。 */
const duplicateDecisionPresentation: Record<
  DuplicateReviewDecision,
  { color: string; label: string }
> = {
  keep_all: { color: "blue", label: "全部保留" },
  select_canonical: { color: "green", label: "已选主记录" },
  dismissed: { color: "default", label: "无需处理" },
};

/** 定义`importPageSize`服务端分页每页数量，保持页面负载稳定。 */
const importPageSize = 5;
/** 定义`evidencePageSize`服务端分页每页数量，保持页面负载稳定。 */
const evidencePageSize = 10;

/** 把formatDate相关原始值格式化为页面可读文本。 */
function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

/** 实现`normalizedValue`辅助逻辑，集中处理页面展示或状态转换规则。 */
function normalizedValue(record: EvidenceRecord, key: string): string {
  const normalizedRow = record.metadata_json.normalized_row;
  if (!normalizedRow || typeof normalizedRow !== "object" || Array.isArray(normalizedRow)) {
    return "-";
  }
  const value = (normalizedRow as Record<string, unknown>)[key];
  return value === null || value === undefined || value === "" ? "-" : String(value);
}

/** 实现`qualityIssues`辅助逻辑，集中处理页面展示或状态转换规则。 */
function qualityIssues(record: EvidenceRecord): EvidenceQualityIssue[] {
  const value = record.metadata_json.quality_issues;
  return Array.isArray(value) ? (value as EvidenceQualityIssue[]) : [];
}

/** 实现`saveBlob`辅助逻辑，集中处理页面展示或状态转换规则。 */
function saveBlob(blob: Blob, filename: string): void {
  const url = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.URL.revokeObjectURL(url);
}

/** 把formatPercent相关原始值格式化为页面可读文本。 */
function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

/** 实现`dimensionEntries`辅助逻辑，集中处理页面展示或状态转换规则。 */
function dimensionEntries(values: Record<string, number>): Array<{ label: string; value: number }> {
  return Object.entries(values).map(([label, value]) => ({ label, value }));
}

/** 实现`dataImportSyncSignature`辅助逻辑，集中处理页面展示或状态转换规则。 */
function dataImportSyncSignature(
  summary: DataImportQualitySummary,
  pageSummary: DataImportPageSummary,
): string {
  return JSON.stringify({
    imports: pageSummary,
    summary: {
      total_imports: summary.total_imports,
      completed_imports: summary.completed_imports,
      failed_imports: summary.failed_imports,
      total_records: summary.total_records,
      verified_records: summary.verified_records,
      warning_records: summary.warning_records,
      blocked_records: summary.blocked_records,
      indexed_records: summary.indexed_records,
      pending_index_records: summary.pending_index_records,
      failed_index_records: summary.failed_index_records,
      problem_import_total: summary.problem_import_total,
      problem_imports: summary.problem_imports
        .map((item) => ({
          import_id: item.import_id,
          warning_records: item.warning_records,
          blocked_records: item.blocked_records,
          failed_index_records: item.failed_index_records,
        }))
        .sort((left, right) => left.import_id.localeCompare(right.import_id)),
    },
  });
}

/** 提供文件导入、质量治理、重复审核和Milvus索引状态工作台。 */
export function DataImportPanel() {
  const [imports, setImports] = useState<DataImportJob[]>([]);
  const [comparisonImports, setComparisonImports] = useState<DataImportJob[]>([]);
  const [qualitySummary, setQualitySummary] = useState<DataImportQualitySummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [selectedImport, setSelectedImport] = useState<DataImportJob | null>(null);
  const [evidence, setEvidence] = useState<EvidenceRecord[]>([]);
  const [evidencePage, setEvidencePage] = useState(1);
  const [evidenceTotal, setEvidenceTotal] = useState(0);
  const [evidenceQualityFilter, setEvidenceQualityFilter] = useState<"all" | EvidenceQualityStatus>("all");
  const [evidenceIndexFilter, setEvidenceIndexFilter] = useState<"all" | EvidenceIndexStatus>("all");
  const [evidenceKeyword, setEvidenceKeyword] = useState("");
  const [evidenceKeywordInput, setEvidenceKeywordInput] = useState("");
  const [issueSummary, setIssueSummary] = useState<EvidenceQualityIssueSummary | null>(null);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [governanceOpen, setGovernanceOpen] = useState(false);
  const [governanceLoading, setGovernanceLoading] = useState(false);
  const [coverage, setCoverage] = useState<DataCoverage | null>(null);
  const [duplicates, setDuplicates] = useState<DataDuplicateGroupSummary[]>([]);
  const [duplicateFilter, setDuplicateFilter] = useState<"pending" | "all">("pending");
  const [duplicatePage, setDuplicatePage] = useState(1);
  const [duplicateTotal, setDuplicateTotal] = useState(0);
  const [duplicateLoading, setDuplicateLoading] = useState(false);
  const [duplicateSummary, setDuplicateSummary] = useState<DataDuplicateGroupPageSummary>({
    total: 0,
    pending: 0,
    reviewed: 0,
  });
  const [duplicateReviewTarget, setDuplicateReviewTarget] = useState<DataDuplicateGroupSummary | null>(null);
  const [reviewingDuplicate, setReviewingDuplicate] = useState<DataDuplicateGroupRecordPage | null>(null);
  const [duplicateRecordPage, setDuplicateRecordPage] = useState(1);
  const [duplicateDetailLoading, setDuplicateDetailLoading] = useState(false);
  const [duplicateReviewRecords, setDuplicateReviewRecords] = useState<DataDuplicateRecord[]>([]);
  const [duplicateDecision, setDuplicateDecision] =
    useState<DuplicateReviewDecision>("keep_all");
  const [canonicalEvidenceId, setCanonicalEvidenceId] = useState<string>();
  const [duplicateReviewNotes, setDuplicateReviewNotes] = useState("");
  const [duplicateReviewSubmitting, setDuplicateReviewSubmitting] = useState(false);
  const [reviewingEvidence, setReviewingEvidence] = useState<EvidenceRecord | null>(null);
  const [evidenceReviewAction, setEvidenceReviewAction] = useState<"verify" | "block">("verify");
  const [evidenceReviewNote, setEvidenceReviewNote] = useState("");
  const [evidenceReviewSubmitting, setEvidenceReviewSubmitting] = useState(false);
  const [baseImportId, setBaseImportId] = useState<string>();
  const [targetImportId, setTargetImportId] = useState<string>();
  const [comparison, setComparison] = useState<DataImportComparison | null>(null);
  const [comparisonLoading, setComparisonLoading] = useState(false);
  const [comparisonSearchLoading, setComparisonSearchLoading] = useState(false);
  const [taskStatuses, setTaskStatuses] = useState<Record<string, AsyncTaskStatus>>({});
  const [focusedImportId, setFocusedImportId] = useState<string>();
  const [currentImportPage, setCurrentImportPage] = useState(1);
  const [importTotal, setImportTotal] = useState(0);
  const [importPageSummary, setImportPageSummary] = useState<DataImportPageSummary>({
    total: 0,
    queued: 0,
    processing: 0,
    completed: 0,
    failed: 0,
  });
  const [importStatusFilter, setImportStatusFilter] = useState<"all" | DataImportJob["status"]>("all");
  const [importKeyword, setImportKeyword] = useState("");
  const [importKeywordInput, setImportKeywordInput] = useState("");
  const [messageApi, contextHolder] = message.useMessage();
  const identityState = useAppSelector((state) => state.identity);
  const canPlan = hasAnyRole(identityState.current, ["admin", "planner"]);
  const dataSyncSnapshotRef = useRef<string | undefined>(undefined);
  const importRequestRef = useRef(0);
  const comparisonSearchRequestRef = useRef(0);
  const comparisonSearchTimerRef = useRef<number | undefined>(undefined);
  const selectedImportId = selectedImport?.id;

  const syncTaskStatuses = useCallback(async (jobs: DataImportJob[]) => {
    const taskIds = jobs.flatMap((job) =>
      [job.celery_task_id, job.index_celery_task_id].filter(
        (taskId): taskId is string => Boolean(taskId),
      ),
    );
    if (taskIds.length === 0) {
      setTaskStatuses({});
      return;
    }
    try {
      const statuses = await getAsyncTaskStatuses(taskIds);
      setTaskStatuses(Object.fromEntries(statuses.map((item) => [item.task_id, item])));
    } catch {
      setTaskStatuses({});
    }
  }, []);

  const applyDataSyncSnapshot = useCallback((summary: DataImportQualitySummary, pageSummary: DataImportPageSummary, announceChange = true) => {
    const nextSignature = dataImportSyncSignature(summary, pageSummary);
    const previousSignature = dataSyncSnapshotRef.current;
    dataSyncSnapshotRef.current = nextSignature;
    if (announceChange && previousSignature && previousSignature !== nextSignature) {
      notifyBusinessDataChanged();
    }
  }, []);

  const refresh = useCallback(async (silent = false) => {
    const requestId = ++importRequestRef.current;
    if (!silent) {
      setLoading(true);
    }
    try {
      const [pageResult, summary, selectedJob] = await Promise.all([
        listDataImportsPage({
          status: importStatusFilter,
          keyword: importKeyword,
          page: currentImportPage,
          pageSize: importPageSize,
        }),
        getDataImportQualitySummary(),
        selectedImportId
          ? getDataImport(selectedImportId).catch(() => null)
          : Promise.resolve(null),
      ]);
      if (requestId !== importRequestRef.current) {
        return;
      }
      setImports(pageResult.items);
      setImportTotal(pageResult.total);
      setImportPageSummary(pageResult.summary);
      void syncTaskStatuses(pageResult.items);
      setSelectedImport((current) =>
        selectedJob ?? current,
      );
      setQualitySummary(summary);
      applyDataSyncSnapshot(summary, pageResult.summary);
      const pageCount = Math.max(1, Math.ceil(pageResult.total / importPageSize));
      if (currentImportPage > pageCount) {
        setCurrentImportPage(pageCount);
      }
    } catch (error) {
      if (!silent && requestId === importRequestRef.current) {
        messageApi.error(error instanceof Error ? error.message : "无法加载导入任务");
      }
    } finally {
      if (!silent && requestId === importRequestRef.current) {
        setLoading(false);
      }
    }
  }, [applyDataSyncSnapshot, currentImportPage, importKeyword, importStatusFilter, messageApi, selectedImportId, syncTaskStatuses]);

  useEffect(() => {
    const initialLoad = window.setTimeout(() => {
      void refresh();
    }, 0);
    const timer = window.setInterval(() => {
      void refresh(true);
    }, 4_000);
    return () => {
      window.clearTimeout(initialLoad);
      importRequestRef.current += 1;
      window.clearInterval(timer);
    };
  }, [refresh]);

  const importPageCount = Math.max(1, Math.ceil(importTotal / importPageSize));
  const effectiveImportPage = Math.min(currentImportPage, importPageCount);
  const evidenceFilters = useMemo(
    () => ({
      qualityStatus: evidenceQualityFilter === "all" ? undefined : evidenceQualityFilter,
      indexStatus: evidenceIndexFilter === "all" ? undefined : evidenceIndexFilter,
      keyword: evidenceKeyword || undefined,
      page: evidencePage,
      pageSize: evidencePageSize,
    }),
    [evidenceIndexFilter, evidenceKeyword, evidencePage, evidenceQualityFilter],
  );
  const hasPendingEvidence =
    (selectedImport?.pending_index_rows ?? 0) > 0 ||
    evidence.some((record) => record.index_status === "indexing");

  useEffect(() => {
    if (!selectedImportId) {
      return;
    }
    let active = true;
    void listImportEvidencePage(selectedImportId, evidenceFilters)
      .then((pageResult) => {
        if (active) {
          setEvidence(pageResult.items);
          setEvidenceTotal(pageResult.total);
          if (evidencePage > Math.max(1, Math.ceil(pageResult.total / evidencePageSize))) {
            setEvidencePage(Math.max(1, Math.ceil(pageResult.total / evidencePageSize)));
          }
        }
      })
      .catch((error: unknown) => {
        if (active) {
          messageApi.error(error instanceof Error ? error.message : "无法加载质量明细");
        }
      })
      .finally(() => {
        if (active) {
          setDetailsLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [evidenceFilters, evidencePage, messageApi, selectedImportId]);

  useEffect(() => {
    if (!selectedImportId) {
      return;
    }
    let active = true;
    void getImportQualityIssuesSummary(selectedImportId)
      .then((summary) => {
        if (active) {
          setIssueSummary(summary);
        }
      })
      .catch(() => {
        if (active) {
          setIssueSummary(null);
        }
      });
    return () => {
      active = false;
    };
  }, [selectedImportId]);

  useEffect(() => {
    if (!selectedImportId || !hasPendingEvidence) {
      return;
    }
    const timer = window.setInterval(() => {
      void listImportEvidencePage(selectedImportId, evidenceFilters)
        .then((pageResult) => {
          setEvidence(pageResult.items);
          setEvidenceTotal(pageResult.total);
        })
        .catch(() => undefined);
    }, 3_000);
    return () => window.clearInterval(timer);
  }, [evidenceFilters, hasPendingEvidence, selectedImportId]);

  useEffect(() => {
    if (!focusedImportId || !imports.some((item) => item.id === focusedImportId)) {
      return;
    }
    const scrollTimer = window.setTimeout(() => {
      const row = [...document.querySelectorAll<HTMLElement>("tr[data-row-key]")].find(
        (item) => item.getAttribute("data-row-key") === focusedImportId,
      );
      row?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 100);
    const clearTimer = window.setTimeout(() => setFocusedImportId(undefined), 6_000);
    return () => {
      window.clearTimeout(scrollTimer);
      window.clearTimeout(clearTimer);
    };
  }, [effectiveImportPage, focusedImportId, imports]);

  const uploadProps: UploadProps = {
    accept: ".csv,.xlsx,.xlsm,.pdf,.pptx,.docx,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff",
    multiple: false,
    showUploadList: false,
    customRequest: async ({ file, onError, onSuccess }) => {
      setUploading(true);
      try {
        const job = await uploadDataFile(file as File);
        setCurrentImportPage(1);
        setImportStatusFilter("all");
        setImportKeyword("");
        setImportKeywordInput("");
        setImports((current) => [job, ...current.filter((item) => item.id !== job.id)].slice(0, importPageSize));
        setImportTotal((current) => current + 1);
        setImportPageSummary((current) => ({
          ...current,
          total: current.total + 1,
          queued: current.queued + 1,
        }));
        notifyBusinessDataChanged();
        messageApi.success("文件已进入解析队列");
        onSuccess?.(job);
      } catch (error) {
        const uploadError = error instanceof Error ? error : new Error("上传失败");
        messageApi.error(uploadError.message);
        onError?.(uploadError);
      } finally {
        setUploading(false);
      }
    },
  };

  const handleTemplateDownload = useCallback(async () => {
    setDownloading(true);
    try {
      const blob = await downloadDataCollectionTemplate();
      saveBlob(blob, "商品规划Agent_数据采集模板.xlsx");
      messageApi.success("采集模板已下载");
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "无法下载采集模板");
    } finally {
      setDownloading(false);
    }
  }, [messageApi]);

  const openImportDetails = useCallback(
    (
      job: DataImportJob,
      focus?: {
        qualityStatus?: EvidenceQualityStatus;
        indexStatus?: EvidenceIndexStatus;
        evidenceId?: string;
        keyword?: string;
      },
    ) => {
      setFocusedImportId(undefined);
      setSelectedImport(job);
      setEvidence([]);
      setEvidencePage(1);
      setEvidenceTotal(0);
      setIssueSummary(null);
      setEvidenceQualityFilter(focus?.qualityStatus ?? "all");
      setEvidenceIndexFilter(focus?.indexStatus ?? "all");
      const focusKeyword = focus?.keyword?.trim() || focus?.evidenceId?.trim() || "";
      setEvidenceKeyword(focusKeyword);
      setEvidenceKeywordInput(focusKeyword);
      setDetailsLoading(true);
    },
    [],
  );

  const focusImport = useCallback(
    async (detail: {
      importId?: string;
      qualityStatus?: EvidenceQualityStatus;
      indexStatus?: EvidenceIndexStatus;
      evidenceId?: string;
      keyword?: string;
    }) => {
      if (!detail.importId) {
        return;
      }
      let job = imports.find((item) => item.id === detail.importId);
      if (!job) {
        try {
          job = await getDataImport(detail.importId);
        } catch (error) {
          messageApi.error(error instanceof Error ? error.message : "无法加载导入批次");
          return;
        }
      }
      if (!job) {
        messageApi.warning("未找到需要处理的数据批次，可能已被撤回");
        return;
      }
      openImportDetails(job, {
        qualityStatus: detail.qualityStatus,
        indexStatus: detail.indexStatus,
        evidenceId: detail.evidenceId,
        keyword: detail.keyword,
      });
      if (imports.some((item) => item.id === detail.importId)) {
        setFocusedImportId(detail.importId);
      }
    },
    [imports, messageApi, openImportDetails],
  );

  useEffect(() => {
    const handleFocusImport = (event: Event) => {
      const detail = (event as CustomEvent<{
        importId?: string;
        qualityStatus?: EvidenceQualityStatus;
        indexStatus?: EvidenceIndexStatus;
        evidenceId?: string;
        keyword?: string;
      }>).detail;
      void focusImport(detail ?? {});
    };
    window.addEventListener("merchpilot:focus-import", handleFocusImport);
    return () => window.removeEventListener("merchpilot:focus-import", handleFocusImport);
  }, [focusImport]);

  const handleRetry = useCallback(async (job: DataImportJob) => {
    setActionLoading(`${job.id}:retry`);
    try {
      const updated = await retryDataImport(job.id);
      setImports((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      notifyBusinessDataChanged();
      messageApi.success("失败批次已重新进入解析队列");
      void refresh(true);
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "无法重试导入批次");
    } finally {
      setActionLoading(null);
    }
  }, [messageApi, refresh]);

  const handleQualityReport = useCallback(async (job: DataImportJob) => {
    setActionLoading(`${job.id}:report`);
    try {
      const blob = await downloadImportQualityReport(job.id);
      const basename = job.filename.replace(/\.[^.]+$/, "");
      saveBlob(blob, `${basename}_数据质量报告.xlsx`);
      messageApi.success("数据质量报告已下载");
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "无法下载数据质量报告");
    } finally {
      setActionLoading(null);
    }
  }, [messageApi]);

  const handleWithdraw = useCallback(async (job: DataImportJob) => {
    setActionLoading(`${job.id}:withdraw`);
    try {
      await withdrawDataImport(job.id);
      notifyBusinessDataChanged();
      if (selectedImport?.id === job.id) {
        setSelectedImport(null);
      }
      messageApi.success("导入批次及其证据已撤回");
      await refresh(true);
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "无法撤回导入批次");
    } finally {
      setActionLoading(null);
    }
  }, [messageApi, refresh, selectedImport]);

  const handleReindex = useCallback(async () => {
    if (!selectedImport) {
      return;
    }
    setActionLoading(`${selectedImport.id}:reindex`);
    try {
      const result = await reindexDataImport(selectedImport.id);
      if (result.queued_records === 0) {
        messageApi.info("当前没有需要重建的索引记录");
      } else {
        notifyBusinessDataChanged();
        messageApi.success(`${result.queued_records} 条证据已进入索引队列`);
        setEvidence((current) =>
          current.map((record) =>
            record.quality_status !== "blocked" &&
            (record.index_status === "pending" || record.index_status === "failed")
              ? { ...record, index_status: "pending" }
              : record,
          ),
        );
      }
      void refresh(true);
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "无法重建索引");
    } finally {
      setActionLoading(null);
    }
  }, [messageApi, refresh, selectedImport]);

  const openGovernanceAnalysis = useCallback(async () => {
    setGovernanceOpen(true);
    setGovernanceLoading(true);
    try {
      const [coverageResult, importPage] = await Promise.all([
        getDataCoverage(),
        listDataImportsPage({ status: "completed", page: 1, pageSize: 20 }),
      ]);
      setCoverage(coverageResult);
      setComparisonImports(importPage.items);
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "无法加载数据治理分析");
    } finally {
      setGovernanceLoading(false);
    }
  }, [messageApi]);

  const loadComparisonImportOptions = useCallback(async (keyword = "") => {
    const requestId = ++comparisonSearchRequestRef.current;
    setComparisonSearchLoading(true);
    try {
      const result = await listDataImportsPage({
        status: "completed",
        keyword,
        page: 1,
        pageSize: 20,
      });
      if (requestId !== comparisonSearchRequestRef.current) {
        return;
      }
      setComparisonImports((current) => {
        const selectedIds = new Set([baseImportId, targetImportId].filter(Boolean));
        const selectedJobs = current.filter((job) => selectedIds.has(job.id));
        return Array.from(
          new Map([...selectedJobs, ...result.items].map((job) => [job.id, job])).values(),
        );
      });
    } catch (error) {
      if (requestId === comparisonSearchRequestRef.current) {
        messageApi.error(error instanceof Error ? error.message : "无法搜索导入批次");
      }
    } finally {
      if (requestId === comparisonSearchRequestRef.current) {
        setComparisonSearchLoading(false);
      }
    }
  }, [baseImportId, messageApi, targetImportId]);

  const scheduleComparisonImportSearch = useCallback((keyword: string) => {
    if (comparisonSearchTimerRef.current) {
      window.clearTimeout(comparisonSearchTimerRef.current);
    }
    comparisonSearchTimerRef.current = window.setTimeout(() => {
      void loadComparisonImportOptions(keyword.trim());
    }, 250);
  }, [loadComparisonImportOptions]);

  useEffect(() => () => {
    if (comparisonSearchTimerRef.current) {
      window.clearTimeout(comparisonSearchTimerRef.current);
    }
    comparisonSearchRequestRef.current += 1;
  }, []);

  const loadDuplicatePage = useCallback(async (
    pageValue: number,
    filterValue: "pending" | "all",
  ) => {
    setDuplicateLoading(true);
    try {
      const result = await listDuplicateEvidenceGroupsPage(
        filterValue,
        pageValue,
        duplicatePageSize,
      );
      setDuplicateSummary(result.summary);
      setDuplicateTotal(result.total);
      const pageCount = Math.max(1, Math.ceil(result.total / duplicatePageSize));
      if (pageValue > pageCount) {
        setDuplicatePage(pageCount);
        return;
      }
      setDuplicates(result.items);
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "无法加载重复数据候选");
    } finally {
      setDuplicateLoading(false);
    }
  }, [messageApi]);

  useEffect(() => {
    if (!governanceOpen) {
      return;
    }
    const timer = window.setTimeout(() => {
      void loadDuplicatePage(duplicatePage, duplicateFilter);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [duplicateFilter, duplicatePage, governanceOpen, loadDuplicatePage]);

  const handleCompareImports = useCallback(async () => {
    if (!baseImportId || !targetImportId) {
      messageApi.warning("请选择两个需要对比的导入批次");
      return;
    }
    if (baseImportId === targetImportId) {
      messageApi.warning("基准批次和目标批次不能相同");
      return;
    }
    setComparisonLoading(true);
    try {
      setComparison(await compareDataImports(baseImportId, targetImportId));
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "无法对比导入批次");
    } finally {
      setComparisonLoading(false);
    }
  }, [baseImportId, messageApi, targetImportId]);

  const loadDuplicateDetailPage = useCallback(async (
    group: DataDuplicateGroupSummary,
    pageValue: number,
    initialize: boolean,
  ) => {
    setDuplicateDetailLoading(true);
    try {
      const result = await getDuplicateEvidenceGroup(
        group.match_type,
        group.match_value,
        pageValue,
        duplicateRecordPageSize,
      );
      setReviewingDuplicate(result);
      setDuplicateRecordPage(result.page);
      setDuplicateReviewRecords((current) => {
        const records = new Map(
          (initialize ? [] : current).map((record) => [record.evidence_id, record]),
        );
        result.items.forEach((record) => records.set(record.evidence_id, record));
        if (result.canonical_record) {
          records.set(result.canonical_record.evidence_id, result.canonical_record);
        }
        return Array.from(records.values());
      });
      if (initialize) {
        setDuplicateDecision(result.review?.decision ?? "keep_all");
        setCanonicalEvidenceId(result.review?.canonical_evidence_id ?? undefined);
        setDuplicateReviewNotes(result.review?.notes ?? "");
      }
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "无法加载重复候选明细");
      if (initialize) {
        setDuplicateReviewTarget(null);
        setReviewingDuplicate(null);
      }
    } finally {
      setDuplicateDetailLoading(false);
    }
  }, [messageApi]);

  const openDuplicateReview = useCallback((group: DataDuplicateGroupSummary) => {
    setDuplicateReviewTarget(group);
    setReviewingDuplicate(null);
    setDuplicateReviewRecords([]);
    setDuplicateRecordPage(1);
    void loadDuplicateDetailPage(group, 1, true);
  }, [loadDuplicateDetailPage]);

  const closeDuplicateReview = useCallback(() => {
    setDuplicateReviewTarget(null);
    setReviewingDuplicate(null);
    setDuplicateReviewRecords([]);
    setDuplicateRecordPage(1);
  }, []);

  const handleDuplicateReview = useCallback(async () => {
    if (!reviewingDuplicate) {
      return;
    }
    if (duplicateDecision === "select_canonical" && !canonicalEvidenceId) {
      messageApi.warning("请选择一条主记录");
      return;
    }
    setDuplicateReviewSubmitting(true);
    try {
      await reviewDuplicateEvidenceGroup({
        match_type: reviewingDuplicate.match_type,
        match_value: reviewingDuplicate.match_value,
        decision: duplicateDecision,
        canonical_evidence_id:
          duplicateDecision === "select_canonical" ? canonicalEvidenceId : undefined,
        notes: duplicateReviewNotes.trim() || undefined,
      });
      closeDuplicateReview();
      await loadDuplicatePage(duplicatePage, duplicateFilter);
      notifyBusinessDataChanged();
      messageApi.success("重复候选审核结果已保存并记录审计日志");
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "无法保存审核结果");
    } finally {
      setDuplicateReviewSubmitting(false);
    }
  }, [
    canonicalEvidenceId,
    duplicateDecision,
    duplicateFilter,
    duplicatePage,
    duplicateReviewNotes,
    closeDuplicateReview,
    loadDuplicatePage,
    messageApi,
    reviewingDuplicate,
  ]);

  const openEvidenceReview = useCallback((record: EvidenceRecord, action: "verify" | "block") => {
    setReviewingEvidence(record);
    setEvidenceReviewAction(action);
    setEvidenceReviewNote("");
  }, []);

  const handleEvidenceReview = useCallback(async () => {
    if (!reviewingEvidence || !selectedImport) {
      return;
    }
    const note = evidenceReviewNote.trim();
    if (evidenceReviewAction === "block" && !note) {
      messageApi.warning("标记不可用必须填写处理说明");
      return;
    }
    setEvidenceReviewSubmitting(true);
    try {
      await reviewImportEvidence(selectedImport.id, reviewingEvidence.id, {
        action: evidenceReviewAction,
        note: note || undefined,
      });
      notifyBusinessDataChanged();
      setReviewingEvidence(null);
      setEvidenceReviewNote("");
      messageApi.success(
        evidenceReviewAction === "verify"
          ? "证据已确认可用，并进入索引队列"
          : "证据已标记不可用，Milvus 向量已清理",
      );
      await Promise.all([
        refresh(true),
        listImportEvidencePage(selectedImport.id, evidenceFilters).then((pageResult) => {
          setEvidence(pageResult.items);
          setEvidenceTotal(pageResult.total);
        }),
        getImportQualityIssuesSummary(selectedImport.id).then(setIssueSummary),
      ]);
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "无法保存证据审核结果");
    } finally {
      setEvidenceReviewSubmitting(false);
    }
  }, [
    evidenceReviewAction,
    evidenceReviewNote,
    evidenceFilters,
    messageApi,
    refresh,
    reviewingEvidence,
    selectedImport,
  ]);

  const columns = useMemo<TableProps<DataImportJob>["columns"]>(
    () => [
      {
        title: "文件",
        dataIndex: "filename",
        key: "filename",
        render: (value: string) => (
          <div className="import-file-cell">
            <DatabaseOutlined />
            <div>
              <span>{value}</span>
              <small>{recordSourceTypeLabel(value)}</small>
            </div>
          </div>
        ),
      },
      {
        title: "状态",
        dataIndex: "status",
        key: "status",
        width: 110,
        render: (value: DataImportJob["status"], record) => {
          const presentation = statusPresentation[value];
          const taskStatus = record.celery_task_id
            ? taskStatuses[record.celery_task_id]
            : undefined;
          const indexTaskStatus = record.index_celery_task_id
            ? taskStatuses[record.index_celery_task_id]
            : undefined;
          return (
            <div className="import-status-cell">
              <Tag color={presentation.color}>{presentation.label}</Tag>
              <Tag color={retrievalStatusPresentation[record.retrieval_status].color}>
                {retrievalStatusPresentation[record.retrieval_status].label}
              </Tag>
              {record.error_message ? <span title={record.error_message}>{record.error_message}</span> : null}
              {taskStatus ? (
                <span className="import-task-state">
                  解析任务：{taskStatus.state_label}
                </span>
              ) : null}
              {indexTaskStatus ? (
                <span className="import-task-state">
                  Milvus 索引：{indexTaskStatus.state_label}
                </span>
              ) : null}
              {record.celery_task_id ? (
                <span className="import-task-id" title={record.celery_task_id}>
                  解析编号 {record.celery_task_id}
                </span>
              ) : null}
              {record.index_celery_task_id ? (
                <span className="import-task-id" title={record.index_celery_task_id}>
                  索引编号 {record.index_celery_task_id}
                </span>
              ) : null}
            </div>
          );
        },
      },
      {
        title: "数据质量",
        key: "quality",
        width: 220,
        render: (_, record) => {
          if (record.status === "queued" || record.status === "processing") {
            return <Progress percent={record.status === "processing" ? 65 : 18} size="small" status="active" />;
          }
          if (!record.total_rows) {
            return <span className="muted-text">暂无有效行</span>;
          }
          const validPercent = Math.round((record.valid_rows / record.total_rows) * 100);
          return (
            <div className="quality-cell">
              <Progress percent={validPercent} size="small" status={record.status === "failed" ? "exception" : "success"} />
              <span>{record.valid_rows} 条可用 / {record.invalid_rows} 条异常</span>
              <span className={record.retrieval_ready ? "index-ready-text" : ""}>
                索引 {record.indexed_rows}/{record.indexable_rows} 条
                {record.pending_index_rows > 0 ? `，${record.pending_index_rows} 条处理中` : ""}
                {record.failed_index_rows > 0 ? `，${record.failed_index_rows} 条失败` : ""}
              </span>
            </div>
          );
        },
      },
      {
        title: "提交时间",
        dataIndex: "created_at",
        key: "created_at",
        width: 130,
        render: formatDate,
      },
      {
        title: "操作",
        key: "actions",
        width: 310,
        fixed: "right",
        render: (_, record) => {
          const canWithdraw = canPlan && ["completed", "failed"].includes(record.status);
          return (
            <Space size={0} wrap>
              <Button
                type="link"
                size="small"
                icon={<EyeOutlined />}
                disabled={record.status !== "completed" || record.total_rows === 0}
                onClick={() => void openImportDetails(record)}
              >
                明细
              </Button>
              <Button
                type="link"
                size="small"
                icon={<FileExcelOutlined />}
                disabled={record.status !== "completed" || record.total_rows === 0}
                loading={actionLoading === `${record.id}:report`}
                onClick={() => void handleQualityReport(record)}
              >
                质量报告
              </Button>
              {record.status === "failed" ? (
                <Button
                  type="link"
                  size="small"
                  icon={<RedoOutlined />}
                  disabled={!canPlan}
                  loading={actionLoading === `${record.id}:retry`}
                  onClick={() => void handleRetry(record)}
                >
                  重试
                </Button>
              ) : null}
              <Popconfirm
                title="撤回该导入批次？"
                description="PostgreSQL 证据、Milvus 向量和原始文件都会被清理，此操作不可恢复。"
                okText="确认撤回"
                cancelText="取消"
                okButtonProps={{ danger: true }}
                disabled={!canWithdraw}
                onConfirm={() => handleWithdraw(record)}
              >
                <Button
                  danger
                  type="link"
                  size="small"
                  icon={<DeleteOutlined />}
                  disabled={!canWithdraw}
                  loading={actionLoading === `${record.id}:withdraw`}
                >
                  撤回
                </Button>
              </Popconfirm>
            </Space>
          );
        },
      },
    ],
    [
      actionLoading,
      canPlan,
      handleQualityReport,
      handleRetry,
      handleWithdraw,
      openImportDetails,
      taskStatuses,
    ],
  );

  const evidenceColumns = useMemo<TableProps<EvidenceRecord>["columns"]>(
    () => [
      {
        title: "行号",
        dataIndex: "source_row",
        key: "source_row",
        width: 72,
      },
      {
        title: "类型 / 品类",
        key: "dimensions",
        width: 160,
        render: (_, record) => (
          <div className="evidence-dimensions">
            <strong>{normalizedValue(record, "data_type")}</strong>
            <span>{normalizedValue(record, "category")}</span>
          </div>
        ),
      },
      {
        title: "内容",
        dataIndex: "content",
        key: "content",
        render: (value: string) => <span className="evidence-content">{value || "-"}</span>,
      },
      {
        title: "质量",
        key: "quality_status",
        width: 190,
        render: (_, record) => {
          const presentation = evidenceQualityPresentation[record.quality_status];
          const issues = qualityIssues(record);
          return (
            <div className="evidence-quality">
              <Tag color={presentation.color}>{presentation.label}</Tag>
              {issues.map((issue) => (
                <span key={`${issue.field}-${issue.code}`}>{issue.message}</span>
              ))}
            </div>
          );
        },
      },
      {
        title: "向量索引",
        key: "index_status",
        width: 140,
        render: (_, record) => {
          const presentation = indexStatusPresentation[record.index_status];
          return <Tag color={presentation.color}>{presentation.label}</Tag>;
        },
      },
      {
        title: "人工审核",
        key: "quality_review",
        width: 180,
        render: (_, record) => (
          <Space size={0} wrap>
            <Button
              type="link"
              size="small"
              disabled={!canPlan || record.quality_status === "verified"}
              onClick={() => openEvidenceReview(record, "verify")}
            >
              确认可用
            </Button>
            <Button
              danger
              type="link"
              size="small"
              disabled={!canPlan || record.quality_status === "blocked"}
              onClick={() => openEvidenceReview(record, "block")}
            >
              标记不可用
            </Button>
          </Space>
        ),
      },
    ],
    [canPlan, openEvidenceReview],
  );

  const reindexableEvidenceCount = selectedImport
    ? selectedImport.pending_index_rows + selectedImport.failed_index_rows
    : 0;
  const completedImportOptions = comparisonImports
    .filter((job) => job.status === "completed")
    .map((job) => ({
      label: `${job.filename} · ${formatDate(job.created_at)}`,
      value: job.id,
    }));
  const duplicateColumns = useMemo<TableProps<DataDuplicateGroupSummary>["columns"]>(
    () => [
      {
        title: "重复类型",
        dataIndex: "match_type",
        key: "match_type",
        width: 120,
        render: (value: DataDuplicateGroupSummary["match_type"]) => (
          <Tag color={value === "source_id" ? "warning" : "purple"}>
            {value === "source_id" ? "来源ID冲突" : "内容完全相同"}
          </Tag>
        ),
      },
      {
        title: "候选记录",
        key: "records",
        render: (_, record) => (
          <div className="duplicate-record-summary">
            {record.records.slice(0, 2).map((item) => (
              <span key={item.evidence_id}>
                <strong>{item.source_id}</strong>
                {item.source_name} · 第 {item.source_row} 行
              </span>
            ))}
            {record.record_count > record.records.length ? (
              <small>另有 {record.record_count - record.records.length} 条</small>
            ) : null}
          </div>
        ),
      },
      {
        title: "记录数",
        dataIndex: "record_count",
        key: "record_count",
        width: 90,
      },
      {
        title: "涉及批次",
        dataIndex: "import_count",
        key: "import_count",
        width: 100,
      },
      {
        title: "审核状态",
        key: "review",
        width: 150,
        render: (_, record) => {
          if (!record.review) {
            return <Tag>待审核</Tag>;
          }
          const presentation = duplicateDecisionPresentation[record.review.decision];
          return (
            <div className="duplicate-review-status">
              <Tag color={presentation.color}>{presentation.label}</Tag>
              <span>{formatDate(record.review.reviewed_at)}</span>
            </div>
          );
        },
      },
      {
        title: "操作",
        key: "action",
        width: 90,
        render: (_, record) => (
          <Button
            type="link"
            disabled={!canPlan}
            onClick={() => openDuplicateReview(record)}
          >
            {record.review ? "修改" : "审核"}
          </Button>
        ),
      },
    ],
    [canPlan, openDuplicateReview],
  );

  return (
    <section className="panel data-import-panel" id="data-import-panel">
      {contextHolder}
      <div className="panel-header">
        <div>
          <h2 className="panel-title">企业数据导入</h2>
          <p className="panel-description">表格、PDF、PPT、文档和图片经解析/OCR后写入 PostgreSQL，并异步生成 Milvus 证据索引</p>
        </div>
        <Space wrap>
          <Button icon={<BarChartOutlined />} onClick={() => void openGovernanceAnalysis()}>
            数据治理分析
          </Button>
          <Button
            icon={<DownloadOutlined />}
            onClick={() => void handleTemplateDownload()}
            loading={downloading}
          >
            下载采集模板
          </Button>
          <Button icon={<ReloadOutlined />} onClick={() => void refresh()} loading={loading}>
            刷新
          </Button>
        </Space>
      </div>

      <div className="import-quality-overview">
        <div>
          <span>导入批次</span>
          <strong>{qualitySummary?.total_imports ?? "-"}</strong>
          <small>{qualitySummary?.completed_imports ?? 0} 个已完成</small>
        </div>
        <div>
          <span>可用证据</span>
          <strong>
            {qualitySummary
              ? qualitySummary.verified_records + qualitySummary.warning_records
              : "-"}
          </strong>
          <small>{qualitySummary?.warning_records ?? 0} 条需要注意</small>
        </div>
        <div>
          <span>阻断记录</span>
          <strong>{qualitySummary?.blocked_records ?? "-"}</strong>
          <small>不会写入检索索引</small>
        </div>
        <div>
          <span>Milvus 已索引</span>
          <strong>{qualitySummary?.indexed_records ?? "-"}</strong>
          <small>{qualitySummary?.failed_index_records ?? 0} 条索引失败</small>
        </div>
      </div>

      <div className="data-import-grid">
        <Upload.Dragger
          {...uploadProps}
          disabled={uploading || !canPlan}
          className="import-dragger"
        >
          <p className="ant-upload-drag-icon"><InboxOutlined /></p>
          <p className="ant-upload-text">拖入业务数据文件，或点击选择</p>
          <p className="ant-upload-hint">支持 CSV、XLSX、XLSM、PDF、PPTX、DOCX 和常见图片，单文件最大 50 MB</p>
          <Button
            type="primary"
            loading={uploading}
            disabled={!canPlan}
            title={identityState.status === "ready" && !canPlan ? "需要规划人员或管理员角色" : undefined}
          >
            {identityState.status === "ready" && !canPlan ? "只读模式" : "选择文件"}
          </Button>
        </Upload.Dragger>

        <div className="import-summary">
          <div className="summary-icon"><CheckCircleOutlined /></div>
          <div>
            <strong>自动质量校验</strong>
            <p>按统一37字段识别必填项、枚举、日期和文本长度，并保留来源行号。</p>
          </div>
          <div>
            <strong>异步证据索引</strong>
            <p>Celery 调用 BGE-M3 生成向量，写入 Milvus 后供 Research Agent 检索与引用。</p>
          </div>
        </div>
      </div>

      <div className="import-filter-toolbar">
        <Select<"all" | DataImportJob["status"]>
          value={importStatusFilter}
          onChange={(value) => {
            setCurrentImportPage(1);
            setImportStatusFilter(value);
          }}
          options={[
            { value: "all", label: `全部状态（${importPageSummary.total}）` },
            { value: "queued", label: `等待处理（${importPageSummary.queued}）` },
            { value: "processing", label: `解析中（${importPageSummary.processing}）` },
            { value: "completed", label: `已完成（${importPageSummary.completed}）` },
            { value: "failed", label: `失败（${importPageSummary.failed}）` },
          ]}
        />
        <Input.Search
          value={importKeywordInput}
          allowClear
          enterButton={<SearchOutlined />}
          placeholder="搜索文件名、批次或创建人"
          onChange={(event) => setImportKeywordInput(event.target.value)}
          onSearch={(value) => {
            setCurrentImportPage(1);
            setImportKeyword(value.trim());
          }}
          className="import-keyword-search"
        />
        <span>当前显示 {imports.length} / {importTotal} 个批次</span>
      </div>

      <Table<DataImportJob>
        className="import-table"
        rowKey="id"
        columns={columns}
        dataSource={imports}
        loading={loading}
        pagination={{
          current: effectiveImportPage,
          pageSize: importPageSize,
          total: importTotal,
          hideOnSinglePage: true,
          onChange: setCurrentImportPage,
        }}
        rowClassName={(job) => (job.id === focusedImportId ? "import-row-focused" : "")}
        locale={{ emptyText: <Empty description="还没有导入任务" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
        scroll={{ x: 1120 }}
      />

      <Drawer
        title={selectedImport ? `数据质量明细｜${selectedImport.filename}` : "数据质量明细"}
        size="min(1080px, 94vw)"
        open={selectedImport !== null}
        onClose={() => setSelectedImport(null)}
        extra={
          <Button
            icon={<SyncOutlined />}
            disabled={!canPlan || reindexableEvidenceCount === 0}
            loading={
              selectedImport !== null && actionLoading === `${selectedImport.id}:reindex`
            }
            onClick={() => void handleReindex()}
          >
            重建失败索引（{reindexableEvidenceCount}）
          </Button>
        }
      >
        {selectedImport ? (
          <>
            <div className="import-detail-summary">
              <div>
                <span>总记录</span>
                <strong>{issueSummary?.total_records ?? selectedImport.total_rows}</strong>
              </div>
              <div>
                <span>质量通过</span>
                <strong>{issueSummary?.verified_records ?? selectedImport.valid_rows}</strong>
              </div>
              <div>
                <span>需要注意</span>
                <strong>{issueSummary?.warning_records ?? "-"}</strong>
              </div>
              <div>
                <span>阻断记录</span>
                <strong>{issueSummary?.blocked_records ?? selectedImport.invalid_rows}</strong>
              </div>
              <div>
                <span>Milvus 已索引</span>
                <strong>{selectedImport.indexed_rows}</strong>
              </div>
              <div>
                <span>检索状态</span>
                <strong className={`retrieval-status-${selectedImport.retrieval_status}`}>
                  {retrievalStatusPresentation[selectedImport.retrieval_status].label}
                </strong>
              </div>
              <p>
                {selectedImport.retrieval_ready
                  ? "当前批次已具备完整检索能力。"
                  : `索引 ${selectedImport.indexed_rows}/${selectedImport.indexable_rows} 条；明细支持按质量状态、索引状态、关键词和页码定位记录。`}
              </p>
            </div>
            {issueSummary && issueSummary.issues.length > 0 ? (
              <Alert
                type="warning"
                showIcon
                message={`发现 ${issueSummary.issues.length} 类质量问题，共 ${issueSummary.warning_records + issueSummary.blocked_records} 条需要处理`}
                description={
                  <Space wrap size={[6, 6]}>
                    {issueSummary.issues.slice(0, 6).map((issue) => (
                      <Tag key={`${issue.field}-${issue.code}`}>
                        {issue.message} · {issue.count}
                      </Tag>
                    ))}
                  </Space>
                }
                className="import-issues-alert"
              />
            ) : null}
            <div className="evidence-filter-toolbar">
              <Input.Search
                value={evidenceKeywordInput}
                allowClear
                enterButton={<SearchOutlined />}
                placeholder="搜索内容、来源ID或文件名"
                onChange={(event) => setEvidenceKeywordInput(event.target.value)}
                onSearch={(value) => {
                  setEvidencePage(1);
                  setEvidenceKeyword(value.trim());
                }}
                className="evidence-keyword-search"
              />
              <Select<"all" | EvidenceQualityStatus>
                value={evidenceQualityFilter}
                onChange={(value) => {
                  setEvidencePage(1);
                  setEvidenceQualityFilter(value);
                }}
                options={[
                  { value: "all", label: `全部质量（${issueSummary?.total_records ?? selectedImport.total_rows}）` },
                  { value: "verified", label: `质量通过（${issueSummary?.verified_records ?? "-"}）` },
                  { value: "warning", label: `需要注意（${issueSummary?.warning_records ?? "-"}）` },
                  { value: "blocked", label: `不可用（${issueSummary?.blocked_records ?? "-"}）` },
                ]}
              />
              <Select<"all" | EvidenceIndexStatus>
                value={evidenceIndexFilter}
                onChange={(value) => {
                  setEvidencePage(1);
                  setEvidenceIndexFilter(value);
                }}
                options={[
                  { value: "all", label: "全部索引状态" },
                  { value: "pending", label: "等待索引" },
                  { value: "indexing", label: "正在索引" },
                  { value: "indexed", label: "已写入 Milvus" },
                  { value: "failed", label: `索引失败（${issueSummary?.failed_index_records ?? "-"}）` },
                ]}
              />
              {evidenceKeyword || evidenceQualityFilter !== "all" || evidenceIndexFilter !== "all" ? (
                <Button
                  onClick={() => {
                    setEvidenceKeyword("");
                    setEvidenceKeywordInput("");
                    setEvidencePage(1);
                    setEvidenceQualityFilter("all");
                    setEvidenceIndexFilter("all");
                  }}
                >
                  清除筛选
                </Button>
              ) : null}
              <span>当前显示 {evidence.length} / {evidenceTotal} 条</span>
            </div>
          </>
        ) : null}
        <Table<EvidenceRecord>
          rowKey="id"
          columns={evidenceColumns}
          dataSource={evidence}
          loading={detailsLoading}
          pagination={{
            current: evidencePage,
            pageSize: evidencePageSize,
            total: evidenceTotal,
            hideOnSinglePage: true,
            onChange: (page) => setEvidencePage(page),
          }}
          locale={{ emptyText: <Empty description="暂无记录明细" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
          scroll={{ x: 1080 }}
        />
      </Drawer>

      <Modal
        title={evidenceReviewAction === "verify" ? "确认该证据可用" : "标记该证据不可用"}
        open={reviewingEvidence !== null}
        okText="提交审核"
        cancelText="取消"
        confirmLoading={evidenceReviewSubmitting}
        okButtonProps={evidenceReviewAction === "block" ? { danger: true } : undefined}
        onOk={() => void handleEvidenceReview()}
        onCancel={() => {
          setReviewingEvidence(null);
          setEvidenceReviewNote("");
        }}
      >
        {reviewingEvidence ? (
          <Space direction="vertical" size="middle" style={{ width: "100%" }}>
            <Alert
              type={evidenceReviewAction === "block" ? "warning" : "info"}
              message={`第 ${reviewingEvidence.source_row} 行 · ${reviewingEvidence.source_id || "无来源 ID"}`}
              description={reviewingEvidence.content || "当前记录没有可展示的内容"}
            />
            <Input.TextArea
              value={evidenceReviewNote}
              onChange={(event) => setEvidenceReviewNote(event.target.value)}
              rows={4}
              maxLength={1000}
              showCount
              placeholder={
                evidenceReviewAction === "block"
                  ? "请填写标记不可用的原因"
                  : "审核说明（可选）"
              }
            />
          </Space>
        ) : null}
      </Modal>

      <Drawer
        title="数据治理分析"
        size="min(1180px, 96vw)"
        open={governanceOpen}
        loading={governanceLoading}
        onClose={() => setGovernanceOpen(false)}
      >
        {coverage ? (
          <>
            <div className="governance-overview">
              <div>
                <span>来源ID覆盖率</span>
                <strong>{formatPercent(coverage.source_id_coverage_rate)}</strong>
                <Progress percent={Math.round(coverage.source_id_coverage_rate * 100)} showInfo={false} />
              </div>
              <div>
                <span>日期覆盖率</span>
                <strong>{formatPercent(coverage.date_coverage_rate)}</strong>
                <Progress percent={Math.round(coverage.date_coverage_rate * 100)} showInfo={false} />
              </div>
              <div>
                <span>数据类型</span>
                <strong>{Object.keys(coverage.data_type_counts).length}</strong>
                <small>当前已覆盖的业务主题</small>
              </div>
              <div>
                <span>重复候选组</span>
                <strong>{duplicateSummary.total}</strong>
                <small>
                  {duplicateSummary.reviewed} 组已审核 · {duplicateSummary.pending} 组待审核
                </small>
              </div>
            </div>

            <div className="coverage-dimensions">
              <div>
                <h3>数据类型覆盖</h3>
                <div className="dimension-tags">
                  {dimensionEntries(coverage.data_type_counts).map((item) => (
                    <Tag key={item.label}>{item.label} · {item.value}</Tag>
                  ))}
                </div>
              </div>
              <div>
                <h3>品类覆盖</h3>
                <div className="dimension-tags">
                  {dimensionEntries(coverage.category_counts).map((item) => (
                    <Tag key={item.label}>{item.label} · {item.value}</Tag>
                  ))}
                </div>
              </div>
              <div>
                <h3>市场覆盖</h3>
                <div className="dimension-tags">
                  {dimensionEntries(coverage.target_market_counts).map((item) => (
                    <Tag key={item.label}>{item.label} · {item.value}</Tag>
                  ))}
                </div>
              </div>
            </div>

            <Divider titlePlacement="start">重复数据候选</Divider>
            <Alert
              type="info"
              showIcon
              message="审核结果会持久化并写入审计日志；选择主记录后，检索命中同组候选时会优先保留主记录，但不会删除 PostgreSQL 记录或 Milvus 向量。"
              className="governance-alert"
            />
            <div className="duplicate-filter-toolbar">
              <span>显示范围</span>
              <Radio.Group
                value={duplicateFilter}
                optionType="button"
                buttonStyle="solid"
                onChange={(event) => {
                  setDuplicateFilter(event.target.value as "pending" | "all");
                  setDuplicatePage(1);
                }}
                options={[
                  { label: `待审核 ${duplicateSummary.pending}`, value: "pending" },
                  { label: `全部 ${duplicateSummary.total}`, value: "all" },
                ]}
              />
            </div>
            <Table<DataDuplicateGroupSummary>
              rowKey={(record) => `${record.match_type}:${record.match_value}`}
              columns={duplicateColumns}
              dataSource={duplicates}
              loading={duplicateLoading}
              pagination={{
                current: duplicatePage,
                pageSize: duplicatePageSize,
                total: duplicateTotal,
                hideOnSinglePage: true,
                showSizeChanger: false,
                showTotal: (total) => `共 ${total} 组`,
                onChange: setDuplicatePage,
              }}
              locale={{
                emptyText: (
                  <Empty
                    description={duplicateFilter === "pending" ? "当前没有待审核重复候选" : "暂未发现重复候选"}
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                  />
                ),
              }}
              scroll={{ x: 920 }}
            />

            <Divider titlePlacement="start">批次版本对比</Divider>
            <div className="comparison-toolbar">
              <Select
                value={baseImportId}
                options={completedImportOptions}
                placeholder="选择基准批次"
                showSearch
                filterOption={false}
                loading={comparisonSearchLoading}
                onSearch={scheduleComparisonImportSearch}
                onOpenChange={(open) => {
                  if (open) {
                    scheduleComparisonImportSearch("");
                  }
                }}
                onChange={(value) => {
                  setBaseImportId(value);
                  setComparison(null);
                }}
              />
              <Select
                value={targetImportId}
                options={completedImportOptions}
                placeholder="选择目标批次"
                showSearch
                filterOption={false}
                loading={comparisonSearchLoading}
                onSearch={scheduleComparisonImportSearch}
                onOpenChange={(open) => {
                  if (open) {
                    scheduleComparisonImportSearch("");
                  }
                }}
                onChange={(value) => {
                  setTargetImportId(value);
                  setComparison(null);
                }}
              />
              <Button
                type="primary"
                icon={<SearchOutlined />}
                loading={comparisonLoading}
                onClick={() => void handleCompareImports()}
              >
                开始对比
              </Button>
            </div>

            {comparison ? (
              <div className="comparison-result">
                {comparison.base_unkeyed_count || comparison.target_unkeyed_count ? (
                  <Alert
                    type="warning"
                    showIcon
                    message={`有 ${comparison.base_unkeyed_count + comparison.target_unkeyed_count} 条记录未填写稳定来源ID，未参与版本差异计算。`}
                  />
                ) : null}
                <div className="comparison-metrics">
                  <div><span>新增</span><strong>{comparison.added_count}</strong></div>
                  <div><span>删除</span><strong>{comparison.removed_count}</strong></div>
                  <div><span>内容变更</span><strong>{comparison.changed_count}</strong></div>
                  <div><span>保持不变</span><strong>{comparison.unchanged_count}</strong></div>
                </div>
                <div className="comparison-lists">
                  <div>
                    <strong>新增来源ID</strong>
                    <p>{comparison.added_source_ids.join("、") || "无"}</p>
                  </div>
                  <div>
                    <strong>删除来源ID</strong>
                    <p>{comparison.removed_source_ids.join("、") || "无"}</p>
                  </div>
                  <div>
                    <strong>内容变更来源ID</strong>
                    <p>{comparison.changed_source_ids.join("、") || "无"}</p>
                  </div>
                </div>
              </div>
            ) : null}
          </>
        ) : (
          <Empty description="暂无可分析数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        )}
      </Drawer>

      <Modal
        title="审核重复数据候选"
        open={duplicateReviewTarget !== null}
        okText="保存审核结果"
        cancelText="取消"
        confirmLoading={duplicateReviewSubmitting}
        okButtonProps={{ disabled: duplicateDetailLoading || !reviewingDuplicate }}
        onOk={() => void handleDuplicateReview()}
        onCancel={closeDuplicateReview}
      >
        {duplicateDetailLoading && !reviewingDuplicate ? (
          <div className="duplicate-review-loading">
            <Spin />
          </div>
        ) : reviewingDuplicate ? (
          <div className="duplicate-review-form">
            <Alert
              type="info"
              showIcon
              message={
                reviewingDuplicate.match_type === "source_id"
                  ? `来源ID ${reviewingDuplicate.match_value} 对应多条记录`
                  : "发现内容完全相同的多条记录"
              }
            />
            <Radio.Group
              value={duplicateDecision}
              onChange={(event) => {
                const decision = event.target.value as DuplicateReviewDecision;
                setDuplicateDecision(decision);
                if (decision !== "select_canonical") {
                  setCanonicalEvidenceId(undefined);
                }
              }}
            >
              <Space direction="vertical">
                <Radio value="keep_all">全部保留：保留台账记录，检索仍执行内容去重</Radio>
                <Radio value="select_canonical">选择主记录：检索命中同组记录时优先使用主记录</Radio>
                <Radio value="dismissed">无需处理：确认候选不需要进一步治理</Radio>
              </Space>
            </Radio.Group>
            {duplicateDecision === "select_canonical" ? (
              <div className="duplicate-canonical-field">
                <span>主记录</span>
                <Select
                  value={canonicalEvidenceId}
                  placeholder="请选择主记录"
                  options={duplicateReviewRecords.map((record) => ({
                    value: record.evidence_id,
                    label: `${record.source_id}｜${record.source_name} 第 ${record.source_row} 行｜${
                      evidenceQualityPresentation[record.quality_status].label
                    }`,
                  }))}
                  onChange={setCanonicalEvidenceId}
                />
              </div>
            ) : null}
            <div className="duplicate-review-record-list">
              {reviewingDuplicate.items.map((record) => (
                <div
                  key={record.evidence_id}
                  className={record.evidence_id === canonicalEvidenceId ? "selected" : undefined}
                >
                  <strong>{record.source_id}</strong>
                  <span>{record.source_name} · 第 {record.source_row} 行</span>
                  <p>{record.content_preview || "无内容摘要"}</p>
                </div>
              ))}
            </div>
            {reviewingDuplicate.record_count > duplicateRecordPageSize ? (
              <Pagination
                current={duplicateRecordPage}
                pageSize={duplicateRecordPageSize}
                total={reviewingDuplicate.record_count}
                showSizeChanger={false}
                showTotal={(total) => `共 ${total} 条候选记录`}
                onChange={(pageValue) => {
                  if (duplicateReviewTarget) {
                    void loadDuplicateDetailPage(duplicateReviewTarget, pageValue, false);
                  }
                }}
              />
            ) : null}
            <Input.TextArea
              value={duplicateReviewNotes}
              rows={3}
              maxLength={1000}
              showCount
              placeholder="审核说明（可选）"
              onChange={(event) => setDuplicateReviewNotes(event.target.value)}
            />
          </div>
        ) : null}
      </Modal>
    </section>
  );
}
