# =============================================================================
# Domain — Business semantic types (Phase 26A/26B)
# =============================================================================
# Formal taxonomy so LLM-extracted nouns do not automatically require a
# business definition. Only DEFINITIONAL_TYPES drive CONTEXT_MISSING.
# Phase 26B adds Business Semantic AST + compile IR (no physical tables in AST).
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class BusinessObjectType(StrEnum):
    """Formal business-object kinds for semantic classification."""

    ENTITY = "ENTITY"
    FACT = "FACT"
    DIMENSION = "DIMENSION"
    MEASURE = "MEASURE"
    DERIVED_METRIC = "DERIVED_METRIC"
    BUSINESS_TERM = "BUSINESS_TERM"
    BUSINESS_RULE = "BUSINESS_RULE"
    ENUM = "ENUM"
    TIME_DIMENSION = "TIME_DIMENSION"
    CURRENCY = "CURRENCY"
    UNIT = "UNIT"
    SEGMENT = "SEGMENT"
    FILTER = "FILTER"


DEFINITIONAL_TYPES: frozenset[BusinessObjectType] = frozenset(
    {
        BusinessObjectType.DERIVED_METRIC,
        BusinessObjectType.BUSINESS_TERM,
        BusinessObjectType.BUSINESS_RULE,
        BusinessObjectType.SEGMENT,
    }
)


class SemanticGapCode(StrEnum):
    """Gap codes when semantic compilation cannot resolve essential meaning."""

    CONTEXT_MISSING = "CONTEXT_MISSING"
    DATA_MISSING = "DATA_MISSING"
    MISSING_RELATIONSHIP = "MISSING_RELATIONSHIP"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True, slots=True)
class ClassifiedConcept:
    """A concept token with its business-object type."""

    concept: str
    object_type: BusinessObjectType

    @property
    def requires_definition(self) -> bool:
        return self.object_type in DEFINITIONAL_TYPES


@dataclass(kw_only=True)
class BusinessSemanticAST:
    """Intermediate business representation — no physical table/column names."""

    query_type: str = "general_query"
    metrics: list[dict[str, Any]] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    segments: list[str] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)
    filters: list[dict[str, Any]] = field(default_factory=list)
    time: dict[str, Any] = field(default_factory=dict)
    facts: list[str] = field(default_factory=list)
    concept_types: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_type": self.query_type,
            "metrics": list(self.metrics),
            "entities": list(self.entities),
            "segments": list(self.segments),
            "dimensions": list(self.dimensions),
            "filters": list(self.filters),
            "time": dict(self.time),
            "facts": list(self.facts),
            "concept_types": dict(self.concept_types),
        }


@dataclass(kw_only=True)
class SemanticCompileResult:
    """IR handed to the Query Planner after semantic compilation."""

    semantic_ast: BusinessSemanticAST = field(default_factory=BusinessSemanticAST)
    resolved_objects: list[dict[str, Any]] = field(default_factory=list)
    unresolved_objects: list[dict[str, Any]] = field(default_factory=list)
    physical_candidates: list[dict[str, Any]] = field(default_factory=list)
    required_sources: list[str] = field(default_factory=list)
    required_metrics: list[str] = field(default_factory=list)
    required_relationships: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_blocking_gaps(self) -> bool:
        return any(
            u.get("code")
            in (
                SemanticGapCode.CONTEXT_MISSING.value,
                SemanticGapCode.DATA_MISSING.value,
                SemanticGapCode.MISSING_RELATIONSHIP.value,
                SemanticGapCode.AMBIGUOUS.value,
            )
            for u in self.unresolved_objects
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "semantic_ast": self.semantic_ast.to_dict(),
            "resolved_objects": list(self.resolved_objects),
            "unresolved_objects": list(self.unresolved_objects),
            "physical_candidates": list(self.physical_candidates),
            "required_sources": list(self.required_sources),
            "required_metrics": list(self.required_metrics),
            "required_relationships": list(self.required_relationships),
            "warnings": list(self.warnings),
            "has_blocking_gaps": self.has_blocking_gaps,
        }
