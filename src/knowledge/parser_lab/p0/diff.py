# =============================================================================
# P0 — KnowledgeDiff(A, B): qué conocimiento aparece, se pierde o cambia
# =============================================================================
# Compara los matches golden de dos KnowledgeStates por objeto canónico.
# Categorías del brief §16. ADDED_FALSE se computa sobre objetos producidos
# que no matchean ningún golden (conocimiento inventado).
# =============================================================================
from __future__ import annotations

from typing import Any

from src.knowledge.parser_lab.p0.evaluate import MATCH_THRESHOLD
from src.knowledge.parser_lab.p0.golden import best_match, match_score
from src.knowledge.parser_lab.p0.state import KnowledgeState


def _produced_false(
    state: KnowledgeState, golden: dict[str, Any], *, semantic_type: str
) -> list[dict[str, Any]]:
    goldens = [
        item
        for item in golden.get("objects") or []
        if item.get("semantic_type") == semantic_type
    ]
    false_objects: list[dict[str, Any]] = []
    for text, obj, kind in state.produced_haystacks_for(semantic_type):
        if any(match_score(item, text) >= MATCH_THRESHOLD for item in goldens):
            continue
        false_objects.append(
            {
                "kind": kind,
                "text": (text or "")[:160],
                "object_id": str(getattr(obj, "rule_id", "") or getattr(obj, "id", "")),
            }
        )
    return false_objects


def knowledge_diff(
    golden: dict[str, Any],
    state_a: KnowledgeState,
    state_b: KnowledgeState,
    matches_a: dict[str, Any],
    matches_b: dict[str, Any],
) -> dict[str, Any]:
    categories: dict[str, list[dict[str, Any]]] = {
        "ADDED_CORRECT": [],
        "ADDED_FALSE": [],
        "MISSING": [],
        "CHANGED": [],
        "MORE_COMPLETE": [],
        "LESS_COMPLETE": [],
        "PROVENANCE_IMPROVED": [],
        "PROVENANCE_REGRESSED": [],
    }
    for item in golden.get("objects") or []:
        object_id = str(item.get("id"))
        match_a = matches_a.get(object_id)
        match_b = matches_b.get(object_id)
        entry = {
            "id": object_id,
            "semantic_type": item.get("semantic_type"),
            "meaning": item.get("meaning"),
            "pages": item.get("pages"),
        }
        if match_a is None or match_b is None:
            continue
        if not match_a.matched and match_b.matched:
            categories["ADDED_CORRECT"].append({**entry, "b_score": match_b.score})
            continue
        if match_a.matched and not match_b.matched:
            categories["MISSING"].append({**entry, "a_score": match_a.score})
            continue
        if not match_a.matched and not match_b.matched:
            continue
        delta = round(match_b.score - match_a.score, 4)
        if abs(delta) > 0.1:
            categories["CHANGED"].append({**entry, "delta": delta})
        if delta > 0:
            categories["MORE_COMPLETE"].append({**entry, "delta": delta})
        elif delta < 0:
            categories["LESS_COMPLETE"].append({**entry, "delta": delta})
        provenance_a = _provenance_for(state_a, item)
        provenance_b = _provenance_for(state_b, item)
        if provenance_b > provenance_a:
            categories["PROVENANCE_IMPROVED"].append(
                {**entry, "a": provenance_a, "b": provenance_b}
            )
        elif provenance_b < provenance_a:
            categories["PROVENANCE_REGRESSED"].append(
                {**entry, "a": provenance_a, "b": provenance_b}
            )
    for semantic_type in ("rule", "table_mapping", "definition"):
        false_b = _produced_false(state_b, golden, semantic_type=semantic_type)
        for false_object in false_b:
            categories["ADDED_FALSE"].append(
                {**false_object, "semantic_type": semantic_type, "side": "b"}
            )
    counts = {name: len(items) for name, items in categories.items()}
    return {
        "schema": "zent.knowledge_diff.1",
        "counts": counts,
        "categories": categories,
    }


def _provenance_for(state: KnowledgeState, golden_object: dict[str, Any]) -> float:
    """Cobertura de locators de las reglas que matchean el golden."""
    rules = state.haystacks_for("rule")
    rules = [item for item in rules if item[2] == "canonical_rule"]
    match = best_match(golden_object, rules)
    if not match.matched or match.produced_index is None:
        return 0.0
    rule = rules[match.produced_index][1]
    return 1.0 if KnowledgeState.rule_has_locator(rule) else 0.0


__all__ = ["knowledge_diff"]
