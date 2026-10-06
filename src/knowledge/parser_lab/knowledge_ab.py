# =============================================================================
# Parser Lab — Knowledge A/B (offline, sin persistencia)
# =============================================================================
# Ambos StructuredDocuments pasan por la MISMA cadena Knowledge OS:
#   Document Understanding -> Semantic Reconstruction -> Semantic Units ->
#   Semantic Threads -> Knowledge Compiler -> Semantic Rule Compiler
# Nada se persiste: KnowledgeCompiler.build es puro y los threads usan el
# planificador/extractor deterministas (sin store, sin LLM).
# =============================================================================
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from src.core.domain.knowledge_v2 import StructuredDocument
from src.knowledge.compiler.model import CompilationResult
from src.knowledge.compiler.pipeline import KnowledgeCompiler
from src.knowledge.parser_lab.quality import evaluate_knowledge_quality
from src.knowledge.semantic.contracts import SemanticWindowResult
from src.knowledge.semantic.extract import extract_window_items
from src.knowledge.semantic.planner import SemanticWindowPlanner, indexable_blocks
from src.knowledge.semantic.processor import _window_blocks
from src.knowledge.semantic.threads import advance_threads, cap_open_threads
from src.knowledge.understanding.engine import understand_document


@dataclass
class KnowledgeSideResult:
    """Resultado offline de un lado del A/B."""

    label: str
    counts: dict[str, int] = field(default_factory=dict)
    threads: dict[str, int] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)
    premise_dimensions: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _payload(document: StructuredDocument) -> dict[str, Any]:
    return (document.metadata or {}).get("understanding") or {}


def _count_threads(document: StructuredDocument) -> tuple[dict[str, int], list[str]]:
    warnings: list[str] = []
    try:
        planner = SemanticWindowPlanner()
        plan = planner.plan(document)
        blocks = indexable_blocks(document)
        threads: dict[str, Any] = {}
        for spec in plan.windows:
            window_blocks = _window_blocks(blocks, spec)
            if not window_blocks:
                continue
            items = extract_window_items(
                document=document,
                window_blocks=window_blocks,
                window_index=spec.window_index,
            )
            result = SemanticWindowResult(
                window_index=spec.window_index,
                organization_id=document.organization_id,
                source_id=document.source_id,
                workspace_id=document.workspace_id,
                document_id=document.id,
                items=tuple(items),
                block_ids=tuple(str(block.id) for block in window_blocks),
            )
            threads, _touched, _stats = advance_threads(threads, result)
            threads, _capped = cap_open_threads(threads, max_open=512)
        statuses = Counter(
            str(getattr(thread, "status", "") or "unknown") for thread in threads.values()
        )
        counts = {status: count for status, count in sorted(statuses.items())}
        counts["total"] = len(threads)
        return counts, warnings
    except Exception as exc:  # noqa: BLE001 — el A/B no se cae por threads
        warnings.append(f"semantic threads no evaluables: {str(exc)[:300]}")
        return {"total": 0}, warnings


def _premise_dimensions(compiled: CompilationResult) -> dict[str, Any]:
    from src.knowledge.rule_compiler.evaluate import rule_premises

    by_origin: Counter[str] = Counter()
    grounded = 0
    unresolved = 0
    for rule in compiled.canonical_rules:
        try:
            premises = rule_premises(rule)
        except Exception:  # noqa: BLE001 — una regla rota no invalida el lado
            premises = []
        for premise in premises:
            by_origin[str(getattr(premise, "origin", "unknown"))] += 1
            if getattr(premise, "grounded", False):
                grounded += 1
            else:
                unresolved += 1
    total = grounded + unresolved
    return {
        "total": total,
        "grounded": grounded,
        "unresolved": unresolved,
        "grounded_rate": (round(grounded / total, 4) if total else None),
        "by_origin": dict(sorted(by_origin.items())),
    }


def _counts(
    understood: StructuredDocument,
    compiled: CompilationResult,
    thread_stats: dict[str, int],
) -> dict[str, int]:
    payload = _payload(understood)
    canonical = compiled.canonical_rules
    return {
        "semantic_units_count": int(
            payload.get("semantic_unit_count")
            or len(payload.get("retrieval_units") or [])
        ),
        "compiler_units_count": len(compiled.units),
        "definitions_count": len(payload.get("definitions") or []),
        "technical_fields_count": len(payload.get("technical_fields") or []),
        "exact_literals_count": len(payload.get("exact_literals") or []),
        "facts_count": len(compiled.facts),
        "entities_count": len(compiled.entities),
        "rules_count": len(compiled.rules),
        "relationships_count": len(compiled.relationships),
        "canonical_rules_count": len(canonical),
        "supported_rules_count": sum(
            1 for rule in canonical if getattr(rule, "supported", False)
        ),
        "executable_rules_count": sum(
            1 for rule in canonical if getattr(rule, "executable", False)
        ),
        "conflicting_rules_count": sum(
            1
            for rule in canonical
            if str(getattr(rule, "verification_state", "")).upper() == "CONFLICTING"
        )
        + len(compiled.conflicts),
        "unknown_rules_count": sum(
            1
            for rule in canonical
            if str(getattr(rule, "verification_state", "")).upper() == "UNKNOWN"
        ),
        "unresolved_rules_count": sum(
            1 for rule in canonical if not getattr(rule, "supported", False)
        ),
        "semantic_threads_count": int(thread_stats.get("total", 0)),
        "quality_issues_count": len(compiled.quality_issues),
    }


def run_offline_knowledge(
    document: StructuredDocument,
    *,
    label: str = "a",
    expectations: dict[str, Any] | None = None,
    run_threads: bool = True,
) -> KnowledgeSideResult:
    """Corre la cadena Knowledge OS offline sobre un StructuredDocument."""
    filename = str(
        (document.metadata or {}).get("filename") or document.external_id or "document.pdf"
    )
    understood = understand_document(document, filename=filename)
    compiled = KnowledgeCompiler.build(understood)
    thread_stats, thread_warnings = (
        _count_threads(understood) if run_threads else ({"total": 0}, [])
    )
    counts = _counts(understood, compiled, thread_stats)
    quality = evaluate_knowledge_quality(
        understood=understood,
        compiled=compiled,
        document=document,
        thread_stats=thread_stats,
        expectations=expectations,
    )
    return KnowledgeSideResult(
        label=label,
        counts=counts,
        threads=thread_stats,
        quality=quality,
        premise_dimensions=_premise_dimensions(compiled),
        warnings=thread_warnings,
    )


def _delta(a: int | float | None, b: int | float | None) -> dict[str, Any]:
    if a is None or b is None:
        ratio = None
    elif a == 0:
        ratio = None
    else:
        ratio = round(float(b) / float(a), 4)
    return {
        "a": a,
        "b": b,
        "b_minus_a": (b - a) if (a is not None and b is not None) else None,
        "b_over_a": ratio,
    }


def compare_knowledge_sides(a: KnowledgeSideResult, b: KnowledgeSideResult) -> dict[str, Any]:
    """Delta objetivo por métrica, sin declarar ganador."""
    keys = sorted(set(a.counts) | set(b.counts))
    counts = {key: _delta(a.counts.get(key), b.counts.get(key)) for key in keys}
    quality_keys = sorted(set(a.quality) | set(b.quality))
    quality: dict[str, Any] = {}
    for key in quality_keys:
        value_a = a.quality.get(key)
        value_b = b.quality.get(key)
        if isinstance(value_a, dict) or isinstance(value_b, dict):
            quality[key] = {"a": value_a, "b": value_b}
        else:
            quality[key] = _delta(value_a, value_b)
    premises = {
        key: _delta(a.premise_dimensions.get(key), b.premise_dimensions.get(key))
        for key in ("total", "grounded", "unresolved")
    }
    threads = {
        key: _delta(a.threads.get(key, 0), b.threads.get(key, 0))
        for key in sorted(set(a.threads) | set(b.threads))
    }
    return {
        "schema": "zent.knowledge_ab.1",
        "labels": {"a": a.label, "b": b.label},
        "counts": counts,
        "quality": quality,
        "premises": premises,
        "threads": threads,
        "warnings": (list(a.warnings) + list(b.warnings)),
    }


def run_and_compare(
    document_a: StructuredDocument,
    document_b: StructuredDocument,
    *,
    labels: tuple[str, str] = ("a", "b"),
    expectations: dict[str, Any] | None = None,
    run_threads: bool = True,
) -> dict[str, Any]:
    """Atajo: cadena offline sobre ambos documentos + comparación."""
    side_a = run_offline_knowledge(
        document_a, label=labels[0], expectations=expectations, run_threads=run_threads
    )
    side_b = run_offline_knowledge(
        document_b, label=labels[1], expectations=expectations, run_threads=run_threads
    )
    comparison = compare_knowledge_sides(side_a, side_b)
    comparison["sides"] = {
        side_a.label: {"counts": side_a.counts, "quality": side_a.quality},
        side_b.label: {"counts": side_b.counts, "quality": side_b.quality},
    }
    return comparison


__all__ = [
    "KnowledgeSideResult",
    "compare_knowledge_sides",
    "run_and_compare",
    "run_offline_knowledge",
]
