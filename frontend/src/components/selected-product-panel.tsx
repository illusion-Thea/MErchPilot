/**
 * 文件职责：提供正式选品分页、验证材料和立项入口。
 */

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  EditOutlined,
  ExperimentOutlined,
  EyeOutlined,
  ProductOutlined,
  ReloadOutlined,
  RocketOutlined,
} from "@ant-design/icons";
import {
  Button,
  Drawer,
  Empty,
  Alert,
  Form,
  Input,
  message,
  Modal,
  Pagination,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Timeline,
} from "antd";
import type { TableProps } from "antd";

import { PlanningResultView } from "@/components/planning-result-view";
import {
  BUSINESS_DATA_CHANGED_EVENT,
  notifyBusinessDataChanged,
} from "@/lib/business-events";
import type { AuditEvent } from "@/lib/http/audit";
import {
  getProjectRun,
  listProjectRunEvidencePage,
  type PlanningRunEvidence,
} from "@/lib/http/planning";
import {
  listSelectedProductsPage,
  listSelectedProductTimelinePage,
  SelectedProduct,
  SelectedProductPageSummary,
  SelectedProductStatus,
  updateSelectedProduct,
} from "@/lib/http/selected-products";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { hasAnyRole } from "@/store/identity-slice";
import { setProjectContext } from "@/store/project-context-slice";

/** 定义`statusPresentation`展示映射，集中维护状态文案、颜色或选项。 */
const statusPresentation: Record<SelectedProductStatus, { color: string; label: string }> = {
  selected: { color: "blue", label: "已入选" },
  validating: { color: "processing", label: "落地验证中" },
  ready: { color: "success", label: "可进入立项" },
  initiated: { color: "cyan", label: "已进入立项" },
  launched: { color: "purple", label: "已上市" },
  paused: { color: "warning", label: "暂缓推进" },
  cancelled: { color: "default", label: "已终止" },
};

/** 定义`statusOptions`展示映射，集中维护状态文案、颜色或选项。 */
const statusOptions = Object.entries(statusPresentation).map(([value, item]) => ({
  value,
  label: item.label,
}));

/** 定义`manualStatusOptions`展示映射，集中维护状态文案、颜色或选项。 */
const manualStatusOptions = statusOptions.filter(
  (item) => !["initiated", "launched"].includes(item.value),
);

/** 定义`selectedProductTimelinePageSize`服务端分页每页数量，保持页面负载稳定。 */
const selectedProductTimelinePageSize = 8;
/** 定义`evidencePageSize`服务端分页每页数量，保持页面负载稳定。 */
const evidencePageSize = 8;

/** 把formatMoney相关原始值格式化为页面可读文本。 */
function formatMoney(value?: number): string {
  return value === undefined
    ? "待补充"
    : `¥${value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}`;
}

/** 把formatPercent相关原始值格式化为页面可读文本。 */
function formatPercent(value?: number): string {
  return value === undefined ? "待补充" : `${(value * 100).toFixed(1)}%`;
}

/** 实现`validationPresentation`辅助逻辑，集中处理页面展示或状态转换规则。 */
function validationPresentation(value?: string): { color: string; label: string } {
  if (value === "ready") return { color: "success", label: "验证通过" };
  if (value === "blocked") return { color: "error", label: "验证阻塞" };
  if (value === "partial") return { color: "warning", label: "部分完成" };
  return { color: "warning", label: "仍需验证" };
}

/** 把formatDateTime相关原始值格式化为页面可读文本。 */
function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

/** 发送`focusInitiativeCreate`跨模块定位事件，并在目标模块加载后聚焦具体记录。 */
function focusInitiativeCreate(selectedProductId: string) {
  document
    .getElementById("product-initiative-panel")
    ?.scrollIntoView({ behavior: "smooth", block: "start" });
  window.setTimeout(() => {
    window.dispatchEvent(
      new CustomEvent("merchpilot:focus-initiative-create", {
        detail: { selectedProductId },
      }),
    );
  }, 150);
}

/** 发送`focusValidationWorkspace`跨模块定位事件，让用户直接回到对应验证运行。 */
function focusValidationWorkspace(projectId: string, runId: string) {
  document
    .getElementById("planning-workspace")
    ?.scrollIntoView({ behavior: "smooth", block: "start" });
  window.setTimeout(() => {
    window.dispatchEvent(
      new CustomEvent("merchpilot:focus-planning-project", {
        detail: { projectId, runId },
      }),
    );
  }, 150);
}

/** 定义`RegistryFormValues`数据契约，约束组件属性或接口响应字段。 */
interface RegistryFormValues {
  status: SelectedProductStatus;
  owner_id?: string;
  notes?: string;
}

/** 定义`RegistryFilter`允许的状态或联合类型，避免跨模块使用任意字符串。 */
type RegistryFilter = SelectedProductStatus | "all" | "initiated_or_launched";
/** 定义`RegistryValidationFilter`允许的状态或联合类型，避免跨模块使用任意字符串。 */
type RegistryValidationFilter = "all" | "pending" | "ready" | "blocked";

/** 定义`selectedProductPageSize`服务端分页每页数量，保持页面负载稳定。 */
const selectedProductPageSize = 6;

/** 定义`emptySelectedProductSummary`初始状态，避免加载期间出现空值分支。 */
const emptySelectedProductSummary: SelectedProductPageSummary = {
  total: 0,
  validating: 0,
  ready: 0,
  initiated: 0,
  paused: 0,
};

/** 定义`timelineTitles`模块常量或配置，供当前文件中的多个流程复用。 */
const timelineTitles: Record<string, string> = {
  "selected_product.created": "审批通过，进入正式选品池",
  "selected_product.updated": "推进信息已人工更新",
  "selected_product.validation_synced": "落地验证状态已自动同步",
  "selected_product.initiated": "已转入商品立项",
};

/** 实现`timelineDescription`辅助逻辑，集中处理页面展示或状态转换规则。 */
function timelineDescription(event: AuditEvent): string {
  if (event.action === "selected_product.created") {
    return `入选人：${event.actor_id}`;
  }
  if (event.action === "selected_product.validation_synced") {
    const completionRate = typeof event.detail.completion_rate === "number"
      ? `${event.detail.completion_rate}%`
      : "待统计";
    const validationStatus = event.detail.validation_status === "ready" ? "验证通过" : "仍需验证";
    return `${validationStatus} · 完成度 ${completionRate} · 操作人 ${event.actor_id}`;
  }
  if (event.action === "selected_product.initiated") {
    return `立项编号：${String(event.detail.initiative_id || "已创建")} · 操作人 ${event.actor_id}`;
  }
  const fields = Array.isArray(event.detail.changed_fields)
    ? event.detail.changed_fields.join("、")
    : "推进信息";
  return `更新：${fields} · 操作人 ${event.actor_id}`;
}

/** 管理正式选品、验证材料、状态门禁和商品立项入口。 */
export function SelectedProductPanel() {
  const dispatch = useAppDispatch();
  const [products, setProducts] = useState<SelectedProduct[]>([]);
  const [total, setTotal] = useState(0);
  const [categories, setCategories] = useState<string[]>([]);
  const [summary, setSummary] = useState<SelectedProductPageSummary>(emptySelectedProductSummary);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<string>();
  const [saving, setSaving] = useState(false);
  const [statusFilter, setStatusFilter] = useState<RegistryFilter>("all");
  const [validationFilter, setValidationFilter] = useState<RegistryValidationFilter>("all");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [keyword, setKeyword] = useState("");
  const [focusedProductId, setFocusedProductId] = useState<string>();
  const [currentPage, setCurrentPage] = useState(1);
  const [focusRequestKey, setFocusRequestKey] = useState(0);
  const [editingProduct, setEditingProduct] = useState<SelectedProduct>();
  const [previewProduct, setPreviewProduct] = useState<SelectedProduct>();
  const [previewSnapshot, setPreviewSnapshot] = useState<Record<string, unknown>>();
  const [previewEvidence, setPreviewEvidence] = useState<PlanningRunEvidence[]>([]);
  const [previewEvidencePage, setPreviewEvidencePage] = useState(1);
  const [previewEvidenceTotal, setPreviewEvidenceTotal] = useState(0);
  const [previewEvidenceUnavailableTotal, setPreviewEvidenceUnavailableTotal] = useState(0);
  const [previewEvidenceLoading, setPreviewEvidenceLoading] = useState(false);
  const [previewTimeline, setPreviewTimeline] = useState<AuditEvent[]>([]);
  const [previewTimelinePage, setPreviewTimelinePage] = useState(1);
  const [previewTimelineTotal, setPreviewTimelineTotal] = useState(0);
  const [previewTimelineLoading, setPreviewTimelineLoading] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [form] = Form.useForm<RegistryFormValues>();
  const [messageApi, contextHolder] = message.useMessage();
  const requestRef = useRef(0);
  const focusLookupRef = useRef<string | undefined>(undefined);
  const identityState = useAppSelector((state) => state.identity);
  const projectContextState = useAppSelector((state) => state.projectContext);
  const currentProjectContextId = projectContextState.current?.projectId;
  const currentProjectContextSource = projectContextState.current?.source;
  const projectContextHydrated = projectContextState.hydrated;
  const projectContextRevision = projectContextState.revision;
  const canManage = hasAnyRole(identityState.current, ["admin", "planner"]);

  const loadPage = useCallback(async () => {
    const requestId = requestRef.current + 1;
    requestRef.current = requestId;
    setLoading(true);
    try {
      const result = await listSelectedProductsPage({
        status: statusFilter === "all" ? undefined : statusFilter,
        category: categoryFilter,
        validationStatus: validationFilter,
        keyword,
        projectId: focusLookupRef.current ? undefined : currentProjectContextId,
        page: currentPage,
        pageSize: selectedProductPageSize,
        selectedProductId: focusLookupRef.current,
      });
      if (requestId !== requestRef.current) return;
      setProducts(result.items);
      setTotal(result.total);
      setCategories(result.categories);
      setSummary(result.summary);
      const focusedProduct = focusLookupRef.current
        ? result.items.find((item) => item.id === focusLookupRef.current)
        : undefined;
      if (focusedProduct) {
        dispatch(
          setProjectContext({
            projectId: focusedProduct.project_id,
            projectName: focusedProduct.project_name,
            category: focusedProduct.category,
            targetMarket: focusedProduct.target_market,
            tenantId: focusedProduct.tenant_id,
            source: "selection",
          }),
        );
      }
      focusLookupRef.current = undefined;
      setListError(undefined);
    } catch (error) {
      if (requestId !== requestRef.current) return;
      const message = error instanceof Error ? error.message : "无法加载选品台账";
      setListError(`${message}，当前页面可能不是最新数据`);
      messageApi.error(message);
    } finally {
      if (requestId === requestRef.current) setLoading(false);
    }
  }, [
    categoryFilter,
    currentPage,
    dispatch,
    keyword,
    messageApi,
    currentProjectContextId,
    statusFilter,
    validationFilter,
  ]);

  const refresh = async () => {
    await loadPage();
  };

  useEffect(() => {
    const initialLoad = window.setTimeout(() => void loadPage(), 0);
    const timer = window.setInterval(() => void loadPage(), 8_000);
    window.addEventListener(BUSINESS_DATA_CHANGED_EVENT, loadPage);
    return () => {
      requestRef.current += 1;
      window.clearTimeout(initialLoad);
      window.clearInterval(timer);
      window.removeEventListener(BUSINESS_DATA_CHANGED_EVENT, loadPage);
    };
  }, [focusRequestKey, loadPage]);

  useEffect(() => {
    if (!projectContextHydrated || currentProjectContextSource === "selection") {
      return;
    }
    const contextTimer = window.setTimeout(() => {
      focusLookupRef.current = undefined;
      setCurrentPage(1);
      setStatusFilter("all");
      setValidationFilter("all");
      setCategoryFilter("all");
      setKeyword("");
    }, 0);
    return () => window.clearTimeout(contextTimer);
  }, [currentProjectContextSource, projectContextHydrated, projectContextRevision]);

  useEffect(() => {
    const handleFocusSelectedProducts = (event: Event) => {
      const detail = (event as CustomEvent<{
        validation?: "pending" | "ready";
        status?: RegistryFilter;
        productId?: string;
        projectId?: string;
      }>).detail;
      if (detail?.productId) {
        focusLookupRef.current = detail.productId;
        setFocusRequestKey((current) => current + 1);
        setFocusedProductId(detail.productId);
        setCurrentPage(1);
        setStatusFilter("all");
        setValidationFilter("all");
        setCategoryFilter("all");
        setKeyword("");
        return;
      }
      if (detail?.projectId) {
        focusLookupRef.current = undefined;
        setFocusedProductId(undefined);
        setCurrentPage(1);
        setStatusFilter(detail.status ?? "all");
        setValidationFilter("all");
        setCategoryFilter("all");
        setKeyword("");
        return;
      }
      if (detail?.status) {
        focusLookupRef.current = undefined;
        setCurrentPage(1);
        setStatusFilter(detail.status);
        setValidationFilter("all");
        setCategoryFilter("all");
        setKeyword("");
        return;
      }
      if (detail?.validation === "pending") {
        focusLookupRef.current = undefined;
        setCurrentPage(1);
        setStatusFilter("all");
        setValidationFilter("pending");
        setCategoryFilter("all");
        setKeyword("");
      }
      if (detail?.validation === "ready") {
        focusLookupRef.current = undefined;
        setCurrentPage(1);
        setStatusFilter("ready");
        setValidationFilter("ready");
        setCategoryFilter("all");
        setKeyword("");
      }
    };
    window.addEventListener("merchpilot:focus-selected-products", handleFocusSelectedProducts);
    return () =>
      window.removeEventListener("merchpilot:focus-selected-products", handleFocusSelectedProducts);
  }, []);

  const categoryOptions = useMemo(() => {
    return [
      { value: "all", label: "全部品类" },
      ...categories.map((category) => ({ value: category, label: category })),
    ];
  }, [categories]);

  const currentPageCount = Math.max(1, Math.ceil(total / selectedProductPageSize));
  const effectiveCurrentPage = Math.min(currentPage, currentPageCount);

  useEffect(() => {
    if (!focusedProductId || !products.some((product) => product.id === focusedProductId)) {
      return;
    }
    const scrollTimer = window.setTimeout(() => {
      const row = [...document.querySelectorAll<HTMLElement>("tr[data-row-key]")].find(
        (item) => item.getAttribute("data-row-key") === focusedProductId,
      );
      row?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 100);
    const clearTimer = window.setTimeout(() => setFocusedProductId(undefined), 6_000);
    return () => {
      window.clearTimeout(scrollTimer);
      window.clearTimeout(clearTimer);
    };
  }, [effectiveCurrentPage, focusedProductId, products]);

  const openEditor = (product: SelectedProduct) => {
    dispatch(
      setProjectContext({
        projectId: product.project_id,
        projectName: product.project_name,
        category: product.category,
        targetMarket: product.target_market,
        tenantId: product.tenant_id,
        source: "selection",
      }),
    );
    form.setFieldsValue({
      status: product.status,
      owner_id: product.owner_id,
      notes: product.notes,
    });
    setEditingProduct(product);
  };

  /** 把正式选品的待验证状态交给规划工作台继续处理，避免用户手动查找运行记录。 */
  const openValidationWorkspace = (product: SelectedProduct) => {
    dispatch(
      setProjectContext({
        projectId: product.project_id,
        projectName: product.project_name,
        category: product.category,
        targetMarket: product.target_market,
        tenantId: product.tenant_id,
        source: "planning",
      }),
    );
    focusValidationWorkspace(product.project_id, product.run_id);
  };

  const openPreview = async (product: SelectedProduct) => {
    dispatch(
      setProjectContext({
        projectId: product.project_id,
        projectName: product.project_name,
        category: product.category,
        targetMarket: product.target_market,
        tenantId: product.tenant_id,
        source: "selection",
      }),
    );
    setPreviewProduct(product);
    setPreviewSnapshot(product.selection_snapshot);
    setPreviewEvidence([]);
    setPreviewEvidencePage(1);
    setPreviewEvidenceTotal(0);
    setPreviewEvidenceUnavailableTotal(0);
    setPreviewEvidenceLoading(true);
    setPreviewTimeline([]);
    setPreviewTimelinePage(1);
    setPreviewTimelineTotal(0);
    setPreviewLoading(true);
    const [runResult, evidenceResult, timelineResult] = await Promise.allSettled([
      getProjectRun(product.project_id, product.run_id),
      listProjectRunEvidencePage(product.project_id, product.run_id, 1, evidencePageSize),
      listSelectedProductTimelinePage(product.id, 1, selectedProductTimelinePageSize),
    ]);
    if (runResult.status === "fulfilled") {
      setPreviewSnapshot(runResult.value.result_snapshot || product.selection_snapshot);
    }
    if (evidenceResult.status === "fulfilled") {
      setPreviewEvidence(evidenceResult.value.items);
      setPreviewEvidenceTotal(evidenceResult.value.total);
      setPreviewEvidenceUnavailableTotal(evidenceResult.value.unavailable_total);
    }
    if (timelineResult.status === "fulfilled") {
      setPreviewTimeline(timelineResult.value.items);
      setPreviewTimelinePage(timelineResult.value.page);
      setPreviewTimelineTotal(timelineResult.value.total);
    }
    if ([runResult, evidenceResult, timelineResult].some((result) => result.status === "rejected")) {
      messageApi.warning("部分最新信息加载失败，已展示可用的决策快照");
    }
    setPreviewEvidenceLoading(false);
    setPreviewLoading(false);
  };

  const loadPreviewEvidencePage = async (pageValue: number) => {
    if (!previewProduct) return;
    setPreviewEvidenceLoading(true);
    try {
      const result = await listProjectRunEvidencePage(
        previewProduct.project_id,
        previewProduct.run_id,
        pageValue,
        evidencePageSize,
      );
      setPreviewEvidence(result.items);
      setPreviewEvidencePage(result.page);
      setPreviewEvidenceTotal(result.total);
      setPreviewEvidenceUnavailableTotal(result.unavailable_total);
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "无法加载证据详情");
    } finally {
      setPreviewEvidenceLoading(false);
    }
  };

  const loadPreviewTimelinePage = async (pageValue: number) => {
    if (!previewProduct) return;
    setPreviewTimelineLoading(true);
    try {
      const result = await listSelectedProductTimelinePage(
        previewProduct.id,
        pageValue,
        selectedProductTimelinePageSize,
      );
      setPreviewTimeline(result.items);
      setPreviewTimelinePage(result.page);
      setPreviewTimelineTotal(result.total);
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "无法加载推进时间线");
    } finally {
      setPreviewTimelineLoading(false);
    }
  };

  const closePreview = () => {
    setPreviewProduct(undefined);
    setPreviewSnapshot(undefined);
    setPreviewEvidence([]);
    setPreviewEvidencePage(1);
    setPreviewEvidenceTotal(0);
    setPreviewEvidenceUnavailableTotal(0);
    setPreviewEvidenceLoading(false);
    setPreviewTimeline([]);
    setPreviewTimelinePage(1);
    setPreviewTimelineTotal(0);
    setPreviewTimelineLoading(false);
  };

  const submitUpdate = async (values: RegistryFormValues) => {
    if (!editingProduct) return;
    setSaving(true);
    try {
      const updated = await updateSelectedProduct(editingProduct.id, {
        status: values.status,
        owner_id: values.owner_id?.trim() || null,
        notes: values.notes?.trim() || null,
      });
      setProducts((current) =>
        current.map((product) => (product.id === updated.id ? updated : product)),
      );
      notifyBusinessDataChanged();
      messageApi.success("选品台账已更新");
      setEditingProduct(undefined);
      form.resetFields();
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "选品台账更新失败");
    } finally {
      setSaving(false);
    }
  };

  const applyOverviewFilter = (
    nextStatus: RegistryFilter,
    nextValidation: RegistryValidationFilter = "all",
  ) => {
    setCurrentPage(1);
    setStatusFilter(nextStatus);
    setValidationFilter(nextValidation);
    setKeyword("");
  };

  const columns: TableProps<SelectedProduct>["columns"] = [
    {
      title: "正式选品",
      key: "product",
      width: 300,
      render: (_, product) => (
        <div className="selected-product-summary">
          <strong>{product.name}</strong>
          <span>{product.project_name} · {product.category} · {product.target_market}</span>
          {product.positioning ? <small>{product.positioning}</small> : null}
        </div>
      ),
    },
    {
      title: "商业测算",
      key: "finance",
      width: 240,
      render: (_, product) => (
        <div className="selected-product-metrics">
          <span>方案分 <strong>{product.score ?? "待评估"}</strong></span>
          <span>售价 <strong>{formatMoney(product.selling_price)}</strong></span>
          <span>毛利率 <strong>{formatPercent(product.margin_rate)}</strong></span>
          <span>预计利润 <strong>{formatMoney(product.estimated_profit)}</strong></span>
        </div>
      ),
    },
    {
      title: "供应与验证",
      key: "validation",
      width: 180,
      render: (_, product) => (
        <div className="selected-product-summary">
          <span>{product.supplier_name || "供应商待确认"}</span>
          <Tag color={validationPresentation(product.validation_status).color}>
            {validationPresentation(product.validation_status).label}
          </Tag>
        </div>
      ),
    },
    {
      title: "推进状态",
      dataIndex: "status",
      key: "status",
      width: 130,
      render: (status: SelectedProductStatus) => {
        const presentation = statusPresentation[status];
        return <Tag color={presentation.color}>{presentation.label}</Tag>;
      },
    },
    {
      title: "负责人",
      dataIndex: "owner_id",
      key: "owner_id",
      width: 130,
      render: (ownerId?: string) => ownerId || "待分配",
    },
    {
      title: "入选时间",
      dataIndex: "selected_at",
      key: "selected_at",
      width: 170,
      render: (value: string) => formatDateTime(value),
    },
    {
      title: "操作",
      key: "actions",
      width: 320,
      fixed: "right",
      render: (_, product) => (
        <Space wrap size={[4, 4]}>
          <Button size="small" icon={<EyeOutlined />} onClick={() => void openPreview(product)}>
            查看
          </Button>
          <Button
            size="small"
            icon={<EditOutlined />}
            disabled={!canManage}
            onClick={() => openEditor(product)}
          >
            更新
          </Button>
          {canManage && ["selected", "validating"].includes(product.status) && product.validation_status !== "ready" ? (
            <Button
              size="small"
              icon={<ExperimentOutlined />}
              onClick={() => openValidationWorkspace(product)}
            >
              进入验证
            </Button>
          ) : null}
          {canManage && product.status === "ready" && product.validation_status === "ready" ? (
            <Button
              size="small"
              type="primary"
              icon={<RocketOutlined />}
              onClick={() => focusInitiativeCreate(product.id)}
            >
              建立立项
            </Button>
          ) : null}
        </Space>
      ),
    },
  ];

  return (
    <section className="panel selected-product-panel" id="selected-product-panel">
      {contextHolder}
      {listError ? (
        <Alert
          type="error"
          showIcon
          message="正式选品台账刷新失败"
          description={listError}
          action={<Button size="small" onClick={() => void refresh()}>重试</Button>}
        />
      ) : null}
      <div className="panel-header">
        <div>
          <h2 className="panel-title"><ProductOutlined /> 正式选品决策池</h2>
          <p className="panel-description">审批通过的候选方案自动沉淀，可持续跟踪验证、立项、暂缓和终止状态</p>
        </div>
        <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void refresh()}>
          刷新
        </Button>
      </div>

      <div className="selected-product-overview">
        <button
          type="button"
          className={`selected-product-overview-card ${statusFilter === "all" && validationFilter === "all" ? "selected-product-overview-card-active" : ""}`}
          aria-pressed={statusFilter === "all" && validationFilter === "all"}
          onClick={() => applyOverviewFilter("all")}
        >
          <span>正式入选</span><strong>{summary.total}</strong><small>审批通过后自动进入台账</small>
        </button>
        <button
          type="button"
          className={`selected-product-overview-card ${validationFilter === "pending" ? "selected-product-overview-card-active" : ""}`}
          aria-pressed={validationFilter === "pending"}
          onClick={() => applyOverviewFilter("all", "pending")}
        >
          <span>待处理验证</span><strong>{summary.validating}</strong><small>样品、成本与供应仍在验证</small>
        </button>
        <button
          type="button"
          className={`selected-product-overview-card ${statusFilter === "ready" && validationFilter === "all" ? "selected-product-overview-card-active" : ""}`}
          aria-pressed={statusFilter === "ready" && validationFilter === "all"}
          onClick={() => applyOverviewFilter("ready")}
        >
          <span>可进入立项</span><strong>{summary.ready}</strong><small>已具备下一阶段推进条件</small>
        </button>
        <button
          type="button"
          className={`selected-product-overview-card ${statusFilter === "initiated_or_launched" && validationFilter === "all" ? "selected-product-overview-card-active" : ""}`}
          aria-pressed={statusFilter === "initiated_or_launched" && validationFilter === "all"}
          onClick={() => applyOverviewFilter("initiated_or_launched")}
        >
          <span>立项与上市</span><strong>{summary.initiated}</strong><small>已进入商品开发或上市阶段</small>
        </button>
        <button
          type="button"
          className={`selected-product-overview-card ${statusFilter === "paused" && validationFilter === "all" ? "selected-product-overview-card-active" : ""}`}
          aria-pressed={statusFilter === "paused" && validationFilter === "all"}
          onClick={() => applyOverviewFilter("paused")}
        >
          <span>暂缓方案</span><strong>{summary.paused}</strong><small>保留决策快照，后续可恢复</small>
        </button>
      </div>

      <div className="selected-product-toolbar">
        <Select
          value={statusFilter}
          onChange={(value: RegistryFilter) => {
            setCurrentPage(1);
            setStatusFilter(value);
          }}
          options={[
            { value: "all", label: "全部状态" },
            ...statusOptions,
            { value: "initiated_or_launched", label: "立项与上市" },
          ]}
        />
        <Select
          value={validationFilter}
          onChange={(value: RegistryValidationFilter) => {
            setCurrentPage(1);
            setValidationFilter(value);
          }}
          options={[
            { value: "all", label: "全部验证状态" },
            { value: "pending", label: "待处理验证" },
            { value: "ready", label: "验证已通过" },
            { value: "blocked", label: "验证阻塞" },
          ]}
        />
        <Select
          value={categoryFilter}
          onChange={(value: string) => {
            setCurrentPage(1);
            setCategoryFilter(value);
          }}
          options={categoryOptions}
          showSearch
          optionFilterProp="label"
        />
        <Input.Search
          allowClear
          value={keyword}
          placeholder="搜索商品、项目、品类或负责人"
          onChange={(event) => {
            setCurrentPage(1);
            setKeyword(event.target.value);
          }}
        />
        <span>当前显示 {products.length} / {total} 个正式选品方案</span>
      </div>

      <Table<SelectedProduct>
        rowKey="id"
        columns={columns}
        dataSource={products}
        loading={loading}
        pagination={{
          current: effectiveCurrentPage,
          pageSize: selectedProductPageSize,
          total,
          hideOnSinglePage: true,
          onChange: setCurrentPage,
        }}
        scroll={{ x: 1450 }}
        rowClassName={(product) => (
          product.id === focusedProductId ? "selected-product-row-focused" : ""
        )}
      />

      <Modal
        title="更新选品推进状态"
        open={Boolean(editingProduct)}
        onCancel={() => {
          setEditingProduct(undefined);
          form.resetFields();
        }}
        onOk={() => form.submit()}
        okText="保存更新"
        confirmLoading={saving}
      >
        <Form form={form} layout="vertical" onFinish={(values) => void submitUpdate(values)}>
          <Form.Item name="status" label="推进状态" rules={[{ required: true }]}>
            <Select
              options={editingProduct && ["initiated", "launched"].includes(editingProduct.status)
                ? [{ value: editingProduct.status, label: statusPresentation[editingProduct.status].label }]
                : manualStatusOptions}
            />
          </Form.Item>
          <Form.Item name="owner_id" label="业务负责人">
            <Input placeholder="例如：product-owner-li" maxLength={64} />
          </Form.Item>
          <Form.Item name="notes" label="推进备注">
            <Input.TextArea rows={4} maxLength={2000} showCount placeholder="记录样品、供应、成本或立项进展" />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        title={previewProduct ? `${previewProduct.name} · 决策快照` : "选品决策快照"}
        size="min(1180px, 96vw)"
        open={Boolean(previewProduct)}
        onClose={closePreview}
      >
        {previewProduct ? (
          <Spin spinning={previewLoading} tip="正在读取最新推进信息">
            <div className="selected-product-timeline">
              <h3>推进时间线</h3>
              <Spin spinning={previewTimelineLoading}>
                {previewTimeline.length ? (
                  <Timeline
                    items={previewTimeline.map((event) => ({
                      color: event.action === "selected_product.validation_synced" ? "green" : "blue",
                      children: (
                        <div className="selected-product-timeline-item">
                          <strong>{timelineTitles[event.action] || "选品信息已更新"}</strong>
                          <span>{timelineDescription(event)}</span>
                          <small>{formatDateTime(event.occurred_at)}</small>
                        </div>
                      ),
                    }))}
                  />
                ) : (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无推进记录" />
                )}
              </Spin>
              {previewTimelineTotal > selectedProductTimelinePageSize ? (
                <Pagination
                  current={previewTimelinePage}
                  pageSize={selectedProductTimelinePageSize}
                  total={previewTimelineTotal}
                  showSizeChanger={false}
                  showTotal={(total) => `共 ${total} 条推进记录`}
                  onChange={(pageValue) => void loadPreviewTimelinePage(pageValue)}
                />
              ) : null}
            </div>
            <PlanningResultView
              snapshot={previewSnapshot}
              evidence={previewEvidence}
              evidenceLoading={previewEvidenceLoading}
              evidencePage={previewEvidencePage}
              evidencePageSize={evidencePageSize}
              evidenceTotal={previewEvidenceTotal}
              evidenceUnavailableTotal={previewEvidenceUnavailableTotal}
              onEvidencePageChange={(pageValue) => void loadPreviewEvidencePage(pageValue)}
              projectName={previewProduct.project_name}
              category={previewProduct.category}
              targetMarket={previewProduct.target_market}
              approvalStatus="approved"
              selectedProductStatus={previewProduct.status}
              selectedProductValidationStatus={previewProduct.validation_status}
              initiativeStatus={
                previewProduct.status === "launched"
                  ? "launched"
                  : previewProduct.status === "initiated"
                    ? "in_progress"
                    : undefined
              }
            />
          </Spin>
        ) : null}
      </Drawer>
    </section>
  );
}
