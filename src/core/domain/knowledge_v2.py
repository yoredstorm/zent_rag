# =============================================================================
# Domain Layer — Knowledge V2 contracts (Phase A scaffolding)
# =============================================================================
# StructuredDocument + KnowledgeCorpus. Pure types: no I/O, no engine wiring.
# INFERRED != APPROVED. Markdown is a derived view, not the canonical form.
#
# These types are inert until RAG_KNOWLEDGE_V2_ENABLED is on (later phases).
# Do not import from KnowledgeIngestionEngine in Phase A.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID, uuid4

from src.core.domain.catalog import CatalogProvenance


class KnowledgeObjectStatus(StrEnum):
    """Lifecycle of a V2 knowledge object (never auto-APPROVED)."""

    DRAFT = "draft"
    OBSERVED = "observed"
    INFERRED = "inferred"
    APPROVED = "approved"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class StructuredBlockKind(StrEnum):
    TITLE = "title"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    LIST = "list"
    CODE = "code"
    FIGURE = "figure"
    METADATA = "metadata"


def inferred_is_not_approved(provenance: CatalogProvenance) -> bool:
    """Law: INFERRED (and OBSERVED) are never treated as APPROVED."""
    return provenance is not CatalogProvenance.APPROVED


@dataclass(frozen=True, kw_only=True)
class StructuredBlock:
    """One lossless unit of a StructuredDocument (section, table, paragraph)."""

    kind: StructuredBlockKind
    text: str
    order: int = 0
    page: int | None = None
    heading_path: tuple[str, ...] = ()
    metadata: dict = field(default_factory=dict)
    id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True, kw_only=True)
class StructuredDocument:
    """Canonical V2 file representation: SOURCE → STRUCTURED.

    Distinct from V1 Markdown strings and from Qdrant chunks. `as_markdown()`
    is a lossy derived view for coexistence with V1 chunkers.
    """

    id: UUID
    organization_id: UUID
    external_id: str
    title: str
    content_hash: str
    source_id: UUID | None = None
    workspace_id: UUID | None = None
    corpus_id: UUID | None = None
    mime_type: str | None = None
    language: str | None = None
    blocks: tuple[StructuredBlock, ...] = ()
    provenance: CatalogProvenance = CatalogProvenance.OBSERVED
    status: KnowledgeObjectStatus = KnowledgeObjectStatus.OBSERVED
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            self.provenance is CatalogProvenance.INFERRED
            and self.status is KnowledgeObjectStatus.APPROVED
        ):
            raise ValueError("INFERRED must not be stored as APPROVED (human review required)")

    def as_markdown(self) -> str:
        """Lossy heading/paragraph flatten for V1 chunkers. Not the source of truth."""
        lines: list[str] = []
        for block in self.blocks:
            if block.kind in (StructuredBlockKind.HEADING, StructuredBlockKind.TITLE):
                lines.append(f"# {block.text}")
            else:
                lines.append(block.text)
        return "\n\n".join(lines)


@dataclass(frozen=True, kw_only=True)
class KnowledgeCorpus:
    """Workspace-scoped collection of sources that form one queryable body.

    Distinct from KnowledgeBase (retrieval/index profile) and Workspace
    (tenant container). Optional knowledge_base_id maps 1:1 during V1 coexistence.
    """

    id: UUID
    organization_id: UUID
    workspace_id: UUID
    name: str
    slug: str
    description: str | None = None
    knowledge_base_id: UUID | None = None
    source_ids: tuple[UUID, ...] = ()
    status: KnowledgeObjectStatus = KnowledgeObjectStatus.DRAFT
