# =============================================================================
# P0 — Golden Set: matching semántico (sin LLM, determinista)
# =============================================================================
# Un objeto golden "está" en un KnowledgeState si sus needles (equivalents +
# valores de properties) aparecen en el texto normalizado de los objetos
# producidos del tipo compatible. No compara texto literal exclusivamente:
# equivalencias + propiedades + allowed_formulations.
# =============================================================================
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

_WORD_RE = re.compile(r"[^\w]+", re.UNICODE)

#: Tipos golden -> tipos producidos compatibles (para provenance y diff).
COMPATIBLE_KINDS: dict[str, tuple[str, ...]] = {
    "definition": ("definition", "unit", "block"),
    "fact": ("fact", "unit"),
    "rule": ("rule_candidate", "canonical_rule", "unit"),
    "cross_page_rule": ("canonical_rule", "rule_candidate", "unit"),
    "condition": ("canonical_rule", "rule_candidate"),
    "exception": ("canonical_rule", "rule_candidate", "unit"),
    "relationship": ("relationship", "unit"),
    "enumeration": ("canonical_rule", "unit", "fact"),
    "range": ("canonical_rule", "unit", "table"),
    "formula": ("canonical_rule", "block", "unit"),
    "table_mapping": ("table", "unit"),
    "symbol_definition": ("definition", "unit", "rule_candidate", "canonical_rule"),
    "length_policy": ("canonical_rule", "rule_candidate", "unit"),
    "temporal_constraint": ("canonical_rule", "unit"),
    "reference": ("unit", "relationship"),
}

RULE_LIKE_TYPES = frozenset({"rule", "cross_page_rule", "length_policy"})

#: Marker de "unidad con conocimiento" para precision (evita castigar
#: unidades puramente estructurales sin vocabulario golden).
_CLAIM_MARKERS = (
    " must ",
    " must not ",
    " no debe ",
    " se define ",
    " definido ",
    " significa ",
    " salvo ",
    " excepto ",
    " si ",
    " requiere ",
    " genera ",
    " aplica ",
)


@lru_cache(maxsize=200_000)
def normalize(text: str) -> str:
    lowered = unicodedata.normalize("NFKC", text or "").lower()
    return " ".join(_WORD_RE.sub(" ", lowered).split())


def _needles(golden: dict[str, Any]) -> list[str]:
    needles: list[str] = []
    for item in golden.get("equivalents") or ():
        if item:
            needles.append(str(item))
    for value in (golden.get("properties") or {}).values():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            needles.extend(str(part) for part in value)
        else:
            needles.append(str(value))
    for item in golden.get("allowed_formulations") or ():
        if item:
            needles.append(str(item))
    return [needle for needle in dict.fromkeys(needles) if needle.strip()]


def match_score(golden: dict[str, Any], haystack: str) -> float:
    """Fracción de needles golden presentes en el haystack (0..1).

    Símbolos puros (&, !) se comparan en crudo: normalizar los borraría.
    """
    needles = _needles(golden)
    if not needles:
        return 0.0
    text = normalize(haystack)
    hits = 0
    for needle in needles:
        normalized = normalize(needle)
        if normalized:
            if normalized in text:
                hits += 1
        elif needle in (haystack or ""):
            hits += 1
    return round(hits / len(needles), 4)


@dataclass(frozen=True)
class GoldenMatch:
    golden_id: str
    semantic_type: str
    score: float
    matched: bool
    produced_kind: str | None = None
    produced_index: int | None = None
    pages: tuple[int, ...] = ()
    section: str | None = None


def best_match(
    golden: dict[str, Any],
    haystacks: list[tuple[str, Any, str]],
    *,
    threshold: float = 0.75,
) -> GoldenMatch:
    """Mejor match de un golden object contra [(texto, objeto, kind)]."""
    best_score = 0.0
    best_kind: str | None = None
    best_index: int | None = None
    for index, (text, _obj, kind) in enumerate(haystacks):
        score = match_score(golden, text)
        if score > best_score:
            best_score = score
            best_kind = kind
            best_index = index
    return GoldenMatch(
        golden_id=str(golden.get("id")),
        semantic_type=str(golden.get("semantic_type")),
        score=best_score,
        matched=best_score >= threshold,
        produced_kind=best_kind,
        produced_index=best_index,
        pages=tuple(int(page) for page in golden.get("pages") or ()),
        section=golden.get("section"),
    )


def is_claimed(text: str, golden: dict[str, Any]) -> bool:
    """¿El objeto producido reclama conocimiento del corpus?"""
    anchors = [normalize(str(term)) for term in golden.get("anchor_terms") or ()]
    if not anchors:
        return False
    normalized = normalize(text)
    return any(anchor and anchor in normalized for anchor in anchors)


def claimed_knowledge_text(text: str) -> bool:
    lowered = f" {(text or '').lower()} "
    return any(marker in lowered for marker in _CLAIM_MARKERS)


__all__ = [
    "COMPATIBLE_KINDS",
    "GoldenMatch",
    "RULE_LIKE_TYPES",
    "best_match",
    "claimed_knowledge_text",
    "is_claimed",
    "match_score",
    "normalize",
]
