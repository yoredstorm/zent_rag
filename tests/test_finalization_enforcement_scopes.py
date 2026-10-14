# =============================================================================
# Enforcement de la FinalizationPolicy — scopes y holds (F2).
# =============================================================================
# Prioridad: SAFETY FLOOR monotónico (P1-D): effective = global ∪ environment ∪
# organización ∪ agente. Cada scope SUMA etapas; ninguno puede desarmar una
# etapa que otro armó. Un scope nunca arma una etapa desconocida (fail-closed
# del lado seguro).
from __future__ import annotations

from types import SimpleNamespace

from src.runtime.enforcement import (
    ENFORCE_STAGES,
    enforcement_stages,
    parse_stages,
    should_hold_trigger,
)
from src.runtime.finalization_policy import (
    FinalizationAction,
    enforced_stages,
    evaluate_finalization,
)
from src.runtime.run_state import AgentRunState, RunIdentity, RunPhase


def _state(*, evidence: str = "complete", requires: bool = False) -> AgentRunState:
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
                missing_entities=(),
                missing_anchors=(),
            )
        )
    state.decisions.requires_deterministic = requires
    return state


class TestParseStages:
    def test_bool_arma_todas_las_etapas(self) -> None:
        assert parse_stages(True) == ENFORCE_STAGES
        assert parse_stages(False) == frozenset()

    def test_off_y_vacio_no_arman_nada(self) -> None:
        for raw in ("", "off", "OFF", "0", "false", "no", None):
            assert parse_stages(raw) == frozenset()

    def test_etapa_desconocida_se_ignora(self) -> None:
        assert parse_stages("answer_gate,nope") == frozenset({"answer_gate"})


class TestPisoMonotonico:
    """SAFETY FLOOR: cada scope SUMA etapas; ninguno resta (P1-D)."""

    def test_sin_configuracion_no_arma_nada(self) -> None:
        assert enforcement_stages(SimpleNamespace()) == frozenset()

    def test_global_solo(self) -> None:
        settings = SimpleNamespace(RUNTIME_FINALIZATION_ENFORCE="answer_gate")
        assert enforcement_stages(settings) == frozenset({"answer_gate"})

    def test_environment_suma_al_global(self) -> None:
        settings = SimpleNamespace(
            RUNTIME_FINALIZATION_ENFORCE="draft_gate",
            RUNTIME_FINALIZATION_ENFORCE_BY_ENV="production=termination_trigger",
            ENVIRONMENT="production",
        )
        assert enforcement_stages(settings) == frozenset(
            {"draft_gate", "termination_trigger"}
        )

    def test_environment_no_coincidente_usa_global(self) -> None:
        settings = SimpleNamespace(
            RUNTIME_FINALIZATION_ENFORCE="draft_gate",
            RUNTIME_FINALIZATION_ENFORCE_BY_ENV="production=termination_trigger",
            ENVIRONMENT="development",
        )
        assert enforcement_stages(settings) == frozenset({"draft_gate"})

    def test_organizacion_suma_al_environment(self) -> None:
        settings = SimpleNamespace(
            RUNTIME_FINALIZATION_ENFORCE="draft_gate",
            RUNTIME_FINALIZATION_ENFORCE_BY_ENV="production=termination_trigger",
            RUNTIME_FINALIZATION_ENFORCE_ORGS="org-1=answer_gate",
            ENVIRONMENT="production",
        )
        assert enforcement_stages(settings, organization_id="org-1") == frozenset(
            {"draft_gate", "termination_trigger", "answer_gate"}
        )

    def test_organizacion_sin_valor_hereda_las_globales(self) -> None:
        settings = SimpleNamespace(
            RUNTIME_FINALIZATION_ENFORCE="draft_gate",
            RUNTIME_FINALIZATION_ENFORCE_ORGS="org-1;org-2=answer_gate",
        )
        assert enforcement_stages(settings, organization_id="org-1") == frozenset(
            {"draft_gate"}
        )
        assert enforcement_stages(settings, organization_id="org-2") == frozenset(
            {"draft_gate", "answer_gate"}
        )
        assert enforcement_stages(settings, organization_id="org-3") == frozenset(
            {"draft_gate"}
        )

    def test_config_del_agente_suma_y_nunca_resta(self) -> None:
        settings = SimpleNamespace(
            RUNTIME_FINALIZATION_ENFORCE="draft_gate",
            RUNTIME_FINALIZATION_ENFORCE_ORGS="org-1=answer_gate",
        )
        config = {"runtime": {"finalization_enforce": "termination_trigger"}}
        assert enforcement_stages(
            settings, config_json=config, organization_id="org-1"
        ) == frozenset({"draft_gate", "answer_gate", "termination_trigger"})
        # `false` del agente NO desarma el piso global (antes sí).
        assert enforcement_stages(
            settings, config_json={"runtime": {"finalization_enforce": False}}
        ) == frozenset({"draft_gate"})

    def test_config_del_agente_booleano(self) -> None:
        settings = SimpleNamespace(RUNTIME_FINALIZATION_ENFORCE="")
        assert enforcement_stages(
            settings, config_json={"runtime": {"finalization_enforce": True}}
        ) == ENFORCE_STAGES
        assert enforcement_stages(
            settings, config_json={"runtime": {"finalization_enforce": False}}
        ) == frozenset()

    def test_reexport_global_de_la_politica(self) -> None:
        # Compat: el helper de la política resuelve solo el scope global.
        assert enforced_stages(
            SimpleNamespace(RUNTIME_FINALIZATION_ENFORCE="termination_trigger")
        ) == frozenset({"termination_trigger"})
        assert enforced_stages(SimpleNamespace()) == frozenset()


class TestHoldDeLaEtapaAnswerGate:
    def test_hold_solo_con_retrieve_more(self) -> None:
        retrieve = evaluate_finalization(
            _state(evidence="insufficient"), retrieval_possible=True
        )
        assert retrieve.action is FinalizationAction.RETRIEVE_MORE
        assert should_hold_trigger(
            retrieve,
            stage="answer_gate",
            enforced=frozenset({"answer_gate"}),
        ) is True
        assert should_hold_trigger(
            retrieve,
            stage="answer_gate",
            enforced=frozenset({"draft_gate"}),
        ) is False

    def test_hold_acotado_y_con_evidencia_completa_no_aplica(self) -> None:
        finalize = evaluate_finalization(
            _state(evidence="complete"), draft_available=True
        )
        assert should_hold_trigger(
            finalize,
            stage="answer_gate",
            enforced=frozenset({"answer_gate"}),
        ) is False

        retrieve = evaluate_finalization(
            _state(evidence="insufficient"), retrieval_possible=True
        )
        assert should_hold_trigger(
            retrieve,
            stage="answer_gate",
            enforced=frozenset({"answer_gate"}),
            holds_used=1,
        ) is False

    def test_terminal_no_transiciona(self) -> None:
        state = _state()
        state.phase = RunPhase.FINALIZED
        from src.runtime.run_guards import RunEvent, evaluate_transition

        verdict = evaluate_transition(
            state.phase, RunEvent.REQUEST_RETRIEVAL
        )
        assert verdict.allowed is False
        assert verdict.reason_code == "TERMINAL_NO_TRANSITIONS"
