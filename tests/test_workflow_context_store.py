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

    detail = await async_client.get(f"/api/v1/workflows/runs/{body['run_id']}", headers=h)
    assert detail.status_code == 200, detail.text
    inspector = detail.json()
    assert inspector["chain_of_thought_exposed"] is False
    assert inspector["context"]["artifacts"]
    assert inspector["artifacts"][0]["value"]["id"] == artifact["value"]["id"]
    assert inspector["contributions"]
    assert any(item["section"] == "artifacts" for item in inspector["contributions"])
    assert inspector["actions"]
    assert inspector["actions"][0]["node_type"] == "business_result"
    assert inspector["actions"][0]["summary"]["result_id"] == artifact["value"]["id"]
    assert {"run_started", "node_finished", "run_finished"} <= {
        event["kind"] for event in inspector["events"]
    }


@pytest.mark.asyncio
async def test_validate_context_refs_drops_foreign(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.platform.workflows.context import TriggerSnapshot, WorkflowContext, WorkflowIdentity
    from src.platform.workflows.context_store import validate_context_refs

    valid = str(uuid4())

    async def fake_ref_exists(section: str, organization_id: UUID, ref_id: str) -> bool:
        return ref_id == valid

    monkeypatch.setattr("src.platform.workflows.context_store._ref_exists", fake_ref_exists)
    context = WorkflowContext(
        identity=WorkflowIdentity(organization_id=uuid4(), workflow_id=uuid4(), run_id=uuid4()),
        trigger=TriggerSnapshot(source="manual"),
    )
    context.evidence_refs = [
        {"value": {"evidence_id": valid}},
        {"value": {"evidence_id": str(uuid4())}},
    ]
    context.claim_refs = [{"value": {"claim_id": str(uuid4())}}]

    dropped = await validate_context_refs(context, uuid4())
    assert dropped == {"evidence_refs": 1, "claim_refs": 1}
    assert len(context.evidence_refs) == 1
    assert context.claim_refs == []


@pytest.mark.asyncio
async def test_run_events_round_trip() -> None:
    from src.platform.workflows.context_store import (
        append_run_event,
        ensure_context_tables,
        list_run_events,
    )

    await ensure_context_tables()
    organization_id = uuid4()
    run_id = uuid4()
    await append_run_event(organization_id, run_id, "run_started", payload={"run_mode": "full"})
    await append_run_event(
        organization_id, run_id, "node_finished", node_id="n1", payload={"status": "succeeded"}
    )
    events = await list_run_events(organization_id, run_id)
    assert [event["kind"] for event in events] == ["run_started", "node_finished"]
    assert events[1]["node_id"] == "n1"
    assert events[0]["payload"] == {"run_mode": "full"}
    assert await list_run_events(uuid4(), run_id) == []


@pytest.mark.asyncio
async def test_partial_run_restores_source_context(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Context Partial")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    graph = _graph(
        [
            _node("t", "trigger_webhook"),
            _node("br", "business_result", {"title": "Resumen parcial", "section": "reports"}),
            _node("n", "notify", {"channel": "in_app", "title": "ok", "message": "ok"}),
        ],
        [_edge("e1", "t", "br"), _edge("e2", "br", "n")],
        ["t"],
    )
    wid = await _create(async_client, org, graph, "Context Partial WF")

    first = await async_client.post(
        f"/api/v1/workflows/{wid}/run", headers=h, json={"payload": {"message": "hola"}}
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["status"] == "succeeded"

    partial = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers={**h, "Idempotency-Key": f"cs-p-{uuid4().hex}"},
        json={
            "payload": {},
            "simulate": True,
            "run_mode": "node",
            "target_node_id": "n",
            "source_run_id": first_body["run_id"],
        },
    )
    assert partial.status_code == 200, partial.text
    partial_body = partial.json()
    assert partial_body["status"] == "simulated", partial_body
    # El contexto del run parcial restaura lo aportado por el run fuente.
    assert partial_body["result"]["context"]["artifacts"], partial_body["result"]["context"]


@pytest.mark.asyncio
async def test_resume_hydrates_context_from_contributions(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Context Resume")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    graph = _graph(
        [
            _node("t", "trigger_webhook"),
            _node("br", "business_result", {"title": "Resumen resume", "section": "reports"}),
        ],
        [_edge("e1", "t", "br")],
        ["t"],
    )
    wid = await _create(async_client, org, graph, "Context Resume WF")

    first = await async_client.post(
        f"/api/v1/workflows/{wid}/run", headers=h, json={"payload": {"message": "hola"}}
    )
    assert first.status_code == 200, first.text
    run_id = first.json()["run_id"]

    from src.platform.workflows.engine import run_workflow

    resumed = await run_workflow(
        UUID(wid),
        {},
        trigger="approval",
        organization_id=UUID(org["organization_id"]),
        actor_type="system",
        resume=True,
        run_id=UUID(run_id),
    )
    assert resumed is not None
    assert resumed["status"] == "succeeded", resumed
    # Los pasos cacheados no re-aplican contribuciones: la hidratación las conserva.
    stored = await load_run_context(UUID(org["organization_id"]), UUID(run_id))
    assert stored is not None
    assert stored["artifacts"], stored
