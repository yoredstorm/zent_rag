# =============================================================================
# Document Understanding — unidades de retrieval encima del chunker V2
# =============================================================================
# El chunker ya arma padre/hijo. Acá se anotan literales, tipo de bloque y
# bbox. El bbox queda en metadata de índice; el empaquetador del LLM no lo pide.
# =============================================================================
from __future__ import annotations

from src.core.domain.knowledge_v2 import DocumentChunk, StructuredDocument
from src.knowledge.understanding.versions import PARSER_VERSION, SCHEMA_VERSION


def annotate_chunks(document: StructuredDocument, chunks: list[DocumentChunk]) -> list[DocumentChunk]:
    understanding = document.metadata.get("understanding") or {}
    if understanding.get("mode") != "active":
        return chunks
    literals = understanding.get("exact_literals") or []
    fields = understanding.get("technical_fields") or []
    sections = {section.id: section for section in document.sections}
    for chunk in chunks:
        chunk.metadata["canonical_version"] = SCHEMA_VERSION
        chunk.metadata["parser_version"] = PARSER_VERSION
        chunk.metadata["filename"] = str(document.metadata.get("filename") or document.title)
        section = sections.get(chunk.section_id) if chunk.section_id else None
        if section is not None:
            if section.metadata.get("prev_section_id"):
                chunk.metadata["prev_section_id"] = section.metadata.get("prev_section_id")
            if section.metadata.get("next_section_id"):
                chunk.metadata["next_section_id"] = section.metadata.get("next_section_id")
        if chunk.metadata.get("block_ids"):
            chunk.metadata.setdefault("retrieval_unit", chunk.metadata.get("block_type") or "text")
            continue
        block = _dominant_block(document, chunk.content)
        if not chunk.metadata.get("exact_literals"):
            found = [item["value"] for item in literals if item.get("value") and item["value"] in chunk.content]
            if found:
                chunk.metadata["exact_literals"] = found
        if chunk.metadata.get("level") == "parent":
            chunk.metadata["retrieval_unit"] = "SECTION"
            chunk.metadata["block_type"] = "SECTION"
        elif block is not None:
            role = str(block.metadata.get("role") or block.kind.value)
            chunk.metadata["block_type"] = role
            chunk.metadata["retrieval_unit"] = _unit_for(role, chunk.content)
            chunk.metadata["primary_block_id"] = str(block.id)
            chunk.metadata["block_ids"] = [str(block.id)]
            if block.metadata.get("table_id"):
                chunk.metadata["table_id"] = str(block.metadata["table_id"])
            if block.bbox is not None:
                chunk.metadata["bbox"] = {
                    "page": block.bbox.page,
                    "x0": block.bbox.x0,
                    "y0": block.bbox.y0,
                    "x1": block.bbox.x1,
                    "y1": block.bbox.y1,
                }
        else:
            chunk.metadata.setdefault("block_type", "text")
            chunk.metadata.setdefault("retrieval_unit", "text")
        if not chunk.metadata.get("field_name"):
            names = [item["name"] for item in fields if item.get("name") and item["name"] in chunk.content]
            if names:
                chunk.metadata["field_name"] = names[0]
    return chunks


def _unit_for(role: str, content: str) -> str:
    if role == "table":
        data_lines = [line for line in content.splitlines() if line.strip()]
        return "table_row" if len(data_lines) <= 4 else "table"
    if role in {"note", "footnote"}:
        return "note"
    if role in {"field_definition", "definition"}:
        return "field"
    if role in {"procedure", "list_item", "list"}:
        return "procedure" if role != "list" else "list"
    return role or "text"


def _dominant_block(document: StructuredDocument, content: str):
    hits = [
        block
        for block in document.blocks
        if block.text and block.text.strip() and block.text.strip() in content
        and not block.metadata.get("chrome")
        and not block.metadata.get("superseded")
    ]
    if not hits:
        return None
    return max(hits, key=lambda block: len(block.text))


def expand_exact(chunks: list[DocumentChunk], needle: str) -> dict | None:
    """Child que contiene el literal y su padre de sección. Sin LLM."""
    if not needle:
        return None
    children = [
        chunk
        for chunk in chunks
        if chunk.parent_id is not None
        and (needle in (chunk.content or "") or needle in (chunk.metadata.get("exact_literals") or []))
    ]
    if not children:
        children = [chunk for chunk in chunks if needle in (chunk.content or "")]
    if not children:
        return None
    child = children[0]
    parent = next((chunk for chunk in chunks if chunk.id == child.parent_id), None)
    return {"child": child, "parent": parent, "needle": needle}


def index_metadata(document: StructuredDocument, chunk: DocumentChunk) -> dict:
    """Campos extra del payload. No incluye el documento entero."""
    understanding = document.metadata.get("understanding") or {}
    if understanding.get("mode") != "active":
        return {}
    keys = (
        "exact_literals",
        "block_type",
        "retrieval_unit",
        "field_name",
        "table_id",
        "bbox",
        "canonical_version",
        "parser_version",
        "prev_section_id",
        "next_section_id",
        "filename",
        "block_ids",
        "primary_block_id",
        "primary_block_type",
        "unit_id",
    )
    extra = {key: chunk.metadata.get(key) for key in keys if chunk.metadata.get(key) not in (None, [], "")}
    extra["canonical_version"] = understanding.get("schema_version")
    extra["parser_version"] = understanding.get("parser_version")
    return extra
