# =============================================================================
# Failure Taxonomy — clasificación única de fallos del runtime.
# =============================================================================
# Regla: un fallo se clasifica por lo que FALLÓ, nunca por lo que el usuario ve.
# Prohibido mezclar realidades distintas:
#   - provider timeout  != evidencia insuficiente
#   - permiso denegado  != tool fallida
#   - retrieval caído   != «no hay información»
#
# Cada clasificación declara: failure_class, reason_code, retryable,
# user_visible (¿el usuario debería verlo?) y operational (¿es fallo de la
# ejecución, no una conclusión sobre el contenido?).
#
# El vocabulario de entrada es cerrado y vive en:
#   - `src.runtime.reason_codes` (política y guards),
#   - `src.runtime.run_budget.STOP_REASONS` (cortes de presupuesto),
#   - `src.runtime.answer_state` (estados de respuesta).
# Un código desconocido devuelve None: es deuda, no una clasificación inventada.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from src.runtime import reason_codes as rc
from src.runtime.answer_state import (
    ANSWER_STATE_CONFLICTING,
    ANSWER_STATE_CONFLICTING_RULE,
    ANSWER_STATE_DERIVATION_FAILED,
    ANSWER_STATE_GROUNDING_ENGINE_FAILED,
    ANSWER_STATE_INSUFFICIENT,
    ANSWER_STATE_OPERATION_MISMATCH,
    ANSWER_STATE_RETRIEVAL_UNAVAILABLE,
    ANSWER_STATE_RULE_EVALUATION_FAILED,
    ANSWER_STATE_RULE_RETRIEVAL_UNAVAILABLE,
    ANSWER_STATE_UNDETERMINED,
)

FAILURE_TAXONOMY_VERSION = "failure-taxonomy-1"


class FailureClass(StrEnum):
    USER_ERROR = "USER_ERROR"
    POLICY_BLOCK = "POLICY_BLOCK"
    AUTHORIZATION_ERROR = "AUTHORIZATION_ERROR"
    AUTHORITY_MISSING = "AUTHORITY_MISSING"
    EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT"
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
    RETRIEVAL_FAILURE = "RETRIEVAL_FAILURE"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    RATE_LIMIT = "RATE_LIMIT"
    TIMEOUT = "TIMEOUT"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    DEPENDENCY_ERROR = "DEPENDENCY_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True, kw_only=True)
class FailureInfo:
    failure_class: FailureClass
    reason_code: str
    retryable: bool
    user_visible: bool
    operational: bool

    def to_public_dict(self) -> dict:
        return {
            "failure_class": str(self.failure_class),
            "reason_code": self.reason_code,
            "retryable": self.retryable,
            "user_visible": self.user_visible,
            "operational": self.operational,
        }


def _info(
    failure_class: FailureClass,
    code: str,
    *,
    retryable: bool,
    user_visible: bool,
    operational: bool,
) -> FailureInfo:
    return FailureInfo(
        failure_class=failure_class,
        reason_code=str(code),
        retryable=bool(retryable),
        user_visible=bool(user_visible),
        operational=bool(operational),
    )


#: Fallo → clasificación. Un código ausente NO es un fallo (señal de control).
_REASON_CODE_FAILURES: dict[str, FailureInfo] = {
    # Autorización / política (nunca se confunden con fallos de tool).
    rc.TOOL_OUTSIDE_ALLOWLIST: _info(
        FailureClass.POLICY_BLOCK,
        rc.TOOL_OUTSIDE_ALLOWLIST,
        retryable=False,
        user_visible=False,
        operational=True,
    ),
    rc.TOOL_NOT_AUTHORIZED: _info(
        FailureClass.AUTHORIZATION_ERROR,
        rc.TOOL_NOT_AUTHORIZED,
        retryable=False,
        user_visible=False,
        operational=True,
    ),
    rc.DUPLICATE_TOOL_CALL: _info(
        FailureClass.POLICY_BLOCK,
        rc.DUPLICATE_TOOL_CALL,
        retryable=False,
        user_visible=False,
        operational=True,
    ),
    rc.TERMINAL_NO_TRANSITIONS: _info(
        FailureClass.INTERNAL_ERROR,
        rc.TERMINAL_NO_TRANSITIONS,
        retryable=False,
        user_visible=False,
        operational=True,
    ),
    # Autoridad determinista ausente: ni evidencia ni provider.
    rc.AUTHORITY_MISSING_RETRIEVE: _info(
        FailureClass.AUTHORITY_MISSING,
        rc.AUTHORITY_MISSING_RETRIEVE,
        retryable=True,
        user_visible=True,
        operational=False,
    ),
    rc.AUTHORITY_MISSING_FOR_EXECUTABLE: _info(
        FailureClass.AUTHORITY_MISSING,
        rc.AUTHORITY_MISSING_FOR_EXECUTABLE,
        retryable=False,
        user_visible=True,
        operational=False,
    ),
    # Retrieval caído: jamás «no hay información».
    rc.RETRIEVAL_UNAVAILABLE: _info(
        FailureClass.RETRIEVAL_FAILURE,
        rc.RETRIEVAL_UNAVAILABLE,
        retryable=True,
        user_visible=True,
        operational=True,
    ),
    # Presupuesto.
    rc.BUDGET_EXHAUSTED: _info(
        FailureClass.BUDGET_EXHAUSTED,
        rc.BUDGET_EXHAUSTED,
        retryable=True,
        user_visible=True,
        operational=True,
    ),
    rc.BUDGET_EXHAUSTED_WITH_EVIDENCE: _info(
        FailureClass.BUDGET_EXHAUSTED,
        rc.BUDGET_EXHAUSTED_WITH_EVIDENCE,
        retryable=True,
        user_visible=True,
        operational=True,
    ),
    rc.BUDGET_EXHAUSTED_WITHOUT_EVIDENCE: _info(
        FailureClass.BUDGET_EXHAUSTED,
        rc.BUDGET_EXHAUSTED_WITHOUT_EVIDENCE,
        retryable=True,
        user_visible=True,
        operational=True,
    ),
    rc.LIMIT_REACHED_WITHOUT_EVIDENCE: _info(
        FailureClass.BUDGET_EXHAUSTED,
        rc.LIMIT_REACHED_WITHOUT_EVIDENCE,
        retryable=True,
        user_visible=True,
        operational=True,
    ),
    # Evidencia: conclusión sobre el contenido, no fallo operativo.
    rc.EVIDENCE_INCOMPLETE: _info(
        FailureClass.EVIDENCE_INSUFFICIENT,
        rc.EVIDENCE_INCOMPLETE,
        retryable=True,
        user_visible=True,
        operational=False,
    ),
    rc.EVIDENCE_INCOMPLETE_LIMITED: _info(
        FailureClass.EVIDENCE_INSUFFICIENT,
        rc.EVIDENCE_INCOMPLETE_LIMITED,
        retryable=True,
        user_visible=True,
        operational=False,
    ),
    rc.EVIDENCE_INSUFFICIENT: _info(
        FailureClass.EVIDENCE_INSUFFICIENT,
        rc.EVIDENCE_INSUFFICIENT,
        retryable=True,
        user_visible=True,
        operational=False,
    ),
    # Tool transitoria/permantente.
    rc.TOOL_RETRY_ALLOWED: _info(
        FailureClass.DEPENDENCY_ERROR,
        rc.TOOL_RETRY_ALLOWED,
        retryable=True,
        user_visible=False,
        operational=True,
    ),
    rc.TOOL_FAILED_PERMANENT_NO_RETRY: _info(
        FailureClass.DEPENDENCY_ERROR,
        rc.TOOL_FAILED_PERMANENT_NO_RETRY,
        retryable=False,
        user_visible=True,
        operational=True,
    ),
}

#: Cortes de presupuesto del ledger.
_STOP_REASON_FAILURES: dict[str, FailureInfo] = {
    "STEP_BUDGET": _info(
        FailureClass.BUDGET_EXHAUSTED,
        "STEP_BUDGET",
        retryable=True,
        user_visible=True,
        operational=True,
    ),
    "TOOL_BUDGET": _info(
        FailureClass.BUDGET_EXHAUSTED,
        "TOOL_BUDGET",
        retryable=True,
        user_visible=True,
        operational=True,
    ),
    "TOKEN_BUDGET": _info(
        FailureClass.BUDGET_EXHAUSTED,
        "TOKEN_BUDGET",
        retryable=True,
        user_visible=True,
        operational=True,
    ),
    "COST_BUDGET": _info(
        FailureClass.BUDGET_EXHAUSTED,
        "COST_BUDGET",
        retryable=True,
        user_visible=True,
        operational=True,
    ),
    "TIME_BUDGET": _info(
        FailureClass.BUDGET_EXHAUSTED,
        "TIME_BUDGET",
        retryable=True,
        user_visible=True,
        operational=True,
    ),
    "PROVIDER_RATE_LIMIT": _info(
        FailureClass.RATE_LIMIT,
        "PROVIDER_RATE_LIMIT",
        retryable=True,
        user_visible=True,
        operational=True,
    ),
    "PROVIDER_FAILURE": _info(
        FailureClass.PROVIDER_FAILURE,
        "PROVIDER_FAILURE",
        retryable=True,
        user_visible=True,
        operational=True,
    ),
}

#: Estados de respuesta operativos → clasificación.
_ANSWER_STATE_FAILURES: dict[str, FailureInfo] = {
    ANSWER_STATE_RETRIEVAL_UNAVAILABLE: _info(
        FailureClass.RETRIEVAL_FAILURE,
        ANSWER_STATE_RETRIEVAL_UNAVAILABLE,
        retryable=True,
        user_visible=True,
        operational=True,
    ),
    ANSWER_STATE_RULE_RETRIEVAL_UNAVAILABLE: _info(
        FailureClass.RETRIEVAL_FAILURE,
        ANSWER_STATE_RULE_RETRIEVAL_UNAVAILABLE,
        retryable=True,
        user_visible=True,
        operational=True,
    ),
    ANSWER_STATE_RULE_EVALUATION_FAILED: _info(
        FailureClass.DEPENDENCY_ERROR,
        ANSWER_STATE_RULE_EVALUATION_FAILED,
        retryable=True,
        user_visible=True,
        operational=True,
    ),
    ANSWER_STATE_GROUNDING_ENGINE_FAILED: _info(
        FailureClass.INTERNAL_ERROR,
        ANSWER_STATE_GROUNDING_ENGINE_FAILED,
        retryable=True,
        user_visible=True,
        operational=True,
    ),
    ANSWER_STATE_DERIVATION_FAILED: _info(
        FailureClass.INTERNAL_ERROR,
        ANSWER_STATE_DERIVATION_FAILED,
        retryable=False,
        user_visible=True,
        operational=True,
    ),
    ANSWER_STATE_INSUFFICIENT: _info(
        FailureClass.EVIDENCE_INSUFFICIENT,
        ANSWER_STATE_INSUFFICIENT,
        retryable=True,
        user_visible=True,
        operational=False,
    ),
    ANSWER_STATE_CONFLICTING: _info(
        FailureClass.EVIDENCE_CONFLICT,
        ANSWER_STATE_CONFLICTING,
        retryable=False,
        user_visible=True,
        operational=False,
    ),
    ANSWER_STATE_UNDETERMINED: _info(
        FailureClass.AUTHORITY_MISSING,
        ANSWER_STATE_UNDETERMINED,
        retryable=False,
        user_visible=True,
        operational=False,
    ),
    ANSWER_STATE_CONFLICTING_RULE: _info(
        FailureClass.EVIDENCE_CONFLICT,
        ANSWER_STATE_CONFLICTING_RULE,
        retryable=False,
        user_visible=True,
        operational=False,
    ),
    ANSWER_STATE_OPERATION_MISMATCH: _info(
        FailureClass.AUTHORITY_MISSING,
        ANSWER_STATE_OPERATION_MISMATCH,
        retryable=False,
        user_visible=True,
        operational=False,
    ),
}

#: Estados de fallo OPERATIVO que deben estar clasificados (cobertura).
OPERATIONAL_STATES_COVERED: frozenset[str] = frozenset(_ANSWER_STATE_FAILURES)


def classify_reason_code(code: str) -> FailureInfo | None:
    """Clasifica un reason_code del catálogo. None = señal de control, no fallo."""
    return _REASON_CODE_FAILURES.get(str(code or ""))


def classify_stop_reason(code: str) -> FailureInfo | None:
    """Clasifica un corte de presupuesto (`run_budget.STOP_REASONS`)."""
    return _STOP_REASON_FAILURES.get(str(code or ""))


def classify_answer_state(state: str) -> FailureInfo | None:
    """Clasifica un estado de respuesta (operativo, abstención o undetermined)."""
    return _ANSWER_STATE_FAILURES.get(str(state or ""))


def classify_failure(code: str) -> FailureInfo | None:
    """Clasifica un código de cualquier vocabulario cerrado (o None)."""
    return (
        classify_reason_code(code)
        or classify_stop_reason(code)
        or classify_answer_state(code)
    )


#: Status de intento de provider (router de gateway) → clase de fallo.
_PROVIDER_ATTEMPT_CLASSES: dict[str, FailureClass] = {
    "rate_limited": FailureClass.RATE_LIMIT,
    "timeout": FailureClass.TIMEOUT,
    "circuit_open": FailureClass.PROVIDER_FAILURE,
    "auth_error": FailureClass.PROVIDER_FAILURE,
    "provider_error": FailureClass.PROVIDER_FAILURE,
    "error": FailureClass.PROVIDER_FAILURE,
}


def classify_provider_attempt(status: str) -> FailureInfo | None:
    """Clasifica un intento de provider. `success` no es un fallo (None)."""
    text = str(status or "")
    failure_class = _PROVIDER_ATTEMPT_CLASSES.get(text)
    if failure_class is None:
        return None
    return _info(
        failure_class,
        f"provider_attempt:{text}",
        retryable=text in {"rate_limited", "timeout", "provider_error"},
        user_visible=False,
        operational=True,
    )


__all__ = [
    "FAILURE_TAXONOMY_VERSION",
    "OPERATIONAL_STATES_COVERED",
    "FailureClass",
    "FailureInfo",
    "classify_answer_state",
    "classify_failure",
    "classify_provider_attempt",
    "classify_reason_code",
    "classify_stop_reason",
]
