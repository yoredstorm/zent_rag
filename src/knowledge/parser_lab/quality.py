# =============================================================================
# Parser Lab — calidad del conocimiento (no solo cantidad)
# =============================================================================
# 100 reglas basura no deben ganar contra 70 reglas correctas. Este módulo
# produce tasas de soporte, duplicación, contradicción, orfandad, provenance
# de propiedades, fragmentación semántica y (si hay fixture etiquetado)
# precision/recall contra expectativas explícitas.
# =============================================================================
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from src.core.domain.knowledge_v2 import StructuredBlockKind, StructuredDocument
from src.knowledge.compiler.model import CompilationResult

_LOCATOR_KEYS = (
    "page",
    "page_number",
    "page_start",
    "section_path",
    "block_id",
    "document_id",
    "source_id",
    "chunk_id",
)
_WORD_RE = re.compile(r"\w+", re.UNICODE)
_MIN_SHORT_BLOCK_CHARS = 40


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return round(float(numerator) / float(denominator), 4)


def _normalized(text: str) -> str:
    return " ".join(_WORD_RE.findall((text or "").lower()))


def _rule_texts(compiled: CompilationResult) -> list[str]:
    texts: list[str] = []
    for rule in compiled.canonical_rules:
        statement = getattr(rule, "statement", "") or ""
        if statement:
            texts.append(statement)
    return texts


def _evidence_stats(compiled: CompilationResult) -> dict[str, Any]:
    total_evidence = 0
    located = 0
    rules_with_evidence = 0
    total_properties = 0
    properties_with_evidence = 0
    for rule in compiled.canonical_rules:
        provenance = list(getattr(rule, "provenance", []) or [])
        if provenance:
            rules_with_evidence += 1
        for evidence in provenance:
            total_evidence += 1
            locator = getattr(evidence, "locator", {}) or {}
            if any(locator.get(key) for key in _LOCATOR_KEYS):
                located += 1
        for prop in (getattr(rule, "properties", {}) or {}).values():
            total_properties += 1
            if getattr(prop, "evidence", None):
                properties_with_evidence += 1
    total_rules = len(compiled.canonical_rules)
    return {
        "rules_with_evidence": rules_with_evidence,
        "orphan_rule_rate": _safe_ratio(total_rules - rules_with_evidence, total_rules),
        "evidence_locator_coverage": _safe_ratio(located, total_evidence),
        "rules_total": total_rules,
        "evidence_total": total_evidence,
        "property_provenance_completeness": _safe_ratio(
            properties_with_evidence, total_properties
        ),
        "properties_total": total_properties,
    }


def _rule_state_counts(compiled: CompilationResult) -> dict[str, int]:
    states = Counter(
        str(getattr(rule, "verification_state", "") or "UNKNOWN").upper()
        for rule in compiled.canonical_rules
    )
    total = len(compiled.canonical_rules)
    supported = sum(1 for rule in compiled.canonical_rules if getattr(rule, "supported", False))
    executable = sum(
        1 for rule in compiled.canonical_rules if getattr(rule, "executable", False)
    )
    return {
        "canonical_rules": total,
        "supported_rules": supported,
        "executable_rules": executable,
        "unresolved_rules": total - supported,
        "conflicting_rules": states.get("CONFLICTING", 0),
        "unknown_rules": states.get("UNKNOWN", 0),
        "partially_supported_rules": states.get("PARTIALLY_SUPPORTED", 0),
        "unsupported_rules": states.get("UNSUPPORTED", 0),
        "by_state": dict(sorted(states.items())),
    }


def _fragmentation_stats(
    understood: StructuredDocument, payload: dict[str, Any]
) -> dict[str, Any]:
    body_kinds = {
        StructuredBlockKind.PARAGRAPH,
        StructuredBlockKind.LIST,
        StructuredBlockKind.TABLE,
        StructuredBlockKind.NOTE,
        StructuredBlockKind.DEFINITION,
        StructuredBlockKind.FIELD_DEFINITION,
    }
    bodies = [
        block
        for block in understood.blocks
        if block.kind in body_kinds and not block.metadata.get("chrome")
    ]
    short = sum(1 for block in bodies if len((block.text or "").strip()) < _MIN_SHORT_BLOCK_CHARS)
    payload_units = payload.get("retrieval_units") or []
    unit_ids = [str(unit.get("unit_id") or "") for unit in payload_units if unit.get("unit_id")]
    units_count = int(
        payload.get("semantic_unit_count") or len(payload_units)
    )
    return {
        "body_blocks": len(bodies),
        "short_block_rate": _safe_ratio(short, len(bodies)),
        "semantic_units": units_count,
        "units_per_section": _safe_ratio(
            units_count,
            max(len(understood.sections), 1),
        ),
        "duplicate_unit_id_rate": _safe_ratio(
            len(unit_ids) - len(set(unit_ids)), len(unit_ids)
        ),
    }


def _duplicate_rule_rate(compiled: CompilationResult) -> float | None:
    texts = [_normalized(text) for text in _rule_texts(compiled) if text]
    if not texts:
        return None
    return _safe_ratio(len(texts) - len(set(texts)), len(texts))


def _contains_any(haystack: str, needles: tuple[str, ...]) -> bool:
    lowered = haystack.lower()
    return any(needle.lower() in lowered for needle in needles if needle)


def expectation_scores(
    *,
    understood: StructuredDocument,
    compiled: CompilationResult,
    expectations: dict[str, Any] | None,
) -> dict[str, Any]:
    """Precision/recall contra expectativas del fixture (cuando existen).

    - required_units: substrings que deben aparecer en los bloques/unidades.
    - required_rules: substrings que deben aparecer en reglas canónicas.
    - forbidden_rules: substrings que marcan ruido (afecta precision).
    - min_definitions: piso de definiciones del lado.
    """
    if not expectations:
        return {
            "recall_units": None,
            "recall_rules": None,
            "precision_rules": None,
            "definitions_floor_met": None,
            "expectations_evaluated": False,
        }
    corpus = "\n".join(block.text or "" for block in understood.blocks)
    payload = (understood.metadata or {}).get("understanding") or {}
    definitions = len(payload.get("definitions") or [])
    required_units = tuple(expectations.get("required_units") or ())
    required_rules = tuple(expectations.get("required_rules") or ())
    forbidden = tuple(expectations.get("forbidden_rules") or ())
    rule_texts = _rule_texts(compiled)
    found_units = sum(1 for needle in required_units if _contains_any(corpus, (needle,)))
    found_rules = sum(
        1
        for needle in required_rules
        if any(_contains_any(text, (needle,)) for text in rule_texts)
    )
    noisy_rules = sum(
        1 for text in rule_texts if _contains_any(text, forbidden)
    )
    minimum = expectations.get("min_definitions")
    return {
        "recall_units": _safe_ratio(found_units, len(required_units)),
        "recall_rules": _safe_ratio(found_rules, len(required_rules)),
        "precision_rules": (
            _safe_ratio(len(rule_texts) - noisy_rules, len(rule_texts))
            if forbidden
            else None
        ),
        "definitions_floor_met": (
            definitions >= int(minimum)
            if minimum is not None
            else None
        ),
        "expectations_evaluated": True,
    }


def evaluate_knowledge_quality(
    *,
    understood: StructuredDocument,
    compiled: CompilationResult,
    document: StructuredDocument | None = None,
    thread_stats: dict[str, int] | None = None,
    expectations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Tasas de calidad para un lado del A/B. None = no evaluable."""
    payload = (understood.metadata or {}).get("understanding") or {}
    states = _rule_state_counts(compiled)
    evidence = _evidence_stats(compiled)
    fragmentation = _fragmentation_stats(understood, payload)
    thread_stats = thread_stats or {}
    threads_total = sum(thread_stats.values())
    quality: dict[str, Any] = {
        "supported_rate": _safe_ratio(states["supported_rules"], states["canonical_rules"]),
        "executable_rate": _safe_ratio(
            states["executable_rules"], states["canonical_rules"]
        ),
        "unsupported_rate": _safe_ratio(
            states["unresolved_rules"], states["canonical_rules"]
        ),
        "conflicting_rate": _safe_ratio(
            states["conflicting_rules"], states["canonical_rules"]
        ),
        "unknown_rate": _safe_ratio(states["unknown_rules"], states["canonical_rules"]),
        "orphan_rule_rate": evidence["orphan_rule_rate"],
        "evidence_locator_coverage": evidence["evidence_locator_coverage"],
        "property_provenance_completeness": evidence["property_provenance_completeness"],
        "duplicate_rule_rate": _duplicate_rule_rate(compiled),
        "contradiction_rate": _safe_ratio(
            len(compiled.conflicts), states["canonical_rules"]
        ),
        "thread_resolved_rate": _safe_ratio(
            thread_stats.get("resolved", 0), threads_total
        ),
        "thread_ambiguous_rate": _safe_ratio(
            thread_stats.get("ambiguous", 0), threads_total
        ),
        "thread_unresolved_rate": _safe_ratio(
            thread_stats.get("unresolved", 0) + thread_stats.get("partial", 0),
            threads_total,
        ),
        **fragmentation,
    }
    quality.update(
        expectation_scores(
            understood=understood, compiled=compiled, expectations=expectations
        )
    )
    quality["evidence"] = evidence
    quality["states"] = states
    return quality


__all__ = ["evaluate_knowledge_quality", "expectation_scores"]
