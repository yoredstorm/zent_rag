# =============================================================================
# Learning cycle — Finding, Hypothesis, Experiment, Evaluation, Recommendation.
# =============================================================================
# Telemetría operacional entra como RunSignal. Nada de esta capa muta
# producción. La promoción es un acto administrativo aparte.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


class WindowName(StrEnum):
    LAST_HOUR = "last_hour"
    LAST_24H = "24h"
    LAST_7D = "7d"
    LAST_30D = "30d"
    ALL_TIME = "all_time"


class FindingStatus(StrEnum):
    OPEN = "open"
    HYPOTHESIZED = "hypothesized"
    EXPERIMENTING = "experimenting"
    RECOMMENDED = "recommended"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class FindingSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class HypothesisStatus(StrEnum):
    PROPOSED = "proposed"
    TESTING = "testing"
    SUPPORTED = "supported"
    REJECTED = "rejected"


class ExperimentMode(StrEnum):
    GOLDEN_SET = "golden_set"
    SHADOW = "shadow"
    REPLAY = "replay"


class ExperimentKind(StrEnum):
    RETRIEVAL_STRATEGY = "retrieval_strategy"
    TOP_K = "top_k"
    RERANKER = "reranker"
    JEV = "jev"
    JEV_MODEL = "jev_model"
    ROUTING_THRESHOLD = "routing_threshold"
    LLM_MODEL = "llm_model"
    CHUNKING = "chunking"
    STRUCTURED_NORMALIZATION = "structured_normalization"
    AGENT_RETRY_POLICY = "agent_retry_policy"
    WORKFLOW_ROUTE = "workflow_route"


class ExperimentStatus(StrEnum):
    QUEUED = "queued"
    COMPLETED = "completed"
    REJECTED = "rejected"


class RecommendationAction(StrEnum):
    PROMOTE = "promote"
    CONTINUE_TESTING = "continue_testing"
    REJECT = "reject"


class RecommendationStatus(StrEnum):
    PENDING = "pending"
    PROMOTED = "promoted"
    CONTINUED = "continued"
    REJECTED = "rejected"


@dataclass(kw_only=True)
class RunSignal:
    """Una ejecución normalizada. No es chain-of-thought ni un documento."""

    organization_id: UUID
    pattern_key: str
    id: UUID = field(default_factory=uuid4)
    intent_family: str = ""
    source_type: str = ""
    source_name: str = ""
    retrieval_strategy: str = ""
    route_label: str = ""
    tool_family: str = ""
    failure_code: str = ""
    success: bool | None = None
    retrieval_successful: bool | None = None
    evidence_sufficient: bool | None = None
    answer_grounded: bool | None = None
    claims_supported: bool | None = None
    tool_succeeded: bool | None = None
    agent_completed: bool | None = None
    workflow_completed: bool | None = None
    retried: bool = False
    fallback: bool = False
    human_accepted: bool | None = None
    explicit_feedback: str | None = None
    quality: float | None = None
    grounding: float | None = None
    task_success: float | None = None
    cost: float = 0.0
    latency_ms: float = 0.0
    tokens: int = 0
    jev_calls: int = 0
    tool_sequence: tuple[str, ...] = ()
    tool_errors: tuple[str, ...] = ()
    jev_capability: str = ""
    executed_capability: str = ""
    occurred_at: datetime = field(default_factory=_utcnow)
    clustered: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.pattern_key).strip():
            raise ValueError("RunSignal.pattern_key must not be empty")
        if isinstance(self.tool_sequence, list):
            self.tool_sequence = tuple(self.tool_sequence)
        if isinstance(self.tool_errors, list):
            self.tool_errors = tuple(self.tool_errors)


@dataclass(kw_only=True)
class Finding:
    organization_id: UUID
    category: str
    severity: FindingSeverity
    pattern_key: str
    observed: str
    alternative: str
    baseline_strategy: str
    candidate_strategy: str
    sample_size: int
    window: str
    confidence: str
    dedupe_key: str
    id: UUID = field(default_factory=uuid4)
    status: FindingStatus = FindingStatus.OPEN
    first_seen: datetime = field(default_factory=_utcnow)
    last_seen: datetime = field(default_factory=_utcnow)
    evidence: list[str] = field(default_factory=list)
    affected: list[str] = field(default_factory=list)
    impact: dict[str, Any] = field(default_factory=dict)
    baseline_rate: float | None = None
    candidate_rate: float | None = None
    memory_id: UUID | None = None

    def __post_init__(self) -> None:
        if isinstance(self.severity, str):
            self.severity = FindingSeverity(self.severity)
        if isinstance(self.status, str):
            self.status = FindingStatus(self.status)
        if self.sample_size < 1:
            raise ValueError("Finding.sample_size must be >= 1")
        if not self.dedupe_key.strip():
            raise ValueError("Finding.dedupe_key must not be empty")

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "organization_id": str(self.organization_id),
            "category": self.category,
            "severity": self.severity.value,
            "pattern_key": self.pattern_key,
            "status": self.status.value,
            "observed": self.observed,
            "alternative": self.alternative,
            "baseline_strategy": self.baseline_strategy,
            "candidate_strategy": self.candidate_strategy,
            "baseline_rate": self.baseline_rate,
            "candidate_rate": self.candidate_rate,
            "sample_size": self.sample_size,
            "window": self.window,
            "confidence": self.confidence,
            "first_seen": _iso(self.first_seen),
            "last_seen": _iso(self.last_seen),
            "evidence": list(self.evidence),
            "affected": list(self.affected),
            "impact": dict(self.impact),
            "memory_id": str(self.memory_id) if self.memory_id else None,
        }


@dataclass(kw_only=True)
class Hypothesis:
    """Falsable: baseline, candidato, métrica, mejora mínima y alcance."""

    organization_id: UUID
    finding_id: UUID
    statement: str
    baseline: str
    candidate: str
    expected_metric: str
    minimum_improvement: float
    scope: str
    id: UUID = field(default_factory=uuid4)
    guardrails: dict[str, float] = field(default_factory=dict)
    status: HypothesisStatus = HypothesisStatus.PROPOSED
    falsifiable: bool = True

    def __post_init__(self) -> None:
        if isinstance(self.status, str):
            self.status = HypothesisStatus(self.status)
        if not self.baseline.strip() or not self.candidate.strip():
            raise ValueError("hypothesis requires baseline and candidate")
        if self.baseline.strip() == self.candidate.strip():
            raise ValueError("hypothesis candidate must differ from baseline")
        if not self.expected_metric.strip():
            raise ValueError("hypothesis requires an expected metric")
        if float(self.minimum_improvement) <= 0:
            raise ValueError("hypothesis requires a positive minimum improvement")
        if not self.scope.strip():
            raise ValueError("hypothesis requires a scope")
        if not self.statement.strip():
            raise ValueError("hypothesis requires a statement")
        self.falsifiable = True

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "organization_id": str(self.organization_id),
            "finding_id": str(self.finding_id),
            "statement": self.statement,
            "baseline": self.baseline,
            "candidate": self.candidate,
            "expected_metric": self.expected_metric,
            "minimum_improvement": self.minimum_improvement,
            "scope": self.scope,
            "guardrails": dict(self.guardrails),
            "status": self.status.value,
            "falsifiable": self.falsifiable,
        }


@dataclass(kw_only=True)
class ToolStep:
    name: str
    execution: str
    side_effect: bool = False

    def __post_init__(self) -> None:
        self.name = self.name.strip()
        self.execution = self.execution.strip().lower()
        if self.execution not in {"mock", "dry_run", "simulation", "live"}:
            raise ValueError(f"unsupported tool execution {self.execution}")


@dataclass(kw_only=True)
class ExperimentRequest:
    organization_id: UUID
    hypothesis_id: UUID
    finding_id: UUID
    mode: ExperimentMode
    kind: ExperimentKind
    baseline: str
    candidate: str
    id: UUID = field(default_factory=uuid4)
    tool_plan: tuple[ToolStep, ...] = ()
    status: ExperimentStatus = ExperimentStatus.QUEUED
    memory_id: UUID | None = None
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if isinstance(self.mode, str):
            self.mode = ExperimentMode(self.mode)
        if isinstance(self.kind, str):
            self.kind = ExperimentKind(self.kind)
        if isinstance(self.status, str):
            self.status = ExperimentStatus(self.status)
        if isinstance(self.tool_plan, list):
            self.tool_plan = tuple(self.tool_plan)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "organization_id": str(self.organization_id),
            "hypothesis_id": str(self.hypothesis_id),
            "finding_id": str(self.finding_id),
            "mode": self.mode.value,
            "kind": self.kind.value,
            "baseline": self.baseline,
            "candidate": self.candidate,
            "status": self.status.value,
            "memory_id": str(self.memory_id) if self.memory_id else None,
            "tool_plan": [
                {"name": step.name, "execution": step.execution, "side_effect": step.side_effect}
                for step in self.tool_plan
            ],
            "mutates_production": False,
            "created_at": _iso(self.created_at),
        }


@dataclass(kw_only=True)
class MetricSample:
    retrieval_recall: float | None = None
    retrieval_precision: float | None = None
    evidence_sufficiency: float | None = None
    grounding: float | None = None
    claim_support: float | None = None
    task_success: float | None = None
    quality: float | None = None
    agent_completion: float | None = None
    tool_errors: float | None = None
    latency_ms: float | None = None
    cost: float | None = None
    tokens: float | None = None
    jev_calls: float | None = None
    fallbacks: float | None = None


HIGHER_IS_BETTER = frozenset(
    {
        "retrieval_recall",
        "retrieval_precision",
        "evidence_sufficiency",
        "grounding",
        "claim_support",
        "task_success",
        "quality",
        "agent_completion",
    }
)
LOWER_IS_BETTER = frozenset(
    {"tool_errors", "latency_ms", "cost", "tokens", "jev_calls", "fallbacks"}
)


@dataclass(kw_only=True)
class EvaluationRecord:
    organization_id: UUID
    experiment_id: UUID
    sample_size: int
    baseline_means: dict[str, float | None]
    candidate_means: dict[str, float | None]
    deltas: dict[str, float | None]
    id: UUID = field(default_factory=uuid4)
    confidence: str = "low"
    reproducible: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "organization_id": str(self.organization_id),
            "experiment_id": str(self.experiment_id),
            "sample_size": self.sample_size,
            "confidence": self.confidence,
            "baseline_means": dict(self.baseline_means),
            "candidate_means": dict(self.candidate_means),
            "deltas": dict(self.deltas),
            "reproducible": dict(self.reproducible),
            "created_at": _iso(self.created_at),
        }


@dataclass(kw_only=True)
class Recommendation:
    organization_id: UUID
    experiment_id: UUID
    evaluation_id: UUID
    finding_id: UUID
    hypothesis_id: UUID
    problem: str
    baseline: str
    candidate: str
    suggested_action: RecommendationAction
    explanation: str
    sample_size: int
    confidence: str
    deltas: dict[str, float | None]
    id: UUID = field(default_factory=uuid4)
    status: RecommendationStatus = RecommendationStatus.PENDING
    memory_id: UUID | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if isinstance(self.suggested_action, str):
            self.suggested_action = RecommendationAction(self.suggested_action)
        if isinstance(self.status, str):
            self.status = RecommendationStatus(self.status)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "organization_id": str(self.organization_id),
            "experiment_id": str(self.experiment_id),
            "evaluation_id": str(self.evaluation_id),
            "finding_id": str(self.finding_id),
            "hypothesis_id": str(self.hypothesis_id),
            "memory_id": str(self.memory_id) if self.memory_id else None,
            "problem": self.problem,
            "baseline": self.baseline,
            "candidate": self.candidate,
            "suggested_action": self.suggested_action.value,
            "status": self.status.value,
            "explanation": self.explanation,
            "sample_size": self.sample_size,
            "confidence": self.confidence,
            "deltas": dict(self.deltas),
            "metrics": dict(self.metrics),
            "actions": ["promote", "continue_testing", "reject"],
            "autonomous_production_mutation": False,
            "created_at": _iso(self.created_at),
        }


@dataclass(kw_only=True)
class PromotionAudit:
    organization_id: UUID
    actor_id: UUID
    recommendation_id: UUID
    experiment_id: UUID
    baseline: str
    candidate: str
    metrics: dict[str, Any]
    id: UUID = field(default_factory=uuid4)
    memory_id: UUID | None = None
    config_mutated: bool = False
    previous_snapshot: dict[str, Any] = field(default_factory=dict)
    applied_snapshot: dict[str, Any] = field(default_factory=dict)
    acted_at: datetime = field(default_factory=_utcnow)
    rolled_back_at: datetime | None = None
    rolled_back_by: UUID | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "organization_id": str(self.organization_id),
            "actor_id": str(self.actor_id),
            "acted_at": _iso(self.acted_at),
            "recommendation_id": str(self.recommendation_id),
            "experiment_id": str(self.experiment_id),
            "memory_id": str(self.memory_id) if self.memory_id else None,
            "baseline": self.baseline,
            "candidate": self.candidate,
            "metrics": dict(self.metrics),
            "config_mutated": self.config_mutated,
            "previous_snapshot": dict(self.previous_snapshot),
            "applied_snapshot": dict(self.applied_snapshot),
            "rolled_back_at": _iso(self.rolled_back_at),
            "rolled_back_by": str(self.rolled_back_by) if self.rolled_back_by else None,
        }


@dataclass(kw_only=True)
class StrategyComparison:
    organization_id: UUID
    pattern_key: str
    window: str
    kind: str
    rows: list[dict[str, Any]]
    sample_size: int
    confidence: str
    id: UUID = field(default_factory=uuid4)
    validated_memory_id: UUID | None = None
    judgment_signal: bool = False
    production_policy_controls_execution: bool = True

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "organization_id": str(self.organization_id),
            "pattern_key": self.pattern_key,
            "window": self.window,
            "kind": self.kind,
            "rows": list(self.rows),
            "sample_size": self.sample_size,
            "confidence": self.confidence,
            "validated_memory_id": str(self.validated_memory_id) if self.validated_memory_id else None,
            "judgment_signal": self.judgment_signal,
            "production_policy_controls_execution": True,
        }
