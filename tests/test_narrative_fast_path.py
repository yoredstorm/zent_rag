# =============================================================================
# Narrative fast path — routing, presupuesto, identidad de build.
# =============================================================================
from __future__ import annotations

from src.runtime.narrative_fast_path import (
    EVIDENCE_ONLY,
    NARRATIVE_FAST_PATH,
    ROUTE_AGENT,
    ROUTE_DETERMINISTIC,
    ROUTE_SCENARIO,
    TIER_FAST_NARRATIVE,
    TIER_STANDARD,
    completeness_for_finish,
    compress_narrative_context,
    grounded_answer_policy,
    jev_needed,
    narrative_model_for,
    narrative_route,
    output_token_budget,
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
