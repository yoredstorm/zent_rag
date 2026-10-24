# =============================================================================
# P01 — un solo gate de release: certificado de backend, hashes y tenant.
# =============================================================================
from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from tests.test_workflow_graph import _edge, _graph, _node
from tests.test_workflows import _create_org, _headers, _owner_session


async def _org(client: AsyncClient, name: str) -> dict:
    org = await _create_org(client, name)
    org["session"] = await _owner_session(client, org["organization_id"])
    return org


def _step_workflow_body(name: str) -> dict:
    return {
        "name": name,
        "trigger_type": "webhook",
        "steps": [
            {
                "type": "notify",
                "config": {"channel": "in_app", "title": "P01", "message": "ok"},
            }
        ],
    }


def _effect_graph(metadata: dict | None = None) -> dict:
    graph = _graph(
        nodes=[
            _node("t", "trigger_webhook"),
            _node(
                "pay",
                "capability_call",
                {"capability_ref": "payments.checkout.create", "binding_ref": "missing"},
            ),
            _node("end", "end"),
        ],
        edges=[_edge("e1", "t", "pay"), _edge("e2", "pay", "end")],
        entrypoints=["t"],
    )
    if metadata is not None:
        graph["metadata"] = metadata
    return graph


async def _create(
    client: AsyncClient,
    org: dict,
    *,
    name: str,
    graph: dict | None = None,
    workspace_id: str | None = None,
    headers: dict | None = None,
) -> str:
    body: dict = _step_workflow_body(name)
    if graph is not None:
        body = {
            "name": name,
            "trigger_type": "webhook",
            "graph": graph,
            "workflow_version": 2,
        }
    if workspace_id:
        body["workspace_id"] = workspace_id
    created = await client.post(
        "/api/v1/workflows",
        headers=headers or {**_headers(org), "Idempotency-Key": f"p01-{uuid4().hex}"},
        json=body,
    )
    assert created.status_code == 200, created.text
    return created.json()["workflow_id"]


async def _certify(
    client: AsyncClient,
    org: dict,
    workflow_id: str,
    *,
    level: str = "design",
    headers: dict | None = None,
) -> dict:
    response = await client.post(
        f"/api/v1/workflows/{workflow_id}/certifications",
        headers={**(headers or _headers(org)), "Idempotency-Key": f"cert-{uuid4().hex}"},
        json={"level": level},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_publish_without_certificate_is_denied(async_client: AsyncClient) -> None:
    org = await _org(async_client, "P01 Publish Denied")
    wid = await _create(async_client, org, name="Sin certificado")

    response = await async_client.post(
        f"/api/v1/workflows/{wid}/publish", headers=_headers(org), json={}
    )

    assert response.status_code == 409, response.text
    assert "certification_required" in response.text


@pytest.mark.asyncio
async def test_activate_without_certificate_is_denied(async_client: AsyncClient) -> None:
    org = await _org(async_client, "P01 Activate Denied")
    wid = await _create(async_client, org, name="Activar sin certificado")

    response = await async_client.post(
        f"/api/v1/workflows/{wid}/activate", headers=_headers(org)
    )

    assert response.status_code == 409, response.text
    detail = await async_client.get(
        f"/api/v1/workflows/{wid}", headers=_headers(org)
    )
    assert detail.json()["status"] == "draft"


@pytest.mark.asyncio
async def test_design_certificate_allows_publish_for_internal_flow(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P01 Design Happy")
    wid = await _create(async_client, org, name="Aviso interno")
    certificate = await _certify(async_client, org, wid)

    assert certificate["state"] == "DESIGN_VALID"
    assert certificate["graph_hash"]
    gate = await async_client.get(
        f"/api/v1/workflows/{wid}/release-gate", headers=_headers(org)
    )
    assert gate.status_code == 200, gate.text
    assert gate.json()["allowed"] is True

    published = await async_client.post(
        f"/api/v1/workflows/{wid}/publish", headers=_headers(org), json={}
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "active"
    assert published.json()["release"]["allowed"] is True


@pytest.mark.asyncio
async def test_simulated_certificate_cannot_publish_external_effect(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P01 External Denied")
    wid = await _create(
        async_client, org, name="Pago externo", graph=_effect_graph()
    )
    certificate = await _certify(async_client, org, wid, level="simulation")

    assert certificate["state"] == "SIMULATION_PASSED"
    response = await async_client.post(
        f"/api/v1/workflows/{wid}/publish", headers=_headers(org), json={}
    )
    assert response.status_code == 409, response.text
    assert "certification_level_insufficient" in response.text
    assert "SANDBOX_VERIFIED" in response.text


@pytest.mark.asyncio
async def test_certificate_becomes_stale_when_graph_changes(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P01 Graph Stale")
    wid = await _create(async_client, org, name="Cambia el grafo")
    await _certify(async_client, org, wid)

    changed = _graph(
        nodes=[_node("t", "trigger_webhook"), _node("n", "set_variable", {"name": "x", "value": 1}), _node("end", "end")],
        edges=[_edge("e1", "t", "n"), _edge("e2", "n", "end")],
        entrypoints=["t"],
    )
    patched = await async_client.patch(
        f"/api/v1/workflows/{wid}",
        headers=_headers(org),
        json={"graph": changed, "workflow_version": 2},
    )
    assert patched.status_code == 200, patched.text

    response = await async_client.post(
        f"/api/v1/workflows/{wid}/publish", headers=_headers(org), json={}
    )
    assert response.status_code == 409, response.text
    assert "certificate_stale" in response.text


@pytest.mark.asyncio
async def test_client_supplied_certificate_metadata_is_ignored(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P01 Forged Metadata")
    forged = {
        "schema": "zent.workflow.certification/v1",
        "level": "provider",
        "state": "READY_TO_PUBLISH",
        "graph_hash": "forged",
        "unverified": 0,
        "publishable": True,
    }
    wid = await _create(
        async_client, org, name="Certificado forjado", graph=_effect_graph({"certification": forged})
    )

    response = await async_client.post(
        f"/api/v1/workflows/{wid}/publish", headers=_headers(org), json={}
    )
    assert response.status_code == 409, response.text
    assert "certification_required" in response.text
    assert "forged" not in response.text


@pytest.mark.asyncio
async def test_certificate_from_other_workspace_is_denied(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P01 Workspace")
    listing = await async_client.get("/api/v1/workspaces", headers=_headers(org))
    assert listing.status_code == 200, listing.text
    ws_a = next(w for w in listing.json()["workspaces"] if w["slug"] == "default")
    created = await async_client.post(
        "/api/v1/workspaces", headers=_headers(org), json={"name": "Workspace B"}
    )
    assert created.status_code == 201, created.text
    ws_b = created.json()
    headers_a = {**_headers(org), "X-Workspace-Id": ws_a["id"]}
    headers_b = {**_headers(org), "X-Workspace-Id": ws_b["id"]}
    wid = await _create(
        async_client, org, name="Solo workspace A", workspace_id=ws_a["id"], headers=headers_a
    )
    await _certify(async_client, org, wid, headers=headers_a)

    response = await async_client.post(
        f"/api/v1/workflows/{wid}/publish", headers=headers_b, json={}
    )
    assert response.status_code in (403, 409), response.text
    assert "workspace_mismatch" in response.text or "certification" in response.text


@pytest.mark.asyncio
async def test_legacy_policy_is_explicit_and_auditable(async_client: AsyncClient) -> None:
    org = await _org(async_client, "P01 Legacy")
    wid = await _create(async_client, org, name="Histórico")

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE workflows SET release_policy = 'legacy', "
                "release_policy_reason = 'prueba P01', release_policy_at = NOW() "
                "WHERE id = :wid AND organization_id = :oid"
            ),
            {"wid": UUID(wid), "oid": UUID(org["organization_id"])},
        )
        await session.commit()
    finally:
        await session.close()

    gate = await async_client.get(
        f"/api/v1/workflows/{wid}/release-gate", headers=_headers(org)
    )
    assert gate.status_code == 200, gate.text
    assert gate.json()["allowed"] is True
    assert gate.json()["legacy"] is True
    published = await async_client.post(
        f"/api/v1/workflows/{wid}/publish", headers=_headers(org), json={}
    )
    assert published.status_code == 200, published.text


@pytest.mark.asyncio
async def test_publish_and_edit_race_never_publishes_uncertified_graph(
    async_client: AsyncClient,
) -> None:
    """Si la edición gana, publish queda STALE; si publica primero, la versión
    congelada conserva el hash certificado. Nunca se publica el grafo nuevo."""
    org = await _org(async_client, "P01 Race")
    wid = await _create(async_client, org, name="Carrera")
    certificate = await _certify(async_client, org, wid)
    changed = _graph(
        nodes=[_node("t", "trigger_webhook"), _node("n", "set_variable", {"name": "race", "value": 1}), _node("end", "end")],
        edges=[_edge("e1", "t", "n"), _edge("e2", "n", "end")],
        entrypoints=["t"],
    )

    published, patched = await asyncio.gather(
        async_client.post(
            f"/api/v1/workflows/{wid}/publish",
            headers={**_headers(org), "Idempotency-Key": f"race-pub-{uuid4().hex}"},
            json={},
        ),
        async_client.patch(
            f"/api/v1/workflows/{wid}",
            headers={**_headers(org), "Idempotency-Key": f"race-edit-{uuid4().hex}"},
            json={"graph": changed, "workflow_version": 2},
        ),
    )
    assert patched.status_code in (200, 409), patched.text
    if published.status_code == 200:
        versions = await async_client.get(
            f"/api/v1/workflows/{wid}/versions", headers=_headers(org)
        )
        production = next(
            v for v in versions.json()["versions"] if v["status"] == "production"
        )
        from src.platform.workflows.release_policy import graph_fingerprint

        assert graph_fingerprint(production["config_snapshot"]["graph"]) == certificate["graph_hash"]
    else:
        assert published.status_code == 409, published.text
        assert "certificate_stale" in published.text or "certification" in published.text


@pytest.mark.asyncio
async def test_awaiting_approval_certificate_cannot_publish(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P01 Approval")
    wid = await _create(async_client, org, name="Pendiente de aprobación")
    certificate = await _certify(async_client, org, wid)

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE workflow_certificates SET state = 'AWAITING_APPROVAL' "
                "WHERE id = :cid"
            ),
            {"cid": UUID(certificate["id"])},
        )
        await session.commit()
    finally:
        await session.close()

    response = await async_client.post(
        f"/api/v1/workflows/{wid}/publish", headers=_headers(org), json={}
    )
    assert response.status_code == 409, response.text
    assert "human_approval_required" in response.text
