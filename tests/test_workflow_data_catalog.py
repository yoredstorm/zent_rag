# =============================================================================
# Workflow Semantic Core — Fase 6: DataReference + Data Catalog.
#
# Unit: parse/render de referencias. API: catálogo de datos por grafo con
# trigger schema, contratos de salida y samples reales del último run.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.platform.workflows.references import DataReference, humanize_path, parse_reference
from tests.test_workflows import _create_org, _headers, _owner_session


def _node(nid: str, ntype: str, config: dict | None = None, **extra) -> dict:
    node: dict = {
        "id": nid,
        "type": ntype,
        "label": ntype,
        "config": config or {},
        "input_ports": [{"name": "in", "type": "json"}],
        "output_ports": [{"name": "out", "type": "json"}],
        "retry_policy": {"max_attempts": 1},
        "timeout_ms": 60_000,
        "error_policy": "fail",
    }
    node.update(extra)
    return node


def _edge(eid: str, frm: str, to: str, **extra) -> dict:
    edge: dict = {"id": eid, "from_node": frm, "from_port": "out", "to_node": to, "to_port": "in"}
    edge.update(extra)
    return edge


def _graph(nodes: list[dict], edges: list[dict], entrypoints: list[str]) -> dict:
    return {
        "workflow_version": 2,
        "nodes": nodes,
        "edges": edges,
        "variables": {},
        "entrypoints": entrypoints,
        "metadata": {},
    }


async def _create(client: AsyncClient, org: dict, graph: dict, name: str) -> str:
    resp = await client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"dc-{uuid4().hex}"},
        json={"name": name, "trigger_type": "webhook", "graph": graph, "workflow_version": 2},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["workflow_id"]


# ---------------------------------------------------------------------------
# Unit: DataReference
# ---------------------------------------------------------------------------
def test_parse_and_render_node_reference() -> None:
    ref = parse_reference("{{nodes.n1.output.rows.0.producto}}")
    assert ref is not None
    assert ref.source_kind == "node"
    assert ref.source_id == "n1"
    assert ref.path == ("rows", "0", "producto")
    assert ref.render() == "{{nodes.n1.output.rows.0.producto}}"
    assert ref.business_label == "Rows 0 producto"


def test_parse_trigger_and_variable_references() -> None:
    trigger = parse_reference("{{trigger.customer.name}}")
    assert trigger is not None
    assert trigger.source_kind == "trigger"
    assert trigger.render() == "{{trigger.customer.name}}"

    variable = parse_reference("{{variables.umbral}}")
    assert variable is not None
    assert variable.source_kind == "variable"
    assert variable.render() == "{{variables.umbral}}"

    assert parse_reference("{{steps.0.output.x}}") is None
    assert parse_reference("nope") is None


def test_data_reference_without_path_renders_node_output() -> None:
    ref = DataReference(source_kind="node", source_id="n9")
    assert ref.render() == "{{nodes.n9.output}}"
    assert ref.to_dict()["ref"] == "{{nodes.n9.output}}"
    assert humanize_path("total_ventas") == "Total ventas"


# ---------------------------------------------------------------------------
# API: catálogo de datos del grafo
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_data_catalog_lists_trigger_and_contract_fields(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Data Catalog")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    graph = _graph(
        [
            _node("t", "trigger_webhook"),
            _node("q", "query_business_data", {"ask": "stock disponible"}, label="Consulta de datos"),
            _node("var", "set_variable", {"name": "umbral", "value": "10"}),
            _node("n", "notify", {"channel": "in_app", "title": "ok", "message": "ok"}),
        ],
        [
            _edge("e1", "t", "q"),
            _edge("e2", "q", "var"),
            _edge("e3", "var", "n"),
        ],
        ["t"],
    )
    wid = await _create(async_client, org, graph, "Data Catalog WF")

    resp = await async_client.get(f"/api/v1/workflows/{wid}/data-catalog", headers=h)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["workflow_id"] == wid
    assert body["run_id"] is None
    by_id = {source["id"]: source for source in body["sources"]}

    trigger = by_id["trigger"]
    assert any(field["ref"] == "{{trigger.message}}" for field in trigger["fields"])

    query = by_id["q"]
    assert query["label"] == "Consulta de datos"
    refs = {field["key"]: field["ref"] for field in query["fields"]}
    assert refs["rows"] == "{{nodes.q.output.rows}}"
    assert refs["answer"] == "{{nodes.q.output.answer}}"
    assert "data" in (query.get("context_writes") or [])

    variable = by_id["var"]
    assert {field["key"] for field in variable["fields"]} >= {"variable", "value"}
    assert "variables" in (variable.get("context_writes") or [])

    # Sample real tras un run simulado.
    run = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers=h,
        json={"payload": {"message": "stock bajo"}, "simulate": True},
    )
    assert run.status_code == 200, run.text
    after = (await async_client.get(f"/api/v1/workflows/{wid}/data-catalog", headers=h)).json()
    assert after["run_id"]
    by_id_after = {source["id"]: source for source in after["sources"]}
    message = next(
        field for field in by_id_after["trigger"]["fields"] if field["ref"] == "{{trigger.message}}"
    )
    assert message["sample"] == "stock bajo"
    variable_field = next(
        field for field in by_id_after["var"]["fields"] if field["key"] == "variable"
    )
    assert variable_field["sample"] == "umbral"


@pytest.mark.asyncio
async def test_data_catalog_event_trigger_uses_event_schema(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Data Catalog Event")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    graph = _graph(
        [
            _node("t", "trigger_event", {"event_type": "sales.closed", "filters": {}}),
            _node("n", "notify", {"channel": "in_app", "title": "ok", "message": "ok"}),
        ],
        [_edge("e1", "t", "n")],
        ["t"],
    )
    wid = await _create(async_client, org, graph, "Data Catalog Event WF")

    resp = await async_client.get(f"/api/v1/workflows/{wid}/data-catalog", headers=h)
    assert resp.status_code == 200, resp.text
    trigger = resp.json()["sources"][0]
    assert trigger["label"] == "Se cerró una venta"
    fields = {field["key"]: field for field in trigger["fields"]}
    assert fields["total"]["ref"] == "{{trigger.total}}"
    assert fields["total"]["type"] == "money"
    assert fields["customer"]["label"] == "Cliente"


@pytest.mark.asyncio
async def test_data_catalog_isolated_by_tenant(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Data Catalog Owner")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    graph = _graph(
        [_node("t", "trigger_webhook"), _node("n", "notify", {"channel": "in_app", "title": "x", "message": "x"})],
        [_edge("e1", "t", "n")],
        ["t"],
    )
    wid = await _create(async_client, org, graph, "Data Catalog Owner WF")

    foreign = await _create_org(async_client, "Data Catalog Other")
    foreign["session"] = await _owner_session(async_client, foreign["organization_id"])
    resp = await async_client.get(f"/api/v1/workflows/{wid}/data-catalog", headers=_headers(foreign))
    assert resp.status_code == 404

    missing = await async_client.get(
        f"/api/v1/workflows/{uuid4()}/data-catalog", headers=_headers(org)
    )
    assert missing.status_code == 404
