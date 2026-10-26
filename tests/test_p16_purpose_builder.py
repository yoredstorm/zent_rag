# =============================================================================
# P16 — Intelligent Agent Purpose Builder
# =============================================================================
from __future__ import annotations

import json
from uuid import uuid4

import pytest

from src.intelligence.response.generator import (
    PURPOSE_MODE_CREATE,
    PURPOSE_MODE_EXPAND,
    PURPOSE_MODE_IMPROVE,
    AgentConfigContext,
    build_purpose_prompt,
    effective_purpose_mode,
    evaluate_purpose_intent,
    parse_purpose_response,
    suggest_purpose_intent,
)

NARRATOR = "Responde como un narrador de cuentos infantil"


def _context(**overrides) -> AgentConfigContext:
    payload = dict(
        name="Principito",
        description="Cuentos para chicos",
        purpose=NARRATOR,
        instructions="",
        profile_audience="technical",
        source_titles=("el_principito.pdf",),
        tools=("search_knowledge",),
    )
    payload.update(overrides)
    return AgentConfigContext(**payload)


def _payload(**overrides) -> dict:
    payload = {
        "schema": "zent.agent_purpose/v2",
        "intent_summary": "Explicar cuentos a niños con una voz narrativa.",
        "purpose": (
            "Eres un narrador de cuentos infantiles que ayuda a explorar historias "
            "con una voz cálida, clara e imaginativa. Explica qué ocurre en cada "
            "relato, conecta causas y consecuencias y propone una lectura sencilla. "
            "Cuando la evidencia no alcance, lo dice sin inventar hechos."
        ),
        "additional_instructions": (
            "Abrí con una imagen o una frase cercana.\n"
            "Usá ejemplos mínimos del texto cuando aclaren la historia.\n"
            "Separá lo que dice la obra de tu interpretación.\n"
            "Si falta evidencia, decilo sin especular.\n"
            "No menciones nombres internos de herramientas."
        ),
        "persona": {
            "role": "Narrador",
            "audience": "infantil",
            "voice": "cálida, imaginativa y clara",
            "communication_principles": [
                "una idea por frase",
                "no inventar hechos",
            ],
        },
        "behavioral_objectives": ["explicar la historia", "conservar la voz narrativa"],
        "knowledge_boundaries": ["no inventar contenido del documento"],
        "warnings": [],
    }
    payload.update(overrides)
    return payload


def test_mode_respects_explicit_choice_and_does_not_turn_edits_into_new_missions() -> None:
    assert effective_purpose_mode(_context(mode="auto")) == PURPOSE_MODE_EXPAND
    assert (
        effective_purpose_mode(_context(mode="auto", instructions="Una regla previa"))
        == PURPOSE_MODE_IMPROVE
    )
    assert effective_purpose_mode(_context(purpose="", description="")) == PURPOSE_MODE_CREATE
    assert effective_purpose_mode(_context(mode="improve")) == PURPOSE_MODE_IMPROVE


def test_prompt_uses_unsaved_fields_and_forbids_tool_inventory() -> None:
    prompt = build_purpose_prompt(_context(instructions="No inventes datos."), mode="expand")
    assert NARRATOR in prompt
    assert "No inventes datos." in prompt
    assert "el_principito.pdf" in prompt
    assert "No enumeres herramientas internas" in prompt
    assert "zent.agent_purpose/v2" in prompt
    assert "audiencia del perfil de estilo" in prompt


def test_structured_response_keeps_purpose_and_instructions_separate() -> None:
    draft = parse_purpose_response(json.dumps(_payload(), ensure_ascii=False), _context())
    assert draft.purpose.startswith("Eres un narrador")
    assert "Abrí con una imagen" in draft.additional_instructions
    assert draft.persona.role == "Narrador"
    assert draft.persona.audience == "infantil"
    quality = evaluate_purpose_intent(draft, _context())
    assert quality.passed is True, quality.to_public_dict()


def test_quality_rejects_tool_inventory_and_generic_filler() -> None:
    generic = _payload(
        purpose=(
            "Atender las consultas del usuario utilizando las herramientas "
            "disponibles de manera eficiente."
        ),
        additional_instructions="",
        persona={"role": "", "audience": "technical", "voice": ""},
    )
    draft = parse_purpose_response(json.dumps(generic, ensure_ascii=False), _context())
    quality = evaluate_purpose_intent(draft, _context())
    assert quality.passed is False
    assert "genericness" in quality.issues
    assert "unnecessary_tool_listing" in quality.issues or quality.generic_phrases


def test_quality_accepts_plural_child_audience() -> None:
    draft = parse_purpose_response(
        json.dumps(
            _payload(
                persona={
                    "role": "Narrador",
                    "audience": "Niños y niñas que escuchan cuentos",
                    "voice": "cálida",
                    "communication_principles": ["una idea por frase"],
                }
            ),
            ensure_ascii=False,
        ),
        _context(),
    )
    assert evaluate_purpose_intent(draft, _context()).criteria["audience_consistency"] is True


def test_quality_preserves_child_audience_against_profile_audience() -> None:
    draft = parse_purpose_response(json.dumps(_payload(), ensure_ascii=False), _context())
    assert evaluate_purpose_intent(draft, _context()).criteria["audience_consistency"] is True
    wrong = parse_purpose_response(
        json.dumps(
            _payload(
                persona={
                    "role": "Narrador",
                    "audience": "técnica",
                    "voice": "cálida",
                    "communication_principles": ["una idea por frase"],
                }
            ),
            ensure_ascii=False,
        ),
        _context(),
    )
    assert evaluate_purpose_intent(wrong, _context()).criteria["audience_consistency"] is False


def test_fallback_preserves_input_instead_of_generic_corporate_text() -> None:
    draft = suggest_purpose_intent(_context(), mode="expand")
    assert draft.purpose == NARRATOR
    assert draft.additional_instructions == ""
    assert "generation_unavailable_preserved_original" in draft.warnings


def test_plain_text_legacy_response_stays_compatible_but_is_flagged() -> None:
    draft = parse_purpose_response("Responde como un narrador de cuentos infantil.", _context())
    assert draft.purpose == "Responde como un narrador de cuentos infantil."
    assert "model_returned_text_not_json" in draft.warnings


# ---------------------------------------------------------------------------
# API: unsaved draft, structured response, quality failure
# ---------------------------------------------------------------------------


def _patch_route(monkeypatch, raw: str | Exception):
    import src.api.routes.agents as agents
    import src.platform.rbac.policy as policy
    from src.intelligence.response.generator import AgentConfigContext

    class FakeCtx:
        organization_id = uuid4()

    prompts: list[str] = []

    async def fake_owned_agent(ctx, agent_id):  # noqa: ANN001
        return object()

    async def fake_context(request, ctx, agent, source_ids_override=None):  # noqa: ANN001
        return AgentConfigContext(
            name="Guardado",
            description="Descripción guardada",
            purpose="Propósito guardado",
            profile_audience="technical",
        )

    async def fake_generate(
        prompt: str, *, max_tokens: int = 400, temperature: float = 0.2
    ) -> str:
        prompts.append(prompt)
        if isinstance(raw, Exception):
            raise raw
        return raw

    monkeypatch.setattr(policy, "require_permission", lambda *a, **k: FakeCtx())
    monkeypatch.setattr(agents, "_get_owned_agent", fake_owned_agent)
    monkeypatch.setattr(agents, "_agent_config_context", fake_context)
    monkeypatch.setattr(agents, "_generate_text", fake_generate)
    return prompts


@pytest.mark.asyncio
async def test_endpoint_uses_unsaved_fields_and_returns_structured_draft(monkeypatch) -> None:
    import src.api.routes.agents as agents

    prompts = _patch_route(monkeypatch, json.dumps(_payload(), ensure_ascii=False))
    payload = await agents.generate_agent_purpose(
        str(uuid4()),
        agents.GeneratePurposeRequest(
            purpose=NARRATOR,
            instructions="Instrucción sin guardar.",
            name="Principito",
            mode="expand",
        ),
        None,  # type: ignore[arg-type]
    )
    assert prompts and NARRATOR in prompts[0]
    assert "Instrucción sin guardar." in prompts[0]
    assert payload["draft"].startswith("Eres un narrador")
    assert payload["purpose"].startswith("Eres un narrador")
    assert "Abrí con una imagen" in payload["additional_instructions"]
    assert payload["quality"]["passed"] is True
    assert payload["saved"] is False
    assert payload["source"] in {"model", "model_repaired"}


@pytest.mark.asyncio
async def test_endpoint_preserves_original_when_model_lists_tools(monkeypatch) -> None:
    import src.api.routes.agents as agents

    bad = json.dumps(
        {
            "schema": "zent.agent_purpose/v2",
            "intent_summary": "Atender consultas",
            "purpose": (
                "Atender las consultas del usuario utilizando las herramientas "
                "disponibles y llamando a la API del ERP."
            ),
            "additional_instructions": "",
            "persona": {"role": "", "audience": "technical", "voice": ""},
            "behavioral_objectives": [],
            "knowledge_boundaries": [],
            "warnings": [],
        },
        ensure_ascii=False,
    )
    _patch_route(monkeypatch, bad)
    payload = await agents.generate_agent_purpose(
        str(uuid4()),
        agents.GeneratePurposeRequest(purpose=NARRATOR, name="Principito"),
        None,  # type: ignore[arg-type]
    )
    assert payload["draft"] == NARRATOR
    assert payload["source"] == "rules"
    assert "quality_failed_preserved_original" in payload["warnings"]


@pytest.mark.asyncio
async def test_endpoint_provider_failure_returns_preserved_input(monkeypatch) -> None:
    import src.api.routes.agents as agents

    _patch_route(monkeypatch, RuntimeError("gateway down"))
    payload = await agents.generate_agent_purpose(
        str(uuid4()),
        agents.GeneratePurposeRequest(purpose=NARRATOR, name="Principito"),
        None,  # type: ignore[arg-type]
    )
    assert payload["draft"] == NARRATOR
    assert payload["source"] == "rules"
    assert any("generation_unavailable" in warning for warning in payload["warnings"])
