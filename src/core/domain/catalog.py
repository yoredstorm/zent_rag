# =============================================================================
# Domain Layer — Zent Discovery Engine & Semantic Catalog (FASE 24)
# =============================================================================
# Entidades puras del catálogo físico y semántico. Sin dependencias externas.
# Separación estricta de provenance: OBSERVED / INFERRED / APPROVED
# (nunca promover INFERRED -> APPROVED automáticamente).
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4


class CatalogProvenance(StrEnum):
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DEPRECATED = "DEPRECATED"


class DiscoveryPhase(StrEnum):
    QUEUED = "QUEUED"
    SCANNING = "SCANNING"
    PROFILING = "PROFILING"
    INFERRING = "INFERRING"
    WAITING_REVIEW = "WAITING_REVIEW"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ScanType(StrEnum):
    INITIAL = "initial"
    INCREMENTAL = "incremental"
    MANUAL = "manual"
    SCHEDULED = "scheduled"


class RelationshipStatus(StrEnum):
    SUGGESTED = "suggested"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class SuggestionType(StrEnum):
    ENTITY_IDENTIFICATION = "entity_identification"
    TABLE_IDENTIFICATION = "table_identification"
    RELATIONSHIP_CANDIDATE = "relationship_candidate"
    ENUM_DEFINITION = "enum_definition"
    FIELD_MAPPING = "field_mapping"
    METRIC_PROPOSAL = "metric_proposal"
    GLOSSARY_TERM = "glossary_term"


class SuggestionStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    EDITED_APPROVED = "edited_approved"


class LineageRelation(StrEnum):
    DEFINES = "DEFINES"
    USES = "USES"
    DEPENDS_ON = "DEPENDS_ON"
    MAPS_TO = "MAPS_TO"
    IS_AUTHORITY_FOR = "IS_AUTHORITY_FOR"
    SOURCE_OF = "SOURCE_OF"


@dataclass(kw_only=True)
class DiscoveryBudgets:
    """Presupuestos de descubrimiento (modo por defecto conservador)."""

    max_tables_per_scan: int = 200
    max_columns_per_table: int = 200
    max_samples: int = 50
    max_query_seconds: float = 10.0
    max_scan_cost: int = 500  # número máximo de queries de metadata por scan
    max_parallelism: int = 3

    def to_dict(self) -> dict:
        return {
            "max_tables_per_scan": self.max_tables_per_scan,
            "max_columns_per_table": self.max_columns_per_table,
            "max_samples": self.max_samples,
            "max_query_seconds": self.max_query_seconds,
            "max_scan_cost": self.max_scan_cost,
            "max_parallelism": self.max_parallelism,
        }


@dataclass
class ScanBudget:
    """Contadores de presupuesto de una ejecución de scan (cancellable/resumable)."""

    budget: DiscoveryBudgets = field(default_factory=DiscoveryBudgets)
    query_count: int = 0
    tables_scanned: int = 0
    columns_profiled: int = 0
    samples_taken: int = 0
    cancelled: bool = False

    def add_query(self) -> bool:
        """True si la query puede ejecutarse; False si se agotó el presupuesto."""
        if self.query_count >= self.budget.max_scan_cost:
            return False
        self.query_count += 1
        return True

    def cancel(self) -> None:
        self.cancelled = True

    def to_dict(self) -> dict:
        return {
            "query_count": self.query_count,
            "tables_scanned": self.tables_scanned,
            "columns_profiled": self.columns_profiled,
            "samples_taken": self.samples_taken,
            "cancelled": self.cancelled,
        }


@dataclass(kw_only=True)
class CatalogSource:
    """Estado de descubrimiento por connector."""

    id: UUID = field(default_factory=uuid4)
    organization_id: UUID
    connector_id: UUID
    kb_source_id: UUID | None = None
    engine: str = ""  # postgres | mysql | mssql | oracle | db2
    phase: DiscoveryPhase = DiscoveryPhase.QUEUED
    budgets: dict = field(default_factory=dict)
    last_scan_at: datetime | None = None
    next_scan_at: datetime | None = None
    scan_interval_hours: int = 0  # 0 = sin rescan automático
    content_signature: str | None = None
    scan_error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(kw_only=True)
class CatalogScan:
    """Historial de scans + cambios detectados (drift)."""

    id: UUID = field(default_factory=uuid4)
    organization_id: UUID
    source_id: UUID
    scan_type: ScanType = ScanType.INITIAL
    status: str = "completed"  # queued | running | completed | partial | failed | cancelled
    tables_scanned: int = 0
    changes: list[dict] = field(default_factory=list)
    error: str | None = None
    duration_ms: float = 0.0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(kw_only=True)
class CatalogTable:
    id: UUID = field(default_factory=uuid4)
    organization_id: UUID
    source_id: UUID
    schema_name: str = ""
    table_name: str
    is_view: bool = False
    row_count_approx: int | None = None
    table_comment: str | None = None
    indexes: list[dict] = field(default_factory=list)
    content_hash: str | None = None
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    removed_at: datetime | None = None

    @property
    def qualified_name(self) -> str:
        return f"{self.schema_name}.{self.table_name}" if self.schema_name else self.table_name


@dataclass(kw_only=True)
class CatalogColumn:
    id: UUID = field(default_factory=uuid4)
    organization_id: UUID
    table_id: UUID
    column_name: str
    ordinal_position: int = 0
    data_type: str = ""
    nullable: bool = True
    is_primary_key: bool = False
    column_default: str | None = None
    column_comment: str | None = None
    null_ratio: float | None = None
    cardinality_approx: int | None = None
    pii_flags: list[str] = field(default_factory=list)
    is_sensitive: bool = False
    sample_disabled: bool = False


@dataclass(kw_only=True)
class CatalogRelationship:
    id: UUID = field(default_factory=uuid4)
    organization_id: UUID
    source_id: UUID
    from_table_id: UUID
    from_column: str
    to_table_id: UUID
    to_column: str
    relation_type: str = "foreign_key"  # foreign_key | inferred
    confidence: str = "high"  # high | medium | low
    status: RelationshipStatus = RelationshipStatus.SUGGESTED
    evidence: list[str] = field(default_factory=list)
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(kw_only=True)
class CatalogEntity:
    """Business Entity (ej: Customer)."""

    id: UUID = field(default_factory=uuid4)
    organization_id: UUID
    name: str
    display_name: str = ""
    description: str | None = None
    provenance: CatalogProvenance = CatalogProvenance.INFERRED
    confidence: str = "low"  # high | medium | low
    evidence: list[str] = field(default_factory=list)
    mapped_table_id: UUID | None = None
    status: str = "draft"  # draft | approved | deprecated
    created_by: UUID | None = None
    approved_by: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(kw_only=True)
class CatalogField:
    """Business Field (ej: customer_id -> CUST_ID)."""

    id: UUID = field(default_factory=uuid4)
    organization_id: UUID
    entity_id: UUID
    name: str
    description: str | None = None
    provenance: CatalogProvenance = CatalogProvenance.INFERRED
    confidence: str = "low"
    mapped_column_id: UUID | None = None
    status: str = "draft"
    created_by: UUID | None = None
    approved_by: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(kw_only=True)
class CatalogMetric:
    """Business Metric gobernada (formula nunca se ejecuta sin validación)."""

    id: UUID = field(default_factory=uuid4)
    organization_id: UUID
    metric_key: str
    name: str
    definition: str
    formula: str | None = None
    semantic_dependencies: list[str] = field(default_factory=list)
    physical_mappings: list[dict] = field(default_factory=list)
    filters: list[dict] = field(default_factory=list)
    time_semantics: str | None = None
    currency_semantics: str | None = None
    owner: str | None = None
    status: str = "draft"  # draft | approved | deprecated
    version: int = 1
    definition_id: UUID | None = None  # puente a business_definitions (Answerability)
    created_by: UUID | None = None
    approved_by: UUID | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(kw_only=True)
class CatalogAuthority:
    """Source Authority: qué fuente manda para cada concepto/dominio."""

    id: UUID = field(default_factory=uuid4)
    organization_id: UUID
    domain: str
    concept: str
    source_name: str
    source_type: str = "connector"  # connector | document | api
    connector_id: UUID | None = None
    authority_level: str = "authoritative"  # authoritative | approved | informational | external
    priority: int = 1
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    created_by: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(kw_only=True)
class CatalogSuggestion:
    """Sugerencia de la Review Queue (nunca se auto-aprueba)."""

    id: UUID = field(default_factory=uuid4)
    organization_id: UUID
    type: SuggestionType
    title: str
    description: str | None = None
    evidence: list[str] = field(default_factory=list)
    confidence: str = "low"
    payload: dict = field(default_factory=dict)  # datos para materializar al aprobar
    status: SuggestionStatus = SuggestionStatus.PENDING
    affected_sources: list[str] = field(default_factory=list)
    affected_agents: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None


@dataclass(kw_only=True)
class CatalogEnumValue:
    """Valores de columna categórica (OBSERVED; significado solo APPROVED)."""

    id: UUID = field(default_factory=uuid4)
    organization_id: UUID
    column_id: UUID
    value: str
    occurrence_count: int = 0
    documented_meaning: str | None = None
    provenance: CatalogProvenance = CatalogProvenance.OBSERVED
    confidence: str = "low"
    status: str = "pending"  # pending | approved | rejected
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(kw_only=True)
class LineageEdge:
    """Arista de lineage / Enterprise Context Graph (PostgreSQL, sin graph DB)."""

    id: UUID = field(default_factory=uuid4)
    organization_id: UUID
    upstream_type: str  # business_entity | business_metric | business_field | physical_column | physical_table | glossary_term | source
    upstream_id: str
    downstream_type: str
    downstream_id: str
    relation: LineageRelation = LineageRelation.DEFINES
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(kw_only=True)
class ReadinessReport:
    """Context Readiness por fuente — nunca un % solo, siempre con composición."""

    organization_id: UUID
    source_id: UUID
    overall: float = 0.0
    schema_coverage: float = 0.0
    relationship_coverage: float = 0.0
    description_coverage: float = 0.0
    semantic_mapping_coverage: float = 0.0
    metric_coverage: float = 0.0
    glossary_coverage: float = 0.0
    freshness: float = 0.0
    data_quality: float = 0.0
    unknown_code_count: int = 0
    pending_review_count: int = 0

    def to_dict(self) -> dict:
        return {
            "overall": round(self.overall, 2),
            "schema_coverage": round(self.schema_coverage, 2),
            "relationship_coverage": round(self.relationship_coverage, 2),
            "description_coverage": round(self.description_coverage, 2),
            "semantic_mapping_coverage": round(self.semantic_mapping_coverage, 2),
            "metric_coverage": round(self.metric_coverage, 2),
            "glossary_coverage": round(self.glossary_coverage, 2),
            "freshness": round(self.freshness, 2),
            "data_quality": round(self.data_quality, 2),
            "unknown_code_count": self.unknown_code_count,
            "pending_review_count": self.pending_review_count,
        }
