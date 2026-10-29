"""文件职责：为本地开发环境幂等创建可完整演示的真实业务工作区。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from typing import Any, Literal, cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from merchpilot.api.schemas import LocalDemoProjectRead, LocalDemoWorkspaceRead
from merchpilot.domain.enums import (
    ApprovalStatus,
    EvidenceIndexStatus,
    EvidenceQualityStatus,
    ImportStatus,
    ProjectStatus,
    RunStatus,
)
from merchpilot.infrastructure.models import (
    ApprovalTask,
    DataImportJob,
    EvidenceRecord,
    PilotSaleRecord,
    PlanningProject,
    PlanningRun,
    ProductInitiative,
    ProductLaunchReview,
    SelectedProduct,
)
from merchpilot.ports.identity import Identity
from merchpilot.services.audit import record_audit_event
from merchpilot.services.concepts import (
    apply_candidate_selection,
    apply_candidate_validation_updates,
    build_candidate_concepts,
    resolve_candidate_concept,
)
from merchpilot.services.finance import calculate_candidate_financials, calculate_financials
from merchpilot.services.planning_metrics import build_planning_metrics
from merchpilot.services.research_governance import build_research_synthesis
from merchpilot.services.scoring import build_scorecard
from merchpilot.services.supplier import evaluate_supplier_constraints

DemoScenario = Literal["planning_approval", "validation", "launch_review", "launched"]
DemoIndexStatus = Literal["pending", "indexing", "indexed", "failed"]

DEMO_VERSION = "merchpilot-local-demo-v2"
DEMO_CATEGORY = "智能保温杯"
DEMO_MARKET = "中国一二线城市"
AGENT_NODES = (
    "requirement_agent",
    "research_planning_agent",
    "market_agent",
    "competitor_agent",
    "user_insight_agent",
    "research_synthesis_agent",
    "concept_agent",
    "supplier_agent",
    "finance_agent",
    "scoring_agent",
    "critic_agent",
    "narrative_agent",
    "review_agent",
)


def _tenant_suffix(tenant_id: str) -> str:
    """把租户标识转换为固定长度后缀，避免不同租户共享演示数据主键。"""
    return sha256(tenant_id.encode("utf-8")).hexdigest()[:12]


def _demo_id(tenant_id: str, entity: str, scenario: str = "shared") -> str:
    """生成稳定主键，使重复初始化只补齐缺失记录而不会复制数据。"""
    return f"demo-{_tenant_suffix(tenant_id)}-{entity}-{scenario}"


def demo_evidence_ids(tenant_id: str) -> list[str]:
    """返回当前租户演示证据的稳定主键，供异步索引任务复用。"""
    return [
        _demo_id(tenant_id, "evidence", f"{index:02d}")
        for index in range(1, len(_evidence_rows()) + 1)
    ]


def demo_import_id(tenant_id: str) -> str:
    """返回当前租户演示导入批次的稳定主键。"""
    return _demo_id(tenant_id, "import")


def _summarize_index_status(
    records: Sequence[EvidenceRecord],
) -> tuple[int, int, DemoIndexStatus]:
    """把逐条证据状态汇总为首页可理解的 Milvus 准备状态。"""
    indexed_count = sum(
        record.index_status == EvidenceIndexStatus.INDEXED.value for record in records
    )
    failed_count = sum(
        record.index_status == EvidenceIndexStatus.FAILED.value for record in records
    )
    if records and indexed_count == len(records):
        return indexed_count, failed_count, "indexed"
    if failed_count:
        return indexed_count, failed_count, "failed"
    if any(record.index_status == EvidenceIndexStatus.INDEXING.value for record in records):
        return indexed_count, failed_count, "indexing"
    return indexed_count, failed_count, "pending"


def _evidence_rows() -> list[dict[str, Any]]:
    """返回覆盖市场、竞品、评论、供应和财务的结构化演示证据。"""
    return [
        {
            "data_type": "市场趋势",
            "source_id": "trend-2026-01",
            "product_name": "智能保温杯市场",
            "yoy_rate": 0.186,
            "mom_rate": 0.032,
            "sales": 128000,
            "selling_points": "通勤便携;温度显示;长效保温",
            "content": "2026 年智能保温杯在一二线城市保持增长，通勤便携、温度显示和长效保温是高频关注方向。",
        },
        {
            "data_type": "市场趋势",
            "source_id": "trend-2026-02",
            "product_name": "办公饮水场景",
            "yoy_rate": 0.142,
            "mom_rate": 0.027,
            "sales": 96000,
            "selling_points": "办公室;礼赠;健康饮水",
            "content": (
                "办公与礼赠场景对智能温显和食品级材质的关注提升，"
                "用户愿意为可靠保温和易清洗支付合理溢价。"
            ),
        },
        {
            "data_type": "竞品",
            "source_id": "competitor-a",
            "product_name": "轻量温显杯 A",
            "brand": "竞品甲",
            "price": 159,
            "sales": 18500,
            "rating": 4.6,
            "selling_points": "轻量化;温显;防漏",
            "pain_points": "杯盖难清洗;温度显示耗电",
            "content": "竞品甲主打轻量温显和防漏，销量较高，但评论集中反馈杯盖结构复杂、清洗不便。",
        },
        {
            "data_type": "竞品",
            "source_id": "competitor-b",
            "product_name": "长效保温杯 B",
            "brand": "竞品乙",
            "price": 199,
            "sales": 14200,
            "rating": 4.5,
            "selling_points": "长效保温;食品级材质;大容量",
            "pain_points": "重量偏大;单手开启困难",
            "content": "竞品乙强调长效保温与大容量，适合办公室，但重量和单手开启体验影响日常通勤。",
        },
        {
            "data_type": "竞品",
            "source_id": "competitor-c",
            "product_name": "基础保温杯 C",
            "brand": "竞品丙",
            "price": 99,
            "sales": 23100,
            "rating": 4.2,
            "selling_points": "高性价比;基础保温;耐用",
            "pain_points": "缺少温显;外观同质化",
            "content": "竞品丙依靠低价和基础保温获得销量，但缺少差异化功能，外观与同价位产品高度同质化。",
        },
        {
            "data_type": "竞品",
            "source_id": "competitor-d",
            "product_name": "智能提醒杯 D",
            "brand": "竞品丁",
            "price": 239,
            "sales": 8600,
            "rating": 4.4,
            "selling_points": "饮水提醒;温显;礼赠包装",
            "pain_points": "价格偏高;应用连接复杂",
            "content": "竞品丁提供饮水提醒与礼赠包装，但应用连接流程复杂，用户对高价格的价值感知分化明显。",
        },
        {
            "data_type": "用户评论",
            "source_id": "review-001",
            "product_name": "智能保温杯评论样本",
            "rating": 4.8,
            "demand_tags": "防漏;轻量;易清洗",
            "pain_points": "通勤包内漏水;杯盖缝隙难清洗",
            "content": "用户希望保温杯放入通勤包后完全防漏，同时杯盖可以快速拆洗，避免长时间使用产生异味。",
        },
        {
            "data_type": "用户评论",
            "source_id": "review-002",
            "product_name": "智能保温杯评论样本",
            "rating": 4.7,
            "demand_tags": "温显;单手开启;保温",
            "pain_points": "开车时不便操作;无法判断水温",
            "content": "用户在驾车和会议场景中需要单手开启，并希望无需打开杯盖即可看到当前水温。",
        },
        {
            "data_type": "用户评论",
            "source_id": "review-003",
            "product_name": "智能保温杯评论样本",
            "rating": 4.5,
            "demand_tags": "食品级材质;无异味;耐用",
            "pain_points": "新杯异味;内胆涂层耐久性",
            "content": "消费者关注内胆材质和长期耐用性，希望新品明确食品接触级认证，并降低新杯异味。",
        },
        {
            "data_type": "用户评论",
            "source_id": "review-004",
            "product_name": "智能保温杯评论样本",
            "rating": 4.6,
            "demand_tags": "轻量;握持;外观",
            "pain_points": "大容量杯过重;杯身易滑",
            "content": "女性通勤用户更偏好 450 到 500 毫升容量，要求杯身轻、握持稳定且外观简洁。",
        },
        {
            "data_type": "供应商",
            "source_id": "supplier-a",
            "supplier": "华东智饮制造",
            "product_name": "智能杯供应方案 A",
            "cost": 62,
            "moq": 800,
            "lead_time_days": 28,
            "supplier_rating": 4.7,
            "certifications": ["ISO9001", "食品接触材料检测"],
            "content": "华东智饮制造可提供温显、防漏和 316L 内胆方案，最小起订量 800，常规交期 28 天。",
        },
        {
            "data_type": "供应商",
            "source_id": "supplier-b",
            "supplier": "粤海杯壶科技",
            "product_name": "智能杯供应方案 B",
            "cost": 58,
            "moq": 1200,
            "lead_time_days": 35,
            "supplier_rating": 4.4,
            "certifications": ["ISO9001"],
            "content": "粤海杯壶科技具备成熟杯壶产能，成本具有优势，但起订量与交期高于当前试点需求。",
        },
        {
            "data_type": "成本费用",
            "source_id": "cost-001",
            "product_name": "智能温显通勤杯成本方案",
            "price": 169,
            "cost": 62,
            "logistics_cost": 8,
            "forecast_sales": 5000,
            "content": "智能温显通勤杯建议零售价 169 元，标准单位制造成本 62 元，单件物流成本约 8 元。",
        },
        {
            "data_type": "成本费用",
            "source_id": "cost-002",
            "product_name": "智能温显通勤杯费用假设",
            "price": 179,
            "cost": 66,
            "logistics_cost": 9,
            "forecast_sales": 4200,
            "content": (
                "包含礼盒和升级温显模组的方案建议零售价 179 元，"
                "单位成本约 66 元，预计首批销量 4200 件。"
            ),
        },
        {
            "data_type": "自有商品",
            "source_id": "own-product-001",
            "product_name": "经典保温杯",
            "price": 129,
            "cost": 51,
            "sales": 7800,
            "inventory": 920,
            "selling_points": "耐用;基础保温",
            "content": "现有经典保温杯价格 129 元，用户认可耐用性，但缺少温显和通勤防漏差异化卖点。",
        },
    ]


def _constraints() -> dict[str, Any]:
    """返回能驱动财务、供应和概念服务的完整项目约束。"""
    return {
        "target_user": "25-40 岁城市通勤与办公室人群",
        "selling_price": 169,
        "unit_cost": 62,
        "logistics_cost": 8,
        "platform_fee_rate": 0.08,
        "tax_rate": 0.03,
        "marketing_rate": 0.1,
        "fixed_cost": 120000,
        "forecast_units": 5000,
        "target_margin": 0.42,
        "supplier_name": "华东智饮制造",
        "moq": 800,
        "lead_time_days": 28,
        "max_lead_time_days": 45,
        "supplier_rating": 4.7,
        "certifications": ["ISO9001", "食品接触材料检测"],
        "sample_passed": True,
        "demo_workspace": DEMO_VERSION,
    }


def _research_output(
    records: Sequence[EvidenceRecord],
    *,
    data_types: set[str],
    topic: str,
) -> dict[str, Any]:
    """把数据库证据转换成真实 Agent 检索结果的同构结构。"""
    hits: list[dict[str, Any]] = []
    for record in records:
        metadata = record.metadata_json if isinstance(record.metadata_json, dict) else {}
        normalized = metadata.get("normalized_row")
        row = dict(normalized) if isinstance(normalized, dict) else {}
        if str(row.get("data_type") or "") not in data_types:
            continue
        hits.append(
            {
                "id": record.id,
                "content": record.content,
                "category": row.get("category"),
                "target_market": row.get("target_market"),
                "metadata": metadata,
                "score": round(0.94 - len(hits) * 0.03, 4),
                "source_name": record.source_name,
                "source_row": record.source_row,
            }
        )
    return {
        "status": "ready",
        "query": f"{DEMO_MARKET} {DEMO_CATEGORY} {topic}",
        "hits": hits[:5],
        "evidence_ids": [str(item["id"]) for item in hits[:5]],
        "retrieval_mode": "milvus_reranked_demo_snapshot",
    }


def _execution_snapshot(now: datetime) -> dict[str, Any]:
    """生成页面可读取的节点执行明细，展示当前 LLM Agent 与人工门禁。"""
    nodes: dict[str, Any] = {}
    for index, node_name in enumerate(AGENT_NODES):
        node_time = now - timedelta(minutes=len(AGENT_NODES) - index)
        nodes[node_name] = {
            "node": node_name,
            "status": "completed",
            "attempt": 1,
            "max_attempts": 3,
            "reused": False,
            "started_at": node_time.isoformat(),
            "completed_at": (node_time + timedelta(seconds=18)).isoformat(),
            "updated_at": (node_time + timedelta(seconds=18)).isoformat(),
        }
    return {"nodes": nodes, "updated_at": now.isoformat(), "source": DEMO_VERSION}


def _ready_validation_plan(
    validation_plan: Mapping[str, Any],
    *,
    actor_id: str,
    updated_at: datetime,
) -> dict[str, Any]:
    """通过既有验证更新函数把四道验证门推进为可立项状态。"""
    gates = validation_plan.get("gates")
    gate_values = gates if isinstance(gates, list) else []
    updates = [
        {
            "gate_id": str(gate.get("id") or ""),
            "status": "ready",
            "note": "本地演示材料已由业务人员复核",
        }
        for gate in gate_values
        if isinstance(gate, Mapping) and gate.get("id")
    ]
    ready_plan = apply_candidate_validation_updates(
        validation_plan,
        updates,
        actor_id=actor_id,
        updated_at=updated_at.isoformat(),
    )
    for gate in cast(list[dict[str, Any]], ready_plan.get("gates") or []):
        gate_id = str(gate.get("id") or "validation")
        gate["materials"] = [
            {
                "id": f"demo-material-{gate_id}",
                "filename": f"{gate.get('label') or gate_id}-复核记录.txt",
                "storage_key": f"demo/{gate_id}.txt",
                "note": "本地演示验证材料，仅用于展示人工门禁链路",
                "uploaded_by": actor_id,
                "uploaded_at": updated_at.isoformat(),
            }
        ]
    return ready_plan


def _planning_result(
    records: Sequence[EvidenceRecord],
    *,
    scenario: DemoScenario,
    actor_id: str,
    now: datetime,
) -> dict[str, Any]:
    """复用正式概念、财务、供应和评分服务构造可解释规划结果。"""
    constraints = _constraints()
    requirement = {
        "category": DEMO_CATEGORY,
        "target_market": DEMO_MARKET,
        "constraints": constraints,
        "target_user": str(constraints.get("target_user") or "城市白领"),
        "generation": {
            "status": "degraded",
            "provider": "deterministic-demo",
            "model": None,
            "prompt_version": "2026-09-06.v1",
            "reason": "本地演示不调用外部模型",
        },
    }
    outputs: dict[str, Any] = {
        "requirement": requirement,
        "market": _research_output(records, data_types={"市场趋势"}, topic="市场规模 增长趋势"),
        "competitor": _research_output(records, data_types={"竞品", "自有商品"}, topic="竞品 价格 卖点"),
        "user_insight": _research_output(records, data_types={"用户评论"}, topic="用户 痛点 需求"),
    }
    outputs["research_plan"] = {
        "market_query": f"{DEMO_MARKET} {DEMO_CATEGORY} 市场规模 增长趋势 销量 价格带",
        "competitor_query": f"{DEMO_MARKET} {DEMO_CATEGORY} 竞品 品牌 产品卖点 定价 销量",
        "user_insight_query": f"{DEMO_MARKET} {DEMO_CATEGORY} 目标用户 需求 痛点 评价 使用场景",
        "strategy": {
            "market": "市场规模、增长和价格带优先",
            "competitor": "竞品实体、卖点和价格横向对比",
            "user_insight": "用户痛点、评价和使用场景提取",
        },
        "generation": {
            "status": "degraded",
            "provider": "deterministic-demo",
            "model": None,
            "prompt_version": "2026-09-06.v1",
            "reason": "本地演示不调用外部模型",
        },
    }
    outputs["research_synthesis"] = build_research_synthesis(outputs)
    metrics = build_planning_metrics(records, category=DEMO_CATEGORY, target_market=DEMO_MARKET)
    concept = build_candidate_concepts(requirement, outputs, metrics)
    concept["generation_mode"] = "deterministic_demo"
    concept["generation"] = {
        "status": "degraded",
        "provider": "deterministic-demo",
        "model": None,
        "prompt_version": "2026-09-06.v1",
        "reason": "本地演示不调用外部模型",
    }
    supplier = evaluate_supplier_constraints(constraints, metrics)
    finance = calculate_financials(constraints, metrics)
    scorecard = build_scorecard(
        [str(item) for item in concept.get("evidence_ids", []) if item],
        finance,
        supplier,
        constraints,
        metrics,
    )
    outputs.update({"concept": concept, "supplier": supplier, "finance": finance, "scorecard": scorecard})
    outputs["critic"] = {
        "status": "partial",
        "summary": "演示审查已完成，正式运行会由方案审查 Agent 根据证据逐项反驳。",
        "findings": [
            {
                "candidate_id": str(concept.get("recommended_candidate_id") or "concept-1"),
                "severity": "warning",
                "issue": "温显模组耐久性和杯盖清洗体验仍需样品验证",
                "evidence_ids": concept.get("evidence_ids", []),
                "recommendation": "在审批后完成样品和小批量测试",
            }
        ],
        "recommended_candidate_id": concept.get("recommended_candidate_id"),
        "required_revisions": ["补充温显模组耐久性和清洗体验验证材料"],
        "generation": {
            "status": "degraded",
            "provider": "deterministic-demo",
            "model": None,
            "prompt_version": "2026-09-06.v1",
            "reason": "本地演示不调用外部模型",
        },
    }
    outputs["narrative"] = {
        "status": "ready",
        "provider": "deterministic-demo",
        "model": None,
        "summary": "智能温显通勤杯的证据、供应和财务条件完整，建议优先验证轻量、防漏和易清洗方案。",
        "recommendations": [
            "优先选择轻量通勤款进入业务审批和样品验证。",
            "首批按 800 件起订量验证防漏、温显稳定性与杯盖清洗体验。",
            "试销阶段重点观察转化率、退货率、实际毛利率和用户评分。",
        ],
        "risks": ["温显模组耐久性和杯盖清洗体验仍需以人工验证材料确认。"],
        "evidence_ids": concept.get("evidence_ids", []),
        "prompt_version": "2026-09-06.v1",
        "reason": None,
    }

    if scenario != "planning_approval":
        candidate_id = str(concept.get("recommended_candidate_id") or "concept-1")
        selected_candidate = resolve_candidate_concept(concept, candidate_id) or {}
        selected_concept = apply_candidate_selection(concept, candidate_id, "approved")
        selected_finance = calculate_candidate_financials(selected_candidate, constraints, metrics)
        validation_plan = selected_candidate.get("validation_plan")
        if scenario in {"launch_review", "launched"} and isinstance(validation_plan, Mapping):
            ready_plan = _ready_validation_plan(
                validation_plan,
                actor_id=actor_id,
                updated_at=now,
            )
            candidates = []
            for candidate in selected_concept.get("candidates", []):
                if not isinstance(candidate, Mapping):
                    continue
                updated_candidate = dict(candidate)
                if str(candidate.get("id") or "") == candidate_id:
                    updated_candidate["validation_plan"] = ready_plan
                    updated_candidate["requires_validation"] = False
                candidates.append(updated_candidate)
            selected_concept["candidates"] = candidates
            selected_candidate = (
                resolve_candidate_concept(selected_concept, candidate_id)
                or selected_candidate
            )
            selected_concept["selected_candidate"] = selected_candidate
        outputs["concept"] = selected_concept
        outputs["finance"] = selected_finance
        outputs["selected_candidate_finance"] = selected_finance
        outputs["scorecard"] = build_scorecard(
            [str(item) for item in selected_concept.get("evidence_ids", []) if item],
            selected_finance,
            supplier,
            constraints,
            metrics,
        )

    return {
        "run_id": "",
        "request": {
            "name": "",
            "category": DEMO_CATEGORY,
            "target_market": DEMO_MARKET,
            "constraints": constraints,
        },
        "metrics": metrics,
        "status": "approval_required" if scenario == "planning_approval" else "completed",
        "approval_required": scenario == "planning_approval",
        "outputs": {
            **outputs,
            "approval_gate": {
                "status": "pending_human_review" if scenario == "planning_approval" else "approved",
                "critic_status": outputs["critic"].get("status"),
                "decision_owner": "商品规划负责人",
            },
        },
        "resume_completed_nodes": [],
        "demo_workspace": DEMO_VERSION,
    }


def _milestones(
    *,
    actor_id: str,
    now: datetime,
    launch_review_status: str,
) -> list[dict[str, Any]]:
    """生成符合现有立项顺序约束的五阶段里程碑。"""
    definitions = (
        ("project_kickoff", "立项确认"),
        ("sample_finalize", "样品定版"),
        ("cost_finalize", "成本定版"),
        ("pilot_sale", "小批量试销"),
        ("launch_review", "上市准备评审"),
    )
    result = []
    for index, (milestone_id, label) in enumerate(definitions):
        status = "completed" if milestone_id != "launch_review" else launch_review_status
        result.append(
            {
                "id": milestone_id,
                "label": label,
                "status": status,
                "owner_id": actor_id,
                "due_date": (date.today() + timedelta(days=(index + 1) * 7)).isoformat(),
                "note": "本地演示业务已完成该环节" if status == "completed" else "等待人工上市评审",
                "updated_by": actor_id,
                "updated_at": (now - timedelta(days=max(0, 5 - index))).isoformat(),
            }
        )
    return result


async def _ensure_evidence(
    session: AsyncSession,
    identity: Identity,
    now: datetime,
) -> tuple[DataImportJob, list[EvidenceRecord], bool]:
    """创建一批可被质量治理、规划聚合和向量索引共同使用的证据。"""
    import_id = _demo_id(identity.tenant_id, "import")
    job = await session.get(DataImportJob, import_id)
    created = False
    rows = _evidence_rows()
    if job is None:
        job = DataImportJob(
            id=import_id,
            tenant_id=identity.tenant_id,
            filename="MerchPilot_智能保温杯_演示数据.csv",
            storage_key=f"demo/{_tenant_suffix(identity.tenant_id)}/smart-cup-demo.csv",
            source_type="tabular",
            status=ImportStatus.COMPLETED.value,
            total_rows=len(rows),
            valid_rows=len(rows),
            invalid_rows=0,
            created_by=identity.user_id,
            completed_at=now,
        )
        session.add(job)
        created = True

    records: list[EvidenceRecord] = []
    for index, row in enumerate(rows, start=1):
        evidence_id = _demo_id(identity.tenant_id, "evidence", f"{index:02d}")
        record = await session.get(EvidenceRecord, evidence_id)
        if record is None:
            normalized_row = {
                **row,
                "category": DEMO_CATEGORY,
                "target_market": DEMO_MARKET,
                "observed_at": now.date().isoformat(),
                "data_quality": "A-已核验",
            }
            content = str(row["content"])
            record = EvidenceRecord(
                id=evidence_id,
                tenant_id=identity.tenant_id,
                import_job_id=import_id,
                source_type="tabular",
                source_name=job.filename,
                source_row=index + 1,
                source_id=str(row["source_id"]),
                content=content,
                metadata_json={
                    "normalized_row": normalized_row,
                    "category": DEMO_CATEGORY,
                    "target_market": DEMO_MARKET,
                    "quality_issues": [],
                    "demo_workspace": DEMO_VERSION,
                },
                content_hash=sha256(content.encode("utf-8")).hexdigest(),
                quality_status=EvidenceQualityStatus.VERIFIED.value,
                index_status=EvidenceIndexStatus.PENDING.value,
                observed_at=now,
            )
            session.add(record)
            created = True
        records.append(record)
    if created:
        record_audit_event(
            session,
            action="import.completed",
            entity_type="data_import",
            entity_id=job.id,
            tenant_id=identity.tenant_id,
            actor_id=identity.user_id,
            detail={"filename": job.filename, "valid_rows": len(records), "demo_workspace": True},
        )
    await session.flush()
    return job, records, created


async def _ensure_project(
    session: AsyncSession,
    identity: Identity,
    records: Sequence[EvidenceRecord],
    *,
    scenario: DemoScenario,
    scenario_label: str,
    project_name: str,
    now: datetime,
) -> tuple[LocalDemoProjectRead, bool]:
    """创建一条业务主线，并按场景补齐审批、选品、立项和上市实体。"""
    project_id = _demo_id(identity.tenant_id, "project", scenario)
    run_id = _demo_id(identity.tenant_id, "run", scenario)
    approval_id = _demo_id(identity.tenant_id, "approval", scenario)
    selection_id = _demo_id(identity.tenant_id, "selection", scenario)
    initiative_id = _demo_id(identity.tenant_id, "initiative", scenario)
    review_id = _demo_id(identity.tenant_id, "review", scenario)
    created = False

    project = await session.get(PlanningProject, project_id)
    if project is None:
        project = PlanningProject(
            id=project_id,
            tenant_id=identity.tenant_id,
            name=project_name,
            category=DEMO_CATEGORY,
            target_market=DEMO_MARKET,
            status=(
                ProjectStatus.APPROVAL_REQUIRED.value
                if scenario == "planning_approval"
                else ProjectStatus.COMPLETED.value
            ),
            constraints={**_constraints(), "demo_scenario": scenario},
            created_by=identity.user_id,
        )
        session.add(project)
        # 审计表通过外键关联项目，先落父记录可避免查询触发自动刷盘时顺序不确定。
        await session.flush()
        created = True
        record_audit_event(
            session,
            action="project.created",
            entity_type="planning_project",
            entity_id=project.id,
            project_id=project.id,
            tenant_id=identity.tenant_id,
            actor_id=identity.user_id,
            detail={
                "name": project.name,
                "category": project.category,
                "target_market": project.target_market,
                "demo_scenario": scenario,
            },
        )

    result = _planning_result(records, scenario=scenario, actor_id=identity.user_id, now=now)
    result["run_id"] = run_id
    result["request"]["name"] = project_name
    result["request"]["project_id"] = project_id
    result["request"]["tenant_id"] = identity.tenant_id
    run = await session.get(PlanningRun, run_id)
    if run is None:
        run = PlanningRun(
            id=run_id,
            project_id=project_id,
            revision_no=1,
            thread_id=f"demo-thread-{_tenant_suffix(identity.tenant_id)}-{scenario}",
            status=(
                RunStatus.APPROVAL_REQUIRED.value
                if scenario == "planning_approval"
                else RunStatus.COMPLETED.value
            ),
            input_snapshot=result["request"],
            result_snapshot=result,
            execution_snapshot=_execution_snapshot(now),
            started_at=now - timedelta(minutes=14),
            completed_at=now - timedelta(minutes=2),
        )
        session.add(run)
        created = True
        record_audit_event(
            session,
            action=(
                "run.approval_required"
                if scenario == "planning_approval"
                else "run.completed"
            ),
            entity_type="planning_run",
            entity_id=run.id,
            project_id=project.id,
            tenant_id=identity.tenant_id,
            actor_id=identity.user_id,
            detail={"status": run.status, "demo_scenario": scenario},
        )

    approval = await session.get(ApprovalTask, approval_id)
    if approval is None:
        pending = scenario == "planning_approval"
        selected_candidate_id = str(
            cast(dict[str, Any], result["outputs"]["concept"]).get("selected_candidate_id")
            or cast(dict[str, Any], result["outputs"]["concept"]).get("recommended_candidate_id")
            or "concept-1"
        )
        approval = ApprovalTask(
            id=approval_id,
            project_id=project_id,
            run_id=run_id,
            approval_type="business",
            status=ApprovalStatus.PENDING.value if pending else ApprovalStatus.APPROVED.value,
            checkpoint_ref=f"demo-checkpoint:{run_id}",
            summary={
                "title": "商品规划方案待业务审核",
                "run_id": run_id,
                "project_name": project_name,
                "category": DEMO_CATEGORY,
                "target_market": DEMO_MARKET,
                "outputs": result["outputs"],
            },
            decision=(
                None
                if pending
                else {
                    "action": "approved",
                    "comment": "演示项目已由商品负责人确认进入正式选品",
                    "changes": {"selected_candidate_id": selected_candidate_id},
                }
            ),
            decision_request_id=None if pending else f"demo-approved-{scenario}",
            assignee_id=None if pending else identity.user_id,
            due_at=now + timedelta(hours=6) if pending else now - timedelta(days=4),
            decided_by=None if pending else identity.user_id,
            decided_at=None if pending else now - timedelta(days=4),
        )
        session.add(approval)
        created = True
        record_audit_event(
            session,
            action="approval.created" if pending else "approval.approved",
            entity_type="approval_task",
            entity_id=approval.id,
            project_id=project.id,
            tenant_id=identity.tenant_id,
            actor_id=identity.user_id,
            detail={"status": approval.status, "project_name": project.name},
        )

    selected_product: SelectedProduct | None = None
    if scenario != "planning_approval":
        selected_product = await session.get(SelectedProduct, selection_id)
        if selected_product is None:
            outputs = cast(dict[str, Any], result["outputs"])
            concept = cast(dict[str, Any], outputs["concept"])
            candidate = cast(dict[str, Any], concept.get("selected_candidate") or {})
            validation_plan = cast(dict[str, Any], candidate.get("validation_plan") or {})
            finance = cast(dict[str, Any], outputs.get("selected_candidate_finance") or outputs["finance"])
            supplier = cast(dict[str, Any], outputs["supplier"])
            candidate_score = cast(dict[str, Any], candidate.get("scorecard") or {})
            if scenario == "validation":
                product_status = "validating"
                validation_status = str(validation_plan.get("status") or "partial")
            elif scenario == "launched":
                product_status = "launched"
                validation_status = "ready"
            else:
                product_status = "initiated"
                validation_status = "ready"
            selected_product = SelectedProduct(
                id=selection_id,
                tenant_id=identity.tenant_id,
                project_id=project_id,
                run_id=run_id,
                approval_task_id=approval_id,
                candidate_id=str(candidate.get("id") or "concept-1"),
                name=str(candidate.get("name") or f"{DEMO_CATEGORY}轻量通勤款"),
                project_name=project_name,
                category=DEMO_CATEGORY,
                target_market=DEMO_MARKET,
                positioning=str(candidate.get("positioning") or "轻量、防漏、易清洗的通勤智能杯"),
                status=product_status,
                owner_id=identity.user_id,
                score=round(
                    float(
                        candidate_score.get("total_score")
                        or outputs["scorecard"].get("score")
                        or 82
                    )
                ),
                selling_price=float(finance.get("selling_price") or 169),
                margin_rate=float(finance.get("margin_rate") or 0.47),
                estimated_profit=float(finance.get("estimated_profit") or 210000),
                supplier_name=str(supplier.get("supplier_name") or "华东智饮制造"),
                validation_status=validation_status,
                selection_snapshot=result,
                notes="本地演示项目：可查看候选、证据、财务、验证和完整推进链路。",
                selected_by=identity.user_id,
                selected_at=now - timedelta(days=4),
            )
            session.add(selected_product)
            created = True
            record_audit_event(
                session,
                action="selected_product.created",
                entity_type="selected_product",
                entity_id=selected_product.id,
                project_id=project.id,
                tenant_id=identity.tenant_id,
                actor_id=identity.user_id,
                detail={"name": selected_product.name, "validation_status": validation_status},
            )

    initiative: ProductInitiative | None = None
    launch_review: ProductLaunchReview | None = None
    if scenario in {"launch_review", "launched"} and selected_product is not None:
        initiative = await session.get(ProductInitiative, initiative_id)
        if initiative is None:
            launched = scenario == "launched"
            initiative = ProductInitiative(
                id=initiative_id,
                tenant_id=identity.tenant_id,
                selected_product_id=selected_product.id,
                project_id=project_id,
                run_id=run_id,
                name=selected_product.name,
                category=DEMO_CATEGORY,
                target_market=DEMO_MARKET,
                status="launched" if launched else "launch_ready",
                owner_id=identity.user_id,
                target_launch_date=(
                    date.today() - timedelta(days=14)
                    if launched
                    else date.today() + timedelta(days=35)
                ),
                budget=280000,
                milestones=_milestones(
                    actor_id=identity.user_id,
                    now=now,
                    launch_review_status="completed" if launched else "in_progress",
                ),
                notes="本地演示立项：包含里程碑、试销、上市评审和经营复盘。",
                created_by=identity.user_id,
                launched_at=now - timedelta(days=14) if launched else None,
            )
            session.add(initiative)
            created = True
            record_audit_event(
                session,
                action="product_initiative.created",
                entity_type="product_initiative",
                entity_id=initiative.id,
                project_id=project.id,
                tenant_id=identity.tenant_id,
                actor_id=identity.user_id,
                detail={"selected_product_id": selected_product.id, "name": initiative.name},
            )

        pilot_rows = (
            ("天猫旗舰店", 8200, 512, 568, 95800.0, 35100.0, 12400.0, 3180.0, 18, 4.7),
            ("抖音商城", 12600, 603, 655, 110600.0, 40600.0, 18700.0, 4420.0, 23, 4.6),
        )
        for index, row in enumerate(pilot_rows, start=1):
            pilot_id = _demo_id(identity.tenant_id, f"pilot-{index}", scenario)
            if await session.get(PilotSaleRecord, pilot_id) is None:
                period_end = date.today() - timedelta(days=18 - index * 7)
                session.add(
                    PilotSaleRecord(
                        id=pilot_id,
                        tenant_id=identity.tenant_id,
                        initiative_id=initiative.id,
                        period_start=period_end - timedelta(days=6),
                        period_end=period_end,
                        channel=row[0],
                        visitors=row[1],
                        orders=row[2],
                        units_sold=row[3],
                        revenue=row[4],
                        product_cost=row[5],
                        marketing_spend=row[6],
                        refunds_amount=row[7],
                        return_count=row[8],
                        rating=row[9],
                        notes="本地演示试销周期数据",
                        created_by=identity.user_id,
                    )
                )
                created = True
                record_audit_event(
                    session,
                    action="product_initiative.pilot_sale_recorded",
                    entity_type="pilot_sale",
                    entity_id=pilot_id,
                    project_id=project.id,
                    tenant_id=identity.tenant_id,
                    actor_id=identity.user_id,
                    detail={
                        "initiative_id": initiative.id,
                        "channel": row[0],
                        "period_start": (period_end - timedelta(days=6)).isoformat(),
                        "period_end": period_end.isoformat(),
                    },
                )

        launch_review = await session.get(ProductLaunchReview, review_id)
        if launch_review is None:
            launched = scenario == "launched"
            readiness = {
                "readiness_status": "ready" if launched else "review",
                "readiness_label": "已具备确认上市条件" if launched else "满足上市条件，但需要人工复核",
                "checks": [
                    {
                        "id": "milestones",
                        "label": "前置里程碑",
                        "status": "passed",
                        "detail": "样品、成本和试销已完成",
                    },
                    {
                        "id": "pilot_sales",
                        "label": "试销经营表现",
                        "status": "passed",
                        "detail": "实际毛利与评分达到试点预期",
                    },
                    {
                        "id": "owner",
                        "label": "上市负责人",
                        "status": "passed",
                        "detail": identity.user_id,
                    },
                ],
                "blockers": [],
                "warnings": [] if launched else ["需要审批人确认上市节奏与首批备货量"],
                "recommendations": ["按试销转化率配置首批正式上市库存，并持续跟踪退货率。"],
            }
            launch_review = ProductLaunchReview(
                id=review_id,
                tenant_id=identity.tenant_id,
                initiative_id=initiative.id,
                status="approved" if launched else "pending",
                submission_note="样品、成本和试销已完成，请复核正式上市方案。",
                decision_note="批准按试销结果进入正式上市。" if launched else None,
                readiness_snapshot=readiness,
                submitted_by=identity.user_id,
                submitted_at=now - timedelta(days=16 if launched else 1),
                decided_by=identity.user_id if launched else None,
                decided_at=now - timedelta(days=15) if launched else None,
            )
            session.add(launch_review)
            created = True
            record_audit_event(
                session,
                action=(
                    "product_initiative.launch_review_decided"
                    if launched
                    else "product_initiative.launch_review_submitted"
                ),
                entity_type="product_launch_review",
                entity_id=launch_review.id,
                project_id=project.id,
                tenant_id=identity.tenant_id,
                actor_id=identity.user_id,
                detail={"initiative_id": initiative.id, "status": launch_review.status},
            )

    recommended_module: Literal["approval", "selection", "initiative"]
    if scenario == "planning_approval":
        recommended_module = "approval"
    elif scenario == "validation":
        recommended_module = "selection"
    else:
        recommended_module = "initiative"
    return (
        LocalDemoProjectRead(
            project_id=project_id,
            project_name=project_name,
            category=DEMO_CATEGORY,
            target_market=DEMO_MARKET,
            scenario=scenario,
            scenario_label=scenario_label,
            recommended_module=recommended_module,
            run_id=run_id,
            approval_task_id=approval_id,
            selected_product_id=selected_product.id if selected_product is not None else None,
            initiative_id=initiative.id if initiative is not None else None,
            launch_review_id=launch_review.id if launch_review is not None else None,
        ),
        created,
    )


async def ensure_demo_workspace(
    session: AsyncSession,
    identity: Identity,
) -> LocalDemoWorkspaceRead:
    """为当前租户创建四条演示主线；不清理、不覆盖用户已有业务数据。"""
    now = datetime.now(UTC)
    _job, records, evidence_created = await _ensure_evidence(session, identity, now)
    specifications: tuple[tuple[DemoScenario, str, str], ...] = (
        ("planning_approval", "待规划审批", "演示｜城市通勤智能杯规划"),
        ("validation", "正式选品验证中", "演示｜轻量防漏杯验证"),
        ("launch_review", "待上市评审", "演示｜温显通勤杯上市准备"),
        ("launched", "已上市复盘", "演示｜智能温显杯上市复盘"),
    )
    projects: list[LocalDemoProjectRead] = []
    created = evidence_created
    for scenario, label, name in specifications:
        project, project_created = await _ensure_project(
            session,
            identity,
            records,
            scenario=scenario,
            scenario_label=label,
            project_name=name,
            now=now,
        )
        projects.append(project)
        created = created or project_created
    await session.commit()
    indexed_count, failed_count, index_status = _summarize_index_status(records)
    return LocalDemoWorkspaceRead(
        enabled=True,
        created=created,
        tenant_id=identity.tenant_id,
        evidence_count=len(records),
        indexed_evidence_count=indexed_count,
        failed_evidence_count=failed_count,
        index_status=index_status,
        primary_project_id=projects[0].project_id,
        projects=projects,
        message=(
            "演示工作区已创建，可按四条业务主线从规划审批一直查看到上市复盘。"
            if created
            else "演示工作区已存在，本次未重复创建数据。"
        ),
    )


async def prepare_demo_evidence_indexing(
    session: AsyncSession,
    tenant_id: str,
) -> None:
    """把上次提交失败的演示证据恢复为待索引，供管理员安全重试。"""
    failed_evidence_id = await session.scalar(
        select(EvidenceRecord.id)
        .where(
            EvidenceRecord.id.in_(demo_evidence_ids(tenant_id)),
            EvidenceRecord.index_status == EvidenceIndexStatus.FAILED.value,
        )
        .limit(1)
    )
    if failed_evidence_id is None:
        return
    await session.execute(
        update(EvidenceRecord)
        .where(
            EvidenceRecord.id.in_(demo_evidence_ids(tenant_id)),
            EvidenceRecord.index_status == EvidenceIndexStatus.FAILED.value,
        )
        .values(index_status=EvidenceIndexStatus.PENDING.value)
    )
    job = await session.get(DataImportJob, demo_import_id(tenant_id))
    if job is not None:
        job.error_message = None
        job.index_celery_task_id = None
    await session.commit()


async def mark_demo_index_dispatched(
    session: AsyncSession,
    tenant_id: str,
    task_id: str,
) -> None:
    """记录已提交的索引任务，并提前展示处理中以阻止重复排队。"""
    await session.execute(
        update(EvidenceRecord)
        .where(
            EvidenceRecord.id.in_(demo_evidence_ids(tenant_id)),
            EvidenceRecord.index_status == EvidenceIndexStatus.PENDING.value,
        )
        .values(index_status=EvidenceIndexStatus.INDEXING.value)
    )
    job = await session.get(DataImportJob, demo_import_id(tenant_id))
    if job is not None:
        job.index_celery_task_id = task_id
        job.error_message = None
    await session.commit()


async def mark_demo_index_dispatch_failed(
    session: AsyncSession,
    tenant_id: str,
    error: str,
) -> None:
    """记录演示索引任务提交失败，避免页面长期停留在不真实的处理中。"""
    await session.execute(
        update(EvidenceRecord)
        .where(
            EvidenceRecord.id.in_(demo_evidence_ids(tenant_id)),
            EvidenceRecord.index_status == EvidenceIndexStatus.PENDING.value,
        )
        .values(index_status=EvidenceIndexStatus.FAILED.value)
    )
    job = await session.get(DataImportJob, demo_import_id(tenant_id))
    if job is not None:
        job.error_message = f"Milvus 索引任务提交失败：{error}"
    await session.commit()


async def get_demo_workspace(
    session: AsyncSession,
    identity: Identity,
) -> LocalDemoWorkspaceRead | None:
    """读取当前租户现有演示工作区，不因查询自动创建数据。"""
    project_ids = {
        scenario: _demo_id(identity.tenant_id, "project", scenario)
        for scenario in ("planning_approval", "validation", "launch_review", "launched")
    }
    existing_projects = list(
        await session.scalars(
            select(PlanningProject).where(PlanningProject.id.in_(project_ids.values()))
        )
    )
    if len(existing_projects) != len(project_ids):
        return None
    evidence_records = list(
        await session.scalars(
            select(EvidenceRecord).where(
                EvidenceRecord.id.in_(demo_evidence_ids(identity.tenant_id))
            )
        )
    )
    if len(evidence_records) != len(demo_evidence_ids(identity.tenant_id)):
        return None
    scenario_names = ("planning_approval", "validation", "launch_review", "launched")
    expected_run_ids = {_demo_id(identity.tenant_id, "run", item) for item in scenario_names}
    expected_approval_ids = {
        _demo_id(identity.tenant_id, "approval", item) for item in scenario_names
    }
    expected_selection_ids = {
        _demo_id(identity.tenant_id, "selection", item)
        for item in ("validation", "launch_review", "launched")
    }
    expected_initiative_ids = {
        _demo_id(identity.tenant_id, "initiative", item)
        for item in ("launch_review", "launched")
    }
    expected_review_ids = {
        _demo_id(identity.tenant_id, "review", item)
        for item in ("launch_review", "launched")
    }
    expected_pilot_ids = {
        _demo_id(identity.tenant_id, f"pilot-{index}", scenario)
        for scenario in ("launch_review", "launched")
        for index in (1, 2)
    }
    entity_checks = (
        (
            set(
                await session.scalars(
                    select(PlanningRun.id).where(PlanningRun.id.in_(expected_run_ids))
                )
            ),
            expected_run_ids,
        ),
        (
            set(
                await session.scalars(
                    select(ApprovalTask.id).where(
                        ApprovalTask.id.in_(expected_approval_ids)
                    )
                )
            ),
            expected_approval_ids,
        ),
        (
            set(
                await session.scalars(
                    select(SelectedProduct.id).where(
                        SelectedProduct.id.in_(expected_selection_ids)
                    )
                )
            ),
            expected_selection_ids,
        ),
        (
            set(
                await session.scalars(
                    select(ProductInitiative.id).where(
                        ProductInitiative.id.in_(expected_initiative_ids)
                    )
                )
            ),
            expected_initiative_ids,
        ),
        (
            set(
                await session.scalars(
                    select(ProductLaunchReview.id).where(
                        ProductLaunchReview.id.in_(expected_review_ids)
                    )
                )
            ),
            expected_review_ids,
        ),
        (
            set(
                await session.scalars(
                    select(PilotSaleRecord.id).where(
                        PilotSaleRecord.id.in_(expected_pilot_ids)
                    )
                )
            ),
            expected_pilot_ids,
        ),
    )
    if any(actual != expected for actual, expected in entity_checks):
        return None
    specifications: tuple[tuple[DemoScenario, str, str], ...] = (
        ("planning_approval", "待规划审批", "演示｜城市通勤智能杯规划"),
        ("validation", "正式选品验证中", "演示｜轻量防漏杯验证"),
        ("launch_review", "待上市评审", "演示｜温显通勤杯上市准备"),
        ("launched", "已上市复盘", "演示｜智能温显杯上市复盘"),
    )
    projects = [
        LocalDemoProjectRead(
            project_id=project_ids[scenario],
            project_name=name,
            category=DEMO_CATEGORY,
            target_market=DEMO_MARKET,
            scenario=scenario,
            scenario_label=label,
            recommended_module=(
                "approval"
                if scenario == "planning_approval"
                else "selection"
                if scenario == "validation"
                else "initiative"
            ),
            run_id=_demo_id(identity.tenant_id, "run", scenario),
            approval_task_id=_demo_id(identity.tenant_id, "approval", scenario),
            selected_product_id=(
                None
                if scenario == "planning_approval"
                else _demo_id(identity.tenant_id, "selection", scenario)
            ),
            initiative_id=(
                _demo_id(identity.tenant_id, "initiative", scenario)
                if scenario in {"launch_review", "launched"}
                else None
            ),
            launch_review_id=(
                _demo_id(identity.tenant_id, "review", scenario)
                if scenario in {"launch_review", "launched"}
                else None
            ),
        )
        for scenario, label, name in specifications
    ]
    indexed_count, failed_count, index_status = _summarize_index_status(evidence_records)
    return LocalDemoWorkspaceRead(
        enabled=True,
        created=False,
        tenant_id=identity.tenant_id,
        evidence_count=len(evidence_records),
        indexed_evidence_count=indexed_count,
        failed_evidence_count=failed_count,
        index_status=index_status,
        primary_project_id=projects[0].project_id,
        projects=projects,
        message="演示工作区已就绪。",
    )
