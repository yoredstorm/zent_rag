# =============================================================================
# Workflow Semantic Core — Fase 7: persistencia del contexto por run.
#
# Contribuciones append-only + proyección por run; validación de refs por
# organización (fail-closed) y round-trip con un run real.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from src.platform.workflows.context_store import (
    filter_persistable_applied,
    load_run_context,
)
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
        headers={**_headers(org), "Idempotency-Key": f"cs-{uuid4().hex}"},
        json={"name": name, "trigger_type": "webhook", "graph": graph, "workflow_version": 2},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["workflow_id"]


@pytest.mark.asyncio
async def test_filter_persistable_applied_rejects_foreign_refs(monkeypatch: pytest.MonkeyPatch) -> None:
    valid_evidence = str(uuid4())
    foreign_evidence = str(uuid4())

    async def fake_ref_exists(section: str, organization_id: UUID, ref_id: str) -> bool:
        return ref_id == valid_evidence

    monkeypatch.setattr("src.platform.workflows.context_store._ref_exists", fake_ref_exists)

    applied = [
        {"section": "data", "payload": {"value": {"total": 1}}},
        {"section": "evidence_refs", "payload": {"value": {"evidence_id": valid_evidence}}},
        {"section": "evidence_refs", "payload": {"value": {"evidence_id": foreign_evidence}}},
        {"section": "claim_refs", "payload": {"value": {"claim_id": foreign_evidence}}},
    ]
    filtered = await filter_persistable_applied(uuid4(), applied)
    assert [item["section"] for item in filtered] == ["data", "evidence_refs"]
    assert filtered[1]["payload"]["value"]["evidence_id"] == valid_evidence


@pytest.mark.asyncio
async def test_run_persists_contributions_and_context(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Context Store")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    graph = _graph(
        [
            _node("t", "trigger_webhook"),
            _node(
                "br",
                "business_result",
                {"title": "Resumen del run", "section": "reports", "importance": "INFO"},
            ),
        ],
        [_edge("e1", "t", "br")],
        ["t"],
    )
    wid = await _create(async_client, org, graph, "Context Store WF")

    run = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers=h,
        json={"payload": {"message": "hola"}},
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["status"] == "succeeded", body

    context = body["result"]["context"]
    assert "security" not in context
    assert context["artifacts"], context
    artifact = context["artifacts"][0]
    assert artifact["value"]["kind"] == "business_result"
    assert artifact["provenance"]["node_type"] == "business_result"

    stored = await load_run_context(UUID(org["organization_id"]), UUID(body["run_id"]))
    assert stored is not None
    assert stored["artifacts"][0]["value"]["id"] == artifact["value"]["id"]

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT section, COUNT(*) AS n FROM workflow_context_contributions "
                    "WHERE run_id = :rid AND organization_id = :oid GROUP BY section"
                ),
                {"rid": body["run_id"], "oid": org["organization_id"]},
            )
        ).fetchall()
    finally:
        await session.close()
    by_section = {row.section: int(row.n) for row in rows}
    assert by_section.get("artifacts", 0) >= 1

    # Sin cross-tenant: otra organización no ve el contexto del run.
    assert await load_run_context(uuid4(), UUID(body["run_id"])) is None
