# =============================================================================
# Narrative fast path — routing, presupuesto, identidad de build.
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace

from src.runtime.narrative_fast_path import (
    EVIDENCE_ONLY,
    NARRATIVE_FAST_PATH,
    ROUTE_AGENT,
    ROUTE_DETERMINISTIC,
    ROUTE_SCENARIO,
    TIER_FAST_NARRATIVE,
    TIER_STANDARD,
    aspect_coverage_rows,
    completeness_for_finish,
    compress_narrative_context,
    concept_coverage_rows,
    coverage_gap_prompt_note,
    entity_coverage_rows,
    fast_path_overrun,
    final_aspect_statuses,
    grounded_answer_policy,
    jev_needed,
    mark_partial_grounded,
    narrative_context_blocks,
    narrative_frame_lines,
    narrative_frame_rows,
    narrative_model_for,
    narrative_route,
    output_token_budget,
    patch_narrative_verification,
    prompt_char_budget,
    source_identity,
)
from src.runtime.runtime_identity import build_parity

CASE_INFO = "cuentame sobre el record 2 en general sobre el cierre de fechas"
CASE_SCENARIO = (
    "tengo estas tres secuencias Record 2 y quiero saber por qué terminó aplicando la última"
)
CASE_EXECUTABLE = "&&&F vs ABCFGEGE cumple?"


def test_informational_uses_narrative_fast_path() -> None:
    route = narrative_route(CASE_INFO)
    assert route.eligible is True
    assert route.route == NARRATIVE_FAST_PATH
    assert route.query_mode == "INFORMATIONAL"
    assert route.shape in {"SIMPLE_LOOKUP", "MULTI_EVIDENCE"}
    assert route.blueprint == "technical_explanation"
    assert route.llm_calls == 1
    assert route.jev == "skip"
    assert jev_needed() is False


def test_scenario_and_executable_are_not_narrative() -> None:
    scenario = narrative_route(CASE_SCENARIO)
    assert scenario.eligible is False
    assert scenario.route == ROUTE_SCENARIO
    executable = narrative_route(CASE_EXECUTABLE)
    assert executable.eligible is False
    assert executable.route == ROUTE_DETERMINISTIC
    assert executable.llm_calls == 0


def test_dates_do_not_force_jev() -> None:
    assert jev_needed() is False
    assert jev_needed(conflicts=1) is True


def test_conversational_prefix_keeps_agent_route() -> None:
    route = narrative_route("buenas, qué significa byte 105?")
    assert route.eligible is False
    assert route.route == ROUTE_AGENT
    assert route.reason == "conversational_prefix"
    plain = narrative_route("qué significa byte 105?")
    assert plain.eligible is True


def test_context_drops_footer_and_duplicate_heading() -> None:
    text = compress_narrative_context(
        [
            "# Cierre\nla vigencia termina\nPage 3\nparser_engine: odl",
            "# Cierre\notra vez el mismo titulo\nla secuencia cierra",
        ],
        max_chars=2000,
    )
    assert "Page 3" not in text
    assert "parser_engine" not in text
    assert text.lower().count("# cierre") == 1
    assert "vigencia" in text


def test_context_caps_each_block_around_the_needle() -> None:
    block = (
        "[Doc: 1] fuente\n"
        + ("relleno " * 500)
        + "Eff Date processing section "
        + ("cola " * 500)
    )
    text = compress_narrative_context(
        [block],
        max_chars=3000,
        needles=("eff date",),
        max_block_chars=1600,
    )
    assert "eff date" in text.lower()
    assert len(text) <= 1800


def test_desired_output_is_a_target_not_a_hard_cap() -> None:
    assert prompt_char_budget(CASE_INFO, evidence_items=5) <= 8_000
    assert output_token_budget("technical_explanation") > 800
    assert 200 <= output_token_budget("direct_fact") <= 400


def test_truncation_does_not_erase_grounding() -> None:
    completeness, overall = completeness_for_finish("length", "VERIFIED_GROUNDED")
    assert completeness == "TRUNCATED"
    assert overall == "PARTIALLY_COMPLETE_BUT_GROUNDED"


def test_source_identity_marks_weak_without_dropping_fields() -> None:
    weak = source_identity({"parser_engine": "opendataloader"})
    assert weak["identity_status"] == "WEAK"
    assert weak["parser_engine"] == "opendataloader"
    strong = source_identity(
        {
            "document_id": "doc-1",
            "filename": "Rec2_Rules_dapp_C.pdf",
            "representation_kind": "llm_markdown",
            "canonical_evidence_id": "ev-1",
        }
    )
    assert strong["identity_status"] == "OK"
    assert strong["filename"] == "Rec2_Rules_dapp_C.pdf"


def test_build_parity_expected_sha_and_unknown_without_metadata() -> None:
    match = build_parity(
        {"git_sha": "5c68bef35efd1a10"},
        {"git_sha": "5c68bef35efd1a10"},
        expected_sha="5c68bef",
    )
    assert match["status"] == "MATCH"
    assert str(match["api_sha"]).startswith("5c68bef")
    stale = build_parity(
        {"git_sha": "52cdaa111111"},
        {"git_sha": "52cdaa111111"},
        expected_sha="5c68bef",
    )
    assert stale["status"] == "METADATA_INCONSISTENT"
    unknown = build_parity({"git_sha": "unknown"}, None, expected_sha="5c68bef")
    assert unknown["status"] == "UNKNOWN"


def test_grounded_policy_forbids_external_domain_knowledge() -> None:
    policy = grounded_answer_policy()
    assert policy.mode == EVIDENCE_ONLY
    assert policy.evidence_only is True
    rules = policy.instructions().lower()
    assert "no recomiendes categor" in rules
    assert "implicación práctica" in rules
    assert "no encontraste respaldo suficiente" in rules
    assert "sentido material" in rules
    assert "una única vez" in rules


def test_narrative_model_policy_configurable_with_agent_fallback() -> None:
    configured = narrative_model_for(
        {"narrative_model": "openai/gpt-4o-mini"}, "big-model"
    )
    assert configured.model == "openai/gpt-4o-mini"
    assert configured.tier == TIER_FAST_NARRATIVE
    assert configured.source == "agent.config.narrative_model"
    fallback = narrative_model_for({}, "big-model")
    assert fallback.model == "big-model"
    assert fallback.tier == TIER_STANDARD
    assert fallback.source == "agent.model"


def test_routing_benchmark() -> None:
    informational = [
        frame.format(topic=topic)
        for frame in (
            "cuentame sobre {topic} en general",
            "explicame como funciona {topic}",
            "que significa {topic}",
            "overview de {topic}",
        )
        for topic in (
            "record 2",
            "cierre de fechas",
            "vigencia",
            "secuencia",
            "estado",
            "registro",
            "fecha",
            "regla",
            "match",
            "effective date",
            "disc date",
            "fare basis",
            "byte 105",
            "categoria 31",
            "discontinuidad",
            "tarifa",
            "calendario",
            "publicacion",
            "historico",
            "glosario",
            "campo",
            "tabla",
            "nota",
            "apendice",
            "manual",
        )
    ]
    assert len(informational) == 100
    scenario = [
        f"tengo la secuencia {index}000 del record y por qué terminó aplicando la última"
        for index in range(1, 51)
    ]
    executable = [
        f"&&&{chr(65 + (index % 20))} vs ABC{index}FGE cumple?"
        for index in range(50)
    ]
    diagnostic = [
        f"por qué falló la validación del lote {index}"
        for index in range(50)
    ]
    info_hits = sum(1 for question in informational if narrative_route(question).eligible)
    scenario_hits = sum(
        1 for question in scenario if narrative_route(question).route == ROUTE_SCENARIO
    )
    executable_hits = sum(
        1
        for question in executable
        if narrative_route(question).route == ROUTE_DETERMINISTIC
    )
    diagnostic_kept = sum(
        1 for question in diagnostic if not narrative_route(question).eligible
    )
    assert info_hits == 100
    assert scenario_hits == 50
    assert executable_hits == 50
    assert diagnostic_kept == 50


class TestExtraccionPura:
    """Bloques puros extraídos del closure `_narrative_fast_path`."""

    def test_frame_lines_solo_entidad_aspecto(self) -> None:
        plan = SimpleNamespace(
            frames=[
                SimpleNamespace(entity="Record 2", aspect="cierre de fechas"),
                SimpleNamespace(entity="Byte 105", aspect=""),
                SimpleNamespace(entity="", aspect="vigencia"),
                SimpleNamespace(entity="", aspect=""),
            ]
        )
        assert narrative_frame_lines(plan) == [
            "- entidad: Record 2; aspecto: cierre de fechas",
            "- entidad: Byte 105",
            "- aspecto: vigencia",
        ]

    def test_frame_lines_sin_frames(self) -> None:
        assert narrative_frame_lines(SimpleNamespace(frames=[])) == []
        assert narrative_frame_lines(None) == []

    def test_context_blocks_usa_el_match_vigente(self) -> None:
        active = SimpleNamespace(
            items=[
                SimpleNamespace(
                    title="Manual",
                    page=7,
                    content="contenido viejo",
                    metadata={"source_id": "s1"},
                )
            ],
            matches=[
                SimpleNamespace(content="contenido del match", evidence_id="e1")
            ],
        )
        blocks = narrative_context_blocks(active, question="¿qué dice?")
        assert blocks[0].startswith("[Doc: 1] Manual pág. 7")
        assert "contenido del match" in blocks[0]
        assert "contenido viejo" not in blocks[0]

    def test_context_blocks_sin_items(self) -> None:
        assert narrative_context_blocks(
            SimpleNamespace(items=[], matches=[]), question="q"
        ) == []

    def test_coverage_gap_note_lista_gaps_y_no_inventa(self) -> None:
        from src.runtime.narrative_coverage import COVERED, MISSING, PARTIAL_MATERIAL

        note = coverage_gap_prompt_note(
            [
                SimpleNamespace(status=COVERED, aspect="", label="ok"),
                SimpleNamespace(status=MISSING, aspect="cierre de fechas", label=""),
                SimpleNamespace(status=PARTIAL_MATERIAL, aspect="", label="vigencia"),
            ]
        )
        assert "cierre de fechas" in note
        assert "vigencia" in note
        assert "«Conclusión»" in note

    def test_coverage_gap_note_sin_gaps_dice_ninguno(self) -> None:
        from src.runtime.narrative_coverage import COVERED

        note = coverage_gap_prompt_note(
            [SimpleNamespace(status=COVERED, aspect="", label="ok")]
        )
        assert "ninguno" in note


class TestCierreExtraido:
    """Helpers del cierre narrativo extraídos del closure."""

    def test_overrun_dentro_de_tolerancia_no_corta(self) -> None:
        assert fast_path_overrun({"token_overrun": 10}, max_tokens=4000) == (False, "")

    def test_overrun_de_tokens_corta_por_token_budget(self) -> None:
        # tolerancia = max(128, 4000 // 50) = 128; 200 la supera.
        assert fast_path_overrun({"token_overrun": 200}, max_tokens=4000) == (
            True,
            "TOKEN_BUDGET",
        )

    def test_overrun_de_costo_manda_sobre_tokens(self) -> None:
        assert fast_path_overrun(
            {"token_overrun": 200, "cost_overrun_usd": 0.02}, max_tokens=4000
        ) == (True, "COST_BUDGET")

    def test_patch_verification_completa_el_ultimo_step(self) -> None:
        steps = [
            {
                "type": "narrative_evidence",
                "verification_input": {"supports": []},
            },
            {"type": "narrative_evidence", "verification_input": {"supports": ["a"]}},
        ]
        patch_narrative_verification(
            steps, finish_reason="length", completeness="TRUNCATED"
        )
        recorded = steps[-1]["verification_input"]
        assert recorded["finish_reason"] == "length"
        assert recorded["completeness"] == "TRUNCATED"
        assert recorded["truncated"] is True
        # El step viejo no se toca.
        assert "finish_reason" not in steps[0]["verification_input"]

    def test_patch_verification_sin_step_no_rompe(self) -> None:
        steps = [{"type": "final"}]
        patch_narrative_verification(
            steps, finish_reason="stop", completeness="COMPLETE"
        )
        assert steps == [{"type": "final"}]

    def test_mark_partial_grounded_agrega_gaps(self) -> None:
        steps = [
            {
                "type": "narrative_evidence",
                "verification_input": {"supports": [], "verification": "COMPLETE"},
            }
        ]
        gaps = [SimpleNamespace(aspect="cierre de fechas", label="")]
        assert mark_partial_grounded(steps, gaps) is True
        recorded = steps[0]["verification_input"]
        assert recorded["verification"] == "PARTIAL"
        assert recorded["grounding"] == "PARTIAL"
        assert recorded["supports"][0]["claim"] == "cierre de fechas"
        assert recorded["supports"][0]["status"] == "UNSUPPORTED"

    def test_mark_partial_grounded_sin_step_devuelve_false(self) -> None:
        assert mark_partial_grounded([{"type": "final"}], ["x"]) is False


class TestProyeccionesDeTraza:
    """Filas del payload de traza (puras; el closure ya no las inline)."""

    def _coverage(self):
        return [
            SimpleNamespace(
                concept_id="c1",
                label="cierre de fechas",
                status="COVERED",
                epistemic="DOCUMENTED",
                entity="Record 2",
                entity_status="COVERED",
                aspect="cierre de fechas",
                aspect_status="COVERED",
                role="PRIMARY",
            ),
            SimpleNamespace(
                concept_id="c2",
                label="vigencia",
                status="MISSING",
                epistemic="UNKNOWN",
                entity="",
                entity_status="",
                aspect="",
                aspect_status="",
                role="SECONDARY",
            ),
        ]

    def test_concept_rows(self) -> None:
        rows = concept_coverage_rows(self._coverage())
        assert rows[0] == {
            "id": "c1",
            "label": "cierre de fechas",
            "status": "COVERED",
            "epistemic": "DOCUMENTED",
        }
        assert len(rows) == 2

    def test_entity_rows_solo_con_entidad(self) -> None:
        rows = entity_coverage_rows(self._coverage())
        assert len(rows) == 1
        assert rows[0]["label"] == "Record 2"
        from src.runtime.narrative_coverage import QUALIFIER

        assert rows[0]["role"] == QUALIFIER

    def test_aspect_rows_y_status_final(self) -> None:
        rows = aspect_coverage_rows(self._coverage())
        assert rows[1]["label"] == "vigencia"
        assert rows[1]["status"] == "MISSING"
        assert final_aspect_statuses(self._coverage()) == ["COVERED", "MISSING"]

    def test_frame_rows(self) -> None:
        plan = SimpleNamespace(
            frames=[
                SimpleNamespace(
                    frame_id="f1",
                    entity="Record 2",
                    aspect="cierre",
                    relation="has_aspect",
                )
            ]
        )
        assert narrative_frame_rows(plan) == [
            {
                "id": "f1",
                "entity": "Record 2",
                "aspect": "cierre",
                "relation": "has_aspect",
            }
        ]
        assert narrative_frame_rows(None) == []


class TestPromptPlanExtraido:
    """`build_narrative_prompt_plan`: prompt y tope de UNA llamada."""

    def _active(self):
        return SimpleNamespace(
            items=[
                SimpleNamespace(
                    title="Manual",
                    page=3,
                    content="contenido",
                    metadata={},
                )
            ],
            matches=[SimpleNamespace(content="contenido del match")],
        )

    async def test_plan_con_presupuesto(self) -> None:
        from src.core.config import get_settings
        from src.runtime.narrative_fast_path import build_narrative_prompt_plan
        from src.runtime.run_budget import RunBudgetLedger

        result = SimpleNamespace(
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            cost=0.0,
            llm_calls=0,
            logical_steps=0,
            tool_calls=0,
        )
        ledger = RunBudgetLedger(
            result, max_steps=10, max_tokens=8000, max_cost_usd=None
        )
        plan = await build_narrative_prompt_plan(
            question="¿qué dice el record 2?",
            agent_instructions="instrucciones",
            agent_config=None,
            active=self._active(),
            concept_plan=SimpleNamespace(frames=[]),
            final_coverage=[],
            route=SimpleNamespace(blueprint="technical_explanation"),
            run_plan=None,
            settings=get_settings(),
            ledger=ledger,
            fallback_model="m1",
        )
        assert plan.exhausted_reason == ""
        assert "Evidencia:" in plan.user_prompt
        assert "[Doc: 1]" in plan.user_prompt
        assert "Reglas de grounding documental" in plan.system_prompt
        assert plan.model_policy.model == "m1"

    async def test_plan_usa_modelo_narrativo_del_agente(self) -> None:
        from src.core.config import get_settings
        from src.runtime.narrative_fast_path import build_narrative_prompt_plan
        from src.runtime.run_budget import RunBudgetLedger

        result = SimpleNamespace(
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            cost=0.0,
            llm_calls=0,
            logical_steps=0,
            tool_calls=0,
        )
        ledger = RunBudgetLedger(
            result, max_steps=10, max_tokens=8000, max_cost_usd=None
        )
        plan = await build_narrative_prompt_plan(
            question="q",
            agent_instructions="i",
            agent_config={"narrative_model": "fast-model"},
            active=self._active(),
            concept_plan=SimpleNamespace(frames=[]),
            final_coverage=[],
            route=SimpleNamespace(blueprint=""),
            run_plan=None,
            settings=get_settings(),
            ledger=ledger,
            fallback_model="m1",
        )
        assert plan.model_policy.model == "fast-model"

    async def test_plan_sin_presupuesto_no_genera(self) -> None:
        from src.core.config import get_settings
        from src.runtime.narrative_fast_path import build_narrative_prompt_plan
        from src.runtime.run_budget import RunBudgetLedger

        result = SimpleNamespace(
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            cost=0.0,
            llm_calls=0,
            logical_steps=0,
            tool_calls=0,
        )
        ledger = RunBudgetLedger(
            result, max_steps=10, max_tokens=0, max_cost_usd=None
        )
        plan = await build_narrative_prompt_plan(
            question="q",
            agent_instructions="i",
            agent_config=None,
            active=self._active(),
            concept_plan=SimpleNamespace(frames=[]),
            final_coverage=[],
            route=SimpleNamespace(blueprint=""),
            run_plan=None,
            settings=get_settings(),
            ledger=ledger,
            fallback_model="m1",
        )
        assert plan.exhausted_reason == "max_tokens exceeded"
        assert plan.stop_reason == "TOKEN_BUDGET"


class _FakeNarrativeLLM:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class _SlowThenFastLLM(_FakeNarrativeLLM):
    async def generate(self, **kwargs):
        import asyncio

        self.calls.append(kwargs)
        if kwargs.get("model") == "primary-model":
            await asyncio.sleep(0.2)
        return self.responses.pop(0)


def _llm_response(content: str, *, finish: str = "stop", tokens: int = 10):
    from src.core.domain.entities import LLMResponse

    return LLMResponse(
        content=content,
        model="m",
        prompt_tokens=tokens,
        completion_tokens=tokens,
        total_tokens=tokens * 2,
        finish_reason=finish,
    )


class TestGeneracionExtraida:
    """`generate_narrative_answer`: timeout, fallback y continuación."""

    async def test_generacion_normal_una_llamada(self) -> None:
        from src.runtime.narrative_fast_path import generate_narrative_answer

        llm = _FakeNarrativeLLM([_llm_response("respuesta")])
        result = await generate_narrative_answer(
            llm,
            user_prompt="p",
            system_prompt="s",
            model="primary-model",
            max_tokens=512,
        )
        assert result.skip_reason == ""
        assert result.response.content == "respuesta"
        assert result.provider_fallback is False
        assert [call["model"] for call in llm.calls] == ["primary-model"]
        assert llm.calls[0]["max_tokens"] == 512

    async def test_timeout_usa_el_fallback(self) -> None:
        from src.runtime.narrative_fast_path import generate_narrative_answer

        llm = _SlowThenFastLLM([_llm_response("desde fallback")])
        result = await generate_narrative_answer(
            llm,
            user_prompt="p",
            system_prompt="s",
            model="primary-model",
            max_tokens=512,
            timeout_seconds=0.01,
            fallback_model="fallback-model",
        )
        assert result.provider_fallback is True
        assert result.response.content == "desde fallback"
        assert [call["model"] for call in llm.calls] == [
            "primary-model",
            "fallback-model",
        ]
        assert result.primary_latency_ms > 0

    async def test_timeout_sin_fallback_no_genera(self) -> None:
        from src.runtime.narrative_fast_path import generate_narrative_answer

        llm = _SlowThenFastLLM([_llm_response("no debería usarse")])
        result = await generate_narrative_answer(
            llm,
            user_prompt="p",
            system_prompt="s",
            model="primary-model",
            max_tokens=512,
            timeout_seconds=0.01,
            fallback_model="",
        )
        assert result.skip_reason == "timeout_no_fallback"
        assert result.response is None
        assert [call["model"] for call in llm.calls] == ["primary-model"]

    async def test_continuacion_suma_tokens_y_cierra(self) -> None:
        from src.runtime.narrative_fast_path import generate_narrative_answer

        llm = _FakeNarrativeLLM(
            [
                _llm_response("parte 1", finish="length", tokens=10),
                _llm_response("parte 2", tokens=5),
            ]
        )
        result = await generate_narrative_answer(
            llm,
            user_prompt="p",
            system_prompt="s",
            model="primary-model",
            max_tokens=512,
            continuation_allowed=True,
            continuation_max_tokens=256,
        )
        assert result.response.content == "parte 1\nparte 2"
        assert result.response.total_tokens == 30
        assert result.response.finish_reason == "stop"
        assert llm.calls[1]["max_tokens"] == 256

    async def test_continuacion_no_permitida_no_llama(self) -> None:
        from src.runtime.narrative_fast_path import generate_narrative_answer

        llm = _FakeNarrativeLLM([_llm_response("cortada", finish="length")])
        result = await generate_narrative_answer(
            llm,
            user_prompt="p",
            system_prompt="s",
            model="primary-model",
            max_tokens=512,
            continuation_allowed=False,
        )
        assert len(llm.calls) == 1
        assert result.response.content == "cortada"
