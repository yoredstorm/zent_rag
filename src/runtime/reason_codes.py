# =============================================================================
# Catálogo único y versionado de reason codes del runtime.
# =============================================================================
# Reglas:
# - Strings estables: renombrar un código es un cambio de contrato.
# - Prohibido vocabulario paralelo: si un código ya existe, se reutiliza.
# - Un código pertenece a un dueño (quién lo emite); los compartidos entre
#   dueños se declaran una sola vez.
#
# Vocabularios que NO se duplican acá:
# - Stop reasons del presupuesto (STEP_BUDGET, TOKEN_BUDGET, PROVIDER_FAILURE,
#   ...): viven en `src.runtime.run_budget.STOP_REASONS` (cerrado y propio).
# - Códigos derivados de la story view (AUTHORITY_FINALIZE, ...): se derivan
#   de los steps en `src.runtime.story_view` (presentación, no emisión).
# =============================================================================
from __future__ import annotations

REASON_CODES_VERSION = "reason-codes-1"

# --- Finalization Policy: resolución de autoridad del cierre -----------------
TOOL_OUTSIDE_ALLOWLIST = "TOOL_OUTSIDE_ALLOWLIST"
TOOL_NOT_AUTHORIZED = "TOOL_NOT_AUTHORIZED"
TOOL_AUTHORIZED = "TOOL_AUTHORIZED"
DETERMINISTIC_AUTHORITY = "DETERMINISTIC_AUTHORITY"
AUTHORITY_MISSING_RETRIEVE = "AUTHORITY_MISSING_RETRIEVE"
AUTHORITY_MISSING_FOR_EXECUTABLE = "AUTHORITY_MISSING_FOR_EXECUTABLE"
RETRIEVAL_UNAVAILABLE = "RETRIEVAL_UNAVAILABLE"
BUDGET_EXHAUSTED_WITH_EVIDENCE = "BUDGET_EXHAUSTED_WITH_EVIDENCE"
BUDGET_EXHAUSTED_WITHOUT_EVIDENCE = "BUDGET_EXHAUSTED_WITHOUT_EVIDENCE"
EVIDENCE_INCOMPLETE = "EVIDENCE_INCOMPLETE"
EVIDENCE_INCOMPLETE_LIMITED = "EVIDENCE_INCOMPLETE_LIMITED"
EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT"
REASONING_INCOMPLETE = "REASONING_INCOMPLETE"
TERMINATION_SATISFIED = "TERMINATION_SATISFIED"
TERMINATION_WITHOUT_DRAFT = "TERMINATION_WITHOUT_DRAFT"
READY = "READY"
NEED_DRAFT = "NEED_DRAFT"

# --- Finalization Policy: señales ignoradas (observabilidad del resolver) ---
JEV_ONLY_NEGATIVE_SIGNAL = "jev_only_negative_signal"
JEV_POSITIVE_WITHOUT_EVIDENCE = "jev_positive_without_evidence"
REASONING_INCOMPLETE_OVERRIDDEN_BY_AUTHORITY = (
    "reasoning_incomplete_overridden_by_authority"
)
TERMINATION_VS_INCOMPLETE_REASONING = "termination_vs_incomplete_reasoning"

# --- Run Guards: transiciones permitidas del loop ----------------------------
TERMINAL_NO_TRANSITIONS = "TERMINAL_NO_TRANSITIONS"
DUPLICATE_TOOL_CALL = "DUPLICATE_TOOL_CALL"
BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
RETRIEVAL_ALLOWED = "RETRIEVAL_ALLOWED"
ANALYSIS_INCOMPLETE = "ANALYSIS_INCOMPLETE"
LIMIT_REACHED_WITHOUT_EVIDENCE = "LIMIT_REACHED_WITHOUT_EVIDENCE"
READY_TO_FINALIZE = "READY_TO_FINALIZE"
TOOL_RETRY_ALLOWED = "TOOL_RETRY_ALLOWED"
TOOL_FAILED_PERMANENT_NO_RETRY = "TOOL_FAILED_PERMANENT_NO_RETRY"
TOOL_RESULT_OBSERVED = "TOOL_RESULT_OBSERVED"

#: Todos los códigos emitibles. Un código fuera de este set es un bug de
#: contrato: o falta declararlo acá, o sobra en el emisor.
ALL_REASON_CODES: frozenset[str] = frozenset(
    {
        # Finalization Policy
        TOOL_OUTSIDE_ALLOWLIST,
        TOOL_NOT_AUTHORIZED,
        TOOL_AUTHORIZED,
        DETERMINISTIC_AUTHORITY,
        AUTHORITY_MISSING_RETRIEVE,
        AUTHORITY_MISSING_FOR_EXECUTABLE,
        RETRIEVAL_UNAVAILABLE,
        BUDGET_EXHAUSTED_WITH_EVIDENCE,
        BUDGET_EXHAUSTED_WITHOUT_EVIDENCE,
        EVIDENCE_INCOMPLETE,
        EVIDENCE_INCOMPLETE_LIMITED,
        EVIDENCE_INSUFFICIENT,
        REASONING_INCOMPLETE,
        TERMINATION_SATISFIED,
        TERMINATION_WITHOUT_DRAFT,
        READY,
        NEED_DRAFT,
        # Señales ignoradas
        JEV_ONLY_NEGATIVE_SIGNAL,
        JEV_POSITIVE_WITHOUT_EVIDENCE,
        REASONING_INCOMPLETE_OVERRIDDEN_BY_AUTHORITY,
        TERMINATION_VS_INCOMPLETE_REASONING,
        # Run Guards
        TERMINAL_NO_TRANSITIONS,
        DUPLICATE_TOOL_CALL,
        BUDGET_EXHAUSTED,
        RETRIEVAL_ALLOWED,
        ANALYSIS_INCOMPLETE,
        LIMIT_REACHED_WITHOUT_EVIDENCE,
        READY_TO_FINALIZE,
        TOOL_RETRY_ALLOWED,
        TOOL_FAILED_PERMANENT_NO_RETRY,
        TOOL_RESULT_OBSERVED,
    }
)


def is_known_reason_code(code: str) -> bool:
    """¿El código pertenece al catálogo? Un desconocido es deuda, no señal."""
    return str(code or "") in ALL_REASON_CODES
