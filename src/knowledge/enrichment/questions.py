# =============================================================================
# Enrichment — preguntas sintéticas de retrieval
# =============================================================================
# Las preguntas NO son evidencia, NO son facts y NO se compilan: son aliases
# de retrieval. Generación por templates deterministas, deduplicadas y
# acotadas. El LLM (si algún día se habilita) solo expande, nunca inventa.
# =============================================================================
from __future__ import annotations

import re

from src.knowledge.enrichment.contracts import (
    PossibleRule,
    SemanticConcept,
    SyntheticQuestion,
    TemporalQualifier,
)
from src.knowledge.enrichment.normalize import collapse, normalize_key, title_first
from src.knowledge.enrichment.profiling import EnrichmentContext
from src.knowledge.enrichment.versioning import ENRICHMENT_VERSION, POLICY_VERSION

_STOP_TITLES = frozenset({"introduction", "overview", "summary", "contenido", "index", "notes"})


def _clean_subject(value: str, limit: int = 60) -> str:
    cleaned = collapse(value)
    return cleaned[:limit].strip()


def build_questions(
    context: EnrichmentContext,
    concepts: tuple[SemanticConcept, ...],
    rules: tuple[PossibleRule, ...],
    temporal: tuple[TemporalQualifier, ...],
    *,
    max_total: int = 120,
    max_per_concept: int = 3,
) -> tuple[SyntheticQuestion, ...]:
    document_id = str(context.document.id)
    section_by_block: dict[str, str] = {}
    for section in context.document.sections:
        for block_id in section.block_ids:
            section_by_block[str(block_id)] = str(section.id)

    found: dict[str, SyntheticQuestion] = {}
    counts: dict[str, int] = {}

    def add(
        question: str,
        query_type: str,
        *,
        units: tuple[str, ...],
        concept_id: str | None = None,
        confidence: float = 0.6,
    ) -> None:
        cleaned = collapse(question)
        if not cleaned or len(cleaned) > 220:
            return
        if len(found) >= max_total:
            return
        key = normalize_key(cleaned)
        if key in found:
            return
        section_id = ""
        for unit in units:
            section_id = section_by_block.get(unit, "")
            if section_id:
                break
        found[key] = SyntheticQuestion(
            question=cleaned,
            query_type=query_type,
            source_unit_id=units[0] if units else "",
            target_concept_id=concept_id,
            expected_document_id=document_id,
            expected_section_id=section_id or None,
            source_unit_ids=units,
            confidence=max(0.0, min(1.0, confidence)),
            derivation_method="deterministic",
            generator_version=ENRICHMENT_VERSION,
            policy_version=POLICY_VERSION,
        )

    # 1. Identificadores exactos: lo que un usuario tipearía tal cual.
    for concept in concepts:
        units = concept.source_unit_ids
        if not units:
            continue
        per_concept = 0
        for identifier in concept.identifiers[:3]:
            if per_concept >= max_per_concept:
                break
            identifier = _clean_subject(identifier, 40)
            if not identifier:
                continue
            if re.match(r"^bytes?\s", identifier, re.IGNORECASE):
                add(
                    f"What does {identifier} mean in {_clean_subject(concept.canonical_name)}?",
                    "exact_identifier",
                    units=units,
                    concept_id=concept.concept_id,
                    confidence=0.8,
                )
                add(
                    f"Which {_clean_subject(concept.canonical_name)} field is at {identifier}?",
                    "exact_identifier",
                    units=units,
                    concept_id=concept.concept_id,
                    confidence=0.7,
                )
            else:
                add(
                    f"What is {identifier}?",
                    "exact_identifier",
                    units=units,
                    concept_id=concept.concept_id,
                    confidence=0.75,
                )
            per_concept += 1
        # 2. Definición del concepto.
        if per_concept < max_per_concept:
            add(
                f"What is {_clean_subject(concept.canonical_name)}?",
                "definition",
                units=units,
                concept_id=concept.concept_id,
                confidence=0.68,
            )
            per_concept += 1
        # 3. Alias/acrónimo: pregunta por la variante.
        for alias in concept.aliases[:1]:
            if per_concept >= max_per_concept:
                break
            add(
                f"What does {_clean_subject(alias, 40)} refer to?",
                "alias",
                units=units,
                concept_id=concept.concept_id,
                confidence=0.55,
            )
            per_concept += 1

    # 4. Sección: pregunta amplia por cobertura (útil para parents).
    for section in context.document.sections:
        heading = _clean_subject(section.heading)
        if not heading or normalize_key(heading) in _STOP_TITLES:
            continue
        units = context.valid_units([str(section.id), *[str(block_id) for block_id in section.block_ids[:8]]])
        add(
            f"What does {title_first(heading)} cover?",
            "section_question",
            units=units,
            confidence=0.55,
        )

    # 5. Reglas posibles: condición/consecuencia.
    for rule in rules[:24]:
        subject = _clean_subject(rule.consequence or rule.statement, 80)
        if not subject:
            continue
        verb = "must" if "must" in rule.statement.lower() or "shall" in rule.statement.lower() else "can"
        add(
            f"When does the rule apply that {subject}?",
            "relation_question",
            units=rule.source_unit_ids,
            confidence=0.5,
        )
        add(
            f"What {verb} happen when {subject}?",
            "semantic_paraphrase",
            units=rule.source_unit_ids,
            confidence=0.45,
        )

    # 6. Temporal: vigencia asociada a las unidades del qualifier.
    for qualifier in temporal[:32]:
        if qualifier.qualifier_type == "format":
            continue
        value = _clean_subject(qualifier.value, 64)
        if not value:
            continue
        add(
            f"What is valid for {value}?",
            "temporal_question",
            units=qualifier.source_unit_ids,
            confidence=0.5,
        )

    result = sorted(found.values(), key=lambda item: (-item.confidence, item.question.casefold()))
    return tuple(result[:max_total])
