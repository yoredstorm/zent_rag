# =============================================================================
# Domain Layer — Knowledge V2 contracts (Phase A scaffolding)
# =============================================================================
# StructuredDocument + KnowledgeCorpus + full document tree. Pure types:
# no I/O, no engine wiring. INFERRED != APPROVED. Markdown is a derived view,
# not the canonical form.
#
# Phase A extension (2026-09-11): the brief §3 document model — pages,
# sections, tables, figures, chunks, entities, facts, relationships and
# multi-level summaries — each preserving provenance and locators so a later
# phase can answer "which page / section / block does this claim come from".
#
# These types are inert until RAG_KNOWLEDGE_V2_ENABLED is on (later phases).
# Do not import from KnowledgeIngestionEngine in Phase A.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from src.core.domain.catalog import CatalogProvenance


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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


class StructuredContentType(StrEnum):
    """content_type of a page/block/chunk (brief §3)."""

    TEXT = "text"
    MARKDOWN = "markdown"
    TABLE = "table"
    LIST = "list"
    CODE = "code"
    FIGURE = "figure"
    FORMULA = "formula"
    METADATA = "metadata"


class ChunkType(StrEnum):
    """Chunking strategies. Legacy fixed/recursive/sentence coexist; the
    document default becomes document_structure + parent_child (brief §8)."""

    FIXED = "fixed"
    RECURSIVE = "recursive"
    SENTENCE = "sentence"
    SEMANTIC = "semantic"
    SECTION = "section"
    PARENT_CHILD = "parent_child"
    TABLE_AWARE = "table_aware"
    DOCUMENT_STRUCTURE = "document_structure"


class KnowledgeRelationshipKind(StrEnum):
    """Cross-document / cross-source relations (brief §19)."""

    SUPPLEMENTS = "supplements"
    MODIFIES = "modifies"
    SUPERSEDES = "supersedes"
    CONTRADICTS = "contradicts"
    REFERENCES = "references"
    DUPLICATES = "duplicates"
    RELATED_TO = "related_to"


class DocumentChangeKind(StrEnum):
    """Detección de cambio contenido en re-ingesta (brief §40)."""

    CREATED = "created"
    UNCHANGED = "unchanged"
    UPDATED = "updated"
    REPLACED = "replaced"


def inferred_is_not_approved(provenance: CatalogProvenance) -> bool:
    """Law: INFERRED (and OBSERVED) are never treated as APPROVED."""
    return provenance is not CatalogProvenance.APPROVED


def _assert_approval_law(provenance: CatalogProvenance, status: KnowledgeObjectStatus) -> None:
    """A knowledge object may only be APPROVED when provenance is APPROVED.

    Human review is the ONLY path into APPROVED; construction with any other
    combination is a domain violation and is refused eagerly.
    """
    if status is KnowledgeObjectStatus.APPROVED and provenance is not CatalogProvenance.APPROVED:
        raise ValueError(
            "APPROVED status requires APPROVED provenance "
            f"(got provenance={provenance.value}, status={status.value}); "
            "human review is the only promotion path"
        )


class DocumentIntegrityError(ValueError):
    """Invariant violation in a StructuredDocument tree (Phase A contract)."""


@dataclass(frozen=True, kw_only=True)
class BoundingBox:
    """Optional spatial location of a page element (PDF layout coordinates)."""

    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    unit: str = "pt"

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValueError(f"BoundingBox page must be >= 1, got {self.page}")
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("BoundingBox must satisfy x1 >= x0 and y1 >= y0")


@dataclass(frozen=True, kw_only=True)
class CharRange:
    """[start, end) character offsets into the raw source text (brief §3)."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end <= self.start:
            raise ValueError(
                f"CharRange must satisfy 0 <= start < end, got ({self.start}, {self.end})"
            )

    @property
    def length(self) -> int:
        return self.end - self.start


@dataclass(frozen=True, kw_only=True)
class KnowledgeEvidence:
    """Grounding locator: where an entity/fact/relationship was read from.

    Everything that asserts knowledge carries at least one evidence pointer so
    a later phase can render a source-first citation (page / section / block).
    """

    organization_id: UUID
    workspace_id: UUID | None = None
    source_id: UUID | None = None
    document_id: UUID | None = None
    section_path: tuple[str, ...] = ()
    page_number: int | None = None
    block_id: UUID | None = None
    chunk_id: UUID | None = None
    excerpt: str = ""
    confidence: float = 0.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("KnowledgeEvidence.confidence must be within [0, 1]")


@dataclass(frozen=True, kw_only=True)
class StructuredBlock:
    """One lossless unit of a StructuredDocument (section, table, paragraph)."""

    kind: StructuredBlockKind
    text: str
    order: int = 0
    page: int | None = None
    heading_path: tuple[str, ...] = ()
    content_type: StructuredContentType = StructuredContentType.TEXT
    char_range: CharRange | None = None
    bbox: BoundingBox | None = None
    language: str | None = None
    token_count: int = 0
    content_hash: str | None = None
    metadata: dict = field(default_factory=dict)
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if self.order < 0:
            raise ValueError(f"StructuredBlock.order must be >= 0, got {self.order}")
        if self.token_count < 0:
            raise ValueError("StructuredBlock.token_count must be >= 0")


@dataclass(frozen=True, kw_only=True)
class DocumentPage:
    """One page of a StructuredDocument; keeps reading order via block_ids.

    Optional for non-paginated formats (DOCX/HTML/Markdown) — parsers simply
    emit no pages for those.
    """

    id: UUID = field(default_factory=uuid4)
    document_id: UUID
    organization_id: UUID
    workspace_id: UUID | None = None
    source_id: UUID | None = None
    page_number: int
    text: str = ""
    block_ids: tuple[UUID, ...] = ()
    bbox: BoundingBox | None = None
    char_range: CharRange | None = None
    language: str | None = None
    token_count: int = 0
    content_hash: str | None = None
    provenance: CatalogProvenance = CatalogProvenance.OBSERVED
    status: KnowledgeObjectStatus = KnowledgeObjectStatus.OBSERVED
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        _assert_approval_law(self.provenance, self.status)
        if self.page_number < 1:
            raise ValueError(f"DocumentPage.page_number must be >= 1, got {self.page_number}")
        if self.token_count < 0:
            raise ValueError("DocumentPage.token_count must be >= 0")


@dataclass(frozen=True, kw_only=True)
class SectionSummary:
    """Multi-level summarization: one level per section (brief §7).

    Summaries never replace original content; they exist for retrieval routing,
    navigation and broad questions, and always carry provenance (INFERRED).
    """

    id: UUID = field(default_factory=uuid4)
    document_id: UUID
    section_id: UUID
    organization_id: UUID
    workspace_id: UUID | None = None
    source_id: UUID | None = None
    summary: str
    key_points: tuple[str, ...] = ()
    language: str | None = None
    token_count: int = 0
    model: str | None = None
    prompt_version: str | None = None
    content_hash: str | None = None
    provenance: CatalogProvenance = CatalogProvenance.INFERRED
    status: KnowledgeObjectStatus = KnowledgeObjectStatus.INFERRED
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        _assert_approval_law(self.provenance, self.status)
        if not self.summary:
            raise ValueError("SectionSummary.summary must not be empty")
        if self.token_count < 0:
            raise ValueError("SectionSummary.token_count must be >= 0")


@dataclass(frozen=True, kw_only=True)
class DocumentSection:
    """A section of the document tree (heading_path, page span, blocks).

    section_path is the stable locator a citation resolves to — e.g.
    ("5", "5.2") for "Manual Operaciones.pdf · Sección 5.2". parent_id builds
    the tree; depth is explicit (not recomputed) for cheap assembly.
    """

    id: UUID = field(default_factory=uuid4)
    document_id: UUID
    organization_id: UUID
    workspace_id: UUID | None = None
    source_id: UUID | None = None
    section_path: tuple[str, ...]
    heading: str = ""
    depth: int = 0
    parent_id: UUID | None = None
    order: int = 0
    page_start: int | None = None
    page_end: int | None = None
    block_ids: tuple[UUID, ...] = ()
    text: str = ""
    language: str | None = None
    token_count: int = 0
    content_hash: str | None = None
    summary: SectionSummary | None = None
    provenance: CatalogProvenance = CatalogProvenance.OBSERVED
    status: KnowledgeObjectStatus = KnowledgeObjectStatus.OBSERVED
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        _assert_approval_law(self.provenance, self.status)
        if not self.section_path:
            raise ValueError("DocumentSection.section_path must not be empty")
        if self.depth < 0:
            raise ValueError(f"DocumentSection.depth must be >= 0, got {self.depth}")
        if self.parent_id == self.id:
            raise ValueError("DocumentSection.parent_id cannot reference itself")
        if self.page_start is not None and self.page_end is not None:
            if self.page_start > self.page_end:
                raise ValueError("DocumentSection.page_start must be <= page_end")
        if self.token_count < 0:
            raise ValueError("DocumentSection.token_count must be >= 0")


@dataclass(frozen=True, kw_only=True)
class DocumentTable:
    """A table preserved losslessly (headers + rows), not flattened to text."""

    id: UUID = field(default_factory=uuid4)
    document_id: UUID
    organization_id: UUID
    workspace_id: UUID | None = None
    source_id: UUID | None = None
    caption: str = ""
    headers: tuple[str, ...] = ()
    rows: tuple[tuple[str, ...], ...] = ()
    page: int | None = None
    bbox: BoundingBox | None = None
    char_range: CharRange | None = None
    token_count: int = 0
    content_hash: str | None = None
    provenance: CatalogProvenance = CatalogProvenance.OBSERVED
    status: KnowledgeObjectStatus = KnowledgeObjectStatus.OBSERVED
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        _assert_approval_law(self.provenance, self.status)
        if self.page is not None and self.page < 1:
            raise ValueError(f"DocumentTable.page must be >= 1, got {self.page}")
        if self.token_count < 0:
            raise ValueError("DocumentTable.token_count must be >= 0")

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def column_count(self) -> int:
        if self.headers:
            return len(self.headers)
        return len(self.rows[0]) if self.rows else 0


@dataclass(frozen=True, kw_only=True)
class DocumentFigure:
    """Figure/illustration; citation may point at the caption + bbox."""

    id: UUID = field(default_factory=uuid4)
    document_id: UUID
    organization_id: UUID
    workspace_id: UUID | None = None
    source_id: UUID | None = None
    caption: str = ""
    figure_type: str = "image"  # image | chart | diagram | formula | logo | scan
    alt_text: str | None = None
    page: int | None = None
    bbox: BoundingBox | None = None
    token_count: int = 0
    content_hash: str | None = None
    provenance: CatalogProvenance = CatalogProvenance.OBSERVED
    status: KnowledgeObjectStatus = KnowledgeObjectStatus.OBSERVED
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        _assert_approval_law(self.provenance, self.status)
        if self.page is not None and self.page < 1:
            raise ValueError(f"DocumentFigure.page must be >= 1, got {self.page}")
        if self.token_count < 0:
            raise ValueError("DocumentFigure.token_count must be >= 0")


@dataclass(frozen=True, kw_only=True)
class DocumentChunk:
    """One retrieval unit with parent/child + section + page locators.

    A small child chunk may be retrieved; the parent/section becomes the final
    context (brief §8). chunk_index is the order within one document.
    """

    id: UUID = field(default_factory=uuid4)
    document_id: UUID
    organization_id: UUID
    workspace_id: UUID | None = None
    source_id: UUID | None = None
    corpus_id: UUID | None = None
    chunk_index: int = 0
    chunk_type: ChunkType = ChunkType.DOCUMENT_STRUCTURE
    parent_id: UUID | None = None
    section_id: UUID | None = None
    page_start: int | None = None
    page_end: int | None = None
    content: str
    content_type: StructuredContentType = StructuredContentType.TEXT
    char_range: CharRange | None = None
    language: str | None = None
    token_count: int = 0
    content_hash: str = ""
    provenance: CatalogProvenance = CatalogProvenance.OBSERVED
    status: KnowledgeObjectStatus = KnowledgeObjectStatus.OBSERVED
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        _assert_approval_law(self.provenance, self.status)
        if self.chunk_index < 0:
            raise ValueError(f"DocumentChunk.chunk_index must be >= 0, got {self.chunk_index}")
        if not self.content.strip():
            raise ValueError("DocumentChunk.content must not be empty")
        if self.token_count < 0:
            raise ValueError("DocumentChunk.token_count must be >= 0")
        if self.page_start is not None and self.page_end is not None:
            if self.page_start > self.page_end:
                raise ValueError("DocumentChunk.page_start must be <= page_end")


@dataclass(frozen=True, kw_only=True)
class KnowledgeEntity:
    """Named entity extracted from a source (person/org/date/amount/concept)."""

    id: UUID = field(default_factory=uuid4)
    organization_id: UUID
    workspace_id: UUID | None = None
    source_id: UUID | None = None
    document_id: UUID | None = None
    entity_type: str = "concept"  # person | organization | date | amount | concept | acronym | ...
    name: str
    normalized_value: str | None = None
    aliases: tuple[str, ...] = ()
    confidence: float = 0.0
    evidence: tuple[KnowledgeEvidence, ...] = ()
    provenance: CatalogProvenance = CatalogProvenance.INFERRED
    status: KnowledgeObjectStatus = KnowledgeObjectStatus.INFERRED
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        _assert_approval_law(self.provenance, self.status)
        if not self.name:
            raise ValueError("KnowledgeEntity.name must not be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("KnowledgeEntity.confidence must be within [0, 1]")


@dataclass(frozen=True, kw_only=True)
class KnowledgeFact:
    """Structured fact (subject/predicate/object) with temporal window.

    document_insights (data_onboarding) become KnowledgeFact instances in a
    later phase without losing their statuses; valid_from/valid_to/observed_at
    support temporal knowledge (§20).
    """

    id: UUID = field(default_factory=uuid4)
    organization_id: UUID
    workspace_id: UUID | None = None
    source_id: UUID | None = None
    document_id: UUID | None = None
    fact_type: str = "statement"  # statement | date | amount | party | clause | rule
    subject: str
    predicate: str
    object_value: str | None = None
    confidence: float = 0.0
    evidence: tuple[KnowledgeEvidence, ...] = ()
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    observed_at: datetime | None = None
    version: int = 1
    provenance: CatalogProvenance = CatalogProvenance.INFERRED
    status: KnowledgeObjectStatus = KnowledgeObjectStatus.INFERRED
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        _assert_approval_law(self.provenance, self.status)
        if not self.subject or not self.predicate:
            raise ValueError("KnowledgeFact requires non-empty subject and predicate")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("KnowledgeFact.confidence must be within [0, 1]")
        if self.version < 1:
            raise ValueError(f"KnowledgeFact.version must be >= 1, got {self.version}")
        if self.valid_from is not None and self.valid_to is not None:
            if self.valid_to < self.valid_from:
                raise ValueError("KnowledgeFact.valid_to must be >= valid_from")

    @property
    def statement(self) -> str:
        return " ".join(
            part for part in (self.subject, self.predicate, self.object_value) if part
        )


@dataclass(frozen=True, kw_only=True)
class RelationshipEndpoint:
    """One side of a KnowledgeRelationship (cross-document friendly)."""

    organization_id: UUID
    node_kind: str  # entity | fact | section | chunk | document
    node_id: UUID
    workspace_id: UUID | None = None
    source_id: UUID | None = None
    document_id: UUID | None = None
    label: str = ""
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.node_kind:
            raise ValueError("RelationshipEndpoint.node_kind must not be empty")


@dataclass(frozen=True, kw_only=True)
class KnowledgeRelationship:
    """Cross-document relation with mandatory provenance (brief §19)."""

    id: UUID = field(default_factory=uuid4)
    organization_id: UUID
    kind: KnowledgeRelationshipKind
    from_node: RelationshipEndpoint
    to_node: RelationshipEndpoint
    workspace_id: UUID | None = None
    confidence: float = 0.0
    evidence: tuple[KnowledgeEvidence, ...] = ()
    notes: str | None = None
    provenance: CatalogProvenance = CatalogProvenance.INFERRED
    status: KnowledgeObjectStatus = KnowledgeObjectStatus.INFERRED
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        _assert_approval_law(self.provenance, self.status)
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("KnowledgeRelationship.confidence must be within [0, 1]")
        for endpoint in (self.from_node, self.to_node):
            if endpoint.organization_id != self.organization_id:
                raise ValueError(
                    "KnowledgeRelationship must not cross organization boundaries "
                    "(tenant isolation invariant)"
                )


@dataclass(frozen=True, kw_only=True)
class DocumentSummary:
    """Document-level summary (INFERRED until human review)."""

    id: UUID = field(default_factory=uuid4)
    document_id: UUID
    organization_id: UUID
    workspace_id: UUID | None = None
    source_id: UUID | None = None
    summary: str
    key_topics: tuple[str, ...] = ()
    key_points: tuple[str, ...] = ()
    language: str | None = None
    token_count: int = 0
    model: str | None = None
    prompt_version: str | None = None
    content_hash: str | None = None
    provenance: CatalogProvenance = CatalogProvenance.INFERRED
    status: KnowledgeObjectStatus = KnowledgeObjectStatus.INFERRED
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        _assert_approval_law(self.provenance, self.status)
        if not self.summary:
            raise ValueError("DocumentSummary.summary must not be empty")
        if self.token_count < 0:
            raise ValueError("DocumentSummary.token_count must be >= 0")


@dataclass(frozen=True, kw_only=True)
class StructuredDocument:
    """Canonical V2 file representation: SOURCE → STRUCTURED.

    Distinct from V1 Markdown strings and from Qdrant chunks. `as_markdown()`
    is a lossy derived view for coexistence with V1 chunkers. `check_consistency()`
    validates the full tree (page/section/table/figure/summary) before a later
    phase persists or indexes it.

    New container fields are additive and optional; existing Phase A callers
    (blocks-only documents) keep working unchanged.
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
    document_type: str | None = None
    language: str | None = None
    blocks: tuple[StructuredBlock, ...] = ()
    pages: tuple[DocumentPage, ...] = ()
    sections: tuple[DocumentSection, ...] = ()
    tables: tuple[DocumentTable, ...] = ()
    figures: tuple[DocumentFigure, ...] = ()
    summary: DocumentSummary | None = None
    provenance: CatalogProvenance = CatalogProvenance.OBSERVED
    status: KnowledgeObjectStatus = KnowledgeObjectStatus.OBSERVED
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        _assert_approval_law(self.provenance, self.status)
        page_numbers = [p.page_number for p in self.pages]
        if len(set(page_numbers)) != len(page_numbers):
            raise ValueError("StructuredDocument.pages must have unique page_number")

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def section_count(self) -> int:
        return len(self.sections)

    @property
    def table_count(self) -> int:
        return len(self.tables)

    @property
    def figure_count(self) -> int:
        return len(self.figures)

    @property
    def block_count(self) -> int:
        return len(self.blocks)

    def block_ids(self) -> frozenset[UUID]:
        return frozenset(block.id for block in self.blocks)

    def check_consistency(self) -> None:
        """Full-tree invariants before persistence/indexing (Phase B+).

        Raises DocumentIntegrityError on: child document_id mismatches, unknown
        block references, orphan parent sections, root-missing section. This is
        an explicit validation the parser/service must call; construction itself
        stays permissive so parsers can assemble incrementally.
        """
        known_blocks = self.block_ids()
        known_sections = {section.id for section in self.sections}

        for page in self.pages:
            if page.document_id != self.id:
                raise DocumentIntegrityError(
                    f"page {page.page_number} document_id ({page.document_id}) "
                    f"!= owning document ({self.id})"
                )
            unknown = [bid for bid in page.block_ids if bid not in known_blocks]
            if unknown:
                raise DocumentIntegrityError(
                    f"page {page.page_number} references unknown blocks: {unknown}"
                )

        for section in self.sections:
            if section.document_id != self.id:
                raise DocumentIntegrityError(
                    f"section {section.section_path} document_id ({section.document_id}) "
                    f"!= owning document ({self.id})"
                )
            unknown = [bid for bid in section.block_ids if bid not in known_blocks]
            if unknown:
                raise DocumentIntegrityError(
                    f"section {section.section_path} references unknown blocks: {unknown}"
                )
            if section.parent_id is not None and section.parent_id not in known_sections:
                raise DocumentIntegrityError(
                    f"section {section.section_path} references unknown parent "
                    f"{section.parent_id}"
                )

        for table in self.tables:
            if table.document_id != self.id:
                raise DocumentIntegrityError(
                    f"table {table.id} document_id ({table.document_id}) "
                    f"!= owning document ({self.id})"
                )

        for figure in self.figures:
            if figure.document_id != self.id:
                raise DocumentIntegrityError(
                    f"figure {figure.id} document_id ({figure.document_id}) "
                    f"!= owning document ({self.id})"
                )

        if self.summary is not None and self.summary.document_id != self.id:
            raise DocumentIntegrityError(
                f"summary document_id ({self.summary.document_id}) "
                f"!= owning document ({self.id})"
            )

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
class DocumentVersion:
    """Versión de un StructuredDocument (brief §40).

    change_kind: created | unchanged | updated | replaced. La invalidación de
    artefactos dependientes (embeddings, summaries, facts, relationships) se
    dispara en fases siguientes cuando change_kind != unchanged.
    """

    organization_id: UUID
    document_id: UUID
    content_hash: str
    id: UUID = field(default_factory=uuid4)
    workspace_id: UUID | None = None
    source_id: UUID | None = None
    version: int = 1
    change_kind: DocumentChangeKind = DocumentChangeKind.CREATED
    previous_version_id: UUID | None = None
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError(f"DocumentVersion.version must be >= 1, got {self.version}")
        if not self.content_hash:
            raise ValueError("DocumentVersion.content_hash must not be empty")


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
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("KnowledgeCorpus.name must not be empty")
