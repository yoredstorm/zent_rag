# =============================================================================
# Knowledge V2 — Text/Markdown parser (blocks + section tree + tables)
# =============================================================================
# Detecta headings (#), listas, tablas markdown (| ... |) y bloques de código
# respetando el orden de lectura. Para TXT plano produce únicamente bloques de
# párrafo sin árbol de secciones.
# =============================================================================
from __future__ import annotations

import re
from uuid import UUID, uuid4, uuid5

from src.core.domain.catalog import CatalogProvenance
from src.core.domain.knowledge_v2 import (
    CharRange,
    DocumentSection,
    DocumentTable,
    KnowledgeObjectStatus,
    StructuredBlock,
    StructuredBlockKind,
    StructuredDocument,
)
from src.knowledge.structure.base import (
    StructuredParser,
    content_hash,
    decode_text,
    token_count,
)

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_FENCE_RE = re.compile(r"^```+")
_TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")

_NS = UUID("b0f2b8e0-4a31-4c6e-9d1c-8f6b2a1c7d40")


def _stable_document_id(organization_id: UUID, source_id: UUID | None, external_id: str) -> UUID:
    """ID determinista por (org, source, external_id) → upsert idempotente."""
    return uuid5(_NS, f"v2:{organization_id}:{source_id}:{external_id}")


class TextParser(StructuredParser):
    """txt / md / markdown → StructuredDocument."""

    kind = "text"

    def parse(
        self,
        data: bytes,
        *,
        organization_id: UUID,
        external_id: str,
        source_id: UUID | None = None,
        workspace_id: UUID | None = None,
        source_name: str = "document",
        mime_type: str | None = None,
    ) -> StructuredDocument:
        text = decode_text(data, source_name)
        lines = text.splitlines()

        blocks: list[StructuredBlock] = []
        tables: list[DocumentTable] = []
        sections: list[DocumentSection] = []
        section_stack: list[tuple[int, DocumentSection]] = []  # (heading_level, section)
        order = 0
        doc_id = _stable_document_id(organization_id, source_id, external_id)

        def next_order() -> int:
            nonlocal order
            value = order
            order += 1
            return value

        def emit_block(
            kind: StructuredBlockKind,
            block_text: str,
            start: int,
            end: int,
            heading_level: int = 0,
        ) -> StructuredBlock:
            block = StructuredBlock(
                kind=kind,
                text=block_text,
                order=next_order(),
                char_range=CharRange(start=start, end=max(start + 1, end)),
                token_count=token_count(block_text),
                content_hash=content_hash(block_text),
            )
            blocks.append(block)
            if kind is StructuredBlockKind.HEADING:
                _attach_heading_section(
                    block, heading_level, organization_id, workspace_id, source_id,
                    doc_id, sections, section_stack,
                )
            return block

        def flush(kind: StructuredBlockKind, collected: list[str], start: int) -> None:
            if not collected:
                return
            emit_block(kind, "\n".join(collected), start, start + len("\n".join(collected)))

        i = 0
        offset = 0
        in_code = False
        code_lines: list[str] = []
        code_start = 0
        # buffers por bloque contiguo
        para: list[str] = []
        para_start = 0
        items: list[str] = []
        list_start = 0

        while i < len(lines):
            line = lines[i]
            line_len = len(line) + 1  # + newline

            if _FENCE_RE.match(line):
                flush(StructuredBlockKind.PARAGRAPH, para, para_start)
                flush(StructuredBlockKind.LIST, items, list_start)
                para, items = [], []
                if not in_code:
                    in_code = True
                    code_lines = []
                    code_start = offset
                else:
                    emit_block(StructuredBlockKind.CODE, "\n".join(code_lines), code_start, offset)
                    code_lines = []
                offset += line_len
                i += 1
                continue

            if in_code:
                code_lines.append(line)
                offset += line_len
                i += 1
                continue

            stripped = line.strip()
            if not stripped:
                flush(StructuredBlockKind.PARAGRAPH, para, para_start)
                flush(StructuredBlockKind.LIST, items, list_start)
                para, items = [], []
                offset += line_len
                i += 1
                continue

            heading_match = _HEADING_RE.match(line)
            if heading_match:
                flush(StructuredBlockKind.PARAGRAPH, para, para_start)
                flush(StructuredBlockKind.LIST, items, list_start)
                para, items = [], []
                level = len(heading_match.group(1))
                emit_block(StructuredBlockKind.HEADING, heading_match.group(2), offset, offset + line_len - 1, level)
                offset += line_len
                i += 1
                continue

            # tabla markdown: fila header + fila separador
            if _TABLE_ROW_RE.match(line) and i + 1 < len(lines) and _TABLE_SEP_RE.match(lines[i + 1]):
                flush(StructuredBlockKind.PARAGRAPH, para, para_start)
                flush(StructuredBlockKind.LIST, items, list_start)
                para, items = [], []
                start = offset
                table_lines = [line]
                consumed = line_len
                i += 1
                table_lines.append(lines[i])
                consumed += len(lines[i]) + 1
                i += 1
                while i < len(lines) and _TABLE_ROW_RE.match(lines[i]):
                    table_lines.append(lines[i])
                    consumed += len(lines[i]) + 1
                    i += 1
                table = _build_table(table_lines, doc_id, organization_id, workspace_id, source_id, next_order())
                tables.append(table)
                caption = " | ".join(table.headers)
                emit_block(StructuredBlockKind.TABLE, caption, start, start + consumed)
                offset += consumed
                continue

            if _LIST_RE.match(line):
                flush(StructuredBlockKind.PARAGRAPH, para, para_start)
                para = []
                if not items:
                    list_start = offset
                items.append(stripped)
                offset += line_len
                i += 1
                continue

            # párrafo
            flush(StructuredBlockKind.LIST, items, list_start)
            items = []
            if not para:
                para_start = offset
            para.append(stripped)
            offset += line_len
            i += 1

        flush(StructuredBlockKind.PARAGRAPH, para, para_start)
        flush(StructuredBlockKind.LIST, items, list_start)
        if in_code and code_lines:
            emit_block(StructuredBlockKind.CODE, "\n".join(code_lines), code_start, offset)

        document_text = "\n".join(b.text for b in blocks)
        return StructuredDocument(
            id=doc_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
            source_id=source_id,
            external_id=external_id,
            title=_title_from_blocks(blocks) or source_name,
            content_hash=content_hash(document_text),
            mime_type=mime_type or _infer_mime(external_id, source_name),
            language=None,
            blocks=tuple(blocks),
            pages=(),
            sections=tuple(sections),
            tables=tuple(tables),
            figures=(),
            provenance=CatalogProvenance.OBSERVED,
            status=KnowledgeObjectStatus.OBSERVED,
        )


def _attach_heading_section(
    block: StructuredBlock,
    heading_level: int,
    organization_id: UUID,
    workspace_id: UUID | None,
    source_id: UUID | None,
    document_id: UUID,
    sections: list[DocumentSection],
    section_stack: list[tuple[int, DocumentSection]],
) -> None:
    while section_stack and section_stack[-1][0] >= heading_level:
        section_stack.pop()
    ancestors = [s[1] for s in section_stack]
    path = tuple(a.heading for a in ancestors) + (block.text,)
    parent_id = ancestors[-1].id if ancestors else None
    section = DocumentSection(
        id=uuid4(),
        document_id=document_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
        source_id=source_id,
        section_path=path,
        heading=block.text,
        depth=heading_level - 1,
        parent_id=parent_id,
        order=block.order,
        block_ids=(block.id,),
        text=block.text,
        token_count=token_count(block.text),
        content_hash=content_hash(block.text),
    )
    sections.append(section)
    section_stack.append((heading_level, section))


def _build_table(
    table_lines: list[str],
    document_id: UUID,
    organization_id: UUID,
    workspace_id: UUID | None,
    source_id: UUID | None,
    order: int,
) -> DocumentTable:
    rows: list[list[str]] = []
    for line in table_lines:
        if _TABLE_SEP_RE.match(line):
            continue  # fila separadora (--- | :--:) no es dato
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.append(cells)
    headers = tuple(rows[0]) if rows else ()
    body = tuple(tuple(r) for r in rows[1:])
    rendered = "\n".join(" | ".join(r) for r in rows)
    return DocumentTable(
        id=uuid4(),
        document_id=document_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
        source_id=source_id,
        caption="",
        headers=headers,
        rows=body,
        token_count=token_count(rendered),
        content_hash=content_hash(rendered),
    )


def _title_from_blocks(blocks: list[StructuredBlock]) -> str | None:
    for block in blocks[:5]:
        if block.kind is StructuredBlockKind.HEADING:
            return block.text
    return None


def _infer_mime(external_id: str, source_name: str) -> str:
    name = external_id.lower()
    if name.endswith((".md", ".markdown")):
        return "text/markdown"
    if name.endswith((".json",)):
        return "application/json"
    return "text/plain"
