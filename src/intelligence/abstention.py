# =============================================================================
# Structured Abstention — Zent explica QUÉ falta, no solo "no sé"
# =============================================================================
# Distingue explícitamente:
#   DATA_MISSING    -> la data física no existe o no está conectada
#   CONTEXT_MISSING -> la data existe pero Zent no conoce su significado/regla
# Los mensajes conservan el prefijo histórico "No tengo suficiente información"
# para que el guard de caché negativo (orchestrator) siga funcionando.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field

from src.core.domain.intelligence import (
    AnswerabilityDecision,
    AnswerabilityStatus,
)

_LEGACY_PREFIX = "No tengo suficiente información para responder esta pregunta."


@dataclass(kw_only=True)
class AbstentionMessage:
    """Mensaje estructurado de abstención para el usuario."""

    status: str
    message: str
    confidence: str
    found: list[str] = field(default_factory=list)
    missing_context: list[str] = field(default_factory=list)
    missing_data: list[str] = field(default_factory=list)
    conflicting_sources: list[dict] = field(default_factory=list)
    recommended_next_step: str | None = None
    clarifying_question: str | None = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "message": self.message,
            "confidence": self.confidence,
            "found": self.found,
            "missing_context": self.missing_context,
            "missing_data": self.missing_data,
            "conflicting_sources": self.conflicting_sources,
            "recommended_next_step": self.recommended_next_step,
            "clarifying_question": self.clarifying_question,
        }


class AbstentionBuilder:
    """Construye mensajes de abstención estructurados y en lenguaje natural."""

    @staticmethod
    def build(decision: AnswerabilityDecision) -> AbstentionMessage:
        status = decision.status
        conf = decision.confidence_level.value

        if status == AnswerabilityStatus.ACCESS_BLOCKED:
            return AbstentionMessage(
                status=status.value,
                message=decision.message or _LEGACY_PREFIX,
                confidence=conf,
                recommended_next_step="Solicitar acceso o revisar la política de la organización",
            )

        if status == AnswerabilityStatus.EXECUTION_FAILED:
            return AbstentionMessage(
                status=status.value,
                message=decision.message or _LEGACY_PREFIX,
                confidence=conf,
                recommended_next_step="Reintentar la consulta o verificar la salud de las fuentes",
            )

        if status == AnswerabilityStatus.SOURCE_CONFLICT:
            found = [
                f"{c['source_a']}={c['value_a']} vs {c['source_b']}={c['value_b']}"
                for c in decision.conflicting_sources
            ]
            return AbstentionMessage(
                status=status.value,
                message=decision.message or _LEGACY_PREFIX,
                confidence=conf,
                found=found,
                conflicting_sources=decision.conflicting_sources,
                recommended_next_step="Configurar una fuente autoritativa para la métrica",
            )

        if status == AnswerabilityStatus.CLARIFICATION_REQUIRED:
            return AbstentionMessage(
                status=status.value,
                message=decision.message or "Necesito una aclaración para responder.",
                confidence=conf,
                clarifying_question=decision.clarifying_question,
                recommended_next_step="Responder la pregunta de aclaración",
            )

        if status == AnswerabilityStatus.AMBIGUOUS:
            return AbstentionMessage(
                status=status.value,
                message=decision.message or _LEGACY_PREFIX,
                confidence=conf,
                recommended_next_step="Proporcionar más contexto",
            )

        if status == AnswerabilityStatus.CONTEXT_MISSING:
            return AbstentionMessage(
                status=status.value,
                message=decision.message or _LEGACY_PREFIX,
                confidence=conf,
                found=decision.found,
                missing_context=decision.missing_context,
                recommended_next_step=(
                    "Create or approve the missing business definitions."
                    if decision.missing_context
                    else None
                ),
            )

        if status == AnswerabilityStatus.DATA_MISSING:
            return AbstentionMessage(
                status=status.value,
                message=decision.message or _LEGACY_PREFIX,
                confidence=conf,
                missing_data=decision.missing_data,
                recommended_next_step=(
                    "Connect the required data source or reindex the knowledge base."
                    if decision.missing_data
                    else None
                ),
            )

        if status == AnswerabilityStatus.DATA_QUALITY_LOW:
            return AbstentionMessage(
                status=status.value,
                message=decision.message or _LEGACY_PREFIX,
                confidence=conf,
                found=decision.found,
                recommended_next_step="Actualizar las fuentes o esperar la sincronización",
            )

        if status == AnswerabilityStatus.HUMAN_REVIEW_REQUIRED:
            return AbstentionMessage(
                status=status.value,
                message=decision.message or _LEGACY_PREFIX,
                confidence=conf,
                found=decision.found,
                recommended_next_step="Escalar a revisión humana con la evidencia adjunta",
            )

        # ANSWERABLE — no aplica abstención, pero devolvemos el mensaje por si acaso
        return AbstentionMessage(
            status=status.value,
            message=decision.message or "",
            confidence=conf,
        )

    @staticmethod
    def to_llm_response(abstention: AbstentionMessage) -> str:
        """Convierte la abstención en el texto final de la respuesta (backward compat)."""
        message = abstention.message
        if abstention.missing_context:
            message += (
                " Contexto faltante: "
                + "; ".join(abstention.missing_context)
                + "."
            )
        if abstention.missing_data:
            message += (
                " Datos faltantes: " + "; ".join(abstention.missing_data) + "."
            )
        if abstention.recommended_next_step:
            message += f" Siguiente paso sugerido: {abstention.recommended_next_step}."
        return message
