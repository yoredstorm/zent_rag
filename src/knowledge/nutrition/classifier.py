# =============================================================================
# Knowledge Nutrition — clasificador de fallos
# =============================================================================
# Clasifica con SEÑALES del run (retrieval, evidencia, gates, feedback), no con
# la intuición de un LLM. Cada clasificación guarda: resultado, inputs
# relevantes, evidencia, señales, confianza, razón resumida y versión.
# =============================================================================
from __future__ import annotations

from .contracts import (
    NUTRITION_POLICY_VERSION,
    FailureClassification,
    FailureSignals,
    FailureType,
)

# Umbrales de señal (deterministas y auditables).
LOW_PARSER_QUALITY = 0.4
LOW_RECONSTRUCTION_QUALITY = 0.35
LOW_TOP_SCORE = 0.25
MIN_ANSWER_EVIDENCE = 1


def classify_failure(signals: FailureSignals) -> FailureClassification:
    """(tipo, confianza, razón) a partir de señales reales."""
    evidence = _evidence(signals)

    def result(failure_type: FailureType, confidence: float, reason: str) -> FailureClassification:
        return FailureClassification(
            failure_type=failure_type.value,
            confidence=max(0.0, min(1.0, confidence)),
            reason=reason,
            policy_version=NUTRITION_POLICY_VERSION,
            signals=evidence,
        )

    # Señales explícitas (ya medidas por otros subsistemas) primero.
    if signals.acl_filtered:
        return result(FailureType.ACL_FILTERED, 0.95, "el filtro ACL eliminó los documentos esperados")
    if signals.parser_quality is not None and signals.parser_quality < LOW_PARSER_QUALITY:
        return result(
            FailureType.PARSER_FAILURE,
            0.85,
            f"calidad de parseo {signals.parser_quality:.2f} < {LOW_PARSER_QUALITY}",
        )
    if (
        signals.reconstruction_quality is not None
        and signals.reconstruction_quality < LOW_RECONSTRUCTION_QUALITY
    ):
        return result(
            FailureType.RECONSTRUCTION_FAILURE,
            0.85,
            f"calidad de reconstrucción {signals.reconstruction_quality:.2f} < {LOW_RECONSTRUCTION_QUALITY}",
        )
    if signals.temporal_mismatch:
        return result(
            FailureType.TEMPORAL_MISMATCH, 0.8, "la evidencia existe pero fuera de la ventana temporal"
        )
    if signals.conflict:
        return result(FailureType.CONFLICT, 0.8, "fuentes en conflicto para la misma consulta")
    if signals.entity_unresolved:
        return result(
            FailureType.ENTITY_RESOLUTION_FAILURE,
            0.75,
            "entidad recuperada pero no resuelta a una identidad conocida",
        )
    if signals.stale:
        return result(FailureType.STALE_KNOWLEDGE, 0.8, "la fuente que responde está desactualizada")
    if signals.wrong_source:
        return result(FailureType.WRONG_SOURCE, 0.7, "respondió una fuente de autoridad equivocada")
    if signals.no_source_match:
        # Ninguna fuente contiene la respuesta (señal del gap detector): NO es
        # un fallo de ranking ni de generación.
        return result(
            FailureType.MISSING_KNOWLEDGE,
            0.8,
            "ninguna fuente del corpus contiene la respuesta",
        )
    if signals.evidence_rank is not None and signals.evidence_rank > 5:
        return result(
            FailureType.BAD_RANK,
            0.75,
            f"evidencia correcta en rank {signals.evidence_rank} (fuera de top-5)",
        )

    # Retrieval miss vs bad rank vs evidencia insuficiente.
    if signals.retrieved_chunks <= 0:
        if signals.lexical_hit is False and signals.semantic_hit is False:
            return result(
                FailureType.RETRIEVAL_MISS,
                0.9,
                "ni dense ni lexical recuperaron candidatos",
            )
        if signals.feedback_rating == "down" and signals.feedback_reason == "wrong_answer":
            return result(FailureType.MISSING_KNOWLEDGE, 0.7, "feedback negativo sin recuperación")
        return result(FailureType.RETRIEVAL_MISS, 0.9, "retrieval sin candidatos")

    if signals.top_score is not None and signals.top_score < LOW_TOP_SCORE:
        return result(
            FailureType.BAD_RANK,
            0.75,
            f"top score {signals.top_score:.2f} < {LOW_TOP_SCORE}",
        )
    if signals.evidence_used < MIN_ANSWER_EVIDENCE:
        return result(
            FailureType.INSUFFICIENT_EVIDENCE,
            0.75,
            "candidatos recuperados pero sin evidencia usable en la respuesta",
        )
    if signals.answer_gate is not None and signals.answer_gate not in ("passed", "ok"):
        return result(
            FailureType.ANSWER_GENERATION_FAILURE,
            0.7,
            f"answer gate={signals.answer_gate}",
        )
    if signals.feedback_rating == "down":
        if signals.feedback_reason == "wrong_answer":
            return result(FailureType.BAD_RANK, 0.6, "feedback wrong_answer con evidencia recuperada")
        return result(
            FailureType.AMBIGUOUS_QUERY,
            0.45,
            f"feedback negativo sin causa clara (reason={signals.feedback_reason or 'none'})",
        )
    return result(FailureType.BAD_RANK, 0.5, "señal débil: se registra sin acción destructiva")


def _evidence(signals: FailureSignals) -> dict:
    """Inputs relevantes para auditar la clasificación (sin CoT)."""
    return {
        "query": (signals.query or "")[:300],
        "retrieved_chunks": signals.retrieved_chunks,
        "top_score": signals.top_score,
        "evidence_used": signals.evidence_used,
        "citations": signals.citations,
        "answer_gate": signals.answer_gate,
        "planner_path": signals.planner_path,
        "feedback_rating": signals.feedback_rating,
        "feedback_reason": signals.feedback_reason,
        "lexical_hit": signals.lexical_hit,
        "semantic_hit": signals.semantic_hit,
        "evidence_rank": signals.evidence_rank,
        "no_source_match": signals.no_source_match,
        "parser_quality": signals.parser_quality,
        "reconstruction_quality": signals.reconstruction_quality,
        "source_id": signals.source_id,
        "document_id": signals.document_id,
        "workspace_id": signals.workspace_id,
    }
