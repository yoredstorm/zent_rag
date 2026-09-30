# =============================================================================
# Document Understanding — vistas. El AST manda. Markdown es una vista.
# =============================================================================
from __future__ import annotations

import hashlib
import re

from src.core.domain.knowledge_v2 import (
    DocumentTable,
    StructuredBlock,
    StructuredBlockKind,
    StructuredDocument,
)

_MARKDOWN_CAP = 200_000


def quality_report(
    document: StructuredDocument,
    *,
    ocr_pages: list[int],
    warnings: list[str],
) -> dict:
    """Puntaje estimado. No finge precisión de un juez humano."""
    pages = list(document.pages)
    if not pages:
        text_confidence = 1.0 if document.blocks else 0.0
        empty_pages: list[int] = []
    else:
        scores: list[float] = []
        empty_pages = []
        for page in pages:
            size = len((page.text or "").strip())
            if size >= 40:
                scores.append(1.0)
            elif size == 0:
                scores.append(0.0)
                empty_pages.append(page.page_number)
            else:
                scores.append(0.45)
        text_confidence = sum(scores) / len(scores)
    layout_confidence = 0.85 if any(block.bbox is not None for block in document.blocks) else 0.5
    table_confidence = 0.8 if document.tables else 0.7
    reading_confidence = 0.8
    score = (
        0.5 * text_confidence
        + 0.2 * layout_confidence
        + 0.15 * table_confidence
        + 0.15 * reading_confidence
    )
    score = max(0.0, score - min(0.2, 0.05 * len(warnings)))
    return {
        "text_confidence": round(text_confidence, 2),
        "layout_confidence": round(layout_confidence, 2),
        "table_confidence": round(table_confidence, 2),
        "reading_order_confidence": reading_confidence,
        "ocr_used": bool(ocr_pages),
        "ocr_pages": list(ocr_pages),
        "empty_pages": empty_pages,
        "warnings": list(warnings),
        "score": round(score, 2),
        "quality_is_estimate": True,
    }


def pipeline_state(quality: dict) -> str:
    empty = quality.get("empty_pages") or []
    if empty and quality.get("text_confidence", 1) == 0:
        return "NEEDS_REVIEW"
    if empty or quality.get("warnings"):
        if quality.get("score", 1) < 0.45:
            return "NEEDS_REVIEW"
        if empty:
            return "PARTIAL"
    if quality.get("score", 1) < 0.55:
        return "NEEDS_REVIEW"
    return "READY"


def _owned_blocks(document: StructuredDocument, section_id: object) -> list[StructuredBlock]:
    owned = [
        block
        for block in document.blocks
        if str(block.metadata.get("parent_section_id") or "") == str(section_id)
    ]
    if owned:
        return sorted(owned, key=lambda block: block.order)
    return [
        block
        for block in document.blocks
        if str(block.id) in {str(block_id) for block_id in _section_block_ids(document, section_id)}
    ]


def _section_block_ids(document: StructuredDocument, section_id: object) -> tuple:
    for section in document.sections:
        if str(section.id) == str(section_id):
            return section.block_ids
    return ()


def to_markdown(document: StructuredDocument) -> str:
    """Vista legible. No es el modelo. Los símbolos se copian sin reescribirlos."""
    lines: list[str] = [f"# {document.title}".rstrip(), ""]
    rendered: set[str] = set()
    sections = sorted(document.sections, key=lambda section: section.order)
    if not sections:
        for block in document.blocks:
            _render_block(lines, block, document)
        return _cap("\n".join(lines).strip() + "\n")

    for section in sections:
        depth = min(section.depth + 2, 6)
        heading = section.heading or " ".join(section.section_path)
        lines.append(f"{'#' * depth} {heading}".rstrip())
        lines.append("")
        for block in _owned_blocks(document, section.id):
            if block.metadata.get("chrome") or block.metadata.get("superseded"):
                continue
            if block.kind is StructuredBlockKind.HEADING and block.text.strip() == heading.strip():
                rendered.add(str(block.id))
                continue
            _render_block(lines, block, document)
            rendered.add(str(block.id))
    for block in document.blocks:
        if str(block.id) in rendered or block.metadata.get("chrome") or block.metadata.get("superseded"):
            continue
        if block.kind in {
            StructuredBlockKind.HEADER,
            StructuredBlockKind.FOOTER,
            StructuredBlockKind.PAGE_NUMBER,
        }:
            continue
        _render_block(lines, block, document)
    return _cap("\n".join(lines).strip() + "\n")


def _render_block(lines: list[str], block: StructuredBlock, document: StructuredDocument) -> None:
    role = str(block.metadata.get("role") or block.kind.value)
    if block.kind is StructuredBlockKind.TABLE or role == "table":
        table = _table_for(document, block)
        if table is not None:
            lines.append(_markdown_table(table))
        else:
            lines.append(_fence_if_mask(block.text))
        lines.append("")
        return
    if role in {"note", "footnote"}:
        lines.append("> " + block.text.strip().replace("\n", "\n> "))
        lines.append("")
        return
    if role == "warning":
        lines.append(f"> **Warning** {block.text.strip()}")
        lines.append("")
        return
    if _maskish(block.text):
        lines.append("```")
        lines.append(block.text.strip())
        lines.append("```")
        lines.append("")
        return
    lines.append(block.text.strip())
    lines.append("")


def _markdown_table(table: DocumentTable) -> str:
    headers = table.headers or tuple(f"c{i}" for i in range(table.column_count or 1))
    if not headers:
        headers = ("value",)
    width = len(headers)
    rows = [list(headers)]
    rows.append(["---"] * width)
    for row in table.rows:
        cells = [cell.replace("|", "\\|") for cell in row]
        if len(cells) < width:
            cells.extend([""] * (width - len(cells)))
        rows.append(cells[:width])
    return "\n".join("| " + " | ".join(cells) + " |" for cells in rows)


def _fence_if_mask(text: str) -> str:
    if _maskish(text):
        return f"```\n{text.strip()}\n```"
    return text


def _maskish(text: str) -> bool:
    stripped = text.strip()
    if "\n" in stripped or len(stripped) > 80:
        return False
    return bool(re.search(r"[&%#?*]", stripped))


def _table_for(document: StructuredDocument, block: StructuredBlock) -> DocumentTable | None:
    raw = block.metadata.get("table_id")
    if not raw:
        return None
    for table in document.tables:
        if str(table.id) == str(raw):
            return table
    return None


def _block(document: StructuredDocument, block_id: object) -> StructuredBlock | None:
    for block in document.blocks:
        if str(block.id) == str(block_id):
            return block
    return None


def _cap(markdown: str) -> str:
    if len(markdown) <= _MARKDOWN_CAP:
        return markdown
    return markdown[:_MARKDOWN_CAP] + "\n\n<!-- truncated -->\n"


def _block_node(block: StructuredBlock) -> dict:
    role = str(block.metadata.get("role") or block.kind.value)
    node: dict = {
        "type": role,
        "id": str(block.id),
        "page": block.page,
        "text": block.text,
        "provenance": block.metadata.get("provenance_type") or "EXTRACTED",
    }
    if block.bbox is not None:
        node["bbox"] = {
            "page": block.bbox.page,
            "x0": block.bbox.x0,
            "y0": block.bbox.y0,
            "x1": block.bbox.x1,
            "y1": block.bbox.y1,
        }
    return node


def to_ast(document: StructuredDocument, extracted: dict) -> dict:
    """Árbol canónico. Markdown no sustituye esta estructura."""
    by_parent: dict[str | None, list] = {}
    for section in document.sections:
        parent = str(section.parent_id) if section.parent_id else None
        by_parent.setdefault(parent, []).append(section)

    def section_node(section) -> dict:
        children = []
        for block in _owned_blocks(document, section.id):
            if block.kind is StructuredBlockKind.HEADING:
                continue
            if block.metadata.get("chrome") or block.metadata.get("superseded"):
                continue
            children.append(_block_node(block))
        for child in sorted(by_parent.get(str(section.id), []), key=lambda item: item.order):
            children.append(section_node(child))
        return {
            "type": "section",
            "id": str(section.id),
            "title": section.heading,
            "page_start": section.page_start,
            "page_end": section.page_end,
            "children": children,
        }

    roots = [section_node(section) for section in sorted(by_parent.get(None, []), key=lambda item: item.order)]
    return {
        "type": "document",
        "title": document.title,
        "children": roots,
        "definitions": extracted.get("definitions") or [],
        "technical_fields": extracted.get("technical_fields") or [],
        "exact_literals": [item["value"] for item in extracted.get("exact_literals") or []],
    }


def to_tree(document: StructuredDocument) -> dict:
    """Contorno corto para la vista de diagnóstico."""

    def brief(text: str) -> str:
        cleaned = re.sub(r"\s+", " ", text or "").strip()
        return cleaned[:80]

    nodes = []
    for section in sorted(document.sections, key=lambda item: item.order):
        if section.parent_id is not None:
            continue
        nodes.append(_tree_section(document, section, brief))
    return {"type": "document", "title": document.title, "children": nodes}


def _tree_section(document: StructuredDocument, section, brief) -> dict:
    children = []
    for block in _owned_blocks(document, section.id):
        if block.metadata.get("chrome"):
            continue
        role = str(block.metadata.get("role") or block.kind.value)
        if role == "heading":
            continue
        children.append({"type": role, "id": str(block.id), "text": brief(block.text), "page": block.page})
    for child in document.sections:
        if child.parent_id == section.id:
            children.append(_tree_section(document, child, brief))
    return {
        "type": "section",
        "id": str(section.id),
        "heading": section.heading,
        "page_start": section.page_start,
        "page_end": section.page_end,
        "children": children,
    }


def source_profile(
    document: StructuredDocument,
    extracted: dict,
    quality: dict,
    *,
    filename: str | None,
) -> dict:
    headings = [section.heading for section in document.sections if section.heading][:12]
    terms = [item["term"] for item in extracted.get("definitions") or []][:20]
    field_names = [item["name"] for item in extracted.get("technical_fields") or []][:20]
    literals = [item["value"] for item in extracted.get("exact_literals") or []][:12]
    if field_names:
        document_type = "technical_specification"
    elif any(str(block.metadata.get("role")) == "procedure" for block in document.blocks):
        document_type = "procedure"
    elif len(document.sections) >= 4:
        document_type = "manual"
    else:
        document_type = document.document_type or "document"
    body = next(
        (
            block.text.strip()
            for block in document.blocks
            if block.kind is StructuredBlockKind.PARAGRAPH and not block.metadata.get("chrome")
        ),
        "",
    )
    return {
        "source_id": str(document.source_id) if document.source_id else None,
        "title": document.title,
        "normalized_filename": (filename or document.title or "").strip(),
        "document_type": document_type,
        "major_sections": headings,
        "important_terms": terms,
        "declared_entities": field_names,
        "scope": body[:240],
        "content_summary": " · ".join(headings[:6]),
        "summary_provenance": "EXTRACTED",
        "exact_literals_sample": literals,
        "structure_quality": quality.get("score"),
    }


def build_report(
    document: StructuredDocument,
    extracted: dict,
    quality: dict,
    *,
    filename: str | None,
    state: str,
    elapsed_s: float,
) -> dict:
    pages = document.page_count
    return {
        "document": document.title,
        "filename": filename or document.title,
        "pages": pages,
        "sections": document.section_count,
        "tables": document.table_count,
        "figures": document.figure_count,
        "definitions": len(extracted.get("definitions") or []),
        "technical_fields": len(extracted.get("technical_fields") or []),
        "exact_literals": len(extracted.get("exact_literals") or []),
        "cross_references": len(extracted.get("cross_references") or []),
        "ocr_pages": quality.get("ocr_pages") or [],
        "warnings": quality.get("warnings") or [],
        "extraction_quality": quality.get("score"),
        "pipeline_state": state,
        "elapsed_s": round(elapsed_s, 4),
        "pages_per_second": round(pages / elapsed_s, 2) if elapsed_s > 0 and pages else None,
        "ingestion_cost_usd": 0.0,
        "stages": [
            "UPLOADED",
            "PARSING",
            "LAYOUT_ANALYSIS",
            "STRUCTURE_BUILDING",
            "ENRICHING",
            "CANONICALIZING",
            state,
        ],
    }


def content_fingerprint(text: str, schema_version: str, chunking_version: str) -> str:
    base = hashlib.sha256(text.encode("utf-8")).hexdigest()
    stamp = f"{base}|{schema_version}|{chunking_version}"
    return hashlib.sha256(stamp.encode("utf-8")).hexdigest()


def public_understanding(metadata: dict | None) -> dict | None:
    """Resumen para listas. Sin markdown ni AST."""
    if not isinstance(metadata, dict):
        return None
    block = metadata.get("understanding")
    if not isinstance(block, dict):
        shadow = metadata.get("understanding_shadow")
        if not isinstance(shadow, dict):
            return None
        return {"mode": "shadow", "report": shadow.get("report"), "pipeline_state": shadow.get("pipeline_state")}
    return {
        "mode": block.get("mode") or "active",
        "schema_version": block.get("schema_version"),
        "parser_version": block.get("parser_version"),
        "pipeline_state": block.get("pipeline_state"),
        "report": block.get("report"),
        "quality": block.get("quality"),
        "profile": block.get("profile"),
        "tree": block.get("tree"),
    }


def understanding_views(metadata: dict | None) -> dict | None:
    if not isinstance(metadata, dict):
        return None
    block = metadata.get("understanding")
    if not isinstance(block, dict):
        return None
    views = block.get("views")
    return views if isinstance(views, dict) else None
