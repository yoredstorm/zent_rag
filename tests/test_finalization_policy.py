# =============================================================================
# Finalization Policy — jerarquía de autoridad y casos del prompt
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace

from src.runtime.finalization_policy import (
    AuthorityLevel,
    FinalizationAction,
    decision_matches_terminal,
    evaluate_finalization,
)
from src.runtime.run_state import AgentRunState, RunIdentity, RunPhase


def _state(
    *,
    evidence: str = "unknown",
    reasoning_incomplete: bool = False,
    authority: str = "none",
    requires_deterministic: bool = False,
    budget_exhausted: bool = False,
) -> AgentRunState:
    state = AgentRunState(identity=RunIdentity(run_id="run-1"))
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
                missing_anchors=(),
            )
        )
    elif evidence == "failed":
        state.evidence.retrieval_failed = True
    if authority == "positive":
        state.decisions.set_envelope(
            SimpleNamespace(authoritative=True, state="MATCH")
        )
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


class TestPromptCases:
    def test_evidencia_completa_jev_duda_no_abstiene(self) -> None:
        decision = evaluate_finalization(
            _state(evidence="complete"),
            jev_verdict="uncertain",
            draft_available=True,
        )
        assert decision.action is FinalizationAction.FINALIZE
        assert "jev_only_negative_signal" in decision.signals_ignored

    def test_evidencia_incompleta_llm_quiere_responder(self) -> None:
        retrieving = evaluate_finalization(_state(evidence="insufficient"))
        assert retrieving.action is FinalizationAction.RETRIEVE_MORE
        limited = evaluate_finalization(
            _state(evidence="insufficient"),
            retrieval_possible=False,
            draft_available=True,
        )
        assert limited.action is FinalizationAction.FINALIZE
        assert limited.limited is True
        assert limited.reason_code == "EVIDENCE_INCOMPLETE_LIMITED"
        abstained = evaluate_finalization(
            _state(evidence="insufficient"), retrieval_possible=False
        )
        assert abstained.action is FinalizationAction.ABSTAIN

    def test_envelope_positivo_llm_incertidumbre_conserva_decision(self) -> None:
        state = _state(
            authority="positive",
            requires_deterministic=True,
            reasoning_incomplete=True,
        )
        decision = evaluate_finalization(
            state,
            jev_verdict="uncertain",
            draft_available=True,
        )
        assert decision.action is FinalizationAction.FINALIZE
        assert decision.authority is AuthorityLevel.DETERMINISTIC
        assert "jev_only_negative_signal" in decision.signals_ignored
        assert (
            "reasoning_incomplete_overridden_by_authority"
            in decision.signals_ignored
        )

    def test_envelope_negativo_no_se_invierte(self) -> None:
        state = _state(authority="negative", requires_deterministic=True)
        decision = evaluate_finalization(state, draft_available=True)
        assert decision.action is FinalizationAction.FINALIZE
        assert decision.reason_code == "DETERMINISTIC_AUTHORITY"

    def test_retrieval_fallido_no_es_insuficiencia(self) -> None:
        decision = evaluate_finalization(
            _state(evidence="failed"), jev_verdict="approve"
        )
        assert decision.action is FinalizationAction.BLOCK
        assert decision.reason_code == "RETRIEVAL_UNAVAILABLE"
        assert "jev_positive_without_evidence" in decision.signals_ignored

    def test_budget_agotado_con_evidencia_cierra_degradado(self) -> None:
        decision = evaluate_finalization(
            _state(evidence="complete", budget_exhausted=True),
            draft_available=True,
        )
        assert decision.action is FinalizationAction.FINALIZE
        assert decision.reason_code == "BUDGET_EXHAUSTED_WITH_EVIDENCE"
        assert decision.limited is True
        assert decision.authority is AuthorityLevel.RESOURCE

    def test_budget_agotado_sin_evidencia_limita(self) -> None:
        decision = evaluate_finalization(
            _state(evidence="unknown", budget_exhausted=True)
        )
        assert decision.action is FinalizationAction.BLOCK
        assert decision.reason_code == "BUDGET_EXHAUSTED_WITHOUT_EVIDENCE"

    def test_reasoning_incompleto_no_responde(self) -> None:
        decision = evaluate_finalization(
            _state(evidence="complete", reasoning_incomplete=True),
            draft_available=True,
        )
        assert decision.action is FinalizationAction.CONTINUE
        assert decision.reason_code == "REASONING_INCOMPLETE"

    def test_informacional_no_aplica_fail_closed(self) -> None:
        decision = evaluate_finalization(
            _state(evidence="complete", requires_deterministic=False),
            draft_available=True,
        )
        assert decision.action is FinalizationAction.FINALIZE
        assert decision.reason_code == "READY"

    def test_ejecutable_sin_autoridad_es_undetermined(self) -> None:
        state = _state(
            evidence="complete",
            requires_deterministic=True,
        )
        decision = evaluate_finalization(state, draft_available=True)
        assert decision.action is FinalizationAction.UNDETERMINED
        assert decision.reason_code == "AUTHORITY_MISSING_FOR_EXECUTABLE"
        assert decision.authority is AuthorityLevel.DETERMINISTIC


class TestSafetyAndObservability:
    def test_tool_sin_autorizacion_no_se_ejecuta(self) -> None:
        denied = evaluate_finalization(
            _state(), tool_requested=True, tool_authorized=False
        )
        assert denied.action is FinalizationAction.CONTINUE
        assert denied.reason_code == "TOOL_NOT_AUTHORIZED"
        allowed = evaluate_finalization(
            _state(), tool_requested=True, tool_authorized=True
        )
        assert allowed.action is FinalizationAction.USE_TOOL

    def test_tool_fuera_de_allowlist_bloquea(self) -> None:
        state = _state()
        state.tools.set_allowed(["echo"])
        state.tools.note_call("search_knowledge")
        decision = evaluate_finalization(state)
        assert decision.action is FinalizationAction.BLOCK
        assert decision.reason_code == "TOOL_OUTSIDE_ALLOWLIST"

    def test_observabilidad_completa(self) -> None:
        decision = evaluate_finalization(
            _state(evidence="complete"),
            jev_verdict="uncertain",
            draft_available=True,
        )
        payload = decision.to_public_dict()
        assert payload["action"] == "FINALIZE"
        assert payload["reason_code"] == "READY"
        assert payload["authority"] == "GENERATION"
        assert payload["signals"]["evidence"] == "complete"
        assert payload["signals"]["jev"] == "uncertain"
        assert payload["signals_ignored"] == ["jev_only_negative_signal"]

    def test_missing_requirements_se_reportan(self) -> None:
        decision = evaluate_finalization(
            _state(evidence="insufficient"), retrieval_possible=False
        )
        assert decision.missing_requirements == ("campo_x",)

    def test_decision_matches_terminal(self) -> None:
        finalize = evaluate_finalization(
            _state(evidence="complete"), draft_available=True
        )
        assert decision_matches_terminal(finalize, RunPhase.FINALIZED) is True
        assert decision_matches_terminal(finalize, RunPhase.ABSTAINED) is False
        undetermined = evaluate_finalization(
            _state(requires_deterministic=True)
        )
        assert (
            decision_matches_terminal(undetermined, RunPhase.UNDETERMINED) is True
        )
