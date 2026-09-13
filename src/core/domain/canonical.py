# =============================================================================
# Domain Layer — Canonical Knowledge Model (Phase 1)
# =============================================================================
# Identidad canónica + mapping entre los silos de conocimiento existentes
# (V1/V2, catalog, KLE, data onboarding, Hub). Tipos puros, sin I/O.
#
# Leyes:
#   - La identidad canónica es determinista por (organization_id, kind,
#     natural_key): el mismo objeto lógico obtiene el mismo UUID en cualquier
#     proceso, y organizaciones distintas nunca colisionan.
#   - Un objeto canónico solo puede estar APPROVED si su provenance es APPROVED
#     (la revisión humana es el único camino de promoción).
#   - Los natural_key son estables entre re-ingestas (no dependen de los UUID
#     generados por cada parser).
#
# Persistencia: migración 102 (knowledge_canonical_objects +
# knowledge_canonical_links). El adapter vive en infrastructure/postgres.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import NAMESPACE_URL, UUID, uuid5

from src.core.domain.catalog import CatalogProvenance
from src.core.domain.knowledge_v2 import KnowledgeObjectStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CanonicalKind(StrEnum):
    """Logical knowledge object kinds that can receive a canonical identity."""

    SOURCE = "source"
    DOCUMENT = "document"
    SECTION = "section"
    BLOCK = "block"
    CHUNK = "chunk"
    ENTITY = "entity"
    FACT = "fact"
    RULE = "rule"
    METRIC = "metric"
    GLOSSARY_TERM = "glossary_term"
    RELATIONSHIP = "relationship"
    QUESTION = "question"
    CLAIM = "claim"
    EVIDENCE = "evidence"
    ARTIFACT = "artifact"


class CanonicalSystem(StrEnum):
    """Physical systems that can be linked to a canonical object."""

    V1_KNOWLEDGE_PLATFORM = "v1_knowledge_platform"
    V1_DOCUMENT_REGISTRY = "v1_document_registry"
    V2_STRUCTURED = "v2_structured"
    CATALOG = "catalog"
    KNOWLEDGE_LEARNING = "knowledge_learning"
    GOVERNED_LEARNING = "governed_learning"
    DATA_ONBOARDING = "data_onboarding"
    KNOWLEDGE_HUB = "knowledge_hub"
    INTELLIGENCE = "intelligence"


# Namespace fijo del programa (no cambiar: invalidaría todas las identidades).
CANONICAL_NAMESPACE: UUID = uuid5(NAMESPACE_URL, "https://zent.ai/knowledge/canonical/v1")

_MAX_NATURAL_KEY = 768
_MAX_TITLE = 512


def canonical_uuid(organization_id: UUID, kind: CanonicalKind, natural_key: str) -> UUID:
    """Deterministic canonical id for (org, kind, natural_key)."""
    return uuid5(CANONICAL_NAMESPACE, f"{organization_id}:{kind.value}:{natural_key}")


def assert_approval_law(provenance: CatalogProvenance, status: KnowledgeObjectStatus) -> None:
    """A knowledge object may only be APPROVED when provenance is APPROVED.

    Mirrors the Knowledge V2 domain law; human review is the only promotion
    path. Kept local so `core` stays a leaf and the V2 module is not modified.
    """
    if status is KnowledgeObjectStatus.APPROVED and provenance is not CatalogProvenance.APPROVED:
        raise ValueError(
            "APPROVED status requires APPROVED provenance "
            f"(got provenance={provenance.value}, status={status.value}); "
            "human review is the only promotion path"
        )


def _normalize(value: str) -> str:
    return " ".join(value.strip().lower().split())


# ---------------------------------------------------------------------------
# Natural keys (stable across re-ingestion; no generated UUIDs inside)
# ---------------------------------------------------------------------------

def source_natural_key(source_id: UUID) -> str:
    return f"source:{source_id}"


def document_natural_key(document_id: UUID) -> str:
    return f"document:{document_id}"


def section_natural_key(document_id: UUID, section_path: tuple[str, ...]) -> str:
    return f"section:{document_id}:{'/'.join(section_path)}"


def block_natural_key(document_id: UUID, order: int, content_hash: str) -> str:
    return f"block:{document_id}:{order}:{content_hash}"


def chunk_natural_key(document_id: UUID, chunk_index: int, content_hash: str) -> str:
    return f"chunk:{document_id}:{chunk_index}:{content_hash}"


def entity_natural_key(name: str, entity_type: str) -> str:
    return f"entity:{_normalize(entity_type)}:{_normalize(name)}"


def fact_natural_key(subject: str, predicate: str, object_value: str | None = None) -> str:
    parts = [_normalize(subject), _normalize(predicate)]
    if object_value is not None:
        parts.append(_normalize(object_value))
    return "fact:" + ":".join(parts)


def rule_natural_key(rule_key: str) -> str:
    return f"rule:{_normalize(rule_key)}"


def metric_natural_key(metric_key: str) -> str:
    return f"metric:{_normalize(metric_key)}"


def glossary_natural_key(term: str) -> str:
    return f"glossary:{_normalize(term)}"


# ---------------------------------------------------------------------------
# Canonical objects and links
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class CanonicalRef:
    """Reference to one physical object in one of the existing systems."""

    system: CanonicalSystem
    object_type: str
    object_ref: str

    def __post_init__(self) -> None:
        if not self.object_type.strip():
            raise ValueError("CanonicalRef.object_type must not be empty")
        if not self.object_ref.strip():
            raise ValueError("CanonicalRef.object_ref must not be empty")


@dataclass(frozen=True, kw_only=True)
class CanonicalObject:
    """Canonical identity of a logical knowledge object.

    `canonical_id` is always derived (never passed): same org + kind +
    natural_key yields the same UUID in every process.
    """

    organization_id: UUID
    kind: CanonicalKind
    natural_key: str
    title: str = ""
    workspace_id: UUID | None = None
    provenance: CatalogProvenance = CatalogProvenance.OBSERVED
    status: KnowledgeObjectStatus = KnowledgeObjectStatus.OBSERVED
    confidence: float | None = None
    authority_level: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    canonical_id: UUID = field(init=False)

    def __post_init__(self) -> None:
        if not self.natural_key.strip():
            raise ValueError("CanonicalObject.natural_key must not be empty")
        if len(self.natural_key) > _MAX_NATURAL_KEY:
            raise ValueError(
                f"CanonicalObject.natural_key must be <= {_MAX_NATURAL_KEY} chars"
            )
        if len(self.title) > _MAX_TITLE:
            raise ValueError(f"CanonicalObject.title must be <= {_MAX_TITLE} chars")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("CanonicalObject.confidence must be within [0, 1]")
        if self.valid_from is not None and self.valid_to is not None:
            if self.valid_to < self.valid_from:
                raise ValueError("CanonicalObject.valid_to must be >= valid_from")
        assert_approval_law(self.provenance, self.status)
        object.__setattr__(
            self,
            "canonical_id",
            canonical_uuid(self.organization_id, self.kind, self.natural_key),
        )


@dataclass(frozen=True, kw_only=True)
class CanonicalLink:
    """Mapping between a physical object and its canonical identity."""

    canonical_id: UUID
    organization_id: UUID
    ref: CanonicalRef
    workspace_id: UUID | None = None
    is_primary: bool = False
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)
