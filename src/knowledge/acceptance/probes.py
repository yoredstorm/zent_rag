# =============================================================================
# Acceptance — generación determinista de probes
# =============================================================================
# Cada probe apunta a evidencia concreta (documento/sección/unidad). Se generan
# desde el enrichment y las preguntas sintéticas; NO desde LLM. Dedupe por
# query normalizada y tope por documento.
# =============================================================================
from __future__ import annotations

from src.core.domain.knowledge_v2 import StructuredDocument
from src.knowledge.enrichment.contracts import SemanticEnrichmentResult

from .contracts import (
    GENERATOR_VERSION,
    PROBE_POLICY_VERSION,
    RetrievalProbe,
    probe_id_for,
)


def _unit_section(document: StructuredDocument, unit_id: str | None) -> str | None:
    if not unit_id:
        return None
    for section in document.sections:
        if str(section.id) == unit_id:
            return str(section.id)
        if any(str(block_id) == unit_id for block_id in section.block_ids):
            return str(section.id)
    return None


def generate_probes(
    document: StructuredDocument,
    enrichment: SemanticEnrichmentResult | None,
    *,
    max_probes: int = 24,
) -> tuple[RetrievalProbe, ...]:
    """Probes representativos por tipo, con evidencia esperada real."""
    if enrichment is None or max_probes <= 0:
        return ()

    per_type: dict[str, int] = {}
    limits = {
        "exact_identifier": max(4, max_probes // 4),
        "alias": max(4, max_probes // 4),
        "definition": max(3, max_probes // 6),
        "semantic_paraphrase": max(3, max_probes // 5),
        "section_question": max(2, max_probes // 8),
        "relation_question": max(2, max_probes // 8),
        "temporal_question": 2,
    }
    seen: set[str] = set()
    probes: list[RetrievalProbe] = []

    def add(
        query: str,
        query_type: str,
        *,
        unit_id: str | None,
        section_id: str | None = None,
        entity_ids: tuple[str, ...] = (),
        semantic_unit_id: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        if len(probes) >= max_probes:
            return
        if per_type.get(query_type, 0) >= limits.get(query_type, 4):
            return
        cleaned = " ".join(str(query or "").split())
        if not cleaned or len(cleaned) > 200:
            return
        key = cleaned.casefold()
        if key in seen:
            return
        seen.add(key)
        per_type[query_type] = per_type.get(query_type, 0) + 1
        probes.append(
            RetrievalProbe(
                probe_id=probe_id_for(document.id, cleaned, query_type),
                organization_id=document.organization_id,
                document_id=document.id,
                workspace_id=document.workspace_id,
                source_id=document.source_id,
                query=cleaned,
                query_type=query_type,
                semantic_unit_id=semantic_unit_id or unit_id,
                expected_document_id=str(document.id),
                expected_section_id=section_id or _unit_section(document, unit_id),
                expected_unit_id=unit_id,
                expected_entity_ids=entity_ids,
                generated_by="semantic_enrichment",
                generator_version=GENERATOR_VERSION,
                policy_version=PROBE_POLICY_VERSION,
                metadata=dict(metadata or {}),
            )
        )

    # 1. Identificadores exactos (wording literal que un usuario tipea).
    for identifier in enrichment.identifiers:
        unit = identifier.source_unit_ids[0] if identifier.source_unit_ids else None
        add(
            identifier.value,
            "exact_identifier",
            unit_id=unit,
            entity_ids=(identifier.identifier_type,),
            metadata={"identifier_type": identifier.identifier_type},
        )

    # 2. Aliases/acrónimos de conceptos.
    concept_by_id = enrichment.concepts_by_id()
    for alias in enrichment.retrieval_aliases:
        concept = concept_by_id.get(alias.target_concept_id or "")
        unit = (concept.source_unit_ids[0] if concept and concept.source_unit_ids else None) or (
            alias.source_unit_ids[0] if alias.source_unit_ids else None
        )
        add(alias.value, "alias", unit_id=unit, metadata={"alias_kind": alias.kind})

    # 3. Preguntas sintéticas por tipo.
    for question in enrichment.synthetic_questions:
        unit = question.source_unit_id or (
            question.source_unit_ids[0] if question.source_unit_ids else None
        )
        add(
            question.question,
            question.query_type,
            unit_id=unit,
            section_id=question.expected_section_id,
            semantic_unit_id=question.source_unit_id or None,
        )

    # 4. Columnas tabulares: nombre + valor de ejemplo (búsqueda de dato).
    for concept in enrichment.concepts:
        if not concept.semantic_type.startswith("column:") or not concept.identifiers:
            continue
        add(
            f"{concept.canonical_name} {concept.identifiers[0]}",
            "table_lookup",
            unit_id=None,
            metadata={"column_concept_id": concept.concept_id},
        )

    # Orden estable: por tipo (documentado) y por query.
    type_order = {
        "exact_identifier": 0,
        "alias": 1,
        "table_lookup": 2,
        "definition": 3,
        "semantic_paraphrase": 4,
        "section_question": 5,
        "relation_question": 6,
        "temporal_question": 7,
    }
    probes.sort(key=lambda probe: (type_order.get(probe.query_type, 99), probe.query.casefold()))
    return tuple(probes[:max_probes])
