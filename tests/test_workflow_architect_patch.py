# =============================================================================
# Workflow Architect — Fase 7: patching conversacional del plan.
# =============================================================================
from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.platform.workflows.architect import (
    heuristic_plan_patch,
    patch_workflow_plan,
)
from src.platform.workflows.architect_metrics import reset_metrics, snapshot
from src.platform.workflows.architect_models import SemanticPlan
from src.platform.workflows.architect_patch import apply_semantic_patch
from tests.test_workflow_architect import _SALE_PLAN, _caps, _setup_capabilities
from tests.test_workflows import _create_org, _headers, _owner_session

_FULL_PERMS = frozenset({"agents:execute", "external_actions:execute", "workflows:create"})


def _sale_plan() -> SemanticPlan:
    return SemanticPlan.model_validate(_SALE_PLAN)


def _step(plan: SemanticPlan, step_id: str):
    return next(step for step in plan.steps if step.id == step_id)


def test_heuristic_patch_sets_threshold() -> None:
    plan = _sale_plan()
    patch = heuristic_plan_patch("cambia el umbral a 50000", plan)
    assert patch is not None
    updated, notes = apply_semantic_patch(plan, patch)
    assert _step(updated, "d").params.get("value") == 50000
    assert notes == []


def test_heuristic_patch_removes_approval_and_rewires() -> None:
    plan = _sale_plan()
    patch = heuristic_plan_patch("quita la aprobación", plan)
    assert patch is not None
    updated, notes = apply_semantic_patch(plan, patch)
    types = {step.type for step in updated.steps}
    assert "human_approval" not in types
    notify = _step(updated, "n")
    assert notify.depends_on == ["d"]
    assert notify.when is None
    assert any("Quité" in note for note in notes)


def test_heuristic_patch_weekdays_schedule() -> None:
    plan = SemanticPlan.model_validate(
        {
            "goal": "Resumen",
            "steps": [
                {
                    "id": "t",
                    "type": "trigger_schedule",
                    "goal": "Cada día",
                    "params": {"daily": {"time": "08:00", "timezone": "America/Lima"}},
                },
                {"id": "n", "type": "notify", "goal": "Avisar", "depends_on": ["t"], "params": {"channel": "in_app"}},
            ],
        }
    )
    patch = heuristic_plan_patch("solo lunes a viernes", plan)
    assert patch is not None
    updated, _ = apply_semantic_patch(plan, patch)
    weekly = _step(updated, "t").params.get("weekly")
    assert weekly and weekly.get("days") == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_llm_patch_replaces_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_metrics()
    before = snapshot()["counters"]["workflow_architect_revision_total"]
    caps = _caps(agents=[{"id": "ag2", "name": "Agente Financiero", "purpose": "analiza finanzas"}])

    class _Provider:
        async def generate(self, prompt, **kwargs):  # noqa: ANN001, ANN003
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "operations": [
                            {"kind": "replace_agent", "step_id": "a", "value": "ag2"}
                        ],
                        "summary": "Usar agente financiero",
                    }
                ),
                model="fake",
            )

    result = await patch_workflow_plan(
        uuid4(),
        _SALE_PLAN,
        "usa el agente financiero",
        capabilities=caps,
        provider=_Provider(),
        permissions=_FULL_PERMS,
    )
    assert result["source"] == "llm"
    plan = SemanticPlan.model_validate(result["plan"])
    assert _step(plan, "a").params.get("agent_id") == "ag2"
    assert result["graph"] is not None
    after = snapshot()["counters"]["workflow_architect_revision_total"]
    assert after == before + 1


@pytest.mark.asyncio
async def test_heuristic_patch_pipeline_compiles() -> None:
    caps = _caps(agents=[{"id": "a1", "name": "Analista", "purpose": "analiza ventas"}])
    result = await patch_workflow_plan(
        uuid4(),
        _SALE_PLAN,
        "cambia el umbral a 50000",
        capabilities=caps,
        provider=object(),  # sin generate → fallback determinístico
        permissions=_FULL_PERMS,
    )
    assert result["source"] == "heuristics"
    assert result["graph"] is not None
    assert not [issue for issue in result["issues"] if issue["severity"] == "error"]
    plan = SemanticPlan.model_validate(result["plan"])
    assert _step(plan, "d").params.get("value") == 50000


@pytest.mark.asyncio
async def test_architect_patch_endpoint(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Architect Patch")
    await _setup_capabilities(async_client, org)
    reset_metrics()
    before = snapshot()["counters"]["workflow_architect_revision_total"]

    from src.api.deps import get_llm_provider
    from src.api.main import app

    class _Boom:
        async def generate(self, prompt, **kwargs):  # noqa: ANN001, ANN003
            raise RuntimeError("llm caído")

    app.dependency_overrides[get_llm_provider] = lambda: _Boom()
    try:
        resp = await async_client.post(
            "/api/v1/workflows/architect/patch",
            headers={**_headers(org), "Idempotency-Key": f"arp-{uuid4().hex}"},
            json={"plan": _SALE_PLAN, "instruction": "quita la aprobación"},
        )
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "heuristics"
    assert body["graph"] is not None
    types = {node["type"] for node in body["graph"]["nodes"]}
    assert "human_approval" not in types
    after = snapshot()["counters"]["workflow_architect_revision_total"]
    assert after == before + 1


@pytest.mark.asyncio
async def test_unrecognized_patch_is_400(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Architect Patch Bad")
    org["session"] = await _owner_session(async_client, org["organization_id"])

    from src.api.deps import get_llm_provider
    from src.api.main import app

    class _Boom:
        async def generate(self, prompt, **kwargs):  # noqa: ANN001, ANN003
            raise RuntimeError("llm caído")

    app.dependency_overrides[get_llm_provider] = lambda: _Boom()
    try:
        resp = await async_client.post(
            "/api/v1/workflows/architect/patch",
            headers={**_headers(org), "Idempotency-Key": f"arb-{uuid4().hex}"},
            json={"plan": _SALE_PLAN, "instruction": "hazlo mágico"},
        )
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)
    assert resp.status_code == 400
