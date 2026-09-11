# =============================================================================
# Domain Layer — Knowledge V2 contracts (Phase A types + Phase B locators)
# =============================================================================
# StructuredDocument + KnowledgeCorpus. Pure types: no I/O, no engine wiring.
# INFERRED != APPROVED. Markdown is a derived view, not the canonical form.
#
# Phase B extends StructuredBlock with citation provenance (page / section /
# block / char span / content_hash) so Phase G can highlight [1] in the viewer.
# Do not import from KnowledgeIngestionEngine (V1 remains the production path).
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID, uuid4

from src.core.domain.catalog import CatalogProvenance

# Reasons used when page_number is null. Parsers must set one of these (or a
# documented adapter-specific reason) rather than leaving the gap implicit.
PAGE_ABSENT_FORMAT_HAS_NO_PAGES = "format_has_no_pages"
PAGE_ABSENT_MARKITDOWN_FALLBACK = "markitdown_textual_fallback"
PAGE_ABSENT_STUB_FORMAT = "stub_format_not_parsed"
PAGE_ABSENT_EMPTY_DOCUMENT = "empty_document"
PAGE_ABSENT_NOT_PROVIDED = "not_provided"

SECTION_ABSENT_PLAIN_TEXT = "plain_text_has_no_headings"
SECTION_ABSENT_NO_HEADINGS = "no_headings_detected"
SECTION_ABSENT_STUB_FORMAT = "stub_format_not_parsed"


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
    """One lossless unit of a StructuredDocument (section, table, paragraph).

    Citation provenance (Phase B / Phase G):
    - ``page`` / ``page_number`` — 1-based PDF page, or null + ``page_absent_reason``
    - ``heading_path`` / ``section_path`` — heading ancestry for the viewer
    - ``order`` / ``block_index`` — reading-order index inside the document
    - ``text`` / ``content`` + ``kind`` / ``content_type``
    - ``char_start`` / ``char_end`` — optional offsets in concatenated text
    - ``content_hash`` — sha256 of ``text`` (set by V2 parsers; optional on hand-built blocks)
    """

    kind: StructuredBlockKind
    text: str
    order: int = 0
    page: int | None = None
    heading_path: tuple[str, ...] = ()
    metadata: dict = field(default_factory=dict)
    id: UUID = field(default_factory=uuid4)
    char_start: int | None = None
    char_end: int | None = None
    content_hash: str | None = None
    page_absent_reason: str | None = None

    @property
    def page_number(self) -> int | None:
        return self.page

    @property
    def section_path(self) -> tuple[str, ...]:
        return self.heading_path

    @property
    def block_index(self) -> int:
        return self.order

    @property
    def content(self) -> str:
        return self.text

    @property
    def content_type(self) -> str:
        return self.kind.value

    def citation_locator(self) -> dict:
        """Stable locator for Phase G inline citations ([1] → viewer highlight)."""
        return {
            "block_id": str(self.id),
            "page_number": self.page,
            "page_absent_reason": self.page_absent_reason,
            "section_path": list(self.heading_path),
            "block_index": self.order,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "content_hash": self.content_hash,
            "content_type": self.kind.value,
            "content": self.text,
        }


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
