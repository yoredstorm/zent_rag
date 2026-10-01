# =============================================================================
# Knowledge Session — la unidad observable del aprendizaje de ZENT
# =============================================================================
# Una Knowledge Session agrupa N fuentes que se están enseñando a ZENT y expone
# su evolución con eventos SEMÁNTICOS reales (no progreso de uploader):
#
#   información -> comprensión -> descubrimiento -> conexión -> conocimiento
#
# Reglas de diseño:
#   - Todo evento y toda métrica procede de trabajo realmente ocurrido en el
#     Knowledge Compiler / pipeline de ingesta. Nunca se fabrica actividad.
#   - El vocabulario es humano; el detalle técnico viaja en el payload.
#   - Los eventos de alta frecuencia se agregan (batching) antes de persistir.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID


class LearningSessionStatus(StrEnum):
    """Ciclo de vida de la sesión de aprendizaje."""

    PREPARING = "preparing"      # sesión creada, fuentes aceptadas
    LEARNING = "learning"        # al menos una fuente en lectura/comprensión
    AVAILABLE = "available"      # ya se puede consultar; quedan fuentes vivos
    OPTIMIZING = "optimizing"    # todas consultables; conocimiento derivado corre
    COMPLETED = "completed"     # aprendizaje terminado
    PARTIAL = "partial"         # terminó con fuentes parcialmente aprendidas
    FAILED = "failed"
    CANCELED = "canceled"


class SourceLearningStatus(StrEnum):
    PENDING = "pending"
    LEARNING = "learning"
    AVAILABLE = "available"   # consultable, aunque siga enriqueciéndose
    COMPLETED = "completed"
    FAILED = "failed"


class LearningStage(StrEnum):
    """Etapas humanas del aprendizaje (con sub-etiqueta técnica en la UI)."""

    READING = "reading"              # Leyendo
    UNDERSTANDING = "understanding"  # Entendiendo
    ORGANIZING = "organizing"        # Organizando
    CONNECTING = "connecting"        # Conectando
    VERIFYING = "verifying"          # Verificando
    LEARNED = "learned"              # Aprendido


# Orden canónico de etapas (la UI deriva el progreso de aquí).
STAGE_ORDER: tuple[str, ...] = (
    LearningStage.READING.value,
    LearningStage.UNDERSTANDING.value,
    LearningStage.ORGANIZING.value,
    LearningStage.CONNECTING.value,
    LearningStage.VERIFYING.value,
    LearningStage.LEARNED.value,
)

# Sub-etiqueta técnica mostrada a usuarios avanzados, por etapa humana.
STAGE_TECHNICAL: dict[str, str] = {
    LearningStage.READING.value: "parser",
    LearningStage.UNDERSTANDING.value: "semantic units",
    LearningStage.ORGANIZING.value: "entity resolution",
    LearningStage.CONNECTING.value: "knowledge graph",
    LearningStage.VERIFYING.value: "evidence linking",
    LearningStage.LEARNED.value: "indexes",
}


class SessionEventType(StrEnum):
    """Eventos semánticos reales emitidos por el Knowledge Compiler."""

    SESSION_STARTED = "SESSION_STARTED"
    SOURCE_RECEIVED = "SOURCE_RECEIVED"
    PARSING_STARTED = "PARSING_STARTED"
    STRUCTURE_DISCOVERED = "STRUCTURE_DISCOVERED"
    TABLE_DETECTED = "TABLE_DETECTED"
    SEMANTIC_UNIT_CREATED = "SEMANTIC_UNIT_CREATED"
    ENTITY_DISCOVERED = "ENTITY_DISCOVERED"
    ENTITY_MATCHED = "ENTITY_MATCHED"
    ENTITY_MERGED = "ENTITY_MERGED"
    FACT_DISCOVERED = "FACT_DISCOVERED"
    FACT_REINFORCED = "FACT_REINFORCED"
    RELATIONSHIP_DISCOVERED = "RELATIONSHIP_DISCOVERED"
    RULE_DISCOVERED = "RULE_DISCOVERED"
    TEMPORAL_RANGE_DISCOVERED = "TEMPORAL_RANGE_DISCOVERED"
    KNOWLEDGE_OBJECT_CREATED = "KNOWLEDGE_OBJECT_CREATED"
    CONFLICT_DETECTED = "CONFLICT_DETECTED"
    DUPLICATE_DETECTED = "DUPLICATE_DETECTED"
    EVIDENCE_LINKED = "EVIDENCE_LINKED"
    INDEX_UPDATED = "INDEX_UPDATED"
    KNOWLEDGE_READY = "KNOWLEDGE_READY"
    SOURCE_AVAILABLE = "SOURCE_AVAILABLE"
    SOURCE_FAILED = "SOURCE_FAILED"
    SESSION_COMPLETED = "SESSION_COMPLETED"
    SESSION_FAILED = "SESSION_FAILED"
    WARNING = "WARNING"


# Eventos de alta frecuencia: se agregan en ventanas antes de persistir.
HIGH_FREQUENCY_EVENTS: frozenset[str] = frozenset(
    {
        SessionEventType.SEMANTIC_UNIT_CREATED.value,
        SessionEventType.ENTITY_DISCOVERED.value,
        SessionEventType.ENTITY_MATCHED.value,
        SessionEventType.FACT_DISCOVERED.value,
        SessionEventType.FACT_REINFORCED.value,
        SessionEventType.RELATIONSHIP_DISCOVERED.value,
        SessionEventType.EVIDENCE_LINKED.value,
        SessionEventType.RULE_DISCOVERED.value,
    }
)

# Categorías de aprendizaje (requisito 14: nuevo/reforzado/actualizado/...).
class KnowledgeChangeCategory(StrEnum):
    NEW = "new"
    REINFORCED = "reinforced"
    UPDATED = "updated"
    RELATED = "related"
    CONFLICTING = "conflicting"
    IGNORED = "ignored"


# Métricas del Knowledge Pulse. Claves estables: la UI pinta exactamente estas.
PULSE_METRICS: tuple[str, ...] = (
    "entities",
    "relationships",
    "facts",
    "rules",
    "evidence",
    "semantic_units",
    "concepts",
    "tables",
    "conflicts",
    "sources_available",
)


@dataclass(kw_only=True)
class KnowledgeDelta:
    """Qué cambió en el cerebro de ZENT con esta sesión."""

    new_concepts: int = 0
    new_entities: int = 0
    new_facts: int = 0
    new_relationships: int = 0
    new_rules: int = 0
    new_evidence: int = 0
    reinforced_facts: int = 0
    enriched_entities: int = 0
    merged_entities: int = 0
    updated: int = 0
    related: int = 0
    duplicates: int = 0
    conflicts: int = 0
    ignored: int = 0
    totals_before: dict = field(default_factory=dict)
    totals_after: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "new_concepts": self.new_concepts,
            "new_entities": self.new_entities,
            "new_facts": self.new_facts,
            "new_relationships": self.new_relationships,
            "new_rules": self.new_rules,
            "new_evidence": self.new_evidence,
            "reinforced_facts": self.reinforced_facts,
            "enriched_entities": self.enriched_entities,
            "merged_entities": self.merged_entities,
            "updated": self.updated,
            "related": self.related,
            "duplicates": self.duplicates,
            "conflicts": self.conflicts,
            "ignored": self.ignored,
            "totals_before": dict(self.totals_before),
            "totals_after": dict(self.totals_after),
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "KnowledgeDelta":
        data = data or {}
        known = {f for f in cls.__dataclass_fields__ if f not in {"totals_before", "totals_after"}}
        kwargs = {key: int(data.get(key) or 0) for key in known}
        kwargs["totals_before"] = dict(data.get("totals_before") or {})
        kwargs["totals_after"] = dict(data.get("totals_after") or {})
        return cls(**kwargs)

    @property
    def delta_totals(self) -> dict:
        """Delta priorizado (nunca el total bruto): requisito 13."""
        before = self.totals_before or {}
        after = self.totals_after or {}
        keys = ("entities", "relationships", "facts", "rules", "evidence")
        delta = {}
        for key in keys:
            try:
                delta[key] = int(after.get(key) or 0) - int(before.get(key) or 0)
            except (TypeError, ValueError):
                delta[key] = 0
        return delta


@dataclass(kw_only=True)
class LearningSessionSource:
    """Una fuente dentro de la sesión, con su evolución real."""

    id: UUID
    session_id: UUID
    organization_id: UUID
    source_id: UUID | None = None
    job_id: UUID | None = None
    name: str = ""
    source_type: str = "file"
    status: str = SourceLearningStatus.PENDING.value
    stage: str = LearningStage.READING.value
    stats: dict = field(default_factory=dict)
    error: str | None = None
    available_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "session_id": str(self.session_id),
            "source_id": str(self.source_id) if self.source_id else None,
            "job_id": str(self.job_id) if self.job_id else None,
            "name": self.name,
            "source_type": self.source_type,
            "status": self.status,
            "stage": self.stage,
            "stage_label": stage_label(self.stage),
            "stats": dict(self.stats),
            "error": self.error,
            "available_at": _iso(self.available_at),
            "completed_at": _iso(self.completed_at),
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


@dataclass(kw_only=True)
class LearningSession:
    """Sesión de aprendizaje: observabilidad completa del requisito 21."""

    id: UUID
    organization_id: UUID
    workspace_id: UUID | None = None
    title: str = ""
    origin: str = "upload"
    status: str = LearningSessionStatus.PREPARING.value
    stage: str = LearningStage.READING.value
    source_count: int = 0
    available_sources: int = 0
    completed_sources: int = 0
    failed_sources: int = 0
    metrics: dict = field(default_factory=dict)
    knowledge_delta: dict = field(default_factory=dict)
    totals_before: dict = field(default_factory=dict)
    totals_after: dict = field(default_factory=dict)
    warnings: int = 0
    errors: int = 0
    started_at: datetime | None = None
    available_at: datetime | None = None
    completed_at: datetime | None = None
    sealed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict:
        delta = self.knowledge_delta or {}
        return {
            "session_id": str(self.id),
            "organization_id": str(self.organization_id),
            "workspace_id": str(self.workspace_id) if self.workspace_id else None,
            "title": self.title,
            "origin": self.origin,
            "status": self.status,
            "stage": self.stage,
            "stage_label": stage_label(self.stage),
            "stage_technical": STAGE_TECHNICAL.get(self.stage),
            "stages": [
                {
                    "key": key,
                    "label": stage_label(key),
                    "technical": STAGE_TECHNICAL.get(key),
                }
                for key in STAGE_ORDER
            ],
            "source_count": self.source_count,
            "available_sources": self.available_sources,
            "completed_sources": self.completed_sources,
            "failed_sources": self.failed_sources,
            "metrics": dict(self.metrics),
            "knowledge_delta": delta,
            "delta_totals": KnowledgeDelta.from_dict(delta).delta_totals,
            "totals_before": dict(self.totals_before),
            "totals_after": dict(self.totals_after),
            "warnings": self.warnings,
            "errors": self.errors,
            "started_at": _iso(self.started_at),
            "available_at": _iso(self.available_at),
            "completed_at": _iso(self.completed_at),
            "sealed_at": _iso(self.sealed_at),
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
            "is_available": self.status
            in (
                LearningSessionStatus.AVAILABLE.value,
                LearningSessionStatus.OPTIMIZING.value,
                LearningSessionStatus.COMPLETED.value,
                LearningSessionStatus.PARTIAL.value,
            ),
        }


STAGE_LABELS: dict[str, str] = {
    LearningStage.READING.value: "Leyendo",
    LearningStage.UNDERSTANDING.value: "Entendiendo",
    LearningStage.ORGANIZING.value: "Organizando",
    LearningStage.CONNECTING.value: "Conectando",
    LearningStage.VERIFYING.value: "Verificando",
    LearningStage.LEARNED.value: "Aprendido",
}


def stage_label(stage: str | None) -> str:
    return STAGE_LABELS.get(stage or "", "Leyendo")


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


__all__ = [
    "KnowledgeChangeCategory",
    "KnowledgeDelta",
    "LearningSession",
    "LearningSessionSource",
    "LearningSessionStatus",
    "LearningStage",
    "HIGH_FREQUENCY_EVENTS",
    "PULSE_METRICS",
    "STAGE_LABELS",
    "STAGE_ORDER",
    "STAGE_TECHNICAL",
    "SessionEventType",
    "SourceLearningStatus",
    "stage_label",
]
