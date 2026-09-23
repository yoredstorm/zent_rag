# =============================================================================
# Response Intelligence — golden tests (§55-§64 del spec).
# =============================================================================
# Estos tests fijan el CONTRATO de composición: qué forma se elige, qué se
# inyecta al generador y qué se publica en la traza. No verifican redacción.
# =============================================================================
from __future__ import annotations

import pytest

from src.core.domain.response import (
    DETAIL_BRIEF,
    DETAIL_DEEP,
    DETAIL_DETAILED,
    SECTION_DIRECT_ANSWER,
    SECTION_LIMITATIONS,
    SECTION_SOURCES,
    ResponseProfile,
)
from src.decision.batch import (
    build_post_generation_questions,
    build_response_composition_questions,
)
from src.decision.registry import default_registry
from src.intelligence.response.blueprints import (
    COMPARISON,
    DEFINITION_EXPLANATION,
    DIAGNOSTIC,
    DIRECT_FACT,
    PROCEDURE,
    SCENARIO_ANALYSIS,
    TECHNICAL_EXPLANATION,
    TUTORIAL,
    public_blueprints,
    register_blueprint,
)
from src.intelligence.response.contract import compose_contract, prompt_block
from src.intelligence.response.profile import (
    RESPONSE_PROFILE_PRESETS,
    apply_turn_overrides,
    detect_turn_overrides,
    profile_from_config,
    profile_prompt_block,
)
from src.intelligence.response.questions import (
    NUOL_QUESTIONS,
    read_composition_answers,
)
from src.intelligence.response.selector import (
    DECIDED_BY_JEV,
    DECIDED_BY_RULES,
    select_blueprint,
)
from src.intelligence.response.wiring import (
    MODE_OFF,
    MODE_ON,
    SOURCE_JEV,
    SOURCE_OFF,
    compose_for_request,
)

# Frases que delatan razonamiento privado: nunca en contrato, prompt ni traza.
COT_MARKERS = (
    "primero pensé",
    "después razoné",
    "chain of thought",
    "chain-of-thought",
    "pensamiento interno",
    "primero pensemos",
    "let me think step by step",
    "razonamiento privado:",
)


def _fake_judge(answers: dict | None = None):
    class FakeJudge:
        def __init__(self) -> None:
            self.calls = 0
            self.phases: list[str] = []
            self.questions: list[list[str]] = []

        async def judge(self, *, state, questions, context=None):
            self.calls += 1
            self.phases.append(str(getattr(context, "phase", "")))
            self.questions.append(sorted(questions))
            payload: dict = {}
            for question_id, spec in questions.items():
                if answers and question_id in answers:
                    payload[question_id] = answers[question_id]
                    continue
                qtype = str((spec or {}).get("type") or "noul")
                if qtype == "choice":
                    criteria = (spec or {}).get("criteria") or {}
                    choice = next(iter(criteria), TECHNICAL_EXPLANATION)
                    payload[question_id] = {
                        "type": "choice",
                        "choice": choice,
                        "confidence": 0.86,
                        "probabilities": {choice: 0.86},
                    }
                elif qtype == "score":
                    payload[question_id] = {"type": "score", "score": 2.0, "confidence": 0.8}
                else:
                    payload[question_id] = {"type": "noul", "noul": 0.9}
            return {
                "model": "jev-test",
                "answers": payload,
                "usage": {"input_tokens": 12, "output_tokens": 6},
            }

    return FakeJudge()


# ---------------------------------------------------------------------------
# §55 — Pregunta sobre un campo técnico con valor
# ---------------------------------------------------------------------------


def test_technical_field_question_eligiendo_explicacion_tecnica() -> None:
    selection = select_blueprint(question="¿Qué significa el campo X cuando su valor es 2?")
    assert selection.blueprint == TECHNICAL_EXPLANATION
    assert selection.decided_by == DECIDED_BY_RULES
    contract = compose_contract(
        question="¿Qué significa el campo X cuando su valor es 2?",
        profile=RESPONSE_PROFILE_PRESETS["technical_detailed"],
        selection=selection,
        answers=read_composition_answers(
            {
                "answers": {
                    "response_blueprint": {
                        "type": "choice",
                        "choice": TECHNICAL_EXPLANATION,
                        "confidence": 0.9,
                        "probabilities": {TECHNICAL_EXPLANATION: 0.9},
                    },
                    "required_detail": {"type": "score", "score": 2.0, "confidence": 0.9},
                    "needs_example": {"type": "noul", "noul": 0.9},
                    "needs_table": {"type": "noul", "noul": 0.8},
                    "needs_citations": {"type": "noul", "noul": 0.95},
                }
            }
        ),
    )
    assert contract.blueprint == TECHNICAL_EXPLANATION
    assert contract.detail == DETAIL_DETAILED
    assert contract.conclusion_first is True
    assert SECTION_DIRECT_ANSWER in contract.sections
    assert "meaning" in contract.sections
    assert "practical_effect" in contract.sections
    assert "example" in contract.sections
    assert contract.formatting["table"] is True
    assert contract.evidence["citations_required"] is True
    block = prompt_block(contract)
    assert "empieza por la conclusión" in block
    assert "cita la fuente junto a la afirmación" in block
    assert "conserva los términos técnicos" in block
    assert "nada de relleno" in block


# ---------------------------------------------------------------------------
# §56 — Dato simple
# ---------------------------------------------------------------------------


def test_simple_fact_sin_encabezados_ni_ejemplo() -> None:
    selection = select_blueprint(question="¿Cuál es el código de Carrier?")
    assert selection.blueprint == DIRECT_FACT
    contract = compose_contract(
        question="¿Cuál es el código de Carrier?",
        profile=RESPONSE_PROFILE_PRESETS["concise"],
        selection=selection,
    )
    assert contract.detail == DETAIL_BRIEF
    assert contract.sections == (SECTION_DIRECT_ANSWER,)
    assert contract.formatting["headings"] is False
    assert "example" not in contract.sections
    block = prompt_block(contract)
    assert "no usar: encabezados, tablas" in block


def test_dato_simple_no_se_convierte_en_articulo_por_perfil_profundo() -> None:
    profile = ResponseProfile(default_detail=DETAIL_DEEP, use_tables=True)
    contract = compose_contract(
        question="¿Cuál es el valor de Record 2?",
        profile=profile,
        selection=select_blueprint(question="¿Cuál es el valor de Record 2?"),
    )
    assert contract.detail in {DETAIL_DETAILED, DETAIL_BRIEF, "normal"}


# ---------------------------------------------------------------------------
# §57 — Escenario
# ---------------------------------------------------------------------------


def test_scenario_con_secuencia_y_alternativa_descartada() -> None:
    selection = select_blueprint(
        question="¿Falta un cierre en estos registros?",
        shape="STATE_TRANSITION",
        has_records=True,
    )
    assert selection.blueprint == SCENARIO_ANALYSIS
    contract = compose_contract(
        question="¿Falta un cierre en estos registros?",
        selection=selection,
        shape="STATE_TRANSITION",
        has_records=True,
    )
    assert "sequence" in contract.sections
    assert "why" in contract.sections
    assert "discarded_alternative" in contract.sections
    assert "what_to_check" in contract.sections
    block = prompt_block(contract)
    assert "sólo con inferencias respaldadas" in block
    assert "la explicación alternativa descartada" in block


# ---------------------------------------------------------------------------
# §58 — Comparación
# ---------------------------------------------------------------------------


def test_comparacion_usa_tabla_con_atributos_comparables() -> None:
    selection = select_blueprint(question="¿Cuál es la diferencia entre Fare Basis y Fare Class?")
    assert selection.blueprint == COMPARISON
    contract = compose_contract(
        question="¿Cuál es la diferencia entre Fare Basis y Fare Class?",
        selection=selection,
        answers=read_composition_answers(
            {"answers": {"needs_table": {"type": "noul", "noul": 0.9}}}
        ),
    )
    assert contract.formatting["table"] is True
    assert "comparison" in contract.sections
    block = prompt_block(contract)
    assert "tabla" in block


# ---------------------------------------------------------------------------
# §59 — Desconocido: nada de certeza falsa
# ---------------------------------------------------------------------------


def test_desconocido_prohibe_lenguaje_definitivo() -> None:
    contract = compose_contract(
        question="¿Por qué falló el cierre del período?",
        selection=select_blueprint(question="¿Por qué falló el cierre del período?"),
        unresolved=("ANALYSIS_INCOMPLETE",),
        missing_information=("falta el registro de cierre del período",),
    )
    assert contract.hedging_required is True
    assert SECTION_LIMITATIONS in contract.sections
    assert contract.evidence["disclose_missing_information"] is True
    block = prompt_block(contract)
    assert "prohibido el lenguaje definitivo" in block
    assert "falta el registro de cierre del período" in block
    assert "inference_unresolved" in contract.uncertainty_notes


# ---------------------------------------------------------------------------
# §60 — Conflicto de fuentes
# ---------------------------------------------------------------------------


def test_conflicto_de_fuentes_no_se_fusiona() -> None:
    contract = compose_contract(
        question="¿Cuál es el límite del campo?",
        selection=select_blueprint(question="¿Cuál es el límite del campo?"),
        source_conflict=True,
        conflict_note="autoritativa: 10; secundaria: 12",
    )
    assert contract.source_conflict is True
    assert contract.evidence["disclose_conflicts"] is True
    assert SECTION_SOURCES in contract.sections
    block = prompt_block(contract)
    assert "no las fusiones en silencio" in block
    assert "source_conflict" in contract.uncertainty_notes


# ---------------------------------------------------------------------------
# §61 — Generador de perfil / propósito: sin hechos, sin capacidades inventadas
# ---------------------------------------------------------------------------


class _Agent:
    name = "ATPCO Specialist"
    description = "Analiza documentación técnica de tarifas"
    config_json = {"purpose": "Explicar reglas tarifarias"}
    tools = ["search_knowledge"]


def test_purpose_generator_no_inventa_capacidades() -> None:
    from src.intelligence.response.generator import (
        context_from_agent,
        suggest_profile,
        validate_purpose,
    )

    context = context_from_agent(
        agent=_Agent(), source_kinds=["pdf"], source_titles=["ATPCO Manual"]
    )
    purpose, warnings = validate_purpose(
        "Analiza documentación técnica ATPCO y responde consultas con evidencia "
        "autorizada. Además consulta la base de datos SQL y llama a la API del ERP.",
        context,
    )
    assert "SQL" not in purpose
    assert "API" not in purpose
    assert "ATPCO" in purpose
    assert warnings and "sql" in warnings[0]
    suggestion = suggest_profile(context=context)
    assert suggestion["preset"] == "technical_detailed"
    assert "conclusión" in suggestion["custom_instructions"]
    assert "sql" not in suggestion["custom_instructions"].lower()


def test_profile_no_contiene_hechos_de_dominio() -> None:
    profile = RESPONSE_PROFILE_PRESETS["technical_detailed"]
    block = profile_prompt_block(profile)
    assert "Byte" not in block
    assert "105" not in block
    assert "conserva la terminología del dominio" in block
    for marker in COT_MARKERS:
        assert marker not in block.lower()


# ---------------------------------------------------------------------------
# §64 — Sin chain-of-thought en contrato, prompt ni traza
# ---------------------------------------------------------------------------


def test_contrato_y_prompt_sin_chain_of_thought() -> None:
    contract = compose_contract(
        question="¿Qué significa el campo X cuando su valor es 2?",
        profile=RESPONSE_PROFILE_PRESETS["clear_didactic"],
    )
    block = prompt_block(contract).lower()
    for marker in COT_MARKERS:
        assert marker not in block
    public = contract.to_public_dict()
    serialized = str(public).lower()
    for marker in COT_MARKERS:
        assert marker not in serialized
    assert "sections" in public
    assert "formatting" in public


# ---------------------------------------------------------------------------
# Selección: determinista primero, JEV sólo con ambigüedad
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question,expected",
    [
        ("¿Qué es un fare component?", DEFINITION_EXPLANATION),
        ("¿Por qué falló la validación?", DIAGNOSTIC),
        ("¿Cómo hago para cargar un archivo?", PROCEDURE),
        ("Resumen ejecutivo del período", "executive_summary"),
        ("Enseñame cómo funciona la regla desde cero", TUTORIAL),
    ],
)
def test_seleccion_determinista_por_estructura(question: str, expected: str) -> None:
    assert select_blueprint(question=question).blueprint == expected


def test_forma_elegida_por_jev_cuando_empata() -> None:
    selection = select_blueprint(question="¿Qué significa el campo X con valor 2?")
    assert selection.ambiguous is True
    assert selection.needs_jev is True
    assert selection.runner_up == DEFINITION_EXPLANATION


def test_blueprint_registry_extensible() -> None:
    from src.intelligence.response.blueprints import Blueprint

    register_blueprint(
        Blueprint(
            id="incident_review",
            label="Revisión de incidente",
            purpose="Revisar un incidente con su línea de tiempo.",
            sections=("summary", "sequence", "evidence"),
        )
    )
    assert any(item["id"] == "incident_review" for item in public_blueprints())
    selection = select_blueprint(
        question="¿Qué significa el campo X con valor 2?",
        preferred_blueprints=("incident_review",),
    )
    assert selection.decided_by in {DECIDED_BY_RULES, "profile"}


# ---------------------------------------------------------------------------
# JEV: un pack, una llamada, Noul honesto
# ---------------------------------------------------------------------------


def test_pack_de_composicion_es_una_sola_llamada() -> None:
    pack = build_response_composition_questions()
    ids = set(pack.ids())
    assert {"response_blueprint", "required_detail"} <= ids
    assert set(NUOL_QUESTIONS) <= ids
    assert len(ids) == 2 + len(NUOL_QUESTIONS)
    payload = pack.to_jevy()
    assert payload["response_blueprint"]["criteria"]
    assert payload["required_detail"]["criteria"]


def test_noul_051_no_es_un_si() -> None:
    answers = read_composition_answers(
        {"answers": {"needs_example": {"type": "noul", "noul": 0.51}}}
    )
    assert answers.needs_flag("needs_example") is False
    assert "needs_example" in answers.uncertain


def test_noul_cero_es_un_no_explicito() -> None:
    answers = read_composition_answers(
        {"answers": {"needs_citations": {"type": "noul", "noul": 0.0}}}
    )
    assert answers.needs_flag("needs_citations") is False
    assert answers.uncertain == ()


@pytest.mark.asyncio
async def test_compose_for_request_llama_al_judge_una_vez() -> None:
    judge = _fake_judge(
        {
            "response_blueprint": {
                "type": "choice",
                "choice": DIAGNOSTIC,
                "confidence": 0.8,
                "probabilities": {DIAGNOSTIC: 0.8, SCENARIO_ANALYSIS: 0.15},
            }
        }
    )
    plan = await compose_for_request(
        question="¿Qué significa el campo X con valor 2?",
        judge=judge,
        mode=MODE_ON,
    )
    assert judge.calls == 1
    assert plan.source == SOURCE_JEV
    assert plan.contract.blueprint == DIAGNOSTIC
    assert plan.contract.decided_by == DECIDED_BY_JEV
    assert judge.phases == ["response_composition"]


@pytest.mark.asyncio
async def test_modo_off_no_compone_contrato() -> None:
    plan = await compose_for_request(question="¿Qué es X?", mode=MODE_OFF)
    assert plan.contract is None
    assert plan.source == SOURCE_OFF
    assert plan.active is False


@pytest.mark.asyncio
async def test_modo_rules_no_gasta_llamadas() -> None:
    judge = _fake_judge()
    plan = await compose_for_request(
        question="¿Qué significa el campo X con valor 2?",
        judge=judge,
        mode="rules",
    )
    assert judge.calls == 0
    assert plan.source == "rules"
    assert plan.contract.blueprint == TECHNICAL_EXPLANATION


@pytest.mark.asyncio
async def test_judge_que_falla_no_rompe_el_contrato() -> None:
    class BrokenJudge:
        async def judge(self, **kwargs):
            raise RuntimeError("judge down")

    plan = await compose_for_request(
        question="¿Qué significa el campo X con valor 2?",
        judge=BrokenJudge(),
        mode=MODE_ON,
    )
    assert plan.contract is not None
    assert plan.contract.blueprint == TECHNICAL_EXPLANATION


# ---------------------------------------------------------------------------
# Perfil del agente y overrides del turno
# ---------------------------------------------------------------------------


def test_perfil_desde_config_es_tolerante() -> None:
    assert profile_from_config(None).tone == "professional"
    profile = profile_from_config({"response_profile": {"preset": "executive"}})
    assert profile.default_detail == "normal"
    broken = profile_from_config(
        {"response_profile": {"tone": "hacker", "default_detail": "enorme"}}
    )
    assert broken.tone == "professional"
    assert broken.default_detail == "normal"


def test_override_del_turno_no_cambia_el_perfil() -> None:
    profile = RESPONSE_PROFILE_PRESETS["technical_detailed"]
    assert detect_turn_overrides("respóndeme corto")["default_detail"] == DETAIL_BRIEF
    effective = apply_turn_overrides(profile, "explícamelo como experto")
    assert effective.technical_level == "expert"
    assert profile.technical_level != "expert"
    contract = compose_contract(
        question="¿Qué significa el campo X con valor 2?", profile=profile
    )
    short = compose_contract(
        question="respóndeme corto: ¿qué significa el campo X con valor 2?", profile=profile
    )
    assert contract.detail != short.detail or short.formatting["headings"] is False


# ---------------------------------------------------------------------------
# Gate de presentación (§24, §25)
# ---------------------------------------------------------------------------


def test_gate_de_presentacion_en_el_mismo_pack() -> None:
    with_gate = set(build_post_generation_questions(claims=["a"]).ids())
    without = set(build_post_generation_questions(claims=["a"], include_presentation=False).ids())
    for question_id in (
        "answer_explains_key_reason",
        "answer_is_needlessly_verbose",
        "important_context_missing",
        "structure",
        "usefulness",
        "revision_reason",
    ):
        assert question_id in with_gate
        assert question_id not in without
    assert with_gate - without == {
        "answer_explains_key_reason",
        "answer_is_needlessly_verbose",
        "important_context_missing",
        "structure",
        "usefulness",
        "revision_reason",
    }
    presentation = [
        definition
        for definition in default_registry().for_phase("post_generation")
        if definition.source == "presentation"
    ]
    assert len(presentation) == 6


def test_revision_reason_es_choice_con_opciones_cerradas() -> None:
    definition = default_registry().get("revision_reason")
    assert definition is not None
    assert definition.type == "choice"
    assert "too_verbose" in definition.options
    assert "unsupported_claim" in definition.options
    assert definition.threshold_key == "revision_reason"


# ---------------------------------------------------------------------------
# Trazas: el contrato y la planificación de la respuesta son datos del run
# ---------------------------------------------------------------------------


class _FlowResult:
    def __init__(self, response_plan: dict | None) -> None:
        self.run_id = "run-1"
        self.agent_id = "agent-1"
        self.organization_id = None
        self.status = "completed"
        self.answer = "ok"
        self.steps = [
            {
                "type": "response_planning",
                "status": "ok",
                "detail": "technical_explanation · detailed",
                "blueprint": "technical_explanation",
                "detail_level": "detailed",
                "decided_by": "rules",
                "needs_example": True,
                "citations_required": True,
            },
            {"type": "llm", "step": 1, "model": "gpt-4o-mini", "tokens": 120, "latency_ms": 900},
        ]
        self.spans = [{"stage": "llm", "duration_ms": 900}]
        self.total_latency_ms = 1200.0
        self.total_tokens = 120
        self.prompt_tokens = 80
        self.completion_tokens = 40
        self.cost = 0.0004
        self.model = "gpt-4o-mini"
        self.provider = "openai"
        self.response_plan = response_plan


def test_flow_v2_expone_la_forma_de_explicar() -> None:
    from src.rag.flow_story import STEP_KIND_PHASES, build_flow_events
    from src.runtime.agent_flow import build_agent_flow

    plan = {
        "mode": "rules",
        "source": "rules",
        "contract": {
            "blueprint": "technical_explanation",
            "detail": "detailed",
            "sections": ["direct_answer", "meaning"],
            "formatting": {"table": False},
            "evidence": {"citations_required": True},
            "decided_by": "rules",
        },
        "selection": {"blueprint": "technical_explanation", "decided_by": "deterministic"},
    }
    flow = build_agent_flow(result=_FlowResult(plan), question="¿Qué significa X?")
    assert flow["flow_version"] == 2
    assert flow["response_contract"]["blueprint"] == "technical_explanation"
    assert flow["response"]["mode"] == "rules"
    # El step de planificación de respuesta no se pierde ni queda sin mapping.
    assert STEP_KIND_PHASES["response_planning"] == "planning"
    events = build_flow_events(flow)
    planning = [event for event in events if event["phase"] == "planning"]
    assert any(event["kind"] == "response_planning" for event in planning)
    planned = next(event for event in planning if event["kind"] == "response_planning")
    assert planned["metrics"]["blueprint"] == "technical_explanation"
    assert planned["technical"].get("unmapped") is not True


def test_flow_sin_contrato_no_lo_inventa() -> None:
    from src.runtime.agent_flow import build_agent_flow

    flow = build_agent_flow(result=_FlowResult(None), question="hola")
    assert "response_contract" not in flow
    assert "response" not in flow


# ---------------------------------------------------------------------------
# §24, §25: gate de presentación en la misma llamada del gate de respuesta
# ---------------------------------------------------------------------------


def test_gate_de_respuesta_suma_presentacion_sin_segunda_llamada() -> None:
    from src.runtime.answer_gate import revision_feedback
    from src.runtime.questions import answer_gate_questions

    base = answer_gate_questions(include_presentation=False)
    with_gate = answer_gate_questions(include_presentation=True)
    assert "revision_reason" not in base
    assert "revision_reason" in with_gate
    assert set(with_gate) - set(base) == {
        "answer_explains_key_reason",
        "answer_is_needlessly_verbose",
        "important_context_missing",
        "structure",
        "usefulness",
        "revision_reason",
    }
    assert revision_feedback({"revision_reason": {"type": "choice", "choice": "missing_example"}}) == (
        "agrega un ejemplo breve que aclare la regla"
    )
    assert revision_feedback({"revision_reason": {"type": "choice", "choice": "no_existe"}}) == ""
    assert revision_feedback(None) == ""


@pytest.mark.asyncio
async def test_revision_por_presentacion_llega_al_feedback() -> None:
    """El motivo de revisión se traduce en instrucción para el generador."""
    from src.runtime.answer_gate import judge_answer

    class GateJudge:
        async def judge(self, *, state, questions, context=None):
            answers: dict = {
                "answer_grounded": {"type": "noul", "noul": 0.9},
                "answer_complete": {"type": "noul", "noul": 0.3},
                "answer_quality": {"type": "score", "score": 2.0},
                "revision_reason": {"type": "choice", "choice": "missing_explanation"},
            }
            return {"model": "jev-test", "answers": answers}

    result = await judge_answer(
        engine=GateJudge(),
        mode="on",
        user_request="¿Qué significa X?",
        draft="X significa Y.",
        observations=["doc: X significa Y"],
        settings=object(),
    )
    assert result.verdict == "revise"
    assert "explica el motivo" in result.feedback
