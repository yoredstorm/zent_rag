# =============================================================================
# Workflow Studio UX v2 (Fases 3 y 4) — ejecución parcial y pinned data.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.test_workflow_graph import _edge, _graph, _node
from tests.test_workflows import _create_org, _headers, _owner_session


async def _org(client: AsyncClient, name: str) -> dict:
    org = await _create_org(client, name)
    org["session"] = await _owner_session(client, org["organization_id"])
    return org


def _chain_graph() -> dict:
    return _graph(
        nodes=[
            _node("t", "trigger_webhook"),
            _node("n1", "notify", {"channel": "in_app", "title": "Aviso 1", "message": "uno"}),
            _node("n2", "notify", {"channel": "in_app", "title": "{{nodes.n1.output.title}}", "message": "dos"}),
            _node("n3", "notify", {"channel": "in_app", "title": "Aviso 3", "message": "tres"}),
        ],
        edges=[_edge("e1", "t", "n1"), _edge("e2", "n1", "n2"), _edge("e3", "n2", "n3")],
        entrypoints=["t"],
    )


async def _workflow(client: AsyncClient, org: dict, name: str, graph: dict) -> str:
    created = await client.post(
        "/api/v1/workflows",
        headers=_headers(org),
        json={"name": name, "trigger_type": "webhook", "graph": graph, "workflow_version": 2},
    )
    assert created.status_code == 200, created.text
    return created.json()["workflow_id"]


async def _run(
    client: AsyncClient,
    org: dict,
    workflow_id: str,
    *,
    simulate: bool = True,
    **extra: object,
) -> dict:
    resp = await client.post(
        f"/api/v1/workflows/{workflow_id}/run",
        headers={**_headers(org), "Idempotency-Key": f"run-{uuid4().hex}"},
        json={"payload": {}, "simulate": simulate, **extra},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _detail(client: AsyncClient, org: dict, run_id: str) -> dict:
    resp = await client.get(f"/api/v1/workflows/runs/{run_id}", headers=_headers(org))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _step(detail: dict, node_id: str) -> dict | None:
    return next((s for s in detail.get("steps", []) if s.get("node_id") == node_id), None)


@pytest.mark.asyncio
async def test_until_node_stops_and_skips_rest(async_client: AsyncClient) -> None:
    org = await _org(async_client, "Partial Until")
    workflow_id = await _workflow(async_client, org, "Cadena", _chain_graph())

    out = await _run(async_client, org, workflow_id, run_mode="until_node", target_node_id="n1")
    assert out["run_mode"] == "until_node"
    detail = await _detail(async_client, org, out["run_id"])
    assert detail["run_mode"] == "until_node"
    assert detail["target_node_id"] == "n1"
    assert _step(detail, "n1")["status"] == "simulated"
    assert _step(detail, "n2")["status"] == "skipped"
    assert _step(detail, "n3")["status"] == "skipped"


@pytest.mark.asyncio
async def test_node_mode_preloads_predecessors_from_source_run(async_client: AsyncClient) -> None:
    org = await _org(async_client, "Partial Node")
    workflow_id = await _workflow(async_client, org, "Cadena", _chain_graph())

    full = await _run(async_client, org, workflow_id)
    assert full["status"] == "simulated"

    partial = await _run(
        async_client,
        org,
        workflow_id,
        run_mode="node",
        target_node_id="n2",
        source_run_id=full["run_id"],
    )
    detail = await _detail(async_client, org, partial["run_id"])
    n2 = _step(detail, "n2")
    assert n2 is not None and n2["status"] == "simulated"
    # La referencia a la salida del predecesor quedó resuelta con el run fuente.
    assert n2["output"]["title"] == "Aviso 1"
    # n1 no se re-ejecutó en este run parcial.
    assert _step(detail, "n1") is None


@pytest.mark.asyncio
async def test_from_node_continues_downstream(async_client: AsyncClient) -> None:
    org = await _org(async_client, "Partial From")
    workflow_id = await _workflow(async_client, org, "Cadena", _chain_graph())
    full = await _run(async_client, org, workflow_id)

    partial = await _run(
        async_client,
        org,
        workflow_id,
        run_mode="from_node",
        target_node_id="n2",
        source_run_id=full["run_id"],
    )
    detail = await _detail(async_client, org, partial["run_id"])
    assert _step(detail, "n2")["status"] == "simulated"
    assert _step(detail, "n3")["status"] == "simulated"


@pytest.mark.asyncio
async def test_node_mode_without_previous_data_fails_with_human_error(async_client: AsyncClient) -> None:
    org = await _org(async_client, "Partial Missing")
    workflow_id = await _workflow(async_client, org, "Cadena", _chain_graph())

    out = await _run(async_client, org, workflow_id, run_mode="node", target_node_id="n2")
    assert out["status"] == "failed"
    assert "Faltan datos" in out["error"]


# ---------------------------------------------------------------------------
# Pinned data
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_pinned_data_only_applies_to_simulation(async_client: AsyncClient) -> None:
    org = await _org(async_client, "Pinned Data")
    h = _headers(org)
    workflow_id = await _workflow(async_client, org, "Cadena", _chain_graph())

    put = await async_client.put(
        f"/api/v1/workflows/{workflow_id}/pinned-data/n1",
        headers={**h, "Idempotency-Key": f"pin-{uuid4().hex}"},
        json={"output": {"title": "fijado", "sent": False}},
    )
    assert put.status_code == 200, put.text

    listed = await async_client.get(f"/api/v1/workflows/{workflow_id}/pinned-data", headers=h)
    assert listed.json()["nodes"][0]["node_id"] == "n1"

    sim = await _run(async_client, org, workflow_id, run_mode="node", target_node_id="n1")
    sim_detail = await _detail(async_client, org, sim["run_id"])
    assert _step(sim_detail, "n1")["output"]["title"] == "fijado"
    assert _step(sim_detail, "n1")["status"] == "simulated"

    # En producción (simulate=false) los pinned se ignoran por diseño.
    real = await _run(async_client, org, workflow_id, simulate=False)
    real_detail = await _detail(async_client, org, real["run_id"])
    n1 = _step(real_detail, "n1")
    assert n1["output"]["sent"] is True
    assert n1["output"].get("simulated") is not True

    removed = await async_client.delete(
        f"/api/v1/workflows/{workflow_id}/pinned-data/n1",
        headers={**h, "Idempotency-Key": f"unpin-{uuid4().hex}"},
    )
    assert removed.status_code == 200


@pytest.mark.asyncio
async def test_pinned_data_rejects_unknown_node_and_cross_tenant(async_client: AsyncClient) -> None:
    org_a = await _org(async_client, "Pinned Tenant A")
    org_b = await _org(async_client, "Pinned Tenant B")
    workflow_id = await _workflow(async_client, org_a, "Cadena", _chain_graph())

    unknown = await async_client.put(
        f"/api/v1/workflows/{workflow_id}/pinned-data/nope",
        headers={**_headers(org_a), "Idempotency-Key": f"pin-{uuid4().hex}"},
        json={"output": {"x": 1}},
    )
    assert unknown.status_code == 422

    cross = await async_client.get(
        f"/api/v1/workflows/{workflow_id}/pinned-data", headers=_headers(org_b)
    )
    assert cross.status_code == 404
