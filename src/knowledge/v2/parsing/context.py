# =============================================================================
# ParseContext + document assembly
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from src.core.domain.catalog import CatalogProvenance
from src.core.domain.knowledge_v2 import (
    KnowledgeObjectStatus,
    StructuredBlock,
    StructuredBlockKind,
    StructuredDocument,
)
from src.knowledge.v2.parsing.blocks import sha256_bytes


@dataclass(frozen=True, kw_only=True)
class ParseContext:
    data: bytes
    filename: str
    organization_id: UUID
    workspace_id: UUID | None = None
    source_id: UUID | None = None
    document_id: UUID | None = None
    mime_type: str | None = None
    external_id: str | None = None

    @property
    def extension(self) -> str:
        return Path(self.filename).suffix.lower().lstrip(".")

    @property
    def stem(self) -> str:
        return Path(self.filename).stem or self.filename


def title_from_blocks(blocks: list[StructuredBlock], fallback: str) -> str:
    for block in blocks:
        if block.kind in (StructuredBlockKind.TITLE, StructuredBlockKind.HEADING) and block.text:
            return block.text.strip()
    return fallback


def assemble_document(
    ctx: ParseContext,
    blocks: list[StructuredBlock],
    *,
    mime_type: str,
    adapter: str,
    extra_metadata: dict | None = None,
    title: str | None = None,
) -> StructuredDocument:
    meta = {"adapter": adapter, **(extra_metadata or {})}
    return StructuredDocument(
        id=ctx.document_id or uuid4(),
        organization_id=ctx.organization_id,
        workspace_id=ctx.workspace_id,
        source_id=ctx.source_id,
        external_id=ctx.external_id or ctx.filename,
        title=title or title_from_blocks(blocks, ctx.stem),
        content_hash=sha256_bytes(ctx.data),
        mime_type=ctx.mime_type or mime_type,
        blocks=tuple(blocks),
        provenance=CatalogProvenance.OBSERVED,
        status=KnowledgeObjectStatus.OBSERVED,
        metadata=meta,
    )
