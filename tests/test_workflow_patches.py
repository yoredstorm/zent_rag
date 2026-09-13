# =============================================================================
# Natural-language patches (commit 6) — validación, diff y aplicación sobre el
# grafo real sin regenerar el workflow completo.
# =============================================================================
from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.platform.workflows.intent import SemanticWorkflowPatch
from src.platform.workflows.patches import apply_patch, graph_fingerprint
from tests.test_workflow_graph import _edge, _graph, _node
from tests.test_workflows import _create_org, _headers, _owner_session


class FakeLLM:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    async def generate(self, **_: object) -> SimpleNamespace:
        return SimpleNamespace(content=json.dumps(self.payload))


def _graph_dict() -> dict:
    return _graph(
        nodes=[
            _node("t", "trigger_webhook"),
            _node(
                "notify",
                "notify",
                {
                    "channel": "in_app",
                    "title": "Stock bajo",
                    "message": "Hay stock bajo",
                    "recipients": [{"kind": "team", "value": "compras", "label": "Compras"}],
                },
            ),
            _node("sched", "trigger_schedule", {"schedule": {"mode": "daily", "time": "08:00", "timezone": "America/Lima"}}),
        ],
        edges=[_edge("e1", "t", "notify")],
        entrypoints=["t"],
    )


def _patch(**operation: object) -> SemanticWorkflowPatch:
    return SemanticWorkflowPatch.model_validate(
        {"summary": "cambio", "operations": [operation], "confidence": 0.9}
    )


# ---------------------------------------------------------------------------
# Aplicación unitaria
# ---------------------------------------------------------------------------
def test_set_value_changes_only_the_target_and_keeps_original() -> None:
    graph = _graph_dict()
    patch = _patch(op="set_value", target="notify", value={"path": "config.title", "value": "Stock crítico"})
    result = apply_patch(graph, patch)
    assert result["issues"] == []
    updated = result["graph"]
    notify = next(n for n in updated["nodes"] if n["id"] == "notify")
    assert notify["config"]["title"] == "Stock crítico"
    assert result["diff"][0]["before"] == "Stock bajo"
    # el grafo original no se muta
    original = next(n for n in graph["nodes"] if n["id"] == "notify")
    assert original["config"]["title"] == "Stock bajo"


def test_change_channel_maps_zent_to_in_app() -> None:
    patch = _patch(op="change_channel", target="notify", value="zent")
    result = apply_patch(_graph_dict(), patch)
    notify = next(n for n in result["graph"]["nodes"] if n["id"] == "notify")
    assert notify["config"]["channel"] == "in_app"


def test_add_and_remove_recipient() -> None:
    add = _patch(
        op="add_recipient",
        target="notify",
        value={"kind": "email", "value": "gerencia@zent.pe", "label": "Gerencia"},
    )
    added = apply_patch(_graph_dict(), add)
    notify = next(n for n in added["graph"]["nodes"] if n["id"] == "notify")
    assert len(notify["config"]["recipients"]) == 2

    remove = _patch(op="remove_recipient", target="notify", value="Compras")
    removed = apply_patch(added["graph"], remove)
    notify = next(n for n in removed["graph"]["nodes"] if n["id"] == "notify")
    assert [r["value"] for r in notify["config"]["recipients"]] == ["gerencia@zent.pe"]


def test_change_schedule_and_rename() -> None:
    schedule = _patch(
        op="change_schedule",
        target="sched",
        value={"mode": "weekly", "days": [0, 1, 2, 3, 4], "time": "08:00", "timezone": "America/Lima"},
    )
    result = apply_patch(_graph_dict(), schedule)
    node = next(n for n in result["graph"]["nodes"] if n["id"] == "sched")
    assert node["config"]["schedule"]["mode"] == "weekly"

    rename = _patch(op="rename", target="workflow", value="Reporte semanal")
    renamed = apply_patch(result["graph"], rename)
    assert renamed["graph"]["metadata"]["display_name"] == "Reporte semanal"


def test_unknown_node_is_blocked_without_changes() -> None:
    patch = _patch(op="change_channel", target="nope", value="email")
    result = apply_patch(_graph_dict(), patch)
    assert any(i["code"] == "patch.node_missing" for i in result["issues"])
    assert result["diff"] == []


def test_condition_edit_requires_technical_review() -> None:
    patch = _patch(
        op="set_value",
        target="notify",
        value={"path": "config.rules.children.0.value", "value": 5},
    )
    result = apply_patch(_graph_dict(), patch)
    assert any(i["code"] == "patch.condition_use_op" for i in result["issues"])


def test_graph_fingerprint_stable() -> None:
    assert graph_fingerprint(_graph_dict()) == graph_fingerprint(_graph_dict())
    changed = _graph_dict()
    changed["nodes"][0]["label"] = "Otro"
    assert graph_fingerprint(changed) != graph_fingerprint(_graph_dict())


# ---------------------------------------------------------------------------
# API: preview → apply → conflicto por versión vieja
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_patch_api_preview_and_apply(async_client: AsyncClient) -> None:
    from src.api.deps import get_llm_provider
    from src.api.main import app

    org = await _create_org(async_client, "Patch API")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    created = await async_client.post(
        "/api/v1/workflows",
        headers=h,
        json={"name": "Patch WF", "trigger_type": "webhook", "graph": _graph_dict(), "workflow_version": 2},
    )
    assert created.status_code == 200, created.text
    wid = created.json()["workflow_id"]

    payload = {
        "summary": "Cambiar el asunto",
        "operations": [
            {
                "op": "set_field",
                "target": "nodes.notify.config.title",
                "value": "Stock crítico",
            }
        ],
        "confidence": 0.9,
    }
    app.dependency_overrides[get_llm_provider] = lambda: FakeLLM(payload)
    try:
        preview = await async_client.post(
            f"/api/v1/workflows/{wid}/patch/preview",
            headers=h,
            json={"prompt": "Cambia el asunto a Stock crítico"},
        )
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert body["diff"], body
        assert body["diff"][0]["after"] == "Stock crítico"
        assert body["base_graph_hash"]
        # Preview no persiste.
        detail = await async_client.get(f"/api/v1/workflows/{wid}", headers=h)
        notify = next(n for n in detail.json()["graph"]["nodes"] if n["id"] == "notify")
        assert notify["config"]["title"] == "Stock bajo"

        applied = await async_client.post(
            f"/api/v1/workflows/{wid}/patch/apply",
            headers=h,
            json={"patch": body["patch"], "base_graph_hash": body["base_graph_hash"]},
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["status"] == "applied"

        detail = await async_client.get(f"/api/v1/workflows/{wid}", headers=h)
        notify = next(n for n in detail.json()["graph"]["nodes"] if n["id"] == "notify")
        assert notify["config"]["title"] == "Stock crítico"

        # Aplicar otra vez con el hash viejo → conflicto.
        stale = await async_client.post(
            f"/api/v1/workflows/{wid}/patch/apply",
            headers=h,
            json={
                "patch": {**body["patch"], "summary": "Reintento con diff viejo"},
                "base_graph_hash": body["base_graph_hash"],
            },
        )
        assert stale.status_code == 409, stale.text
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)


@pytest.mark.asyncio
async def test_patch_preview_unknown_workflow(async_client: AsyncClient) -> None:
    from src.api.deps import get_llm_provider
    from src.api.main import app

    org = await _create_org(async_client, "Patch 404")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    app.dependency_overrides[get_llm_provider] = lambda: FakeLLM({"summary": "x", "operations": []})
    try:
        resp = await async_client.post(
            f"/api/v1/workflows/{uuid4()}/patch/preview",
            headers=_headers(org),
            json={"prompt": "cambia algo"},
        )
        # El endpoint valida el body del LLM después de cargar el workflow: 404.
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)
