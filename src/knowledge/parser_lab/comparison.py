# =============================================================================
# Parser Lab — comparador estructural (DocumentParserComparison)
# =============================================================================
# Compara dos StructuredDocuments del MISMO PDF sin declarar ganador:
# entrega conteos objetivos por lado y deltas. La métrica definitiva es la
# de conocimiento (knowledge_ab.py); esta capa explica el "por qué".
#
# Nota: "lost text" solo puede medirse contra un texto de referencia; el
# benchmark usa el texto crudo de pdfplumber como referencia común.
# =============================================================================
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from src.core.domain.knowledge_v2 import StructuredBlockKind, StructuredDocument
from src.knowledge.structure.pdf_parser import _is_layout_row

#: Símbolos que la extracción debe preservar (contrato de fidelidad).
SYMBOL_PROBES = (
    "&", "%", "#", "-", "–", "—", "→", "≤", "≥", "*", "|", ":", "€", "$",
    "§", "¿", "?", "¡", "(", ")", "/", "+", "=", "@",
)

_TERMINAL = (".", "!", "?", ";", ":", "…", "»", '"')
_WORD_RE = re.compile(r"\w+", re.UNICODE)
_LOWER_START = re.compile(r"^[a-z]", re.UNICODE)


def _normalized(text: str) -> str:
    return " ".join((text or "").lower().split())


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return round(float(numerator) / float(denominator), 4)


def _tokens(text: str) -> Counter[str]:
    return Counter(match.group(0).lower() for match in _WORD_RE.finditer(text or ""))


def _blocks(document: StructuredDocument):
    return sorted(document.blocks, key=lambda block: block.order)


def _kind_counts(document: StructuredDocument) -> dict[str, int]:
    counts = Counter(block.kind.value for block in document.blocks)
    return dict(sorted(counts.items()))


def _duplicate_metrics(document: StructuredDocument) -> dict[str, Any]:
    by_text: dict[str, list] = {}
    for block in document.blocks:
        text = _normalized(block.text)
        if len(text) >= 12:
            by_text.setdefault(text, []).append(block)
    groups = [group for group in by_text.values() if len(group) > 1]
    duplicate_chars = sum(
        len(text) * (len(group) - 1) for text, group in by_text.items() if len(group) > 1
    )
    chrome_candidates = 0
    for text, group in by_text.items():
        pages = {block.page for block in group if block.page is not None}
        if len(pages) >= 3 and len(text) <= 120:
            chrome_candidates += 1
    return {
        "duplicate_text_groups": len(groups),
        "duplicate_text_chars": duplicate_chars,
        "repeated_chrome_candidates": chrome_candidates,
    }


def _reading_order_metrics(document: StructuredDocument) -> dict[str, Any]:
    blocks = _blocks(document)
    orders = [block.order for block in blocks]
    duplicate_orders = len(orders) - len(set(orders))
    page_sequence = [block.page for block in blocks if block.page is not None]
    page_regressions = sum(
        1
        for previous, current in zip(page_sequence, page_sequence[1:])
        if current < previous
    )
    element_ids = [
        block.metadata.get("element_id")
        for block in blocks
        if block.metadata.get("element_id") is not None
    ]
    return {
        "blocks": len(blocks),
        "duplicate_orders": duplicate_orders,
        "page_regressions": page_regressions,
        "monotonic": page_regressions == 0 and duplicate_orders == 0,
        "duplicate_element_ids": len(element_ids) - len(set(element_ids)),
    }


def _bbox_metrics(document: StructuredDocument) -> dict[str, Any]:
    blocks = list(document.blocks)
    with_bbox = sum(1 for block in blocks if block.bbox is not None)
    tables_with_bbox = sum(1 for table in document.tables if table.bbox is not None)
    return {
        "blocks_with_bbox": with_bbox,
        "blocks_total": len(blocks),
        "block_bbox_coverage": _safe_ratio(with_bbox, len(blocks)),
        "tables_with_bbox": tables_with_bbox,
        "tables_total": len(document.tables),
        "table_bbox_coverage": _safe_ratio(tables_with_bbox, len(document.tables)),
    }


def _text_metrics(document: StructuredDocument, reference_text: str | None) -> dict[str, Any]:
    blocks = _blocks(document)
    text = "\n".join(block.text or "" for block in blocks)
    metrics: dict[str, Any] = {
        "total_chars": len(text),
        "total_tokens": len(_WORD_RE.findall(text)),
        "empty_blocks": sum(1 for block in blocks if not (block.text or "").strip()),
        "replacement_chars": text.count("\ufffd"),
        "cid_artifacts": len(re.findall(r"\(cid:\d+\)", text)),
        "broken_tokens": len(re.findall(r"\w\|\w", text)),
        "fixed_width_rows": sum(
            1 for line in text.splitlines() if _is_layout_row(line)
        ),
        "symbols": {
            symbol: text.count(symbol)
            for symbol in SYMBOL_PROBES
            if text.count(symbol)
        },
    }
    metrics.update(_duplicate_metrics(document))
    metrics["broken_sentences"] = _broken_sentence_count(blocks)
    metrics["cross_page_pairs"] = _cross_page_pairs(blocks)
    if reference_text is not None:
        reference = _tokens(reference_text)
        tokens = _tokens(text)
        missing = reference - tokens
        missing_chars = sum(len(token) * count for token, count in missing.items())
        metrics.update(
            {
                "reference_tokens": sum(reference.values()),
                "missing_reference_tokens": sum(missing.values()),
                "missing_reference_chars": missing_chars,
                "text_recall_tokens": _safe_ratio(
                    sum(tokens.values()) - sum(missing.values()),
                    sum(reference.values()),
                ),
            }
        )
    return metrics


def _broken_sentence_count(blocks: list) -> int:
    broken = 0
    ordered = [block for block in blocks if block.page is not None]
    for previous, current in zip(ordered, ordered[1:]):
        prev_text = (previous.text or "").rstrip()
        next_text = (current.text or "").lstrip()
        if not prev_text or not next_text:
            continue
        if previous.page != current.page and prev_text[-1:] not in _TERMINAL and _LOWER_START.match(next_text):
            broken += 1
    return broken


def _cross_page_pairs(blocks: list) -> int:
    pairs = 0
    for previous, current in zip(blocks, blocks[1:]):
        if (
            previous.page is not None
            and current.page is not None
            and current.page == previous.page + 1
            and (previous.text or "").rstrip()[-1:] not in _TERMINAL
        ):
            pairs += 1
    return pairs


def _table_metrics(document: StructuredDocument) -> dict[str, Any]:
    rows = 0
    cells = 0
    cells_with_bbox = 0
    tables_with_cells = 0
    cross_page_links = 0
    spanned = 0
    for table in document.tables:
        rows += table.row_count
        metadata = table.metadata or {}
        cell_list = metadata.get("cells") or []
        if cell_list:
            tables_with_cells += 1
            cells += len(cell_list)
            cells_with_bbox += sum(1 for cell in cell_list if cell.get("bbox"))
            spanned += sum(
                1
                for cell in cell_list
                if int(cell.get("row_span") or 1) > 1
                or int(cell.get("column_span") or 1) > 1
            )
        if metadata.get("previous_table_id") is not None or metadata.get("next_table_id") is not None:
            cross_page_links += 1
        if not cell_list:
            cells += sum(1 for row in table.rows for _ in row)
    return {
        "tables": len(document.tables),
        "table_rows": rows,
        "table_cells": cells,
        "tables_with_cell_structure": tables_with_cells,
        "cells_with_bbox": cells_with_bbox,
        "spanned_cells": spanned,
        "cross_page_table_links": cross_page_links,
        "tables_with_caption": sum(1 for table in document.tables if table.caption),
    }


def _section_metrics(document: StructuredDocument) -> dict[str, Any]:
    depths = Counter(section.depth for section in document.sections)
    orphan_sections = sum(1 for section in document.sections if not section.block_ids)
    grouped = Counter(block.heading_path[-1:] for block in document.blocks if block.heading_path)
    return {
        "sections": len(document.sections),
        "max_depth": max(depths, default=-1),
        "depth_histogram": {str(depth): count for depth, count in sorted(depths.items())},
        "orphan_sections": orphan_sections,
        "blocks_with_heading_path": sum(
            1 for block in document.blocks if block.heading_path
        ),
        "distinct_leaf_headings": len(grouped),
    }


def _figure_metrics(document: StructuredDocument) -> dict[str, Any]:
    return {
        "figures": len(document.figures),
        "figures_with_alt": sum(1 for figure in document.figures if figure.alt_text),
        "formulas": sum(
            1
            for block in document.blocks
            if block.kind is StructuredBlockKind.FORMULA
        ),
    }


def side_metrics(
    document: StructuredDocument,
    *,
    label: str,
    reference_text: str | None = None,
) -> dict[str, Any]:
    """Métricas objetivas de un lado (un parser)."""
    return {
        "label": label,
        "pages": document.page_count,
        "kind_counts": _kind_counts(document),
        "reading_order": _reading_order_metrics(document),
        "bbox": _bbox_metrics(document),
        "text": _text_metrics(document, reference_text),
        "tables": _table_metrics(document),
        "sections": _section_metrics(document),
        "figures": _figure_metrics(document),
        "metadata_parser": document.metadata.get("parser") or {},
        "structure_source": document.metadata.get("structure_source"),
        "parser_warnings": list(document.metadata.get("parser_warnings") or []),
    }


def _summary(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    def ratio(section: str, key: str) -> dict[str, float | None]:
        value_a = a[section].get(key)
        value_b = b[section].get(key)
        return {
            "a": value_a,
            "b": value_b,
            "b_minus_a": (
                (value_b - value_a)
                if (value_a is not None and value_b is not None)
                else None
            ),
            "b_over_a": _safe_ratio(
                float(value_b or 0), float(value_a or 0)
            ),
        }

    return {
        "pages": {
            "a": a["pages"],
            "b": b["pages"],
            "b_over_a": _safe_ratio(b["pages"], a["pages"]),
        },
        "blocks_ratio": ratio("reading_order", "blocks"),
        "tables_ratio": ratio("tables", "tables"),
        "table_cells_ratio": ratio("tables", "table_cells"),
        "headings_ratio": {
            "a": a["kind_counts"].get("heading", 0),
            "b": b["kind_counts"].get("heading", 0),
            "b_over_a": _safe_ratio(
                b["kind_counts"].get("heading", 0), a["kind_counts"].get("heading", 0)
            ),
        },
        "sections_ratio": ratio("sections", "sections"),
        "bbox_coverage": {
            "a": a["bbox"]["block_bbox_coverage"],
            "b": b["bbox"]["block_bbox_coverage"],
        },
        "duplicated_text_blocks": {
            "a": a["text"]["duplicate_text_groups"],
            "b": b["text"]["duplicate_text_groups"],
        },
        "duplicated_text_chars": {
            "a": a["text"]["duplicate_text_chars"],
            "b": b["text"]["duplicate_text_chars"],
        },
        "repeated_chrome_candidates": {
            "a": a["text"]["repeated_chrome_candidates"],
            "b": b["text"]["repeated_chrome_candidates"],
        },
        "reading_order_monotonic": {
            "a": a["reading_order"]["monotonic"],
            "b": b["reading_order"]["monotonic"],
        },
        "page_regressions": {
            "a": a["reading_order"]["page_regressions"],
            "b": b["reading_order"]["page_regressions"],
        },
        "fixed_width_rows": {
            "a": a["text"]["fixed_width_rows"],
            "b": b["text"]["fixed_width_rows"],
        },
        "cross_page_pairs": {
            "a": a["text"]["cross_page_pairs"],
            "b": b["text"]["cross_page_pairs"],
        },
        "cross_page_table_links": {
            "a": a["tables"]["cross_page_table_links"],
            "b": b["tables"]["cross_page_table_links"],
        },
        "missing_reference_chars": {
            "a": a["text"].get("missing_reference_chars"),
            "b": b["text"].get("missing_reference_chars"),
        },
        "text_recall_tokens": {
            "a": a["text"].get("text_recall_tokens"),
            "b": b["text"].get("text_recall_tokens"),
        },
        "symbols_preserved": {
            "a": sum(a["text"]["symbols"].values()),
            "b": sum(b["text"]["symbols"].values()),
        },
    }


def _warnings(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for side in (a, b):
        for warning in side.get("parser_warnings") or []:
            warnings.append(f"[{side['label']}] {warning}")
    return warnings


@dataclass
class DocumentParserComparison:
    """Comparador A/B de dos StructuredDocuments del mismo PDF."""

    labels: tuple[str, str] = ("a", "b")
    include_side_metrics: bool = True

    def compare(
        self,
        document_a: StructuredDocument,
        document_b: StructuredDocument,
        *,
        reference_text: str | None = None,
    ) -> dict[str, Any]:
        a_label, b_label = self.labels
        a = side_metrics(document_a, label=a_label, reference_text=reference_text)
        b = side_metrics(document_b, label=b_label, reference_text=reference_text)
        result: dict[str, Any] = {
            "schema": "zent.parser_comparison.1",
            "labels": {"a": a_label, "b": b_label},
            "summary": _summary(a, b),
            "warnings": _warnings(a, b),
        }
        if self.include_side_metrics:
            result["sides"] = {a_label: a, b_label: b}
        return result


def compare_documents(
    document_a: StructuredDocument,
    document_b: StructuredDocument,
    *,
    labels: tuple[str, str] = ("a", "b"),
    reference_text: str | None = None,
    include_side_metrics: bool = True,
) -> dict[str, Any]:
    """Atajo funcional del comparador estructural."""
    return DocumentParserComparison(
        labels=labels, include_side_metrics=include_side_metrics
    ).compare(document_a, document_b, reference_text=reference_text)


__all__ = [
    "DocumentParserComparison",
    "SYMBOL_PROBES",
    "compare_documents",
    "side_metrics",
]
