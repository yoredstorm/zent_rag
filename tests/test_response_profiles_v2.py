# =============================================================================
# P14 — Response Behavior Engine V2
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from src.intelligence.response.contract import (
    compose_contract,
    contract_from_public,
    prompt_block,
)
from src.intelligence.response.profile import (
    RESPONSE_PROFILE_PRESETS,
    profile_from_config,
    profile_hash,
)
from src.intelligence.response.wiring import compose_for_request


def _preset(name: str):
    return profile_from_config({"response_profile": {"preset": name}})


def test_all_presets_have_distinct_operational_strategies() -> None:
    profiles = {name: _preset(name) for name in RESPONSE_PROFILE_PRESETS}
    assert len(profiles) == 8
    assert len({item.communication_strategy for item in profiles.values()}) == 8
    assert profiles["precise"].example_policy == "never"
    assert profiles["clear_didactic"].example_policy == "minimal_supported"
    assert profiles["executive"].structure_policy == "decision_impact_next_action"
    assert profiles["concise"].structure_policy == "answer_only"
    assert profiles["analytical"].analysis_depth == "hypothesis_and_tradeoffs"
    assert profiles["evidence_first"].source_presentation_policy == "inline_required"
    # Una cita obligatoria no se apaga por elegir un perfil breve.
    assert profiles["concise"].cite_sources is True
    assert profiles["executive"].cite_sources is True


def test_profile_from_full_config_and_subdict_are_equivalent() -> None:
    full = {"response_profile": {"preset": "technical_detailed"}}
    assert profile_from_config(full) == profile_from_config(full["response_profile"])
    # Un config de agente sin perfil no se confunde con un perfil parcial por
    # tener el campo legacy `tone`.
    assert profile_from_config({"tone": "friendly", "temperature": 0.2}) == profile_from_config(
        None
    )


def test_contract_carries_strategy_hash_and_roundtrips() -> None:
    profile = _preset("analytical")
    contract = compose_contract(
        question="Compara estas dos alternativas y dime cuál conviene.",
        profile=profile,
    )
    assert contract.profile_id == "analytical"
    assert contract.profile_version == 2
    assert contract.communication_strategy == "decompose_compare"
    assert contract.effective_profile_hash == profile_hash(profile)
    assert contract.override_origin == "agent_config"
    restored = contract_from_public(contract.to_public_dict())
    assert restored == contract
    text = prompt_block(contract)
    assert "estrategia de comunicación: decompose_compare" in text
    assert "política de estructura: problem_alternatives_criteria_conclusion" in text


def test_turn_override_is_audited_without_changing_saved_profile() -> None:
    saved = _preset("analytical")
    contract = compose_contract(
        question="respóndeme corto: ¿qué significa el campo X con valor 2?",
        profile=saved,
    )
    assert contract.detail == "brief"
    assert contract.override_origin == "turn_override"
    assert "default_detail" in contract.turn_overrides
    assert saved.default_detail == "deep"


@pytest.mark.asyncio
async def test_response_plan_exposes_applied_profile() -> None:
    plan = await compose_for_request(
        question="¿Qué significa el campo X cuando vale 2?",
        profile=_preset("precise"),
        mode="rules",
    )
    public = plan.to_public_dict()
    assert public["profile"]["profile_id"] == "precise"
    assert public["contract"]["profile_id"] == "precise"
    assert public["contract"]["communication_strategy"] == "definition_scope"
    assert plan.contract is not None
    assert plan.contract.effective_profile_hash


# ---------------------------------------------------------------------------
# API: preview temporal, persistencia explícita y comparador A/B
# ---------------------------------------------------------------------------


async def _create_org(client: AsyncClient, name: str) -> dict:
    response = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"p14-{uuid4().hex[:8]}@example.com",
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


async def _create_agent(client: AsyncClient) -> tuple[dict, str, dict]:
    org = await _create_org(client, "P14 Response Profiles")
    org["session"] = await _owner_session(org["organization_id"])
    headers = {
        "Authorization": f"Bearer {org['session']}",
        "X-Organization-Id": org["organization_id"],
    }
    created = await client.post(
        "/api/v1/agents",
        json={
            "name": f"p14-{uuid4().hex[:8]}",
            "tools": [],
            "config": {
                "response_profile": {
                    "preset": "balanced",
                    "custom_instructions": "Estilo guardado.",
                }
            },
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["config"]["response_profile"] is not None, created.text
    return org, created.json()["id"], headers


@pytest.mark.asyncio
async def test_preview_uses_temporary_profile_without_persisting(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_generate(
        prompt: str, *, max_tokens: int = 400, temperature: float = 0.2
    ) -> str:
        return f"respuesta simulada ({max_tokens})"

    monkeypatch.setattr("src.api.routes.agents._generate_text", fake_generate)
    _, agent_id, headers = await _create_agent(async_client)

    preview = await async_client.post(
        f"/api/v1/agents/{agent_id}/config/preview",
        json={
            "question": "¿Qué exige esta condición contractual?",
            "profile": {"preset": "precise"},
        },
        headers=headers,
    )
    assert preview.status_code == 200, preview.text
    data = preview.json()
    assert data["profile_source"] == "temporary"
    assert data["profile"]["profile_id"] == "precise"
    assert data["response_contract"]["communication_strategy"] == "definition_scope"
    assert data["simulated_evidence"] is True
    assert data["tools_executed"] is False

    saved = await async_client.get(f"/api/v1/agents/{agent_id}", headers=headers)
    assert saved.json()["config"]["response_profile"]["profile_id"] == "balanced"


@pytest.mark.asyncio
async def test_profile_only_save_replaces_previous_fields(
    async_client: AsyncClient,
) -> None:
    _, agent_id, headers = await _create_agent(async_client)
    saved = await async_client.put(
        f"/api/v1/agents/{agent_id}/config/response-profile",
        json={"profile": {"preset": "concise"}},
        headers=headers,
    )
    assert saved.status_code == 200, saved.text
    profile = saved.json()["config"]["response_profile"]
    assert profile["profile_id"] == "concise"
    assert profile["use_examples"] is False
    assert profile["use_tables"] is False
    assert profile["communication_strategy"] == "answer_only"

    reloaded = await async_client.get(f"/api/v1/agents/{agent_id}", headers=headers)
    assert reloaded.json()["config"]["response_profile"]["profile_id"] == "concise"


@pytest.mark.asyncio
async def test_compare_profiles_uses_same_evidence_and_no_tools(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_generate(
        prompt: str, *, max_tokens: int = 400, temperature: float = 0.2
    ) -> str:
        return "misma evidencia simulada"

    monkeypatch.setattr("src.api.routes.agents._generate_text", fake_generate)
    _, agent_id, headers = await _create_agent(async_client)

    compared = await async_client.post(
        f"/api/v1/agents/{agent_id}/config/compare",
        json={
            "question": "¿Conviene migrar ahora o esperar?",
            "profile_ids": ["analytical", "executive", "concise"],
        },
        headers=headers,
    )
    assert compared.status_code == 200, compared.text
    data = compared.json()
    assert data["simulated_evidence"] is True
    assert data["tools_executed"] is False
    assert data["same_evidence"] is True
    assert len(data["results"]) == 3
    by_id = {item["profile_id"]: item for item in data["results"]}
    assert by_id["analytical"]["response_contract"]["communication_strategy"] == "decompose_compare"
    assert by_id["executive"]["response_contract"]["structure_policy"] == "decision_impact_next_action"
    assert by_id["concise"]["response_contract"]["detail"] == "brief"
    assert all(item["error"] == "" for item in data["results"])

    bad = await async_client.post(
        f"/api/v1/agents/{agent_id}/config/compare",
        json={"question": "¿Qué hago?", "profile_ids": ["analytical", "inventado"]},
        headers=headers,
    )
    assert bad.status_code == 400
