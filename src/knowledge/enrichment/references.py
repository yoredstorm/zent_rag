# =============================================================================
# Enrichment — referencias cruzadas
# =============================================================================
# Reutiliza las cross_references del understanding (ver tabla X, sección Y).
# Una referencia NO resuelta queda como candidato (`resolved_target=None`):
# la duda es información, no se fuerza el link.
# =============================================================================
from __future__ import annotations

from src.knowledge.enrichment.contracts import SemanticReference
from src.knowledge.enrichment.profiling import EnrichmentContext
from src.knowledge.enrichment.versioning import POLICY_VERSION


def build_references(
    context: EnrichmentContext,
    *,
    max_total: int = 200,
) -> tuple[SemanticReference, ...]:
    found: dict[str, SemanticReference] = {}

    for reference in context.understanding.get("cross_references") or ():
        reference_text = " ".join(str(reference.get("reference_text") or "").split())
        if not reference_text:
            continue
        key = reference_text.casefold()
        if key in found:
            continue
        block_id = str(reference.get("from_block") or "")
        units = context.valid_units([block_id])
        found[key] = SemanticReference(
            reference_text=reference_text,
            target_kind=str(reference.get("target_kind") or "section"),
            target_candidate=str(reference.get("target_candidate") or ""),
            resolved_target=(
                str(reference["resolved_target"])
                if reference.get("resolved_target")
                else None
            ),
            source_unit_id=block_id,
            source_unit_ids=units,
            confidence=float(reference.get("confidence") or 0.6),
            derivation_method="deterministic",
            policy_version=POLICY_VERSION,
        )

    result = sorted(found.values(), key=lambda item: (-item.confidence, item.reference_text.casefold()))
    return tuple(result[:max_total])
