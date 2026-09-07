# =============================================================================
# Semantic Compiler — Phase 26B Business Semantic AST
# =============================================================================
# Question → Understanding → Concept classification → Business AST →
# physical resolution against approved definitions (never invent SQL joins).
# =============================================================================
from __future__ import annotations

from typing import Iterable

from src.core.domain.intelligence import BusinessDefinition, QueryUnderstanding
from src.core.domain.semantic import (
    BusinessObjectType,
    BusinessSemanticAST,
    SemanticCompileResult,
    SemanticGapCode,
)

_INTENT_QUERY_TYPE: dict[str, str] = {
    "business_metric": "metric_query",
    "document_policy": "document_query",
    "operational_status": "operational_query",
    "concept_definition": "definition_query",
    "general": "general_query",
}

_METRIC_TYPES = frozenset(
    {
        BusinessObjectType.DERIVED_METRIC,
        BusinessObjectType.MEASURE,
    }
)


def _as_type(raw: str | None) -> BusinessObjectType | None:
    if not raw:
        return None
    try:
        return BusinessObjectType(raw)
    except ValueError:
        return None


class SemanticCompiler:
    """Compile QueryUnderstanding into a Business Semantic AST + resolve IR."""

    def compile(
        self,
        understanding: QueryUnderstanding,
        *,
        query: str = "",
        definitions: Iterable[BusinessDefinition] | None = None,
    ) -> SemanticCompileResult:
        del query  # reserved for future time/entity parsing from text
        approved = {
            d.concept.strip().lower(): d
            for d in (definitions or [])
            if d.status == "approved"
        }
        concept_types = dict(understanding.concept_types or {})
        resolved_map = dict(understanding.resolved_concepts or {})

        metrics: list[dict] = []
        facts: list[str] = []
        dimensions: list[str] = []
        segments: list[str] = []
        filters: list[dict] = []

        for concept in understanding.concepts or []:
            key = concept.strip().lower()
            obj_type = _as_type(concept_types.get(key))
            if obj_type in _METRIC_TYPES:
                version = None
                if key in approved:
                    version = approved[key].version
                metrics.append({"name": key, "version": version})
            elif obj_type == BusinessObjectType.FACT:
                facts.append(key)
            elif obj_type == BusinessObjectType.DIMENSION:
                dimensions.append(key)
            elif obj_type == BusinessObjectType.SEGMENT:
                segments.append(key)
            elif obj_type == BusinessObjectType.FILTER:
                filters.append({"name": key})

        # Named entity mentions from understanding (not physical keys)
        entities: list[dict] = []
        for value in understanding.entities or []:
            entities.append({"type": "entity", "value": value})
        for concept in understanding.concepts or []:
            key = concept.strip().lower()
            if _as_type(concept_types.get(key)) == BusinessObjectType.ENTITY:
                if not any(e.get("value", "").lower() == key for e in entities):
                    entities.append({"type": "entity", "value": key})

        time: dict = {}
        if understanding.time_scope:
            time = {"scope": understanding.time_scope}

        if understanding.ambiguity:
            # Ambiguity is recorded on AST path via unresolved AMBIGUOUS later
            pass

        ast = BusinessSemanticAST(
            query_type=_INTENT_QUERY_TYPE.get(
                understanding.intent, "general_query"
            ),
            metrics=metrics,
            entities=entities,
            segments=segments,
            dimensions=dimensions,
            filters=filters,
            time=time,
            facts=facts,
            concept_types=concept_types,
        )

        resolved_objects: list[dict] = []
        unresolved_objects: list[dict] = []
        physical_candidates: list[dict] = []
        required_metrics = [m["name"] for m in metrics]
        required_sources: list[str] = []
        required_relationships: list[str] = []
        warnings: list[str] = []

        # Resolve definitional concepts only — ENTITY/FACT never force CONTEXT_MISSING
        definitional = list(understanding.requires_definition or [])
        for name in definitional:
            key = name.strip().lower()
            obj_type = _as_type(concept_types.get(key))
            is_resolved = bool(resolved_map.get(key)) or key in approved
            if is_resolved:
                definition = approved.get(key)
                entry = {
                    "name": key,
                    "object_type": (
                        obj_type.value if obj_type else BusinessObjectType.BUSINESS_TERM.value
                    ),
                    "definition_id": str(definition.id) if definition else None,
                    "version": definition.version if definition else None,
                }
                resolved_objects.append(entry)
                if definition and definition.authoritative_source_id:
                    required_sources.append(definition.authoritative_source_id)
                if definition and definition.expression:
                    # Candidate from approved expression only — never invent tables
                    physical_candidates.append(
                        {
                            "concept": key,
                            "source": "definition_expression",
                            "expression": definition.expression,
                        }
                    )
                elif definition:
                    physical_candidates.append(
                        {
                            "concept": key,
                            "source": "definition",
                            "definition": definition.definition[:240],
                        }
                    )
            else:
                unresolved_objects.append(
                    {
                        "name": key,
                        "object_type": (
                            obj_type.value
                            if obj_type
                            else BusinessObjectType.BUSINESS_TERM.value
                        ),
                        "code": SemanticGapCode.CONTEXT_MISSING.value,
                        "message": (
                            f"No approved business definition for '{key}'"
                        ),
                    }
                )

        if understanding.ambiguity:
            unresolved_objects.append(
                {
                    "name": "_query",
                    "object_type": BusinessObjectType.BUSINESS_TERM.value,
                    "code": SemanticGapCode.AMBIGUOUS.value,
                    "message": understanding.clarifying_question
                    or "Query is ambiguous",
                }
            )

        # Deduplicate sources
        required_sources = list(dict.fromkeys(required_sources))

        if unresolved_objects and any(
            u.get("code") == SemanticGapCode.CONTEXT_MISSING.value
            for u in unresolved_objects
        ):
            warnings.append(
                "Essential semantic objects unresolved — refuse invented physical relationships"
            )

        return SemanticCompileResult(
            semantic_ast=ast,
            resolved_objects=resolved_objects,
            unresolved_objects=unresolved_objects,
            physical_candidates=physical_candidates,
            required_sources=required_sources,
            required_metrics=required_metrics,
            required_relationships=required_relationships,
            warnings=warnings,
        )
