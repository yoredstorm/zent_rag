# =============================================================================
# Knowledge V2 — Hierarchical chunking (Phase C slice 1)
# =============================================================================
# document_structure + parent_child (brief §8): un chunk padre por sección hoja
# (contexto final) y chunks hijos pequeños para retrieval (parent_id +
# section_id + page span). Los bloques fuera de secciones se agrupan bajo un
# chunk padre implícito del documento. Puro y determinista; sin LLM.
# =============================================================================
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from uuid import UUID, uuid4

from src.core.domain.catalog import CatalogProvenance
from src.core.domain.knowledge_v2 import (
    CharRange,
    ChunkType,
    DocumentChunk,
    DocumentSection,
    KnowledgeObjectStatus,
    StructuredBlock,
    StructuredDocument,
)
from src.knowledge.structure.base import content_hash, token_count


@dataclass(frozen=True, kw_only=True)
class ChunkingConfig:
    child_max_chars: int = 600
    child_overlap: int = 50


def assign_blocks_to_sections(
    document: StructuredDocument,
) -> StructuredDocument:
    """Atribuye los bloques de cuerpo a la sección activa (in-order).

    Los parsers anclan solo el heading a la sección; este paso enriquece
    block_ids con los bloques que caen bajo cada sección en orden de lectura.
    No muta: devuelve un StructuredDocument reconstruido.
    """
    if not document.blocks or not document.sections:
        return document

    section_by_heading: dict[UUID, DocumentSection] = {}
    for section in document.sections:
        for heading_block_id in section.block_ids:
            section_by_heading[heading_block_id] = section

    ordered_sections = sorted(document.sections, key=lambda s: s.order)
    stack: list[DocumentSection] = []
    owners: dict[UUID, UUID] = {}
    for block in sorted(document.blocks, key=lambda b: b.order):
        section_of_heading = section_by_heading.get(block.id)
        if section_of_heading is not None:
            while stack and stack[-1].depth >= section_of_heading.depth:
                stack.pop()
            stack.append(section_of_heading)
            continue
        if stack:
            owners[block.id] = stack[-1].id

    new_sections = tuple(
        dataclasses.replace(
            section,
            block_ids=section.block_ids
            + tuple(b.id for b in document.blocks if owners.get(b.id) == section.id),
        )
        for section in ordered_sections
    )
    return dataclasses.replace(document, sections=new_sections)


def _split_text(text: str, config: ChunkingConfig) -> list[str]:
    """Divide en piezas por presupuesto de caracteres con overlap (progreso garantizado)."""
    if len(text) <= config.child_max_chars:
        return [text] if text.strip() else []
    pieces: list[str] = []
    start = 0
    text_len = len(text)
    # overlap nunca puede >= max (garantiza start_new > start)
    overlap = max(0, min(config.child_overlap, config.child_max_chars - 1))
    while start < text_len:
        end = min(start + config.child_max_chars, text_len)
        if end < text_len:
            # corte en límite de palabra cuando sea posible
            boundary = text.rfind(" ", start, end)
            if boundary > start + config.child_max_chars // 2:
                end = boundary
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= text_len:
            break
        # progreso garantizado: el overlap nunca retrocede el start (<= -1)
        start = max(end - overlap, start + 1)
    return pieces


def chunk_structured_document(
    document: StructuredDocument,
    *,
    config: ChunkingConfig | None = None,
) -> list[DocumentChunk]:
    """Produce la lista de DocumentChunk del árbol (parent/child)."""
    config = config or ChunkingConfig()
    document = assign_blocks_to_sections(document)
    chunks: list[DocumentChunk] = []
    next_index = 0

    def make_parent(
        content: str,
        *,
        section_id: UUID | None,
        page_start: int | None,
        page_end: int | None,
        char_range: CharRange | None,
    ) -> DocumentChunk:
        nonlocal next_index
        chunk = DocumentChunk(
            id=uuid4(),
            document_id=document.id,
            organization_id=document.organization_id,
            workspace_id=document.workspace_id,
            source_id=document.source_id,
            corpus_id=document.corpus_id,
            chunk_index=next_index,
            chunk_type=ChunkType.DOCUMENT_STRUCTURE,
            parent_id=None,
            section_id=section_id,
            page_start=page_start,
            page_end=page_end,
            content=content,
            char_range=char_range,
            language=document.language,
            token_count=token_count(content),
            content_hash=content_hash(content),
            provenance=CatalogProvenance.OBSERVED,
            status=KnowledgeObjectStatus.OBSERVED,
            metadata={"level": "parent"},
        )
        next_index += 1
        chunks.append(chunk)
        return chunk

    def make_children(
        parent: DocumentChunk,
        content: str,
        offset: int,
    ) -> list[DocumentChunk]:
        nonlocal next_index
        made: list[DocumentChunk] = []
        for piece in _split_text(content, config):
            children_char_range = None
            if parent.char_range is not None:
                start = offset + content.index(piece) if piece in content else offset
                children_char_range = CharRange(
                    start=start, end=min(start + len(piece), parent.char_range.end)
                )
            child = DocumentChunk(
                id=uuid4(),
                document_id=document.id,
                organization_id=document.organization_id,
                workspace_id=document.workspace_id,
                source_id=document.source_id,
                corpus_id=document.corpus_id,
                chunk_index=next_index,
                chunk_type=ChunkType.PARENT_CHILD,
                parent_id=parent.id,
                section_id=parent.section_id,
                page_start=parent.page_start,
                page_end=parent.page_end,
                content=piece,
                char_range=children_char_range,
                language=document.language,
                token_count=token_count(piece),
                content_hash=content_hash(piece),
                provenance=CatalogProvenance.OBSERVED,
                status=KnowledgeObjectStatus.OBSERVED,
                metadata={"level": "child", **parent.metadata},
            )
            next_index += 1
            made.append(child)
            chunks.append(child)
        return made

    if not document.blocks and not document.sections:
        return chunks

    # Contenido por bloque con offsets acumulados (orden de lectura).
    block_texts: list[str] = []
    block_offsets: dict[UUID, int] = {}
    offset = 0
    for block in document.blocks:
        block_offsets[block.id] = offset
        block_texts.append(block.text)
        offset += len(block.text) + 2  # +separador "\n\n"

    total_text = "\n\n".join(block_texts)

    if not document.sections:
        # documento sin estructura: root implícito → children
        parent = make_parent(
            total_text,
            section_id=None,
            page_start=_first_page(document.blocks),
            page_end=_last_page(document.blocks),
            char_range=CharRange(start=0, end=max(1, len(total_text))),
        )
        make_children(parent, total_text, 0)
        return chunks

    # map block_id → sección asignada (hoja más profunda que lo contenga)
    block_owner: dict[UUID, UUID] = {}
    for section in document.sections:
        for block_id in section.block_ids:
            block_owner[block_id] = section.id

    leaves = [
        s
        for s in document.sections
        if not any(other.parent_id == s.id for other in document.sections)
    ]
    covered_blocks: set[UUID] = set()
    for section in sorted(leaves, key=lambda s: s.order):
        ids = [b for b in section.block_ids if b in block_owner]
        if not ids:
            continue
        covered_blocks.update(ids)
        items = []
        for b in ids:
            block = _find_block(document, b)
            if block is not None:
                items.append(block.text)
        items = [section.heading] + items if section.heading else items
        content = "\n\n".join(items)
        start = block_offsets[ids[0]]
        end = start + sum(len(_document_block_text(document, b)) for b in ids) + 2 * (len(ids) - 1)
        page_start = section.page_start if section.page_start is not None else _first_page_for(document, ids)
        page_end = section.page_end if section.page_end is not None else _last_page_for(document, ids)
        parent = make_parent(
            content,
            section_id=section.id,
            page_start=page_start,
            page_end=page_end,
            char_range=CharRange(start=start, end=max(start + 1, end)),
        )
        make_children(parent, content, start)

    # bloques no cubiertos → root implícito del documento
    leftover = [b for b in document.blocks if b.id not in covered_blocks]
    if leftover:
        content = "\n\n".join(b.text for b in leftover)
        parent = make_parent(
            content,
            section_id=None,
            page_start=_first_page(leftover),
            page_end=_last_page(leftover),
            char_range=None,
        )
        make_children(parent, content, 0)

    return chunks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_block(document: StructuredDocument, block_id: UUID) -> StructuredBlock | None:
    for block in document.blocks:
        if block.id == block_id:
            return block
    return None


def _document_block_text(document: StructuredDocument, block_id: UUID) -> str:
    block = _find_block(document, block_id)
    return block.text if block is not None else ""


def _first_page(blocks: list[StructuredBlock]) -> int | None:
    pages = [b.page for b in blocks if b.page is not None]
    return min(pages) if pages else None


def _last_page(blocks: list[StructuredBlock]) -> int | None:
    pages = [b.page for b in blocks if b.page is not None]
    return max(pages) if pages else None


def _first_page_for(document: StructuredDocument, block_ids: list[UUID]) -> int | None:
    pages = [
        b.page
        for b in document.blocks
        if b.id in block_ids and b.page is not None
    ]
    return min(pages) if pages else None


def _last_page_for(document: StructuredDocument, block_ids: list[UUID]) -> int | None:
    pages = [
        b.page
        for b in document.blocks
        if b.id in block_ids and b.page is not None
    ]
    return max(pages) if pages else None
