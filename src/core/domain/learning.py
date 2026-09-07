# =============================================================================
# Domain Layer — Governed Learning (FASE 25)
# =============================================================================
# Entidades puras del ciclo: Context Gaps, Improvements, Approvals, Replays,
# Spider policies/runs, conflicts. Sin dependencias externas.
# Principio: LLM inference != truth; Inferred != Approved.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class ContextGapType(StrEnum):
    MISSING_SOURCE = "MISSING_SOURCE"
    MISSING_TABLE = "MISSING_TABLE"
    MISSING_FIELD = "MISSING_FIELD"
    MISSING_RELATIONSHIP = "MISSING_RELATIONSHIP"
    MISSING_BUSINESS_TERM = "MISSING_BUSINESS_TERM"
    MISSING_METRIC = "MISSING_METRIC"
    UNDEFINED_ENUM = "UNDEFINED_ENUM"
    AMBIGUOUS_TERM = "AMBIGUOUS_TERM"
    STALE_SOURCE = "STALE_SOURCE"
    LOW_DATA_QUALITY = "LOW_DATA_QUALITY"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    PERMISSION_LIMITATION = "PERMISSION_LIMITATION"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"


class ImprovementStatus(StrEnum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"
    BLOCKED = "BLOCKED"


class PriorityLevel(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ApprovalAction(StrEnum):
    APPROVE = "approve"
    REJECTED = "reject"
    EDIT_APPROVE = "edit_approve"


class ReplayVerdict(StrEnum):
    PASSED = "pass"
    WARN = "warn"
    FAIL = "fail"
    UNKNOWN = "unknown"


@dataclass(kw_only=True)
class ContextGap:
    """Gap estructurado derivado de consultas no contestables."""

    id: UUID = field(default_factory=uuid4)
    organization_id: UUID
    gap_type: ContextGapType
    concept: str
    question: str | None = None
    evidence_hints: list[str] = field(default_factory=list)
    impact: dict = field(default_factory=dict)
    occurrences: int = 1
    status: str = "open"  # open | resolved | acknowledged
    first_seen_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_by: UUID | None = None
    resolved_at: datetime | None = None


@dataclass(kw_only=True)
class ImprovementItem:
    """Item del backlog centralizado de mejoras de inteligencia."""

    id: UUID = field(default_factory=uuid4)
    organization_id: UUID
    priority: PriorityLevel = PriorityLevel.MEDIUM
    gap_type: str = ""
    title: str
    description: str | None = None
    evidence: list[str] = field(default_factory=list)
    affected_queries: int = 0
    affected_users: int = 0
    affected_agents: int = 0
    affected_sources: list[str] = field(default_factory=list)
    recommended_action: str | None = None
    estimated_impact: dict = field(default_factory=dict)
    status: ImprovementStatus = ImprovementStatus.OPEN
    owner: str | None = None
    suggested_concept: str | None = None
    cluster_key: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: datetime | None = None


@dataclass(kw_only=True)
class ApprovalRecord:
    """Registro de aprobación: who / when / why / evidencia / versiones."""

    id: UUID = field(default_factory=uuid4)
    organization_id: UUID
    knowledge_type: str  # metric | relationship | glossary | enum | authority | entity | field
    knowledge_id: str
    action: ApprovalAction
    acted_by: UUID | None = None
    reason: str | None = None
    source_evidence: list[str] = field(default_factory=list)
    previous_version: dict = field(default_factory=dict)
    new_version: dict = field(default_factory=dict)
    replay_id: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(kw_only=True)
class LearningReplay:
    """Evaluation Replay: antes/después de un cambio de conocimiento."""

    id: UUID = field(default_factory=uuid4)
    organization_id: UUID
    knowledge_type: str
    knowledge_id: str
    trigger: str = "manual"  # auto | manual
    eval_run_id: UUID | None = None
    baseline_run_id: UUID | None = None
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)
    verdict: ReplayVerdict = ReplayVerdict.UNKNOWN
    status: str = "queued"  # queued | running | completed | failed
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(kw_only=True)
class SourceConflictRecord:
    """Conflicto entre fuentes (registrado incluso si la autoridad lo resuelve)."""

    id: UUID = field(default_factory=uuid4)
    organization_id: UUID
    concept: str
    question: str | None = None
    source_a: str
    value_a: Any = None
    source_b: str
    value_b: Any = None
    resolved_by_authority: bool = False
    authority_source: str | None = None
    status: str = "recorded"  # recorded | resolved
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(kw_only=True)
class SpiderPolicy:
    """Política de discovery autorizado y limitado (Zent Spider)."""

    id: UUID = field(default_factory=uuid4)
    organization_id: UUID
    name: str
    enabled: bool = True
    schedule_hours: int = 24
    allowed_source_ids: list[str] = field(default_factory=list)  # [] = todos los del tenant
    allowed_schemas: list[str] = field(default_factory=list)  # [] = todos los descubiertos
    excluded_objects: list[str] = field(default_factory=list)
    profiling_level: str = "standard"  # none | standard | deep
    max_cost: int = 500
    max_duration_min: int = 60
    sampling_policy: str = "conservative"  # none | conservative | standard
    pii_policy: str = "never"  # never | mask
    created_by: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(kw_only=True)
class SpiderRun:
    """Ejecución de una política de Spider (findings detectados)."""

    id: UUID = field(default_factory=uuid4)
    organization_id: UUID
    policy_id: UUID
    status: str = "running"  # running | completed | failed | cancelled
    findings: list[dict] = field(default_factory=list)
    duration_ms: float = 0.0
    error: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None


@dataclass(kw_only=True)
class AgentReadiness:
    """Intelligence Readiness de un agente (caché operativa)."""

    id: UUID = field(default_factory=uuid4)
    organization_id: UUID
    agent_id: UUID
    overall: str = "LOW"  # HIGH | MEDIUM | LOW | INSUFFICIENT
    score: float = 0.0
    dimensions: dict = field(default_factory=dict)
    computed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
