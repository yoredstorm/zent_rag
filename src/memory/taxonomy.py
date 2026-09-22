# =============================================================================
# Failure taxonomy + success signals.
# =============================================================================
# Un excepción técnica aislada no es memoria. Sólo códigos repetibles, o
# códigos aislados que ya se repitieron, pueden abrir un MemoryRecord.
# CognitiveFailureMode (Cognitive OS) se mapea; no se reemplaza.
# =============================================================================
from __future__ import annotations

from enum import StrEnum

from src.core.domain.cognitive import CognitiveFailureMode


class FailureCode(StrEnum):
    RETRIEVAL_NO_RESULTS = "retrieval.no_results"
    RETRIEVAL_LOW_RELEVANCE = "retrieval.low_relevance"
    RETRIEVAL_TIMEOUT = "retrieval.timeout"
    RETRIEVAL_WRONG_STRATEGY = "retrieval.wrong_strategy"
    KNOWLEDGE_CONFLICT = "knowledge.conflict"
    KNOWLEDGE_STALE_SOURCE = "knowledge.stale_source"
    AGENT_LOOP = "agent.loop"
    AGENT_TOOL_RETRY = "agent.tool_retry"
    AGENT_INVALID_TOOL_ARGS = "agent.invalid_tool_args"
    TOOL_TIMEOUT = "tool.timeout"
    TOOL_PERMISSION_DENIED = "tool.permission_denied"
    SQL_SCHEMA_MISMATCH = "sql.schema_mismatch"
    SQL_INVALID_QUERY = "sql.invalid_query"
    GROUNDING_UNSUPPORTED_CLAIM = "grounding.unsupported_claim"
    GROUNDING_CONTRADICTION = "grounding.contradiction"
    DECISION_LOW_CONFIDENCE = "decision.low_confidence"
    DECISION_WRONG_ROUTE = "decision.wrong_route"
    BUDGET_EXCEEDED = "budget.exceeded"


class SuccessSignal(StrEnum):
    RETRIEVAL_EXACT = "retrieval.exact_success"
    TOOL_SUCCESS = "tool.success"
    GROUNDED_ANSWER = "grounding.supported"
    WORKFLOW_SUCCESS = "workflow.success"
    AGENT_COMPLETED = "agent.completed"
    NO_FALLBACK = "decision.no_fallback"
    LOW_COST = "runtime.low_cost"
    LOW_LATENCY = "runtime.low_latency"


# Errores que, una sola vez, no justifican memoria.
ISOLATED_FAILURES = frozenset(
    {
        FailureCode.RETRIEVAL_TIMEOUT,
        FailureCode.TOOL_TIMEOUT,
        FailureCode.TOOL_PERMISSION_DENIED,
        FailureCode.BUDGET_EXCEEDED,
        FailureCode.SQL_INVALID_QUERY,
    }
)

# Patrones que sí pueden observarse desde la primera repetición estructurada.
REPEATABLE_FAILURES = frozenset(
    {
        FailureCode.RETRIEVAL_NO_RESULTS,
        FailureCode.RETRIEVAL_LOW_RELEVANCE,
        FailureCode.RETRIEVAL_WRONG_STRATEGY,
        FailureCode.KNOWLEDGE_CONFLICT,
        FailureCode.KNOWLEDGE_STALE_SOURCE,
        FailureCode.AGENT_LOOP,
        FailureCode.AGENT_TOOL_RETRY,
        FailureCode.AGENT_INVALID_TOOL_ARGS,
        FailureCode.SQL_SCHEMA_MISMATCH,
        FailureCode.GROUNDING_UNSUPPORTED_CLAIM,
        FailureCode.GROUNDING_CONTRADICTION,
        FailureCode.DECISION_LOW_CONFIDENCE,
        FailureCode.DECISION_WRONG_ROUTE,
    }
)

_COGNITIVE_MAP: dict[CognitiveFailureMode, FailureCode] = {
    CognitiveFailureMode.AGENT_TIMEOUT: FailureCode.TOOL_TIMEOUT,
    CognitiveFailureMode.MODEL_FAILURE: FailureCode.DECISION_LOW_CONFIDENCE,
    CognitiveFailureMode.TOOL_FAILURE: FailureCode.AGENT_TOOL_RETRY,
    CognitiveFailureMode.BUDGET_LIMIT: FailureCode.BUDGET_EXCEEDED,
    CognitiveFailureMode.INVALID_OUTPUT: FailureCode.AGENT_INVALID_TOOL_ARGS,
    CognitiveFailureMode.PERMISSION_FAILURE: FailureCode.TOOL_PERMISSION_DENIED,
    CognitiveFailureMode.RETRIEVAL_EMPTY: FailureCode.RETRIEVAL_NO_RESULTS,
}


def coerce_failure(code: str | FailureCode | CognitiveFailureMode | None) -> FailureCode | None:
    if code is None:
        return None
    if isinstance(code, FailureCode):
        return code
    if isinstance(code, CognitiveFailureMode):
        return _COGNITIVE_MAP.get(code)
    text = str(code).strip()
    if not text:
        return None
    try:
        return FailureCode(text)
    except ValueError:
        return None


def failure_is_admitted(code: FailureCode, *, occurrences: int, isolated_min: int) -> bool:
    """True sólo si el fallo es un patrón, no un error técnico suelto."""
    if code in REPEATABLE_FAILURES:
        return occurrences >= 1
    if code in ISOLATED_FAILURES:
        return occurrences >= isolated_min
    return False


def coerce_success(signal: str | SuccessSignal | None) -> SuccessSignal | None:
    if signal is None:
        return None
    if isinstance(signal, SuccessSignal):
        return signal
    try:
        return SuccessSignal(str(signal).strip())
    except ValueError:
        return None
