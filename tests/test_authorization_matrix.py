# =============================================================================
# Matriz de autorización (P1-C): JEV juzga, nunca autoriza por sí solo.
# =============================================================================
# Contrato:
#   UNTRUSTED/PROBABILISTIC (JEV) PRODUCE SIGNALS.
#   POLICY (la matriz determinista × JEV, compuesta en código) PRODUCE
#   AUTHORIZATION.
#   Determinista DENY siempre gana; determinista ALLOW no se invierte por un
#   juicio; una señal JEV sola no produce BLOCK ni autorización.
#
# Estos tests son el contrato behavioral de la matriz; `resolve_authorization`
# es la única función que decide el ruling.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.domain.decision import DecisionContext, RoutingDecision
from src.decision.composite import CompositeDecisionProvider
from src.decision.confidence import JudgmentConfidencePolicy
from src.decision.judgment import PHASE_PRE_GENERATION
from src.decision.policy import authorize_decision
from src.decision.preflight import (
    ACTION_ABSTAIN,
    ACTION_ASK_USER,
    ACTION_DETERMINISTIC,
    ACTION_GENERATE,
    ACTION_RETRIEVE,
    AUTHORIZATION_ALLOW,
    AUTHORIZATION_DENY,
    AUTHORIZATION_UNKNOWN,
    JEV_SIGNAL_NEGATIVE,
    JEV_SIGNAL_POSITIVE,
    RULING_ADVISORY,
    RULING_ALLOW,
    RULING_BLOCK,
    RULING_REQUIRES_CORROBORATION,
    RULING_RETRIEVE_MORE,
    DeterministicSignals,
    LLMEscalationPolicy,
    build_pack,
    resolve_authorization,
)
from src.decision.settings import DecisionEngineSettings

#: Acciones que un juicio probabilístico NUNCA puede producir por sí solo.
_DEFINITIVE_ACTIONS = frozenset({ACTION_ABSTAIN, ACTION_ASK_USER, ACTION_DETERMINISTIC})


# -----------------------------------------------------------------------------
# La matriz como tabla (unidad pura).
# -----------------------------------------------------------------------------
class TestMatrizUnitaria:
    def test_determinista_deny_gana_con_cualquier_juicio(self) -> None:
        for jev in (JEV_SIGNAL_NEGATIVE, JEV_SIGNAL_POSITIVE):
            for corroborated in (False, True):
                for budget in (0, 3):
                    assert (
                        resolve_authorization(
                            deterministic=AUTHORIZATION_DENY,
                            jev=jev,
                            corroborated=corroborated,
                            retrieval_budget_left=budget,
                        )
                        == RULING_BLOCK
                    ), (jev, corroborated, budget)

    def test_determinista_allow_no_se_invierte_por_jev(self) -> None:
        assert (
            resolve_authorization(
                deterministic=AUTHORIZATION_ALLOW, jev=JEV_SIGNAL_NEGATIVE
            )
            == RULING_ADVISORY
        )
        assert (
            resolve_authorization(
                deterministic=AUTHORIZATION_ALLOW, jev=JEV_SIGNAL_POSITIVE
            )
            == RULING_ALLOW
        )

    def test_jev_solo_no_produce_block_nunca(self) -> None:
        for corroborated in (False, True):
            for budget in (0, 1, 5):
                ruling = resolve_authorization(
                    deterministic=AUTHORIZATION_UNKNOWN,
                    jev=JEV_SIGNAL_NEGATIVE,
                    corroborated=corroborated,
                    retrieval_budget_left=budget,
                )
                assert ruling in {
                    RULING_ADVISORY,
                    RULING_RETRIEVE_MORE,
                    RULING_REQUIRES_CORROBORATION,
                }, (corroborated, budget)

    def test_jev_solo_corroborado_pide_evidencia_no_bloquea(self) -> None:
        assert (
            resolve_authorization(
                deterministic=AUTHORIZATION_UNKNOWN,
                jev=JEV_SIGNAL_NEGATIVE,
                corroborated=True,
                retrieval_budget_left=2,
            )
            == RULING_RETRIEVE_MORE
        )
        assert (
            resolve_authorization(
                deterministic=AUTHORIZATION_UNKNOWN,
                jev=JEV_SIGNAL_NEGATIVE,
                corroborated=True,
                retrieval_budget_left=0,
            )
            == RULING_REQUIRES_CORROBORATION
        )

    def test_jev_solo_incierto_es_advisory(self) -> None:
        assert (
            resolve_authorization(
                deterministic=AUTHORIZATION_UNKNOWN,
                jev=JEV_SIGNAL_NEGATIVE,
                corroborated=False,
                retrieval_budget_left=9,
            )
            == RULING_ADVISORY
        )

    def test_jev_positivo_no_eleva_nada(self) -> None:
        # UNKNOWN + positivo: no bloquea, pero tampoco autoriza nada por sí:
        # el ruling sigue siendo la ruta vigente (allow del pipeline).
        assert (
            resolve_authorization(
                deterministic=AUTHORIZATION_UNKNOWN, jev=JEV_SIGNAL_POSITIVE
            )
            == RULING_ALLOW
        )


# -----------------------------------------------------------------------------
# Comportamiento del preflight (la matriz aplicada a la decisión real).
# -----------------------------------------------------------------------------
def _policy() -> JudgmentConfidencePolicy:
    return JudgmentConfidencePolicy.default_policy()


def _pre_generation_pack(**answers):
    return build_pack(
        phase=PHASE_PRE_GENERATION,
        payload={"answers": answers},
        mode="on",
        policy=_policy(),
    )


def _ready_answers(**overrides):
    answers = {
        "analysis_complete": {"type": "noul", "noul": 0.97},
        "answerable_from_current_evidence": {"type": "noul", "noul": 0.94},
        "critical_fact_missing": {"type": "noul", "noul": 0.04},
        "critical_conflict_unresolved": {"type": "noul", "noul": 0.03},
        "inference_supported": {"type": "noul", "noul": 0.93},
        "next_action": {
            "type": "choice",
            "choice": "generate_answer",
            "confidence": 0.95,
            "probabilities": {"generate_answer": 0.95},
        },
    }
    answers.update(overrides)
    return answers


def _signals(**overrides) -> DeterministicSignals:
    base = dict(
        answerable=None,
        evidence_sufficient=None,
        analysis_complete=None,
        retrieval_rounds=1,
        retrieval_budget_left=2,
        legacy_tier="standard",
    )
    base.update(overrides)
    return DeterministicSignals(**base)


def _deny_signals(**overrides) -> DeterministicSignals:
    base = dict(
        answerable=False,
        evidence_sufficient=False,
        analysis_complete=False,
        retrieval_budget_left=0,
        legacy_tier="standard",
    )
    base.update(overrides)
    return DeterministicSignals(**base)


class TestPreflightMatriz:
    def test_juicio_solo_negativo_no_bloquea_la_generacion(self) -> None:
        pack = _pre_generation_pack(
            **_ready_answers(analysis_complete={"type": "noul", "noul": 0.10})
        )
        decision = LLMEscalationPolicy(policy=_policy()).evaluate(
            pack=pack, signals=_signals(), mode="on"
        )
        assert decision.allow_generation is True
        assert "jev_only_signal" in decision.conflicts
        assert decision.action == ACTION_GENERATE

    def test_juicio_corroborado_sin_segunda_senal_pide_corroboracion(self) -> None:
        """≥2 insatisfechas, alta confianza, sin señal determinista: NO bloquea."""
        pack = _pre_generation_pack(
            **_ready_answers(
                answerable_from_current_evidence={"type": "noul", "noul": 0.05},
                inference_supported={"type": "noul", "noul": 0.05},
            )
        )
        decision = LLMEscalationPolicy(policy=_policy()).evaluate(
            pack=pack, signals=_signals(retrieval_budget_left=2), mode="on"
        )
        assert decision.action == ACTION_RETRIEVE
        assert "corroboration_required" in decision.reasons
        assert "judgment_only_signal_multiple" in decision.reasons
        assert decision.action not in _DEFINITIVE_ACTIONS

    def test_juicio_corroborado_sin_presupuesto_no_abstiene_por_jev(self) -> None:
        pack = _pre_generation_pack(
            **_ready_answers(
                answerable_from_current_evidence={"type": "noul", "noul": 0.05},
                inference_supported={"type": "noul", "noul": 0.05},
            )
        )
        decision = LLMEscalationPolicy(policy=_policy()).evaluate(
            pack=pack, signals=_signals(retrieval_budget_left=0), mode="on"
        )
        assert decision.allow_generation is True
        assert "corroboration_required" in decision.reasons
        assert decision.action not in _DEFINITIVE_ACTIONS

    def test_barrido_ninguna_senal_jev_sola_es_definitiva(self) -> None:
        """Barrido de confianza/insatisfechas: JEV solo nunca da acción definitiva."""
        cases = (
            {"analysis_complete": {"type": "noul", "noul": 0.02}},
            {
                "analysis_complete": {"type": "noul", "noul": 0.02},
                "inference_supported": {"type": "noul", "noul": 0.02},
            },
            {
                "analysis_complete": {"type": "noul", "noul": 0.02},
                "inference_supported": {"type": "noul", "noul": 0.02},
                "critical_conflict_unresolved": {"type": "noul", "noul": 0.95},
            },
            {
                "answerable_from_current_evidence": {"type": "noul", "noul": 0.02},
                "analysis_complete": {"type": "noul", "noul": 0.02},
                "inference_supported": {"type": "noul", "noul": 0.02},
                "critical_conflict_unresolved": {"type": "noul", "noul": 0.95},
            },
        )
        checked = 0
        for answers in cases:
            for budget in (0, 1, 4):
                pack = _pre_generation_pack(**_ready_answers(**answers))
                decision = LLMEscalationPolicy(policy=_policy()).evaluate(
                    pack=pack,
                    signals=_signals(retrieval_budget_left=budget),
                    mode="on",
                )
                checked += 1
                assert decision.action not in _DEFINITIVE_ACTIONS, (
                    answers,
                    budget,
                    decision.to_public_dict(),
                )
                assert (
                    decision.action != ACTION_GENERATE
                    or decision.allow_generation is True
                )
        assert checked >= 12

    def test_deny_determinista_gana_con_juicio_positivo(self) -> None:
        """El código duda (deny) aunque JEV apruebe: manda el determinista."""
        pack = _pre_generation_pack(**_ready_answers())
        decision = LLMEscalationPolicy(policy=_policy()).evaluate(
            pack=pack, signals=_deny_signals(), mode="on"
        )
        assert decision.allow_generation is False
        assert decision.action in (ACTION_RETRIEVE, ACTION_ABSTAIN)

    def test_allow_determinista_no_se_invierte_por_juicio_negativo(self) -> None:
        pack = _pre_generation_pack(
            **_ready_answers(analysis_complete={"type": "noul", "noul": 0.10})
        )
        signals = _signals(answerable=True, evidence_sufficient=True, analysis_complete=True)
        decision = LLMEscalationPolicy(policy=_policy()).evaluate(
            pack=pack, signals=signals, mode="on"
        )
        assert decision.allow_generation is True
        assert decision.action == ACTION_GENERATE
        assert "deterministic_signals_ok" in decision.reasons

    def test_jev_ausente_degrada_de_forma_explicita(self) -> None:
        decision = LLMEscalationPolicy(policy=_policy()).evaluate(
            pack=None, signals=_signals(), mode="on"
        )
        assert decision.reasons == ["jev_unavailable"]
        assert decision.decided_by == "deterministic"
        assert decision.allow_generation is True
        assert decision.action == ACTION_GENERATE


# -----------------------------------------------------------------------------
# Shadow de verdad: el juicio puede observarse, la autoridad no cambia.
# -----------------------------------------------------------------------------
class TestShadowNoActua:
    def test_shadow_mode_impide_actuar_en_modo_jev(self) -> None:
        shadowed = DecisionEngineSettings(routing_mode="jev", shadow_mode=True)
        assert shadowed.acts(None) is False
        assert shadowed.observes(None) is True
        acting = DecisionEngineSettings(routing_mode="jev", shadow_mode=False)
        assert acting.acts(None) is True

    @pytest.mark.asyncio
    async def test_jev_shadow_no_cambia_la_ejecucion(self) -> None:
        class FakeRules:
            name = "rules"

            async def decide(self, context):
                return RoutingDecision(
                    provider="rules",
                    resolved=False,
                    capability="knowledge.answer",
                    confidence=0.0,
                )

        class FakeJev:
            name = "jev"

            async def decide(self, context):
                return RoutingDecision(
                    provider="jev",
                    resolved=True,
                    capability="database.query",
                    confidence=0.99,
                )

        provider = CompositeDecisionProvider(
            settings=DecisionEngineSettings(routing_mode="jev", shadow_mode=True),
            rules=FakeRules(),
            jev=FakeJev(),
        )
        context = DecisionContext(
            user_request="¿cuánto vendimos?",
            organization_id=uuid4(),
            request_id=uuid4(),
            available_capabilities=("knowledge.answer", "database.query"),
            permissions=frozenset({"*"}),
        )
        decision = await provider.decide(context)
        # El juicio se observó, pero la ruta vigente siguió en charge.
        assert decision.metadata.get("acting") is False
        assert decision.provider == "legacy"
        assert decision.metadata.get("shadow_candidate") is not None
        assert decision.capability == "knowledge.answer"


# -----------------------------------------------------------------------------
# JEV no autoriza: la policy recorta capacidades sin importar la confianza.
# -----------------------------------------------------------------------------
class TestJevNoAutoriza:
    def test_juicio_positivo_con_alta_confianza_no_otorga_capacidad(self) -> None:
        decision = RoutingDecision(
            provider="jev",
            resolved=True,
            capability="database.query",
            confidence=0.99,
        )
        context = DecisionContext(
            user_request="q",
            organization_id=uuid4(),
            request_id=uuid4(),
            available_capabilities=("knowledge.answer", "database.query"),
            permissions=frozenset(),  # sin permiso de SQL
        )
        gated = authorize_decision(decision, context)
        assert gated.capability != "database.query"
        assert gated.metadata.get("authorization_denied") is True

    def test_juicio_positivo_no_otorga_tool(self) -> None:
        decision = RoutingDecision(
            provider="jev",
            resolved=True,
            capability="tool.call_api",
            confidence=0.99,
        )
        context = DecisionContext(
            user_request="q",
            organization_id=uuid4(),
            request_id=uuid4(),
            available_capabilities=("knowledge.answer", "tool.call_api"),
            permissions=frozenset(),
        )
        gated = authorize_decision(decision, context)
        assert gated.capability != "tool.call_api"
        assert gated.metadata.get("authorization_denied") is True
