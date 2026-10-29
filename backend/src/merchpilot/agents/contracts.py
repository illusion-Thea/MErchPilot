"""文件职责：定义 LLM Agent 的结构化输入输出契约。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RequirementAnalysis(BaseModel):
    """需求理解 Agent 的结构化产出。"""

    category: str = ""
    target_market: str = ""
    target_user: str = ""
    constraints: dict[str, Any] = Field(default_factory=dict)
    core_constraints: list[str] = Field(default_factory=list)
    success_metrics: list[str] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class ResearchPlan(BaseModel):
    """研究规划 Agent 的结构化产出。"""

    market_query: str = ""
    competitor_query: str = ""
    user_insight_query: str = ""
    strategy: dict[str, str] = Field(default_factory=dict)
    follow_up_queries: dict[str, list[str]] = Field(default_factory=dict)
    evidence_requirements: dict[str, list[str]] = Field(default_factory=dict)
    rationale: str = ""


class ConceptDraft(BaseModel):
    """概念生成 Agent 输出的单个候选方案草案。"""

    id: str = ""
    name: str = ""
    positioning: str = ""
    target_user: str = ""
    evidence_features: list[str] = Field(default_factory=list)
    pain_points_addressed: list[str] = Field(default_factory=list)
    feature_hypotheses: list[str] = Field(default_factory=list)
    specification_suggestions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    validation_items: list[str] = Field(default_factory=list)
    price_reference: dict[str, Any] = Field(default_factory=dict)
    unit_cost_reference: float | None = None
    differentiation_hypothesis: str = ""
    risks: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "medium"
    evidence_ids: list[str] = Field(default_factory=list)


class ConceptDraftSet(BaseModel):
    """概念生成 Agent 的候选方案集合。"""

    candidates: list[ConceptDraft] = Field(default_factory=list)
    rationale: str = ""


class CriticFinding(BaseModel):
    """方案审查 Agent 发现的一条问题。"""

    candidate_id: str = "global"
    severity: Literal["blocker", "warning", "info"] = "warning"
    issue: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    recommendation: str = ""


class CriticReview(BaseModel):
    """方案审查 Agent 的结构化产出。"""

    status: Literal["ready", "partial", "blocked"] = "partial"
    summary: str = ""
    findings: list[CriticFinding] = Field(default_factory=list)
    recommended_candidate_id: str | None = None
    required_revisions: list[str] = Field(default_factory=list)


class NarrativeOutput(BaseModel):
    """规划报告 Agent 的结构化产出。"""

    summary: str = ""
    recommendations: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class MultimodalEvidenceItem(BaseModel):
    """Qwen 多模态抽取的一条可追溯证据。"""

    title: str = ""
    content: str = ""
    category: str = ""
    target_market: str = ""
    target_user: str = ""
    data_type: str = "document_extract"
    observed_at: str = ""
    evidence_tags: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "medium"
    needs_review: bool = True


class MultimodalEvidenceBatch(BaseModel):
    """Qwen 多模态抽取结果集合，作为非结构化文件进入证据库前的契约。"""

    items: list[MultimodalEvidenceItem] = Field(default_factory=list)
    summary: str = ""
