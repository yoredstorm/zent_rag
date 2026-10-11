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
ANSWER_STATE_OPERATION_MISMATCH = "UNDETERMINED_OPERATION_MISMATCH"


def operational_failure_state(stage: str = "", code: str = "") -> str:
    """Estado de fallo OPERATIVO con la prioridad histórica código/stage.

    Definición única del mapeo que usaban `finalize_authoritative_answer` y la
    cadena determinista: grounding manda, luego rule_retrieval, rule_evaluation
    y derivation; sin señal operativa → UNDETERMINED_RULE.
    """
    stage = str(stage or "")
    code = str(code or "")
    if stage == "grounding" or code == ANSWER_STATE_GROUNDING_ENGINE_FAILED:
        return ANSWER_STATE_GROUNDING_ENGINE_FAILED
    if stage == "rule_retrieval" or code == ANSWER_STATE_RULE_RETRIEVAL_UNAVAILABLE:
        return ANSWER_STATE_RULE_RETRIEVAL_UNAVAILABLE
    if stage == "rule_evaluation" or code == ANSWER_STATE_RULE_EVALUATION_FAILED:
        return ANSWER_STATE_RULE_EVALUATION_FAILED
    if stage == "derivation" or code == ANSWER_STATE_DERIVATION_FAILED:
        return ANSWER_STATE_DERIVATION_FAILED
    return ANSWER_STATE_UNDETERMINED


def select_answer_state(
    *,
    has_deterministic_result: bool = False,
    is_knowledge_question: bool = True,
    operational_failure: str = "",
    retrieval_failed: bool = False,
    evidence_count: int | None = None,
    conflicts: bool = False,
    conflict_state: str = ANSWER_STATE_CONFLICTING,
    operation_mismatch: bool = False,
    missing_premises: bool = False,
    default_state: str = "",
) -> str:
    """Prioridad ÚNICA de estados de respuesta. Código decide; nunca el LLM.

    La usan el gate de respuesta (`resolve_answer_state`) y la cadena
    determinista (`DerivedPreparationResult.answer_state`), cada uno adaptando
    sus señales y sus mensajes. `evidence_count=None` = señal no disponible
    (no dispara INSUFFICIENT_EVIDENCE).
    """
    if has_deterministic_result:
        return ANSWER_STATE_DERIVED
    if not is_knowledge_question:
        return ""
    if operational_failure:
        return operational_failure
    if retrieval_failed and evidence_count == 0:
        return ANSWER_STATE_RETRIEVAL_UNAVAILABLE
    if conflicts:
        return conflict_state
    if operation_mismatch:
        return ANSWER_STATE_OPERATION_MISMATCH
    if missing_premises:
        return ANSWER_STATE_UNDETERMINED
    if evidence_count == 0:
        return ANSWER_STATE_INSUFFICIENT
    return default_state

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
    "ANSWER_STATE_OPERATION_MISMATCH",
    "ANSWER_STATE_RETRIEVAL_UNAVAILABLE",
    "ANSWER_STATE_RULE_EVALUATION_FAILED",
    "ANSWER_STATE_RULE_RETRIEVAL_UNAVAILABLE",
    "ANSWER_STATE_UNDETERMINED",
    "OPERATIONAL_FAILURE_STATES",
    "UNDETERMINED_STATES",
    "operational_failure_state",
    "select_answer_state",
]
