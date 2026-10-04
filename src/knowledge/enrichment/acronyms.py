# =============================================================================
# Enrichment — acrónimos
# =============================================================================
# Dos caminos deterministas:
#   1. explícito en el texto:  «Voluntary Changes (VC)»
#   2. iniciales de un nombre multi-palabra («Voluntary Changes» -> VC)
#
# Nunca se inventan expansiones: el acrónimo se enlaza a la forma que YA
# aparece en la fuente. Confianza baja/media y provenance obligatoria.
# =============================================================================
from __future__ import annotations

import re

from src.knowledge.enrichment.contracts import RetrievalAlias, SemanticConcept
from src.knowledge.enrichment.normalize import collapse, normalize_key, split_tokens
from src.knowledge.enrichment.profiling import EnrichmentContext
from src.knowledge.enrichment.versioning import POLICY_VERSION

_EXPLICIT = re.compile(
    r"\b([A-Z][A-Za-z0-9][A-Za-z0-9\s\-/]{2,60}?)\s*\(([A-Z][A-Z0-9]{1,9})\)"
)

_INITIAL_STOP = frozenset({"of", "the", "and", "de", "del", "la", "el", "y", "for", "to", "a"})


def _initials(name: str) -> str | None:
    tokens = [token for token in split_tokens(name) if token]
    if not 2 <= len(tokens) <= 6:
        return None
    # Solo tokens significativos (>=2 chars): evita iniciales de ruido tipo
    # "Y CONT" -> "YC" (no hay evidencia de que sea un acrónimo real).
    significant = [
        token
        for token in tokens
        if len(token) >= 2 and token.lower() not in _INITIAL_STOP and token[:1].isalpha()
    ]
    if len(significant) < 2:
        return None
    acronym = "".join(token[0].upper() for token in significant)
    if not 2 <= len(acronym) <= 6:
        return None
    return acronym


def build_acronyms(
    context: EnrichmentContext,
    concepts: tuple[SemanticConcept, ...],
    *,
    max_total: int = 200,
) -> tuple[RetrievalAlias, ...]:
    by_key = {normalize_key(concept.canonical_name): concept for concept in concepts}
    found: dict[str, RetrievalAlias] = {}

    def add(value: str, *, units: tuple[str, ...], confidence: float, concept_id: str | None) -> None:
        acronym = collapse(value).upper()
        if not acronym or len(acronym) > 10:
            return
        key = normalize_key(acronym)
        candidate = RetrievalAlias(
            value=acronym,
            kind="acronym",
            target_concept_id=concept_id,
            source_unit_ids=units,
            confidence=max(0.0, min(1.0, confidence)),
            derivation_method="structural" if concept_id else "deterministic",
            policy_version=POLICY_VERSION,
        )
        existing = found.get(key)
        if existing is None or candidate.confidence > existing.confidence:
            found[key] = candidate

    # 1. Explícitos en el texto.
    for block in context.document.blocks:
        text = block.text or ""
        if "(" not in text:
            continue
        for match in _EXPLICIT.finditer(text):
            expansion, acronym = match.group(1), match.group(2)
            concept = by_key.get(normalize_key(expansion))
            add(
                acronym,
                units=context.valid_units([str(block.id)]),
                confidence=0.85 if concept is not None else 0.7,
                concept_id=concept.concept_id if concept is not None else None,
            )

    # 2. Iniciales de conceptos multi-palabra (nunca para frases genéricas).
    for concept in concepts:
        tokens = [token for token in split_tokens(concept.canonical_name) if token]
        if not 2 <= len(tokens) <= 5:
            continue
        acronym = _initials(concept.canonical_name)
        if acronym is None:
            continue
        add(
            acronym,
            units=concept.source_unit_ids,
            confidence=max(0.45, concept.confidence - 0.25),
            concept_id=concept.concept_id,
        )

    result = sorted(found.values(), key=lambda item: (-item.confidence, item.value))
    return tuple(result[:max_total])
