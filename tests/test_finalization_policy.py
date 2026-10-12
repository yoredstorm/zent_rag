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


class TestShadowDivergence:
    def test_sin_divergencia_no_emite_metrica(self) -> None:
        from src.infrastructure.observability.metrics import (
            zent_finalization_shadow_divergence_total,
        )
        from src.runtime.finalization_policy import observe_shadow_divergence

        decision = evaluate_finalization(
            _state(evidence="complete"), draft_available=True
        )
        counter = zent_finalization_shadow_divergence_total.labels(
            stage="closure",
            action=str(decision.action),
            reason_code=decision.reason_code,
        )
        before = counter._value.get()
        assert observe_shadow_divergence(decision, RunPhase.FINALIZED) is False
        assert counter._value.get() == before

    def test_divergencia_emite_metrica_y_devuelve_true(self) -> None:
        from src.infrastructure.observability.metrics import (
            zent_finalization_shadow_divergence_total,
        )
        from src.runtime.finalization_policy import observe_shadow_divergence

        # La ruta cerró ABSTAINED pero la política resuelve FINALIZE (evidencia
        # completa + draft): divergencia real que el shadow debe registrar.
        decision = evaluate_finalization(
            _state(evidence="complete"), draft_available=True
        )
        counter = zent_finalization_shadow_divergence_total.labels(
            stage="closure",
            action=str(decision.action),
            reason_code=decision.reason_code,
        )
        before = counter._value.get()
        assert observe_shadow_divergence(decision, RunPhase.ABSTAINED) is True
        assert counter._value.get() == before + 1


class TestEnforcement:
    def test_stages_default_y_custom(self) -> None:
        from types import SimpleNamespace

        from src.runtime.finalization_policy import (
            ENFORCE_STAGES,
            enforced_stages,
        )

        # El default de producción vive en Settings; el helper sin atributo
        # (doble de test) no enforza nada.
        assert enforced_stages(SimpleNamespace()) == frozenset()
        assert enforced_stages(
            SimpleNamespace(RUNTIME_FINALIZATION_ENFORCE="off")
        ) == frozenset()
        assert enforced_stages(SimpleNamespace(RUNTIME_FINALIZATION_ENFORCE="")) == frozenset()
        assert enforced_stages(
            SimpleNamespace(
                RUNTIME_FINALIZATION_ENFORCE="termination_trigger,draft_gate"
            )
        ) == frozenset({"termination_trigger", "draft_gate"})
        assert "answer_gate" in ENFORCE_STAGES
        assert enforced_stages(
            SimpleNamespace(RUNTIME_FINALIZATION_ENFORCE="draft_gate,unknown")
        ) == frozenset({"draft_gate"})

    def test_should_hold_solo_retrieve_more_y_etapa_armada(self) -> None:
        from src.runtime.finalization_policy import should_hold_trigger

        retrieve = evaluate_finalization(
            _state(evidence="insufficient"), retrieval_possible=True
        )
        finalize = evaluate_finalization(
            _state(evidence="complete"), draft_available=True
        )
        enforced = frozenset({"termination_trigger"})
        assert should_hold_trigger(
            retrieve,
            stage="termination_trigger",
            enforced=enforced,
        ) is True
        assert should_hold_trigger(
            retrieve,
            stage="draft_gate",
            enforced=enforced,
        ) is False
        assert should_hold_trigger(
            finalize,
            stage="termination_trigger",
            enforced=enforced,
        ) is False
        assert should_hold_trigger(
            None,
            stage="termination_trigger",
            enforced=enforced,
        ) is False

    def test_should_hold_acotado_por_max_holds(self) -> None:
        from src.runtime.finalization_policy import should_hold_trigger

        retrieve = evaluate_finalization(
            _state(evidence="insufficient"), retrieval_possible=True
        )
        assert should_hold_trigger(
            retrieve,
            stage="termination_trigger",
            enforced=frozenset({"termination_trigger"}),
            holds_used=1,
        ) is False


class TestTriggerShadow:
    def test_termination_acompanado_por_la_politica(self) -> None:
        from src.infrastructure.observability.metrics import (
            zent_finalization_shadow_divergence_total,
        )
        from src.runtime.finalization_policy import observe_trigger_shadow

        state = _state(evidence="complete")
        counter = zent_finalization_shadow_divergence_total.labels(
            stage="termination_trigger",
            action="FINALIZE",
            reason_code="TERMINATION_SATISFIED",
        )
        before = counter._value.get()
        decision = observe_trigger_shadow(
            state,
            stage="termination_trigger",
            intended="FINALIZE",
            retrieval_possible=True,
            draft_available=True,
            termination_requested=True,
        )
        assert decision.action is FinalizationAction.FINALIZE
        assert counter._value.get() == before

    def test_termination_prematuro_con_retrieval_posible_diverge(self) -> None:
        from src.infrastructure.observability.metrics import (
            zent_finalization_shadow_divergence_total,
        )
        from src.runtime.finalization_policy import observe_trigger_shadow

        state = _state(evidence="insufficient")
        decision = observe_trigger_shadow(
            state,
            stage="termination_trigger",
            intended="FINALIZE",
            retrieval_possible=True,
            draft_available=True,
            termination_requested=True,
        )
        assert decision.action is FinalizationAction.RETRIEVE_MORE
        counter = zent_finalization_shadow_divergence_total.labels(
            stage="termination_trigger",
            action=str(decision.action),
            reason_code=decision.reason_code,
        )
        assert counter._value.get() >= 1

    def test_draft_gate_abstiene_y_la_politica_pediria_retrieval(self) -> None:
        from src.infrastructure.observability.metrics import (
            zent_finalization_shadow_divergence_total,
        )
        from src.runtime.finalization_policy import observe_trigger_shadow

        state = _state(evidence="insufficient")
        decision = observe_trigger_shadow(
            state,
            stage="draft_gate",
            intended="ABSTAIN",
            retrieval_possible=True,
            draft_available=True,
        )
        assert decision.action is FinalizationAction.RETRIEVE_MORE
        counter = zent_finalization_shadow_divergence_total.labels(
            stage="draft_gate",
            action=str(decision.action),
            reason_code=decision.reason_code,
        )
        assert counter._value.get() >= 1

    def test_draft_gate_con_fallo_operativo_no_diverge(self) -> None:
        from src.runtime.finalization_policy import observe_trigger_shadow

        state = _state(evidence="failed")
        decision = observe_trigger_shadow(
            state,
            stage="draft_gate",
            intended="BLOCK",
            retrieval_possible=False,
            draft_available=True,
        )
        assert decision.action is FinalizationAction.BLOCK
        assert decision.reason_code == "RETRIEVAL_UNAVAILABLE"
