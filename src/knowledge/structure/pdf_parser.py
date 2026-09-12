# =============================================================================
# Knowledge V2 — PDF parser (pdfplumber / pdfminer)
# =============================================================================
# PDF ciudadano de primera clase: página + bloques de texto con bbox, headings
# (font size / bold), tablas y metadatos del documento, respetando el orden de
# lectura (top→bottom, left→right). Las tablas se extraen con find_tables y el
# texto que cae dentro de su bbox no se duplica en bloques de párrafo.
# =============================================================================
from __future__ import annotations

import io
import re
import statistics
from collections.abc import Iterable
from uuid import UUID, uuid4, uuid5

from src.core.domain.catalog import CatalogProvenance
from src.core.domain.knowledge_v2 import (
    BoundingBox,
    DocumentPage,
    DocumentSection,
    DocumentTable,
    KnowledgeObjectStatus,
    StructuredBlock,
    StructuredBlockKind,
    StructuredDocument,
)
from src.knowledge.structure.base import (
    StructuredParser,
    StructuredParserError,
    content_hash,
    token_count,
)

_NS = UUID("8a3c1d50-3e2b-4f9a-9c8d-2b5a7e1f4c60")
_BOLD_RE = re.compile(r"bold|black|semibold|heavy", re.IGNORECASE)
_NUMBERED_HEADING_RE = re.compile(r"^\s*((?:\d+\.)+\d+|\d+)\s*[.)]?\s*(.*)$")
_CID_RE = re.compile(r"\(cid:(\d+)\)")


def _decode_cid_text(text: str) -> str:
    """Traduce glyphs '(cid:NNN)' de pdfminer a su carácter latin-1 cuando
    el mapeo unicode falta (p. ej. 'ó' → (cid:243))."""

    def _replace(match: re.Match[str]) -> str:
        code = int(match.group(1))
        return chr(code) if code < 256 else match.group(0)

    return _CID_RE.sub(_replace, text)


def _stable_document_id(organization_id: UUID, source_id: UUID | None, external_id: str) -> UUID:
    return uuid5(_NS, f"v2:{organization_id}:{source_id}:{external_id}")


class PdfParser(StructuredParser):
    """pdf → StructuredDocument (páginas, bloques con bbox, tablas, headings)."""

    kind = "pdf"
    mime_type = "application/pdf"

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
        try:
            import pdfplumber
        except ImportError as exc:  # pragma: no cover - dep declared in pyproject
            raise StructuredParserError("pdfplumber is not installed") from exc

        try:
            pdf = pdfplumber.open(io.BytesIO(data))
        except Exception as exc:
            raise StructuredParserError(f"PDF could not be opened ({source_name}): {exc}") from exc

        try:
            pages: list[DocumentPage] = []
            tables: list[DocumentTable] = []
            blocks: list[StructuredBlock] = []
            sections: list[DocumentSection] = []
            heading_candidates: list[StructuredBlock] = []
            order = 0
            all_sizes: list[float] = []

            for page_no, page in enumerate(pdf.pages, start=1):
                page_blocks: list[StructuredBlock] = []
                try:
                    words = page.extract_words(
                        use_text_flow=False,
                        extra_attrs=["fontname", "size"],
                    )
                except Exception:
                    words = []
                if not words:
                    text = (page.extract_text() or "").strip()
                    pages.append(
                        DocumentPage(
                            id=uuid4(),
                            document_id=_DOC_PLACEHOLDER_PAGE,
                            organization_id=organization_id,
                            workspace_id=workspace_id,
                            source_id=source_id,
                            page_number=page_no,
                            text=text,
                            token_count=token_count(text),
                            content_hash=content_hash(text),
                        )
                    )
                    continue

                all_sizes.extend(word.get("size") or 0.0 for word in words if word.get("size"))
                lines = _group_words_into_lines(words)
                page_tables = _extract_tables(
                    page, tables, page_no, organization_id, workspace_id, source_id, order
                )
                order += len(page_tables)
                table_bboxes = [t.bbox for t in page.find_tables()]

                for line in lines:
                    if _inside_any_table(line, table_bboxes):
                        continue
                    block = line_to_block(
                        line, order, page_no, StructuredBlockKind.PARAGRAPH
                    )
                    if _is_heading_candidate(line):
                        block = _replace_block_kind(block, StructuredBlockKind.HEADING)
                        heading_candidates.append(block)
                    page_blocks.append(block)
                    blocks.append(block)
                    order += 1

                page_text = "\n".join(ln["text"] for ln in lines)
                pages.append(
                    DocumentPage(
                        id=uuid4(),
                        document_id=_DOC_PLACEHOLDER_PAGE,
                        organization_id=organization_id,
                        workspace_id=workspace_id,
                        source_id=source_id,
                        page_number=page_no,
                        text=page_text,
                        block_ids=tuple(b.id for b in page_blocks),
                        token_count=token_count(page_text),
                        content_hash=content_hash(page_text),
                    )
                )

            body_median = statistics.median(all_sizes) if all_sizes else 12.0
            _reclassify_headings(blocks, heading_candidates, body_median)
            sections = _build_sections(
                blocks, organization_id, workspace_id, source_id
            )

            doc_id = _stable_document_id(organization_id, source_id, external_id)
            pages = [_rebind_page(p, doc_id) for p in pages]
            tables = [_rebind_table(t, doc_id) for t in tables]
            sections = [_rebind_section(s, doc_id) for s in sections]

            metadata = dict(pdf.metadata or {})
            document_text = "\n".join(b.text for b in blocks)
            return StructuredDocument(
                id=doc_id,
                organization_id=organization_id,
                workspace_id=workspace_id,
                source_id=source_id,
                external_id=external_id,
                title=metadata.get("Title") or source_name,
                content_hash=content_hash(document_text),
                mime_type=mime_type or "application/pdf",
                language=None,
                blocks=tuple(blocks),
                pages=tuple(pages),
                sections=tuple(sections),
                tables=tuple(tables),
                figures=(),
                provenance=CatalogProvenance.OBSERVED,
                status=KnowledgeObjectStatus.OBSERVED,
                metadata={
                    "pdf_info": {k: str(v) for k, v in metadata.items()},
                    "page_count": len(pdf.pages),
                },
            )
        finally:
            pdf.close()


# ---------------------------------------------------------------------------
# Construcción de bloques / líneas / tablas
# ---------------------------------------------------------------------------

_DOC_PLACEHOLDER_PAGE = UUID("00000000-0000-0000-0000-0000000000cc")


def line_to_block(
    line: dict, order: int, page_no: int, kind: StructuredBlockKind
) -> StructuredBlock:
    text = line["text"]
    return StructuredBlock(
        kind=kind,
        text=text,
        order=order,
        page=page_no,
        bbox=BoundingBox(
            page=page_no,
            x0=line["x0"],
            y0=line["top"],
            x1=line["x1"],
            y1=line["bottom"],
        ),
        token_count=token_count(text),
        content_hash=content_hash(text),
        metadata={
            "size": round(line.get("max_size") or 0.0, 2),
            "width": round((line.get("x1") or 0.0) - (line.get("x0") or 0.0), 2),
        },
    )


def _replace_block_kind(block: StructuredBlock, kind: StructuredBlockKind) -> StructuredBlock:
    import dataclasses

    return dataclasses.replace(block, kind=kind)


def _group_words_into_lines(words: Iterable[dict], y_tolerance: float = 3.0) -> list[dict]:
    """Agrupa palabras en líneas por coordenada top cuantizada; ordena
    top→bottom, left→right dentro de la línea."""
    ordered = sorted(
        words,
        key=lambda w: (w.get("top", 0.0), w.get("x0", 0.0)),
    )
    lines: list[dict] = []
    current: list[dict] = []
    current_top: float | None = None
    current_bottom: float = 0.0
    for word in ordered:
        top = word.get("top", 0.0)
        if current_top is None or abs(top - current_top) <= y_tolerance:
            if current_top is None:
                current_top = top
            current.append(word)
            current_bottom = max(current_bottom, word.get("bottom", 0.0))
            continue
        lines.append(_collapse_line(current, current_top, current_bottom, y_tolerance))
        current = [word]
        current_top = top
        current_bottom = word.get("bottom", 0.0)
    if current:
        lines.append(_collapse_line(current, current_top, current_bottom, y_tolerance))
    # lectura: primero por página (ya separada), luego top→bottom
    lines.sort(key=lambda ln: (ln["top"], ln["x0"]))
    return lines


def _collapse_line(
    words: list[dict], top: float | None, bottom: float, y_tolerance: float
) -> dict:
    top = top if top is not None else min((w.get("top", 0.0) for w in words), default=0.0)
    text = _decode_cid_text(" ".join(w.get("text", "") for w in words)).strip()
    return {
        "words": words,
        "text": text,
        "x0": min(w.get("x0", 0.0) for w in words),
        "x1": max(w.get("x1", 0.0) for w in words),
        "top": top,
        "bottom": max(bottom, max((w.get("bottom", 0.0) for w in words), default=0.0)),
        "max_size": max((w.get("size") or 0.0 for w in words), default=0.0),
        "bold": any(_BOLD_RE.search(str(w.get("fontname", ""))) for w in words),
    }


def _is_heading_candidate(line: dict) -> bool:
    """Candidato a heading: bold O tamaño destacado, sin puntuación de frase."""
    if not line["text"]:
        return False
    text = line["text"]
    if len(text) > 160 or len(text) < 2:
        return False
    return bool(line["bold"])


def _reclassify_headings(
    blocks: list[StructuredBlock],
    heading_candidates: list[StructuredBlock],
    body_median: float,
) -> None:
    """Refina con el tamaño medio del body: degrada a párrafo los bold ancho
    (párrafos en negrita) y conserva headings cortos/medios con tamaño >= body."""
    candidates = {id(b): b for b in heading_candidates}
    for index, block in enumerate(blocks):
        if id(block) not in candidates:
            continue
        size = float(block.metadata.get("size") or 0.0)
        width = float(block.metadata.get("width") or 0.0)
        keep_heading = size >= body_median + 1.0 or (width <= 480.0 and len(block.text) <= 40)
        if not keep_heading:
            blocks[index] = _replace_block_kind(block, StructuredBlockKind.PARAGRAPH)


def _extract_tables(
    page,
    tables: list[DocumentTable],
    page_no: int,
    organization_id: UUID,
    workspace_id: UUID | None,
    source_id: UUID | None,
    order: int,
) -> list[DocumentTable]:
    """Extrae tablas con find_tables y las anexa (orden estable)."""
    try:
        found = page.find_tables()
    except Exception:
        return []
    extracted: list[DocumentTable] = []
    for i, table in enumerate(found):
        rows = table.extract() or []
        headers = tuple(str(c) if c is not None else "" for c in rows[0]) if rows else ()
        body = tuple(
            tuple(str(c) if c is not None else "" for c in row) for row in rows[1:]
        )
        rendered = "\n".join(" | ".join(r) for r in rows)
        table_doc_id = _DOC_PLACEHOLDER_PAGE
        dt = DocumentTable(
            id=uuid4(),
            document_id=table_doc_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
            source_id=source_id,
            headers=headers,
            rows=body,
            page=page_no,
            bbox=BoundingBox(
                page=page_no, x0=table.bbox[0], y0=table.bbox[1],
                x1=table.bbox[2], y1=table.bbox[3],
            ),
            token_count=token_count(rendered),
            content_hash=content_hash(rendered),
            metadata={"table_index": i, "order": order + i},
        )
        tables.append(dt)
        extracted.append(dt)
    return extracted


def _inside_any_table(line: dict, table_bboxes: list[tuple[float, float, float, float]]) -> bool:
    for bbox in table_bboxes:
        x0, top, x1, bottom = bbox
        if (
            line["x0"] >= x0 - 2
            and line["x1"] <= x1 + 2
            and line["top"] >= top - 2
            and line["bottom"] <= bottom + 2
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# Árbol de secciones desde headings numerados ("5", "5.2", ...)
# ---------------------------------------------------------------------------

def _build_sections(
    blocks: list[StructuredBlock],
    organization_id: UUID,
    workspace_id: UUID | None,
    source_id: UUID | None,
) -> list[DocumentSection]:
    sections: list[DocumentSection] = []
    stack: list[DocumentSection] = []
    document_id = _DOC_PLACEHOLDER_PAGE  # se rebindea en parse()
    for block in blocks:
        if block.kind is not StructuredBlockKind.HEADING:
            continue
        segments, heading_text = _parse_heading_numbering(block.text)
        if segments:
            depth = len(segments) - 1
            section_path = tuple(segments)
        else:
            depth = 0
            section_path = (block.text,)
        while stack and stack[-1].depth >= depth:
            stack.pop()
        parent_id = stack[-1].id if stack else None
        section = DocumentSection(
            id=uuid4(),
            document_id=document_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
            source_id=source_id,
            section_path=section_path,
            heading=heading_text or block.text,
            depth=depth,
            parent_id=parent_id,
            order=block.order,
            page_start=block.page,
            page_end=block.page,
            block_ids=(block.id,),
            text=block.text,
            token_count=token_count(block.text),
            content_hash=content_hash(block.text),
        )
        sections.append(section)
        stack.append(section)
    return sections


def _parse_heading_numbering(text: str) -> tuple[tuple[str, ...] | None, str]:
    match = _NUMBERED_HEADING_RE.match(text)
    if not match:
        return None, text
    numbering = match.group(1)
    if not all(part.isdigit() for part in numbering.split(".")):
        return None, text
    return tuple(numbering.split(".")), match.group(2).strip()


def _rebind_page(page: DocumentPage, document_id: UUID) -> DocumentPage:
    import dataclasses

    return dataclasses.replace(page, document_id=document_id)


def _rebind_table(table: DocumentTable, document_id: UUID) -> DocumentTable:
    import dataclasses

    return dataclasses.replace(table, document_id=document_id)


def _rebind_section(section: DocumentSection, document_id: UUID) -> DocumentSection:
    import dataclasses

    return dataclasses.replace(section, document_id=document_id)
