# =============================================================================
# Run Guards — transiciones permitidas del Agent Runtime como DATOS.
# =============================================================================
# Tabla explícita: (fase, evento, guards) -> (fase destino, reason_code).
# El loop conserva su autonomía DENTRO de transiciones permitidas; esta tabla
# hace legible qué puede y qué no puede hacer un agente, y es la fuente de los
# tests de transición. No ejecuta nada: resuelve si una transición es válida.
#
# No duplica el workflow engine ni reemplaza los gates: los guards reutilizan
# las señales canónicas (autorización de tool, budget, autoridad determinista,
# completitud de análisis, evidencia).
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from src.runtime.reason_codes import (
    ANALYSIS_INCOMPLETE,
    AUTHORITY_MISSING_FOR_EXECUTABLE,
    BUDGET_EXHAUSTED,
    BUDGET_EXHAUSTED_WITH_EVIDENCE,
    DUPLICATE_TOOL_CALL,
    LIMIT_REACHED_WITHOUT_EVIDENCE,
    READY_TO_FINALIZE,
    RETRIEVAL_ALLOWED,
    TERMINAL_NO_TRANSITIONS,
    TOOL_AUTHORIZED,
    TOOL_FAILED_PERMANENT_NO_RETRY,
    TOOL_NOT_AUTHORIZED,
    TOOL_RESULT_OBSERVED,
    TOOL_RETRY_ALLOWED,
)
from src.runtime.run_state import TERMINAL_PHASES, RunPhase

RUN_GUARDS_VERSION = "run-guards-1"


class RunEvent(StrEnum):
    REQUEST_TOOL = "REQUEST_TOOL"
    REQUEST_RETRIEVAL = "REQUEST_RETRIEVAL"
    REQUEST_FINALIZE = "REQUEST_FINALIZE"
    OBSERVE_TOOL_RESULT = "OBSERVE_TOOL_RESULT"


@dataclass(frozen=True, kw_only=True)
class TransitionVerdict:
    allowed: bool
    to_phase: RunPhase
    reason_code: str
    version: str = RUN_GUARDS_VERSION

    def to_public_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "to_phase": str(self.to_phase),
            "reason_code": self.reason_code,
        }


def evaluate_transition(
    phase: RunPhase,
    event: RunEvent,
    *,
    tool_authorized: bool = False,
    duplicate_tool_call: bool = False,
    tool_failure: str = "",
    budget_exhausted: bool = False,
    evidence_available: bool = False,
    requires_deterministic: bool = False,
    authority_present: bool = False,
    analysis_incomplete: bool = False,
) -> TransitionVerdict:
    """Resuelve una transición del run sin ejecutarla.

    Terminales no transicionan: un FINAL nunca va a TOOL/RETRIEVAL/REASON.
    """
    if phase in TERMINAL_PHASES:
        return TransitionVerdict(
            allowed=False, to_phase=phase, reason_code=TERMINAL_NO_TRANSITIONS
        )

    if event is RunEvent.REQUEST_TOOL:
        if not tool_authorized:
            return TransitionVerdict(
                allowed=False, to_phase=RunPhase.REASONING, reason_code=TOOL_NOT_AUTHORIZED
            )
        if duplicate_tool_call:
            return TransitionVerdict(
                allowed=False, to_phase=RunPhase.REASONING, reason_code=DUPLICATE_TOOL_CALL
            )
        if budget_exhausted:
            return TransitionVerdict(
                allowed=False,
                to_phase=RunPhase.READY_TO_FINALIZE,
                reason_code=BUDGET_EXHAUSTED,
            )
        return TransitionVerdict(
            allowed=True, to_phase=RunPhase.ACTING, reason_code=TOOL_AUTHORIZED
        )

    if event is RunEvent.REQUEST_RETRIEVAL:
        if budget_exhausted:
            return TransitionVerdict(
                allowed=False,
                to_phase=RunPhase.READY_TO_FINALIZE,
                reason_code=BUDGET_EXHAUSTED,
            )
        return TransitionVerdict(
            allowed=True, to_phase=RunPhase.RETRIEVING, reason_code=RETRIEVAL_ALLOWED
        )

    if event is RunEvent.REQUEST_FINALIZE:
        if requires_deterministic and not authority_present:
            # Fail-closed: una consulta ejecutable sin autoridad no finaliza
            # con conclusión binaria; termina no concluyente por código.
            return TransitionVerdict(
                allowed=True,
                to_phase=RunPhase.UNDETERMINED,
                reason_code=AUTHORITY_MISSING_FOR_EXECUTABLE,
            )
        if analysis_incomplete:
            return TransitionVerdict(
                allowed=False,
                to_phase=RunPhase.REASONING,
                reason_code=ANALYSIS_INCOMPLETE,
            )
        if budget_exhausted:
            return TransitionVerdict(
                allowed=True,
                to_phase=RunPhase.FINALIZED,
                reason_code=(
                    BUDGET_EXHAUSTED_WITH_EVIDENCE
                    if evidence_available
                    else LIMIT_REACHED_WITHOUT_EVIDENCE
                ),
            )
        return TransitionVerdict(
            allowed=True, to_phase=RunPhase.FINALIZED, reason_code=READY_TO_FINALIZE
        )

    # OBSERVE_TOOL_RESULT: política de retry por tipo de fallo.
    if tool_failure == "transient":
        return TransitionVerdict(
            allowed=True, to_phase=RunPhase.REASONING, reason_code=TOOL_RETRY_ALLOWED
        )
    if tool_failure == "permanent":
        return TransitionVerdict(
            allowed=False,
            to_phase=RunPhase.REASONING,
            reason_code=TOOL_FAILED_PERMANENT_NO_RETRY,
        )
    return TransitionVerdict(
        allowed=True, to_phase=RunPhase.REASONING, reason_code=TOOL_RESULT_OBSERVED
    )


__all__ = [
    "RUN_GUARDS_VERSION",
    "RunEvent",
    "TransitionVerdict",
    "evaluate_transition",
]
