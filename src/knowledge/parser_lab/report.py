# =============================================================================
# Parser Lab — Document Knowledge Coverage Report (§15)
# =============================================================================
# Reporte por documento y por parser: estructura + unidades + conocimiento
# canónico + provenance + warnings. Visible desde logs (render_report_text)
# o como JSON en el benchmark.
# =============================================================================
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.core.domain.knowledge_v2 import StructuredDocument
from src.knowledge.parser_lab.knowledge_ab import KnowledgeSideResult


def build_coverage_report(
    *,
    label: str,
    document: StructuredDocument,
    knowledge: KnowledgeSideResult,
    structural: dict[str, Any] | None = None,
    parser_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Un side del A/B con la forma pedida por el brief §15."""
    counts = knowledge.counts
    quality = knowledge.quality
    parser_metadata = parser_info or document.metadata.get("parser") or {}
    bbox = (structural or {}).get("bbox") or {}
    structure_source = document.metadata.get("structure_source")
    warnings = list(knowledge.warnings)
    warnings.extend(document.metadata.get("parser_warnings") or [])
    report: dict[str, Any] = {
        "schema": "zent.parser_coverage_report.1",
        "parser": {
            "label": label,
            "engine": parser_metadata.get("engine"),
            "version": parser_metadata.get("version"),
            "mode": parser_metadata.get("mode"),
            "structure_source": structure_source,
            "use_struct_tree": parser_metadata.get("use_struct_tree"),
        },
        "document": {
            "external_id": document.external_id,
            "title": document.title,
            "pages": document.page_count,
            "blocks": document.block_count,
            "sections": document.section_count,
            "tables": document.table_count,
            "figures": document.figure_count,
            "content_hash": document.content_hash,
        },
        "structural_quality": {
            "kind_counts": (structural or {}).get("kind_counts"),
            "reading_order": (structural or {}).get("reading_order"),
            "bbox_coverage": bbox.get("block_bbox_coverage"),
            "table_bbox_coverage": bbox.get("table_bbox_coverage"),
            "duplicated_text_groups": ((structural or {}).get("text") or {}).get(
                "duplicate_text_groups"
            ),
            "missing_reference_chars": ((structural or {}).get("text") or {}).get(
                "missing_reference_chars"
            ),
        },
        "semantic_units": counts.get("semantic_units_count", 0),
        "definitions": counts.get("definitions_count", 0),
        "facts": counts.get("facts_count", 0),
        "rules": counts.get("rules_count", 0),
        "supported_rules": counts.get("supported_rules_count", 0),
        "executable_rules": counts.get("executable_rules_count", 0),
        "unresolved_rules": counts.get("unresolved_rules_count", 0),
        "conflicting_rules": counts.get("conflicting_rules_count", 0),
        "unknown_rules": counts.get("unknown_rules_count", 0),
        "canonical_rules": counts.get("canonical_rules_count", 0),
        "relationships": counts.get("relationships_count", 0),
        "semantic_threads": dict(knowledge.threads),
        "premise_dimensions": dict(knowledge.premise_dimensions),
        "provenance_coverage": {
            "evidence_locator_coverage": quality.get("evidence_locator_coverage"),
            "property_provenance_completeness": quality.get(
                "property_provenance_completeness"
            ),
            "orphan_rule_rate": quality.get("orphan_rule_rate"),
            "block_bbox_coverage": bbox.get("block_bbox_coverage"),
        },
        "knowledge_quality": {
            key: value
            for key, value in quality.items()
            if key not in {"evidence", "states"}
        },
        "warnings": warnings,
    }
    return report


def render_report_text(report: dict[str, Any]) -> str:
    """Versión de una pantalla para logs/diagnóstico."""
    parser = report.get("parser") or {}
    document = report.get("document") or {}
    lines = [
        f"== {parser.get('label')} ({parser.get('engine')} {parser.get('version')}"
        f", mode={parser.get('mode')}, source={parser.get('structure_source')}) ==",
        f"doc={document.get('external_id')} pages={document.get('pages')} "
        f"blocks={document.get('blocks')} tables={document.get('tables')} "
        f"sections={document.get('sections')}",
        f"units={report.get('semantic_units')} definitions={report.get('definitions')} "
        f"facts={report.get('facts')} relationships={report.get('relationships')}",
        f"rules={report.get('rules')} canonical={report.get('canonical_rules')} "
        f"supported={report.get('supported_rules')} "
        f"executable={report.get('executable_rules')} "
        f"conflicting={report.get('conflicting_rules')} "
        f"unknown={report.get('unknown_rules')}",
        f"threads={report.get('semantic_threads')} "
        f"premises={report.get('premise_dimensions')}",
        f"provenance={report.get('provenance_coverage')}",
    ]
    warnings = report.get("warnings") or []
    if warnings:
        lines.append("warnings:")
        lines.extend(f"  - {warning}" for warning in warnings[:20])
    return "\n".join(lines)


def write_report(path: str | Path, report: dict[str, Any]) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return str(target)


__all__ = ["build_coverage_report", "render_report_text", "write_report"]
