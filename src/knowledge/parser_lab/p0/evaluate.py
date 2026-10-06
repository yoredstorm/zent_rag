# =============================================================================
# P0 — Métricas estáticas: estructura, semántica, conocimiento, reglas, premisas
# =============================================================================
# Todas se calculan contra el Golden Set. No hay LLM: matching determinista
# por needles (equivalents + properties) con umbral documentado.
# =============================================================================
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from src.knowledge.parser_lab.comparison import side_metrics
from src.knowledge.parser_lab.p0.golden import (
    RULE_LIKE_TYPES,
    best_match,
    claimed_knowledge_text,
    is_claimed,
    match_score,
    normalize,
)
from src.knowledge.parser_lab.p0.state import (
    KnowledgeState,
    candidate_rule_text,
    canonical_rule_text,
    unit_text,
)

MATCH_THRESHOLD = 0.75

_NUMBERED_SECTION = re.compile(r"^(\d+(?:\.\d+)*)")
_KNOWLEDGE_UNIT_TYPES = frozenset(
    {"DEFINITION", "FIELD_DEFINITION", "PATTERN", "NOTE", "WARNING", "PROCEDURE", "TABLE"}
)


def _fraction(hits: int, total: int) -> float | None:
    if total == 0:
        return None
    return round(hits / total, 4)


def golden_matches(
    state: KnowledgeState,
    golden: dict[str, Any],
    *,
    threshold: float = MATCH_THRESHOLD,
) -> dict[str, Any]:
    matches: dict[str, Any] = {}
    for golden_object in golden.get("objects") or []:
        haystacks = state.haystacks_for(str(golden_object.get("semantic_type")))
        matches[str(golden_object.get("id"))] = best_match(
            golden_object, haystacks, threshold=threshold
        )
    return matches


def _objects_of(golden: dict[str, Any], semantic_type: str) -> list[dict[str, Any]]:
    return [
        item
        for item in golden.get("objects") or []
        if item.get("semantic_type") == semantic_type
    ]


def _golden_needles_text(golden: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in golden.get("equivalents") or []:
        parts.append(str(item))
    for value in (golden.get("properties") or {}).values():
        parts.append(str(value))
    return " ".join(parts)


def structural_metrics(
    state: KnowledgeState,
    golden: dict[str, Any],
    *,
    reference_text: str | None = None,
) -> dict[str, Any]:
    document = state.understood
    document_text = state.document_text
    base = side_metrics(document, label=state.label, reference_text=reference_text)
    objects = golden.get("objects") or []

    text_hits = sum(
        1
        for item in objects
        if match_score(item, document_text) >= MATCH_THRESHOLD
    )
    order_hits = 0
    order_total = 0
    for item in objects:
        pages = item.get("pages") or []
        if not pages:
            continue
        order_total += 1
        expected_page = min(int(page) for page in pages)
        best_order = None
        for block in document.blocks:
            if match_score(item, block.text or "") >= 0.5:
                if best_order is None or block.order < best_order[0]:
                    best_order = (block.order, block.page)
        if best_order is not None and best_order[1] == expected_page:
            order_hits += 1

    headings = [
        normalize(block.text)
        for block in document.blocks
        if block.kind.value == "heading"
    ]
    heading_text = " \n ".join(headings)
    section_total = 0
    heading_hits = 0
    hierarchy_hits = 0
    hierarchy_total = 0
    section_paths = {tuple(section.section_path) for section in document.sections}
    for item in objects:
        section = item.get("section")
        if not section:
            continue
        section_total += 1
        normalized = normalize(str(section))
        if normalized and normalized in heading_text:
            heading_hits += 1
        numbered = _NUMBERED_SECTION.match(str(section).strip())
        if numbered:
            hierarchy_total += 1
            segments = numbered.group(1).split(".")
            if len(segments) == 1:
                hierarchy_hits += 1
            else:
                parent = tuple(segments[:-1])
                if any(
                    tuple(str(part) for part in path[: len(parent)]) == parent
                    for path in section_paths
                ):
                    hierarchy_hits += 1

    table_goldens = _objects_of(golden, "table_mapping")
    table_detected = 0
    table_structured = 0
    for item in table_goldens:
        matched_table = None
        for table in document.tables:
            from src.knowledge.parser_lab.p0.state import table_text

            if match_score(item, table_text(table)) >= MATCH_THRESHOLD:
                matched_table = table
                break
        if matched_table is not None:
            table_detected += 1
            headers_ok = bool(matched_table.headers) and any(
                str(header).strip() for header in matched_table.headers
            )
            rectangular = bool(matched_table.headers) and all(
                len(row) == len(matched_table.headers) for row in matched_table.rows
            )
            if headers_ok and rectangular:
                table_structured += 1

    symbols = {
        needle
        for item in objects
        for needle in (item.get("equivalents") or [])
        if len(str(needle).strip()) == 1
    }
    symbol_hits = sum(1 for symbol in symbols if str(symbol) in document_text)

    special = {
        char
        for item in objects
        for char in _golden_needles_text(item)
        if ord(char) > 127
    }
    special_hits = sum(1 for char in special if char in document_text)

    cross_page = _objects_of(golden, "cross_page_rule")
    cross_page_hits = 0
    canonical_haystacks = state.haystacks_for("rule")
    for item in cross_page:
        pages = {int(page) for page in item.get("pages") or []}
        match = best_match(item, canonical_haystacks)
        rule_pages: set[int] = set()
        if match.matched and match.produced_index is not None:
            rule_pages = KnowledgeState.rule_pages(canonical_haystacks[match.produced_index][1])
        unit_pages: set[int] = set()
        for text, unit, kind in state.haystacks_for("unit"):
            if kind == "unit" and match_score(item, text) >= 0.5:
                start = getattr(unit, "page_start", None)
                end = getattr(unit, "page_end", None)
                if start is not None and end is not None and start != end:
                    unit_pages.update({int(start), int(end)})
        covered = rule_pages | unit_pages
        if pages and len(pages & covered) >= min(2, len(pages)):
            cross_page_hits += 1

    return {
        "text_preservation_recall": _fraction(text_hits, len(objects)),
        "reading_order_accuracy": _fraction(order_hits, order_total),
        "heading_accuracy": _fraction(heading_hits, section_total),
        "section_hierarchy_accuracy": _fraction(hierarchy_hits, hierarchy_total),
        "table_detection_recall": _fraction(table_detected, len(table_goldens)),
        "table_structure_accuracy": _fraction(table_structured, len(table_goldens)),
        "symbol_preservation": _fraction(symbol_hits, len(symbols)),
        "special_character_preservation": _fraction(special_hits, len(special)),
        "cross_page_continuity": _fraction(cross_page_hits, len(cross_page)),
        "duplicate_rate": base["text"]["duplicate_text_groups"],
        "duplicate_text_chars": base["text"]["duplicate_text_chars"],
        "header_footer_contamination": base["text"]["repeated_chrome_candidates"],
        "broken_sentence_rate": base["text"]["broken_sentences"],
        "page_regressions": base["reading_order"]["page_regressions"],
        "bbox_coverage": base["bbox"]["block_bbox_coverage"],
        "fixed_width_rows": base["text"]["fixed_width_rows"],
        "missing_reference_chars": base["text"].get("missing_reference_chars"),
        "text_recall_tokens": base["text"].get("text_recall_tokens"),
        "tables": base["tables"]["tables"],
        "blocks": base["reading_order"]["blocks"],
        "headings": base["kind_counts"].get("heading", 0),
        "sections": base["sections"]["sections"],
        "kind_counts": base["kind_counts"],
    }


def semantic_metrics(
    state: KnowledgeState,
    golden: dict[str, Any],
    matches: dict[str, Any],
) -> dict[str, Any]:
    objects = golden.get("objects") or []
    unit_haystacks = state.haystacks_for("unit")
    unit_matches = {
        str(item.get("id")): best_match(item, unit_haystacks) for item in objects
    }
    unit_recall = sum(1 for match in unit_matches.values() if match.matched)

    claimed_units: list[tuple[str, Any]] = []
    for text, unit, _kind in unit_haystacks:
        unit_type = str(getattr(unit, "unit_type", "") or "")
        if unit_type in _KNOWLEDGE_UNIT_TYPES or claimed_knowledge_text(text):
            claimed_units.append((text, unit))
    claimed_matched = 0
    merged_units = 0
    for text, _unit in claimed_units:
        hits = [
            item
            for item in objects
            if match_score(item, text) >= MATCH_THRESHOLD
        ]
        if hits:
            claimed_matched += 1
        types = {str(item.get("semantic_type")) for item in hits}
        if len(hits) >= 2 and len(types) >= 2:
            merged_units += 1

    fragmented = 0
    matched_overall = 0
    for item in objects:
        overall = matches.get(str(item.get("id")))
        if overall is None or not overall.matched:
            continue
        matched_overall += 1
        unit_match = unit_matches[str(item.get("id"))]
        if unit_match.matched:
            continue
        partial = sum(
            1 for text, _unit, _kind in unit_haystacks if match_score(item, text) >= 0.5
        )
        if partial >= 2:
            fragmented += 1

    cross_page = _objects_of(golden, "cross_page_rule")
    cross_page_hits = 0
    canonical_haystacks = state.haystacks_for("rule")
    for item in cross_page:
        hit = False
        match = unit_matches.get(str(item.get("id")))
        if match is not None and match.matched:
            unit = unit_haystacks[match.produced_index][1]
            start = getattr(unit, "page_start", None)
            end = getattr(unit, "page_end", None)
            metadata = getattr(unit, "metadata", {}) or {}
            if (start is not None and end is not None and start != end) or metadata.get(
                "continuation"
            ):
                hit = True
        if not hit:
            canonical_match = best_match(item, canonical_haystacks)
            if canonical_match.matched and canonical_match.produced_index is not None:
                rule = canonical_haystacks[canonical_match.produced_index][1]
                pages = KnowledgeState.rule_pages(rule)
                golden_pages = {int(page) for page in item.get("pages") or []}
                if golden_pages and len(pages & golden_pages) >= min(2, len(golden_pages)):
                    hit = True
        if hit:
            cross_page_hits += 1

    definitions = _objects_of(golden, "definition")
    definition_haystacks = state.haystacks_for("definition")
    definition_hits = sum(
        1
        for item in definitions
        if best_match(item, definition_haystacks).matched
    )

    rule_like = [item for item in objects if item.get("semantic_type") in RULE_LIKE_TYPES]
    candidate_haystacks = state.haystacks_for("rule")
    candidate_hits = sum(
        1 for item in rule_like if best_match(item, candidate_haystacks).matched
    )

    exceptions = _objects_of(golden, "exception")
    exception_haystacks = state.haystacks_for("exception")
    exception_hits = sum(
        1 for item in exceptions if best_match(item, exception_haystacks).matched
    )

    tables = _objects_of(golden, "table_mapping")
    table_units = [
        item for item in unit_haystacks if str(getattr(item[1], "unit_type", "")) == "TABLE"
    ]
    table_hits = sum(
        1 for item in tables if best_match(item, table_units).matched
    )

    return {
        "semantic_unit_recall": _fraction(unit_recall, len(objects)),
        "semantic_unit_precision": _fraction(claimed_matched, len(claimed_units)),
        "claimed_units": len(claimed_units),
        "fragmentation_rate": _fraction(fragmented, matched_overall),
        "incorrect_merge_rate": _fraction(merged_units, len(claimed_units)),
        "cross_page_stitch_accuracy": _fraction(cross_page_hits, len(cross_page)),
        "definition_detection_recall": _fraction(definition_hits, len(definitions)),
        "rule_candidate_recall": _fraction(candidate_hits, len(rule_like)),
        "exception_detection_recall": _fraction(exception_hits, len(exceptions)),
        "table_semantic_preservation": _fraction(table_hits, len(tables)),
        "units_total": len(unit_haystacks),
    }


def _produced_precision(
    state: KnowledgeState,
    golden: dict[str, Any],
    semantic_type: str,
    *,
    anchor_claimed_only: bool,
) -> tuple[float | None, int, int]:
    goldens = _objects_of(golden, semantic_type)
    produced = state.produced_haystacks_for(semantic_type)
    if anchor_claimed_only:
        produced = [
            (text, obj, kind)
            for text, obj, kind in produced
            if is_claimed(text, golden)
        ]
    if not produced:
        return None, 0, len(goldens)
    matched = 0
    for text, _obj, _kind in produced:
        if any(match_score(item, text) >= MATCH_THRESHOLD for item in goldens):
            matched += 1
    return _fraction(matched, len(produced)), len(produced), len(goldens)


def knowledge_metrics(
    state: KnowledgeState,
    golden: dict[str, Any],
    matches: dict[str, Any],
) -> dict[str, Any]:
    type_map = {
        "definition": ("definition", False),
        "fact": ("fact", True),
        "relationship": ("relationship", True),
        "rule": ("rule", False),
        "exception": ("exception", False),
        "enumeration": ("enumeration", False),
        "formula": ("formula", False),
        "table_mapping": ("table_mapping", False),
    }
    result: dict[str, Any] = {}
    recalls: list[float] = []
    precisions: list[tuple[float, int]] = []
    for label, (semantic_type, anchor_only) in type_map.items():
        goldens = _objects_of(golden, semantic_type)
        if not goldens:
            result[f"{label}_recall"] = None
            result[f"{label}_precision"] = None
            continue
        produced = state.produced_haystacks_for(semantic_type)
        recall_hits = sum(
            1
            for item in goldens
            if best_match(item, produced).matched
        )
        recall = _fraction(recall_hits, len(goldens))
        precision, produced_count, _ = _produced_precision(
            state, golden, semantic_type, anchor_claimed_only=anchor_only
        )
        result[f"{label}_recall"] = recall
        result[f"{label}_precision"] = precision
        if recall is not None:
            recalls.append(recall)
        if precision is not None and produced_count:
            precisions.append((precision, produced_count))
    result["knowledge_recall_avg"] = (
        round(sum(recalls) / len(recalls), 4) if recalls else None
    )
    if precisions:
        total = sum(count for _value, count in precisions)
        result["knowledge_precision"] = round(
            sum(value * count for value, count in precisions) / total, 4
        )
    else:
        result["knowledge_precision"] = None
    return result


def canonical_metrics(
    state: KnowledgeState,
    golden: dict[str, Any],
    matches: dict[str, Any],
) -> dict[str, Any]:
    canonical = state.rules
    rule_like = [item for item in golden.get("objects") or [] if item.get("semantic_type") in RULE_LIKE_TYPES]
    canonical_haystacks = state.haystacks_for("rule")
    canonical_only = [
        item for item in canonical_haystacks if item[2] == "canonical_rule"
    ]

    recall_hits = sum(
        1 for item in rule_like if best_match(item, canonical_only).matched
    )
    matched_canonical = 0
    for text, _rule, _kind in canonical_only:
        if any(match_score(item, text) >= MATCH_THRESHOLD for item in rule_like):
            matched_canonical += 1

    states = Counter(str(getattr(rule, "verification_state", "") or "UNKNOWN") for rule in canonical)
    supported = sum(1 for rule in canonical if getattr(rule, "supported", False))
    executable = sum(1 for rule in canonical if getattr(rule, "executable", False))
    missing_premises = sum(
        1 for rule in canonical if getattr(rule, "missing_premises", None)
    )
    properties_total = 0
    properties_with_evidence = 0
    for rule in canonical:
        for prop in (getattr(rule, "properties", {}) or {}).values():
            properties_total += 1
            if getattr(prop, "evidence", None):
                properties_with_evidence += 1
    return {
        "canonical_rule_recall": _fraction(recall_hits, len(rule_like)),
        "canonical_rule_precision": _fraction(matched_canonical, len(canonical_only)),
        "canonical_rules": len(canonical),
        "supported_rate": _fraction(supported, len(canonical)),
        "executable_rate": _fraction(executable, len(canonical)),
        "unknown_rate": _fraction(states.get("UNKNOWN", 0), len(canonical)),
        "partially_supported_rate": _fraction(
            states.get("PARTIALLY_SUPPORTED", 0), len(canonical)
        ),
        "conflicting_rate": _fraction(states.get("CONFLICTING", 0), len(canonical)),
        "false_rule_rate": _fraction(len(canonical_only) - matched_canonical, len(canonical_only)),
        "missing_premise_rate": _fraction(missing_premises, len(canonical)),
        "property_provenance_completeness": _fraction(
            properties_with_evidence, properties_total
        ),
        "contradiction_rate": _fraction(
            len(state.compiled.conflicts), len(canonical)
        ),
        "false_rule_count": len(canonical_only) - matched_canonical,
    }


# ---------------------------------------------------------------------------
# Premise coverage
# ---------------------------------------------------------------------------


def _definition_corpus(state: KnowledgeState) -> str:
    parts = [state.document_text]
    for definition in state.definitions:
        parts.append(f"{definition.get('term')} {definition.get('definition')}")
    parts.extend(canonical_rule_text(rule) for rule in state.rules)
    parts.extend(candidate_rule_text(rule) for rule in state.compiled.rules)
    parts.extend(unit_text(unit) for _text, unit, _kind in state.haystacks_for("unit"))
    return "\n".join(parts)


def _symbol_defined(state: KnowledgeState, symbol: str) -> bool:
    raw_corpus = _definition_corpus(state)
    if not symbol or symbol not in raw_corpus:
        return False
    corpus = normalize(raw_corpus)
    markers = ("alphanumeric", "position", "indica", "match", "caracter", "significa")
    return sum(1 for marker in markers if marker in corpus) >= 2


def premise_satisfied(premise: str, state: KnowledgeState, golden: dict[str, Any]) -> bool:
    corpus = normalize(_definition_corpus(state))
    if premise == "symbol.definition":
        symbols = [
            str(value)
            for key, value in (golden.get("properties") or {}).items()
            if "symbol" in key
        ] or [
            needle
            for needle in (golden.get("equivalents") or [])
            if len(str(needle).strip()) == 1
        ]
        return any(_symbol_defined(state, symbol) for symbol in symbols)
    if premise == "matching.operator":
        for rule in state.rules:
            for prop in (getattr(rule, "properties", {}) or {}).values():
                name = str(getattr(prop, "name", "")).lower()
                value = str(getattr(prop, "value", "")).lower()
                if "match" in name or "operator" in name or "positional" in value:
                    return True
        return any(
            marker in corpus
            for marker in (
                "positionally",
                "specific position",
                "positional",
                "posicional",
                "position",
            )
        )
    if premise == "length.policy":
        for rule in state.rules:
            for prop in (getattr(rule, "properties", {}) or {}).values():
                name = str(getattr(prop, "name", "")).lower()
                value = str(getattr(prop, "value", "")).lower()
                if "length" in name or "longitud" in name or "length" in value:
                    return True
        return any(
            marker in corpus
            for marker in (
                "at least the number of characters",
                "longitud minima",
                "length",
                "min length",
            )
        )
    if premise == "condition.present":
        for rule in state.rules:
            if getattr(rule, "conditions", None):
                return True
        return any(
            marker in corpus
            for marker in (" si ", " if ", " supera", " excede", " when ", " mayor a")
        )
    if premise == "range.value":
        for rule in state.rules:
            for prop in (getattr(rule, "properties", {}) or {}).values():
                name = str(getattr(prop, "name", "")).lower()
                if "range" in name or "position" in name or "byte" in name:
                    return True
        return bool(re.search(r"\b\d{1,3}\s*[-–]\s*\d{1,3}\b", corpus))
    if premise == "formula.expression":
        for rule in state.rules:
            expression = str(getattr(getattr(rule, "formula", None), "expression", "") or "")
            if expression:
                return True
        return state.has_formula_block(state)
    if premise == "table.mapping":
        return any(
            match_score(golden, text) >= 0.4 for text, _obj, _kind in state.haystacks_for("table")
        )
    if premise == "temporal.window":
        return bool(re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", corpus))
    if premise == "enumeration.values":
        for rule in state.rules:
            enumeration = getattr(rule, "enumeration", None)
            if enumeration is not None and (
                getattr(enumeration, "values", None) or getattr(enumeration, "allowed", None)
            ):
                return True
        return bool(re.search(r"\b(nuevo|activo|suspendido)\b", corpus))
    return False


def premise_metrics(
    state: KnowledgeState,
    golden: dict[str, Any],
    matches: dict[str, Any],
) -> dict[str, Any]:
    per_premise: dict[str, list[int]] = {}
    object_coverage: list[float] = []
    required_total = 0
    satisfied_total = 0
    for item in golden.get("objects") or []:
        required = list(item.get("required_premises") or [])
        if not required:
            continue
        required_total += len(required)
        satisfied = 0
        for premise in required:
            ok = premise_satisfied(premise, state, item)
            per_premise.setdefault(premise, []).append(1 if ok else 0)
            satisfied += 1 if ok else 0
        satisfied_total += satisfied
        object_coverage.append(round(satisfied / len(required), 4))
    rates = {
        premise: _fraction(sum(values), len(values))
        for premise, values in sorted(per_premise.items())
    }
    return {
        "premise_coverage_recall": _fraction(satisfied_total, required_total),
        "premise_objects": len(object_coverage),
        "premise_per_kind": rates,
    }


def all_static_metrics(
    state: KnowledgeState,
    golden: dict[str, Any],
    *,
    reference_text: str | None = None,
) -> dict[str, Any]:
    matches = golden_matches(state, golden)
    return {
        "structural": structural_metrics(state, golden, reference_text=reference_text),
        "semantic": semantic_metrics(state, golden, matches),
        "knowledge": knowledge_metrics(state, golden, matches),
        "canonical": canonical_metrics(state, golden, matches),
        "premise": premise_metrics(state, golden, matches),
        "matches": {
            key: {
                "matched": value.matched,
                "score": value.score,
                "produced_kind": value.produced_kind,
            }
            for key, value in matches.items()
        },
    }


__all__ = [
    "MATCH_THRESHOLD",
    "all_static_metrics",
    "canonical_metrics",
    "golden_matches",
    "knowledge_metrics",
    "premise_metrics",
    "premise_satisfied",
    "semantic_metrics",
    "structural_metrics",
]
