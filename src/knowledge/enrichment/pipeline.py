# =============================================================================
# Enrichment — pipeline
# =============================================================================
# Orden obligatorio (deterministic-first):
#   1. structural  (definiciones, campos, secciones, columnas)
#   2. deterministic (aliases, acrónimos, identificadores, fechas, unidades)
#   3. statistical  (términos representativos viven en parent representation)
#   4. domain heuristics (profile packs)
#   5. model items (opcional, validados por el mismo guard, NUNCA inventan)
#
# Sin provider configurado, todo se resuelve sin LLM.
# =============================================================================
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Iterable

from src.core.domain.knowledge_v2 import StructuredDocument

from .acronyms import build_acronyms
from .aliases import build_aliases
from .concepts import build_concepts
from .contracts import (
    EnrichmentItem,
    EnrichmentStatistics,
    RetrievalAlias,
    SemanticConcept,
    SemanticEnrichmentResult,
)
from .identifiers import build_identifiers, identifier_aliases
from .metrics import observe_enrichment
from .profiling import EnrichmentProfilePack, active_profile_packs, build_context, load_profile_packs
from .quality import assess_quality, guard_items
from .questions import build_questions
from .references import build_references
from .rules import build_possible_rules
from .temporal import build_temporal_qualifiers
from .units import build_domain_terms, build_semantic_types
from .versioning import ENRICHMENT_SCHEMA_VERSION, ENRICHMENT_VERSION, POLICY_VERSION


@dataclass(frozen=True)
class EnrichmentLimits:
    """Topes configurables: el enrichment nunca explota en volumen."""

    max_concepts: int = 200
    max_aliases: int = 400
    max_identifiers: int = 300
    max_domain_terms: int = 200
    max_temporal: int = 200
    max_references: int = 200
    max_rules: int = 80
    max_questions: int = 120
    max_semantic_types: int = 300
    max_aliases_per_concept: int = 6


def limits_from_settings() -> EnrichmentLimits:
    try:
        from src.core.config import get_settings

        settings = get_settings()
    except Exception:  # noqa: BLE001
        return EnrichmentLimits()
    return EnrichmentLimits(
        max_concepts=int(getattr(settings, "KNOWLEDGE_ENRICHMENT_MAX_CONCEPTS", 200) or 200),
        max_aliases=int(getattr(settings, "KNOWLEDGE_ENRICHMENT_MAX_ALIASES", 400) or 400),
        max_identifiers=int(getattr(settings, "KNOWLEDGE_ENRICHMENT_MAX_IDENTIFIERS", 300) or 300),
        max_domain_terms=int(getattr(settings, "KNOWLEDGE_ENRICHMENT_MAX_DOMAIN_TERMS", 200) or 200),
        max_temporal=int(getattr(settings, "KNOWLEDGE_ENRICHMENT_MAX_TEMPORAL", 200) or 200),
        max_questions=int(getattr(settings, "KNOWLEDGE_ENRICHMENT_MAX_QUESTIONS", 120) or 120),
        max_rules=int(getattr(settings, "KNOWLEDGE_ENRICHMENT_MAX_RULES", 80) or 80),
    )


def enrich_document(
    document: StructuredDocument,
    *,
    packs: Iterable[EnrichmentProfilePack] | None = None,
    limits: EnrichmentLimits | None = None,
    model_items: Iterable[EnrichmentItem] | None = None,
) -> SemanticEnrichmentResult:
    """Documento entendido -> señal derivada trazable. Nunca I/O, nunca evidencia."""
    started = time.perf_counter()
    limits = limits or limits_from_settings()
    if packs is None:
        load_profile_packs()
        packs = active_profile_packs()
    context = build_context(document, packs=packs)

    # Guard universal: TODO item derivado (determinista o modelo) necesita
    # provenance real hacia unidades del documento. Un item huérfano se
    # descarta y se contabiliza; jamás llega al índice ni a la metadata.
    rejected = 0
    unknown_units = 0
    prohibited = 0

    def _guard(category: tuple) -> tuple:
        nonlocal rejected, unknown_units, prohibited
        outcome = guard_items(context, tuple(category))
        rejected += outcome.rejected
        unknown_units += outcome.unknown_source_units
        prohibited += outcome.prohibited
        return outcome.items

    concepts = _guard(build_concepts(context)[: limits.max_concepts])
    aliases = _guard(
        build_aliases(
            context,
            concepts,
            max_per_concept=limits.max_aliases_per_concept,
            max_total=limits.max_aliases,
        )
    )
    acronyms = _guard(build_acronyms(context, concepts, max_total=limits.max_aliases))
    identifiers = _guard(build_identifiers(context, max_total=limits.max_identifiers))
    identifier_alias_list = _guard(
        identifier_aliases(identifiers, max_total=limits.max_aliases)
    )
    domain_terms = _guard(build_domain_terms(context, max_total=limits.max_domain_terms))
    semantic_types = _guard(
        build_semantic_types(
            concepts, domain_terms, max_total=limits.max_semantic_types
        )
    )
    temporal = _guard(
        build_temporal_qualifiers(context, max_total=limits.max_temporal)
    )
    references = _guard(build_references(context, max_total=limits.max_references))
    rules = _guard(build_possible_rules(context, max_total=limits.max_rules))
    questions = _guard(
        build_questions(
            context,
            concepts,
            rules,
            temporal,
            max_total=limits.max_questions,
        )
    )

    # Model items (opcionales): entran por el MISMO guard de procedencia.
    model_concepts: list[SemanticConcept] = []
    model_aliases: list[RetrievalAlias] = []
    if model_items:
        guarded = guard_items(context, tuple(model_items))
        rejected += guarded.rejected
        unknown_units += guarded.unknown_source_units
        prohibited += guarded.prohibited
        for item in guarded.items:
            if isinstance(item, SemanticConcept):
                model_concepts.append(item)
            elif isinstance(item, RetrievalAlias):
                model_aliases.append(item)

    if model_concepts:
        concepts = tuple(list(concepts) + model_concepts[: limits.max_concepts])
    retrieval_aliases = _dedupe_aliases(
        (*aliases, *acronyms, *identifier_alias_list, *model_aliases),
        limit=limits.max_aliases,
    )
    # Los aliases aceptados se reflejan dentro del concepto (señal completa:
    # canonical + variants + provenance en un solo objeto auditable).
    concepts = _attach_aliases(concepts, retrieval_aliases)

    elapsed = time.perf_counter() - started
    enrichment_version = _version_with_packs(context.packs)
    statistics = EnrichmentStatistics(
        units_total=len(context.unit_ids),
        concepts=len(concepts),
        aliases=len(aliases),
        identifiers=len(identifiers),
        domain_terms=len(domain_terms),
        temporal_qualifiers=len(temporal),
        references=len(references),
        possible_rules=len(rules),
        retrieval_aliases=len(retrieval_aliases),
        synthetic_questions=len(questions),
        semantic_types=len(semantic_types),
        deterministic_items=(
            len(concepts)
            + len(aliases)
            + len(acronyms)
            + len(identifiers)
            + len(domain_terms)
            + len(temporal)
            + len(references)
            + len(rules)
            + len(questions)
        ),
        model_items=len(model_concepts) + len(model_aliases),
        rejected_items=rejected,
        seconds=round(elapsed, 6),
    )
    all_items = (
        *concepts,
        *aliases,
        *acronyms,
        *identifiers,
        *domain_terms,
        *temporal,
        *references,
        *rules,
        *retrieval_aliases,
        *questions,
        *semantic_types,
    )
    quality = assess_quality(
        all_items,
        rejected=rejected,
        unknown_source_units=unknown_units,
        prohibited=prohibited,
        warnings=(
            ("items_rejected_for_provenance",) if rejected else ()
        ),
    )
    result = SemanticEnrichmentResult(
        organization_id=document.organization_id,
        document_id=document.id,
        source_id=document.source_id,
        workspace_id=document.workspace_id,
        language=document.language,
        enrichment_version=enrichment_version,
        schema_version=ENRICHMENT_SCHEMA_VERSION,
        policy_version=POLICY_VERSION,
        concepts=tuple(concepts),
        aliases=tuple(aliases),
        identifiers=tuple(identifiers),
        domain_terms=tuple(domain_terms),
        temporal_qualifiers=tuple(temporal),
        references=tuple(references),
        possible_rules=tuple(rules),
        retrieval_aliases=tuple(retrieval_aliases),
        synthetic_questions=tuple(questions),
        semantic_types=tuple(semantic_types),
        statistics=statistics,
        quality=quality,
        source_provenance={
            "document_id": str(document.id),
            "source_id": str(document.source_id) if document.source_id else None,
            "content_hash": document.content_hash,
            "parser_version": (document.metadata.get("understanding") or {}).get("parser_version"),
            "enrichment_policy": POLICY_VERSION,
        },
    )
    observe_enrichment(document.organization_id, result)
    return result


def _version_with_packs(packs) -> str:
    """Versión de enrichment + firma de packs activos.

    Cambiar un pack (o su versión) cambia el fingerprint de representación:
    el índice stale se re-materializa sin reprocesar la fuente.
    """
    signature = ";".join(sorted(f"{pack.name}:{pack.version}" for pack in packs))
    digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:8]
    return f"{ENRICHMENT_VERSION}+{digest}"


def _dedupe_aliases(
    aliases: Iterable[RetrievalAlias],
    *,
    limit: int,
) -> tuple[RetrievalAlias, ...]:
    seen: dict[str, RetrievalAlias] = {}
    for alias in aliases:
        key = " ".join(alias.value.split()).casefold()
        if not key:
            continue
        existing = seen.get(key)
        if existing is None or alias.confidence > existing.confidence:
            seen[key] = alias
    ordered = sorted(seen.values(), key=lambda item: (-item.confidence, item.value.casefold()))
    return tuple(ordered[:limit])


def _attach_aliases(
    concepts: tuple[SemanticConcept, ...],
    aliases: tuple[RetrievalAlias, ...],
) -> tuple[SemanticConcept, ...]:
    """Adjunta a cada concepto sus aliases aceptados (inmutable, sin duplicar)."""
    from dataclasses import replace

    by_concept: dict[str, list[str]] = {}
    for alias in aliases:
        if not alias.target_concept_id:
            continue
        by_concept.setdefault(alias.target_concept_id, []).append(alias.value)
    if not by_concept:
        return concepts
    result: list[SemanticConcept] = []
    for concept in concepts:
        extra = by_concept.get(concept.concept_id)
        if not extra:
            result.append(concept)
            continue
        merged = tuple(
            dict.fromkeys(
                (*concept.aliases, *(value for value in extra if value != concept.canonical_name))
            )
        )
        result.append(replace(concept, aliases=merged))
    return tuple(result)
