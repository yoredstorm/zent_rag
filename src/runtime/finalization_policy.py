# =============================================================================
# Finalization Policy — resolución de autoridad del run.
# =============================================================================
# Responde «¿puede responder este run?» combinando señales que YA produjeron
# los gates especializados (evidence, reasoning, deterministic authority,
# budget, termination, JEV) y devolviendo una ACCIÓN con nivel de autoridad,
# reason_code y observabilidad de la resolución (señales, ignoradas, conflictos).
#
# NO reimplementa gates: no recalcula evidencia, no juzga, no genera.
# Es el punto único donde se resuelve QUIÉN manda entre señales contradictorias.
#
# Jerarquía (mayor manda): SAFETY > DETERMINISTIC > EVIDENCE > REASONING >
# TERMINATION > GENERATION. El nivel RESOURCE cubre cortes por presupuesto.
#
# Reglas duras:
#   - JEV nunca autoriza ni ejecuta: puede pedir cautela, no decidir.
#   - Una decisión determinista autoritativa no se anula con narrativa.
#   - Retrieval fallido != evidencia insuficiente (realidades distintas).
#   - Consulta ejecutable sin autoridad determinista => UNDETERMINED, jamás
#     una conclusión binaria libre.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from src.runtime.enforcement import (
    ENFORCE_STAGES as ENFORCE_STAGES_IMPL,
)
from src.runtime.enforcement import (
    enforcement_stages,
)
from src.runtime.enforcement import (
    should_hold_trigger as _should_hold_trigger,
)
from src.runtime.reason_codes import (
    AUTHORITY_MISSING_FOR_EXECUTABLE,
    AUTHORITY_MISSING_RETRIEVE,
    BUDGET_EXHAUSTED_WITH_EVIDENCE,
    BUDGET_EXHAUSTED_WITHOUT_EVIDENCE,
    DETERMINISTIC_AUTHORITY,
    EVIDENCE_INCOMPLETE,
    EVIDENCE_INCOMPLETE_LIMITED,
    EVIDENCE_INSUFFICIENT,
    JEV_ONLY_NEGATIVE_SIGNAL,
    JEV_POSITIVE_WITHOUT_EVIDENCE,
    NEED_DRAFT,
    READY,
    REASONING_INCOMPLETE,
    REASONING_INCOMPLETE_OVERRIDDEN_BY_AUTHORITY,
    RETRIEVAL_UNAVAILABLE,
    TERMINATION_SATISFIED,
    TERMINATION_VS_INCOMPLETE_REASONING,
    TERMINATION_WITHOUT_DRAFT,
    TOOL_AUTHORIZED,
    TOOL_NOT_AUTHORIZED,
    TOOL_OUTSIDE_ALLOWLIST,
)
from src.runtime.run_state import TERMINAL_PHASES, AgentRunState, RunPhase

FINALIZATION_POLICY_VERSION = "finalization-policy-1"


class FinalizationAction(StrEnum):
    CONTINUE = "CONTINUE"
    RETRIEVE_MORE = "RETRIEVE_MORE"
    USE_TOOL = "USE_TOOL"
    FINALIZE = "FINALIZE"
    ABSTAIN = "ABSTAIN"
    BLOCK = "BLOCK"
    UNDETERMINED = "UNDETERMINED"


class AuthorityLevel(StrEnum):
    SAFETY = "SAFETY"
    DETERMINISTIC = "DETERMINISTIC"
    EVIDENCE = "EVIDENCE"
    REASONING = "REASONING"
    TERMINATION = "TERMINATION"
    GENERATION = "GENERATION"
    RESOURCE = "RESOURCE"


#: Aprobaciones JEV que NUNCA habilitan una respuesta por sí solas.
_JEV_AFFIRMATIVE = frozenset({"yes", "si", "sí", "approve", "approve_with_limits"})
#: Veredictos JEV que son solo cautela: no anulan autoridad ni evidencia.
_JEV_NEGATIVE = frozenset({"no", "negar", "deny", "uncertain", "uncertainty"})


@dataclass(frozen=True, kw_only=True)
class FinalizationDecision:
    """Resolución explícita de autoridad con trazabilidad completa."""

    action: FinalizationAction
    reason_code: str
    authority: AuthorityLevel
    signals: dict = field(default_factory=dict)
    signals_ignored: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    missing_requirements: tuple[str, ...] = ()
    limited: bool = False
    version: str = FINALIZATION_POLICY_VERSION

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "action": str(self.action),
            "reason_code": self.reason_code,
            "authority": str(self.authority),
            "signals": dict(self.signals),
            "signals_ignored": list(self.signals_ignored),
            "conflicts": list(self.conflicts),
            "missing_requirements": list(self.missing_requirements),
            "limited": self.limited,
        }


def _missing_requirements(state: AgentRunState) -> tuple[str, ...]:
    sufficiency = state.evidence.sufficiency
    if sufficiency is None:
        return ()
    missing = [
        *(getattr(sufficiency, "missing_entities", ()) or ()),
        *(getattr(sufficiency, "missing_anchors", ()) or ()),
    ]
    return tuple(str(item) for item in missing if str(item or "").strip())


def _signals(
    state: AgentRunState,
    *,
    tool_requested: bool,
    tool_authorized: bool | None,
    retrieval_possible: bool,
    termination_requested: bool,
    draft_available: bool,
    jev_verdict: str | None,
) -> dict:
    evidence = state.evidence
    decisions = state.decisions
    if evidence.retrieval_failed and not evidence.complete:
        evidence_signal = "failed"
    elif evidence.insufficient:
        evidence_signal = "insufficient"
    elif evidence.complete:
        evidence_signal = "complete"
    else:
        evidence_signal = "unknown"
    authority_signal = (
        "authoritative"
        if decisions.authoritative
        else (
            "external"
            if decisions.external_authority
            else ("missing" if decisions.requires_deterministic else "not_required")
        )
    )
    return {
        "evidence": evidence_signal,
        "reasoning": (
            "incomplete" if state.reasoning.blocks_early_answer else "complete"
        ),
        "authority": authority_signal,
        "budget": "exhausted" if state.budget.exhausted else "ok",
        "jev": str(jev_verdict or "not_applicable"),
        "termination": "requested" if termination_requested else "not_requested",
        "draft": "available" if draft_available else "missing",
        "retrieval": (
            "failed"
            if evidence.retrieval_failed
            else ("possible" if retrieval_possible else "exhausted")
        ),
        "tool": (
            "requested" if tool_requested else "not_requested"
        ),
        "tool_authorized": str(bool(tool_authorized)),
    }


def evaluate_finalization(
    state: AgentRunState,
    *,
    tool_requested: bool = False,
    tool_authorized: bool | None = None,
    retrieval_possible: bool = True,
    termination_requested: bool = False,
    draft_available: bool = False,
    jev_verdict: str | None = None,
) -> FinalizationDecision:
    """Resuelve la autoridad del run y devuelve la acción con su razón.

    Los gates siguen siendo especializados; acá solo se decide quién manda
    cuando sus señales conviven (y qué señales se ignoran y por qué).
    """
    signals = _signals(
        state,
        tool_requested=tool_requested,
        tool_authorized=tool_authorized,
        retrieval_possible=retrieval_possible,
        termination_requested=termination_requested,
        draft_available=draft_available,
        jev_verdict=jev_verdict,
    )
    ignored: list[str] = []
    conflicts: list[str] = []
    missing = _missing_requirements(state)
    evidence = state.evidence
    decisions = state.decisions
    budget = state.budget
    jev = str(jev_verdict or "").strip().lower()

    def note_ignored(code: str) -> None:
        if code not in ignored:
            ignored.append(code)

    def decide(
        action: FinalizationAction,
        reason: str,
        authority: AuthorityLevel,
        *,
        limited: bool = False,
    ) -> FinalizationDecision:
        # Observabilidad: un veredicto JEV negativo que no manda se registra
        # como señal ignorada (nunca abstiene por sí solo con evidencia).
        if (
            action is FinalizationAction.FINALIZE
            and jev in _JEV_NEGATIVE
            and evidence.complete
        ):
            note_ignored("jev_only_negative_signal")
        return FinalizationDecision(
            action=action,
            reason_code=reason,
            authority=authority,
            signals=signals,
            signals_ignored=tuple(ignored),
            conflicts=tuple(conflicts),
            missing_requirements=missing,
            limited=limited,
        )

    # 1. SAFETY / AUTHORIZATION: ninguna acción se ejecuta sin autorización.
    if state.tools.calls_outside_allowlist():
        return decide(
            FinalizationAction.BLOCK, TOOL_OUTSIDE_ALLOWLIST, AuthorityLevel.SAFETY
        )
    if tool_requested:
        if not tool_authorized:
            return decide(
                FinalizationAction.CONTINUE, TOOL_NOT_AUTHORIZED, AuthorityLevel.SAFETY
            )
        return decide(FinalizationAction.USE_TOOL, TOOL_AUTHORIZED, AuthorityLevel.SAFETY)

    # 2. DETERMINISTIC AUTHORITY: no se anula con narrativa ni con JEV.
    #    Incluye la autoridad externa registrada (SQL-first, DAG cognitivo,
    #    extractivo): es determinista aunque no porte DecisionEnvelope.
    if decisions.authoritative or decisions.external_authority:
        if jev in _JEV_NEGATIVE:
            note_ignored(JEV_ONLY_NEGATIVE_SIGNAL)
        if state.reasoning.blocks_early_answer:
            note_ignored(REASONING_INCOMPLETE_OVERRIDDEN_BY_AUTHORITY)
        return decide(
            FinalizationAction.FINALIZE, DETERMINISTIC_AUTHORITY, AuthorityLevel.DETERMINISTIC
        )
    if decisions.requires_deterministic and state.phase not in TERMINAL_PHASES:
        if jev in _JEV_NEGATIVE and evidence.complete:
            note_ignored(JEV_ONLY_NEGATIVE_SIGNAL)
        if retrieval_possible and not budget.exhausted and evidence.insufficient:
            return decide(
                FinalizationAction.RETRIEVE_MORE,
                AUTHORITY_MISSING_RETRIEVE,
                AuthorityLevel.DETERMINISTIC,
            )
        return decide(
            FinalizationAction.UNDETERMINED,
            AUTHORITY_MISSING_FOR_EXECUTABLE,
            AuthorityLevel.DETERMINISTIC,
        )

    # 3. RETRIEVAL FAILURE: fallo operativo, nunca «no hay datos».
    if evidence.retrieval_failed and not evidence.complete:
        if jev in _JEV_AFFIRMATIVE:
            ignored.append(JEV_POSITIVE_WITHOUT_EVIDENCE)
        return decide(
            FinalizationAction.BLOCK, RETRIEVAL_UNAVAILABLE, AuthorityLevel.EVIDENCE
        )

    # 4. BUDGET: con evidencia se cierra degradado; sin evidencia se limita.
    if budget.exhausted:
        if evidence.complete or evidence.can_answer:
            return decide(
                FinalizationAction.FINALIZE,
                BUDGET_EXHAUSTED_WITH_EVIDENCE,
                AuthorityLevel.RESOURCE,
                limited=True,
            )
        return decide(
            FinalizationAction.BLOCK,
            BUDGET_EXHAUSTED_WITHOUT_EVIDENCE,
            AuthorityLevel.RESOURCE,
        )

    # 5. EVIDENCE SUFFICIENCY.
    if evidence.insufficient:
        if jev in _JEV_AFFIRMATIVE:
            ignored.append(JEV_POSITIVE_WITHOUT_EVIDENCE)
        if retrieval_possible:
            return decide(
                FinalizationAction.RETRIEVE_MORE, EVIDENCE_INCOMPLETE, AuthorityLevel.EVIDENCE
            )
        if draft_available:
            return decide(
                FinalizationAction.FINALIZE,
                EVIDENCE_INCOMPLETE_LIMITED,
                AuthorityLevel.EVIDENCE,
                limited=True,
            )
        return decide(
            FinalizationAction.ABSTAIN, EVIDENCE_INSUFFICIENT, AuthorityLevel.EVIDENCE
        )

    # 6. REASONING COMPLETENESS: análisis complejo incompleto no concluye.
    if state.reasoning.blocks_early_answer:
        if termination_requested:
            conflicts.append(TERMINATION_VS_INCOMPLETE_REASONING)
        return decide(
            FinalizationAction.CONTINUE, REASONING_INCOMPLETE, AuthorityLevel.REASONING
        )

    # 7. TERMINATION.
    if termination_requested:
        if draft_available:
            return decide(
                FinalizationAction.FINALIZE, TERMINATION_SATISFIED, AuthorityLevel.TERMINATION
            )
        return decide(
            FinalizationAction.CONTINUE, TERMINATION_WITHOUT_DRAFT, AuthorityLevel.TERMINATION
        )

    # 8. GENERATION: sin señales negativas, se puede finalizar con borrador.
    if draft_available:
        return decide(FinalizationAction.FINALIZE, READY, AuthorityLevel.GENERATION)
    return decide(FinalizationAction.CONTINUE, NEED_DRAFT, AuthorityLevel.GENERATION)


#: Acción esperada por fase terminal (para verificar acuerdo en el cierre).
_EXPECTED_ACTIONS: dict[RunPhase, frozenset[FinalizationAction]] = {
    RunPhase.FINALIZED: frozenset({FinalizationAction.FINALIZE}),
    RunPhase.LIMIT_REACHED: frozenset({FinalizationAction.FINALIZE}),
    RunPhase.ABSTAINED: frozenset({FinalizationAction.ABSTAIN}),
    RunPhase.UNDETERMINED: frozenset({FinalizationAction.UNDETERMINED}),
    RunPhase.BLOCKED: frozenset({FinalizationAction.BLOCK}),
}


def expected_actions_for_phase(phase: RunPhase) -> frozenset[FinalizationAction]:
    return _EXPECTED_ACTIONS.get(phase, frozenset())


def gate_abstention_action(
    state: AgentRunState, *, draft_available: bool
) -> str:
    """Qué hacer cuando JEV quiere abstenerse y no hay envelope determinista.

    La política manda: si la evidencia canónica ALCANZA (completa o `can_answer`),
    se responde con límites y la señal JEV queda registrada como ignorada. Si la
    evidencia es insuficiente o el retrieval falló, la abstención se mantiene
    (responder un draft sin respaldo violaría evidence-first).
    """
    if state.evidence.retrieval_failed and not state.evidence.complete:
        return "abstain"
    if not (state.evidence.complete or state.evidence.can_answer):
        return "abstain"
    decision = evaluate_finalization(
        state,
        draft_available=draft_available,
        retrieval_possible=False,
        jev_verdict="no",
    )
    return (
        "answer_with_limits"
        if decision.action is FinalizationAction.FINALIZE
        else "abstain"
    )


def decision_matches_terminal(
    decision: FinalizationDecision, phase: RunPhase
) -> bool:
    """¿La resolución coincide con la fase terminal del run?"""
    expected = _EXPECTED_ACTIONS.get(phase)
    if expected is None:
        return decision.action in (
            FinalizationAction.CONTINUE,
            FinalizationAction.RETRIEVE_MORE,
            FinalizationAction.USE_TOOL,
        )
    return decision.action in expected


#: Etapas de enforcement válidas (mismas que el shadow). La resolución de scopes
#: (agente > org > environment > global) vive en `src/runtime/enforcement.py`.
ENFORCE_STAGES: frozenset[str] = ENFORCE_STAGES_IMPL


def enforced_stages(settings: object) -> frozenset[str]:
    """Etapas con enforcement activo para un scope global (compat/observabilidad).

    Para scopes por agente/org usar `enforcement.enforcement_stages`.
    """
    return enforcement_stages(settings)


def should_hold_trigger(*args: object, **kwargs: object) -> bool:
    """Re-export del hold acotado (ver `src.runtime.enforcement`)."""
    return _should_hold_trigger(*args, **kwargs)


#: Acción que la ruta vigente ejecutaba por fase terminal. Solo alimenta la
#: métrica de divergencia: la política nunca decide con esto.
LEGACY_ACTION_BY_PHASE: dict[RunPhase, str] = {
    RunPhase.FINALIZED: "FINALIZE",
    RunPhase.LIMIT_REACHED: "FINALIZE",
    RunPhase.ABSTAINED: "ABSTAIN",
    RunPhase.UNDETERMINED: "UNDETERMINED",
    RunPhase.BLOCKED: "BLOCK",
    RunPhase.FAILED: "FAILED",
}


def legacy_action_for_phase(phase: RunPhase) -> str:
    return LEGACY_ACTION_BY_PHASE.get(phase, "UNKNOWN")


def _emit_divergence(
    stage: str, decision: FinalizationDecision, *, legacy_action: str = ""
) -> None:
    """Contador de divergencia (fail-soft). Emite el contrato nuevo y el alias.

    `policy_action` es lo que resolvió la política; `legacy_action` lo que la
    ruta vigente ejecuta(ba). El alias `zent_finalization_shadow_divergence_total`
    se mantiene 1 release para no romper scrapes existentes.
    """
    policy_action = str(decision.action)
    try:
        from src.infrastructure.observability.metrics import (
            zent_finalization_divergence_total,
            zent_finalization_shadow_divergence_total,
        )

        zent_finalization_divergence_total.labels(
            stage=str(stage),
            policy_action=policy_action,
            legacy_action=str(legacy_action or ""),
            reason_code=str(decision.reason_code),
        ).inc()
        zent_finalization_shadow_divergence_total.labels(
            stage=str(stage),
            action=policy_action,
            reason_code=str(decision.reason_code),
        ).inc()
    except Exception:  # noqa: BLE001 — observabilidad, nunca rompe el run
        pass


def resolve_closure(
    state: AgentRunState,
    *,
    draft_available: bool,
    retrieval_possible: bool = False,
) -> FinalizationDecision:
    """Resuelve el cierre y publica la resolución en el estado (observabilidad).

    No cambia la respuesta: el cambio, si corresponde, lo aplica el modo
    estricto o el enforcement del trigger. Fuente única para agente y RAG.
    """
    decision = evaluate_finalization(
        state,
        draft_available=draft_available,
        retrieval_possible=retrieval_possible,
    )
    state.decisions.finalization = decision.to_public_dict()
    return decision


def observe_shadow_divergence(
    decision: FinalizationDecision, phase: RunPhase
) -> bool:
    """Métrica de divergencia del cierre (fail-soft, nunca rompe el run).

    Devuelve True si hubo divergencia. El gate de adopción por etapas exige
    cero divergencias sobre el corpus antes de convertir una señal en autoridad.
    """
    if decision_matches_terminal(decision, phase):
        return False
    _emit_divergence(
        "closure", decision, legacy_action=legacy_action_for_phase(phase)
    )
    return True


def observe_trigger_shadow(
    state: AgentRunState,
    *,
    stage: str,
    intended: str,
    retrieval_possible: bool,
    draft_available: bool,
    tool_requested: bool = False,
    tool_authorized: bool | None = None,
    termination_requested: bool = False,
) -> FinalizationDecision:
    """Shadow a nivel TRIGGER: la ruta vigente va a cerrar; ¿la política acompaña?

    `intended` es la acción que la ruta vigente ejecutará (FINALIZE para el
    trigger de termination; ABSTAIN/BLOCK/UNDETERMINED para el gate del
    borrador; FINALIZE para la etapa answer_gate). Divergencia = la política
    resuelve una acción distinta a la esperada por el trigger. A diferencia del
    cierre (que evalúa con `retrieval_possible=False`), acá el presupuesto de
    búsqueda todavía importa: detecta cierres prematuros que el shadow del
    cierre no puede ver.
    """
    decision = evaluate_finalization(
        state,
        tool_requested=tool_requested,
        tool_authorized=tool_authorized,
        retrieval_possible=retrieval_possible,
        termination_requested=termination_requested,
        draft_available=draft_available,
    )
    if str(decision.action) != str(intended):
        _emit_divergence(stage, decision, legacy_action=str(intended))
    return decision


__all__ = [
    "AuthorityLevel",
    "ENFORCE_STAGES",
    "FINALIZATION_POLICY_VERSION",
    "FinalizationAction",
    "FinalizationDecision",
    "LEGACY_ACTION_BY_PHASE",
    "decision_matches_terminal",
    "enforced_stages",
    "enforcement_stages",
    "evaluate_finalization",
    "expected_actions_for_phase",
    "gate_abstention_action",
    "legacy_action_for_phase",
    "observe_shadow_divergence",
    "observe_trigger_shadow",
    "resolve_closure",
    "should_hold_trigger",
]
