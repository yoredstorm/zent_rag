# =============================================================================
# Enrichment — quality gate
# =============================================================================
# Ley de procedencia: un item sin unidades fuente REALES del documento se
# elimina antes de tocar el índice o la metadata. `canonical=True` o
# `derived=False` están prohibidos en esta capa.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass

from src.knowledge.enrichment.contracts import (
    EnrichmentItem,
    EnrichmentQuality,
)
from src.knowledge.enrichment.profiling import EnrichmentContext


@dataclass(frozen=True)
class GuardOutcome:
    items: tuple[EnrichmentItem, ...]
    rejected: int
    unknown_source_units: int
    prohibited: int


def guard_items(
    context: EnrichmentContext,
    items: tuple[EnrichmentItem, ...],
) -> GuardOutcome:
    kept: list[EnrichmentItem] = []
    rejected = 0
    unknown = 0
    prohibited = 0
    for item in items:
        if item.canonical or not item.derived:
            prohibited += 1
            rejected += 1
            continue
        if not item.source_unit_ids:
            rejected += 1
            continue
        if not all(context.has_unit(unit) for unit in item.source_unit_ids):
            unknown += 1
            rejected += 1
            continue
        kept.append(item)
    return GuardOutcome(
        items=tuple(kept),
        rejected=rejected,
        unknown_source_units=unknown,
        prohibited=prohibited,
    )


def assess_quality(
    items: tuple[EnrichmentItem, ...],
    *,
    rejected: int = 0,
    unknown_source_units: int = 0,
    prohibited: int = 0,
    warnings: tuple[str, ...] = (),
) -> EnrichmentQuality:
    confidences = [float(item.confidence) for item in items]
    with_provenance = sum(1 for item in items if item.source_unit_ids)
    return EnrichmentQuality(
        items_total=len(items) + rejected,
        items_with_provenance=with_provenance,
        orphan_items=max(0, len(items) - with_provenance),
        unknown_source_units=unknown_source_units,
        prohibited_items=prohibited,
        average_confidence=(sum(confidences) / len(confidences)) if confidences else 0.0,
        min_confidence=min(confidences) if confidences else 0.0,
        max_confidence=max(confidences) if confidences else 0.0,
        warnings=warnings,
    )
