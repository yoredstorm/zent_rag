# =============================================================================
# P15 — intent fidelity, persona consistency and response quality
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from src.intelligence.response.contract import compose_contract, prompt_block
from src.intelligence.response.identity import (
    identity_from_agent_config,
    identity_prompt_block,
)
from src.intelligence.response.intent import detect_user_intent
from src.intelligence.response.profile import RESPONSE_PROFILE_PRESETS
from src.intelligence.response.quality import evaluate_response_quality
from src.intelligence.response.selector import select_blueprint
from src.intelligence.response.wiring import compose_for_request
from src.rag.adaptive.claims import deterministic_judgment
from src.runtime.turn_intent import rules_turn_intent

FROZEN_QUESTION = "¿Qué te parece El principito?"
NARRATOR = "Responde como un narrador de cuentos infantil"


def test_user_intent_is_generic_and_multitopic() -> None:
    cases = {
        "¿Qué te parece El principito?": "valuation",
        "¿Qué opinas de este diseño?": "valuation",
        "¿Cuál es tu interpretación del final?": "interpretation",
        "¿Recomendarías este producto?": "recommendation",
        "¿Cuál conviene para una pyme?": "recommendation",
        "¿Qué diferencia hay entre estos contratos?": "comparison",
        "Escríbeme un cuento sobre un faro": "creation",
        "Explícame esto desde cero": "teaching",
    }
    for question, expected in cases.items():
        assert detect_user_intent(question).kind == expected, question


def test_turn_intent_marks_valuation_as_evaluative_with_evidence() -> None:
    decision = rules_turn_intent(FROZEN_QUESTION)
    assert decision is not None
    assert decision.intent == "valuation"
    assert decision.evaluative is True
    assert decision.needs_external_evidence is True
    assert decision.route == "knowledge"


def test_blueprint_for_evaluation_is_not_technical_explanation() -> None:
    selection = select_blueprint(question=FROZEN_QUESTION)
    assert selection.blueprint == "interpretive_valuation"


def test_identity_is_extracted_from_natural_language_purpose() -> None:
    identity = identity_from_agent_config({"purpose": NARRATOR})
    assert identity.active is True
    assert "narrador" in identity.label.lower() or "narrador" in identity.voice.lower()
    block = identity_prompt_block(identity)
    assert "AGENT IDENTITY" in block
    assert "no rechaces" in block.lower()
    assert "no una restricción de conocimiento" in block


def test_every_profile_preserves_identity_and_evaluation() -> None:
    identity = identity_from_agent_config({"purpose": NARRATOR})
    for name, profile in RESPONSE_PROFILE_PRESETS.items():
        contract = compose_contract(
            question=FROZEN_QUESTION,
            profile=profile,
            identity=identity,
        )
        assert contract.identity_preserved is True, name
        assert contract.identity_id == "agent-identity"
        assert contract.identity_voice
        assert contract.evidence["evaluative"] is True
        assert contract.request_intent == "valuation"
        block = prompt_block(contract, profile=profile, identity=identity)
        assert "AGENT IDENTITY" in block
        assert "valoración interpretativa" in block
        assert "RESPONSE PROFILE" in block


def test_narrative_identity_restores_minimal_examples_when_profile_forbids_them() -> None:
    identity = identity_from_agent_config({"purpose": NARRATOR})
    contract = compose_contract(
        question=FROZEN_QUESTION,
        profile=RESPONSE_PROFILE_PRESETS["precise"],
        identity=identity,
    )
    assert "profile_disables_examples" in contract.identity_conflicts
    assert contract.example_policy == "minimal_supported"


@pytest.mark.asyncio
async def test_plan_exposes_intent_and_identity() -> None:
    identity = identity_from_agent_config({"purpose": NARRATOR})
    plan = await compose_for_request(
        question=FROZEN_QUESTION,
        profile=RESPONSE_PROFILE_PRESETS["concise"],
        identity=identity,
        mode="rules",
    )
    public = plan.to_public_dict()
    assert public["user_intent"]["kind"] == "valuation"
    assert public["evaluative"] is True
    assert public["identity"]["label"]
    assert public["contract"]["request_intent"] == "valuation"
    assert public["contract"]["identity_preserved"] is True


def test_claims_distinguish_interpretation_from_unsupported_fact() -> None:
    interpretive = deterministic_judgment(
        "Me parece una obra valiosa porque el narrador construye un vínculo con el lector.",
        [],
    )
    assert interpretive.factual is False
    assert interpretive.claim_type == "interpretive"
    assert interpretive.verdict == "not_verifiable"

    factual = deterministic_judgment("El libro fue publicado en 1943.", [])
    assert factual.factual is True
    assert factual.claim_type == "unsupported"
    assert factual.verdict == "unsupported"


def test_evaluative_gate_keeps_justified_answer_but_not_without_evidence() -> None:
    from src.runtime.answer_gate import keep_evaluative_answer

    assert keep_evaluative_answer(
        evaluative=True,
        draft="Me parece una obra valiosa por su tono.",
        supporting_chunks=2,
    )
    assert keep_evaluative_answer(
        evaluative=True,
        draft="Me parece una obra valiosa por su tono.",
        evidence_available=True,
    )
    assert not keep_evaluative_answer(
        evaluative=True,
        draft="Me parece una obra valiosa por su tono.",
        supporting_chunks=0,
        evidence_available=False,
    )
    assert not keep_evaluative_answer(
        evaluative=False,
        draft="Me parece una obra valiosa.",
        evidence_available=True,
    )


def test_quality_marks_refusal_and_metadata_without_claiming_semantic_validation() -> None:
    refusal = evaluate_response_quality(
        answer="No puedo darte una opinión personal porque soy un modelo.",
        contract={"profile_id": "balanced", "detail": "normal"},
        intent={"kind": "valuation", "evaluative": True},
        identity={"identity_id": "agent-identity", "voice": "narrador"},
    )
    assert refusal.unnecessary_refusal is True
    assert refusal.status == "needs_review"
    assert refusal.semantic_evaluated is False
    assert refusal.label == "Chequeos deterministas"

    good = evaluate_response_quality(
        answer=(
            "Me parece una obra valiosa: el narrador construye un vínculo afectivo "
            "con el lector y la historia deja una enseñanza sobre la amistad. "
            "Esa lectura se apoya en el tono y en la relación entre los personajes."
        ),
        contract={
            "profile_id": "analytical",
            "detail": "normal",
            "communication_strategy": "decompose_compare",
        },
        intent={"kind": "valuation", "evaluative": True},
        identity={"identity_id": "agent-identity", "voice": "narrador"},
    )
    assert good.intent_fulfilled is True
    assert good.unnecessary_refusal is False
    assert good.semantic_evaluated is False
    assert good.label == "Chequeos deterministas"

    metadata = evaluate_response_quality(
        answer="La respuesta está bien. fragmentos=12 cobertura_entidades=0.8",
        contract={"profile_id": "balanced", "detail": "normal"},
        intent={"kind": "valuation", "evaluative": True},
    )
    assert metadata.irrelevant_internal_metadata is True
    assert metadata.status == "needs_review"


# ---------------------------------------------------------------------------
# API wiring: preview and compare carry identity/intent/quality
# ---------------------------------------------------------------------------


async def _create_org(client: AsyncClient, name: str) -> dict:
    response = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"p15-{uuid4().hex[:8]}@example.com",
            "country": "CL",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _owner_session(organization_id: str) -> str:
    from src.infrastructure.postgres.relational_db import PostgresUserRepository
    from src.platform.auth.session import encrypt_session

    user = await PostgresUserRepository().get_by_external_id(
        UUID(organization_id), "default-admin"
    )
    assert user is not None
    return encrypt_session(user.id, UUID(organization_id))


async def _create_narrator_agent(client: AsyncClient) -> tuple[str, dict]:
    org = await _create_org(client, "P15 Narrator")
    org["session"] = await _owner_session(org["organization_id"])
    headers = {
        "Authorization": f"Bearer {org['session']}",
        "X-Organization-Id": org["organization_id"],
    }
    created = await client.post(
        "/api/v1/agents",
        json={
            "name": f"p15-{uuid4().hex[:8]}",
            "tools": [],
            "config": {
                "purpose": NARRATOR,
                "response_profile": {"preset": "balanced"},
            },
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()["id"], headers


def test_agent_flow_publishes_response_quality_without_fake_validation() -> None:
    from src.agents.runtime.agent_runtime import AgentRunResult
    from src.runtime.agent_flow import build_agent_flow

    result = AgentRunResult(
        run_id=uuid4(),
        agent_id=uuid4(),
        organization_id=uuid4(),
        status="completed",
        answer="No puedo darte una opinión personal porque soy un modelo.",
        message=FROZEN_QUESTION,
        steps=[
            {"type": "conversation_intent", "detail": "valuation"},
            {"type": "final", "answer": "No puedo darte una opinión personal."},
        ],
        response_plan={
            "profile": {"profile_id": "concise"},
            "identity": {"identity_id": "agent-identity", "voice": "narrador"},
            "user_intent": {"kind": "valuation", "evaluative": True},
            "contract": {
                "blueprint": "interpretive_valuation",
                "profile_id": "concise",
                "detail": "brief",
                "request_intent": "valuation",
                "identity_id": "agent-identity",
                "identity_voice": "narrador",
                "identity_preserved": True,
                "identity_conflicts": [],
            },
        },
        total_latency_ms=10.0,
        total_tokens=10,
        cost=0.0,
        model="fake",
        provider="fake",
    )
    flow = build_agent_flow(result=result, question=FROZEN_QUESTION, agent_tools=())
    quality = flow["response_quality"]
    assert quality["semantic_evaluated"] is False
    assert quality["label"] == "Chequeos deterministas"
    assert quality["unnecessary_refusal"] is True
    assert quality["status"] == "needs_review"


@pytest.mark.asyncio
async def test_preview_carries_identity_intent_and_not_evaluated_quality(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_generate(
        prompt: str, *, max_tokens: int = 400, temperature: float = 0.2
    ) -> str:
        return (
            "Me parece una historia valiosa: el narrador acompaña al lector y "
            "la obra deja una enseñanza sobre la amistad."
        )

    monkeypatch.setattr("src.api.routes.agents._generate_text", fake_generate)
    agent_id, headers = await _create_narrator_agent(async_client)
    response = await async_client.post(
        f"/api/v1/agents/{agent_id}/config/preview",
        json={"question": FROZEN_QUESTION, "profile": {"preset": "concise"}},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["identity"]["voice"]
    assert data["intent"]["kind"] == "valuation"
    assert data["intent"]["evaluative"] is True
    assert data["response_contract"]["blueprint"] == "interpretive_valuation"
    assert data["response_contract"]["identity_preserved"] is True
    assert data["quality"]["semantic_evaluated"] is False
    assert data["quality"]["label"] in {"Chequeos deterministas", "No evaluado"}
    assert data["validation"]["semantic_evaluated"] is False
