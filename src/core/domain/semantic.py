# =============================================================================
# Domain — Business semantic object types (Phase 26A)
# =============================================================================
# Formal taxonomy so LLM-extracted nouns do not automatically require a
# business definition. Only DEFINITIONAL_TYPES drive CONTEXT_MISSING.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


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


@dataclass(frozen=True, slots=True)
class ClassifiedConcept:
    """A concept token with its business-object type."""

    concept: str
    object_type: BusinessObjectType

    @property
    def requires_definition(self) -> bool:
        return self.object_type in DEFINITIONAL_TYPES
