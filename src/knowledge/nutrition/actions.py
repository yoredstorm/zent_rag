# =============================================================================
# Knowledge Nutrition — acciones
# =============================================================================
# Mapea cada fallo a una acción potencial. Reglas duras:
#   - NUNCA acción destructiva automática sobre conocimiento canónico.
#   - Feedback débil => status "observed" (señal), no acción.
#   - Toda acción guarda resultado/inputs/evidencia/confianza/razón/versión.
# =============================================================================
from __future__ import annotations

from .contracts import (
    NUTRITION_POLICY_VERSION,
    FailureClassification,
    FailureType,
    NutritionAction,
    NutritionActionStatus,
    NutritionActionType,
)

# Confianza mínima para proponer acción (por debajo: solo se observa).
MIN_ACTION_CONFIDENCE = 0.55

_ACTION_MAP: dict[FailureType, tuple[NutritionActionType, bool, str]] = {
    FailureType.RETRIEVAL_MISS: (
        NutritionActionType.GENERATE_RETRIEVAL_ALIASES,
        False,
        "generar aliases adicionales y recomputar la representación de retrieval",
    ),
    FailureType.BAD_RANK: (
        NutritionActionType.RECORD_RANKING_SIGNAL,
        False,
        "registrar señal de ranking para evaluador offline / reranker",
    ),
    FailureType.MISSING_KNOWLEDGE: (
        NutritionActionType.KNOWLEDGE_GAP,
        True,
        "el conocimiento no existe en ninguna fuente: abrir Knowledge Gap",
    ),
    FailureType.STALE_KNOWLEDGE: (
        NutritionActionType.SOURCE_REFRESH_REQUEST,
        True,
        "la fuente que responde está desactualizada: solicitar refresh",
    ),
    FailureType.PARSER_FAILURE: (
        NutritionActionType.INGESTION_QUALITY_REVIEW,
        True,
        "revisar calidad de parseo de la fuente",
    ),
    FailureType.RECONSTRUCTION_FAILURE: (
        NutritionActionType.RECONSTRUCTION_QUEUE,
        True,
        "encolar reconstrucción semántica del documento",
    ),
    FailureType.ENTITY_RESOLUTION_FAILURE: (
        NutritionActionType.ALIAS_CANDIDATE_REVIEW,
        True,
        "revisar candidatos de alias/merge (sin merge irreversible)",
    ),
    FailureType.TEMPORAL_MISMATCH: (
        NutritionActionType.TEMPORAL_ASSERTION_REVIEW,
        True,
        "revisar ventana temporal de las assertions",
    ),
    FailureType.WRONG_SOURCE: (
        NutritionActionType.SOURCE_AUTHORITY_SIGNAL,
        False,
        "registrar señal de autoridad/ranking de fuente",
    ),
    FailureType.CONFLICT: (
        NutritionActionType.CONFLICT_REVIEW,
        True,
        "revisar conflicto entre fuentes (la evidencia contradictoria no se borra)",
    ),
    FailureType.ANSWER_GENERATION_FAILURE: (
        NutritionActionType.ANSWER_PIPELINE_REVIEW,
        True,
        "revisar pipeline de respuesta/prompt con la evidencia recuperada",
    ),
    FailureType.INSUFFICIENT_EVIDENCE: (
        NutritionActionType.EVIDENCE_REVIEW,
        True,
        "revisar suficiencia de evidencia (candidatos sin soporte)",
    ),
    FailureType.AMBIGUOUS_QUERY: (
        NutritionActionType.QUERY_REFINEMENT_SIGNAL,
        False,
        "registrar señal de ambigüedad de query para refinamiento",
    ),
    FailureType.ACL_FILTERED: (
        NutritionActionType.ACL_AUDIT,
        True,
        "auditar ACL: el usuario no ve documentos que quizá debería ver",
    ),
}


def action_for_classification(
    classification: FailureClassification,
    *,
    organization_id: str | None = None,
    workspace_id: str | None = None,
    source_id: str | None = None,
    document_id: str | None = None,
    query: str | None = None,
    evidence: dict | None = None,
    model_version: str | None = None,
) -> NutritionAction:
    map_entry = _ACTION_MAP.get(FailureType(classification.failure_type))
    if map_entry is None:
        action_type = NutritionActionType.EVIDENCE_REVIEW
        requires_review = True
        reason = "fallo sin mapeo explícito: revisar evidencia"
    else:
        action_type, requires_review, reason = map_entry

    strong = classification.confidence >= MIN_ACTION_CONFIDENCE
    status = (
        NutritionActionStatus.PROPOSED.value
        if strong
        else NutritionActionStatus.OBSERVED.value
    )
    if action_type in (
        NutritionActionType.RECORD_RANKING_SIGNAL,
        NutritionActionType.SOURCE_AUTHORITY_SIGNAL,
        NutritionActionType.QUERY_REFINEMENT_SIGNAL,
    ) and strong:
        # Señal no destructiva: puede aplicarse directo (append-only).
        status = NutritionActionStatus.APPLIED.value

    return NutritionAction(
        action_type=action_type.value,
        failure_type=classification.failure_type,
        reason=reason,
        confidence=classification.confidence,
        status=status,
        organization_id=organization_id,
        workspace_id=workspace_id,
        source_id=source_id,
        document_id=document_id,
        query=(query or "")[:500] or None,
        evidence={
            "classification": classification.to_dict(),
            **(evidence or {}),
        },
        policy_version=NUTRITION_POLICY_VERSION,
        model_version=model_version,
        destructive=False,
        requires_review=requires_review,
    )
