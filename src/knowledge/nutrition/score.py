# =============================================================================
# Knowledge Nutrition — score multidimensional
# =============================================================================
# Un solo número ciego no sirve. Se persisten dimensiones; las no medidas
# quedan en None (jamás 0). El score final pondera SOLO lo medido con pesos
# documentados y versionados.
#
#   nutrition_score = Σ(w_i * d_i) / Σ(w_i)  para d_i medido
# =============================================================================
from __future__ import annotations

from src.core.domain.knowledge_v2 import StructuredDocument
from src.knowledge.acceptance.contracts import AcceptanceReport
from src.knowledge.enrichment.contracts import SemanticEnrichmentResult

from .contracts import (
    NUTRITION_SCORE_VERSION,
    NUTRITION_WEIGHTS,
    NutritionDimensions,
    NutritionScore,
)


def compute_nutrition_score(
    document: StructuredDocument,
    *,
    enrichment: SemanticEnrichmentResult | None = None,
    compiled=None,
    acceptance: AcceptanceReport | None = None,
    demand_coverage: float | None = None,
    freshness: float | None = None,
    scope: str = "document",
    scope_id: str | None = None,
    details: dict | None = None,
) -> NutritionScore:
    """Dimensiones medidas desde artefactos reales; None si no hay medición."""
    understanding = document.metadata.get("understanding") or {}
    quality = understanding.get("quality") or {}
    reconstruction = document.metadata.get("semantic_reconstruction") or {}
    reconstruction_quality = (reconstruction.get("quality") or {}).get("score")

    structure_quality = _bounded(quality.get("overall_score"))
    if structure_quality is None:
        structure_quality = _bounded(quality.get("structure_confidence"))
    if structure_quality is None and (understanding or reconstruction):
        structure_quality = _bounded((quality.get("dimensions") or {}).get("structure_confidence"))

    semantic_coverage = None
    if enrichment is not None and enrichment.statistics.units_total:
        covered = sum(1 for item in enrichment.items() if item.source_unit_ids)
        semantic_coverage = _bounded(covered / max(enrichment.statistics.units_total, 1))

    evidence_coverage = None
    entity_linkage = None
    relationship_coverage = None
    temporal_quality = None
    if compiled is not None:
        entities = list(getattr(compiled, "entities", ()) or ())
        facts = list(getattr(compiled, "facts", ()) or ())
        rules = list(getattr(compiled, "rules", ()) or ())
        relationships = list(getattr(compiled, "relationships", ()) or ())
        with_evidence = sum(
            1
            for item in (*entities, *facts, *rules)
            if getattr(item, "evidence", None)
        )
        total_items = len(entities) + len(facts) + len(rules)
        evidence_coverage = _bounded(with_evidence / total_items) if total_items else None
        entity_linkage = (
            _bounded(
                sum(1 for entity in entities if getattr(entity, "evidence", None))
                / len(entities)
            )
            if entities
            else None
        )
        relationship_coverage = (
            _bounded(len(relationships) / max(len(entities), 1)) if entities else None
        )
        temporal_facts = sum(
            1
            for fact in facts
            if getattr(fact, "valid_from", None) or getattr(fact, "valid_to", None)
        )
        has_temporal_content = bool(temporal_facts) or bool(
            enrichment is not None and enrichment.temporal_qualifiers
        )
        if facts and has_temporal_content:
            temporal_quality = _bounded(temporal_facts / len(facts))
        else:
            # Sin contenido temporal en la fuente, la dimensión NO aplica:
            # None (no penalizar por algo que el documento no pretende tener).
            temporal_quality = None

    retrievability = None
    if acceptance is not None and acceptance.probes_total:
        retrievability = _bounded(
            acceptance.recall_at_5 if acceptance.recall_at_5 is not None else None
        )

    dimensions = NutritionDimensions(
        structure_quality=structure_quality,
        reconstruction_quality=_bounded(reconstruction_quality),
        evidence_coverage=evidence_coverage,
        semantic_coverage=semantic_coverage,
        entity_linkage=entity_linkage,
        relationship_coverage=relationship_coverage,
        temporal_quality=temporal_quality,
        freshness=_bounded(freshness),
        retrievability=retrievability,
        demand_coverage=_bounded(demand_coverage),
    )
    measured = dimensions.measured()
    if measured:
        weighted = sum(
            NUTRITION_WEIGHTS.get(key, 0.0) * value for key, value in measured.items()
        )
        total_weight = sum(NUTRITION_WEIGHTS.get(key, 0.0) for key in measured)
        score = round(weighted / total_weight, 4) if total_weight > 0 else None
    else:
        score = None

    return NutritionScore(
        scope=scope,
        scope_id=scope_id or str(document.id),
        dimensions=dimensions,
        nutrition_score=score,
        formula_version=NUTRITION_SCORE_VERSION,
        weights=dict(NUTRITION_WEIGHTS),
        measured_dimensions=len(measured),
        total_dimensions=len(NUTRITION_WEIGHTS),
        details={
            "document_id": str(document.id),
            "content_hash": document.content_hash,
            **(details or {}),
        },
    )


def _bounded(value) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, number))
