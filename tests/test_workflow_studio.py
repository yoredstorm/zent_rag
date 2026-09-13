# =============================================================================
# Workflow Studio — rotación del secret inbound, versiones publicables,
# publicar/restaurar y edición del trigger_type.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from tests.test_workflow_graph import _edge, _graph, _node, _notify_node
from tests.test_workflows import _create_org, _headers, _owner_session

NOTIFY_STEPS = [
    {"type": "notify", "config": {"channel": "in_app", "title": "Studio", "message": "ok"}}
]


async def _org(client: AsyncClient, name: str) -> dict:
    org = await _create_org(client, name)
    org["session"] = await _owner_session(client, org["organization_id"])
    return org


async def _workflow(client: AsyncClient, org: dict, name: str = "Studio WF") -> dict:
    created = await client.post(
        "/api/v1/workflows",
        headers=_headers(org),
        json={"name": name, "trigger_type": "webhook", "steps": NOTIFY_STEPS},
    )
    assert created.status_code == 200, created.text
    return created.json()


# ---------------------------------------------------------------------------
# Secret inbound
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_rotate_hook_secret_invalidates_previous(async_client: AsyncClient) -> None:
    org = await _org(async_client, "WF Studio Rotate")
    wf = await _workflow(async_client, org)
    wid = wf["workflow_id"]
    old_secret = wf["hook_secret"]

    activate = await async_client.post(
        f"/api/v1/workflows/{wid}/activate", headers=_headers(org)
    )
    assert activate.status_code == 200, activate.text

    rotated = await async_client.post(
        f"/api/v1/workflows/{wid}/hook-secret/rotate", headers=_headers(org)
    )
    assert rotated.status_code == 200, rotated.text
    new_secret = rotated.json()["hook_secret"]
    assert new_secret and new_secret != old_secret
    assert rotated.json()["hook_url"] == f"/api/v1/public/workflows/{wid}/hook"

    stale = await async_client.post(
        f"/api/v1/public/workflows/{wid}/hook",
        headers={"X-Zent-Workflow-Secret": old_secret},
        json={"message": "hola"},
    )
    assert stale.status_code == 401, stale.text

    fresh = await async_client.post(
        f"/api/v1/public/workflows/{wid}/hook",
        headers={"X-Zent-Workflow-Secret": new_secret},
        json={"message": "hola"},
    )
    assert fresh.status_code == 200, fresh.text

    # El hash nunca sale en el detalle; solo la señal de que existe.
    detail = await async_client.get(f"/api/v1/workflows/{wid}", headers=_headers(org))
    assert detail.json()["has_hook_secret"] is True
    assert "hook_secret_hash" not in detail.json()["trigger_config"]


@pytest.mark.asyncio
async def test_public_hook_rejects_secret_in_query_string(async_client: AsyncClient) -> None:
    """Bruno/Postman suelen pegar X-Zent-Workflow-Secret en Params. El hook
    solo lee el header: hay que devolver un 401 que lo diga, no un genérico."""
    org = await _org(async_client, "WF Hook Query")
    wf = await _workflow(async_client, org)
    wid = wf["workflow_id"]
    secret = wf["hook_secret"]
    activate = await async_client.post(
        f"/api/v1/workflows/{wid}/activate", headers=_headers(org)
    )
    assert activate.status_code == 200, activate.text

    via_query = await async_client.post(
        f"/api/v1/public/workflows/{wid}/hook",
        params={"X-Zent-Workflow-Secret": secret},
        json={"message": "quien es el gerente"},
    )
    assert via_query.status_code == 401, via_query.text
    body = via_query.json()
    msg = str(body.get("message") or body.get("detail") or "")
    assert "header" in msg.lower()
    assert "X-Zent-Workflow-Secret" in msg

    via_header = await async_client.post(
        f"/api/v1/public/workflows/{wid}/hook",
        headers={"X-Zent-Workflow-Secret": secret},
        json={"message": "quien es el gerente"},
    )
    assert via_header.status_code == 200, via_header.text


@pytest.mark.asyncio
async def test_rotate_hook_secret_unknown_workflow(async_client: AsyncClient) -> None:
    org = await _org(async_client, "WF Studio Rotate 404")
    missing = await async_client.post(
        f"/api/v1/workflows/{uuid4()}/hook-secret/rotate", headers=_headers(org)
    )
    assert missing.status_code == 404


# ---------------------------------------------------------------------------
# Versiones
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_version_snapshot_lifecycle(async_client: AsyncClient) -> None:
    org = await _org(async_client, "WF Studio Versions")
    wid = (await _workflow(async_client, org))["workflow_id"]

    empty = await async_client.get(f"/api/v1/workflows/{wid}/versions", headers=_headers(org))
    assert empty.status_code == 200, empty.text
    assert empty.json() == {"versions": [], "count": 0}

    snap = await async_client.post(
        f"/api/v1/workflows/{wid}/versions",
        headers=_headers(org),
        json={"notes": "primera"},
    )
    assert snap.status_code == 200, snap.text
    version = snap.json()
    assert version["version_number"] == 1
    assert version["status"] == "draft"
    assert version["notes"] == "primera"
    # El snapshot es ejecutable y no filtra el secret.
    assert version["config_snapshot"]["name"] == "Studio WF"
    assert version["config_snapshot"]["steps"]
    assert "hook_secret_hash" not in version["config_snapshot"]["trigger_config"]

    second = await async_client.post(
        f"/api/v1/workflows/{wid}/versions", headers=_headers(org), json={}
    )
    assert second.json()["version_number"] == 2

    listed = await async_client.get(f"/api/v1/workflows/{wid}/versions", headers=_headers(org))
    assert [v["version_number"] for v in listed.json()["versions"]] == [2, 1]

    vid = version["id"]
    ready = await async_client.post(
        f"/api/v1/workflows/{wid}/versions/{vid}/promote",
        headers=_headers(org),
        json={"status": "ready"},
    )
    assert ready.status_code == 200, ready.text
    assert ready.json()["status"] == "ready"

    prod = await async_client.post(
        f"/api/v1/workflows/{wid}/versions/{vid}/promote",
        headers=_headers(org),
        json={"status": "production"},
    )
    assert prod.json()["status"] == "production"

    # draft → production no es una transición válida.
    bad = await async_client.post(
        f"/api/v1/workflows/{wid}/versions/{second.json()['id']}/promote",
        headers=_headers(org),
        json={"status": "production"},
    )
    assert bad.status_code == 400
    assert "transición inválida" in bad.text

    missing = await async_client.post(
        f"/api/v1/workflows/{wid}/versions/{uuid4()}/promote",
        headers=_headers(org),
        json={"status": "ready"},
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_publish_activates_and_pins_production(async_client: AsyncClient) -> None:
    org = await _org(async_client, "WF Studio Publish")
    wid = (await _workflow(async_client, org))["workflow_id"]

    published = await async_client.post(
        f"/api/v1/workflows/{wid}/publish",
        headers=_headers(org),
        json={"notes": "v1 lista"},
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "active"
    assert published.json()["version"]["status"] == "production"

    detail = await async_client.get(f"/api/v1/workflows/{wid}", headers=_headers(org))
    assert detail.json()["status"] == "active"

    # Publicar otra vez deja una sola versión en production.
    again = await async_client.post(
        f"/api/v1/workflows/{wid}/publish", headers=_headers(org), json={}
    )
    assert again.json()["version"]["version_number"] == 2
    versions = (
        await async_client.get(f"/api/v1/workflows/{wid}/versions", headers=_headers(org))
    ).json()["versions"]
    production = [v for v in versions if v["status"] == "production"]
    assert len(production) == 1
    assert production[0]["version_number"] == 2
    assert next(v for v in versions if v["version_number"] == 1)["status"] == "ready"


@pytest.mark.asyncio
async def test_restore_version_rolls_back_live_workflow(async_client: AsyncClient) -> None:
    org = await _org(async_client, "WF Studio Restore")
    wid = (await _workflow(async_client, org, "Antes"))["workflow_id"]

    snap = await async_client.post(
        f"/api/v1/workflows/{wid}/versions", headers=_headers(org), json={}
    )
    vid = snap.json()["id"]

    patched = await async_client.patch(
        f"/api/v1/workflows/{wid}",
        headers=_headers(org),
        json={
            "name": "Despues",
            "steps": [
                {"type": "notify", "config": {"channel": "in_app", "title": "A", "message": "m"}},
                {"type": "notify", "config": {"channel": "in_app", "title": "B", "message": "m"}},
            ],
        },
    )
    assert patched.status_code == 200, patched.text
    changed = await async_client.get(f"/api/v1/workflows/{wid}", headers=_headers(org))
    assert changed.json()["name"] == "Despues"
    assert len(changed.json()["steps"]) == 2

    restored = await async_client.post(
        f"/api/v1/workflows/{wid}/versions/{vid}/restore", headers=_headers(org)
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["version_number"] == 1

    back = await async_client.get(f"/api/v1/workflows/{wid}", headers=_headers(org))
    assert back.json()["name"] == "Antes"
    assert len(back.json()["steps"]) == 1
    # Restaurar no toca el secret inbound.
    assert back.json()["has_hook_secret"] is True


@pytest.mark.asyncio
async def test_versions_isolated_per_organization(async_client: AsyncClient) -> None:
    owner = await _org(async_client, "WF Studio Owner")
    other = await _org(async_client, "WF Studio Intruder")
    wid = (await _workflow(async_client, owner))["workflow_id"]
    await async_client.post(
        f"/api/v1/workflows/{wid}/versions", headers=_headers(owner), json={}
    )

    leaked = await async_client.get(
        f"/api/v1/workflows/{wid}/versions", headers=_headers(other)
    )
    assert leaked.status_code == 200
    assert leaked.json()["count"] == 0

    denied = await async_client.post(
        f"/api/v1/workflows/{wid}/versions", headers=_headers(other), json={}
    )
    assert denied.status_code == 404


# ---------------------------------------------------------------------------
# Trigger editable desde el estudio
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_patch_updates_trigger_type(async_client: AsyncClient) -> None:
    org = await _org(async_client, "WF Studio Trigger")
    wid = (await _workflow(async_client, org))["workflow_id"]

    patched = await async_client.patch(
        f"/api/v1/workflows/{wid}",
        headers=_headers(org),
        json={
            "trigger_type": "schedule",
            "trigger_config": {"every_minutes": 15},
            "steps": NOTIFY_STEPS,
        },
    )
    assert patched.status_code == 200, patched.text

    detail = await async_client.get(f"/api/v1/workflows/{wid}", headers=_headers(org))
    assert detail.json()["trigger_type"] == "schedule"
    assert detail.json()["trigger_config"]["every_minutes"] == 15

    bad = await async_client.patch(
        f"/api/v1/workflows/{wid}",
        headers=_headers(org),
        json={"trigger_type": "carrier-pigeon"},
    )
    assert bad.status_code == 422


# ---------------------------------------------------------------------------
# Probar (dry-run) ejecuta los nodos de lectura de verdad
# ---------------------------------------------------------------------------
class _FakeRuntime:
    """Runtime de agente: responde o revienta, según `boom`."""

    def __init__(self, answer: str = "El gerente es Ana.", boom: str | None = None) -> None:
        self.answer = answer
        self.boom = boom
        self.calls: list[str] = []

    async def run(self, request):  # noqa: ANN001, ANN201
        from src.agents.runtime.agent_runtime import AgentRunResult

        self.calls.append(request.message)
        if self.boom:
            raise RuntimeError(self.boom)
        return AgentRunResult(
            run_id=uuid4(),
            agent_id=request.agent.id,
            organization_id=request.agent.organization_id,
            status="completed",
            answer=self.answer,
            message=request.message,
            user_id=request.user_id,
            role=request.role,
            total_latency_ms=12.0,
            total_tokens=30,
            cost=0.0002,
        )


async def _agent(client: AsyncClient, org: dict, name: str = "Giannina") -> str:
    """Agente recién creado: `draft` + `is_active`, como en Agent Studio."""
    created = await client.post(
        "/api/v1/agents",
        headers=_headers(org),
        json={"name": name, "system_prompt": "responde corto", "model": "gpt-4o-mini", "tools": []},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def _llm_workflow(client: AsyncClient, org: dict, llm_config: dict) -> str:
    graph = _graph(
        [
            _node("t", "trigger_webhook", {}, input_ports=[]),
            _node("ask", "llm", llm_config),
            _notify_node("avisa", "no-enviar-llm"),
        ],
        [_edge("e1", "t", "ask"), _edge("e2", "ask", "avisa")],
        ["t"],
    )
    created = await client.post(
        "/api/v1/workflows",
        headers=_headers(org),
        json={"name": "Preguntar", "trigger_type": "webhook", "graph": graph},
    )
    assert created.status_code == 200, created.text
    return created.json()["workflow_id"]


async def _run_steps(client: AsyncClient, org: dict, wid: str, *, simulate: bool) -> dict:
    out = await client.post(
        f"/api/v1/workflows/{wid}/run",
        headers=_headers(org),
        json={"payload": {"message": "quien es el gerente"}, "simulate": simulate},
    )
    assert out.status_code == 200, out.text
    detail = await client.get(
        f"/api/v1/workflows/runs/{out.json()['run_id']}", headers=_headers(org)
    )
    assert detail.status_code == 200, detail.text
    return {s["node_id"]: s for s in detail.json()["steps"]}


@pytest.mark.asyncio
async def test_dry_run_executes_agent_and_still_simulates_notify(
    async_client: AsyncClient,
) -> None:
    from src.api.deps import get_agent_runtime
    from src.api.main import app

    org = await _org(async_client, "WF Studio Probar")
    agent_id = await _agent(async_client, org)
    wid = await _llm_workflow(
        async_client, org, {"agent_id": agent_id, "prompt": "{{trigger.message}}"}
    )

    runtime = _FakeRuntime()
    app.dependency_overrides[get_agent_runtime] = lambda: runtime
    try:
        steps = await _run_steps(async_client, org, wid, simulate=True)
    finally:
        app.dependency_overrides.pop(get_agent_runtime, None)

    # El agente corrió de verdad con el mensaje del trigger.
    assert runtime.calls == ["quien es el gerente"]
    assert steps["ask"]["status"] == "succeeded"
    assert steps["ask"]["output"]["text"] == "El gerente es Ana."
    assert steps["ask"]["output"].get("simulated") is None

    # La escritura sigue simulada: nada de notificaciones en un dry-run.
    assert steps["avisa"]["status"] == "simulated"
    session = await _session()
    try:
        from sqlalchemy import text

        n = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM tenant_notifications "
                    "WHERE organization_id = :oid AND title = 'no-enviar-llm'"
                ),
                {"oid": UUID(org["organization_id"])},
            )
        ).scalar()
        assert int(n) == 0
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_agent_error_surfaces_instead_of_echo(async_client: AsyncClient) -> None:
    from src.api.deps import get_agent_runtime
    from src.api.main import app

    org = await _org(async_client, "WF Studio Error")
    agent_id = await _agent(async_client, org)
    wid = await _llm_workflow(
        async_client, org, {"agent_id": agent_id, "prompt": "{{trigger.message}}"}
    )

    app.dependency_overrides[get_agent_runtime] = lambda: _FakeRuntime(boom="limit_reached")
    try:
        steps = await _run_steps(async_client, org, wid, simulate=True)
    finally:
        app.dependency_overrides.pop(get_agent_runtime, None)

    assert steps["ask"]["status"] == "failed"
    assert "limit_reached" in (steps["ask"]["error"] or "")
    # Ya no se traga el fallo devolviendo un eco del prompt.
    assert "gpt-4o-mini" not in str(steps["ask"].get("output") or {})


@pytest.mark.asyncio
async def test_unknown_agent_fails_with_clear_message(async_client: AsyncClient) -> None:
    org = await _org(async_client, "WF Studio Agente Ajeno")
    wid = await _llm_workflow(
        async_client, org, {"agent_id": str(uuid4()), "prompt": "{{trigger.message}}"}
    )
    steps = await _run_steps(async_client, org, wid, simulate=True)
    assert steps["ask"]["status"] == "failed"
    assert "no está disponible" in (steps["ask"]["error"] or "")


@pytest.mark.asyncio
async def test_llm_without_agent_marks_the_echo(async_client: AsyncClient) -> None:
    org = await _org(async_client, "WF Studio Sin Agente")
    wid = await _llm_workflow(async_client, org, {"prompt": "{{trigger.message}}"})
    steps = await _run_steps(async_client, org, wid, simulate=True)

    assert steps["ask"]["status"] == "succeeded"
    output = steps["ask"]["output"]
    assert output["echo"] is True
    assert "no tiene agente" in output["warning"]


async def _session():  # noqa: ANN202
    from src.infrastructure.postgres.session import get_async_session

    return await get_async_session()
