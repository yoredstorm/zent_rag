# =============================================================================
# Knowledge Compiler — FACT EXTRACTION y RELATIONSHIP DISCOVERY
# =============================================================================
# Un hecho es atómico: (sujeto, predicado, objeto) con evidencia. No hay hecho
# sin evidencia. Las relaciones del grafo se derivan de los mismos hechos y de
# los enlaces estructurales, con tipo, confianza y evidencia — nunca inventadas.
# =============================================================================
from __future__ import annotations

from src.knowledge.compiler.model import (
    EntityCandidate,
    FactCandidate,
    FactKind,
    RelationshipCandidate,
    RelationshipKind,
    SemanticUnit,
    SemanticUnitKind,
    TemporalScope,
    normalize_term,
)

_RELATION_PREDICATE = {
    "HAS_PATTERN": RelationshipKind.HAS_PATTERN.value,
    "HAS_NOTE": RelationshipKind.HAS_NOTE.value,
    "HAS_EXAMPLE": RelationshipKind.HAS_EXAMPLE.value,
    "HAS_WARNING": RelationshipKind.HAS_WARNING.value,
    "REFERENCES": RelationshipKind.REFERENCES.value,
    "XREF": RelationshipKind.REFERENCES.value,
    "PART_OF": RelationshipKind.PART_OF.value,
    "CONTAINS": RelationshipKind.CONTAINS.value,
}


def _index_units(units: list[SemanticUnit]) -> dict[str, SemanticUnit]:
    return {f"{unit.kind}:{normalize_term(unit.label)}": unit for unit in units}


def build_facts(
    units: list[SemanticUnit],
    *,
    temporal: TemporalScope | None = None,
) -> list[FactCandidate]:
    """Hechos deterministas extraídos de las unidades semánticas."""
    scope = temporal or TemporalScope()
    facts: list[FactCandidate] = []
    for unit in units:
        if unit.kind == SemanticUnitKind.DEFINITION.value:
            facts.append(
                FactCandidate(
                    subject=unit.label,
                    predicate="defined_as",
                    object_value=unit.text,
                    fact_kind=FactKind.DEFINITION.value,
                    method="document",
                    confidence=unit.confidence,
                    temporal=scope,
                    evidence=[unit.evidence],
                )
            )
            continue
        if unit.kind == SemanticUnitKind.FIELD.value:
            attributes = unit.attributes
            if attributes.get("start_position") is not None:
                facts.append(
                    FactCandidate(
                        subject=unit.label,
                        predicate="starts_at_position",
                        object_value=str(attributes["start_position"]),
                        fact_kind=FactKind.STRUCTURAL.value,
                        method="document",
                        confidence=unit.confidence,
                        temporal=scope,
                        evidence=[unit.evidence],
                    )
                )
            if attributes.get("length") is not None:
                facts.append(
                    FactCandidate(
                        subject=unit.label,
                        predicate="has_length",
                        object_value=str(attributes["length"]),
                        fact_kind=FactKind.STRUCTURAL.value,
                        method="document",
                        confidence=unit.confidence,
                        temporal=scope,
                        evidence=[unit.evidence],
                    )
                )
            if attributes.get("literal_pattern"):
                facts.append(
                    FactCandidate(
                        subject=unit.label,
                        predicate="has_pattern",
                        object_value=str(attributes["literal_pattern"]),
                        fact_kind=FactKind.STRUCTURAL.value,
                        method="document",
                        confidence=unit.confidence,
                        temporal=scope,
                        evidence=[unit.evidence],
                    )
                )
            if unit.text:
                facts.append(
                    FactCandidate(
                        subject=unit.label,
                        predicate="described_as",
                        object_value=unit.text,
                        fact_kind=FactKind.FIELD_MEANING.value,
                        method="document",
                        confidence=unit.confidence,
                        temporal=scope,
                        evidence=[unit.evidence],
                    )
                )
            continue
        if unit.kind == SemanticUnitKind.COLUMN.value:
            table_reference = str(unit.attributes.get("table") or "").strip()
            if table_reference:
                facts.append(
                    FactCandidate(
                        subject=unit.label,
                        predicate="belongs_to_table",
                        object_value=table_reference,
                        fact_kind=FactKind.STRUCTURAL.value,
                        method="schema",
                        confidence=unit.confidence,
                        temporal=scope,
                        attributes={"table": table_reference},
                        evidence=[unit.evidence],
                    )
                )
            position = unit.attributes.get("position")
            if position is not None:
                facts.append(
                    FactCandidate(
                        subject=unit.label,
                        predicate="has_position",
                        object_value=str(position),
                        fact_kind=FactKind.STRUCTURAL.value,
                        method="schema",
                        confidence=unit.confidence,
                        temporal=scope,
                        attributes={"table": table_reference},
                        evidence=[unit.evidence],
                    )
                )
            for attribute, predicate in (
                ("inferred_type", "has_type"),
                ("semantic_type", "has_semantic_type"),
                ("excel_letter", "has_excel_letter"),
            ):
                value = unit.attributes.get(attribute)
                if value and value != "unknown":
                    facts.append(
                        FactCandidate(
                            subject=unit.label,
                            predicate=predicate,
                            object_value=str(value),
                            fact_kind=FactKind.STRUCTURAL.value,
                            method="schema",
                            confidence=unit.confidence,
                            temporal=scope,
                            attributes={"table": table_reference},
                            evidence=[unit.evidence],
                        )
                    )
            continue
        if unit.kind == SemanticUnitKind.TABLE.value:
            row_count = unit.attributes.get("row_count")
            column_count = unit.attributes.get("column_count")
            if row_count is not None:
                facts.append(
                    FactCandidate(
                        subject=unit.label,
                        predicate="has_row_count",
                        object_value=str(row_count),
                        fact_kind=FactKind.STRUCTURAL.value,
                        method="schema",
                        confidence=unit.confidence,
                        temporal=scope,
                        evidence=[unit.evidence],
                    )
                )
            if column_count is not None:
                facts.append(
                    FactCandidate(
                        subject=unit.label,
                        predicate="has_column_count",
                        object_value=str(column_count),
                        fact_kind=FactKind.STRUCTURAL.value,
                        method="schema",
                        confidence=unit.confidence,
                        temporal=scope,
                        evidence=[unit.evidence],
                    )
                )
            continue
        if unit.kind == SemanticUnitKind.REFERENCE.value:
            target = str(unit.attributes.get("target") or unit.label).strip()
            facts.append(
                FactCandidate(
                    subject=unit.label,
                    predicate="referenced_by",
                    object_value=unit.text or target,
                    fact_kind=FactKind.REFERENCE.value,
                    method="document",
                    confidence=unit.confidence,
                    temporal=scope,
                    evidence=[unit.evidence],
                )
            )
    return facts


def build_relationships(
    units: list[SemanticUnit],
    *,
    document_title: str,
    extracted_relations: list[dict] | None = None,
) -> list[RelationshipCandidate]:
    """Aristas del grafo: estructura (tabla/columna) + enlaces del documento."""
    units_by_block: dict[str, list[SemanticUnit]] = {}
    for unit in units:
        block_id = unit.evidence.locator.block_id
        if block_id is not None:
            units_by_block.setdefault(str(block_id), []).append(unit)

    relationships: list[RelationshipCandidate] = []
    seen: set[tuple[str, str, str]] = set()

    def add(relationship: RelationshipCandidate) -> None:
        key = (
            normalize_term(relationship.subject),
            relationship.predicate,
            normalize_term(relationship.object_name),
        )
        if key in seen:
            return
        seen.add(key)
        relationships.append(relationship)

    for unit in units:
        if unit.kind != SemanticUnitKind.COLUMN.value:
            continue
        table_reference = str(unit.attributes.get("table") or "").strip()
        if not table_reference:
            continue
        add(
            RelationshipCandidate(
                subject=unit.label,
                predicate="part_of",
                object_name=table_reference,
                relationship_type="structural",
                confidence=unit.confidence,
                evidence=[unit.evidence],
            )
        )

    for relation in extracted_relations or []:
        predicate = _RELATION_PREDICATE.get(
            str(relation.get("relation_type") or "").upper()
        )
        if predicate is None:
            continue
        block_id = relation.get("from_block_id")
        owners = units_by_block.get(str(block_id), []) if block_id else []
        subject = (
            str(relation.get("field_name") or "").strip()
            or (owners[0].label if owners else "")
            or document_title
        )
        target = (
            str(relation.get("target_literal") or "").strip()
            or str(relation.get("target") or "").strip()
            or str(relation.get("note") or "").strip()
        )
        if not target:
            continue
        evidence = owners[0].evidence if owners else None
        if evidence is None:
            continue
        add(
            RelationshipCandidate(
                subject=subject,
                predicate=predicate,
                object_name=target[:200],
                relationship_type="document",
                confidence=float(relation.get("confidence") or 0.7),
                evidence=[evidence],
            )
        )

    return relationships


def entity_facts(
    entities: list[EntityCandidate], *, temporal: TemporalScope | None = None
) -> list[FactCandidate]:
    """Hechos de identidad: descripción y tipo declarados por la fuente.

    Los alias NO se convierten en hechos ``also_known_as``: la identidad
    multi-alias vive en ``knowledge_entity_aliases``. Convertirlos en hechos
    producía "conflictos" entre alias legítimos del mismo canónico.
    """
    scope = temporal or TemporalScope()
    facts: list[FactCandidate] = []
    for entity in entities:
        if entity.description:
            facts.append(
                FactCandidate(
                    subject=entity.name,
                    predicate="described_as",
                    object_value=entity.description,
                    subject_type=entity.entity_type,
                    fact_kind=FactKind.DEFINITION.value,
                    method="document",
                    confidence=entity.confidence,
                    temporal=scope,
                    evidence=list(entity.evidence[:3]),
                )
            )
    return facts
