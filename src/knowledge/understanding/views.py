# =============================================================================
# Document Understanding — vistas. El AST manda. Markdown es una vista.
# =============================================================================
from __future__ import annotations

import hashlib
import json
import re

from src.core.domain.knowledge_v2 import (
    DocumentTable,
    StructuredBlock,
    StructuredBlockKind,
    StructuredDocument,
)
from src.knowledge.understanding.versions import (
    CHUNKING_VERSION,
    SEMANTIC_UNIT_VERSION,
    SOURCE_PROFILE_VERSION,
    UNDERSTANDING_SCHEMA_VERSION,
)

_MARKDOWN_CAP = 200_000


def quality_report(
    document: StructuredDocument,
    *,
    ocr_pages: list[int],
    warnings: list[str],
    extracted: dict | None = None,
) -> dict:
    """Dimensiones reales. overall no sube solo porque no hubo excepciones."""
    extracted = extracted or {}
    pages = list(document.pages)
    empty_pages: list[int] = []
    if pages:
        scores: list[float] = []
        for page in pages:
            size = len((page.text or "").strip())
            if size >= 40:
                scores.append(1.0)
            elif size == 0:
                scores.append(0.0)
                empty_pages.append(page.page_number)
            else:
                scores.append(0.45)
        text_fidelity = sum(scores) / len(scores)
    else:
        usable = [
            block
            for block in document.blocks
            if (block.text or "").strip() and not block.metadata.get("chrome")
        ]
        covered = sum(min(len(block.text), 80) for block in usable)
        text_fidelity = 0.0 if not usable else min(1.0, covered / (80 * len(usable)))

    indexable = [
        block
        for block in document.blocks
        if not block.metadata.get("chrome") and not block.metadata.get("superseded")
    ]
    if not indexable:
        structure_confidence = 0.0
    else:
        owned = sum(
            1
            for block in indexable
            if block.metadata.get("parent_section_id") or block.kind is StructuredBlockKind.HEADING
        )
        structure_confidence = owned / len(indexable)

    layout_values = [
        float(page.metadata["column_confidence"])
        for page in pages
        if isinstance(page.metadata.get("column_confidence"), (int, float))
    ]
    if layout_values:
        layout_confidence = sum(layout_values) / len(layout_values)
    elif any(block.bbox is not None for block in document.blocks):
        layout_confidence = 0.55
    else:
        layout_confidence = 0.4

    if document.tables:
        confidences = [
            float(table.metadata["merge_confidence"])
            for table in document.tables
            if isinstance(table.metadata.get("merge_confidence"), (int, float))
        ]
        candidates = sum(1 for table in document.tables if table.metadata.get("continuation_candidate"))
        table_confidence = sum(confidences) / len(confidences) if confidences else 0.6
        if candidates:
            table_confidence = min(table_confidence, 0.5)
    else:
        table_confidence = None

    if document.sections:
        headed = sum(1 for section in document.sections if (section.heading or "").strip())
        section_confidence = headed / len(document.sections)
    else:
        section_confidence = 0.2 if indexable else 0.0

    symbol_preservation = _symbol_preservation(document, extracted)
    dimensions = {
        "text_fidelity": text_fidelity,
        "structure_confidence": structure_confidence,
        "layout_confidence": layout_confidence,
        "section_confidence": section_confidence,
    }
    if table_confidence is not None:
        dimensions["table_confidence"] = table_confidence
    if symbol_preservation is not None:
        dimensions["symbol_preservation"] = symbol_preservation
    weights = {
        "text_fidelity": 0.3,
        "structure_confidence": 0.2,
        "layout_confidence": 0.15,
        "section_confidence": 0.15,
        "table_confidence": 0.1,
        "symbol_preservation": 0.1,
    }
    weighted = sum(weights[name] * value for name, value in dimensions.items())
    weight_sum = sum(weights[name] for name in dimensions)
    overall = weighted / weight_sum if weight_sum else 0.0
    if warnings:
        overall = max(0.0, overall - min(0.15, 0.03 * len(warnings)))
    reading = layout_confidence
    return {
        "text_fidelity": round(text_fidelity, 2),
        "text_confidence": round(text_fidelity, 2),
        "structure_confidence": round(structure_confidence, 2),
        "layout_confidence": round(layout_confidence, 2),
        "table_confidence": None if table_confidence is None else round(table_confidence, 2),
        "symbol_preservation": None if symbol_preservation is None else round(symbol_preservation, 2),
        "section_confidence": round(section_confidence, 2),
        "reading_order_confidence": round(reading, 2),
        "overall_score": round(overall, 2),
        "ocr_used": bool(ocr_pages),
        "ocr_pages": list(ocr_pages),
        "empty_pages": empty_pages,
        "warnings": list(warnings),
        "score": round(overall, 2),
        "quality_is_estimate": False,
        "dimensions": {key: round(value, 2) for key, value in dimensions.items()},
    }


def _symbol_preservation(document: StructuredDocument, extracted: dict) -> float | None:
    masks: list[str] = []
    pattern = re.compile(r"(?=.*[&%#?*])[&%#?*A-Za-z0-9._\-]{2,32}")
    for block in document.blocks:
        if block.metadata.get("chrome"):
            continue
        masks.extend(pattern.findall(block.text or ""))
    unique = list(dict.fromkeys(masks))
    if not unique:
        return None
    found = {item.get("value") for item in extracted.get("exact_literals") or []}
    return sum(1 for mask in unique if mask in found) / len(unique)


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
        "block_id": str(block.id),
        "page": block.page,
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
    mask_literals = [
        item for item in extracted.get("exact_literals") or [] if item.get("pattern_type") == "mask"
    ]
    strong_spec = len(field_names) >= 2 or (len(field_names) >= 1 and (document.tables or mask_literals))
    if strong_spec:
        document_type = "technical_specification"
        profile_confidence = 0.74
    elif any(str(block.metadata.get("role")) == "procedure" for block in document.blocks):
        document_type = "procedure"
        profile_confidence = 0.62
    elif len(document.sections) >= 4:
        document_type = "manual"
        profile_confidence = 0.58
    else:
        document_type = "document"
        profile_confidence = 0.4
    body = next(
        (
            block.text.strip()
            for block in document.blocks
            if block.kind is StructuredBlockKind.PARAGRAPH and not block.metadata.get("chrome")
        ),
        "",
    )
    paths = [" / ".join(section.section_path) for section in document.sections if section.section_path][:24]
    captions = [table.caption for table in document.tables if table.caption][:12]
    references = [
        item.get("target_candidate")
        for item in extracted.get("cross_references") or []
        if item.get("target_candidate")
    ][:12]
    scopes = list(dict.fromkeys(headings))[:24]
    return {
        "source_id": str(document.source_id) if document.source_id else None,
        "title": document.title,
        "normalized_filename": (filename or document.title or "").strip(),
        "document_type": document_type,
        "profile_confidence": profile_confidence,
        "profile_version": SOURCE_PROFILE_VERSION,
        "major_sections": headings,
        "section_paths": paths,
        "declared_scopes": scopes,
        "field_vocabulary": field_names,
        "reference_vocabulary": references,
        "table_captions": captions,
        "important_terms": terms,
        "declared_entities": field_names,
        "scope": body[:240],
        "content_summary": " · ".join(headings[:6]),
        "summary_provenance": "EXTRACTED",
        "exact_literals_sample": literals,
        "important_exact_literals": literals[:8],
        "structure_quality": quality.get("overall_score", quality.get("score")),
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


def canonical_digest(ast: dict, document: StructuredDocument) -> str:
    """Hash estructural. No usa solo Markdown ni ids aleatorios."""

    def stable(node):
        if isinstance(node, dict):
            return {
                key: stable(value)
                for key, value in node.items()
                if key not in {"id", "block_id"}
            }
        if isinstance(node, list):
            return [stable(item) for item in node]
        return node

    blocks = [
        {
            "order": block.order,
            "kind": block.kind.value,
            "role": block.metadata.get("role"),
            "page": block.page,
            "text": block.text,
        }
        for block in document.blocks
        if not block.metadata.get("chrome") and not block.metadata.get("superseded")
    ]
    material = json.dumps(
        {
            "schema": UNDERSTANDING_SCHEMA_VERSION,
            "ast": stable(ast),
            "blocks": blocks,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def retrieval_digest(units: list) -> str:
    """Hash de unidades ordenadas. Un informe distinto no lo cambia."""
    material = [
        {
            "type": unit.unit_type,
            "heading": (unit.metadata or {}).get("heading"),
            "page_start": unit.page_start,
            "content": unit.content,
            "field_name": unit.field_name,
            "literals": list(unit.exact_literals),
        }
        for unit in units
    ]
    raw = json.dumps(
        {
            "semantic_unit_version": SEMANTIC_UNIT_VERSION,
            "chunking_version": CHUNKING_VERSION,
            "units": material,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parsed_digest(document: StructuredDocument) -> str:
    lines = [
        f"{block.page}|{block.order}|{block.kind.value}|{block.text}"
        for block in document.blocks
    ]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


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
        return None
    return {
        "mode": "active",
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
