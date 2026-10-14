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
#
# Clasificación (P1-G): cada veredicto declara su clase en `GUARD_CLASS` y la
# autoridad canónica que lo aplica aunque el flag de enforcement esté `off`
# (`GUARD_CANONICAL_ENFORCER`). SECURITY/CORRECTNESS duplican autoridades que
# corren siempre; RESOURCE respeta `RunBudgetLedger`; QUALITY queda advisory.
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


class GuardClass(StrEnum):
    """Clasificación de cada veredicto de la tabla (P1-G del hardening).

    SECURITY/CORRECTNESS: el veredicto DUPLICA una autoridad canónica que corre
    siempre (registro de tools, política del cierre, ledger). El flag de
    enforcement (`RUNTIME_RUN_GUARDS_ENFORCE`) puede dejarlos advisory sin
    abrir un hueco: la autoridad canónica sigue bloqueando.
    RESOURCE: respeta la autoridad canónica de `RunBudgetLedger`.
    QUALITY/EXPERIMENTAL: advisory por diseño (observabilidad/retry).
    """

    SECURITY = "SECURITY"
    CORRECTNESS = "CORRECTNESS"
    RESOURCE = "RESOURCE"
    QUALITY = "QUALITY"
    EXPERIMENTAL = "EXPERIMENTAL"


#: Clase de cada reason_code emitible por la tabla. Un código nuevo en la tabla
#: SIN clase rompe `test_run_guards_classification`: es deuda de autoridad.
GUARD_CLASS: dict[str, GuardClass] = {
    TOOL_NOT_AUTHORIZED: GuardClass.SECURITY,
    TOOL_AUTHORIZED: GuardClass.SECURITY,
    AUTHORITY_MISSING_FOR_EXECUTABLE: GuardClass.SECURITY,
    TERMINAL_NO_TRANSITIONS: GuardClass.CORRECTNESS,
    ANALYSIS_INCOMPLETE: GuardClass.CORRECTNESS,
    READY_TO_FINALIZE: GuardClass.CORRECTNESS,
    RETRIEVAL_ALLOWED: GuardClass.CORRECTNESS,
    BUDGET_EXHAUSTED: GuardClass.RESOURCE,
    BUDGET_EXHAUSTED_WITH_EVIDENCE: GuardClass.RESOURCE,
    LIMIT_REACHED_WITHOUT_EVIDENCE: GuardClass.RESOURCE,
    DUPLICATE_TOOL_CALL: GuardClass.QUALITY,
    TOOL_RETRY_ALLOWED: GuardClass.QUALITY,
    TOOL_FAILED_PERMANENT_NO_RETRY: GuardClass.QUALITY,
    TOOL_RESULT_OBSERVED: GuardClass.QUALITY,
}

#: Autoridad canónica que aplica la clase aunque el flag de guards esté `off`.
#: Vacío = no hay autoridad canónica equivalente: el veredicto necesitaría el
#: flag encendido (hoy: ninguno; QUALITY/EXPERIMENTAL son advisory por diseño).
GUARD_CANONICAL_ENFORCER: dict[GuardClass, str] = {
    GuardClass.SECURITY: (
        "src.agents.tools.registry.tool_allowed"
        " + src.runtime.finalization_policy.resolve_closure_phase"
    ),
    GuardClass.CORRECTNESS: "src.runtime.finalization_policy.resolve_closure_phase",
    GuardClass.RESOURCE: "src.runtime.run_budget.RunBudgetLedger",
    GuardClass.QUALITY: "",
    GuardClass.EXPERIMENTAL: "",
}

#: Clases que el flag de guards puede dejar advisory sin abrir un hueco.
ADVISORY_CLASSES: frozenset[GuardClass] = frozenset(
    {GuardClass.QUALITY, GuardClass.EXPERIMENTAL}
)


def guard_class(reason_code: str) -> GuardClass | None:
    return GUARD_CLASS.get(str(reason_code or ""))


def requires_guard_enforcement(reason_code: str) -> bool:
    """¿El veredicto necesita el flag de guards (no tiene autoridad canónica)?"""
    klass = guard_class(reason_code)
    if klass is None:
        return True  # desconocido: fail-closed del lado del enforcement
    return not GUARD_CANONICAL_ENFORCER.get(klass, "")


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
    "ADVISORY_CLASSES",
    "GUARD_CANONICAL_ENFORCER",
    "GUARD_CLASS",
    "RUN_GUARDS_VERSION",
    "GuardClass",
    "RunEvent",
    "TransitionVerdict",
    "evaluate_transition",
    "guard_class",
    "requires_guard_enforcement",
]
