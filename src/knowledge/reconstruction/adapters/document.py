# =============================================================================
# Semantic Reconstruction Layer — Document Source Adapters
# =============================================================================
# PDF, DOCX, TXT, Markdown y HTML llegan ya convertidos a StructuredDocument
# por los parsers estructurales. Este adapter NO relee el archivo: traduce el
# árbol físico a elementos crudos universales conservando página, bbox,
# sección y orden de lectura. Las subclases por formato solo ajustan el tipo.
#
# PDF: layout, columnas, headers/footers, tablas y caption ya vienen marcados
#      por el parser + Document Understanding.
# Markdown/HTML/DOCX: jerarquía de headings como estructura.
# =============================================================================
from __future__ import annotations

from src.core.domain.knowledge_v2 import (
    StructuredBlock,
    StructuredBlockKind,
    StructuredDocument,
)
from src.knowledge.structure.base import token_count

from ..contracts import (
    ElementKind,
    RawElement,
    RawExtraction,
    RawTable,
    SourceKind,
    SourceProvenance,
    element_uuid,
)
from .base import SourceAdapter

_KIND_MAP: dict[str, str] = {
    StructuredBlockKind.TITLE.value: ElementKind.TITLE.value,
    StructuredBlockKind.HEADING.value: ElementKind.HEADING.value,
    StructuredBlockKind.PARAGRAPH.value: ElementKind.PARAGRAPH.value,
    StructuredBlockKind.TABLE.value: ElementKind.TABLE.value,
    StructuredBlockKind.TABLE_ROW.value: ElementKind.TABLE_ROW.value,
    StructuredBlockKind.LIST.value: ElementKind.LIST.value,
    StructuredBlockKind.LIST_ITEM.value: ElementKind.LIST_ITEM.value,
    StructuredBlockKind.CODE.value: ElementKind.CODE.value,
    StructuredBlockKind.FIGURE.value: ElementKind.FIGURE.value,
    StructuredBlockKind.FORMULA.value: ElementKind.FORMULA.value,
    StructuredBlockKind.METADATA.value: ElementKind.METADATA.value,
    StructuredBlockKind.DEFINITION.value: ElementKind.DEFINITION.value,
    StructuredBlockKind.NOTE.value: ElementKind.NOTE.value,
    StructuredBlockKind.WARNING.value: ElementKind.WARNING.value,
    StructuredBlockKind.EXAMPLE.value: ElementKind.EXAMPLE.value,
    StructuredBlockKind.PROCEDURE.value: ElementKind.PROCEDURE.value,
    StructuredBlockKind.CAPTION.value: ElementKind.CAPTION.value,
    StructuredBlockKind.FOOTNOTE.value: ElementKind.NOTE.value,
    StructuredBlockKind.HEADER.value: ElementKind.HEADER.value,
    StructuredBlockKind.FOOTER.value: ElementKind.FOOTER.value,
    StructuredBlockKind.PAGE_NUMBER.value: ElementKind.PAGE_NUMBER.value,
    StructuredBlockKind.QUOTE.value: ElementKind.QUOTE.value,
    StructuredBlockKind.REFERENCE.value: ElementKind.REFERENCE.value,
    StructuredBlockKind.FIELD_DEFINITION.value: ElementKind.FIELD.value,
}


def block_provenance(
    block: StructuredBlock,
    document: StructuredDocument,
    *,
    source_kind: str,
    adapter: str,
) -> SourceProvenance:
    bbox = None
    if block.bbox is not None:
        bbox = (block.bbox.x0, block.bbox.y0, block.bbox.x1, block.bbox.y1)
    return SourceProvenance(
        source_kind=source_kind,
        adapter=adapter,
        source_id=document.source_id,
        document_id=document.id,
        document_title=document.title,
        block_id=block.id,
        page=block.page or (block.bbox.page if block.bbox else None),
        bbox=bbox,
        section_path=tuple(block.heading_path or ()),
        char_start=block.char_range.start if block.char_range else None,
        char_end=block.char_range.end if block.char_range else None,
        content_hash=block.content_hash,
        excerpt=(block.text or "").strip()[:400],
    )


class DocumentSourceAdapter(SourceAdapter):
    """Traduce un StructuredDocument a elementos crudos universales."""

    kind = SourceKind.TEXT.value
    description = "Documento estructurado (bloques, páginas, tablas, secciones)"

    def extract(
        self,
        document: StructuredDocument,
        *,
        raw_text: str | None = None,
    ) -> RawExtraction:
        extraction = RawExtraction(
            source_kind=self.kind,
            adapter=self.name,
            title=document.title or document.external_id,
        )
        for index, block in enumerate(document.blocks):
            text = (block.text or "").strip()
            if not text:
                continue
            metadata = block.metadata or {}
            kind = _KIND_MAP.get(block.kind.value, ElementKind.PARAGRAPH.value)
            chrome = str(metadata.get("chrome") or "")
            if chrome in {"header", "footer", "page_number"}:
                kind = chrome
            attributes = {
                "block_kind": block.kind.value,
                "role": metadata.get("role"),
                "chrome": metadata.get("chrome"),
                "superseded": bool(metadata.get("superseded")),
                "reflowed": bool(metadata.get("reflowed")),
                "reflow_parts": list(metadata.get("reflow_parts") or ())[:64],
                "table_id": metadata.get("table_id"),
                "ocr": bool(metadata.get("ocr")),
                "token_count": block.token_count or token_count(text),
            }
            extraction.elements.append(
                RawElement(
                    id=element_uuid(document.id, index, text),
                    kind=kind,
                    text=text,
                    order=index,
                    provenance=block_provenance(
                        block, document, source_kind=self.kind, adapter=self.name
                    ),
                    depth=max(0, len(block.heading_path or ()) - 1),
                    heading_path=tuple(block.heading_path or ()),
                    confidence=float(metadata.get("confidence") or 0.85),
                    attributes={key: value for key, value in attributes.items() if value},
                )
            )
        for index, table in enumerate(document.tables):
            extraction.tables.append(
                RawTable(
                    id=f"table-{index}",
                    name=table.caption or f"table-{index}",
                    headers=tuple(table.headers),
                    rows=tuple(tuple(row) for row in table.rows),
                    header_depth=int(table.metadata.get("header_depth") or 1),
                    merged_cells=tuple(table.metadata.get("merged_cells") or ()),
                    formulas=tuple(table.metadata.get("formulas") or ()),
                    title=table.caption,
                    provenance=SourceProvenance(
                        source_kind=self.kind,
                        adapter=self.name,
                        source_id=document.source_id,
                        document_id=document.id,
                        document_title=document.title,
                        page=table.page,
                        bbox=(
                            (table.bbox.x0, table.bbox.y0, table.bbox.x1, table.bbox.y1)
                            if table.bbox
                            else None
                        ),
                        table=table.caption or f"table-{index}",
                        content_hash=table.content_hash,
                        excerpt=(table.caption or "")[:400],
                    ),
                    confidence=0.9,
                    metadata={"page": table.page},
                )
            )
        extraction.stats = {
            "blocks": len(document.blocks),
            "pages": document.page_count,
            "sections": document.section_count,
            "tables": len(document.tables),
            "figures": document.figure_count,
            "elements": len(extraction.elements),
        }
        return extraction


class PdfSourceAdapter(DocumentSourceAdapter):
    kind = SourceKind.PDF.value
    description = "PDF: layout, columnas, headers/footers, tablas y caption"


class DocxSourceAdapter(DocumentSourceAdapter):
    kind = SourceKind.DOCX.value
    description = "DOCX: jerarquía de headings, párrafos, listas y tablas"


class TextSourceAdapter(DocumentSourceAdapter):
    kind = SourceKind.TEXT.value
    description = "Texto plano"


class MarkdownSourceAdapter(DocumentSourceAdapter):
    kind = SourceKind.MARKDOWN.value
    description = "Markdown: jerarquía de headings como estructura"


class HtmlSourceAdapter(DocumentSourceAdapter):
    kind = SourceKind.HTML.value
    description = "HTML: headings, listas, tablas y bloques de código"


__all__ = [
    "DocumentSourceAdapter",
    "DocxSourceAdapter",
    "HtmlSourceAdapter",
    "MarkdownSourceAdapter",
    "PdfSourceAdapter",
    "TextSourceAdapter",
    "block_provenance",
]
