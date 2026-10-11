# =============================================================================
# Hardening adversarial — propiedades de la resolución de autoridad (P8)
# =============================================================================
# No verifica happy paths: cruza evidencia × autoridad × presupuesto ×
# razonamiento × borrador × ejecutable y comprueba invariantes de la política.
from __future__ import annotations

from itertools import product
from types import SimpleNamespace

import pytest

from src.runtime.finalization_policy import (
    FinalizationAction,
    evaluate_finalization,
)
from src.runtime.run_state import AgentRunState, RunIdentity

_EVIDENCE = ("complete", "insufficient", "failed", "unknown")
_AUTHORITY = ("none", "positive", "negative")
_MATRIX = list(
    product(_EVIDENCE, _AUTHORITY, (False, True), (False, True), (False, True), (False, True))
)


def _state(
    *,
    evidence: str,
    authority: str,
    budget_exhausted: bool,
    reasoning_incomplete: bool,
    requires_deterministic: bool,
) -> AgentRunState:
    state = AgentRunState(identity=RunIdentity(run_id="adversarial"))
    if evidence == "complete":
        state.evidence.observe(
            sufficiency=SimpleNamespace(
                evidence_complete=True,
                recommended_action="generate",
                missing_entities=(),
                missing_anchors=(),
            )
        )
    elif evidence == "insufficient":
        state.evidence.observe(
            sufficiency=SimpleNamespace(
                evidence_complete=False,
                recommended_action="retrieve_more",
                missing_entities=("campo_x",),
                missing_anchors=("&&&F",),
            )
        )
    elif evidence == "failed":
        state.evidence.retrieval_failed = True
    if authority == "positive":
        state.decisions.set_envelope(SimpleNamespace(authoritative=True, state="MATCH"))
    elif authority == "negative":
        state.decisions.set_envelope(
            SimpleNamespace(authoritative=True, state="NO_MATCH")
        )
    state.decisions.requires_deterministic = requires_deterministic
    if reasoning_incomplete:
        state.reasoning.run = SimpleNamespace(
            enabled=True,
            is_complex=True,
            analysis_complete=False,
            blocks_early_answer=True,
        )
    if budget_exhausted:
        state.budget.ledger = SimpleNamespace(
            remaining_tokens=0, remaining_cost_usd=None
        )
    return state


@pytest.mark.parametrize(
    "evidence,authority,budget,reasoning,draft,executable", _MATRIX
)
def test_propiedades_de_resolucion(
    evidence: str,
    authority: str,
    budget: bool,
    reasoning: bool,
    draft: bool,
    executable: bool,
) -> None:
    state = _state(
        evidence=evidence,
        authority=authority,
        budget_exhausted=budget,
        reasoning_incomplete=reasoning,
        requires_deterministic=executable,
    )
    decision = evaluate_finalization(
        state,
        draft_available=draft,
        retrieval_possible=False,
        jev_verdict="uncertain",
    )

    # Forma: acción válida y razón siempre presente.
    assert isinstance(decision.action, FinalizationAction)
    assert decision.reason_code
    assert decision.signals

    # Una acción de tool nunca aparece sin pedido explícito.
    assert decision.action is not FinalizationAction.USE_TOOL

    # Autoridad positiva: nunca se anula (ni JEV, ni razonamiento, ni budget).
    if authority == "positive":
        assert decision.action is FinalizationAction.FINALIZE

    # Ejecutable sin autoridad: nunca fin libre ni abstención documental.
    if executable and authority == "none":
        assert decision.action in (
            FinalizationAction.RETRIEVE_MORE,
            FinalizationAction.UNDETERMINED,
        )

    # Retrieval fallido sin autoridad y sin exigencia ejecutable: BLOCK
    # operativo, no insuficiencia documental.
    if evidence == "failed" and authority == "none" and not executable:
        assert decision.action is FinalizationAction.BLOCK
        assert decision.reason_code == "RETRIEVAL_UNAVAILABLE"

    # Budget agotado (no ejecutable, sin autoridad): nunca CONTINUE.
    if budget and authority == "none" and not executable:
        assert decision.action in (
            FinalizationAction.FINALIZE,
            FinalizationAction.BLOCK,
        )

    # JEV negativo nunca es la única señal que abstiene con evidencia completa.
    if (
        evidence == "complete"
        and authority == "none"
        and not budget
        and not reasoning
        and not executable
        and draft
    ):
        assert decision.action is FinalizationAction.FINALIZE


def test_resolucion_estable_100_runs() -> None:
    """Misma entrada => misma decisión semántica (sin narrativa de por medio)."""
    state = _state(
        evidence="complete",
        authority="none",
        budget_exhausted=False,
        reasoning_incomplete=False,
        requires_deterministic=False,
    )
    first = evaluate_finalization(state, draft_available=True).to_public_dict()
    for _ in range(100):
        again = evaluate_finalization(state, draft_available=True).to_public_dict()
        assert again == first


def test_ejecutable_sin_autoridad_jamas_decide_binario() -> None:
    for evidence in _EVIDENCE:
        state = _state(
            evidence=evidence,
            authority="none",
            budget_exhausted=False,
            reasoning_incomplete=False,
            requires_deterministic=True,
        )
        for retrieval_possible in (False, True):
            decision = evaluate_finalization(
                state, retrieval_possible=retrieval_possible
            )
            assert decision.action in (
                FinalizationAction.RETRIEVE_MORE,
                FinalizationAction.UNDETERMINED,
            )


class TestToolSecurity:
    def test_tool_denegado_no_se_ejecuta_nunca(self) -> None:
        state = _state(
            evidence="complete",
            authority="none",
            budget_exhausted=False,
            reasoning_incomplete=False,
            requires_deterministic=False,
        )
        for requested in (False, True):
            for authorized in (False, True, None):
                decision = evaluate_finalization(
                    state, tool_requested=requested, tool_authorized=authorized
                )
                if decision.action is FinalizationAction.USE_TOOL:
                    assert requested is True and authorized is True
                if requested and not authorized:
                    assert decision.action is FinalizationAction.CONTINUE
                    assert decision.reason_code == "TOOL_NOT_AUTHORIZED"

    def test_loop_guard_bloquea_mismo_run_y_permite_run_nuevo(self) -> None:
        from src.core.domain.intelligence import ToolFingerprint
        from src.intelligence.loop_guard import LoopGuard

        fingerprint = ToolFingerprint.compute(
            tool="echo",
            source=None,
            arguments={"text": "x"},
            query="q",
            agent_id="a",
            organization_id="o",
        )
        same_run = LoopGuard()
        assert same_run.check(fingerprint) is True
        assert same_run.check(fingerprint) is False
        new_run = LoopGuard()
        assert new_run.check(fingerprint) is True
