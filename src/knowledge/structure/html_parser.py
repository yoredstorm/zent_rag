# =============================================================================
# Knowledge V2 — HTML parser (BeautifulSoup)
# =============================================================================
# Recorre el body en orden de documento: headings (h1-h6) → árbol de secciones,
# párrafos, listas, código, tablas y figuras (img con alt). Sin páginas ni
# bbox; conserva el atributo lang y el <title>.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4, uuid5

from bs4 import BeautifulSoup

from src.core.domain.catalog import CatalogProvenance
from src.core.domain.knowledge_v2 import (
    DocumentFigure,
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

_NS = UUID("3f5b2c9d-8e1a-4d6b-9c0e-7f2a4b6d8e10")


def _stable_document_id(organization_id: UUID, source_id: UUID | None, external_id: str) -> UUID:
    return uuid5(_NS, f"v2:{organization_id}:{source_id}:{external_id}")


_HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}


class HtmlParser(StructuredParser):
    """html / htm → StructuredDocument (bloques + secciones + tablas + figuras)."""

    kind = "html"
    mime_type = "text/html"

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
            soup = BeautifulSoup(data, "html.parser")
        except Exception as exc:
            raise StructuredParserError(f"HTML could not be parsed ({source_name}): {exc}") from exc

        blocks: list[StructuredBlock] = []
        tables: list[DocumentTable] = []
        figures: list[DocumentFigure] = []
        sections: list[DocumentSection] = []
        section_stack: list[tuple[int, DocumentSection]] = []
        order = 0
        doc_id = _stable_document_id(organization_id, source_id, external_id)

        def next_order() -> int:
            nonlocal order
            value = order
            order += 1
            return value

        def emit_block(kind: StructuredBlockKind, text_value: str, heading_level: int = 0) -> None:
            block = StructuredBlock(
                kind=kind,
                text=text_value,
                order=next_order(),
                token_count=token_count(text_value),
                content_hash=content_hash(text_value),
            )
            blocks.append(block)
            if kind is StructuredBlockKind.HEADING:
                _attach_heading_section(
                    block, heading_level, organization_id, workspace_id, source_id,
                    doc_id, sections, section_stack,
                )

        body = soup.body or soup
        for element in body.find_all(
            ["h1", "h2", "h3", "h4", "h5", "h6", "p", "ul", "ol", "pre", "code", "table", "img", "figcaption"]
        ):
            if element.find_parent(["table"]) is not None and element.name not in ("table",):
                continue  # celdas ya cubiertas por la tabla
            if element.name in _HEADING_TAGS:
                text = element.get_text(" ", strip=True)
                if text:
                    emit_block(StructuredBlockKind.HEADING, text, _HEADING_TAGS[element.name])
            elif element.name == "p":
                text = element.get_text(" ", strip=True)
                if text:
                    emit_block(StructuredBlockKind.PARAGRAPH, text)
            elif element.name in ("ul", "ol"):
                items = [li.get_text(" ", strip=True) for li in element.find_all("li", recursive=False)]
                items = [i for i in items if i]
                if items:
                    emit_block(StructuredBlockKind.LIST, "\n".join(items))
            elif element.name in ("pre", "code"):
                text = element.get_text("\n", strip=False).strip()
                if text:
                    emit_block(StructuredBlockKind.CODE, text)
            elif element.name == "table":
                table = _build_table(element, doc_id, organization_id, workspace_id, source_id, next_order())
                if table.rows or table.headers:
                    tables.append(table)
                    emit_block(StructuredBlockKind.TABLE, " | ".join(table.headers))
            elif element.name == "img":
                alt = element.get("alt") or ""
                src = element.get("src") or ""
                if src or alt:
                    figures.append(
                        DocumentFigure(
                            id=uuid4(),
                            document_id=doc_id,
                            organization_id=organization_id,
                            workspace_id=workspace_id,
                            source_id=source_id,
                            caption=alt,
                            figure_type="image",
                            metadata={"src": src},
                            token_count=token_count(alt or src),
                            content_hash=content_hash(alt or src),
                        )
                    )

        title_tag = soup.find("title")
        html_lang = (soup.html.get("lang") if soup.html else None) or None
        document_text = "\n".join(b.text for b in blocks)
        return StructuredDocument(
            id=doc_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
            source_id=source_id,
            external_id=external_id,
            title=(title_tag.get_text(strip=True) if title_tag else None) or source_name,
            content_hash=content_hash(document_text),
            mime_type=mime_type or "text/html",
            language=html_lang,
            blocks=tuple(blocks),
            pages=(),
            sections=tuple(sections),
            tables=tuple(tables),
            figures=tuple(figures),
            provenance=CatalogProvenance.OBSERVED,
            status=KnowledgeObjectStatus.OBSERVED,
        )


def _build_table(
    element,
    document_id: UUID,
    organization_id: UUID,
    workspace_id: UUID | None,
    source_id: UUID | None,
    order: int,
) -> DocumentTable:
    rows: list[tuple[str, ...]] = []
    for tr in element.find_all("tr"):
        cells = tuple(
            td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])
        )
        if any(cells):
            rows.append(cells)
    headers = tuple(c for c in rows[0]) if rows else ()
    body = tuple(rows[1:])
    rendered = "\n".join(" | ".join(r) for r in rows)
    return DocumentTable(
        id=uuid4(),
        document_id=document_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
        source_id=source_id,
        headers=headers,
        rows=body,
        token_count=token_count(rendered),
        content_hash=content_hash(rendered),
        metadata={"html_order": order},
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
