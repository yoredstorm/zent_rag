# =============================================================================
# P0 — Reporte del benchmark: summary.json + report.md con winner por métrica
# =============================================================================
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.knowledge.parser_lab.p0.scoring import (
    knowledge_completeness_score,
    migration_recommendation,
    weights_documentation,
    zent_pdf_knowledge_score,
)

#: (sección, etiqueta, path, higher_is_better)
METRIC_TABLE: list[tuple[str, str, tuple[str, ...], bool]] = [
    ("STRUCTURAL QUALITY", "Text Preservation Recall", ("structural", "text_preservation_recall"), True),
    ("STRUCTURAL QUALITY", "Reading Order Accuracy", ("structural", "reading_order_accuracy"), True),
    ("STRUCTURAL QUALITY", "Heading Accuracy", ("structural", "heading_accuracy"), True),
    ("STRUCTURAL QUALITY", "Section Hierarchy Accuracy", ("structural", "section_hierarchy_accuracy"), True),
    ("STRUCTURAL QUALITY", "Table Detection Recall", ("structural", "table_detection_recall"), True),
    ("STRUCTURAL QUALITY", "Table Structure Accuracy", ("structural", "table_structure_accuracy"), True),
    ("STRUCTURAL QUALITY", "Symbol Preservation", ("structural", "symbol_preservation"), True),
    ("STRUCTURAL QUALITY", "Special Character Preservation", ("structural", "special_character_preservation"), True),
    ("STRUCTURAL QUALITY", "Cross-page Continuity", ("structural", "cross_page_continuity"), True),
    ("STRUCTURAL QUALITY", "Duplicate Rate", ("structural", "duplicate_rate"), False),
    ("STRUCTURAL QUALITY", "Header/Footer Contamination", ("structural", "header_footer_contamination"), False),
    ("STRUCTURAL QUALITY", "Broken Sentence Rate", ("structural", "broken_sentence_rate"), False),
    ("SEMANTIC QUALITY", "Semantic Unit Recall", ("semantic", "semantic_unit_recall"), True),
    ("SEMANTIC QUALITY", "Semantic Unit Precision", ("semantic", "semantic_unit_precision"), True),
    ("SEMANTIC QUALITY", "Fragmentation Rate", ("semantic", "fragmentation_rate"), False),
    ("SEMANTIC QUALITY", "Incorrect Merge Rate", ("semantic", "incorrect_merge_rate"), False),
    ("SEMANTIC QUALITY", "Cross-page Stitch Accuracy", ("semantic", "cross_page_stitch_accuracy"), True),
    ("SEMANTIC QUALITY", "Definition Detection Recall", ("semantic", "definition_detection_recall"), True),
    ("SEMANTIC QUALITY", "Rule Candidate Recall", ("semantic", "rule_candidate_recall"), True),
    ("SEMANTIC QUALITY", "Exception Detection Recall", ("semantic", "exception_detection_recall"), True),
    ("SEMANTIC QUALITY", "Table Semantic Preservation", ("semantic", "table_semantic_preservation"), True),
    ("KNOWLEDGE QUALITY", "Definition Recall", ("knowledge", "definition_recall"), True),
    ("KNOWLEDGE QUALITY", "Fact Recall", ("knowledge", "fact_recall"), True),
    ("KNOWLEDGE QUALITY", "Rule Recall", ("knowledge", "rule_recall"), True),
    ("KNOWLEDGE QUALITY", "Relationship Recall", ("knowledge", "relationship_recall"), True),
    ("KNOWLEDGE QUALITY", "Exception Recall", ("knowledge", "exception_recall"), True),
    ("KNOWLEDGE QUALITY", "Enumeration Recall", ("knowledge", "enumeration_recall"), True),
    ("KNOWLEDGE QUALITY", "Formula Recall", ("knowledge", "formula_recall"), True),
    ("KNOWLEDGE QUALITY", "Table Mapping Recall", ("knowledge", "table_mapping_recall"), True),
    ("KNOWLEDGE QUALITY", "Knowledge Precision", ("knowledge", "knowledge_precision"), True),
    ("CANONICAL RULE QUALITY", "CanonicalRule Recall", ("canonical", "canonical_rule_recall"), True),
    ("CANONICAL RULE QUALITY", "CanonicalRule Precision", ("canonical", "canonical_rule_precision"), True),
    ("CANONICAL RULE QUALITY", "SUPPORTED Rate", ("canonical", "supported_rate"), True),
    ("CANONICAL RULE QUALITY", "EXECUTABLE Rate", ("canonical", "executable_rate"), True),
    ("CANONICAL RULE QUALITY", "UNKNOWN Rate", ("canonical", "unknown_rate"), False),
    ("CANONICAL RULE QUALITY", "PARTIALLY_SUPPORTED Rate", ("canonical", "partially_supported_rate"), False),
    ("CANONICAL RULE QUALITY", "CONFLICTING Rate", ("canonical", "conflicting_rate"), False),
    ("CANONICAL RULE QUALITY", "False Rule Rate", ("canonical", "false_rule_rate"), False),
    ("CANONICAL RULE QUALITY", "Missing Premise Rate", ("canonical", "missing_premise_rate"), False),
    (
        "CANONICAL RULE QUALITY",
        "Property Provenance Completeness",
        ("canonical", "property_provenance_completeness"),
        True,
    ),
    ("PREMISE COVERAGE", "Premise Coverage Recall", ("premise", "premise_coverage_recall"), True),
    ("RETRIEVAL", "Recall@K", ("runtime", "retrieval", "recall_at_k"), True),
    ("RETRIEVAL", "MRR", ("runtime", "retrieval", "mrr"), True),
    ("RETRIEVAL", "Rule Retrieval Recall", ("runtime", "retrieval", "rule_retrieval_recall"), True),
    ("RETRIEVAL", "Premise Retrieval Recall", ("runtime", "retrieval", "premise_retrieval_recall"), True),
    ("RETRIEVAL", "Irrelevant Evidence Ratio", ("runtime", "retrieval", "irrelevant_evidence_ratio"), False),
    ("RETRIEVAL", "Source-local Success", ("runtime", "retrieval", "source_local_success"), True),
    (
        "RETRIEVAL",
        "Cross-page Evidence Recovery",
        ("runtime", "retrieval", "cross_page_evidence_recovery"),
        True,
    ),
    (
        "ANSWERABILITY",
        "Answerable With Evidence Rate",
        ("runtime", "decision", "answerable_with_evidence_rate"),
        True,
    ),
    (
        "ANSWERABILITY",
        "False Abstention Rate",
        ("runtime", "decision", "false_abstention_rate"),
        False,
    ),
    (
        "ANSWERABILITY",
        "Unsupported Hallucination Rate",
        ("runtime", "decision", "unsupported_hallucination_rate"),
        False,
    ),
    ("DECISION ACCURACY", "Answer Accuracy", ("runtime", "decision", "answer_accuracy"), True),
    (
        "DECISION ACCURACY",
        "Deterministic Decision Rate",
        ("runtime", "decision", "deterministic_decision_rate"),
        True,
    ),
    ("CONSISTENCY", "Consistency Rate", ("runtime", "consistency", "consistency_rate"), True),
    ("PERFORMANCE", "Seconds per Page", ("performance", "seconds_per_page"), False),
]


def _get(metrics: dict[str, Any], path: tuple[str, ...]) -> float | None:
    node: Any = metrics
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return None if node is None else float(node)


def _winner(values: dict[str, float | None], higher_is_better: bool) -> str:
    present = {label: value for label, value in values.items() if value is not None}
    if len(present) < 2:
        return "-"
    best = max(present.values()) if higher_is_better else min(present.values())
    winners = [label for label, value in present.items() if value == best]
    return "tie" if len(winners) > 1 else winners[0]


def build_metric_table(aggregate: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for section, label, path, higher in METRIC_TABLE:
        values = {side: _get(metrics, path) for side, metrics in aggregate.items()}
        rows.append(
            {
                "section": section,
                "metric": label,
                "path": ".".join(path),
                "higher_is_better": higher,
                "values": values,
                "winner": _winner(values, higher),
            }
        )
    return rows


_LABEL_ORDER = ("pdfplumber", "opendataloader", "opendataloader-hybrid")


def _ordered_labels(aggregate: dict[str, Any]) -> dict[str, Any]:
    ordered = {label: aggregate[label] for label in _LABEL_ORDER if label in aggregate}
    ordered.update({key: value for key, value in aggregate.items() if key not in ordered})
    return ordered


def build_summary(
    *,
    records: list[dict[str, Any]],
    aggregate: dict[str, dict[str, Any]],
    corpus_dir: str,
    golden_dir: str,
    config: dict[str, Any],
    pending_docs: list[dict[str, str]],
) -> dict[str, Any]:
    aggregate = _ordered_labels(aggregate)
    labels = list(aggregate.keys())
    a_label = labels[0]
    b_label = labels[1] if len(labels) > 1 else labels[0]
    hybrid_label = next(
        (label for label in labels if "hybrid" in label), None
    )
    recommendation = migration_recommendation(
        aggregate[a_label],
        aggregate[b_label],
        hybrid=aggregate.get(hybrid_label) if hybrid_label else None,
        corpus_complete=not any(record.get("error") for record in records),
    )
    return {
        "schema": "zent.pdf_knowledge_benchmark.1",
        "config": config,
        "corpus_dir": corpus_dir,
        "golden_dir": golden_dir,
        "pending_docs": pending_docs,
        "documents": records,
        "aggregate": aggregate,
        "metric_table": build_metric_table(aggregate),
        "kcs": {label: knowledge_completeness_score(metrics) for label, metrics in aggregate.items()},
        "zent_score": {
            label: zent_pdf_knowledge_score(metrics) for label, metrics in aggregate.items()
        },
        "recommendation": recommendation,
        "weights": weights_documentation(),
    }


def render_markdown(summary: dict[str, Any]) -> str:
    labels = list(summary["aggregate"].keys())
    header = "| Metric | " + " | ".join(labels) + " | winner |"
    separator = "| --- |" + " ---: |" * len(labels) + " --- |"
    lines = [
        "# PDF Parser Knowledge Benchmark (P0)",
        "",
        "> La métrica principal no es parsing: es cuánto conocimiento correcto, "
        "relacionado, recuperable y ejecutable adquiere ZENT del PDF.",
        "",
        "## Tabla de decisión",
        "",
        header,
        separator,
    ]
    current_section = None
    for row in summary["metric_table"]:
        if row["section"] != current_section:
            current_section = row["section"]
            lines.append(f"| **{current_section}** | " + " | ".join([""] * len(labels)) + " | |")
        values = [
            ("n/a" if row["values"].get(label) is None else f"{row['values'][label]:.4f}")
            for label in labels
        ]
        lines.append(
            f"| {row['metric']} | " + " | ".join(values) + f" | {row['winner']} |"
        )
    lines.extend(["", "## Scores", ""])
    for label in labels:
        kcs = summary["kcs"][label]
        zpks = summary["zent_score"][label]
        lines.append(
            f"- **{label}**: KCS={kcs['value']} (clamped {kcs['clamped']}), "
            f"ZentPdfKnowledgeScore={zpks['value']}, "
            f"performance_viable={zpks['performance_viable']}"
        )
    recommendation = summary["recommendation"]
    lines.extend(
        [
            "",
            "## Recomendación",
            "",
            f"**Verdict: `{recommendation['verdict']}`**",
            "",
            "| Criterio | Cumple |",
            "| --- | --- |",
        ]
    )
    for name, ok in recommendation["criteria"].items():
        lines.append(f"| {name} | {'sí' if ok else 'no'} |")
    lines.extend(["", "## Documentos", ""])
    lines.append("| Documento | letter | pdfplumber s | ODL s | ODL rules | pdfplumber rules | KCS p | KCS odl |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for record in summary["documents"]:
        lines.append(
            f"| {record.get('document')} | {record.get('letter')} | "
            f"{record.get('performance', {}).get('pdfplumber', {}).get('seconds')} | "
            f"{record.get('performance', {}).get('opendataloader', {}).get('seconds')} | "
            f"{record.get('sides', {}).get('opendataloader', {}).get('canonical', {}).get('canonical_rules')} | "
            f"{record.get('sides', {}).get('pdfplumber', {}).get('canonical', {}).get('canonical_rules')} | "
            f"{record.get('kcs', {}).get('pdfplumber')} | "
            f"{record.get('kcs', {}).get('opendataloader')} |"
        )
    pending = summary.get("pending_docs") or []
    if pending:
        lines.extend(["", "## Pendientes", ""])
        for item in pending:
            lines.append(f"- {item.get('name')}: {item.get('reason')}")
    return "\n".join(lines)


def write_outputs(out_dir: str | Path, summary: dict[str, Any]) -> tuple[str, str]:
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    summary_path = root / "summary.json"
    report_path = root / "report.md"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    report_path.write_text(render_markdown(summary), encoding="utf-8")
    return str(summary_path), str(report_path)


__all__ = ["METRIC_TABLE", "build_metric_table", "build_summary", "render_markdown", "write_outputs"]
