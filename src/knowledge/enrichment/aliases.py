# =============================================================================
# Enrichment — aliases de retrieval
# =============================================================================
# Un alias de enrichment NO es un alias canónico de entidad: es una variante
# de búsqueda con provenance. La resolución de identidad sigue siendo del
# EntityResolver del compilador (la duda es información).
# =============================================================================
from __future__ import annotations

from src.knowledge.enrichment.contracts import RetrievalAlias, SemanticConcept
from src.knowledge.enrichment.normalize import normalize_key, surface_variants
from src.knowledge.enrichment.profiling import EnrichmentContext
from src.knowledge.enrichment.versioning import POLICY_VERSION


def _kind_for(original: str, variant: str) -> str:
    if variant.lower() == original.lower():
        return "surface"
    if variant.upper() == variant and any(char.isalpha() for char in variant) and " " not in variant:
        return "code"
    if variant.replace("-", "").replace("_", "").replace(" ", "").lower() == original.replace(
        "-", ""
    ).replace("_", "").replace(" ", "").lower():
        return "separator"
    return "case"


def build_aliases(
    context: EnrichmentContext,
    concepts: tuple[SemanticConcept, ...],
    *,
    max_per_concept: int = 6,
    max_total: int = 400,
) -> tuple[RetrievalAlias, ...]:
    """Variantes deterministas por concepto + aliases explícitos del documento."""
    aliases: list[RetrievalAlias] = []
    seen: dict[str, RetrievalAlias] = {}

    def add(value: str, *, units: tuple[str, ...], confidence: float, kind: str, concept_id: str | None) -> None:
        cleaned = " ".join(str(value or "").split())
        if not cleaned or len(cleaned) > 80:
            return
        key = normalize_key(cleaned)
        if not key:
            return
        candidate = RetrievalAlias(
            value=cleaned,
            kind=kind,
            target_concept_id=concept_id,
            source_unit_ids=units,
            confidence=max(0.0, min(1.0, confidence)),
            derivation_method="deterministic",
            policy_version=POLICY_VERSION,
        )
        existing = seen.get(key)
        if existing is None or candidate.confidence > existing.confidence:
            seen[key] = candidate

    for concept in concepts:
        variants = surface_variants(concept.canonical_name, max_variants=max_per_concept)
        for variant in variants:
            add(
                variant,
                units=concept.source_unit_ids,
                confidence=max(0.5, concept.confidence - 0.1),
                kind=_kind_for(concept.canonical_name, variant),
                concept_id=concept.concept_id,
            )
        for explicit in concept.aliases:
            add(
                explicit,
                units=concept.source_unit_ids,
                confidence=max(0.55, concept.confidence - 0.05),
                kind=_kind_for(concept.canonical_name, explicit),
                concept_id=concept.concept_id,
            )

    aliases = list(seen.values())
    aliases.sort(key=lambda item: (-item.confidence, item.value.casefold()))
    return tuple(aliases[:max_total])
