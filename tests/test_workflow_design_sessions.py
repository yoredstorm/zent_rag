# =============================================================================
# Prompt 07 — Persistent Workflow Design Sessions.
# =============================================================================
from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from httpx import AsyncClient

from src.api.deps import get_llm_provider
from src.api.main import app
from src.platform.workflows.design_sessions import (
    DesignSessionConflict,
    append_design_message,
    close_design_session,
    create_design_session,
    get_design_session,
    reopen_design_session,
    restore_design_revision,
    save_design_result,
)
from tests.test_workflow_planner_agentic import _SPEC
from tests.test_workflows import _create_org, _headers, _owner_session

_PLAN = {
    "schema_version": "2.0",
    "goal": "Avisar al equipo",
    "steps": [
        {"id": "t", "type": "trigger_manual", "goal": "Inicio"},
        {
            "id": "n",
            "type": "notify",
            "goal": "Avisar",
            "depends_on": ["t"],
            "params": {"channel": "in_app", "title": "Aviso", "message": "Listo"},
        },
    ],
}


def _result(plan: dict | None = None) -> dict:
    return {
        "state": "DRAFT_READY",
        "plan": plan or _PLAN,
        "graph": {"workflow_version": 2, "nodes": [], "edges": [], "entrypoints": []},
        "plan_hash": "a" * 64,
        "issues": [],
        "requirements": [],
        "clarifications": [],
        "readiness": {"ready": True, "passed": 1, "warnings": 0, "errors": 0, "total": 1},
        "assumptions": [],
        "questions": [],
        "preview": [],
        "matches": [],
        "capability_snapshot": {"snapshot_hash": "c" * 64},
        "trace": [],
        "publishable": True,
    }


class _Provider:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = payloads
        self.calls = 0

    async def generate(self, prompt, **kwargs):  # noqa: ANN001, ANN003
        index = min(self.calls, len(self.payloads) - 1)
        self.calls += 1
        return SimpleNamespace(content=json.dumps(self.payloads[index]))


@pytest.mark.asyncio
async def test_design_session_persists_messages_plan_and_concurrency(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Design Session Service")
    org_id = UUID(org["organization_id"])
    created = await create_design_session(
        org_id,
        user_id=None,
        prompt="Quiero avisar al equipo",
        title="Aviso",
    )
    session_id = UUID(created["id"])
    assert created["revision"] == 0
    saved = await save_design_result(
        org_id,
        session_id,
        _result(),
        expected_revision=0,
        kind="initial",
        instruction="Quiero avisar al equipo",
        diff={"summary": "initial"},
    )
    assert saved["revision"] == 1
    assert saved["plan"]["goal"] == "Avisar al equipo"
    await append_design_message(
        org_id, session_id, role="assistant", content="Listo", revision=1
    )
    loaded = await get_design_session(org_id, session_id, include_revisions=True)
    assert loaded is not None
    assert len(loaded["messages"]) >= 2
    assert loaded["revisions"][0]["revision"] == 1
    with pytest.raises(DesignSessionConflict):
        await save_design_result(
            org_id,
            session_id,
            _result(),
            expected_revision=0,
            kind="patch",
        )


@pytest.mark.asyncio
async def test_design_session_restore_close_and_reopen(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Design Session Restore")
    org_id = UUID(org["organization_id"])
    created = await create_design_session(org_id, prompt="Crear aviso")
    session_id = UUID(created["id"])
    await save_design_result(
        org_id, session_id, _result(), expected_revision=0, kind="initial"
    )
    second_plan = {
        **_PLAN,
        "goal": "Aviso modificado",
    }
    second = await save_design_result(
        org_id,
        session_id,
        _result(second_plan),
        expected_revision=1,
        kind="patch",
        diff={"summary": "modificar aviso"},
    )
    assert second["revision"] == 2
    restored = await restore_design_revision(
        org_id,
        session_id,
        1,
        expected_revision=second["revision"],
        instruction="Deshacer",
    )
    assert restored["revision"] == 3
    assert restored["plan"]["goal"] == "Avisar al equipo"
    closed = await close_design_session(
        org_id, session_id, expected_revision=restored["revision"]
    )
    assert closed["status"] == "closed"
    reopened = await reopen_design_session(
        org_id, session_id, expected_revision=closed["revision"]
    )
    assert reopened["status"] == "active"


@pytest.mark.asyncio
async def test_design_session_simulation_and_draft_are_separate(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Design Session Draft")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    provider = _Provider(
        [
            _SPEC,
            {"action": "plan", "plan": _PLAN, "matches": []},
        ]
    )
    app.dependency_overrides[get_llm_provider] = lambda: provider
    try:
        created = await async_client.post(
            "/api/v1/workflows/architect/sessions",
            headers=_headers(org),
            json={"prompt": "Quiero avisar al equipo"},
        )
        assert created.status_code == 200, created.text
        design = created.json()["design_session"]
        simulated = await async_client.post(
            f"/api/v1/workflows/architect/sessions/{design['id']}/simulate",
            headers=_headers(org),
            json={
                "scenarios": [{"scenario_id": "ok", "initial_inputs": {}}],
                "expected_revision": design["revision"],
            },
        )
        assert simulated.status_code == 200, simulated.text
        simulation_body = simulated.json()
        assert simulation_body["certification"]["scenarios"][0]["result"] == "PASSED"
        assert simulation_body["design_session"]["revision"] == design["revision"] + 1

        draft = await async_client.post(
            f"/api/v1/workflows/architect/sessions/{design['id']}/draft",
            headers=_headers(org),
            json={
                "expected_revision": simulation_body["design_session"]["revision"],
                "name": "Aviso desde sesión",
                "description": "Diseño conversacional",
                "config_level": "simple",
            },
        )
        assert draft.status_code == 200, draft.text
        body = draft.json()
        assert body["workflow"]["workflow_id"]
        assert body["design_session"]["workflow_id"] == body["workflow"]["workflow_id"]
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)


@pytest.mark.asyncio
async def test_design_session_patch_preview_does_not_apply_until_confirmed(
    async_client: AsyncClient,
) -> None:
    org = await _create_org(async_client, "Design Patch Preview")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    provider = _Provider(
        [
            _SPEC,
            {"action": "plan", "plan": _PLAN, "matches": []},
            {
                "operations": [
                    {
                        "kind": "set_param",
                        "step_id": "n",
                        "key": "title",
                        "value": "Título confirmado",
                    }
                ],
                "summary": "Cambiar título",
            },
        ]
    )
    app.dependency_overrides[get_llm_provider] = lambda: provider
    try:
        created = await async_client.post(
            "/api/v1/workflows/architect/sessions",
            headers=_headers(org),
            json={"prompt": "Quiero avisar al equipo"},
        )
        assert created.status_code == 200, created.text
        design = created.json()["design_session"]

        preview = await async_client.post(
            f"/api/v1/workflows/architect/sessions/{design['id']}/patch-preview",
            headers=_headers(org),
            json={"message": "Cambia el título", "expected_revision": design["revision"]},
        )
        assert preview.status_code == 200, preview.text
        preview_body = preview.json()
        assert preview_body["confirmation_required"] is True
        assert preview_body["diff"]["modified"][0]["step_id"] == "n"
        unchanged = await async_client.get(
            f"/api/v1/workflows/architect/sessions/{design['id']}", headers=_headers(org)
        )
        assert unchanged.json()["revision"] == design["revision"]
        assert unchanged.json()["plan"]["steps"][1]["params"]["title"] == "Aviso"

        applied = await async_client.post(
            f"/api/v1/workflows/architect/sessions/{design['id']}/patch-apply",
            headers=_headers(org),
            json={
                "message": "Cambia el título",
                "expected_revision": design["revision"],
                "patch": preview_body["patch"],
            },
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["design_session"]["revision"] == design["revision"] + 1
        assert (
            applied.json()["design_session"]["plan"]["steps"][1]["params"]["title"]
            == "Título confirmado"
        )

        stale = await async_client.post(
            f"/api/v1/workflows/architect/sessions/{design['id']}/patch-apply",
            headers=_headers(org),
            json={
                "message": "Otra vez",
                "expected_revision": design["revision"],
                "patch": preview_body["patch"],
            },
        )
        assert stale.status_code == 409
        assert stale.json()["current_revision"] == design["revision"] + 1
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)


@pytest.mark.asyncio
async def test_design_session_api_restore_close_reopen_and_list(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Design Session Lifecycle")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    provider = _Provider([_SPEC, {"action": "plan", "plan": _PLAN, "matches": []}])
    app.dependency_overrides[get_llm_provider] = lambda: provider
    try:
        created = await async_client.post(
            "/api/v1/workflows/architect/sessions",
            headers=_headers(org),
            json={"prompt": "Quiero avisar al equipo"},
        )
        assert created.status_code == 200, created.text
        design = created.json()["design_session"]

        listed = await async_client.get(
            "/api/v1/workflows/architect/sessions", headers=_headers(org)
        )
        assert listed.status_code == 200, listed.text
        assert any(item["id"] == design["id"] for item in listed.json()["sessions"])

        restored = await async_client.post(
            f"/api/v1/workflows/architect/sessions/{design['id']}/restore",
            headers=_headers(org),
            json={"revision": 1, "expected_revision": design["revision"]},
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["revision"] == design["revision"] + 1
        assert restored.json()["plan"]["goal"] == "Avisar al equipo"

        closed = await async_client.post(
            f"/api/v1/workflows/architect/sessions/{design['id']}/close",
            headers=_headers(org),
            json={"expected_revision": restored.json()["revision"]},
        )
        assert closed.status_code == 200, closed.text
        assert closed.json()["status"] == "closed"

        reopened = await async_client.post(
            f"/api/v1/workflows/architect/sessions/{design['id']}/reopen",
            headers=_headers(org),
            json={"expected_revision": closed.json()["revision"]},
        )
        assert reopened.status_code == 200, reopened.text
        assert reopened.json()["status"] == "active"
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)


@pytest.mark.asyncio
async def test_design_session_api_conversation_and_conflict(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Design Session API")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    provider = _Provider(
        [
            _SPEC,
            {
                "action": "plan",
                "plan": _PLAN,
                "matches": [],
            },
            {
                "operations": [
                    {
                        "kind": "set_param",
                        "step_id": "n",
                        "key": "title",
                        "value": "Nuevo aviso",
                        "reason": "pedido del usuario",
                    }
                ],
                "summary": "Cambiar título",
            },
        ]
    )
    app.dependency_overrides[get_llm_provider] = lambda: provider
    try:
        created = await async_client.post(
            "/api/v1/workflows/architect/sessions",
            headers=_headers(org),
            json={"prompt": "Quiero avisar al equipo cuando pase algo"},
        )
        assert created.status_code == 200, created.text
        payload = created.json()
        design = payload["design_session"]
        assert design["revision"] == 1
        assert design["plan"]["goal"] == "Avisar al equipo"
        assert len(design["messages"]) >= 2

        changed = await async_client.post(
            f"/api/v1/workflows/architect/sessions/{design['id']}/messages",
            headers=_headers(org),
            json={"message": "Cambia el título a Nuevo aviso", "expected_revision": 1},
        )
        assert changed.status_code == 200, changed.text
        changed_body = changed.json()
        assert changed_body["design_session"]["revision"] == 2
        assert changed_body["design_session"]["plan"]["steps"][1]["params"]["title"] == "Nuevo aviso"
        assert len(changed_body["design_session"]["messages"]) >= 4

        stale = await async_client.post(
            f"/api/v1/workflows/architect/sessions/{design['id']}/messages",
            headers=_headers(org),
            json={"message": "Cambia otra vez", "expected_revision": 1},
        )
        assert stale.status_code == 409
        assert stale.json()["error_code"] == "DESIGN_SESSION_CONFLICT"
        assert stale.json()["current_revision"] == 2
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)
