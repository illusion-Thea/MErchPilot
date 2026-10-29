/**
 * 文件职责：提供商品立项、里程碑、试销和上市闭环工作台。
 */

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import {
  CheckCircleOutlined,
  EditOutlined,
  EyeOutlined,
  FileDoneOutlined,
  PlusOutlined,
  ReloadOutlined,
  RocketOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  message,
  Modal,
  Pagination,
  Progress,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Timeline,
} from "antd";
import type { TableProps } from "antd";

import type { AuditEvent } from "@/lib/http/audit";
import {
  BUSINESS_DATA_CHANGED_EVENT,
  notifyBusinessDataChanged,
} from "@/lib/business-events";
import {
  createProductInitiative,
  createPilotSale,
  getPilotSalesSummary,
  listPilotSalesPage,
  listProductInitiativesPage,
  listProductInitiativeTimelinePage,
  ProductInitiative,
  ProductInitiativePageSummary,
  ProductInitiativeStatus,
  ProductMilestone,
  ProductMilestoneStatus,
  PilotSaleRecord,
  PilotSaleSummary,
  PilotSaleTrend,
  ProductLaunchReadiness,
  ProductLaunchReview,
  ProductLaunchReviewStatus,
  decideProductLaunchReview,
  getProductInitiative,
  getProductLaunchReadiness,
  getPilotSalesTrend,
  listTenantProductLaunchReviewsPage,
  submitProductLaunchReview,
  updatePilotSale,
  updateProductInitiative,
  updateProductMilestone,
} from "@/lib/http/product-initiatives";
import { listSelectedProductsPage, SelectedProduct } from "@/lib/http/selected-products";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { hasAnyRole } from "@/store/identity-slice";
import { setProjectContext } from "@/store/project-context-slice";

/** 定义`statusPresentation`展示映射，集中维护状态文案、颜色或选项。 */
const statusPresentation: Record<ProductInitiativeStatus, { color: string; label: string }> = {
  in_progress: { color: "processing", label: "立项推进中" },
  launch_ready: { color: "success", label: "可确认上市" },
  launched: { color: "purple", label: "已上市" },
  paused: { color: "warning", label: "已暂停" },
  cancelled: { color: "default", label: "已取消" },
};

/** 定义`milestonePresentation`展示映射，集中维护状态文案、颜色或选项。 */
const milestonePresentation: Record<ProductMilestoneStatus, { color: string; label: string }> = {
  pending: { color: "default", label: "待开始" },
  in_progress: { color: "processing", label: "进行中" },
  completed: { color: "success", label: "已完成" },
  blocked: { color: "error", label: "受阻" },
};

/** 定义`milestoneOptions`展示映射，集中维护状态文案、颜色或选项。 */
const milestoneOptions = Object.entries(milestonePresentation).map(([value, item]) => ({
  value,
  label: item.label,
}));

/** 定义`readinessPresentation`展示映射，集中维护状态文案、颜色或选项。 */
const readinessPresentation = {
  ready: { color: "success", label: "可确认上市" },
  review: { color: "warning", label: "待人工复核" },
  blocked: { color: "error", label: "暂不能上市" },
} as const;

/** 定义`readinessCheckPresentation`展示映射，集中维护状态文案、颜色或选项。 */
const readinessCheckPresentation = {
  passed: { color: "success", label: "已满足" },
  pending: { color: "default", label: "待处理" },
  warning: { color: "warning", label: "需复核" },
  blocked: { color: "error", label: "阻断" },
} as const;

/** 定义`launchReviewPresentation`展示映射，集中维护状态文案、颜色或选项。 */
const launchReviewPresentation: Record<ProductLaunchReviewStatus, { color: string; label: string }> = {
  pending: { color: "processing", label: "待审批" },
  approved: { color: "success", label: "已通过" },
  revision_required: { color: "warning", label: "退回修订" },
  rejected: { color: "error", label: "已驳回" },
};

/** 定义`initiativePageSize`服务端分页每页数量，保持页面负载稳定。 */
const initiativePageSize = 6;
/** 定义`pilotSalePageSize`服务端分页每页数量，保持页面负载稳定。 */
const pilotSalePageSize = 5;
/** 定义`timelinePageSize`服务端分页每页数量，保持页面负载稳定。 */
const timelinePageSize = 8;
/** 定义`launchReviewPageSize`服务端分页每页数量，保持页面负载稳定。 */
const launchReviewPageSize = 5;
/** 定义`emptyInitiativeSummary`初始状态，避免加载期间出现空值分支。 */
const emptyInitiativeSummary: ProductInitiativePageSummary = {
  total: 0,
  active: 0,
  attention: 0,
  ready: 0,
  launched: 0,
};

/** 定义`Line`模块常量或配置，供当前文件中的多个流程复用。 */
const Line = dynamic(() => import("@ant-design/charts").then((module) => module.Line), {
  ssr: false,
});

/** 定义`CreateFormValues`数据契约，约束组件属性或接口响应字段。 */
interface CreateFormValues {
  selected_product_id: string;
  owner_id?: string;
  target_launch_date?: string;
  budget?: number;
  notes?: string;
}

/** 定义`InitiativeEditFormValues`数据契约，约束组件属性或接口响应字段。 */
interface InitiativeEditFormValues {
  owner_id?: string;
  target_launch_date?: string;
  budget?: number;
  notes?: string;
}

/** 定义`LaunchReviewSubmitFormValues`数据契约，约束组件属性或接口响应字段。 */
interface LaunchReviewSubmitFormValues {
  submission_note?: string;
}

/** 定义`LaunchReviewDecisionFormValues`数据契约，约束组件属性或接口响应字段。 */
interface LaunchReviewDecisionFormValues {
  decision_note: string;
}

/** 定义`MilestoneFormValues`数据契约，约束组件属性或接口响应字段。 */
interface MilestoneFormValues {
  status: ProductMilestoneStatus;
  owner_id?: string;
  due_date?: string;
  note?: string;
}

/** 定义`PilotSaleFormValues`数据契约，约束组件属性或接口响应字段。 */
interface PilotSaleFormValues {
  period_start: string;
  period_end: string;
  channel: string;
  visitors: number;
  orders: number;
  units_sold: number;
  revenue: number;
  product_cost: number;
  marketing_spend: number;
  refunds_amount: number;
  return_count: number;
  rating?: number;
  notes?: string;
}

/** 定义`InitiativeFilter`允许的状态或联合类型，避免跨模块使用任意字符串。 */
type InitiativeFilter = "all" | ProductInitiativeStatus | "needs_attention";

/** 把formatDate相关原始值格式化为页面可读文本。 */
function formatDate(value?: string): string {
  if (!value) return "待确定";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(value));
}

/** 把formatMoney相关原始值格式化为页面可读文本。 */
function formatMoney(value?: number): string {
  return value === undefined
    ? "待确定"
    : `¥${value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}`;
}

/** 实现`progressOf`辅助逻辑，集中处理页面展示或状态转换规则。 */
function progressOf(initiative: ProductInitiative): number {
  if (!initiative.milestones.length) return 0;
  const completed = initiative.milestones.filter((item) => item.status === "completed").length;
  return Math.round((completed / initiative.milestones.length) * 100);
}

/** 实现`currentMilestone`辅助逻辑，集中处理页面展示或状态转换规则。 */
function currentMilestone(initiative: ProductInitiative): ProductMilestone | undefined {
  return initiative.milestones.find((item) => item.status === "blocked")
    ?? initiative.milestones.find((item) => item.status === "in_progress")
    ?? initiative.milestones.find((item) => item.status === "pending")
    ?? initiative.milestones.at(-1);
}

/** 判断`isOverdue`条件是否成立，供页面状态和操作权限复用。 */
function isOverdue(value?: string): boolean {
  if (!value) return false;
  const dueAt = new Date(value).getTime();
  return !Number.isNaN(dueAt) && dueAt < Date.now();
}

/** 实现`needsAttention`辅助逻辑，集中处理页面展示或状态转换规则。 */
function needsAttention(initiative: ProductInitiative): boolean {
  if (initiative.status === "launch_ready") return true;
  if (initiative.milestones.some((item) => item.status === "blocked")) return true;
  return initiative.status === "in_progress" && initiative.milestones.some(
    (item) => item.status !== "completed" && isOverdue(item.due_date),
  );
}

/** 把formatPercent相关原始值格式化为页面可读文本。 */
function formatPercent(value?: number): string {
  return value === undefined ? "待统计" : `${(value * 100).toFixed(1)}%`;
}

/** 实现`timelineText`辅助逻辑，集中处理页面展示或状态转换规则。 */
function timelineText(event: AuditEvent): string {
  if (event.action === "product_initiative.created") return "商品立项已创建";
  if (event.action === "product_initiative.milestone_updated") {
    return `${String(event.detail.milestone_label || "里程碑")}更新为${
      event.detail.milestone_status === "completed" ? "已完成" : "新状态"
    }`;
  }
  if (event.action === "product_initiative.updated") return "立项信息或状态已更新";
  if (event.action === "product_initiative.launch_review_submitted") return "上市准备评审已提交";
  if (event.action === "product_initiative.launch_review_decided") {
    const action = event.detail.action;
    return action === "approved"
      ? "上市准备评审已通过"
      : action === "revision_required"
        ? "上市准备评审已退回修订"
        : "上市准备评审已驳回";
  }
  if (event.action === "product_initiative.pilot_sale_recorded") return "试销经营数据已录入";
  if (event.action === "product_initiative.pilot_sale_updated") return "试销经营数据已修订";
  return "立项记录已更新";
}

/** 管理商品立项、里程碑、试销、上市评审与最终上市确认。 */
export function ProductInitiativePanel() {
  const dispatch = useAppDispatch();
  const [initiatives, setInitiatives] = useState<ProductInitiative[]>([]);
  const [readyProducts, setReadyProducts] = useState<SelectedProduct[]>([]);
  const [readyProductLoading, setReadyProductLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<string>();
  const [detailLoading, setDetailLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [initiativeFilter, setInitiativeFilter] = useState<InitiativeFilter>("all");
  const [initiativeKeyword, setInitiativeKeyword] = useState("");
  const [initiativePage, setInitiativePage] = useState(1);
  const [initiativeTotal, setInitiativeTotal] = useState(0);
  const [initiativeSummary, setInitiativeSummary] = useState<ProductInitiativePageSummary>(
    emptyInitiativeSummary,
  );
  const [initiativeEditOpen, setInitiativeEditOpen] = useState(false);
  const [detail, setDetail] = useState<ProductInitiative>();
  const [timeline, setTimeline] = useState<AuditEvent[]>([]);
  const [timelinePage, setTimelinePage] = useState(1);
  const [timelineTotal, setTimelineTotal] = useState(0);
  const [editingMilestone, setEditingMilestone] = useState<ProductMilestone>();
  const [pilotSales, setPilotSales] = useState<PilotSaleRecord[]>([]);
  const [pilotSalePage, setPilotSalePage] = useState(1);
  const [pilotSaleTotal, setPilotSaleTotal] = useState(0);
  const [pilotSummary, setPilotSummary] = useState<PilotSaleSummary>();
  const [pilotTrend, setPilotTrend] = useState<PilotSaleTrend>();
  const [launchReadiness, setLaunchReadiness] = useState<ProductLaunchReadiness>();
  const [launchReviews, setLaunchReviews] = useState<ProductLaunchReview[]>([]);
  const [launchReviewPage, setLaunchReviewPage] = useState(1);
  const [launchReviewTotal, setLaunchReviewTotal] = useState(0);
  const [launchReviewPendingTotal, setLaunchReviewPendingTotal] = useState(0);
  const [pilotSaleOpen, setPilotSaleOpen] = useState(false);
  const [editingPilotSale, setEditingPilotSale] = useState<PilotSaleRecord>();
  const [launchReviewSubmitOpen, setLaunchReviewSubmitOpen] = useState(false);
  const [launchReviewDecisionOpen, setLaunchReviewDecisionOpen] = useState(false);
  const [launchReviewDecisionAction, setLaunchReviewDecisionAction] = useState<
    "approved" | "rejected" | "revision_required"
  >("approved");
  const [launchReviewTarget, setLaunchReviewTarget] = useState<ProductLaunchReview>();
  const [createForm] = Form.useForm<CreateFormValues>();
  const [initiativeEditForm] = Form.useForm<InitiativeEditFormValues>();
  const [launchReviewSubmitForm] = Form.useForm<LaunchReviewSubmitFormValues>();
  const [launchReviewDecisionForm] = Form.useForm<LaunchReviewDecisionFormValues>();
  const [milestoneForm] = Form.useForm<MilestoneFormValues>();
  const [pilotSaleForm] = Form.useForm<PilotSaleFormValues>();
  const [messageApi, contextHolder] = message.useMessage();
  const [detailWarnings, setDetailWarnings] = useState<string[]>([]);
  const detailRequestRef = useRef(0);
  const detailPagesRef = useRef({ timeline: 1, pilotSale: 1, launchReview: 1 });
  const detailPageRequestRef = useRef({ timeline: 0, pilotSale: 0, launchReview: 0 });
  const initiativeRequestRef = useRef(0);
  const readyProductRequestRef = useRef(0);
  const readyProductSearchTimerRef = useRef<number | undefined>(undefined);
  const identityState = useAppSelector((state) => state.identity);
  const projectContextState = useAppSelector((state) => state.projectContext);
  const currentProjectContextId = projectContextState.current?.projectId;
  const currentProjectContextSource = projectContextState.current?.source;
  const projectContextHydrated = projectContextState.hydrated;
  const projectContextRevision = projectContextState.revision;
  const canManage = hasAnyRole(identityState.current, ["admin", "planner"]);
  const canReview = hasAnyRole(identityState.current, ["admin", "approver"]);
  const currentDetailId = detail?.id;

  const refreshDetailData = useCallback(async (
    initiativeId: string,
    requestId = detailRequestRef.current,
    showLoading = false,
    pages = detailPagesRef.current,
  ) => {
    if (showLoading) setDetailLoading(true);
    const results = await Promise.allSettled([
      getProductInitiative(initiativeId),
      listProductInitiativeTimelinePage(initiativeId, pages.timeline, timelinePageSize),
      listPilotSalesPage(initiativeId, pages.pilotSale, pilotSalePageSize),
      getPilotSalesSummary(initiativeId),
      getPilotSalesTrend(initiativeId),
      getProductLaunchReadiness(initiativeId),
      listTenantProductLaunchReviewsPage(
        "all",
        pages.launchReview,
        launchReviewPageSize,
        initiativeId,
      ),
    ]);
    if (requestId !== detailRequestRef.current) return;
    const [initiativeResult, timelineResult, salesResult, summaryResult, trendResult, readinessResult, reviewsResult] = results;
    if (initiativeResult.status === "fulfilled") {
      setDetail(initiativeResult.value);
      setInitiatives((current) =>
        current.map((item) => (item.id === initiativeResult.value.id ? initiativeResult.value : item)),
      );
    }
    if (timelineResult.status === "fulfilled") {
      setTimeline(timelineResult.value.items);
      setTimelineTotal(timelineResult.value.total);
    }
    if (salesResult.status === "fulfilled") {
      setPilotSales(salesResult.value.items);
      setPilotSaleTotal(salesResult.value.total);
    }
    if (summaryResult.status === "fulfilled") setPilotSummary(summaryResult.value);
    if (trendResult.status === "fulfilled") setPilotTrend(trendResult.value);
    if (readinessResult.status === "fulfilled") setLaunchReadiness(readinessResult.value);
    if (reviewsResult.status === "fulfilled") {
      setLaunchReviews(reviewsResult.value.items);
      setLaunchReviewTotal(reviewsResult.value.total);
      setLaunchReviewPendingTotal(reviewsResult.value.summary.pending);
    }
    const warningLabels: string[] = [];
    if (initiativeResult.status === "rejected") warningLabels.push("立项详情");
    if (timelineResult.status === "rejected") warningLabels.push("推进时间线");
    if (salesResult.status === "rejected") warningLabels.push("试销数据");
    if (summaryResult.status === "rejected") warningLabels.push("试销汇总");
    if (trendResult.status === "rejected") warningLabels.push("试销趋势");
    if (readinessResult.status === "rejected") warningLabels.push("上市准备预检");
    if (reviewsResult.status === "rejected") warningLabels.push("上市评审");
    setDetailWarnings(warningLabels);
    if (showLoading && requestId === detailRequestRef.current) setDetailLoading(false);
  }, []);

  const refreshDetailAfterMutation = useCallback(async (
    initiativeId: string,
    resetSections: Array<"timeline" | "pilotSale" | "launchReview">,
  ) => {
    const pages = { ...detailPagesRef.current };
    resetSections.forEach((section) => {
      pages[section] = 1;
    });
    detailPagesRef.current = pages;
    if (resetSections.includes("timeline")) setTimelinePage(1);
    if (resetSections.includes("pilotSale")) setPilotSalePage(1);
    if (resetSections.includes("launchReview")) setLaunchReviewPage(1);
    await refreshDetailData(initiativeId, detailRequestRef.current, false, pages);
  }, [refreshDetailData]);

  const loadTimelinePage = useCallback(async (pageValue: number) => {
    if (!currentDetailId) return;
    const requestId = ++detailPageRequestRef.current.timeline;
    try {
      const result = await listProductInitiativeTimelinePage(
        currentDetailId,
        pageValue,
        timelinePageSize,
      );
      if (requestId !== detailPageRequestRef.current.timeline) return;
      detailPagesRef.current = { ...detailPagesRef.current, timeline: result.page };
      setTimelinePage(result.page);
      setTimeline(result.items);
      setTimelineTotal(result.total);
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "无法加载推进记录");
    }
  }, [currentDetailId, messageApi]);

  const loadPilotSalePage = useCallback(async (pageValue: number) => {
    if (!currentDetailId) return;
    const requestId = ++detailPageRequestRef.current.pilotSale;
    try {
      const result = await listPilotSalesPage(currentDetailId, pageValue, pilotSalePageSize);
      if (requestId !== detailPageRequestRef.current.pilotSale) return;
      detailPagesRef.current = { ...detailPagesRef.current, pilotSale: result.page };
      setPilotSalePage(result.page);
      setPilotSales(result.items);
      setPilotSaleTotal(result.total);
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "无法加载试销记录");
    }
  }, [currentDetailId, messageApi]);

  const loadLaunchReviewPage = useCallback(async (pageValue: number) => {
    if (!currentDetailId) return;
    const requestId = ++detailPageRequestRef.current.launchReview;
    try {
      const result = await listTenantProductLaunchReviewsPage(
        "all",
        pageValue,
        launchReviewPageSize,
        currentDetailId,
      );
      if (requestId !== detailPageRequestRef.current.launchReview) return;
      detailPagesRef.current = { ...detailPagesRef.current, launchReview: result.page };
      setLaunchReviewPage(result.page);
      setLaunchReviews(result.items);
      setLaunchReviewTotal(result.total);
      setLaunchReviewPendingTotal(result.summary.pending);
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "无法加载上市评审记录");
    }
  }, [currentDetailId, messageApi]);

  const closeDetail = useCallback(() => {
    detailRequestRef.current += 1;
    setDetail(undefined);
    setDetailLoading(false);
    setTimeline([]);
    setTimelinePage(1);
    setTimelineTotal(0);
    setPilotSales([]);
    setPilotSalePage(1);
    setPilotSaleTotal(0);
    setPilotSummary(undefined);
    setPilotTrend(undefined);
    setLaunchReadiness(undefined);
    setLaunchReviews([]);
    setLaunchReviewPage(1);
    setLaunchReviewTotal(0);
    setLaunchReviewPendingTotal(0);
    detailPagesRef.current = { timeline: 1, pilotSale: 1, launchReview: 1 };
    detailPageRequestRef.current = { timeline: 0, pilotSale: 0, launchReview: 0 };
    setDetailWarnings([]);
  }, []);

  const loadPage = useCallback(async () => {
    const requestId = ++initiativeRequestRef.current;
    setLoading(true);
    const initiativeResult = await Promise.resolve(
      listProductInitiativesPage({
        status: initiativeFilter,
        keyword: initiativeKeyword,
        projectId: currentProjectContextId,
        page: initiativePage,
        pageSize: initiativePageSize,
      }),
    ).then(
      (value) => ({ status: "fulfilled" as const, value }),
      (reason: unknown) => ({ status: "rejected" as const, reason }),
    );
    if (requestId !== initiativeRequestRef.current) return;
    if (initiativeResult.status === "fulfilled") {
      setInitiatives(initiativeResult.value.items);
      setInitiativeTotal(initiativeResult.value.total);
      setInitiativeSummary(initiativeResult.value.summary);
      const pageCount = Math.max(1, Math.ceil(initiativeResult.value.total / initiativePageSize));
      if (initiativePage > pageCount) setInitiativePage(pageCount);
    }
    if (initiativeResult.status === "rejected") {
      setListError("立项列表暂时无法刷新，已保留现有数据");
    } else {
      setListError(undefined);
    }
    setLoading(false);
    if (currentDetailId) void refreshDetailData(currentDetailId);
  }, [
    currentDetailId,
    currentProjectContextId,
    initiativeFilter,
    initiativeKeyword,
    initiativePage,
    refreshDetailData,
  ]);

  const refresh = async () => {
    await loadPage();
  };

  useEffect(() => {
    const initialLoadTimer = window.setTimeout(() => void loadPage(), 0);
    const timer = window.setInterval(() => void loadPage(), 8_000);
    const handleBusinessDataChanged = () => void loadPage();
    window.addEventListener(BUSINESS_DATA_CHANGED_EVENT, handleBusinessDataChanged);
    return () => {
      initiativeRequestRef.current += 1;
      window.clearTimeout(initialLoadTimer);
      window.clearInterval(timer);
      window.removeEventListener(BUSINESS_DATA_CHANGED_EVENT, handleBusinessDataChanged);
    };
  }, [loadPage]);

  useEffect(() => {
    if (!projectContextHydrated || currentProjectContextSource === "initiative") {
      return;
    }
    const contextTimer = window.setTimeout(() => {
      closeDetail();
      setInitiativePage(1);
      setInitiativeFilter("all");
      setInitiativeKeyword("");
    }, 0);
    return () => window.clearTimeout(contextTimer);
  }, [
    closeDetail,
    currentProjectContextSource,
    projectContextHydrated,
    projectContextRevision,
  ]);

  const summary = initiativeSummary;
  const effectiveInitiativePage = Math.min(
    initiativePage,
    Math.max(1, Math.ceil(initiativeTotal / initiativePageSize)),
  );

  const applyOverviewFilter = (filter: InitiativeFilter) => {
    setInitiativePage(1);
    setInitiativeFilter(filter);
    setInitiativeKeyword("");
  };

  const loadReadyProductOptions = useCallback(async (
    keyword = "",
    selectedProductId?: string,
  ): Promise<SelectedProduct[]> => {
    const requestId = ++readyProductRequestRef.current;
    setReadyProductLoading(true);
    try {
      const result = await listSelectedProductsPage({
        status: "ready",
        keyword: selectedProductId ? undefined : keyword,
        selectedProductId,
        page: 1,
        pageSize: selectedProductId ? 1 : 20,
      });
      if (requestId !== readyProductRequestRef.current) {
        return [];
      }
      const currentSelectedId = selectedProductId ?? createForm.getFieldValue("selected_product_id");
      setReadyProducts((current) => {
        const selected = current.find((product) => product.id === currentSelectedId);
        return Array.from(
          new Map(
            [...(selected ? [selected] : []), ...result.items].map((product) => [
              product.id,
              product,
            ]),
          ).values(),
        );
      });
      return result.items;
    } catch (error) {
      if (requestId === readyProductRequestRef.current) {
        messageApi.error(error instanceof Error ? error.message : "无法加载可立项商品");
      }
      return [];
    } finally {
      if (requestId === readyProductRequestRef.current) {
        setReadyProductLoading(false);
      }
    }
  }, [createForm, messageApi]);

  const scheduleReadyProductSearch = useCallback((keyword: string) => {
    if (readyProductSearchTimerRef.current) {
      window.clearTimeout(readyProductSearchTimerRef.current);
    }
    readyProductSearchTimerRef.current = window.setTimeout(() => {
      void loadReadyProductOptions(keyword.trim());
    }, 250);
  }, [loadReadyProductOptions]);

  useEffect(() => () => {
    if (readyProductSearchTimerRef.current) {
      window.clearTimeout(readyProductSearchTimerRef.current);
    }
    readyProductRequestRef.current += 1;
  }, []);

  const openCreate = useCallback((selectedProductId?: string) => {
    createForm.resetFields();
    if (selectedProductId) {
      createForm.setFieldsValue({ selected_product_id: selectedProductId });
    }
    setCreateOpen(true);
    void loadReadyProductOptions("", selectedProductId);
  }, [createForm, loadReadyProductOptions]);

  const openDetail = useCallback(async (initiative: ProductInitiative) => {
    dispatch(
      setProjectContext({
        projectId: initiative.project_id,
        category: initiative.category,
        targetMarket: initiative.target_market,
        tenantId: initiative.tenant_id,
        source: "initiative",
      }),
    );
    const requestId = detailRequestRef.current + 1;
    detailRequestRef.current = requestId;
    detailPagesRef.current = { timeline: 1, pilotSale: 1, launchReview: 1 };
    setDetail(initiative);
    setTimeline([]);
    setTimelinePage(1);
    setTimelineTotal(0);
    setPilotSales([]);
    setPilotSalePage(1);
    setPilotSaleTotal(0);
    setPilotSummary(undefined);
    setPilotTrend(undefined);
    setLaunchReadiness(undefined);
    setLaunchReviews([]);
    setLaunchReviewPage(1);
    setLaunchReviewTotal(0);
    setLaunchReviewPendingTotal(0);
    setDetailWarnings([]);
    await refreshDetailData(initiative.id, requestId, true);
  }, [dispatch, refreshDetailData]);

  useEffect(() => {
    const handleFocusInitiative = (event: Event) => {
      const detail = (event as CustomEvent<{ initiativeId?: string; projectId?: string }>).detail;
      const initiativeId = detail?.initiativeId;
      if (!initiativeId && detail?.projectId) {
        closeDetail();
        setInitiativePage(1);
        setInitiativeFilter("all");
        setInitiativeKeyword("");
        return;
      }
      const initiative = initiatives.find((item) => item.id === initiativeId);
      if (initiative) {
        void openDetail(initiative);
        return;
      }
      if (initiativeId) {
        void getProductInitiative(initiativeId)
          .then((item) => openDetail(item))
          .catch(() => messageApi.warning("目标商品立项暂时无法打开，请刷新后重试"));
      }
    };
    window.addEventListener("merchpilot:focus-initiative", handleFocusInitiative);
    return () => window.removeEventListener("merchpilot:focus-initiative", handleFocusInitiative);
  }, [closeDetail, initiatives, messageApi, openDetail]);

  useEffect(() => {
    const handleFocusInitiativeCreate = async (event: Event) => {
      const selectedProductId = (
        event as CustomEvent<{ selectedProductId?: string }>
      ).detail?.selectedProductId;
      if (!canManage) {
        messageApi.warning("当前角色没有创建商品立项权限，请联系规划人员处理");
        return;
      }
      const availableProducts = selectedProductId
        ? await loadReadyProductOptions("", selectedProductId)
        : await loadReadyProductOptions();
      if (selectedProductId && !availableProducts.some((product) => product.id === selectedProductId)) {
        messageApi.warning("目标选品暂未满足立项条件，请刷新正式选品台账后重试");
        return;
      }
      createForm.resetFields();
      if (selectedProductId) {
        createForm.setFieldsValue({ selected_product_id: selectedProductId });
      }
      setCreateOpen(true);
    };
    window.addEventListener("merchpilot:focus-initiative-create", handleFocusInitiativeCreate);
    return () =>
      window.removeEventListener("merchpilot:focus-initiative-create", handleFocusInitiativeCreate);
  }, [canManage, createForm, loadReadyProductOptions, messageApi]);

  const submitPilotSale = async (values: PilotSaleFormValues) => {
    if (!detail) return;
    setSaving(true);
    try {
      const payload = { ...values, notes: values.notes?.trim() };
      if (editingPilotSale) {
        await updatePilotSale(detail.id, editingPilotSale.id, payload);
      } else {
        await createPilotSale(detail.id, payload);
      }
      await refreshDetailAfterMutation(detail.id, ["pilotSale", "timeline"]);
      setPilotSaleOpen(false);
      setEditingPilotSale(undefined);
      pilotSaleForm.resetFields();
      notifyBusinessDataChanged();
      messageApi.success(editingPilotSale ? "试销经营数据已修订" : "试销经营数据已录入");
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "试销数据录入失败");
    } finally {
      setSaving(false);
    }
  };

  const openPilotSaleEditor = (record?: PilotSaleRecord) => {
    setEditingPilotSale(record);
    if (record) {
      pilotSaleForm.setFieldsValue({
        period_start: record.period_start,
        period_end: record.period_end,
        channel: record.channel,
        visitors: record.visitors,
        orders: record.orders,
        units_sold: record.units_sold,
        revenue: record.revenue,
        product_cost: record.product_cost,
        marketing_spend: record.marketing_spend,
        refunds_amount: record.refunds_amount,
        return_count: record.return_count,
        rating: record.rating,
        notes: record.notes,
      });
    } else {
      pilotSaleForm.resetFields();
    }
    setPilotSaleOpen(true);
  };

  const submitCreate = async (values: CreateFormValues) => {
    setSaving(true);
    try {
      const created = await createProductInitiative({
        selected_product_id: values.selected_product_id,
        owner_id: values.owner_id?.trim() || null,
        target_launch_date: values.target_launch_date || null,
        budget: values.budget ?? null,
        notes: values.notes?.trim() || null,
      });
      messageApi.success("商品立项已创建");
      setCreateOpen(false);
      createForm.resetFields();
      await refresh();
      await openDetail(created);
      notifyBusinessDataChanged();
      window.dispatchEvent(
        new CustomEvent("merchpilot:selected-product-created", {
          detail: { selectedProductId: values.selected_product_id, initiativeId: created.id },
        }),
      );
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "商品立项创建失败");
    } finally {
      setSaving(false);
    }
  };

  const openInitiativeEditor = (initiative: ProductInitiative) => {
    initiativeEditForm.setFieldsValue({
      owner_id: initiative.owner_id,
      target_launch_date: initiative.target_launch_date,
      budget: initiative.budget,
      notes: initiative.notes,
    });
    setInitiativeEditOpen(true);
  };

  const submitInitiativeEdit = async (values: InitiativeEditFormValues) => {
    if (!detail) return;
    setSaving(true);
    try {
      const updated = await updateProductInitiative(detail.id, {
        owner_id: values.owner_id?.trim() || null,
        target_launch_date: values.target_launch_date || null,
        budget: values.budget ?? null,
        notes: values.notes?.trim() || null,
      });
      setDetail(updated);
      setInitiatives((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      await refreshDetailAfterMutation(updated.id, ["timeline"]);
      setInitiativeEditOpen(false);
      initiativeEditForm.resetFields();
      messageApi.success("立项信息已更新");
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "立项信息更新失败");
    } finally {
      setSaving(false);
    }
  };

  const openMilestone = (milestone: ProductMilestone) => {
    milestoneForm.setFieldsValue({
      status: milestone.status,
      owner_id: milestone.owner_id,
      due_date: milestone.due_date,
      note: milestone.note,
    });
    setEditingMilestone(milestone);
  };

  const openLaunchReviewSubmit = () => {
    launchReviewSubmitForm.resetFields();
    setLaunchReviewSubmitOpen(true);
  };

  const submitLaunchReview = async (values: LaunchReviewSubmitFormValues) => {
    if (!detail) return;
    setSaving(true);
    try {
      await submitProductLaunchReview(detail.id, {
        submission_note: values.submission_note?.trim() || null,
      });
      await refreshDetailAfterMutation(detail.id, ["timeline", "launchReview"]);
      setLaunchReviewSubmitOpen(false);
      launchReviewSubmitForm.resetFields();
      notifyBusinessDataChanged();
      messageApi.success("上市准备评审已提交，等待审批");
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "上市准备评审提交失败");
    } finally {
      setSaving(false);
    }
  };

  const openLaunchReviewDecision = (
    review: ProductLaunchReview,
    action: "approved" | "rejected" | "revision_required",
  ) => {
    setLaunchReviewTarget(review);
    setLaunchReviewDecisionAction(action);
    launchReviewDecisionForm.resetFields();
    setLaunchReviewDecisionOpen(true);
  };

  const submitLaunchReviewDecision = async (values: LaunchReviewDecisionFormValues) => {
    if (!detail || !launchReviewTarget) return;
    setSaving(true);
    try {
      await decideProductLaunchReview(detail.id, launchReviewTarget.id, {
        action: launchReviewDecisionAction,
        decision_note: values.decision_note?.trim() || "",
      });
      await refreshDetailAfterMutation(detail.id, ["timeline", "launchReview"]);
      setLaunchReviewDecisionOpen(false);
      setLaunchReviewTarget(undefined);
      launchReviewDecisionForm.resetFields();
      notifyBusinessDataChanged();
      messageApi.success(
        launchReviewDecisionAction === "approved"
          ? "上市准备评审已通过"
          : launchReviewDecisionAction === "revision_required"
            ? "评审已退回修订"
            : "评审已驳回",
      );
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "上市准备评审处理失败");
    } finally {
      setSaving(false);
    }
  };

  const submitMilestone = async (values: MilestoneFormValues) => {
    if (!detail || !editingMilestone) return;
    setSaving(true);
    try {
      const updated = await updateProductMilestone(detail.id, editingMilestone.id, {
        status: values.status,
        owner_id: values.owner_id?.trim() || null,
        due_date: values.due_date || null,
        note: values.note?.trim() || null,
      });
      setDetail(updated);
      setInitiatives((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setEditingMilestone(undefined);
      milestoneForm.resetFields();
      await refreshDetailAfterMutation(updated.id, ["timeline", "launchReview"]);
      notifyBusinessDataChanged();
      messageApi.success("里程碑已更新");
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "里程碑更新失败");
    } finally {
      setSaving(false);
    }
  };

  const changeInitiativeStatus = async (
    initiative: ProductInitiative,
    nextStatus: "in_progress" | "launched" | "paused",
  ) => {
    setSaving(true);
    try {
      const updated = await updateProductInitiative(initiative.id, { status: nextStatus });
      setInitiatives((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setDetail(updated);
      await refreshDetailAfterMutation(updated.id, ["timeline"]);
      notifyBusinessDataChanged();
      messageApi.success(nextStatus === "launched" ? "商品已确认上市" : "立项状态已更新");
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "立项状态更新失败");
    } finally {
      setSaving(false);
    }
  };

  const columns: TableProps<ProductInitiative>["columns"] = [
    {
      title: "商品立项",
      key: "product",
      width: 300,
      render: (_, initiative) => (
        <div className="initiative-summary">
          <strong>
            {initiative.name}
            {needsAttention(initiative) ? <Tag color="warning">需处理</Tag> : null}
          </strong>
          <span>{initiative.category} · {initiative.target_market}</span>
          <small>负责人：{initiative.owner_id || "待分配"}</small>
        </div>
      ),
    },
    {
      title: "里程碑进度",
      key: "progress",
      width: 260,
      render: (_, initiative) => (
        <div className="initiative-progress">
          <Progress percent={progressOf(initiative)} size="small" />
          <span>
            {initiative.milestones.filter((item) => item.status === "completed").length}
            /{initiative.milestones.length} 个节点完成
          </span>
        </div>
      ),
    },
    {
      title: "当前节点",
      key: "current_milestone",
      width: 220,
      render: (_, initiative) => {
        const milestone = currentMilestone(initiative);
        if (!milestone) return "暂无里程碑";
        const presentation = milestonePresentation[milestone.status];
        return (
          <div className="initiative-current-milestone">
            <div>
              <Tag color={presentation.color}>{presentation.label}</Tag>
              {isOverdue(milestone.due_date) && milestone.status !== "completed" ? (
                <Tag color="error">已逾期</Tag>
              ) : null}
            </div>
            <span>{milestone.label}</span>
            <small>{milestone.due_date ? `计划完成：${formatDate(milestone.due_date)}` : "完成日期待确定"}</small>
          </div>
        );
      },
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 130,
      render: (value: ProductInitiativeStatus) => (
        <Tag color={statusPresentation[value].color}>{statusPresentation[value].label}</Tag>
      ),
    },
    {
      title: "目标上市",
      dataIndex: "target_launch_date",
      key: "target_launch_date",
      width: 130,
      render: (value?: string) => formatDate(value),
    },
    {
      title: "立项预算",
      dataIndex: "budget",
      key: "budget",
      width: 130,
      render: (value?: number) => formatMoney(value),
    },
    {
      title: "操作",
      key: "actions",
      width: 220,
      fixed: "right",
      render: (_, initiative) => (
        <Space>
          <Button size="small" icon={<EyeOutlined />} onClick={() => void openDetail(initiative)}>
            查看推进
          </Button>
          {initiative.status === "launch_ready" ? (
            <Button
              size="small"
              type="primary"
              icon={<CheckCircleOutlined />}
              disabled={!canManage}
              onClick={() => void changeInitiativeStatus(initiative, "launched")}
            >
              确认上市
            </Button>
          ) : null}
        </Space>
      ),
    },
  ];

  return (
    <section className="panel product-initiative-panel" id="product-initiative-panel">
      {contextHolder}
      {listError ? (
        <Alert
          type="error"
          showIcon
          message="商品立项数据刷新失败"
          description={listError}
          action={<Button size="small" onClick={() => void refresh()}>重试</Button>}
        />
      ) : null}
      <div className="panel-header">
        <div>
          <h2 className="panel-title"><RocketOutlined /> 商品立项中心</h2>
          <p className="panel-description">将验证通过的正式选品转为可执行立项，持续推进样品、成本、试销和上市评审</p>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void refresh()}>
            刷新
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            disabled={!canManage}
            onClick={() => openCreate()}
          >
            新建立项
          </Button>
        </Space>
      </div>

      <div className="initiative-overview">
        <button
          type="button"
          className={`initiative-overview-card ${initiativeFilter === "all" ? "initiative-overview-card-active" : ""}`}
          aria-pressed={initiativeFilter === "all"}
          onClick={() => applyOverviewFilter("all")}
        >
          <span>全部立项</span><strong>{summary.total}</strong><small>正式进入商品开发阶段</small>
        </button>
        <button
          type="button"
          className={`initiative-overview-card ${initiativeFilter === "needs_attention" ? "initiative-overview-card-active" : ""}`}
          aria-pressed={initiativeFilter === "needs_attention"}
          onClick={() => applyOverviewFilter("needs_attention")}
        >
          <span>待优先处理</span><strong>{summary.attention}</strong><small>阻塞、逾期或待确认上市</small>
        </button>
        <button
          type="button"
          className={`initiative-overview-card ${initiativeFilter === "in_progress" ? "initiative-overview-card-active" : ""}`}
          aria-pressed={initiativeFilter === "in_progress"}
          onClick={() => applyOverviewFilter("in_progress")}
        >
          <span>推进中</span><strong>{summary.active}</strong><small>里程碑正在执行</small>
        </button>
        <button
          type="button"
          className={`initiative-overview-card ${initiativeFilter === "launch_ready" ? "initiative-overview-card-active" : ""}`}
          aria-pressed={initiativeFilter === "launch_ready"}
          onClick={() => applyOverviewFilter("launch_ready")}
        >
          <span>待确认上市</span><strong>{summary.ready}</strong><small>所有里程碑均已完成</small>
        </button>
        <button
          type="button"
          className={`initiative-overview-card ${initiativeFilter === "launched" ? "initiative-overview-card-active" : ""}`}
          aria-pressed={initiativeFilter === "launched"}
          onClick={() => applyOverviewFilter("launched")}
        >
          <span>已上市</span><strong>{summary.launched}</strong><small>保留完整立项轨迹</small>
        </button>
      </div>

      <div className="initiative-filter-toolbar">
        <Select
          value={initiativeFilter}
          onChange={(value: InitiativeFilter) => {
            setInitiativePage(1);
            setInitiativeFilter(value);
          }}
          options={[
            { value: "all", label: "全部立项" },
            { value: "needs_attention", label: "待优先处理" },
            { value: "in_progress", label: "推进中" },
            { value: "launch_ready", label: "待确认上市" },
            { value: "launched", label: "已上市" },
            { value: "paused", label: "已暂停" },
            { value: "cancelled", label: "已取消" },
          ]}
        />
        <Input.Search
          allowClear
          value={initiativeKeyword}
          placeholder="搜索立项名称、品类、市场或负责人"
          onChange={(event) => {
            setInitiativePage(1);
            setInitiativeKeyword(event.target.value);
          }}
        />
        <span>当前显示 {initiatives.length} / {initiativeTotal} 个立项</span>
      </div>

      <Table<ProductInitiative>
        rowKey="id"
        columns={columns}
        dataSource={initiatives}
        loading={loading}
        pagination={{
          current: effectiveInitiativePage,
          pageSize: initiativePageSize,
          total: initiativeTotal,
          hideOnSinglePage: true,
          onChange: setInitiativePage,
        }}
        scroll={{ x: 1400 }}
        locale={{ emptyText: <Empty description="暂无商品立项，验证通过后可在此发起" /> }}
      />

      <Modal
        title="新建商品立项"
        open={createOpen}
        onCancel={() => {
          setCreateOpen(false);
          createForm.resetFields();
        }}
        onOk={() => createForm.submit()}
        okText="确认立项"
        confirmLoading={saving}
      >
        <Form form={createForm} layout="vertical" onFinish={(values) => void submitCreate(values)}>
          <Form.Item name="selected_product_id" label="可立项商品" rules={[{ required: true }]}>
            <Select
              showSearch
              filterOption={false}
              loading={readyProductLoading}
              onSearch={scheduleReadyProductSearch}
              onOpenChange={(open) => {
                if (open) {
                  scheduleReadyProductSearch("");
                }
              }}
              notFoundContent={readyProductLoading ? <Spin size="small" /> : "暂无可立项商品"}
              options={readyProducts.map((item) => ({
                value: item.id,
                label: `${item.name} · ${item.category} · ${item.target_market}`,
              }))}
            />
          </Form.Item>
          <Form.Item name="owner_id" label="立项负责人">
            <Input maxLength={64} placeholder="默认沿用正式选品负责人" />
          </Form.Item>
          <Form.Item name="target_launch_date" label="目标上市日期">
            <Input type="date" />
          </Form.Item>
          <Form.Item name="budget" label="立项预算">
            <InputNumber min={0} precision={2} style={{ width: "100%" }} addonBefore="¥" />
          </Form.Item>
          <Form.Item name="notes" label="立项说明">
            <Input.TextArea rows={3} maxLength={2000} showCount />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        title={detail ? `${detail.name} · 立项推进` : "商品立项推进"}
        size="min(920px, 96vw)"
        open={Boolean(detail)}
        onClose={closeDetail}
        extra={detail && canManage ? (
          <Space>
            {detail.status !== "cancelled" ? (
              <Button icon={<EditOutlined />} onClick={() => openInitiativeEditor(detail)}>
                编辑立项信息
              </Button>
            ) : null}
            {detail.status === "paused" ? (
              <Button onClick={() => void changeInitiativeStatus(detail, "in_progress")}>恢复推进</Button>
            ) : detail.status === "in_progress" ? (
              <Button onClick={() => void changeInitiativeStatus(detail, "paused")}>暂停</Button>
            ) : null}
            {detail.status === "launch_ready" ? (
              <Button type="primary" onClick={() => void changeInitiativeStatus(detail, "launched")}>确认上市</Button>
            ) : null}
          </Space>
        ) : null}
      >
        {detail ? (
          <div className="initiative-detail">
            {detailLoading ? (
              <div className="initiative-detail-loading" role="status">
                <Spin size="small" />
                <span>正在加载最新推进信息</span>
              </div>
            ) : null}
            <Descriptions bordered size="small" column={{ xs: 1, sm: 2 }}>
              <Descriptions.Item label="推进状态">
                <Tag color={statusPresentation[detail.status].color}>{statusPresentation[detail.status].label}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="负责人">{detail.owner_id || "待分配"}</Descriptions.Item>
              <Descriptions.Item label="目标上市">{formatDate(detail.target_launch_date)}</Descriptions.Item>
              <Descriptions.Item label="立项预算">{formatMoney(detail.budget)}</Descriptions.Item>
              <Descriptions.Item label="整体进度" span={2}>
                <Progress percent={progressOf(detail)} />
              </Descriptions.Item>
              <Descriptions.Item label="立项说明" span={2}>{detail.notes || "暂无说明"}</Descriptions.Item>
            </Descriptions>

            {detailWarnings.length > 0 ? (
              <Alert
                className="initiative-detail-warning"
                showIcon
                type="warning"
                message="部分推进信息暂时无法加载"
                description={`${detailWarnings.join("、")}加载失败，当前仍保留已成功读取的数据；刷新或稍后重试即可补齐。`}
              />
            ) : null}

            {launchReadiness ? (
              <div className="launch-readiness-card">
                <div className="initiative-section-header">
                  <div>
                    <h3>上市准备预检</h3>
                    <span className="launch-readiness-caption">确认上市前集中检查关键条件，结果不会自动替代人工审批</span>
                  </div>
                  <Tag color={readinessPresentation[launchReadiness.readiness_status].color}>
                    {readinessPresentation[launchReadiness.readiness_status].label}
                  </Tag>
                </div>
                <Alert
                  showIcon
                  type={launchReadiness.readiness_status === "ready"
                    ? "success"
                    : launchReadiness.readiness_status === "blocked"
                      ? "error"
                      : "warning"}
                  message={launchReadiness.readiness_label}
                  description={[
                    ...launchReadiness.blockers,
                    ...launchReadiness.warnings,
                    ...launchReadiness.recommendations,
                  ].join("；")}
                />
                <List
                  size="small"
                  className="launch-readiness-check-list"
                  dataSource={launchReadiness.checks}
                  renderItem={(check) => (
                    <List.Item>
                      <Space>
                        <Tag color={readinessCheckPresentation[check.status].color}>
                          {readinessCheckPresentation[check.status].label}
                        </Tag>
                        <strong>{check.label}</strong>
                        <span>{check.detail}</span>
                      </Space>
                    </List.Item>
                  )}
                />
              </div>
            ) : null}

            <h3>执行里程碑</h3>
            <List
              className="initiative-milestone-list"
              dataSource={detail.milestones}
              renderItem={(milestone) => {
                const presentation = milestonePresentation[milestone.status];
                return (
                  <List.Item
                    actions={canManage && !["launched", "paused", "cancelled"].includes(detail.status) ? [
                      <Button key="edit" size="small" icon={<EditOutlined />} onClick={() => openMilestone(milestone)}>
                        更新
                      </Button>,
                    ] : undefined}
                  >
                    <List.Item.Meta
                      title={<Space><span>{milestone.label}</span><Tag color={presentation.color}>{presentation.label}</Tag></Space>}
                      description={[
                        milestone.owner_id ? `负责人：${milestone.owner_id}` : "负责人待分配",
                        milestone.due_date ? `计划完成：${formatDate(milestone.due_date)}` : "完成日期待确定",
                        milestone.note || "暂无推进备注",
                      ].join(" · ")}
                    />
                  </List.Item>
                );
              }}
            />

            <div className="initiative-section-header">
              <div>
                <h3><FileDoneOutlined /> 上市准备评审</h3>
                <span className="launch-readiness-caption">提交后由审批人员在线处理，审批意见和预检快照会永久保留</span>
              </div>
              {canManage && detail.status === "in_progress" &&
              detail.milestones.find((milestone) => milestone.id === "launch_review")?.status !== "completed" &&
              launchReviewPendingTotal === 0 ? (
                <Button icon={<FileDoneOutlined />} onClick={openLaunchReviewSubmit}>
                  提交上市评审
                </Button>
              ) : null}
            </div>
            {launchReviews.length ? (
              <List
                className="launch-review-list"
                dataSource={launchReviews}
                renderItem={(review) => {
                  const presentation = launchReviewPresentation[review.status];
                  const pending = review.status === "pending";
                  return (
                    <List.Item
                      actions={pending && canReview ? [
                        <Button key="approve" size="small" type="primary" onClick={() => openLaunchReviewDecision(review, "approved")}>
                          通过
                        </Button>,
                        <Button key="revision" size="small" onClick={() => openLaunchReviewDecision(review, "revision_required")}>
                          退回修订
                        </Button>,
                        <Button key="reject" size="small" danger onClick={() => openLaunchReviewDecision(review, "rejected")}>
                          驳回
                        </Button>,
                      ] : undefined}
                    >
                      <List.Item.Meta
                        title={<Space><Tag color={presentation.color}>{presentation.label}</Tag><strong>评审单 {review.id.slice(-8)}</strong></Space>}
                        description={[
                          `提交人：${review.submitted_by}`,
                          `提交时间：${formatDate(review.submitted_at)}`,
                          review.decided_by ? `处理人：${review.decided_by}` : "等待审批处理",
                          review.decision_note || review.submission_note || "暂无意见",
                        ].join(" · ")}
                      />
                    </List.Item>
                  );
                }}
              />
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未提交上市准备评审" />
            )}
            {launchReviewTotal > launchReviewPageSize ? (
              <Pagination
                current={launchReviewPage}
                pageSize={launchReviewPageSize}
                total={launchReviewTotal}
                showSizeChanger={false}
                showTotal={(total) => `共 ${total} 次上市评审`}
                onChange={(pageValue) => void loadLaunchReviewPage(pageValue)}
              />
            ) : null}

            <div className="initiative-section-header">
              <h3>试销经营复盘</h3>
              {canManage ? <Button type="primary" onClick={() => openPilotSaleEditor()}>录入试销数据</Button> : null}
            </div>
            <div className="pilot-sale-overview">
              <div><span>累计收入</span><strong>{formatMoney(pilotSummary?.revenue)}</strong><small>{pilotSummary?.orders ?? 0} 笔订单</small></div>
              <div><span>成交转化率</span><strong>{formatPercent(pilotSummary?.conversion_rate)}</strong><small>{pilotSummary?.visitors ?? 0} 位访客</small></div>
              <div><span>实际毛利率</span><strong>{formatPercent(pilotSummary?.actual_margin_rate)}</strong><small>规划 {formatPercent(pilotSummary?.planned_margin_rate)}</small></div>
              <div><span>营销回报</span><strong>{pilotSummary?.marketing_roi === undefined ? "待统计" : `${pilotSummary.marketing_roi.toFixed(2)} 倍`}</strong><small>退货率 {formatPercent(pilotSummary?.return_rate)}</small></div>
            </div>
            {pilotSummary ? (
              <Alert
                showIcon
                type={pilotSummary.assessment_status === "recommended"
                  ? "success"
                  : pilotSummary.assessment_status === "blocked"
                    ? "error"
                    : pilotSummary.assessment_status === "review"
                      ? "warning"
                      : "info"}
                message={pilotSummary.assessment_label}
                description={[
                  ...pilotSummary.risks,
                  ...pilotSummary.recommendations,
                ].join("；")}
              />
            ) : null}
            {pilotTrend?.periods.length ? (
              <div className="pilot-sale-trend">
                <div className="pilot-sale-trend-header">
                  <div>
                    <h4>试销趋势</h4>
                    <span>按试销周期汇总收入、利润和转化率，支持多渠道复盘</span>
                  </div>
                  <Tag color="blue">
                    最近 {pilotTrend.periods.length} / {pilotTrend.period_total} 个周期
                  </Tag>
                </div>
                <Line
                  data={pilotTrend.periods.flatMap((point) => [
                    { period: point.label, metric: "收入", value: point.revenue },
                    { period: point.label, metric: "实际利润", value: point.gross_profit },
                  ])}
                  xField="period"
                  yField="value"
                  colorField="metric"
                  smooth
                  height={260}
                  axis={{
                    x: { title: "试销周期" },
                    y: { title: "金额（元）" },
                  }}
                  tooltip={{ channel: "y" }}
                />
                {pilotTrend.channels.length > 1 ? (
                  <Table
                    className="pilot-sale-channel-table"
                    size="small"
                    rowKey="channel"
                    pagination={false}
                    dataSource={pilotTrend.channels}
                    columns={[
                      { title: "渠道", dataIndex: "channel", key: "channel" },
                      { title: "收入", dataIndex: "revenue", key: "revenue", render: (value: number) => formatMoney(value) },
                      { title: "订单", dataIndex: "orders", key: "orders" },
                      { title: "转化率", dataIndex: "conversion_rate", key: "conversion_rate", render: (value?: number) => formatPercent(value) },
                      { title: "实际毛利率", dataIndex: "actual_margin_rate", key: "actual_margin_rate", render: (value?: number) => formatPercent(value) },
                    ]}
                  />
                ) : null}
                {pilotTrend.channel_total > pilotTrend.channels.length ? (
                  <span className="pilot-sale-trend-note">
                    渠道表按收入展示前 {pilotTrend.channels.length} / {pilotTrend.channel_total} 个渠道
                  </span>
                ) : null}
              </div>
            ) : null}
            <List
              dataSource={pilotSales}
              locale={{ emptyText: "暂无试销经营数据" }}
              renderItem={(record) => (
                <List.Item
                  actions={canManage ? [
                    <Button key="edit" size="small" icon={<EditOutlined />} onClick={() => openPilotSaleEditor(record)}>
                      修订
                    </Button>,
                  ] : undefined}
                >
                  <List.Item.Meta
                    title={`${record.channel} · ${formatDate(record.period_start)} 至 ${formatDate(record.period_end)}`}
                    description={`收入 ${formatMoney(record.revenue)} · 订单 ${record.orders} · 销量 ${record.units_sold} · 毛利率 ${formatPercent(record.actual_margin_rate)} · 评分 ${record.rating ?? "待统计"}`}
                  />
                </List.Item>
              )}
            />
            {pilotSaleTotal > pilotSalePageSize ? (
              <Pagination
                current={pilotSalePage}
                pageSize={pilotSalePageSize}
                total={pilotSaleTotal}
                showSizeChanger={false}
                showTotal={(total) => `共 ${total} 条试销记录`}
                onChange={(pageValue) => void loadPilotSalePage(pageValue)}
              />
            ) : null}

            <h3>推进记录</h3>
            {timeline.length ? (
              <Timeline
                items={timeline.map((event) => ({
                  color: event.action === "product_initiative.milestone_updated" ? "green" : "blue",
                  children: `${timelineText(event)} · ${event.actor_id} · ${formatDate(event.occurred_at)}`,
                }))}
              />
            ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无推进记录" />}
            {timelineTotal > timelinePageSize ? (
              <Pagination
                current={timelinePage}
                pageSize={timelinePageSize}
                total={timelineTotal}
                showSizeChanger={false}
                showTotal={(total) => `共 ${total} 条推进记录`}
                onChange={(pageValue) => void loadTimelinePage(pageValue)}
              />
            ) : null}
          </div>
        ) : null}
      </Drawer>

      <Modal
        title="编辑立项信息"
        open={initiativeEditOpen}
        onCancel={() => {
          setInitiativeEditOpen(false);
          initiativeEditForm.resetFields();
        }}
        onOk={() => initiativeEditForm.submit()}
        okText="保存信息"
        confirmLoading={saving}
      >
        <Alert
          showIcon
          type="info"
          message="修改后会立即更新上市准备预检"
          description="负责人、目标上市日期、预算和立项说明会写入审计时间线；如修改了目标日期，上市确认时将再次校验。"
          style={{ marginBottom: 16 }}
        />
        <Form form={initiativeEditForm} layout="vertical" onFinish={(values) => void submitInitiativeEdit(values)}>
          <Form.Item name="owner_id" label="立项负责人">
            <Input maxLength={64} placeholder="请输入负责上市推进的企业账号" />
          </Form.Item>
          <Form.Item name="target_launch_date" label="目标上市日期">
            <Input type="date" />
          </Form.Item>
          <Form.Item name="budget" label="立项预算">
            <InputNumber min={0} precision={2} style={{ width: "100%" }} addonBefore="¥" />
          </Form.Item>
          <Form.Item name="notes" label="立项说明">
            <Input.TextArea rows={4} maxLength={2000} showCount />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="提交上市准备评审"
        open={launchReviewSubmitOpen}
        onCancel={() => {
          setLaunchReviewSubmitOpen(false);
          launchReviewSubmitForm.resetFields();
        }}
        onOk={() => launchReviewSubmitForm.submit()}
        okText="提交评审"
        confirmLoading={saving}
      >
        <Alert
          showIcon
          type={launchReadiness?.readiness_status === "review" ? "warning" : "info"}
          message={launchReadiness?.readiness_label || "提交前会重新执行上市准备预检"}
          description="系统会保存本次提交时的里程碑、试销、负责人、目标日期和预算快照，审批人员将基于最新数据复核。"
          style={{ marginBottom: 16 }}
        />
        <Form form={launchReviewSubmitForm} layout="vertical" onFinish={(values) => void submitLaunchReview(values)}>
          <Form.Item name="submission_note" label="提交说明">
            <Input.TextArea rows={5} maxLength={2000} showCount placeholder="说明本次上市准备情况、风险处理和需要审批关注的事项" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={launchReviewDecisionAction === "approved" ? "通过上市准备评审" : launchReviewDecisionAction === "revision_required" ? "退回上市准备评审" : "驳回上市准备评审"}
        open={launchReviewDecisionOpen}
        onCancel={() => {
          setLaunchReviewDecisionOpen(false);
          setLaunchReviewTarget(undefined);
          launchReviewDecisionForm.resetFields();
        }}
        onOk={() => launchReviewDecisionForm.submit()}
        okText={launchReviewDecisionAction === "approved" ? "确认通过" : "确认处理"}
        confirmLoading={saving}
      >
        <Alert
          showIcon
          type={launchReviewDecisionAction === "approved" ? "info" : "warning"}
          message="审批结果会同步到上市准备评审里程碑"
          description={launchReviewDecisionAction === "approved" ? "通过后将自动完成上市准备评审节点；之后还需要执行确认上市。" : "退回或驳回必须填写处理意见，规划人员修改后可以重新提交。"}
          style={{ marginBottom: 16 }}
        />
        <Form form={launchReviewDecisionForm} layout="vertical" onFinish={(values) => void submitLaunchReviewDecision(values)}>
          <Form.Item
            name="decision_note"
            label="处理意见"
            rules={launchReviewDecisionAction === "approved" ? undefined : [{ required: true, message: "请填写处理意见" }]}
          >
            <Input.TextArea rows={5} maxLength={2000} showCount placeholder="请输入审批意见" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={editingMilestone ? `更新里程碑 · ${editingMilestone.label}` : "更新里程碑"}
        open={Boolean(editingMilestone)}
        onCancel={() => {
          setEditingMilestone(undefined);
          milestoneForm.resetFields();
        }}
        onOk={() => milestoneForm.submit()}
        okText="保存推进"
        confirmLoading={saving}
      >
        {detail && editingMilestone && detail.milestones.some((milestone, index) =>
          milestone.id === editingMilestone.id
            ? detail.milestones.slice(index + 1).some((later) => ["in_progress", "completed"].includes(later.status))
            : false,
        ) ? (
          <Alert
            showIcon
            type="warning"
            message="后置里程碑已开始或完成"
            description="当前节点不能回退状态；如需回退，请先处理后置里程碑。负责人、日期和备注仍可调整。"
            style={{ marginBottom: 16 }}
          />
        ) : null}
        <Form form={milestoneForm} layout="vertical" onFinish={(values) => void submitMilestone(values)}>
          <Form.Item name="status" label="执行状态" rules={[{ required: true }]}>
            <Select options={milestoneOptions} />
          </Form.Item>
          <Form.Item name="owner_id" label="负责人">
            <Input maxLength={64} />
          </Form.Item>
          <Form.Item name="due_date" label="计划完成日期">
            <Input type="date" />
          </Form.Item>
          <Form.Item name="note" label="推进备注">
            <Input.TextArea rows={4} maxLength={2000} showCount />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={editingPilotSale ? "修订试销经营数据" : "录入试销经营数据"}
        open={pilotSaleOpen}
        onCancel={() => {
          setPilotSaleOpen(false);
          setEditingPilotSale(undefined);
          pilotSaleForm.resetFields();
        }}
        onOk={() => pilotSaleForm.submit()}
        okText="保存数据"
        confirmLoading={saving}
        width={760}
      >
        <Alert
          showIcon
          type="info"
          message="同一试销周期与渠道只能保留一条记录"
          description="如果需要更正已有数据，请在历史记录中点击“修订”，不要重复录入。"
          style={{ marginBottom: 16 }}
        />
        <Form form={pilotSaleForm} layout="vertical" onFinish={(values) => void submitPilotSale(values)}>
          <div className="pilot-sale-form-grid">
            <Form.Item name="period_start" label="开始日期" rules={[{ required: true }]}><Input type="date" /></Form.Item>
            <Form.Item name="period_end" label="结束日期" rules={[{ required: true }]}><Input type="date" /></Form.Item>
            <Form.Item name="channel" label="试销渠道" rules={[{ required: true }]}><Input placeholder="例如：天猫旗舰店" /></Form.Item>
            <Form.Item name="visitors" label="访客数" initialValue={0}><InputNumber min={0} precision={0} style={{ width: "100%" }} /></Form.Item>
            <Form.Item name="orders" label="订单数" initialValue={0}><InputNumber min={0} precision={0} style={{ width: "100%" }} /></Form.Item>
            <Form.Item name="units_sold" label="销售件数" initialValue={0}><InputNumber min={0} precision={0} style={{ width: "100%" }} /></Form.Item>
            <Form.Item name="revenue" label="销售收入" initialValue={0}><InputNumber min={0} precision={2} addonBefore="¥" style={{ width: "100%" }} /></Form.Item>
            <Form.Item name="product_cost" label="商品成本" initialValue={0}><InputNumber min={0} precision={2} addonBefore="¥" style={{ width: "100%" }} /></Form.Item>
            <Form.Item name="marketing_spend" label="营销投入" initialValue={0}><InputNumber min={0} precision={2} addonBefore="¥" style={{ width: "100%" }} /></Form.Item>
            <Form.Item name="refunds_amount" label="退款金额" initialValue={0}><InputNumber min={0} precision={2} addonBefore="¥" style={{ width: "100%" }} /></Form.Item>
            <Form.Item name="return_count" label="退货件数" initialValue={0}><InputNumber min={0} precision={0} style={{ width: "100%" }} /></Form.Item>
            <Form.Item name="rating" label="用户评分"><InputNumber min={0} max={5} precision={1} style={{ width: "100%" }} /></Form.Item>
          </div>
          <Form.Item name="notes" label="试销备注"><Input.TextArea rows={3} maxLength={2000} showCount /></Form.Item>
        </Form>
      </Modal>
    </section>
  );
}
