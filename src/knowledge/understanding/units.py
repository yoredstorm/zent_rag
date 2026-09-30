# =============================================================================
# Semantic retrieval units — estructura primero, tamaño después
# =============================================================================
# Una definición, nota o campo chico es una unidad. Solo se parte si el texto
# de ESA unidad supera el presupuesto. El padre de sección se conserva.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass, field
from uuid import uuid4, uuid5

from src.core.domain.catalog import CatalogProvenance
from src.core.domain.knowledge_v2 import (
    ChunkType,
    DocumentChunk,
    KnowledgeObjectStatus,
    StructuredBlock,
    StructuredBlockKind,
    StructuredDocument,
)
from src.knowledge.structure.base import content_hash, token_count
from src.knowledge.structure.chunker import chunk_structured_document
from src.knowledge.understanding.versions import DERIVED_NS

_MASK = re.compile(r"^(?=.*[&%#?*])[&%#?*A-Za-z0-9._\-]{2,32}$")

_ROLE_TYPE = {
    "definition": "DEFINITION",
    "field_definition": "FIELD_DEFINITION",
    "note": "NOTE",
    "footnote": "NOTE",
    "warning": "WARNING",
    "example": "EXAMPLE",
    "procedure": "PROCEDURE",
    "list": "LIST",
    "list_item": "LIST",
    "table": "TABLE",
    "reference": "REFERENCE",
    "caption": "REFERENCE",
    "code": "CODE_BLOCK",
    "formula": "CODE_BLOCK",
}


@dataclass
class RetrievalUnit:
    unit_id: str
    unit_type: str
    document_id: str
    section_id: str | None
    parent_section_id: str | None
    block_ids: list[str]
    page_start: int | None
    page_end: int | None
    bbox: dict | None
    content: str
    exact_literals: list[str]
    field_name: str | None
    relations: list[dict]
    provenance: str
    confidence: float
    metadata: dict = field(default_factory=dict)

    def compact(self) -> dict:
        return {
            "unit_id": self.unit_id,
            "unit_type": self.unit_type,
            "document_id": self.document_id,
            "section_id": self.section_id,
            "parent_section_id": self.parent_section_id,
            "block_ids": list(self.block_ids),
            "page_start": self.page_start,
            "page_end": self.page_end,
            "bbox": self.bbox,
            "exact_literals": list(self.exact_literals),
            "field_name": self.field_name,
            "relations": list(self.relations),
            "provenance": self.provenance,
            "confidence": self.confidence,
            "heading": self.metadata.get("heading"),
            "primary_block_id": self.block_ids[0] if self.block_ids else None,
            "primary_block_type": self.unit_type,
        }


def build_retrieval_units(
    document: StructuredDocument,
    *,
    budget: int = 1200,
) -> list[RetrievalUnit]:
    """Unidades nativas. El corte por tamaño solo actúa si una unidad no cabe."""
    understanding = document.metadata.get("understanding") or {}
    literals = understanding.get("exact_literals") or []
    fields = understanding.get("technical_fields") or []
    relations = understanding.get("relations") or []
    by_section: dict[str, list[StructuredBlock]] = {}
    loose: list[StructuredBlock] = []
    for block in document.blocks:
        if _skip(block):
            continue
        section_id = block.metadata.get("parent_section_id")
        if section_id:
            by_section.setdefault(str(section_id), []).append(block)
        elif block.kind is not StructuredBlockKind.HEADING:
            loose.append(block)

    units: list[RetrievalUnit] = []
    sections = list(document.sections) or []
    if not sections and (loose or document.blocks):
        body = [block for block in document.blocks if not _skip(block)]
        children = _units_from_blocks(
            document,
            body,
            section_id=None,
            parent_section_id=None,
            heading=document.title,
            budget=budget,
            literals=literals,
            fields=fields,
            relations=relations,
        )
        if children:
            units.append(
                _section_unit(document, None, None, document.title or "document", children)
            )
            units.extend(children)
        return units

    for section in sorted(sections, key=lambda item: item.order):
        owned = sorted(by_section.get(str(section.id), []), key=lambda block: block.order)
        children = _units_from_blocks(
            document,
            owned,
            section_id=str(section.id),
            parent_section_id=str(section.parent_id) if section.parent_id else None,
            heading=section.heading,
            budget=budget,
            literals=literals,
            fields=fields,
            relations=relations,
        )
        if not children and not (section.heading or "").strip():
            continue
        units.append(
            _section_unit(
                document,
                str(section.id),
                str(section.parent_id) if section.parent_id else None,
                section.heading or section.text or "section",
                children,
                page_start=section.page_start,
                page_end=section.page_end,
            )
        )
        units.extend(children)
    return units


def chunks_for_document(document: StructuredDocument, config=None) -> list[DocumentChunk]:
    """DU activo: unidades semánticas. Si no, el chunker de secciones."""
    understanding = document.metadata.get("understanding") or {}
    if understanding.get("mode") == "active":
        budget = _budget()
        return chunks_from_retrieval_units(document, build_retrieval_units(document, budget=budget))
    return chunk_structured_document(document, config=config)


def chunks_from_retrieval_units(
    document: StructuredDocument,
    units: list[RetrievalUnit],
) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    index = 0
    current_parent: DocumentChunk | None = None
    siblings: list[DocumentChunk] = []

    def close_siblings() -> None:
        for position, child in enumerate(siblings):
            child.metadata["prev_chunk_id"] = str(siblings[position - 1].id) if position else None
            child.metadata["next_chunk_id"] = (
                str(siblings[position + 1].id) if position + 1 < len(siblings) else None
            )

    for unit in units:
        if unit.unit_type == "SECTION":
            close_siblings()
            siblings = []
            if not unit.content.strip():
                current_parent = None
                continue
            current_parent = _chunk(
                document,
                unit,
                index=index,
                parent_id=None,
                chunk_type=ChunkType.DOCUMENT_STRUCTURE,
                level="parent",
            )
            index += 1
            chunks.append(current_parent)
            continue
        if not unit.content.strip():
            continue
        parent_id = current_parent.id if current_parent is not None else None
        child = _chunk(
            document,
            unit,
            index=index,
            parent_id=parent_id,
            chunk_type=ChunkType.PARENT_CHILD,
            level="child",
        )
        index += 1
        chunks.append(child)
        siblings.append(child)
    close_siblings()
    return chunks


def _units_from_blocks(
    document: StructuredDocument,
    blocks: list[StructuredBlock],
    *,
    section_id: str | None,
    parent_section_id: str | None,
    heading: str,
    budget: int,
    literals: list[dict],
    fields: list[dict],
    relations: list[dict],
) -> list[RetrievalUnit]:
    units: list[RetrievalUnit] = []
    buffer: list[StructuredBlock] = []

    def flush() -> None:
        if not buffer:
            return
        units.extend(
            _emit(
                document,
                list(buffer),
                unit_type="PARAGRAPH_GROUP",
                section_id=section_id,
                parent_section_id=parent_section_id,
                heading=heading,
                budget=budget,
                literals=literals,
                fields=fields,
                relations=relations,
            )
        )
        buffer.clear()

    for block in blocks:
        if block.kind is StructuredBlockKind.HEADING:
            continue
        kind = _unit_type(block)
        if kind == "PARAGRAPH_GROUP":
            buffer.append(block)
            continue
        flush()
        units.extend(
            _emit(
                document,
                [block],
                unit_type=kind,
                section_id=section_id,
                parent_section_id=parent_section_id,
                heading=heading,
                budget=budget,
                literals=literals,
                fields=fields,
                relations=relations,
            )
        )
    flush()
    return units


def _emit(
    document: StructuredDocument,
    blocks: list[StructuredBlock],
    *,
    unit_type: str,
    section_id: str | None,
    parent_section_id: str | None,
    heading: str,
    budget: int,
    literals: list[dict],
    fields: list[dict],
    relations: list[dict],
) -> list[RetrievalUnit]:
    content = "\n".join(block.text.strip() for block in blocks if block.text.strip())
    if not content:
        return []
    ids = [str(block.id) for block in blocks]
    pieces = _split_if_needed(content, budget, unit_type)
    made: list[RetrievalUnit] = []
    for part_index, piece in enumerate(pieces):
        owned = [
            item
            for item in literals
            if item.get("value") and str(item.get("block_id")) in ids and item["value"] in piece
        ]
        owned_literals = [item["value"] for item in owned]
        field_name = next((item.get("field_name") for item in owned if item.get("field_name")), None)
        if field_name is None:
            field_name = next(
                (
                    item["name"]
                    for item in fields
                    if item.get("name") and str(item.get("block_id") or "") in ids
                ),
                None,
            )
        if field_name is None and unit_type == "FIELD_DEFINITION":
            field_name = next((item["name"] for item in fields if item.get("name") and item["name"] in piece), None)
        related = [
            item
            for item in relations
            if str(item.get("from_block_id")) in ids or str(item.get("to_block_id")) in ids
        ][:8]
        first = blocks[0]
        bbox = None
        if first.bbox is not None:
            bbox = {
                "page": first.bbox.page,
                "x0": first.bbox.x0,
                "y0": first.bbox.y0,
                "x1": first.bbox.x1,
                "y1": first.bbox.y1,
            }
        pages = [block.page for block in blocks if block.page]
        confidence = min(
            (float(block.metadata.get("confidence") or 0.8) for block in blocks),
            default=0.8,
        )
        emitted_type = unit_type
        if unit_type == "TABLE" and len(pieces) > 1:
            emitted_type = "TABLE_ROW_GROUP"
        unit_id = str(
            uuid5(
                _derived_ns(),
                f"{document.id}|{emitted_type}|{section_id}|{part_index}|{piece[:80]}",
            )
        )
        made.append(
            RetrievalUnit(
                unit_id=unit_id,
                unit_type=emitted_type,
                document_id=str(document.id),
                section_id=section_id,
                parent_section_id=parent_section_id,
                block_ids=ids,
                page_start=min(pages) if pages else None,
                page_end=max(pages) if pages else None,
                bbox=bbox,
                content=piece,
                exact_literals=owned_literals,
                field_name=field_name,
                relations=related,
                provenance=str(first.metadata.get("provenance_type") or "EXTRACTED"),
                confidence=confidence,
                metadata={"heading": heading, "part_index": part_index, "part_count": len(pieces)},
            )
        )
    return made


def _section_unit(
    document: StructuredDocument,
    section_id: str | None,
    parent_section_id: str | None,
    heading: str,
    children: list[RetrievalUnit],
    *,
    page_start: int | None = None,
    page_end: int | None = None,
) -> RetrievalUnit:
    body = "\n\n".join(child.content for child in children if child.content.strip())
    content = heading.strip()
    if body:
        content = f"{content}\n\n{body}" if content else body
    ids: list[str] = []
    literals: list[str] = []
    for child in children:
        for block_id in child.block_ids:
            if block_id not in ids:
                ids.append(block_id)
        for literal in child.exact_literals:
            if literal not in literals:
                literals.append(literal)
    pages = [child.page_start for child in children if child.page_start] + [
        child.page_end for child in children if child.page_end
    ]
    return RetrievalUnit(
        unit_id=str(uuid5(_derived_ns(), f"{document.id}|SECTION|{section_id}|{heading}")),
        unit_type="SECTION",
        document_id=str(document.id),
        section_id=section_id,
        parent_section_id=parent_section_id,
        block_ids=ids,
        page_start=page_start or (min(pages) if pages else None),
        page_end=page_end or (max(pages) if pages else None),
        bbox=children[0].bbox if children else None,
        content=content,
        exact_literals=literals,
        field_name=next((child.field_name for child in children if child.field_name), None),
        relations=[],
        provenance="EXTRACTED",
        confidence=min((child.confidence for child in children), default=0.7),
        metadata={"heading": heading},
    )


def _chunk(
    document: StructuredDocument,
    unit: RetrievalUnit,
    *,
    index: int,
    parent_id,
    chunk_type: ChunkType,
    level: str,
) -> DocumentChunk:
    section_id = None
    if unit.section_id:
        from uuid import UUID

        try:
            section_id = UUID(unit.section_id)
        except ValueError:
            section_id = None
    metadata = {
        "level": level,
        "retrieval_unit": unit.unit_type,
        "block_type": unit.unit_type,
        "unit_id": unit.unit_id,
        "block_ids": list(unit.block_ids),
        "primary_block_id": unit.block_ids[0] if unit.block_ids else None,
        "primary_block_type": unit.unit_type,
        "exact_literals": list(unit.exact_literals),
        "field_name": unit.field_name,
        "bbox": unit.bbox,
        "provenance": unit.provenance,
        "confidence": unit.confidence,
        "heading": unit.metadata.get("heading"),
        "relations": unit.relations,
    }
    return DocumentChunk(
        id=uuid4(),
        document_id=document.id,
        organization_id=document.organization_id,
        workspace_id=document.workspace_id,
        source_id=document.source_id,
        corpus_id=document.corpus_id,
        chunk_index=index,
        chunk_type=chunk_type,
        parent_id=parent_id,
        section_id=section_id,
        page_start=unit.page_start,
        page_end=unit.page_end,
        content=unit.content,
        language=document.language,
        token_count=token_count(unit.content),
        content_hash=content_hash(unit.content),
        provenance=CatalogProvenance.OBSERVED,
        status=KnowledgeObjectStatus.OBSERVED,
        metadata=metadata,
    )


def _unit_type(block: StructuredBlock) -> str:
    text = (block.text or "").strip()
    if text and _MASK.match(text):
        return "PATTERN"
    if block.kind is StructuredBlockKind.CODE:
        return "CODE_BLOCK"
    role = str(block.metadata.get("role") or "")
    if role in _ROLE_TYPE:
        return _ROLE_TYPE[role]
    if block.kind is StructuredBlockKind.TABLE:
        return "TABLE"
    if block.kind is StructuredBlockKind.LIST_ITEM:
        return "LIST"
    return "PARAGRAPH_GROUP"


def _split_if_needed(content: str, budget: int, unit_type: str) -> list[str]:
    if budget <= 0 or len(content) <= budget:
        return [content]
    pieces: list[str] = []
    current: list[str] = []
    size = 0
    for line in content.splitlines() or [content]:
        extra = len(line) + 1
        if current and size + extra > budget:
            pieces.append("\n".join(current))
            current = [line]
            size = extra
        else:
            current.append(line)
            size += extra
    if current:
        pieces.append("\n".join(current))
    if not pieces:
        return [content]
    if unit_type == "TABLE" and len(pieces) > 1:
        header = content.splitlines()[0]
        rebuilt = [pieces[0]]
        for piece in pieces[1:]:
            rebuilt.append(piece if piece.startswith(header) else f"{header}\n{piece}")
        return rebuilt
    return pieces


def _skip(block: StructuredBlock) -> bool:
    if block.metadata.get("chrome") or block.metadata.get("superseded"):
        return True
    if block.metadata.get("index_semantic") is False:
        return True
    return False


def _budget() -> int:
    try:
        from src.core.config import get_settings

        return int(getattr(get_settings(), "SEMANTIC_UNIT_MAX_CHARS", 1200) or 1200)
    except Exception:  # noqa: BLE001
        return 1200


def _derived_ns():
    from uuid import UUID

    return UUID(DERIVED_NS)
