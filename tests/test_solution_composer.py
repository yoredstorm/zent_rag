from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.test_workflows import _create_org, _headers, _owner_session


async def _org(client: AsyncClient, name: str) -> dict:
    org = await _create_org(client, name)
    org["session"] = await _owner_session(client, org["organization_id"])
    return org


@pytest.mark.asyncio
async def test_compose_mission_without_template(async_client: AsyncClient) -> None:
    org = await _org(async_client, "P04 Compose New")
    brief = (
        "Cuando llegue un contrato, analiza el documento con IA, "
        "espera aprobación humana y crea un recordatorio de seguimiento."
    )
    response = await async_client.post(
        "/api/v1/studio/solutions/compile",
        headers=_headers(org),
        json={"brief": brief, "mode": "compose"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "compose"
    assert body["template_id"] == "composed"
    assert body["graph"] is not None, body["blockers"]
    assert body["can_materialize"] is True, body["blockers"]
    assert body["architect"]["source"] == "heuristics"
    assert any(node["type"] == "llm" for node in body["graph"]["nodes"])


@pytest.mark.asyncio
async def test_composed_solution_materializes_real_draft(async_client: AsyncClient) -> None:
    org = await _org(async_client, "P04 Compose Materialize")
    brief = (
        "Cuando llegue un contrato, analiza el documento con IA, "
        "espera aprobación humana y crea un recordatorio de seguimiento."
    )
    response = await async_client.post(
        "/api/v1/studio/solutions/materialize",
        headers=_headers(org),
        json={
            "brief": brief,
            "mode": "compose",
            "confirm": True,
            "idempotency_key": f"p04-{uuid4().hex}",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "READY", body
    workflow_id = body["artifacts"]["workflow"]["id"]
    detail = await async_client.get(
        f"/api/v1/workflows/{workflow_id}", headers=_headers(org)
    )
    assert detail.status_code == 200, detail.text
    graph = detail.json()["graph"]
    assert graph
    llm_nodes = [node for node in graph["nodes"] if node["type"] == "llm"]
    assert llm_nodes
    assert all((node.get("config") or {}).get("agent_id") for node in llm_nodes)


@pytest.mark.asyncio
async def test_compose_does_not_invent_unavailable_capability(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P04 Compose Missing Cap")
    response = await async_client.post(
        "/api/v1/studio/solutions/compile",
        headers=_headers(org),
        json={
            "brief": "Consulta el ERP inexistente, compara facturas y envía un pago automático.",
            "mode": "compose",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "compose"
    if body["graph"] is None:
        assert body["blockers"]
        assert body["status"] == "NEEDS_CONFIGURATION"


@pytest.mark.asyncio
async def test_template_mode_still_wins_when_requested(async_client: AsyncClient) -> None:
    org = await _org(async_client, "P04 Template Mode")
    response = await async_client.post(
        "/api/v1/studio/solutions/compile",
        headers=_headers(org),
        json={
            "brief": "Quiero un mentor de Python con progreso",
            "mode": "template",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "template"
    assert body["template_id"] == "mentor"
