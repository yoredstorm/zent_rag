# =============================================================================
# Domain Layer — Knowledge Operating System (FASE 34)
# =============================================================================
# Modelo semántico empresarial: objetos de conocimiento (dominios, conceptos,
# entidades, atributos, relaciones, reglas, métricas, KPIs, procesos, términos,
# sinónimos, eventos, restricciones), aristas tipadas, assertions con
# provenance/evidencia y confianza explicable, gaps y conflictos.
#
# Leyes:
#   - EVIDENCE FIRST: ninguna assertion sin evidencia puede ser VERIFIED.
#   - La confianza NO es el número del LLM: se compone de señales explicables.
#   - ERROR != ZERO: una dimensión no medida se marca measured=False y NUNCA
#     se cuenta como 0 en el score global.
#   - Un objeto solo es VERIFIED si provenance=APPROVED (revisión humana).
#
# Sin I/O: tipos puros reutilizables por API, materializador y tests.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# -----------------------------------------------------------------------------
# Tipos de conocimiento
# -----------------------------------------------------------------------------


class KnowledgeObjectType(StrEnum):
    """Tipos de conocimiento de orden superior (sección 5)."""

    DOMAIN = "domain"
    CONCEPT = "concept"
    ENTITY = "entity"
    ATTRIBUTE = "attribute"
    RELATIONSHIP = "relationship"
    BUSINESS_RULE = "business_rule"
    METRIC = "metric"
    KPI = "kpi"
    PROCESS = "process"
    TERM = "term"
    SYNONYM = "synonym"
    EVENT = "event"
    CONSTRAINT = "constraint"
    VERIFIED_QUERY = "verified_query"
    # Artefactos físicos: útiles como evidencia/linaje, no como conocimiento
    # de negocio de primer nivel.
    SOURCE = "source"
    TABLE = "table"
    COLUMN = "column"
    DOCUMENT = "document"
    SECTION = "section"
    CHUNK = "chunk"


BUSINESS_OBJECT_TYPES: tuple[KnowledgeObjectType, ...] = (
    KnowledgeObjectType.DOMAIN,
    KnowledgeObjectType.CONCEPT,
    KnowledgeObjectType.ENTITY,
    KnowledgeObjectType.ATTRIBUTE,
    KnowledgeObjectType.RELATIONSHIP,
    KnowledgeObjectType.BUSINESS_RULE,
    KnowledgeObjectType.METRIC,
    KnowledgeObjectType.KPI,
    KnowledgeObjectType.PROCESS,
    KnowledgeObjectType.TERM,
    KnowledgeObjectType.SYNONYM,
    KnowledgeObjectType.EVENT,
    KnowledgeObjectType.CONSTRAINT,
    KnowledgeObjectType.VERIFIED_QUERY,
)

PHYSICAL_OBJECT_TYPES: tuple[KnowledgeObjectType, ...] = (
    KnowledgeObjectType.SOURCE,
    KnowledgeObjectType.TABLE,
    KnowledgeObjectType.COLUMN,
    KnowledgeObjectType.DOCUMENT,
    KnowledgeObjectType.SECTION,
    KnowledgeObjectType.CHUNK,
)

# Compatibilidad: kinds de la migración 102 que se normalizan al vocabulario
# nuevo al leer. Nunca se escriben valores legados desde el materializador.
_LEGACY_KIND_ALIASES: dict[str, KnowledgeObjectType] = {
    "glossary_term": KnowledgeObjectType.TERM,
    "rule": KnowledgeObjectType.BUSINESS_RULE,
    "fact": KnowledgeObjectType.CONCEPT,
    "claim": KnowledgeObjectType.CONCEPT,
    "artifact": KnowledgeObjectType.VERIFIED_QUERY,
    "evidence": KnowledgeObjectType.CONCEPT,
}


def normalize_object_type(raw: str) -> str:
    value = (raw or "").strip().lower()
    alias = _LEGACY_KIND_ALIASES.get(value)
    return (alias or value).value if alias else value


class KnowledgeObjectStatus(StrEnum):
    """Estado explícito de un objeto (sección 46)."""

    DRAFT = "draft"
    DISCOVERED = "discovered"
    INFERRED = "inferred"
    VERIFIED = "verified"
    REJECTED = "rejected"
    DEPRECATED = "deprecated"


_LEGACY_STATUS_ALIASES: dict[str, KnowledgeObjectStatus] = {
    "observed": KnowledgeObjectStatus.DISCOVERED,
    "approved": KnowledgeObjectStatus.VERIFIED,
    "archived": KnowledgeObjectStatus.DEPRECATED,
}


def normalize_object_status(raw: str) -> str:
    value = (raw or "").strip().lower()
    alias = _LEGACY_STATUS_ALIASES.get(value)
    return (alias or value).value if alias else value


class KnowledgeProvenance(StrEnum):
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DEPRECATED = "DEPRECATED"


class RelationshipType(StrEnum):
    """Una FK no es comprensión empresarial (sección 9)."""

    PHYSICAL = "physical"
    LOGICAL = "logical"
    SEMANTIC = "semantic"
    BUSINESS = "business"


class EdgeStatus(StrEnum):
    DISCOVERED = "discovered"
    INFERRED = "inferred"
    VERIFIED = "verified"
    REJECTED = "rejected"
    DEPRECATED = "deprecated"


class AssertionStatus(StrEnum):
    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    VERIFIED = "verified"
    REJECTED = "rejected"
    CONFLICTED = "conflicted"
    STALE = "stale"


class AssertionMethod(StrEnum):
    """Origen de una assertion (sección 8)."""

    DETERMINISTIC = "deterministic"
    SCHEMA = "schema"
    STATISTICAL = "statistical"
    DOCUMENT = "document"
    HUMAN = "human"
    JEV = "jev"
    LLM = "llm"
    COMBINED = "combined"


class AssertionType(StrEnum):
    FACT = "fact"
    RELATIONSHIP_CARDINALITY = "relationship_cardinality"
    FIELD_MEANING = "field_meaning"
    BUSINESS_RULE = "business_rule"
    METRIC_DEFINITION = "metric_definition"
    PROCESS_STEP = "process_step"
    TERM_DEFINITION = "term_definition"
    CONSTRAINT = "constraint"
    OTHER = "other"


class EvidenceType(StrEnum):
    DETERMINISTIC = "deterministic"
    SCHEMA = "schema"
    STATISTICAL = "statistical"
    DOCUMENT = "document"
    HUMAN = "human"
    JEV = "jev"
    LLM = "llm"
    COMBINED = "combined"


# Fuerza de evidencia por tipo (señal explicable, no inventada).
EVIDENCE_STRENGTH: dict[str, float] = {
    EvidenceType.DETERMINISTIC.value: 1.00,
    EvidenceType.SCHEMA.value: 0.95,
    EvidenceType.HUMAN.value: 0.90,
    EvidenceType.STATISTICAL.value: 0.80,
    EvidenceType.DOCUMENT.value: 0.70,
    EvidenceType.JEV.value: 0.60,
    EvidenceType.LLM.value: 0.50,
    EvidenceType.COMBINED.value: 0.75,
}

# Certeza semántica por método de derivación.
METHOD_CERTAINTY: dict[str, float] = {
    AssertionMethod.DETERMINISTIC.value: 0.95,
    AssertionMethod.SCHEMA.value: 0.90,
    AssertionMethod.STATISTICAL.value: 0.80,
    AssertionMethod.HUMAN.value: 0.95,
    AssertionMethod.DOCUMENT.value: 0.70,
    AssertionMethod.JEV.value: 0.65,
    AssertionMethod.LLM.value: 0.55,
    AssertionMethod.COMBINED.value: 0.80,
}

# Autoridad por defecto de una fuente según su nivel declarado.
AUTHORITY_RELIABILITY: dict[str, float] = {
    "authoritative": 1.00,
    "high": 1.00,
    "approved": 0.85,
    "medium": 0.70,
    "informational": 0.60,
    "low": 0.40,
    "external": 0.45,
    "unknown": 0.50,
}


class GapType(StrEnum):
    UNKNOWN_DEFINITION = "UNKNOWN_DEFINITION"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    MISSING_RELATIONSHIP = "MISSING_RELATIONSHIP"
    AMBIGUOUS_TERM = "AMBIGUOUS_TERM"
    CONTRADICTION = "CONTRADICTION"
    MISSING_METRIC_DEFINITION = "MISSING_METRIC_DEFINITION"
    MISSING_BUSINESS_RULE = "MISSING_BUSINESS_RULE"
    STALE_KNOWLEDGE = "STALE_KNOWLEDGE"
    UNRESOLVED_QUERY = "UNRESOLVED_QUERY"
    UNSUPPORTED_ASSERTION = "UNSUPPORTED_ASSERTION"
    INCOMPLETE_SOURCE = "INCOMPLETE_SOURCE"
    RETRIEVAL_FAILURE = "RETRIEVAL_FAILURE"


class GapStatus(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    IGNORED = "ignored"
    ACKNOWLEDGED = "acknowledged"


class ConflictStatus(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    IGNORED = "ignored"


class ConflictResolution(StrEnum):
    CHOSE_A = "chose_a"
    CHOSE_B = "chose_b"
    MERGED = "merged"
    EXCEPTION = "exception"
    DELEGATED = "delegated"


class HealthDimensionKey(StrEnum):
    COVERAGE = "coverage"
    SEMANTIC = "semantic_understanding"
    RELATIONSHIPS = "relationships"
    RULES_METRICS = "rules_metrics"
    RETRIEVAL = "retrieval_quality"
    FRESHNESS = "freshness"
    VALIDATION = "human_validation"
    CONFLICTS = "conflicts"


class KnowledgeState(StrEnum):
    """Estado del dataset que la UI debe distinguir (sección 47)."""

    EMPTY = "empty"
    PARTIAL = "partial"
    READY = "ready"
    ERROR = "error"


class KnowledgeErrorCode(StrEnum):
    OVERVIEW_UNAVAILABLE = "knowledge_overview_unavailable"
    MODEL_UNAVAILABLE = "knowledge_model_unavailable"
    OBJECT_NOT_FOUND = "knowledge_object_not_found"
    ASSERTION_NOT_FOUND = "knowledge_assertion_not_found"
    GAP_NOT_FOUND = "knowledge_gap_not_found"
    CONFLICT_NOT_FOUND = "knowledge_conflict_not_found"
    SOURCE_NOT_FOUND = "knowledge_source_not_found"
    VALIDATION_DENIED = "knowledge_validation_denied"


# -----------------------------------------------------------------------------
# Confianza explicable (sección 8)
# -----------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class ConfidenceSignals:
    """Señales reales usadas para calcular confianza. Explicable y calibrable."""

    source_reliability: float = 0.5
    evidence_strength: float = 0.0
    evidence_count: int = 0
    semantic_certainty: float = 0.5
    freshness: float = 1.0
    validation: float = 0.85  # 1.0 verificado, 0.0 rechazado

    def to_dict(self) -> dict:
        return {
            "source_reliability": round(self.source_reliability, 4),
            "evidence_strength": round(self.evidence_strength, 4),
            "evidence_count": int(self.evidence_count),
            "semantic_certainty": round(self.semantic_certainty, 4),
            "freshness": round(self.freshness, 4),
            "validation": round(self.validation, 4),
        }


_CONFIDENCE_WEIGHTS: dict[str, float] = {
    "source_reliability": 0.25,
    "evidence_strength": 0.30,
    "corroboration": 0.15,
    "semantic_certainty": 0.20,
    "freshness": 0.10,
}


def compute_confidence(signals: ConfidenceSignals) -> tuple[float, dict]:
    """Media geométrica ponderada de señales reales (0..1) + composición.

    Multiplicativa a propósito: evidencia débil castiga aunque la fuente sea
    confiable, y una assertion sin evidencia no puede llegar a 1.0.
    Sin evidencia (evidence_count=0) el techo es 0.6.
    """
    corroboration = _clamp01(min(1.0, signals.evidence_count / 3.0))
    components = {
        "source_reliability": max(0.05, _clamp01(signals.source_reliability)),
        "evidence_strength": max(0.05, _clamp01(signals.evidence_strength)),
        "corroboration": max(0.05, corroboration),
        "semantic_certainty": max(0.05, _clamp01(signals.semantic_certainty)),
        "freshness": max(0.05, _clamp01(signals.freshness)),
    }
    total_weight = sum(_CONFIDENCE_WEIGHTS.values())
    product = 1.0
    for key, weight in _CONFIDENCE_WEIGHTS.items():
        product *= components[key] ** (weight / total_weight)
    score = round(_clamp01(product), 4)
    if signals.evidence_count <= 0:
        score = min(score, 0.6)
    if signals.validation <= 0.0:
        score = 0.0
    elif signals.validation >= 1.0:
        score = max(score, 0.9) if signals.evidence_count > 0 else score
    detail = {
        "formula": (
            "product(component^weight) con pesos "
            + ", ".join(f"{k}={v}" for k, v in _CONFIDENCE_WEIGHTS.items())
        ),
        "components": {**components, "corroboration": corroboration},
        "weights": dict(_CONFIDENCE_WEIGHTS),
        "signals": signals.to_dict(),
        "caps": ["sin evidencia techo 0.6", "rechazado 0.0", "verificado piso 0.9"],
        "score": score,
    }
    return score, detail


def confidence_label(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 0.85:
        return "high"
    if score >= 0.6:
        return "medium"
    if score >= 0.35:
        return "low"
    return "very_low"


# -----------------------------------------------------------------------------
# Prioridad de gaps / active learning (secciones 16-17)
# -----------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class GapImpact:
    """Impacto real de un gap: qué objetos/consultas/agentes dependen de él."""

    affected_objects: int = 0
    affected_queries: int = 0
    affected_agents: int = 0
    affected_workflows: int = 0
    business_impact: float = 0.0
    retrieval_impact: float = 0.0

    def to_dict(self) -> dict:
        return {
            "affected_objects": int(self.affected_objects),
            "affected_queries": int(self.affected_queries),
            "affected_agents": int(self.affected_agents),
            "affected_workflows": int(self.affected_workflows),
            "business_impact": round(self.business_impact, 4),
            "retrieval_impact": round(self.retrieval_impact, 4),
        }


_GAP_PRIORITY_WEIGHTS: dict[str, float] = {
    "business_impact": 0.30,
    "retrieval_impact": 0.20,
    "dependents": 0.20,
    "confidence_gap": 0.15,
    "ambiguity": 0.15,
}


def compute_gap_priority(
    *,
    impact: GapImpact,
    confidence: float | None,
    ambiguity: float = 0.5,
    dependents: float = 0.0,
) -> tuple[str, float]:
    """Prioridad 0..1 explicable. El usuario ve primero lo que más mejora."""
    signals = {
        "business_impact": _clamp01(impact.business_impact),
        "retrieval_impact": _clamp01(impact.retrieval_impact),
        "dependents": _clamp01(dependents),
        "confidence_gap": 1.0 - _clamp01(confidence if confidence is not None else 0.0),
        "ambiguity": _clamp01(ambiguity),
    }
    total = sum(_GAP_PRIORITY_WEIGHTS.values())
    score = round(
        sum(signals[k] * w for k, w in _GAP_PRIORITY_WEIGHTS.items()) / total, 4
    )
    if score >= 0.75:
        return "critical", score
    if score >= 0.55:
        return "high", score
    if score >= 0.35:
        return "medium", score
    return "low", score


# -----------------------------------------------------------------------------
# Health explicable (secciones 4, 25)
# -----------------------------------------------------------------------------


@dataclass(kw_only=True)
class HealthDimension:
    """Una dimensión del Knowledge Health, medible o NO MEDIDA."""

    key: str
    label: str
    score: float | None
    weight: float
    measured: bool
    reason: str = ""
    formula: str = ""
    signals: dict = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    updated_at: datetime | None = None
    trend: float | None = None

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "score": round(self.score, 2) if self.score is not None else None,
            "weight": round(self.weight, 4),
            "measured": bool(self.measured),
            "reason": self.reason,
            "formula": self.formula,
            "signals": self.signals,
            "missing": list(self.missing),
            "issues": list(self.issues),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "trend": round(self.trend, 2) if self.trend is not None else None,
        }


@dataclass(kw_only=True)
class KnowledgeHealth:
    """Salud del conocimiento: global solo sobre dimensiones MEDIDAS."""

    overall: float | None
    measured_dimensions: int
    total_dimensions: int
    dimensions: list[HealthDimension] = field(default_factory=list)
    state: str = KnowledgeState.PARTIAL.value
    computed_at: datetime = field(default_factory=_utcnow)

    def to_dict(self) -> dict:
        return {
            "overall": round(self.overall, 2) if self.overall is not None else None,
            "measured_dimensions": self.measured_dimensions,
            "total_dimensions": self.total_dimensions,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "state": self.state,
            "computed_at": self.computed_at.isoformat(),
        }


def aggregate_health(dimensions: list[HealthDimension]) -> tuple[float | None, int]:
    """Promedio ponderado SOLO sobre dimensiones medidas.

    No medido NO es 0: se excluye del cálculo y se reporta aparte.
    """
    measured = [d for d in dimensions if d.measured and d.score is not None]
    if not measured:
        return None, 0
    total_weight = sum(max(d.weight, 0.0) for d in measured)
    if total_weight <= 0:
        return None, len(measured)
    acc = sum(
        max(0.0, min(100.0, d.score or 0.0)) * max(d.weight, 0.0) for d in measured
    )
    return round(acc / total_weight, 2), len(measured)


# -----------------------------------------------------------------------------
# Registros (shape estable para API/materializador)
# -----------------------------------------------------------------------------


@dataclass(kw_only=True)
class KnowledgeObjectRecord:
    id: UUID
    organization_id: UUID
    type: str
    name: str
    display_name: str = ""
    description: str | None = None
    domain: str | None = None
    status: str = KnowledgeObjectStatus.DISCOVERED.value
    provenance: str = KnowledgeProvenance.OBSERVED.value
    confidence: float | None = None
    source_of_truth: str | None = None
    source_id: UUID | None = None
    authority_level: str | None = None
    evidence_count: int = 0
    assertion_count: int = 0
    verified_at: datetime | None = None
    freshness_at: datetime | None = None
    last_seen_at: datetime | None = None
    metadata: dict = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "type": self.type,
            "name": self.name,
            "display_name": self.display_name or self.name,
            "description": self.description,
            "domain": self.domain,
            "status": self.status,
            "provenance": self.provenance,
            "confidence": round(self.confidence, 4) if self.confidence is not None else None,
            "confidence_label": confidence_label(self.confidence),
            "source_of_truth": self.source_of_truth,
            "source_id": str(self.source_id) if self.source_id else None,
            "authority_level": self.authority_level,
            "evidence_count": int(self.evidence_count),
            "assertion_count": int(self.assertion_count),
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "freshness_at": self.freshness_at.isoformat() if self.freshness_at else None,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
