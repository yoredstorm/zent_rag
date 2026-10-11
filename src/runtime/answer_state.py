# =============================================================================
# Answer state vocabulary — un solo vocabulario de estados de respuesta.
# =============================================================================
# Antes vivía duplicado: constantes en `answer_gate`, literales en
# `decision_envelope` y en `deterministic_authority`. El estado de respuesta es
# UNA realidad: acá está su definición, y `answer_gate` re-exporta los nombres
# históricos para no romper importadores.
#
# Regla: los fallos OPERATIVOS (no se pudo buscar/derivar) nunca se mezclan con
# insuficiencia documental ni con conflictos de fuentes.
# =============================================================================
from __future__ import annotations

ANSWER_STATE_RETRIEVAL_UNAVAILABLE = "RETRIEVAL_UNAVAILABLE"
ANSWER_STATE_INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
ANSWER_STATE_CONFLICTING = "CONFLICTING_EVIDENCE"
ANSWER_STATE_UNDETERMINED = "UNDETERMINED_RULE"
ANSWER_STATE_DERIVED = "DERIVED_RESULT"
ANSWER_STATE_RULE_RETRIEVAL_UNAVAILABLE = "RULE_RETRIEVAL_UNAVAILABLE"
ANSWER_STATE_RULE_EVALUATION_FAILED = "RULE_EVALUATION_FAILED"
ANSWER_STATE_GROUNDING_ENGINE_FAILED = "GROUNDING_ENGINE_FAILED"
ANSWER_STATE_DERIVATION_FAILED = "DERIVATION_FAILED"
ANSWER_STATE_CONFLICTING_RULE = "CONFLICTING_RULE"

#: Fallos OPERATIVOS: la cadena no pudo ejecutarse (no es «no hay datos»).
OPERATIONAL_FAILURE_STATES: frozenset[str] = frozenset(
    {
        ANSWER_STATE_RETRIEVAL_UNAVAILABLE,
        ANSWER_STATE_RULE_RETRIEVAL_UNAVAILABLE,
        ANSWER_STATE_RULE_EVALUATION_FAILED,
        ANSWER_STATE_GROUNDING_ENGINE_FAILED,
        ANSWER_STATE_DERIVATION_FAILED,
    }
)

#: Abstuvo con mensaje: hay pregunta, no hay conclusión respaldada.
ABSTAINED_STATES: frozenset[str] = frozenset(
    {ANSWER_STATE_INSUFFICIENT, ANSWER_STATE_CONFLICTING}
)

#: No concluyente: falta semántica o hay conflicto de reglas.
UNDETERMINED_STATES: frozenset[str] = frozenset(
    {ANSWER_STATE_UNDETERMINED, ANSWER_STATE_CONFLICTING_RULE}
)

__all__ = [
    "ABSTAINED_STATES",
    "ANSWER_STATE_CONFLICTING",
    "ANSWER_STATE_CONFLICTING_RULE",
    "ANSWER_STATE_DERIVATION_FAILED",
    "ANSWER_STATE_DERIVED",
    "ANSWER_STATE_GROUNDING_ENGINE_FAILED",
    "ANSWER_STATE_INSUFFICIENT",
    "ANSWER_STATE_RETRIEVAL_UNAVAILABLE",
    "ANSWER_STATE_RULE_EVALUATION_FAILED",
    "ANSWER_STATE_RULE_RETRIEVAL_UNAVAILABLE",
    "ANSWER_STATE_UNDETERMINED",
    "OPERATIONAL_FAILURE_STATES",
    "UNDETERMINED_STATES",
]
