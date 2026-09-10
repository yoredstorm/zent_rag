# =============================================================================
# Domain Layer — Knowledge Learning Engine (FASE 33)
# =============================================================================
# Entidades puras del aprendizaje de conocimiento: runs, etapas, eventos,
# feedback y score de readiness. Sin dependencias externas.
#
# "Learning" NO es fine-tuning de pesos: es descubrimiento de schema, profiling,
# comprensión semántica, validación humana, indexado y evaluación. Los estados
# del pipeline son explícitos y auditables; el LLM nunca es la única fuente de
# verdad (INFERRED != APPROVED).
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID

# -----------------------------------------------------------------------------
# Estados y etapas
# -----------------------------------------------------------------------------


class LearningRunStatus(StrEnum):
    """Estado del run de aprendizaje (compatible con training_runs)."""

    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_VALIDATION = "awaiting_validation"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (
            LearningRunStatus.COMPLETED,
            LearningRunStatus.FAILED,
            LearningRunStatus.CANCELLED,
        )


class LearningTrigger(StrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    ONBOARDING = "onboarding"


class LearningStage(StrEnum):
    """Etapas del pipeline de aprendizaje (explícitas y observables)."""

    CONNECTING = "connecting"
    DISCOVERING_SCHEMA = "discovering_schema"
    PROFILING = "profiling"
    DETECTING_ENTITIES = "detecting_entities"
    ANALYZING_FIELDS = "analyzing_fields"
    DETECTING_RELATIONSHIPS = "detecting_relationships"
    LLM_REASONING = "llm_reasoning"
    GENERATING_QUESTIONS = "generating_questions"
    AWAITING_VALIDATION = "awaiting_validation"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    EVALUATING = "evaluating"
    SCORING = "scoring"
    READY = "ready"


# Etapas que la FASE 1 ejecuta realmente (deterministas). Las fases 2-7
# agregan las restantes a measure que se implementan: nunca se simulan.
PHASE1_ACTIVE_STAGES: tuple[LearningStage, ...] = (
    LearningStage.CONNECTING,
    LearningStage.DISCOVERING_SCHEMA,
    LearningStage.PROFILING,
    LearningStage.DETECTING_ENTITIES,
    LearningStage.ANALYZING_FIELDS,
    LearningStage.DETECTING_RELATIONSHIPS,
    # FASE 33D: preguntas deterministas desde evidencia real (siempre activa).
    LearningStage.GENERATING_QUESTIONS,
    LearningStage.SCORING,
)

# Peso relativo de cada etapa para el progreso global (0-100 real, sin timers).
PHASE1_STAGE_WEIGHTS: dict[LearningStage, int] = {
    LearningStage.CONNECTING: 5,
    LearningStage.DISCOVERING_SCHEMA: 30,
    LearningStage.PROFILING: 15,
    LearningStage.DETECTING_ENTITIES: 15,
    LearningStage.ANALYZING_FIELDS: 20,
    LearningStage.DETECTING_RELATIONSHIPS: 10,
    LearningStage.GENERATING_QUESTIONS: 10,
    LearningStage.EVALUATING: 15,
    LearningStage.SCORING: 5,
    # FASE 33B: solo se incluye cuando el flag LLM está activo.
    LearningStage.LLM_REASONING: 25,
}

# Mapa completo de pesos por etapa (el progreso normaliza sobre las etapas
# realmente incluidas en el run).
STAGE_WEIGHTS: dict[LearningStage, int] = PHASE1_STAGE_WEIGHTS

_STAGE_LABELS: dict[LearningStage, str] = {
    LearningStage.CONNECTING: "Conectando a la fuente",
    LearningStage.DISCOVERING_SCHEMA: "Descubriendo schema",
    LearningStage.PROFILING: "Perfilando columnas",
    LearningStage.DETECTING_ENTITIES: "Detectando entidades",
    LearningStage.ANALYZING_FIELDS: "Analizando campos",
    LearningStage.DETECTING_RELATIONSHIPS: "Entendiendo relaciones",
    LearningStage.LLM_REASONING: "Razonando con el LLM",
    LearningStage.GENERATING_QUESTIONS: "Generando preguntas",
    LearningStage.AWAITING_VALIDATION: "Esperando validación humana",
    LearningStage.CHUNKING: "Fragmentando conocimiento",
    LearningStage.EMBEDDING: "Construyendo embeddings",
    LearningStage.INDEXING: "Indexando",
    LearningStage.EVALUATING: "Evaluando conocimiento",
    LearningStage.SCORING: "Calculando readiness",
    LearningStage.READY: "Conocimiento listo",
}


def stage_label(stage: str | LearningStage) -> str:
    try:
        return _STAGE_LABELS[LearningStage(stage)]
    except (ValueError, KeyError):
        return str(stage)


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


class LLMAnalysisStatus(StrEnum):
    """Estado del análisis LLM por tabla (FASE 33B)."""

    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class QuestionType(StrEnum):
    """Origen/tipo de una pregunta de negocio (FASE 33D)."""

    ENUM_MEANING = "enum_meaning"
    FIELD_AMBIGUITY = "field_ambiguity"
    TABLE_VARIANT = "table_variant"
    TAX_INCLUSION = "tax_inclusion"
    RELATIONSHIP_MEANING = "relationship_meaning"
    BUSINESS_RULE = "business_rule"
    METRIC_DEFINITION = "metric_definition"
    LLM_QUESTION = "llm_question"
    OTHER = "other"


class QuestionPriority(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class QuestionStatus(StrEnum):
    PENDING = "pending"
    ANSWERED = "answered"
    SKIPPED = "skipped"
    DEFERRED = "deferred"
    EXPIRED = "expired"


class FeedbackSource(StrEnum):
    QUESTION = "question"
    REVIEW_QUEUE = "review_queue"
    STUDIO = "studio"
    IMPORT = "import"


QUESTION_PRIORITY_WEIGHTS: dict[str, float] = {
    "ambiguity": 0.30,
    "business_impact": 0.25,
    "retrieval_impact": 0.15,
    "frequency": 0.10,
    "confidence_gap": 0.10,
    "dependents": 0.10,
}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def compute_question_priority(
    *,
    ambiguity: float,
    business_impact: float,
    retrieval_impact: float,
    frequency: float,
    confidence: float,
    dependents: float,
) -> tuple[QuestionPriority, float]:
    """Score de prioridad 0..1 explicable (sección 8) y etiqueta.

    No bombardea al cliente: solo CRITICAL/HIGH deberían bloquear el gate.
    """
    signals = {
        "ambiguity": _clamp01(ambiguity),
        "business_impact": _clamp01(business_impact),
        "retrieval_impact": _clamp01(retrieval_impact),
        "frequency": _clamp01(frequency),
        "confidence_gap": 1.0 - _clamp01(confidence),
        "dependents": _clamp01(dependents),
    }
    total_weight = sum(QUESTION_PRIORITY_WEIGHTS.values())
    score = round(
        sum(
            signals[key] * weight
            for key, weight in QUESTION_PRIORITY_WEIGHTS.items()
        )
        / total_weight,
        4,
    )
    if score >= 0.78:
        return QuestionPriority.CRITICAL, score
    if score >= 0.58:
        return QuestionPriority.HIGH, score
    if score >= 0.38:
        return QuestionPriority.MEDIUM, score
    return QuestionPriority.LOW, score


class KnowledgeGate(StrEnum):
    """Knowledge Readiness Gate (sección 31)."""

    NOT_READY = "NOT_READY"
    LEARNING = "LEARNING"
    NEEDS_INPUT = "NEEDS_INPUT"
    READY = "READY"
    DEGRADED = "DEGRADED"


class KnowledgeEventType(StrEnum):
    STAGE_STARTED = "stage.started"
    STAGE_COMPLETED = "stage.completed"
    STAGE_FAILED = "stage.failed"
    LEARNING_STARTED = "learning.started"
    SCHEMA_DISCOVERED = "schema.discovered"
    TABLE_ANALYZED = "table.analyzed"
    ENTITY_DETECTED = "entity.detected"
    FIELD_DETECTED = "field.detected"
    RELATIONSHIP_DETECTED = "relationship.detected"
    LLM_ANALYSIS_STARTED = "llm.analysis.started"
    LLM_ANALYSIS_COMPLETED = "llm.analysis.completed"
    QUESTION_GENERATED = "question.generated"
    KNOWLEDGE_CONFIRMED = "knowledge.confirmed"
    EMBEDDING_STARTED = "embedding.started"
    EMBEDDING_PROGRESS = "embedding.progress"
    EVALUATION_STARTED = "evaluation.started"
    EVALUATION_COMPLETED = "evaluation.completed"
    SCORE_COMPUTED = "knowledge.score.computed"
    LEARNING_COMPLETED = "learning.completed"
    LEARNING_FAILED = "learning.failed"
    LEARNING_CANCELLED = "learning.cancelled"


class EventCategory(StrEnum):
    """Filtros del Activity Feed (All / Discovery / AI / Validation / Indexing)."""

    DISCOVERY = "discovery"
    AI = "ai"
    VALIDATION = "validation"
    INDEXING = "indexing"
    SYSTEM = "system"


_CATEGORY_BY_EVENT: dict[str, EventCategory] = {
    KnowledgeEventType.LEARNING_STARTED.value: EventCategory.SYSTEM,
    KnowledgeEventType.LEARNING_COMPLETED.value: EventCategory.SYSTEM,
    KnowledgeEventType.LEARNING_FAILED.value: EventCategory.SYSTEM,
    KnowledgeEventType.LEARNING_CANCELLED.value: EventCategory.SYSTEM,
    KnowledgeEventType.STAGE_STARTED.value: EventCategory.SYSTEM,
    KnowledgeEventType.STAGE_COMPLETED.value: EventCategory.SYSTEM,
    KnowledgeEventType.STAGE_FAILED.value: EventCategory.SYSTEM,
    KnowledgeEventType.SCHEMA_DISCOVERED.value: EventCategory.DISCOVERY,
    KnowledgeEventType.TABLE_ANALYZED.value: EventCategory.DISCOVERY,
    KnowledgeEventType.ENTITY_DETECTED.value: EventCategory.AI,
    KnowledgeEventType.FIELD_DETECTED.value: EventCategory.AI,
    KnowledgeEventType.RELATIONSHIP_DETECTED.value: EventCategory.AI,
    KnowledgeEventType.LLM_ANALYSIS_STARTED.value: EventCategory.AI,
    KnowledgeEventType.LLM_ANALYSIS_COMPLETED.value: EventCategory.AI,
    KnowledgeEventType.QUESTION_GENERATED.value: EventCategory.VALIDATION,
    KnowledgeEventType.KNOWLEDGE_CONFIRMED.value: EventCategory.VALIDATION,
    KnowledgeEventType.EMBEDDING_STARTED.value: EventCategory.INDEXING,
    KnowledgeEventType.EMBEDDING_PROGRESS.value: EventCategory.INDEXING,
    KnowledgeEventType.EVALUATION_STARTED.value: EventCategory.INDEXING,
    KnowledgeEventType.EVALUATION_COMPLETED.value: EventCategory.INDEXING,
    KnowledgeEventType.SCORE_COMPUTED.value: EventCategory.SYSTEM,
}


def event_category(event_type: str) -> EventCategory:
    return _CATEGORY_BY_EVENT.get(event_type, EventCategory.SYSTEM)


# -----------------------------------------------------------------------------
# Score (Knowledge Readiness, sección 11)
# -----------------------------------------------------------------------------

DEFAULT_SCORE_WEIGHTS: dict[str, float] = {
    "schema_discovery": 0.15,
    "semantic_understanding": 0.20,
    "relationships": 0.15,
    "human_validation": 0.15,
    "knowledge_coverage": 0.15,
    "rag_evaluation": 0.15,
    "data_freshness": 0.05,
}

DEFAULT_GATE_THRESHOLDS: dict[str, float] = {
    # Score global mínimo para READY.
    "ready_overall": 80.0,
    # Umbrales por dimensión exigidos por el gate READY (sección 31).
    "schema_coverage": 90.0,
    "semantic_coverage": 70.0,
    "evaluation_score": 75.0,
    # Preguntas críticas pendientes máximas para READY.
    "critical_questions_max": 0,
    # Debajo de esto el conocimiento está "learning"/no listo.
    "min_overall": 40.0,
    # Días sin escanear para considerar la fuente stale (DEGRADED).
    "stale_source_days": 14.0,
}


@dataclass(kw_only=True)
class ScoreDimension:
    """Una dimensión del score con composición explicable."""

    key: str
    label: str
    score: float  # 0-100
    weight: float  # 0-1
    detail: str = ""
    measured: bool = True

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "score": round(self.score, 2),
            "weight": round(self.weight, 4),
            "detail": self.detail,
            "measured": self.measured,
        }


@dataclass(kw_only=True)
class KnowledgeScoreResult:
    """Resultado de Knowledge Readiness con razones accionables."""

    organization_id: UUID
    source_id: UUID | None = None
    run_id: UUID | None = None
    overall: float = 0.0
    gate: KnowledgeGate = KnowledgeGate.NOT_READY
    dimensions: list[ScoreDimension] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)
    computed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def dimension(self, key: str) -> ScoreDimension | None:
        return next((d for d in self.dimensions if d.key == key), None)

    def to_dict(self) -> dict:
        return {
            "organization_id": str(self.organization_id),
            "source_id": str(self.source_id) if self.source_id else None,
            "run_id": str(self.run_id) if self.run_id else None,
            "overall": round(self.overall, 2),
            "gate": self.gate.value,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "reasons": list(self.reasons),
            "weights": {k: round(v, 4) for k, v in self.weights.items()},
            "computed_at": self.computed_at.isoformat(),
        }


def compute_overall(
    scores: dict[str, float], weights: dict[str, float]
) -> float:
    """Promedio ponderado normalizado (dimensiones ausentes = 0)."""
    total_weight = sum(max(w, 0.0) for w in weights.values())
    if total_weight <= 0:
        return 0.0
    acc = sum(
        max(0.0, min(100.0, scores.get(key, 0.0))) * max(weight, 0.0)
        for key, weight in weights.items()
    )
    return round(acc / total_weight, 2)


# -----------------------------------------------------------------------------
# Runs / steps / events / feedback
# -----------------------------------------------------------------------------


@dataclass(kw_only=True)
class KnowledgeLearningRun:
    id: UUID
    organization_id: UUID
    catalog_source_id: UUID | None = None
    workspace_id: UUID | None = None
    kb_source_id: UUID | None = None
    training_run_id: UUID | None = None
    trigger: LearningTrigger = LearningTrigger.MANUAL
    status: LearningRunStatus = LearningRunStatus.QUEUED
    current_stage: str = LearningStage.CONNECTING.value
    overall_progress: int = 0
    stage_progress: int = 0
    gate: KnowledgeGate | None = None
    tables_analyzed: int = 0
    entities_detected: int = 0
    fields_detected: int = 0
    relationships_detected: int = 0
    metrics: dict = field(default_factory=dict)
    error_summary: dict = field(default_factory=dict)
    created_by: UUID | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass(kw_only=True)
class KnowledgeLearningStep:
    id: UUID
    organization_id: UUID
    run_id: UUID
    stage: str
    sequence: int = 0
    status: StageStatus = StageStatus.PENDING
    progress: int = 0
    metrics: dict = field(default_factory=dict)
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: float = 0.0


@dataclass(kw_only=True)
class KnowledgeEvent:
    id: UUID
    organization_id: UUID
    event_type: str
    run_id: UUID | None = None
    source_id: UUID | None = None
    stage: str | None = None
    category: str = EventCategory.SYSTEM.value
    severity: str = "info"  # info | success | warning | error
    message: str = ""
    payload: dict = field(default_factory=dict)
    seq: int = 0
    created_at: datetime | None = None


@dataclass(kw_only=True)
class KnowledgeLearningSettings:
    """Configuración por tenant: pesos del score y umbrales del gate."""

    organization_id: UUID
    weights: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_SCORE_WEIGHTS)
    )
    thresholds: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_GATE_THRESHOLDS)
    )
    updated_by: UUID | None = None
    updated_at: datetime | None = None

    def effective_weights(self) -> dict[str, float]:
        merged = dict(DEFAULT_SCORE_WEIGHTS)
        for key, value in (self.weights or {}).items():
            if key in merged and isinstance(value, (int, float)) and value >= 0:
                merged[key] = float(value)
        return merged

    def effective_thresholds(self) -> dict[str, float]:
        merged = dict(DEFAULT_GATE_THRESHOLDS)
        for key, value in (self.thresholds or {}).items():
            if key in merged and isinstance(value, (int, float)):
                merged[key] = float(value)
        return merged
