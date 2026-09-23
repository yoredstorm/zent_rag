# =============================================================================
# JEV Preflight — juicio previo a la generación cara.
# =============================================================================
# Golden scenarios (§57-§63) y reglas no negociables: Noul 0.0 no es default,
# 0.51 no es YES, un Choice ambiguo no se trata como claro, un Score conserva su
# vecindad, el código compone la decisión y sin dos señales no se bloquea nada.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.decision.batch import (
    build_phase_questions,
    build_post_generation_questions,
    build_pre_reasoning_questions,
    validate_question_ids,
)
from src.decision.confidence import (
    VERDICT_NO,
    VERDICT_UNCERTAIN,
    VERDICT_YES,
    JudgmentConfidencePolicy,
    JudgmentThresholds,
)
from src.decision.distributions import (
    DIRECTION_NO,
    DIRECTION_UNCERTAIN,
    noul_reading,
    read_choice,
    read_noul,
    read_score,
)
from src.decision.engine import DecisionEngine
from src.decision.judgment import (
    PHASE_POST_GENERATION,
    PHASE_POST_RECONSTRUCTION,
    PHASE_PRE_GENERATION,
    PHASE_PRE_REASONING,
)
from src.decision.preflight import (
    ACTION_ABSTAIN,
    ACTION_DETERMINISTIC,
    ACTION_GENERATE,
    DECIDED_BY_JEV,
    MODE_ON,
    MODE_SHADOW,
    DeterministicSignals,
    JudgmentPack,
    LLMEscalationPolicy,
    build_pack,
    build_readiness,
    compose_final_action,
    compose_post_reconstruction,
    compose_pre_reasoning,
    normalize_preflight_mode,
    run_pack,
    tier_index,
)
from src.decision.providers.jev import JevDecisionProvider
from src.decision.registry import get_definition, public_registry, question_version
from src.decision.settings import DecisionEngineSettings
from src.rag.flow_story import with_story
from src.rag.preflight_hook import OrchestratorPreflightHook, PreflightSettings


def _policy() -> JudgmentConfidencePolicy:
    return JudgmentConfidencePolicy.default_policy()


def _pre_generation_pack(**answers) -> JudgmentPack:
    """Pack PRE_GENERATION a partir de respuestas crudas (sin llamar a JEV)."""
    return build_pack(
        phase=PHASE_PRE_GENERATION,
        payload={"answers": answers},
        mode=MODE_ON,
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
        answerable=True,
        evidence_sufficient=True,
        evidence_score=0.8,
        analysis_complete=True,
        retrieval_rounds=1,
        retrieval_budget_left=2,
        legacy_tier="standard",
    )
    base.update(overrides)
    return DeterministicSignals(**base)


class FakeJudge:
    """Judge simple: responde lo que se le diga, nunca toca la API."""

    def __init__(self, answers: dict | None = None) -> None:
        self.calls = 0
        self.phases: list[str] = []
        self.questions: list[list[str]] = []
        self.states: list[dict] = []
        self._answers = answers or {}

    async def judge(self, *, state, questions, context=None):
        self.calls += 1
        self.phases.append(str(getattr(context, "phase", "")))
        self.questions.append(sorted(questions))
        self.states.append(dict(state))
        answers = {}
        for question_id, spec in questions.items():
            if question_id in self._answers:
                answers[question_id] = self._answers[question_id]
                continue
            qtype = str((spec or {}).get("type") or "noul")
            if qtype == "choice":
                criteria = (spec or {}).get("criteria") or {}
                choice = next(iter(criteria), "generate_answer")
                answers[question_id] = {
                    "type": "choice",
                    "choice": choice,
                    "confidence": 0.9,
                    "probabilities": {choice: 0.9},
                }
            elif qtype == "score":
                answers[question_id] = {"type": "score", "score": 2.0, "confidence": 0.8}
            else:
                answers[question_id] = {"type": "noul", "noul": 0.9}
        return {"model": "jev-test", "answers": answers, "usage": {"input_tokens": 10, "output_tokens": 4}}


# ---------------------------------------------------------------------------
# §61 — Noul 0.0 es un NO fuerte, nunca un default
# ---------------------------------------------------------------------------


def test_noul_cero_es_no_fuerte_y_nunca_default() -> None:
    reading = read_noul({"type": "noul", "noul": 0.0})
    assert reading is not None
    assert reading.value == 0.0
    assert reading.direction == DIRECTION_NO
    assert reading.certainty == 1.0
    thresholds = JudgmentThresholds()
    assert thresholds.is_no(reading) is True
    assert thresholds.is_yes(reading) is False
    assert read_noul({"type": "noul", "noul": False}) is not None
    assert read_noul({"type": "noul", "noul": False}).value == 0.0  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# §26 — la incertidumbre es información
# ---------------------------------------------------------------------------


def test_noul_medio_es_incierto_no_yes_debil() -> None:
    reading = noul_reading(0.51)
    assert reading.direction == DIRECTION_UNCERTAIN
    assert reading.certainty < 0.05
    assert JudgmentThresholds().is_uncertain(reading) is True
    assert JudgmentThresholds().is_yes(reading) is False
    decision = LLMEscalationPolicy(policy=_policy()).evaluate(
        pack=_pre_generation_pack(**_ready_answers(analysis_complete={"type": "noul", "noul": 0.51})),
        signals=_signals(),
        mode=MODE_ON,
    )
    assert "analysis_complete" in decision.uncertain_critical
    assert "analysis_complete" in decision.unsatisfied


def test_veredicto_tres_vias_desde_umbrales() -> None:
    thresholds = JudgmentThresholds(noul_yes=0.75, noul_no=0.25)
    assert thresholds.verdict(noul_reading(0.96)) == VERDICT_YES
    assert thresholds.verdict(noul_reading(0.04)) == VERDICT_NO
    assert thresholds.verdict(noul_reading(0.60)) == VERDICT_UNCERTAIN
    assert thresholds.verdict(none_reading()) == VERDICT_UNCERTAIN


def none_reading():
    return read_noul({"type": "noul"}, default=None)


# ---------------------------------------------------------------------------
# §9, §11 — distribuciones
# ---------------------------------------------------------------------------


def test_choice_conserva_runner_up_margen_y_entropia() -> None:
    reading = read_choice(
        {
            "type": "choice",
            "choice": "state_transition",
            "confidence": 0.58,
            "probabilities": {
                "state_transition": 0.58,
                "temporal_sequence": 0.34,
                "multi_evidence": 0.08,
            },
        }
    )
    assert reading is not None
    assert reading.runner_up == "temporal_sequence"
    assert reading.margin == pytest.approx(0.24)
    assert reading.entropy > 0
    assert [option for option, _ in reading.alternatives][:2] == [
        "temporal_sequence",
        "multi_evidence",
    ]
    payload = reading.to_public_dict()
    assert payload["probabilities"]["temporal_sequence"] == 0.34


def test_score_conserva_vecindad_de_niveles() -> None:
    reading = read_score(
        {
            "type": "score",
            "score": 2.06,
            "confidence": 0.88,
            "probabilities": {"weak": 0.04, "partial": 0.16, "good": 0.50, "excellent": 0.30},
        }
    )
    assert reading is not None
    assert reading.level == "good"
    assert reading.neighbourhood_mass == pytest.approx(0.46)
    assert reading.to_public_dict()["neighbourhood"][0]["level"] == "good"


# ---------------------------------------------------------------------------
# §5, §7, §46, §47 — un pack, una llamada, preguntas acotadas
# ---------------------------------------------------------------------------


def test_pack_pre_generation_mezcla_primitivas_en_una_llamada() -> None:
    phase = build_phase_questions("pre_generation")
    ids = validate_question_ids(phase.to_jevy())
    assert phase.phase == "pre_generation"
    types = {spec.type for spec in phase.questions.values()}
    assert {"choice", "score", "noul"} <= types
    assert "next_action" in ids and "generation_tier" in ids
    assert len(ids) <= 16


def test_preguntas_condicionales_dependen_del_estado_disponible() -> None:
    with_sql = build_pre_reasoning_questions(available={"sql_enabled"})
    without_sql = build_pre_reasoning_questions(available=set())
    assert "needs_structured_data" in with_sql.ids()
    assert "needs_structured_data" not in without_sql.ids()


def test_preguntas_por_hipotesis_se_expanden_por_candidato() -> None:
    phase = build_phase_questions("post_reconstruction", hypotheses=["a", "b"])
    ids = phase.ids()
    assert "hypothesis_0_supported" in ids and "hypothesis_1_contradicted" in ids
    assert "hypothesis_2_supported" not in ids


def test_verificacion_de_respuesta_viaja_en_el_pack_post_generation() -> None:
    phase = build_post_generation_questions(claims=["una afirmación"])
    ids = phase.ids()
    assert "answer_grounded" in ids
    assert "final_action" in ids
    assert "claim_0_supported" in ids
    assert ids.count("answer_grounded") == 1


# ---------------------------------------------------------------------------
# §57 — golden simple: sin packs complejos
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consulta_simple_no_paga_pack_de_pre_reasoning() -> None:
    judge = FakeJudge()
    hook = OrchestratorPreflightHook(
        PreflightSettings(mode=MODE_ON), judge=judge, policy=_policy()
    )
    decision = await hook.judge_pre_reasoning(
        trace=hook.new_trace(request_id=uuid4()),
        query="¿Qué es Carrier Code?",
        skip=True,
    )
    assert judge.calls == 0
    assert decision.needs == {}
    assert decision.decided_by != DECIDED_BY_JEV


# ---------------------------------------------------------------------------
# §8 — código compone, no otro LLM
# ---------------------------------------------------------------------------


def test_codigo_compone_state_transition_con_timeline() -> None:
    pack = build_pack(
        phase=PHASE_PRE_REASONING,
        payload={
            "answers": {
                "reasoning_shape": {
                    "type": "choice",
                    "choice": "state_transition",
                    "confidence": 0.92,
                    "probabilities": {"state_transition": 0.92, "temporal_sequence": 0.06},
                },
                "needs_timeline": {"type": "noul", "noul": 0.96},
                "needs_state_reconstruction": {"type": "noul", "noul": 0.98},
                "simple_lookup_sufficient": {"type": "noul", "noul": 0.04},
                "analysis_complexity": {"type": "score", "score": 3.0, "confidence": 0.9},
            }
        },
        mode=MODE_ON,
        policy=_policy(),
    )
    decision = compose_pre_reasoning(pack, policy=_policy())
    assert decision.shape == "state_transition"
    assert decision.requires("timeline") is True
    assert decision.requires("state_reconstruction") is True
    assert decision.simple_fast_path is False
    assert decision.shape_ambiguous is False


# ---------------------------------------------------------------------------
# §10, §60 — choice ambiguo
# ---------------------------------------------------------------------------


def test_choice_ambiguo_no_se_trata_como_claro() -> None:
    pack = build_pack(
        phase=PHASE_PRE_REASONING,
        payload={
            "answers": {
                "reasoning_shape": {
                    "type": "choice",
                    "choice": "state_transition",
                    "confidence": 0.47,
                    "probabilities": {"state_transition": 0.47, "temporal_sequence": 0.45},
                },
                "needs_timeline": {"type": "noul", "noul": 0.55},
            }
        },
        mode=MODE_ON,
        policy=_policy(),
    )
    judgment = pack.get("reasoning_shape")
    assert judgment is not None
    assert judgment.ambiguous is True
    decision = compose_pre_reasoning(pack, policy=_policy())
    assert decision.shape_ambiguous is True
    assert decision.shape_runner_up == "temporal_sequence"
    assert "reasoning_shape" in decision.uncertain
    # Ambigüedad material entre estado y secuencia ⇒ también hace falta timeline.
    assert decision.requires("timeline") is True
    # Y la timeline dudosa queda registrada como incertidumbre, no como YES.
    assert "needs_timeline" in decision.uncertain


# ---------------------------------------------------------------------------
# §58 — golden state transition: el gate habilita generar
# ---------------------------------------------------------------------------


def test_golden_state_transition_habilita_generacion() -> None:
    pack = _pre_generation_pack(
        **_ready_answers(),
        answer_readiness={"type": "score", "score": 2.8, "confidence": 0.92},
        evidence_strength={"type": "score", "score": 2.6, "confidence": 0.9},
    )
    decision = LLMEscalationPolicy(policy=_policy()).evaluate(
        pack=pack, signals=_signals(), mode=MODE_ON
    )
    assert decision.allow_generation is True
    assert decision.action == ACTION_GENERATE
    assert decision.unsatisfied == []
    assert decision.confidence >= 0.75


# ---------------------------------------------------------------------------
# §62 — modelo caro evitado
# ---------------------------------------------------------------------------


def test_golden_modelo_caro_evitado_usa_tier_barato() -> None:
    pack = _pre_generation_pack(
        **_ready_answers(
            needs_complex_reasoning_model={"type": "noul", "noul": 0.05},
            expensive_llm_needed={"type": "noul", "noul": 0.08},
        ),
        generation_tier={
            "type": "choice",
            "choice": "small",
            "confidence": 0.9,
            "probabilities": {"small": 0.9},
        },
    )
    decision = LLMEscalationPolicy(policy=_policy()).evaluate(
        pack=pack, signals=_signals(), mode=MODE_ON
    )
    assert decision.tier == "small"
    assert decision.expensive_model_allowed is False
    assert "cheaper_tier_sufficient" in decision.reasons


# ---------------------------------------------------------------------------
# §63 — modelo caro requerido
# ---------------------------------------------------------------------------


def test_golden_modelo_de_razonamiento_aprobado() -> None:
    pack = _pre_generation_pack(
        **_ready_answers(needs_complex_reasoning_model={"type": "noul", "noul": 0.93})
    )
    decision = LLMEscalationPolicy(policy=_policy()).evaluate(
        pack=pack, signals=_signals(), mode=MODE_ON
    )
    assert decision.tier == "reasoning"
    assert decision.expensive_model_allowed is True
    assert tier_index(decision.tier) > tier_index("small")


# ---------------------------------------------------------------------------
# §59 — golden sin schema: no se invoca el LLM caro para adivinar
# ---------------------------------------------------------------------------


def test_golden_analisis_incompleto_no_invoca_modelo_caro() -> None:
    pack = _pre_generation_pack(
        **_ready_answers(
            analysis_complete={"type": "noul", "noul": 0.04},
            critical_fact_missing={"type": "noul", "noul": 0.95},
            next_action={
                "type": "choice",
                "choice": "abstain",
                "confidence": 0.88,
                "probabilities": {"abstain": 0.88},
            },
        )
    )
    signals = _signals(
        evidence_sufficient=False,
        analysis_complete=False,
        retrieval_budget_left=0,
    )
    decision = LLMEscalationPolicy(policy=_policy()).evaluate(
        pack=pack, signals=signals, mode=MODE_ON
    )
    assert decision.allow_generation is False
    assert decision.action == ACTION_ABSTAIN
    assert decision.expensive_model_allowed is False


def test_sin_evidencia_pero_con_presupuesto_se_pide_otra_ronda() -> None:
    pack = _pre_generation_pack(
        **_ready_answers(
            analysis_complete={"type": "noul", "noul": 0.10},
            critical_fact_missing={"type": "noul", "noul": 0.90},
        )
    )
    signals = _signals(evidence_sufficient=False, retrieval_budget_left=2)
    decision = LLMEscalationPolicy(policy=_policy()).evaluate(
        pack=pack, signals=signals, mode=MODE_ON
    )
    assert decision.allow_generation is False
    assert decision.action == "retrieve_more"


# ---------------------------------------------------------------------------
# §17 — una señal sola no bloquea (dos señales, nunca max())
# ---------------------------------------------------------------------------


def test_jev_solo_no_bloquea_sin_segunda_senal() -> None:
    pack = _pre_generation_pack(
        **_ready_answers(analysis_complete={"type": "noul", "noul": 0.10})
    )
    decision = LLMEscalationPolicy(policy=_policy()).evaluate(
        pack=pack, signals=_signals(), mode=MODE_ON
    )
    assert decision.allow_generation is True
    assert "jev_only_signal" in decision.conflicts


# ---------------------------------------------------------------------------
# §20 — el presupuesto no degrada seguridad
# ---------------------------------------------------------------------------


def test_presupuesto_no_baja_el_tier_si_el_juicio_pide_razonamiento() -> None:
    pack = _pre_generation_pack(
        **_ready_answers(needs_complex_reasoning_model={"type": "noul", "noul": 0.95})
    )
    decision = LLMEscalationPolicy(policy=_policy()).evaluate(
        pack=pack, signals=_signals(prefer_small_model=True), mode=MODE_ON
    )
    assert decision.tier == "reasoning"
    assert "budget_prefers_small" not in decision.reasons


# ---------------------------------------------------------------------------
# §18 — respuesta determinística
# ---------------------------------------------------------------------------


def test_respuesta_deterministica_solo_con_conclusion_establecida() -> None:
    pack = _pre_generation_pack(
        **_ready_answers(
            simple_deterministic_answer_possible={"type": "noul", "noul": 0.90},
            needs_complex_reasoning_model={"type": "noul", "noul": 0.05},
        )
    )
    policy = LLMEscalationPolicy(policy=_policy(), allow_deterministic=True)
    decision = policy.evaluate(pack=pack, signals=_signals(), mode=MODE_ON)
    assert decision.tier == "deterministic"
    assert decision.action == ACTION_DETERMINISTIC
    assert decision.allow_generation is False
    # Por defecto el tier determinístico NO se aplica: se genera.
    default = LLMEscalationPolicy(policy=_policy())
    assert default.evaluate(pack=pack, signals=_signals(), mode=MODE_ON).tier != "deterministic"


# ---------------------------------------------------------------------------
# §15 — hipótesis: support/contradiction y veredicto compuesto en código
# ---------------------------------------------------------------------------


def test_hipotesis_se_componen_con_soporte_y_contradiccion() -> None:
    pack = build_pack(
        phase=PHASE_POST_RECONSTRUCTION,
        payload={
            "answers": {
                "scenario_completeness": {"type": "score", "score": 2.4, "confidence": 0.9},
                "state_reconstruction_quality": {"type": "score", "score": 2.2, "confidence": 0.85},
                "timeline_coherent": {"type": "noul", "noul": 0.93},
                "critical_transition_missing": {"type": "noul", "noul": 0.05},
                "critical_unknown_remaining": {"type": "noul", "noul": 0.06},
                "inference_possible": {"type": "noul", "noul": 0.92},
                "hypothesis_user_supported": {"type": "noul", "noul": 0.08},
                "hypothesis_user_contradicted": {"type": "noul", "noul": 0.91},
                "hypothesis_0_supported": {"type": "noul", "noul": 0.90},
                "hypothesis_0_contradicted": {"type": "noul", "noul": 0.10},
                "hypothesis_1_supported": {"type": "noul", "noul": 0.80},
                "hypothesis_1_contradicted": {"type": "noul", "noul": 0.85},
                "hypothesis_2_supported": {"type": "noul", "noul": 0.05},
                "hypothesis_2_contradicted": {"type": "noul", "noul": 0.88},
            }
        },
        mode=MODE_ON,
        policy=_policy(),
    )
    judgment = compose_post_reconstruction(pack, hypothesis_count=3, policy=_policy())
    verdicts = [item["verdict"] for item in judgment.hypothesis_verdicts]
    assert verdicts == ["supported", "unresolved", "rejected"]
    assert judgment.user_hypothesis_contradicted == VERDICT_YES
    assert judgment.user_hypothesis_supported == VERDICT_NO
    assert judgment.analysis_complete is True


# ---------------------------------------------------------------------------
# §22, §23 — verificación de la respuesta y motivo de revisión
# ---------------------------------------------------------------------------


def test_final_action_compone_revision_y_motivo() -> None:
    pack = build_pack(
        phase=PHASE_POST_GENERATION,
        payload={
            "answers": {
                "answer_grounded": {"type": "noul", "noul": 0.93},
                "answer_complete": {"type": "noul", "noul": 0.40},
                "answer_contains_unsupported_conclusion": {"type": "noul", "noul": 0.88},
                "answer_overstates_uncertainty": {"type": "noul", "noul": 0.10},
                "answer_ignores_material_conflict": {"type": "noul", "noul": 0.05},
                "final_action": {
                    "type": "choice",
                    "choice": "approve",
                    "confidence": 0.60,
                    "probabilities": {"approve": 0.60, "revise": 0.35},
                },
            }
        },
        mode=MODE_ON,
        policy=_policy(),
    )
    composed = compose_final_action(pack, policy=_policy())
    assert composed["action"] == "revise"
    assert composed["revision_reason"] == "unsupported_claim"
    assert "incomplete_answer" in composed["reasons"]


def test_final_action_abstiene_si_no_esta_respaldada() -> None:
    pack = build_pack(
        phase=PHASE_POST_GENERATION,
        payload={
            "answers": {
                "answer_grounded": {"type": "noul", "noul": 0.05},
                "final_action": {
                    "type": "choice",
                    "choice": "approve",
                    "confidence": 0.90,
                    "probabilities": {"approve": 0.9},
                },
            }
        },
        mode=MODE_ON,
        policy=_policy(),
    )
    composed = compose_final_action(pack, policy=_policy())
    assert composed["action"] == "abstain"
    assert composed["revision_reason"] == "missing_evidence"


# ---------------------------------------------------------------------------
# §27 — matriz de preparación
# ---------------------------------------------------------------------------


def test_matriz_de_preparacion_se_calcula_en_codigo() -> None:
    pack = _pre_generation_pack(
        **_ready_answers(),
        evidence_strength={"type": "score", "score": 2.8, "confidence": 0.94},
    )
    decision = LLMEscalationPolicy(policy=_policy()).evaluate(
        pack=pack, signals=_signals(), mode=MODE_ON
    )
    readiness = build_readiness(pack=pack, signals=_signals(), decision=decision)
    rows = {row.key: row for row in readiness.rows}
    assert rows["evidence"].source == DECIDED_BY_JEV
    assert rows["evidence"].state == "ok"
    assert rows["answerability"].state == "ok"
    assert rows["llm"].state == "ok"
    payload = readiness.to_public_dict()["rows"]
    assert payload[0]["key"] == "evidence"
    assert all("source" in row for row in payload)


# ---------------------------------------------------------------------------
# §29, §30 — registro y versionado de preguntas
# ---------------------------------------------------------------------------


def test_registry_versiona_y_documenta_las_preguntas() -> None:
    definition = get_definition("reasoning_shape", phase=PHASE_PRE_REASONING)
    assert definition is not None
    assert definition.version >= 1
    assert definition.ui_label.startswith("¿")
    assert "state_transition" in definition.options
    assert question_version("analysis_complete", phase=PHASE_PRE_GENERATION) >= 1
    assert question_version("no_existe") == 0
    registry = {row["id"]: row for row in public_registry()}
    assert registry["analysis_complete"]["phase"] == PHASE_PRE_GENERATION
    assert registry["expensive_llm_needed"]["ui_label"]


def test_el_pack_registra_la_version_de_cada_pregunta() -> None:
    pack = _pre_generation_pack(**_ready_answers())
    judgment = pack.get("analysis_complete")
    assert judgment is not None
    assert judgment.version == question_version("analysis_complete", phase=PHASE_PRE_GENERATION)
    assert judgment.effect == "generation_allowed" or judgment.effect is None


# ---------------------------------------------------------------------------
# §44 — la incertidumbre explica el run largo
# ---------------------------------------------------------------------------


def test_incertidumbre_critica_se_registra_y_afecta_la_matriz() -> None:
    pack = _pre_generation_pack(
        **_ready_answers(answerable_from_current_evidence={"type": "noul", "noul": 0.54})
    )
    signals = _signals(answerable=None, evidence_sufficient=None, analysis_complete=None)
    decision = LLMEscalationPolicy(policy=_policy()).evaluate(
        pack=pack, signals=signals, mode=MODE_ON
    )
    assert "answerable_from_current_evidence" in decision.uncertain_critical
    # Sin segunda señal determinística no se bloquea, pero la duda se declara.
    assert decision.allow_generation is True
    assert "jev_only_signal" in decision.conflicts
    readiness = build_readiness(pack=pack, signals=signals, decision=decision)
    row = readiness.get("llm")
    assert row is not None and row.state == "warn"


# ---------------------------------------------------------------------------
# §5 — una llamada por fase, con el engine real (batching)
# ---------------------------------------------------------------------------


class FakeJevClient:
    def __init__(self) -> None:
        self.calls = 0
        self.phases: list[list[str]] = []

    async def system_one(self, *, state, questions, model, timeout):
        self.calls += 1
        self.phases.append(sorted(questions))
        answers = {}
        for question_id, spec in questions.items():
            qtype = str((spec or {}).get("type") or "noul")
            if qtype == "choice":
                criteria = (spec or {}).get("criteria") or {}
                choice = next(iter(criteria), "generate_answer")
                answers[question_id] = {
                    "type": "choice",
                    "choice": choice,
                    "confidence": 0.9,
                    "probabilities": {choice: 0.9},
                }
            elif qtype == "score":
                answers[question_id] = {"type": "score", "score": 2.5, "confidence": 0.9}
            else:
                answers[question_id] = {"type": "noul", "noul": 0.9}
        return {
            "model": model,
            "answers": answers,
            "usage": {"input_tokens": 50, "output_tokens": 20},
        }


def _engine(client: FakeJevClient) -> DecisionEngine:
    settings = DecisionEngineSettings(
        routing_mode="jev",
        jev_api_key="test-key",
        batch_mode="on",
        fallback_model="cheap",
    )
    provider = JevDecisionProvider(settings, client=client)
    return DecisionEngine(provider, settings, jev=provider)


@pytest.mark.asyncio
async def test_run_pack_hace_una_sola_llamada_por_fase() -> None:
    client = FakeJevClient()
    engine = _engine(client)
    request_id = uuid4()

    decision = await OrchestratorPreflightHook(
        PreflightSettings(mode=MODE_ON), judge=engine, policy=_policy()
    ).judge_pre_reasoning(
        trace=None,
        query="¿El registro necesita un CLOSE?",
        organization_id=uuid4(),
        request_id=request_id,
        sql_enabled=True,
    )
    # Un solo llamado, muchas preguntas: 11 juicios en 1 request.
    assert client.calls == 1
    assert len(client.phases[0]) == len(
        build_phase_questions("pre_reasoning", available={"sql_enabled"}).ids()
    )
    assert decision.decided_by == DECIDED_BY_JEV


@pytest.mark.asyncio
async def test_run_pack_reutiliza_el_juicio_del_mismo_estado() -> None:
    client = FakeJevClient()
    engine = _engine(client)
    hook = OrchestratorPreflightHook(
        PreflightSettings(mode=MODE_ON), judge=engine, policy=_policy()
    )
    request_id = uuid4()
    trace = hook.new_trace(request_id=request_id)
    first = await hook.judge_pre_generation(
        trace=trace,
        query="¿El registro necesita un CLOSE?",
        signals=_signals(),
        organization_id=uuid4(),
        request_id=request_id,
        evidence="registro 1 | UPDATE",
    )
    assert first.pack is not None and first.pack.ok
    assert first.pack.cached is False
    calls_after_first = client.calls
    second = await hook.judge_pre_generation(
        trace=trace,
        query="¿El registro necesita un CLOSE?",
        signals=_signals(),
        organization_id=uuid4(),
        request_id=request_id,
        evidence="registro 1 | UPDATE",
    )
    # Mismo request, mismo estado ⇒ se reutiliza el payload (sin doble costo).
    assert client.calls == calls_after_first
    assert second.pack is not None and second.pack.cached is True


# ---------------------------------------------------------------------------
# §64 — shadow: JEV dice qué haría, la ejecución legacy manda
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shadow_no_aplica_la_decision() -> None:
    judge = FakeJudge()
    hook = OrchestratorPreflightHook(
        PreflightSettings(mode=MODE_SHADOW), judge=judge, policy=_policy()
    )
    assert hook.controls_request(uuid4()) is False
    result = await hook.judge_pre_generation(
        trace=None,
        query="¿El registro necesita un CLOSE?",
        signals=_signals(),
        organization_id=uuid4(),
        request_id=uuid4(),
    )
    assert result.decision.applied is False
    assert result.decision.mode == MODE_SHADOW


def test_modo_desconocido_cae_en_off() -> None:
    assert normalize_preflight_mode("nonsense") == "off"
    assert normalize_preflight_mode("ON") == MODE_ON


# ---------------------------------------------------------------------------
# §34, §35, §40 — la historia muestra el juicio y su efecto
# ---------------------------------------------------------------------------


def test_historia_agrupa_packs_y_muestra_efectos() -> None:
    flow = {
        "steps": [],
        "sources": [],
        "jev_preflight": {
            "mode": MODE_ON,
            "summary": {"calls": 2, "judgments": 5, "decisions_influenced": 1},
            "packs": [
                {
                    "phase": "pre_generation",
                    "status": "ok",
                    "mode": MODE_ON,
                    "question_count": 3,
                    "latency_ms": 36.4,
                    "questions": [
                        {
                            "id": "analysis_complete",
                            "type": "noul",
                            "decision": "yes",
                            "value": 0.96,
                            "certainty": 0.92,
                            "effect": "generation_allowed",
                        },
                        {
                            "id": "needs_state_reconstruction",
                            "type": "noul",
                            "decision": "yes",
                            "value": 0.97,
                            "certainty": 0.94,
                            "effect": "state_reconstruction_activated",
                        },
                        {
                            "id": "generation_tier",
                            "type": "choice",
                            "decision": "small",
                            "confidence": 0.88,
                            "effect": "generation_tier_small",
                        },
                    ],
                }
            ],
            "decisions": [
                {
                    "phase": "pre_generation",
                    "action": ACTION_GENERATE,
                    "tier": "small",
                    "allow_generation": True,
                    "applied": True,
                    "reasons": ["cheaper_tier_sufficient"],
                    "uncertain_critical": [],
                    "readiness": {"rows": [{"key": "evidence", "state": "ok", "source": "jev"}]},
                }
            ],
        },
    }
    events = with_story(flow)["events"]
    packs = [event for event in events if event["kind"] == "jev_pack"]
    assert len(packs) == 1
    pack = packs[0]
    assert pack["phase"] == "decision"
    assert pack["metrics"]["judgment_count"] == 3
    assert pack["metrics"]["effects"] == [
        "generation_allowed",
        "state_reconstruction_activated",
        "generation_tier_small",
    ]
    assert pack["metrics"]["readiness"]["rows"][0]["key"] == "evidence"
    assert pack["decision"]["tier"] == "small"
    assert pack["technical"]["question_count"] == 3


def test_la_historia_nunca_expone_razonamiento_privado() -> None:
    flow = {
        "jev_preflight": {
            "mode": MODE_ON,
            "packs": [
                {
                    "phase": "pre_generation",
                    "status": "ok",
                    "questions": [{"id": "analysis_complete", "type": "noul", "decision": "yes"}],
                }
            ],
            "decisions": [],
        }
    }
    rendered = str(with_story(flow))
    lowered = rendered.lower()
    for banned in ("chain-of-thought", "chain of thought", "scratchpad", "let me think"):
        assert banned not in lowered


# ---------------------------------------------------------------------------
# §54, §55 — reporte de efectividad y embudo
# ---------------------------------------------------------------------------


def _trace_and_decision(*, tier: str = "small", allow: bool = True):
    from src.decision.preflight import PreflightTrace

    trace = PreflightTrace(mode=MODE_ON)
    trace.add_pack(
        build_pack(
            phase=PHASE_PRE_GENERATION,
            payload={"answers": _ready_answers()},
            mode=MODE_ON,
            policy=_policy(),
        )
    )
    decision = LLMEscalationPolicy(policy=_policy()).evaluate(
        pack=trace.pack_for(PHASE_PRE_GENERATION), signals=_signals(), mode=MODE_ON
    )
    decision.tier = tier
    decision.allow_generation = allow
    decision.applied = allow
    return trace, decision


def test_reporte_de_efectividad_agrega_lo_observado() -> None:
    from src.decision.preflight_report import (
        clear_observations,
        observation_from_trace,
        preflight_questions,
        preflight_report,
        record_observation,
    )

    clear_observations()
    trace, decision = _trace_and_decision()
    record_observation(observation_from_trace(trace=trace, decision=decision, mode=MODE_ON))
    record_observation(
        observation_from_trace(
            trace=trace,
            decision=_trace_and_decision(tier="deterministic", allow=False)[1],
            mode=MODE_ON,
        )
    )
    report = preflight_report()
    assert report["kpis"]["requests_observed"] == 2
    assert report["kpis"]["judgments"] == 2 * trace.packs[0].question_count
    assert report["kpis"]["batched_calls"] == 2
    assert report["kpis"]["questions_per_call"] > 1
    assert report["kpis"]["llm_escalations_avoided"] == 1
    stages = {row["stage"]: row["count"] for row in report["funnel"]}
    assert stages["requests"] == 2
    assert stages["generation_blocked"] == 1
    asked = {row["id"]: row for row in report["questions"]}
    assert asked["analysis_complete"]["asked"] == 2
    assert asked["analysis_complete"]["version"] >= 1
    # El registro se expone para el modo técnico (§53).
    registry = {row["id"] for row in preflight_questions()}
    assert {"reasoning_shape", "next_action", "final_action"} <= registry
    clear_observations()


def test_endpoint_preflight_entrega_reporte_registro_y_politica() -> None:
    import asyncio

    import src.api.routes.decision as decision_routes
    from src.decision.preflight_report import clear_observations

    clear_observations()
    original = decision_routes.require_platform_permission
    decision_routes.require_platform_permission = lambda *args, **kwargs: None  # type: ignore[assignment]
    try:
        payload = asyncio.run(decision_routes.decision_preflight(request=None))  # type: ignore[arg-type]
    finally:
        decision_routes.require_platform_permission = original  # type: ignore[assignment]
    assert "kpis" in payload
    assert payload["mode"] in {"off", "shadow", "on", "canary"}
    assert payload["registry"]
    assert "questions" in payload["policy"]


# ---------------------------------------------------------------------------
# Robustez: sin JEV todo sigue igual
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sin_judge_no_hay_llamada_ni_bloqueo() -> None:
    hook = OrchestratorPreflightHook(
        PreflightSettings(mode=MODE_ON), judge=None, policy=_policy()
    )
    assert hook.enabled() is False
    pack = await run_pack(
        judge=None, phase=PHASE_PRE_GENERATION, state={"question": "x"}, mode=MODE_ON
    )
    assert pack.ok is False
    assert pack.skipped_reason == "judge_unavailable"


@pytest.mark.asyncio
async def test_modo_off_no_llama_a_jev() -> None:
    judge = FakeJudge()
    pack = await run_pack(
        judge=judge, phase=PHASE_PRE_GENERATION, state={"question": "x"}, mode="off"
    )
    assert judge.calls == 0
    assert pack.skipped_reason == "mode_off"


@pytest.mark.asyncio
async def test_judge_que_falla_no_rompe_el_pack() -> None:
    class Broken:
        async def judge(self, *, state, questions, context=None):
            raise RuntimeError("jev down")

    pack = await run_pack(
        judge=Broken(), phase=PHASE_PRE_GENERATION, state={"question": "x"}, mode=MODE_ON
    )
    assert pack.ok is False
    assert pack.error is True
