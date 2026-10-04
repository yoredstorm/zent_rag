# =============================================================================
# Knowledge Nutrition — contratos
# =============================================================================
# Feedback es una SEÑAL, no una verdad. Ninguna acción de nutrition modifica
# conocimiento canónico de forma destructiva automática: las acciones son
# propuestas con evidencia, confianza y versión de política.
# =============================================================================
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum


class FailureType(StrEnum):
    RETRIEVAL_MISS = "RETRIEVAL_MISS"
    BAD_RANK = "BAD_RANK"
    MISSING_KNOWLEDGE = "MISSING_KNOWLEDGE"
    STALE_KNOWLEDGE = "STALE_KNOWLEDGE"
    PARSER_FAILURE = "PARSER_FAILURE"
    RECONSTRUCTION_FAILURE = "RECONSTRUCTION_FAILURE"
    ENTITY_RESOLUTION_FAILURE = "ENTITY_RESOLUTION_FAILURE"
    CONFLICT = "CONFLICT"
    AMBIGUOUS_QUERY = "AMBIGUOUS_QUERY"
    ANSWER_GENERATION_FAILURE = "ANSWER_GENERATION_FAILURE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    WRONG_SOURCE = "WRONG_SOURCE"
    ACL_FILTERED = "ACL_FILTERED"
    TEMPORAL_MISMATCH = "TEMPORAL_MISMATCH"


class NutritionActionType(StrEnum):
    GENERATE_RETRIEVAL_ALIASES = "GENERATE_RETRIEVAL_ALIASES"
    RECOMPUTE_RETRIEVAL_REPRESENTATION = "RECOMPUTE_RETRIEVAL_REPRESENTATION"
    SELECTIVE_REINDEX = "SELECTIVE_REINDEX"
    RECORD_RANKING_SIGNAL = "RECORD_RANKING_SIGNAL"
    KNOWLEDGE_GAP = "KNOWLEDGE_GAP"
    SOURCE_REFRESH_REQUEST = "SOURCE_REFRESH_REQUEST"
    INGESTION_QUALITY_REVIEW = "INGESTION_QUALITY_REVIEW"
    RECONSTRUCTION_QUEUE = "RECONSTRUCTION_QUEUE"
    ALIAS_CANDIDATE_REVIEW = "ALIAS_CANDIDATE_REVIEW"
    TEMPORAL_ASSERTION_REVIEW = "TEMPORAL_ASSERTION_REVIEW"
    SOURCE_AUTHORITY_SIGNAL = "SOURCE_AUTHORITY_SIGNAL"
    CONFLICT_REVIEW = "CONFLICT_REVIEW"
    ANSWER_PIPELINE_REVIEW = "ANSWER_PIPELINE_REVIEW"
    EVIDENCE_REVIEW = "EVIDENCE_REVIEW"
    QUERY_REFINEMENT_SIGNAL = "QUERY_REFINEMENT_SIGNAL"
    ACL_AUDIT = "ACL_AUDIT"


class NutritionActionStatus(StrEnum):
    OBSERVED = "observed"      # señal débil: solo se registra
    PROPOSED = "proposed"      # requiere revisión/aprobación
    APPLIED = "applied"        # aplicada de forma no destructiva e idempotente
    REJECTED = "rejected"


NUTRITION_POLICY_VERSION = "nutrition-policy-1"
NUTRITION_SCORE_VERSION = "nutrition-score-1"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, kw_only=True)
class FailureSignals:
    """Señales REALES del run (retrieval, evidencia, gate, feedback)."""

    query: str = ""
    retrieved_chunks: int = 0
    top_score: float | None = None
    evidence_used: int = 0
    citations: int = 0
    answer_gate: str | None = None
    planner_path: str | None = None
    feedback_rating: str | None = None
    feedback_reason: str | None = None
    lexical_hit: bool | None = None
    semantic_hit: bool | None = None
    evidence_rank: int | None = None
    no_source_match: bool | None = None
    wrong_source: bool | None = None
    acl_filtered: bool | None = None
    temporal_mismatch: bool | None = None
    stale: bool | None = None
    conflict: bool | None = None
    entity_unresolved: bool | None = None
    parser_quality: float | None = None
    reconstruction_quality: float | None = None
    source_id: str | None = None
    document_id: str | None = None
    workspace_id: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class FailureClassification:
    failure_type: str
    confidence: float
    reason: str
    policy_version: str = NUTRITION_POLICY_VERSION
    signals: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "failure_type": self.failure_type,
            "confidence": round(float(self.confidence), 4),
            "reason": self.reason,
            "policy_version": self.policy_version,
            "signals": dict(self.signals),
        }


@dataclass(frozen=True, kw_only=True)
class NutritionAction:
    """Acción propuesta. `destructive=False` SIEMPRE en esta capa."""

    action_type: str
    failure_type: str
    reason: str
    confidence: float = 0.0
    status: str = NutritionActionStatus.PROPOSED.value
    organization_id: str | None = None
    workspace_id: str | None = None
    source_id: str | None = None
    document_id: str | None = None
    query: str | None = None
    evidence: dict = field(default_factory=dict)
    policy_version: str = NUTRITION_POLICY_VERSION
    model_version: str | None = None
    destructive: bool = False
    requires_review: bool = True
    duration_ms: float = 0.0
    created_at: datetime = field(default_factory=_utcnow)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        return data


@dataclass(frozen=True, kw_only=True)
class NutritionDimensions:
    """Dimensiones del score. None = NO MEDIDA (nunca se trata como 0)."""

    structure_quality: float | None = None
    reconstruction_quality: float | None = None
    evidence_coverage: float | None = None
    semantic_coverage: float | None = None
    entity_linkage: float | None = None
    relationship_coverage: float | None = None
    temporal_quality: float | None = None
    freshness: float | None = None
    retrievability: float | None = None
    demand_coverage: float | None = None

    def measured(self) -> dict[str, float]:
        return {
            key: float(value)
            for key, value in asdict(self).items()
            if value is not None
        }

    def to_dict(self) -> dict:
        return asdict(self)


NUTRITION_WEIGHTS: dict[str, float] = {
    "structure_quality": 0.12,
    "reconstruction_quality": 0.14,
    "evidence_coverage": 0.16,
    "semantic_coverage": 0.12,
    "entity_linkage": 0.08,
    "relationship_coverage": 0.06,
    "temporal_quality": 0.06,
    "freshness": 0.06,
    "retrievability": 0.14,
    "demand_coverage": 0.06,
}


@dataclass(frozen=True, kw_only=True)
class NutritionScore:
    scope: str = "document"  # document | source | knowledge_area | workspace
    scope_id: str = ""
    dimensions: NutritionDimensions = field(default_factory=NutritionDimensions)
    nutrition_score: float | None = None
    formula_version: str = NUTRITION_SCORE_VERSION
    weights: dict = field(default_factory=lambda: dict(NUTRITION_WEIGHTS))
    measured_dimensions: int = 0
    total_dimensions: int = len(NUTRITION_WEIGHTS)
    computed_at: datetime = field(default_factory=_utcnow)
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        measured = self.dimensions.measured()
        return {
            "scope": self.scope,
            "scope_id": self.scope_id,
            "dimensions": {
                **self.dimensions.to_dict(),
                "nutrition_score": self.nutrition_score,
            },
            "measured_dimensions": self.measured_dimensions,
            "total_dimensions": self.total_dimensions,
            "formula_version": self.formula_version,
            "weights": dict(self.weights),
            "measured_values": measured,
            "computed_at": self.computed_at.isoformat(),
            "details": dict(self.details),
        }

    @property
    def coverage(self) -> float:
        if self.total_dimensions <= 0:
            return 0.0
        return round(self.measured_dimensions / self.total_dimensions, 4)
