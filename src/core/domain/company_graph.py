# =============================================================================
# Domain Layer — Company Intelligence Graph (GRAPH-FIRST, STORAGE-AGNOSTIC)
# =============================================================================
# Modelo canónico para representar una organización como conjunto navegable
# de entidades y relaciones: concepts, processes, systems, data, rules,
# agents, workflows, knowledge, memories.
#
# Leyes:
#   - entity_type y relationship_type son extensibles: el registry acepta
#     tipos nuevos sin migraciones ni enums rígidos.
#   - NADA se auto-confirma salvo relaciones estructuralmente verificables
#     (ver AUTO_CONFIRMABLE_TYPES en el servicio): un LLM que infiere no es
#     evidencia estructural.
#   - Toda entidad/relación no trivial responde "¿por qué Zent cree esto?"
#     vía source + source_ref + evidence (ProvenanceRef). Nunca se guarda
#     chain-of-thought.
#   - Temporalidad: valid_from/valid_to definen vigencia. NULL = abierto.
#
# Reutiliza (NO duplica): CatalogProvenance, ClaimRecord/EvidenceRecord,
# MemoryRecord, Finding/Experiment del Learning Engine, CatalogAuthority.
# Tipos puros, sin I/O. Persistencia: migración 129. Adapter en
# infrastructure/postgres/company_graph.py. Puerto en core/ports.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Namespace fijo (no cambiar: invalidaría identidades deterministas).
COMPANY_GRAPH_NAMESPACE: UUID = uuid5(
    NAMESPACE_URL, "https://zent.ai/company/graph/v1"
)


def company_entity_uuid(
    organization_id: UUID, entity_type: str, canonical_name: str
) -> UUID:
    """Identidad determinista por (org, tipo, nombre canónico)."""
    return uuid5(
        COMPANY_GRAPH_NAMESPACE,
        f"{organization_id}:{entity_type.strip().lower()}"
        f":{canonical_name.strip().lower()}",
    )


# ---------------------------------------------------------------------------
# Entity types (extensible: ver normalize_entity_type)
# ---------------------------------------------------------------------------


class CompanyEntityType(StrEnum):
    """Tipos canónicos iniciales. NO es cerrado: el servicio acepta tipos
    nuevos vía normalize_entity_type sin cambiar este enum ni migrar."""

    ORGANIZATION = "organization"
    DOMAIN = "domain"
    CONCEPT = "concept"
    PROCESS = "process"
    POLICY = "policy"
    RULE = "rule"
    SYSTEM = "system"
    SERVICE = "service"
    DATABASE = "database"
    DATASET = "dataset"
    TABLE = "table"
    FIELD = "field"
    API = "api"
    KNOWLEDGE_SOURCE = "knowledge_source"
    DOCUMENT = "document"
    AGENT = "agent"
    WORKFLOW = "workflow"
    TOOL = "tool"
    EVENT = "event"
    METRIC = "metric"
    KPI = "kpi"
    PERSON = "person"
    ROLE = "role"
    TEAM = "team"
    CLAIM = "claim"
    MEMORY = "memory"
    DECISION = "decision"
    FINDING = "finding"
    EXPERIMENT = "experiment"
    RECOMMENDATION = "recommendation"


def normalize_entity_type(value: str) -> str:
    """Normaliza un tipo de entidad. Acepta valores fuera del enum canónico
    (extensibilidad sin proliferación de tablas)."""
    normalized = " ".join(value.strip().lower().split())
    if not normalized:
        raise ValueError("entity_type must not be empty")
    if len(normalized) > 64:
        raise ValueError("entity_type must be <= 64 chars")
    return normalized


# ---------------------------------------------------------------------------
# Relationship type registry (extensible, sin enums rígidos)
# ---------------------------------------------------------------------------


class CompanyRelationshipType(StrEnum):
    """Relaciones iniciales soportadas."""

    BELONGS_TO = "BELONGS_TO"
    CONTAINS = "CONTAINS"
    USES = "USES"
    USED_BY = "USED_BY"
    DEPENDS_ON = "DEPENDS_ON"
    GOVERNED_BY = "GOVERNED_BY"
    AUTOMATES = "AUTOMATES"
    ASSISTS = "ASSISTS"
    CONNECTS_TO = "CONNECTS_TO"
    READS_FROM = "READS_FROM"
    WRITES_TO = "WRITES_TO"
    DESCRIBES = "DESCRIBES"
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    MAPS_TO = "MAPS_TO"
    TRIGGERS = "TRIGGERS"
    PRODUCES = "PRODUCES"
    CONSUMES = "CONSUMES"
    OWNS = "OWNS"
    AFFECTS = "AFFECTS"
    RELATED_TO = "RELATED_TO"


class RelationshipRegistry:
    """Registry de tipos de relación. Los tipos conocidos vienen precargados;
    el dominio/servicio puede registrar más (APPLIES_TO, CONCERNS, IMPROVES,
    VALIDATES, ...) sin tocar el enum ni la base de datos."""

    _known: dict[str, str] = {item.value: item.value for item in CompanyRelationshipType}

    @classmethod
    def register(cls, relationship_type: str) -> str:
        normalized = normalize_relationship_type(relationship_type)
        cls._known.setdefault(normalized, normalized)
        return normalized

    @classmethod
    def normalize(cls, relationship_type: str) -> str:
        return normalize_relationship_type(relationship_type)

    @classmethod
    def is_known(cls, relationship_type: str) -> bool:
        try:
            return normalize_relationship_type(relationship_type) in cls._known
        except ValueError:
            return False

    @classmethod
    def all(cls) -> list[str]:
        return sorted(cls._known)


def normalize_relationship_type(value: str) -> str:
    """Normaliza un tipo de relación. Permite tipos custom no registrados
    (se preservan tal cual en mayúsculas)."""
    normalized = "_".join(value.strip().upper().split())
    if not normalized:
        raise ValueError("relationship_type must not be empty")
    if len(normalized) > 64:
        raise ValueError("relationship_type must be <= 64 chars")
    if any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for ch in normalized):
        raise ValueError(
            "relationship_type must contain only A-Z, 0-9 and underscores"
        )
    return normalized


# ---------------------------------------------------------------------------
# Status: nada descubierto es verdad confirmada
# ---------------------------------------------------------------------------


class EntityStatus(StrEnum):
    DISCOVERED = "discovered"
    SUPPORTED = "supported"
    CONFIRMED = "confirmed"
    CONTRADICTED = "contradicted"
    DEPRECATED = "deprecated"
    STALE = "stale"
    REJECTED = "rejected"
    AUTO_CONFIRMED = "auto_confirmed"


_TERMINAL_STATUSES = frozenset({EntityStatus.DEPRECATED, EntityStatus.REJECTED})

_NON_CURRENT_STATUSES = frozenset({EntityStatus.DEPRECATED, EntityStatus.REJECTED})

_ALLOWED_TRANSITIONS: dict[EntityStatus, frozenset[EntityStatus]] = {
    EntityStatus.DISCOVERED: frozenset(
        {
            EntityStatus.SUPPORTED,
            EntityStatus.CONFIRMED,
            # Verificación estructural: el schema confirma el nodo sin humano.
            EntityStatus.AUTO_CONFIRMED,
            EntityStatus.CONTRADICTED,
            EntityStatus.STALE,
            EntityStatus.DEPRECATED,
            EntityStatus.REJECTED,
        }
    ),
    EntityStatus.SUPPORTED: frozenset(
        {
            EntityStatus.CONFIRMED,
            EntityStatus.AUTO_CONFIRMED,
            EntityStatus.CONTRADICTED,
            EntityStatus.STALE,
            EntityStatus.DEPRECATED,
            EntityStatus.REJECTED,
        }
    ),
    EntityStatus.CONFIRMED: frozenset(
        {EntityStatus.CONTRADICTED, EntityStatus.STALE, EntityStatus.DEPRECATED}
    ),
    EntityStatus.AUTO_CONFIRMED: frozenset(
        {EntityStatus.CONTRADICTED, EntityStatus.STALE, EntityStatus.DEPRECATED}
    ),
    EntityStatus.CONTRADICTED: frozenset(
        {
            EntityStatus.SUPPORTED,
            EntityStatus.CONFIRMED,
            EntityStatus.DEPRECATED,
            EntityStatus.REJECTED,
        }
    ),
    EntityStatus.STALE: frozenset(
        {
            EntityStatus.DISCOVERED,
            EntityStatus.SUPPORTED,
            EntityStatus.DEPRECATED,
            EntityStatus.REJECTED,
        }
    ),
    EntityStatus.DEPRECATED: frozenset(),
    EntityStatus.REJECTED: frozenset(),
}


def assert_status_transition(old: EntityStatus, new: EntityStatus) -> None:
    """Ley de transición de estados. Terminales no salen."""
    if old is new:
        return
    if new not in _ALLOWED_TRANSITIONS[old]:
        raise ValueError(
            f"status transition not allowed: {old.value} -> {new.value}"
        )


def is_current_status(status: EntityStatus) -> bool:
    return status not in _NON_CURRENT_STATUSES


# ---------------------------------------------------------------------------
# Source authority (5 niveles del spec; mapeo a catalog_authority en service)
# ---------------------------------------------------------------------------


class SourceAuthorityLevel(StrEnum):
    AUTHORITATIVE = "authoritative"
    PRIMARY = "primary"
    SECONDARY = "secondary"
    INFORMATIONAL = "informational"
    UNTRUSTED = "untrusted"


_SOURCE_AUTHORITY_RANK: dict[SourceAuthorityLevel, int] = {
    SourceAuthorityLevel.AUTHORITATIVE: 4,
    SourceAuthorityLevel.PRIMARY: 3,
    SourceAuthorityLevel.SECONDARY: 2,
    SourceAuthorityLevel.INFORMATIONAL: 1,
    SourceAuthorityLevel.UNTRUSTED: 0,
}


def source_authority_rank(level: SourceAuthorityLevel | None) -> int:
    """Rango numérico del nivel de autoridad. Sin nivel = 1 (informational):
    nunca se asume autoridad por ausencia de regla."""
    if level is None:
        return 1
    return _SOURCE_AUTHORITY_RANK[level]


# ---------------------------------------------------------------------------
# Provenance: ¿por qué Zent cree esto? (sin chain-of-thought)
# ---------------------------------------------------------------------------


class ProvenanceKind(StrEnum):
    """Orígenes trazables. Reutiliza stores existentes (claim, memory,
    evidence_ledger, document, schema/catalog) en vez de duplicarlos."""

    SOURCE = "source"
    CLAIM = "claim"
    MEMORY = "memory"
    CONVERSATION = "conversation"
    RUN = "run"
    EXPERIMENT = "experiment"
    FINDING = "finding"
    RECOMMENDATION = "recommendation"
    SCHEMA = "schema"
    CATALOG = "catalog"
    DATABASE = "database"
    DOCUMENT = "document"
    MANUAL = "manual"
    EVIDENCE = "evidence"


@dataclass(frozen=True, kw_only=True)
class ProvenanceRef:
    """Referencia estructurada a la evidencia que sostiene una entidad o
    relación. `ref` es el id del objeto en su store de origen."""

    kind: ProvenanceKind
    ref: str

    def __post_init__(self) -> None:
        if not self.ref.strip():
            raise ValueError("ProvenanceRef.ref must not be empty")

    def to_dict(self) -> dict:
        return {"kind": self.kind.value, "ref": self.ref}

    @classmethod
    def from_dict(cls, payload: dict) -> ProvenanceRef:
        return cls(kind=ProvenanceKind(payload["kind"]), ref=str(payload["ref"]))


# ---------------------------------------------------------------------------
# CompanyEntity
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class CompanyEntity:
    """Nodo canónico del grafo de compañía. `id` es determinista por
    (org, entity_type, canonical_name): el mismo concepto lógico obtiene el
    mismo UUID en cualquier proceso (upsert idempotente)."""

    organization_id: UUID
    entity_type: str
    canonical_name: str
    display_name: str = ""
    description: str = ""
    domain: str = "general"
    aliases: tuple[str, ...] = ()
    status: EntityStatus = EntityStatus.DISCOVERED
    confidence: float | None = None
    authority_level: SourceAuthorityLevel | None = None
    source: str = ""
    source_ref: str = ""
    evidence: tuple[ProvenanceRef, ...] = ()
    metadata: dict = field(default_factory=dict)
    workspace_id: UUID | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    first_observed_at: datetime = field(default_factory=_utcnow)
    last_observed_at: datetime = field(default_factory=_utcnow)
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    id: UUID = field(init=False)

    def __post_init__(self) -> None:
        entity_type = normalize_entity_type(self.entity_type)
        object.__setattr__(self, "entity_type", entity_type)
        if not self.canonical_name.strip():
            raise ValueError("CompanyEntity.canonical_name must not be empty")
        if len(self.canonical_name) > 320:
            raise ValueError("CompanyEntity.canonical_name must be <= 320 chars")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("CompanyEntity.confidence must be within [0, 1]")
        if self.valid_from is not None and self.valid_to is not None:
            if self.valid_to < self.valid_from:
                raise ValueError("CompanyEntity.valid_to must be >= valid_from")
        object.__setattr__(
            self,
            "id",
            company_entity_uuid(
                self.organization_id, entity_type, self.canonical_name
            ),
        )


# ---------------------------------------------------------------------------
# CompanyRelationship
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class CompanyRelationship:
    """Arista dirigida del grafo. from -> to con tipo extensible."""

    organization_id: UUID
    from_entity_id: UUID
    to_entity_id: UUID
    relationship_type: str
    status: EntityStatus = EntityStatus.DISCOVERED
    confidence: float | None = None
    source: str = ""
    source_ref: str = ""
    evidence_refs: tuple[ProvenanceRef, ...] = ()
    metadata: dict = field(default_factory=dict)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    first_observed_at: datetime = field(default_factory=_utcnow)
    last_observed_at: datetime = field(default_factory=_utcnow)
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "relationship_type", normalize_relationship_type(self.relationship_type)
        )
        if self.from_entity_id == self.to_entity_id:
            raise ValueError("CompanyRelationship must link two different entities")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("CompanyRelationship.confidence must be within [0, 1]")
        if self.valid_from is not None and self.valid_to is not None:
            if self.valid_to < self.valid_from:
                raise ValueError("CompanyRelationship.valid_to must be >= valid_from")


# ---------------------------------------------------------------------------
# Temporal helpers
# ---------------------------------------------------------------------------


def is_valid_at(
    valid_from: datetime | None,
    valid_to: datetime | None,
    as_of: datetime,
) -> bool:
    """Vigencia semiabierta: [valid_from, valid_to). NULL = abierto."""
    if valid_from is not None and as_of < valid_from:
        return False
    if valid_to is not None and as_of >= valid_to:
        return False
    return True


def is_current(
    status: EntityStatus,
    valid_from: datetime | None,
    valid_to: datetime | None,
    as_of: datetime | None = None,
) -> bool:
    """Vista 'current': no terminal + vigente a la fecha."""
    if not is_current_status(status):
        return False
    return is_valid_at(valid_from, valid_to, as_of or _utcnow())
