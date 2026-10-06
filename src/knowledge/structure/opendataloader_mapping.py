# =============================================================================
# OpenDataLoader PDF — mapeo JSON nativo -> StructuredDocument de ZENT
# =============================================================================
# Frontera única entre el JSON particular de OpenDataLoader y Knowledge OS.
# Nada downstream debe leer el JSON original: todo se traduce a los contratos
# de src.core.domain.knowledge_v2 preservando provenance, orden de lectura,
# bbox, jerarquía de headings, tablas con celdas y secciones.
#
# Tipos OpenDataLoader observados (v2.x): paragraph, heading, caption, table,
# table row, table cell, list, list item, image, formula, text block,
# header, footer. Los contenedores (text block, table row/cell, list items)
# se aplanan/agregan según el caso; nunca se pierde su identidad original.
# =============================================================================
from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from src.core.domain.catalog import CatalogProvenance
from src.core.domain.knowledge_v2 import (
    BoundingBox,
    DocumentFigure,
    DocumentPage,
    DocumentSection,
    DocumentTable,
    KnowledgeObjectStatus,
    StructuredBlock,
    StructuredBlockKind,
    StructuredDocument,
)
from src.knowledge.structure.base import content_hash, token_count
from src.knowledge.structure.opendataloader_client import OpenDataLoaderConversion
from src.knowledge.structure.pdf_parser import (
    _parse_heading_numbering,
    _stable_document_id,
)

_DOC_PLACEHOLDER = UUID("00000000-0000-0000-0000-0000000000dd")

_KIND_MAP: dict[str, StructuredBlockKind] = {
    "paragraph": StructuredBlockKind.PARAGRAPH,
    "heading": StructuredBlockKind.HEADING,
    "caption": StructuredBlockKind.CAPTION,
    "list": StructuredBlockKind.LIST,
    "list item": StructuredBlockKind.LIST_ITEM,
    "image": StructuredBlockKind.FIGURE,
    "formula": StructuredBlockKind.FORMULA,
    "header": StructuredBlockKind.HEADER,
    "footer": StructuredBlockKind.FOOTER,
}

_READING_ORDER_SKIP = frozenset({"header", "footer"})

#: Texto normalizado para detectar duplicados/repetidos sin puntuación.
_WORD_RE = re.compile(r"[^\w&%#?*.,;:!¡¿?()\-]+", re.UNICODE)


@dataclass(frozen=True, kw_only=True)
class OpenDataLoaderMappingContext:
    """Todo lo que el parser sabe y el mapeo necesita registrar."""

    organization_id: UUID
    external_id: str
    source_id: UUID | None = None
    workspace_id: UUID | None = None
    source_name: str = "document"
    mime_type: str | None = None
    page_heights: tuple[float, ...] = ()
    parser_info: dict[str, Any] = field(default_factory=dict)
    structure_source: str = "inferred_layout"
    conversion: OpenDataLoaderConversion | None = None
    extra_warnings: tuple[str, ...] = ()


def element_text(element: dict[str, Any]) -> str:
    """Texto recursivo de un elemento ODL (content + kids + list items)."""
    parts: list[str] = []
    content = element.get("content")
    if isinstance(content, str) and content.strip():
        parts.append(content.strip())
    for key in ("kids", "list items"):
        for child in element.get(key) or []:
            if isinstance(child, dict):
                text = element_text(child)
                if text:
                    parts.append(text)
    return "\n".join(part for part in parts if part.strip())


def odl_bbox(
    box: Any,
    *,
    page: int | None,
    page_heights: tuple[float, ...],
) -> BoundingBox | None:
    """[left, bottom, right, top] PDF -> BoundingBox top-left (pt).

    OpenDataLoader entrega coordenadas con origen abajo-izquierda; ZENT usa el
    mismo sistema que pdfplumber (origen arriba-izquierda). Si falta la altura
    de página se conserva el rectángulo nativo y se advierte en metadata.
    """
    if not isinstance(box, (list, tuple)) or len(box) != 4 or page is None:
        return None
    try:
        left, bottom, right, top = (float(value) for value in box)
    except (TypeError, ValueError):
        return None
    height = None
    if 1 <= page <= len(page_heights):
        candidate = float(page_heights[page - 1] or 0.0)
        height = candidate if candidate > 0 else None
    if height is None:
        y0, y1 = bottom, top
    else:
        y0, y1 = height - top, height - bottom
    try:
        return BoundingBox(
            page=page,
            x0=min(left, right),
            y0=min(y0, y1),
            x1=max(left, right),
            y1=max(y0, y1),
        )
    except ValueError:
        return None


def _bbox_native(box: Any) -> list[float] | None:
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        return [float(value) for value in box]
    except (TypeError, ValueError):
        return None


def _normalized_text(text: str) -> str:
    return " ".join(_WORD_RE.sub(" ", (text or "").lower()).split())


class _Mapper:
    """Estado de una conversión JSON -> StructuredDocument."""

    def __init__(self, context: OpenDataLoaderMappingContext) -> None:
        self.context = context
        self.blocks: list[StructuredBlock] = []
        self.tables: list[DocumentTable] = []
        self.figures: list[DocumentFigure] = []
        self.sections: list[DocumentSection] = []
        self.warnings: list[str] = list(context.extra_warnings)
        self._order = 0
        self._page_order: dict[int, int] = {}
        self._page_blocks: dict[int, list[StructuredBlock]] = {}
        self._page_texts: dict[int, list[str]] = {}
        self._table_specs: list[dict[str, Any]] = []
        self._captions: dict[int, dict[str, Any]] = {}

    # -- bloques ------------------------------------------------------------

    def _emit_block(
        self,
        kind: StructuredBlockKind,
        text: str,
        *,
        page: int | None,
        bbox: BoundingBox | None,
        element: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> StructuredBlock:
        page_number = page if (page and page >= 1) else 1
        page_index = self._page_order.get(page_number, 0)
        self._page_order[page_number] = page_index + 1
        metadata: dict[str, Any] = {
            "parser_engine": self.context.parser_info.get("engine", "opendataloader"),
            "parser_version": self.context.parser_info.get("version", "unknown"),
            "parser_mode": self.context.parser_info.get("mode", "local"),
            "structure_source": self.context.structure_source,
            "reading_order": self._order,
            "page_order": page_index + 1,
            "element_type": (element or {}).get("type"),
            "element_id": (element or {}).get("id"),
            "bbox_native": _bbox_native((element or {}).get("bounding box")),
        }
        if element is not None:
            if element.get("pdfua_tag"):
                metadata["pdfua_tag"] = element["pdfua_tag"]
            if element.get("hidden text"):
                metadata["hidden_text"] = True
            if element.get("font"):
                metadata["font"] = element["font"]
            if element.get("font size") is not None:
                metadata["font_size"] = element["font size"]
        if meta:
            metadata.update(meta)
        block = StructuredBlock(
            kind=kind,
            text=text,
            order=self._order,
            page=page_number,
            bbox=bbox,
            token_count=token_count(text),
            content_hash=content_hash(text),
            metadata=metadata,
        )
        self._order += 1
        self.blocks.append(block)
        self._page_blocks.setdefault(page_number, []).append(block)
        if text:
            self._page_texts.setdefault(page_number, []).append(text)
        return block

    def _emit_element(self, element: dict[str, Any]) -> None:
        element_type = str(element.get("type") or "").strip().lower()
        page = element.get("page number")
        page = int(page) if isinstance(page, (int, float)) else None
        bbox = odl_bbox(
            element.get("bounding box"),
            page=page,
            page_heights=self.context.page_heights,
        )
        if element_type == "text block":
            for kid in element.get("kids") or []:
                if isinstance(kid, dict):
                    self._emit_element(kid)
            return
        if element_type == "list":
            self._emit_list(element, page=page, bbox=bbox)
            return
        if element_type == "table":
            self._emit_table(element, page=page, bbox=bbox)
            return
        if element_type == "image":
            self._emit_figure(element, page=page, bbox=bbox)
            return
        kind = _KIND_MAP.get(element_type)
        if kind is None:
            self.warnings.append(
                f"elemento OpenDataLoader sin mapeo: type={element_type!r} "
                f"page={page} id={element.get('id')}"
            )
            kind = StructuredBlockKind.PARAGRAPH
        text = element_text(element)
        meta: dict[str, Any] = {}
        if element_type == "heading":
            numbered, _heading_text = _parse_heading_numbering(text)
            meta["heading_depth"] = (
                len(numbered) - 1 if numbered else self._heading_depth(element, text)
            )
            meta["heading_level"] = element.get("heading level")
            if element.get("level"):
                meta["odl_level"] = element["level"]
        if element_type == "formula":
            meta["format"] = (
                "latex" if re.search(r"\\[a-zA-Z]+", text) else "text"
            )
        if element_type in _READING_ORDER_SKIP:
            meta.setdefault("chrome", element_type)
        self._emit_block(kind, text, page=page, bbox=bbox, element=element, meta=meta)

    def _emit_list(
        self, element: dict[str, Any], *, page: int | None, bbox: BoundingBox | None
    ) -> None:
        items = [item for item in (element.get("list items") or []) if isinstance(item, dict)]
        item_meta: list[dict[str, Any]] = []
        texts: list[str] = []
        for item in items:
            text = element_text(item)
            if not text:
                continue
            item_page = item.get("page number")
            item_bbox = odl_bbox(
                item.get("bounding box"),
                page=int(item_page) if isinstance(item_page, (int, float)) else page,
                page_heights=self.context.page_heights,
            )
            item_meta.append(
                {
                    "id": item.get("id"),
                    "text": text,
                    "page": item_page,
                    "bbox": (
                        dataclasses.asdict(item_bbox) if item_bbox is not None else None
                    ),
                }
            )
            texts.append(text)
        self._emit_block(
            StructuredBlockKind.LIST,
            "\n".join(texts),
            page=page,
            bbox=bbox,
            element=element,
            meta={
                "numbering_style": element.get("numbering style"),
                "list_id": element.get("id"),
                "list_items": item_meta,
                "number_of_list_items": element.get("number of list items"),
                "previous_list_id": element.get("previous list id"),
                "next_list_id": element.get("next list id"),
            },
        )

    def _emit_figure(
        self, element: dict[str, Any], *, page: int | None, bbox: BoundingBox | None
    ) -> None:
        figure_id = uuid4()
        alt = str(element.get("alt") or "").strip()
        figure = DocumentFigure(
            id=figure_id,
            document_id=_DOC_PLACEHOLDER,
            organization_id=self.context.organization_id,
            workspace_id=self.context.workspace_id,
            source_id=self.context.source_id,
            caption=alt,
            figure_type="chart" if alt else "image",
            alt_text=alt or None,
            page=page,
            bbox=bbox,
            token_count=token_count(alt),
            content_hash=content_hash(alt) if alt else None,
            metadata={
                "element_id": element.get("id"),
                "source": element.get("source"),
                "format": element.get("format"),
                "alt_source": element.get("alt_source"),
                "pdfua_tag": element.get("pdfua_tag"),
                "structure_source": self.context.structure_source,
                "parser_engine": self.context.parser_info.get("engine"),
                "parser_version": self.context.parser_info.get("version"),
                "parser_mode": self.context.parser_info.get("mode"),
            },
        )
        self.figures.append(figure)
        if alt:
            self._emit_block(
                StructuredBlockKind.FIGURE,
                alt,
                page=page,
                bbox=bbox,
                element=element,
                meta={"figure_id": str(figure_id)},
            )

    # -- tablas ---------------------------------------------------------------

    def _table_grid(
        self, element: dict[str, Any], page: int | None
    ) -> tuple[list[list[str]], list[dict[str, Any]], int, list[dict[str, Any]]]:
        rows = [row for row in (element.get("rows") or []) if isinstance(row, dict)]
        cells: list[dict[str, Any]] = []
        max_row = 0
        max_col = 0
        for fallback_row, row in enumerate(rows, start=1):
            row_number = int(row.get("row number") or fallback_row)
            for cell in row.get("cells") or []:
                if not isinstance(cell, dict):
                    continue
                cell_row = int(cell.get("row number") or row_number)
                cell_col = int(cell.get("column number") or 0)
                max_row = max(max_row, cell_row)
                max_col = max(max_col, cell_col)
                cell_bbox = odl_bbox(
                    cell.get("bounding box"),
                    page=page,
                    page_heights=self.context.page_heights,
                )
                cells.append(
                    {
                        "row": cell_row,
                        "column": cell_col,
                        "row_span": int(cell.get("row span") or 1),
                        "column_span": int(cell.get("column span") or 1),
                        "is_header": bool(cell.get("is_header")),
                        "text": element_text(cell),
                        "element_id": cell.get("id"),
                        "bbox": (
                            {
                                "x0": cell_bbox.x0,
                                "y0": cell_bbox.y0,
                                "x1": cell_bbox.x1,
                                "y1": cell_bbox.y1,
                            }
                            if cell_bbox is not None
                            else None
                        ),
                        "bbox_native": _bbox_native(cell.get("bounding box")),
                        "pdfua_tag": cell.get("pdfua_tag"),
                    }
                )
        grid = [["" for _ in range(max_col)] for _ in range(max_row)]
        for cell in cells:
            row = max(0, cell["row"] - 1)
            col = max(0, cell["column"] - 1)
            if row < max_row and col < max_col:
                grid[row][col] = cell["text"]
        header_cells = [cell for cell in cells if cell["is_header"]]
        header_rows = (
            max(cell["row"] for cell in header_cells) if header_cells else (1 if grid else 0)
        )
        merged = [
            {
                "row": cell["row"],
                "column": cell["column"],
                "row_span": cell["row_span"],
                "column_span": cell["column_span"],
            }
            for cell in cells
            if cell["row_span"] > 1 or cell["column_span"] > 1
        ]
        return grid, cells, header_rows, merged

    def _emit_table(
        self, element: dict[str, Any], *, page: int | None, bbox: BoundingBox | None
    ) -> None:
        grid, cells, header_rows, merged = self._table_grid(element, page)
        if not grid:
            self.warnings.append(
                f"tabla OpenDataLoader sin filas (page={page} id={element.get('id')})"
            )
            return
        table_id = uuid4()
        header_count = max(1, min(header_rows, len(grid)))
        headers = tuple(grid[0]) if grid else ()
        body = tuple(tuple(row) for row in grid[header_count:])
        rendered = "\n".join(" | ".join(row) for row in grid)
        caption_id = element.get("id")
        self._table_specs.append(
            {
                "id": table_id,
                "element": element,
                "headers": headers,
                "body": body,
                "grid": grid,
                "cells": cells,
                "header_depth": header_count,
                "merged_cells": merged,
                "caption_element_id": caption_id,
                "rendered": rendered,
                "page": page,
                "bbox": bbox,
            }
        )
        block = self._emit_block(
            StructuredBlockKind.TABLE,
            rendered,
            page=page,
            bbox=bbox,
            element=element,
            meta={
                "table_id": str(table_id),
                "table_index": len(self._table_specs) - 1,
                "row_count": len(grid),
                "column_count": len(grid[0]) if grid else 0,
                "header_depth": header_count,
                "merged_cells": merged,
                "previous_table_id": element.get("previous table id"),
                "next_table_id": element.get("next table id"),
            },
        )
        self._table_specs[-1]["block_id"] = block.id

    def _collect_captions(self, kids: list[dict[str, Any]]) -> None:
        for element in kids:
            if not isinstance(element, dict):
                continue
            if str(element.get("type") or "").lower() == "caption":
                linked = element.get("linked content id")
                if isinstance(linked, (int, float)):
                    self._captions[int(linked)] = element
            for key in ("kids", "list items"):
                nested = element.get(key)
                if isinstance(nested, list) and nested and str(element.get("type") or "").lower() != "table":
                    self._collect_captions(nested)

    def _finalize_tables(self) -> None:
        for table_index, spec in enumerate(self._table_specs):
            caption = ""
            found = self._captions.get(int(spec["caption_element_id"]))
            if found is not None:
                caption = element_text(found)
            table = DocumentTable(
                id=spec["id"],
                document_id=_DOC_PLACEHOLDER,
                organization_id=self.context.organization_id,
                workspace_id=self.context.workspace_id,
                source_id=self.context.source_id,
                caption=caption,
                headers=spec["headers"],
                rows=spec["body"],
                page=spec["page"],
                bbox=spec["bbox"],
                token_count=token_count(spec["rendered"]),
                content_hash=content_hash(spec["rendered"]),
                metadata={
                    "table_index": table_index,
                    "order": self._order,
                    "strategy": "opendataloader",
                    "row_count": len(spec["grid"]),
                    "column_count": len(spec["grid"][0]) if spec["grid"] else 0,
                    "header_depth": spec["header_depth"],
                    "cells": spec["cells"],
                    "merged_cells": spec["merged_cells"],
                    "previous_table_id": spec["element"].get("previous table id"),
                    "next_table_id": spec["element"].get("next table id"),
                    "element_id": spec["element"].get("id"),
                    "bbox_native": _bbox_native(spec["element"].get("bounding box")),
                    "structure_source": self.context.structure_source,
                    "parser_engine": self.context.parser_info.get("engine"),
                    "parser_version": self.context.parser_info.get("version"),
                    "parser_mode": self.context.parser_info.get("mode"),
                    "block_id": str(spec.get("block_id")),
                },
            )
            self.tables.append(table)

    # -- headings / secciones ---------------------------------------------

    @staticmethod
    def _heading_depth(element: dict[str, Any], text: str) -> int:
        level = str(element.get("level") or "").strip().lower()
        if level in {"doctitle", "title"}:
            return 0
        try:
            heading_level = int(element.get("heading level") or 1)
        except (TypeError, ValueError):
            heading_level = 1
        return max(heading_level - 1, 0)

    def _build_sections(self) -> None:
        stack: list[DocumentSection] = []
        for block in self.blocks:
            if block.kind is not StructuredBlockKind.HEADING:
                continue
            segments, heading_text = _parse_heading_numbering(block.text)
            if segments:
                depth = len(segments) - 1
                section_path = tuple(segments)
            else:
                depth = int(block.metadata.get("heading_depth") or 0)
                section_path = (block.text,)
            while stack and stack[-1].depth >= depth:
                stack.pop()
            parent_id = stack[-1].id if stack else None
            section = DocumentSection(
                id=uuid4(),
                document_id=_DOC_PLACEHOLDER,
                organization_id=self.context.organization_id,
                workspace_id=self.context.workspace_id,
                source_id=self.context.source_id,
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
                metadata={
                    "parser_engine": self.context.parser_info.get("engine"),
                    "parser_version": self.context.parser_info.get("version"),
                    "parser_mode": self.context.parser_info.get("mode"),
                    "structure_source": self.context.structure_source,
                    "element_id": block.metadata.get("element_id"),
                },
            )
            self.sections.append(section)
            stack.append(section)

    @staticmethod
    def _merge_path(stack: list[DocumentSection]) -> tuple[str, ...]:
        path: list[str] = []
        for section in stack:
            segments = list(section.section_path)
            overlap = 0
            for size in range(1, min(len(path), len(segments)) + 1):
                if path[-size:] == segments[:size]:
                    overlap = size
            path.extend(segments[overlap:])
        return tuple(path)

    def _apply_heading_paths(self) -> None:
        section_by_block = {
            section.block_ids[0]: section
            for section in self.sections
            if section.block_ids
        }
        section_positions = {section.id: index for index, section in enumerate(self.sections)}
        stack: list[DocumentSection] = []
        updated: list[StructuredBlock] = []
        for block in self.blocks:
            section = section_by_block.get(block.id)
            if section is not None:
                while stack and stack[-1].depth >= section.depth:
                    stack.pop()
                stack.append(section)
            path = self._merge_path(stack)
            metadata = dict(block.metadata)
            if stack:
                owner = stack[-1]
                metadata["section_id"] = str(owner.id)
                metadata["section_path"] = list(owner.section_path)
                metadata["section_order"] = section_positions.get(owner.id)
            if path != tuple(block.heading_path) or metadata != block.metadata:
                updated.append(
                    dataclasses.replace(block, heading_path=path, metadata=metadata)
                )
            else:
                updated.append(block)
        self.blocks = updated

    # -- document ----------------------------------------------------------

    def _reading_order_warnings(self) -> None:
        orders = [block.order for block in self.blocks]
        if len(set(orders)) != len(orders):
            self.warnings.append("reading order duplicado: hay blocks con el mismo order")
        if orders != sorted(orders):
            self.warnings.append("reading order no monótono: order fuera de secuencia")
        element_ids = [
            block.metadata.get("element_id")
            for block in self.blocks
            if block.metadata.get("element_id") is not None
        ]
        if len(set(element_ids)) != len(element_ids):
            self.warnings.append("element id duplicado en el JSON de OpenDataLoader")
        # Texto repetido: candidato a chrome (headers/footers) o duplicación
        # tabla+párrafo. El Document Understanding lo refina después.
        by_text: dict[str, list[StructuredBlock]] = {}
        for block in self.blocks:
            text = _normalized_text(block.text)
            if len(text) >= 12:
                by_text.setdefault(text, []).append(block)
        repeated = [group for group in by_text.values() if len(group) > 1]
        if repeated:
            pages = {
                block.page
                for group in repeated
                for block in group
            }
            self.warnings.append(
                f"texto repetido: {len(repeated)} grupos de bloques duplicados "
                f"(páginas: {sorted(page for page in pages if page is not None)[:8]})"
            )
        table_texts = {
            _normalized_text(block.text)
            for block in self.blocks
            if block.kind is StructuredBlockKind.TABLE
        }
        paragraph_texts = {
            _normalized_text(block.text)
            for block in self.blocks
            if block.kind is StructuredBlockKind.PARAGRAPH
        }
        overlap = table_texts & paragraph_texts
        if overlap:
            self.warnings.append(
                f"tabla y párrafo comparten {len(overlap)} bloques de texto idéntico"
            )
        # Solapamiento imposible: mismo page, IoU alto, bloques distintos.
        by_page: dict[int, list[StructuredBlock]] = {}
        for block in self.blocks:
            if block.bbox is not None and block.page is not None:
                by_page.setdefault(block.page, []).append(block)
        impossible = 0
        for page_blocks in by_page.values():
            for i, first in enumerate(page_blocks):
                for second in page_blocks[i + 1 :]:
                    if first.bbox is None or second.bbox is None:
                        continue
                    ratio = _iou(first.bbox, second.bbox)
                    if ratio > 0.9:
                        impossible += 1
        if impossible:
            self.warnings.append(
                f"solapamiento imposible: {impossible} pares de bloques con IoU > 0.9"
            )

    def run(self, payload: dict[str, Any]) -> StructuredDocument:
        try:
            page_count = int(payload.get("number of pages") or 0)
        except (TypeError, ValueError):
            page_count = 0
        page_count = max(page_count, len(self.context.page_heights))
        kids = [kid for kid in (payload.get("kids") or []) if isinstance(kid, dict)]
        self._collect_captions(kids)
        for element in kids:
            self._emit_element(element)
        self._finalize_tables()
        self._build_sections()
        self._apply_heading_paths()
        self._reading_order_warnings()

        doc_id = _stable_document_id(
            self.context.organization_id, self.context.source_id, self.context.external_id
        )
        pages: list[DocumentPage] = []
        for page_number in range(1, max(page_count, max(self._page_blocks, default=1)) + 1):
            page_blocks = self._page_blocks.get(page_number, [])
            text = "\n".join(self._page_texts.get(page_number, []))
            pages.append(
                DocumentPage(
                    id=uuid4(),
                    document_id=doc_id,
                    organization_id=self.context.organization_id,
                    workspace_id=self.context.workspace_id,
                    source_id=self.context.source_id,
                    page_number=page_number,
                    text=text,
                    block_ids=tuple(block.id for block in page_blocks),
                    token_count=token_count(text),
                    content_hash=content_hash(text),
                    metadata={
                        "parser_engine": self.context.parser_info.get("engine"),
                        "parser_version": self.context.parser_info.get("version"),
                        "parser_mode": self.context.parser_info.get("mode"),
                        "structure_source": self.context.structure_source,
                        "page_order": page_number,
                    },
                )
            )

        section_positions = {section.id: index for index, section in enumerate(self.sections)}
        updated_blocks: list[StructuredBlock] = []
        for block in self.blocks:
            metadata = dict(block.metadata)
            section_id = metadata.get("section_id")
            if section_id:
                metadata["section_order"] = section_positions.get(UUID(section_id))
            updated_blocks.append(dataclasses.replace(block, metadata=metadata))
        self.blocks = updated_blocks

        pages = [dataclasses.replace(page, document_id=doc_id) for page in pages]
        tables = [dataclasses.replace(table, document_id=doc_id) for table in self.tables]
        sections = [dataclasses.replace(section, document_id=doc_id) for section in self.sections]
        figures = [dataclasses.replace(figure, document_id=doc_id) for figure in self.figures]

        document_text = "\n".join(block.text for block in self.blocks)
        title = str(payload.get("title") or "").strip()
        if not title:
            for block in self.blocks:
                if block.kind is StructuredBlockKind.HEADING and block.text:
                    title = block.text
                    break
        conversion = self.context.conversion
        parser_metadata: dict[str, Any] = dict(self.context.parser_info)
        if conversion is not None:
            parser_metadata["conversion"] = {
                "elapsed_seconds": round(conversion.elapsed_seconds, 4),
                "output_json_bytes": conversion.output_json_bytes,
                "pages_per_second": (
                    round(page_count / conversion.elapsed_seconds, 3)
                    if conversion.elapsed_seconds and page_count
                    else None
                ),
                "java": conversion.java,
            }
        return StructuredDocument(
            id=doc_id,
            organization_id=self.context.organization_id,
            workspace_id=self.context.workspace_id,
            source_id=self.context.source_id,
            external_id=self.context.external_id,
            title=title or self.context.source_name,
            content_hash=content_hash(document_text),
            mime_type=self.context.mime_type or "application/pdf",
            language=None,
            blocks=tuple(self.blocks),
            pages=tuple(pages),
            sections=tuple(sections),
            tables=tuple(tables),
            figures=tuple(figures),
            provenance=CatalogProvenance.OBSERVED,
            status=KnowledgeObjectStatus.OBSERVED,
            metadata={
                "pdf_info": {
                    key: str(value)
                    for key, value in payload.items()
                    if key not in {"kids"} and value is not None
                },
                "page_count": page_count,
                "parser": parser_metadata,
                "structure_source": self.context.structure_source,
                "parser_options": self.context.parser_info.get("options", {}),
                "parser_warnings": list(self.warnings),
            },
        )


def _iou(first: BoundingBox, second: BoundingBox) -> float:
    x0 = max(first.x0, second.x0)
    y0 = max(first.y0, second.y0)
    x1 = min(first.x1, second.x1)
    y1 = min(first.y1, second.y1)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    intersection = (x1 - x0) * (y1 - y0)
    area_first = max((first.x1 - first.x0) * (first.y1 - first.y0), 0.0)
    area_second = max((second.x1 - second.x0) * (second.y1 - second.y0), 0.0)
    union = area_first + area_second - intersection
    return intersection / union if union > 0 else 0.0


def map_opendataloader_document(
    payload: dict[str, Any], *, context: OpenDataLoaderMappingContext
) -> StructuredDocument:
    """JSON raíz de OpenDataLoader -> StructuredDocument nativo de ZENT."""
    if not isinstance(payload, dict):
        raise TypeError(
            f"payload OpenDataLoader inválido: {type(payload).__name__} (esperado dict)"
        )
    return _Mapper(context).run(payload)


__all__ = [
    "OpenDataLoaderMappingContext",
    "element_text",
    "map_opendataloader_document",
    "odl_bbox",
]
