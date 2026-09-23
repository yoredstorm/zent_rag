# =============================================================================
# Company Discovery — Confidence scoring (§8)
# =============================================================================
# Regla: contar ocurrencias NO basta. La confianza combina:
#   - calidad estructural (schema/config verificado > interpretación)
#   - evidencia acumulada en dimensiones distintas (fuentes, actores, runs)
#   - autoridad de la fuente
#   - contradicciones (penalización explícita)
# Sin señal de éxito ni corroboración, un candidato se queda en SUGGESTED:
# hace falta validación humana (o verificación estructural) para CONFIRM.
# =============================================================================
from __future__ import annotations

from src.core.domain.company_discovery import (
    CandidateKind,
    CandidateSupport,
    ConfidenceBreakdown,
)
from src.core.domain.company_graph import SourceAuthorityLevel, source_authority_rank

# Umbrales del ciclo DISCOVER -> SUPPORT -> SUGGEST.
SUPPORT_OBSERVATIONS = 2
SUGGEST_CONFIDENCE = 0.55
VALIDATE_CONFIDENCE = 0.75

# Piso de corroboración independiente: una sola fuente, por más veces que
# repita, no habilita sugerir una relación interpretativa.
MIN_DISTINCT_SOURCES_FOR_SUGGEST = 2


def score_candidate(
    *,
    kind: CandidateKind,
    support: CandidateSupport,
    authority_level: SourceAuthorityLevel | None = None,
    evidence_quality: float | None = None,
) -> ConfidenceBreakdown:
    """Confianza trazable por factores. Determinista, sin LLM.

    La corroboración se mide en DIMENSIONES INDEPENDIENTES (fuentes, actores,
    ejecuciones). Repetir la misma observación 50 veces desde una sola fuente
    no es evidencia: por eso `observations` pesa casi nada y existe una puerta
    de independencia que hunde lo no corroborado.
    """
    factors: dict[str, float] = {}

    if support.structural:
        base = 0.9
        factors["structural"] = base
    else:
        base = 0.25
        factors["interpretive_base"] = base

    # Corroboración por dimensiones distintas.
    sources = min(support.distinct_sources, 3) * 0.08
    actors = min(support.distinct_actors, 2) * 0.10
    runs = min(support.successful_runs, 6) * 0.03
    factors["distinct_sources"] = round(sources, 4)
    factors["distinct_actors"] = round(actors, 4)
    factors["successful_runs"] = round(runs, 4)

    # Repetición: nudge mínimo, nunca la señal principal.
    observations = min(support.observations, 10) * 0.002
    factors["observations"] = round(observations, 4)

    # Autoridad de fuente: factor multiplicativo (no suma ciega).
    rank = source_authority_rank(authority_level)
    authority_factor = {0: 0.4, 1: 0.8, 2: 1.0, 3: 1.1, 4: 1.15}[rank]
    factors["authority_factor"] = authority_factor
    if support.authoritative_sources:
        factors["authoritative_sources"] = min(
            support.authoritative_sources, 3
        ) * 0.04

    grounding = evidence_quality if evidence_quality is not None else 1.0
    factors["evidence_quality"] = grounding

    contradiction_penalty = min(support.contradictions, 4) * 0.15
    factors["contradiction_penalty"] = -contradiction_penalty

    # Puerta de independencia: sin corroboración cruzada no se sugiere.
    independent = support.distinct_sources >= 2 or support.distinct_actors >= 2
    independence_factor = 1.0 if (independent or support.structural) else 0.6
    factors["independence_factor"] = independence_factor

    total = (
        base
        + sources
        + actors
        + runs
        + observations
        + factors.get("authoritative_sources", 0.0)
        - contradiction_penalty
    ) * authority_factor * grounding * independence_factor
    total = max(0.0, min(total, 1.0))
    factors["total"] = round(total, 4)
    return ConfidenceBreakdown(total=total, factors=factors)


def next_stage_for(
    *,
    kind: CandidateKind,
    support: CandidateSupport,
    confidence: float,
    structural: bool,
) -> str:
    """Etapa alcanzable sin intervención humana.

    Nunca devuelve CONFIRMED: confirmar es acto humano o verificación
    estructural determinista (Fase 5A auto-confirmable), y ambos caminos
    pasan por el promotor, no por el scoring.
    """
    if support.contradictions and confidence < SUGGEST_CONFIDENCE:
        return "discovered"
    if structural and confidence >= VALIDATE_CONFIDENCE:
        return "validated"
    if confidence >= SUGGEST_CONFIDENCE:
        if kind in (CandidateKind.KNOWLEDGE_GAP, CandidateKind.TEMPORAL):
            return "suggested"
        if support.distinct_sources >= MIN_DISTINCT_SOURCES_FOR_SUGGEST or structural:
            return "suggested"
        return "supported"
    if support.observations >= SUPPORT_OBSERVATIONS:
        return "supported"
    return "discovered"


def mapping_confident(support: CandidateSupport) -> bool:
    """Un mapping técnico sólo se sugiere con evidencia acumulada real:
    varios runs exitosos y corroboración, no una ocurrencia."""
    if support.contradictions:
        return False
    if support.structural:
        return True
    return (
        support.successful_runs >= 3
        and support.observations >= 3
        and (support.distinct_sources >= 2 or support.distinct_actors >= 2)
    )
