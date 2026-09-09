# =============================================================================
# Phase 32A — Workflow Graph IR, ejecución DAG, aislamiento, RBAC, dry-run,
# aprobaciones, event triggers y schedules v2.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from tests.test_workflows import _create_org, _headers, _owner_session


# ---------------------------------------------------------------------------
# Helpers de grafo
# ---------------------------------------------------------------------------
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


def _notify_node(nid: str, title: str, message: str = "ok") -> dict:
    return _node(nid, "notify", {"channel": "in_app", "title": title, "message": message})


# ---------------------------------------------------------------------------
# IR / Adapter / Validación
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_legacy_adapter_roundtrip() -> None:
    from src.platform.workflows.ir import LegacyWorkflowAdapter, validate_graph

    steps = [
        {"type": "api_call", "config": {"url": "https://a.example", "method": "GET", "json_path": "q"}},
        {
            "type": "condition",
            "config": {"field": "trigger.stock", "operator": "<", "value": "10"},
            "then": [{"type": "notify", "config": {"channel": "in_app", "title": "bajo", "message": "m"}}],
            "else": [{"type": "notify", "config": {"channel": "in_app", "title": "ok", "message": "m"}}],
        },
        {"type": "notify", "config": {"channel": "in_app", "title": "fin", "message": "x"}},
    ]
    graph = LegacyWorkflowAdapter.steps_to_graph(steps, "webhook", {})
    validate_graph(graph)
    assert graph.entrypoints == ["n0"]
    ids = {n.id for n in graph.nodes}
    assert "n2" in ids and "n3" in ids  # ramas
    # Mapa legacy: pasos top-level son n0, n1, n4
    assert graph.metadata["legacy_index_map"] == {"0": "n0", "1": "n1", "2": "n4"}
    # La referencia steps.0 del paso top-level 2 fue reescrita a nodes.n0
    # (api_call con json_path directo no lleva refs; verificamos en condición).
    cond = next(n for n in graph.nodes if n.type == "condition")
    assert cond.config["field"] == "trigger.stock"


@pytest.mark.asyncio
async def test_validate_cycle_rejected(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "WF Graph Cycle")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    bad = _graph(
        [
            _node("a", "llm", {"prompt": "x"}),
            _node("b", "llm", {"prompt": "y"}),
        ],
        [
            _edge("e1", "a", "b"),
            _edge("e2", "b", "a"),
        ],
        ["a"],
    )
    resp = await async_client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"g-cyc-{uuid4().hex}"},
        json={"name": "Cycle", "graph": bad},
    )
    assert resp.status_code == 400
    assert "ciclo" in resp.text

    ok = _graph(
        [_node("a", "llm", {"prompt": "x"}), _node("b", "llm", {"prompt": "y"})],
        [_edge("e1", "a", "b")],
        ["a"],
    )
    validate = await async_client.post(
        "/api/v1/workflows/validate",
        headers=_headers(org),
        json={"graph": ok},
    )
    assert validate.status_code == 200, validate.text
    assert validate.json()["valid"] is True


# ---------------------------------------------------------------------------
# Ejecución de grafo
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_graph_run_condition_and_join(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "WF Graph Run")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    graph = _graph(
        [
            _node(
                "trigger",
                "trigger_webhook",
                {},
                output_ports=[{"name": "out", "type": "json"}],
            ),
            _node(
                "cond",
                "condition",
                {"field": "trigger.qty", "operator": ">", "value": "5"},
                output_ports=[
                    {"name": "out", "type": "boolean"},
                    {"name": "then", "type": "json"},
                    {"name": "else", "type": "json"},
                ],
            ),
            _node("then", "llm", {"prompt": "alta {{trigger.qty}}"}),
            _node("joina", "join"),
            _node("notif", "notify", {"channel": "in_app", "title": "final", "message": "ok"}),
        ],
        [
            _edge("e1", "trigger", "cond"),
            _edge("e2", "cond", "then", from_port="then"),
            _edge("e3", "then", "joina"),
            _edge("e4", "cond", "joina", from_port="else"),
            _edge("e5", "joina", "notif"),
        ],
        ["trigger"],
    )
    created = await async_client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"g-run-{uuid4().hex}"},
        json={"name": "Graph Run", "trigger_type": "webhook", "graph": graph},
    )
    assert created.status_code == 200, created.text
    wid = created.json()["workflow_id"]
    assert created.json()["workflow_version"] == 2

    result = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers={**_headers(org), "Idempotency-Key": f"g-rr-{uuid4().hex}"},
        json={"payload": {"qty": "9"}},
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["status"] == "succeeded", body
    detail = await async_client.get(f"/api/v1/workflows/runs/{body['run_id']}", headers=h)
    steps = detail.json()["steps"]
    by_node = {s["node_id"]: s for s in steps}
    assert by_node["then"]["status"] == "succeeded"
    assert "alta 9" in by_node["then"]["output"]["text"]
    assert by_node["joina"]["status"] == "succeeded"
    assert by_node["notif"]["status"] == "succeeded"

    # Rama else cuando la condición falla.
    result2 = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers={**_headers(org), "Idempotency-Key": f"g-rr2-{uuid4().hex}"},
        json={"payload": {"qty": "2"}},
    )
    body2 = result2.json()
    assert body2["status"] == "succeeded", body2
    d2 = await async_client.get(f"/api/v1/workflows/runs/{body2['run_id']}", headers=h)
    by2 = {s["node_id"]: s for s in d2.json()["steps"]}
    assert ("then" not in by2) or (by2["then"]["status"] == "skipped")
    assert by2["joina"]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_for_each_bounded_with_join(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "WF ForEach")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    graph = _graph(
        [
            _node(
                "fe",
                "for_each",
                {"collection": "{{trigger.items}}", "max_iterations": 3, "concurrency": 1},
                output_ports=[{"name": "done", "type": "json"}, {"name": "out", "type": "json"}],
                metadata={"_branch": ["item_notify"]},
            ),
            _node(
                "item_notify",
                "notify",
                {"channel": "in_app", "title": "item", "message": "{{nodes.fe.output.items_processed}}"},
                input_ports=[{"name": "in", "type": "json"}],
                metadata={"_branch_of": "fe"},
            ),
            _node("fin", "notify", {"channel": "in_app", "title": "listo", "message": "fin"}),
        ],
        [
            _edge("e1", "fe", "item_notify", from_port="out"),
            _edge("e2", "fe", "fin", from_port="done"),
        ],
        ["fe"],
    )
    created = await async_client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"fe-c-{uuid4().hex}"},
        json={"name": "Loop", "graph": graph},
    )
    wid = created.json()["workflow_id"]
    result = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers={**_headers(org), "Idempotency-Key": f"fe-r-{uuid4().hex}"},
        json={"payload": {"items": ["a", "b", "c", "d"]}},
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["status"] == "succeeded", body
    detail = await async_client.get(f"/api/v1/workflows/runs/{body['run_id']}", headers=h)
    steps = {s["node_id"]: s for s in detail.json()["steps"]}
    assert steps["fe"]["output"]["items_processed"] == 3  # cap max_iterations
    assert steps["fin"]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_dry_run_simulates_side_effects(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "WF Sim Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    created = await async_client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"sim-c-{uuid4().hex}"},
        json={
            "name": "Sim",
            "steps": [
                {"type": "notify", "config": {"channel": "email", "title": "no-enviar", "message": "x"}},
            ],
        },
    )
    wid = created.json()["workflow_id"]

    result = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers={**_headers(org), "Idempotency-Key": f"sim-r-{uuid4().hex}"},
        json={"simulate": True, "payload": {}},
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["status"] == "simulated"
    assert body["simulate"] is True
    assert len(body["planned_effects"]) >= 1

    # Sin simulación real: no se creó la notificación de email.
    detail = await async_client.get(f"/api/v1/workflows/runs/{body['run_id']}", headers=h)
    step = detail.json()["steps"][0]
    assert step["status"] == "simulated"
    assert step["output"].get("simulated") is True

    session = await _get_session()
    try:
        from sqlalchemy import text

        n = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM tenant_notifications "
                    "WHERE organization_id = :oid AND title = 'no-enviar'"
                ),
                {"oid": UUID(org["organization_id"])},
            )
        ).scalar()
        assert int(n) == 0
    finally:
        await session.close()


async def _get_session():
    from src.infrastructure.postgres.session import get_async_session

    return await get_async_session()


# ---------------------------------------------------------------------------
# P0 — aislamiento cross-tenant / cross-workspace
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cross_tenant_run_denied(async_client: AsyncClient) -> None:
    org_a = await _create_org(async_client, "WF Iso A")
    org_b = await _create_org(async_client, "WF Iso B")

    from src.platform.workflows.engine import WorkflowAccessError, create_workflow, run_workflow

    wf = await create_workflow(UUID(org_a["organization_id"]), "Iso A Flow", "webhook", {}, [])
    with pytest.raises(WorkflowAccessError):
        await run_workflow(
            UUID(wf["workflow_id"]),
            {},
            organization_id=UUID(org_b["organization_id"]),
        )


@pytest.mark.asyncio
async def test_workspace_isolation(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "WF Ws Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    # Workspace A (primer default) y B (nuevo).
    sm = await async_client.post(
        "/api/v1/onboarding/start-mode",
        headers=h,
        json={"mode": "blank"},
    )
    assert sm.status_code == 200, sm.text
    ws_a = sm.json()["workspace_id"]
    ws_b = await async_client.post(
        "/api/v1/workspaces",
        headers={**_headers(org), "Idempotency-Key": f"ws-b-{uuid4().hex}"},
        json={"name": "Workspace B"},
    )
    assert ws_b.status_code == 201, ws_b.text
    ws_b_id = ws_b.json()["id"]

    from src.platform.workflows.engine import WorkflowAccessError, create_workflow, list_workflows, run_workflow

    wf_a = await create_workflow(
        UUID(org["organization_id"]), "Ws A Flow", "webhook", {}, [], workspace_id=UUID(ws_a)
    )
    wf_b = await create_workflow(
        UUID(org["organization_id"]), "Ws B Flow", "webhook", {}, [], workspace_id=UUID(ws_b_id)
    )

    listed_a = await list_workflows(UUID(org["organization_id"]), UUID(ws_a))
    ids_a = {w["id"] for w in listed_a["workflows"]}
    assert wf_a["workflow_id"] in ids_a
    assert wf_b["workflow_id"] not in ids_a

    listed_b = await list_workflows(UUID(org["organization_id"]), UUID(ws_b_id))
    ids_b = {w["id"] for w in listed_b["workflows"]}
    assert wf_b["workflow_id"] in ids_b

    # Ejecutar el workflow de A pretendiendo el workspace B → denegado (P0).
    with pytest.raises(WorkflowAccessError):
        await run_workflow(
            UUID(wf_a["workflow_id"]),
            {},
            organization_id=UUID(org["organization_id"]),
            workspace_id=UUID(ws_b_id),
        )


# ---------------------------------------------------------------------------
# Aprobación humana
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_human_approval_flow(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "WF Appr Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    graph = _graph(
        [
            _node("aprov", "human_approval", {"action": "escribir en BD", "summary": "delete client"}),
            _node("fin", "notify", {"channel": "in_app", "title": "aprobado!", "message": "fin"}),
        ],
        [_edge("e1", "aprov", "fin")],
        ["aprov"],
    )
    created = await async_client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"ap-c-{uuid4().hex}"},
        json={"name": "Aprov", "graph": graph},
    )
    wid = created.json()["workflow_id"]

    result = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers={**_headers(org), "Idempotency-Key": f"ap-r-{uuid4().hex}"},
        json={"payload": {}},
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["status"] == "pending_approval", body
    run_id = body["run_id"]

    appr = await async_client.get(f"/api/v1/workflows/runs/{run_id}/approvals", headers=h)
    approvals = appr.json()["approvals"]
    assert len(approvals) == 1
    assert approvals[0]["status"] == "pending"
    approval_id = approvals[0]["id"]

    # Rechazo → run failed.
    rejected = await async_client.post(
        f"/api/v1/workflows/runs/{run_id}/approvals/{approval_id}/decide",
        headers={**_headers(org), "Idempotency-Key": f"ap-d-{uuid4().hex}"},
        json={"decision": "rejected"},
    )
    assert rejected.status_code == 200, rejected.text
    detail = await async_client.get(f"/api/v1/workflows/runs/{run_id}", headers=h)
    assert detail.json()["status"] == "failed"

    # Aprobación → resume del run (nodos previos reutilizados, no re-ejecutados).
    graph2 = _graph(
        [
            _node("llm0", "llm", {"prompt": "pre"}),
            _node("aprov2", "human_approval", {"action": "pago" }),
            _node("fin2", "notify", {"channel": "in_app", "title": "ok-final", "message": "fin"}),
        ],
        [_edge("e1", "llm0", "aprov2"), _edge("e2", "aprov2", "fin2")],
        ["llm0"],
    )
    created2 = await async_client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"ap2-c-{uuid4().hex}"},
        json={"name": "Aprov2", "graph": graph2},
    )
    wid2 = created2.json()["workflow_id"]
    run2 = await async_client.post(
        f"/api/v1/workflows/{wid2}/run",
        headers={**_headers(org), "Idempotency-Key": f"ap2-r-{uuid4().hex}"},
        json={"payload": {}},
    )
    run2_id = run2.json()["run_id"]
    assert run2.json()["status"] == "pending_approval"
    appr2 = (
        await async_client.get(f"/api/v1/workflows/runs/{run2_id}/approvals", headers=h)
    ).json()["approvals"][0]

    approved = await async_client.post(
        f"/api/v1/workflows/runs/{run2_id}/approvals/{appr2['id']}/decide",
        headers={**_headers(org), "Idempotency-Key": f"ap2-d-{uuid4().hex}"},
        json={"decision": "approved"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    detail2 = await async_client.get(f"/api/v1/workflows/runs/{run2_id}", headers=h)
    assert detail2.json()["status"] == "succeeded"
    steps2 = {s["node_id"]: s for s in detail2.json()["steps"]}
    assert steps2["fin2"]["status"] == "succeeded"


# ---------------------------------------------------------------------------
# Event triggers
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_event_trigger_dispatches_workflow(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "WF Evt Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    created = await async_client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"ev-c-{uuid4().hex}"},
        json={
            "name": "En evento",
            "trigger_type": "event",
            "steps": [
                {"type": "notify", "config": {"channel": "in_app", "title": "EVT", "message": "{{trigger.amount}}"}}
            ],
        },
    )
    wid = created.json()["workflow_id"]
    trig = await async_client.post(
        "/api/v1/workflows/triggers",
        headers={**_headers(org), "Idempotency-Key": f"ev-t-{uuid4().hex}"},
        json={"workflow_id": wid, "event_type": "invoice.detected", "filters": {"kind": "cl"}},
    )
    assert trig.status_code == 200, trig.text

    from src.platform.workflows.events import dispatch_event_to_workflows

    fired = await dispatch_event_to_workflows(
        "invoice.detected",
        {
            "organization_id": org["organization_id"],
            "kind": "cl",
            "amount": 1200,
            "_meta": {"ts": "x"},
        },
    )
    assert fired == 1

    # Filtro no empareja → no dispara.
    fired2 = await dispatch_event_to_workflows(
        "invoice.detected",
        {"organization_id": org["organization_id"], "kind": "pe"},
    )
    assert fired2 == 0

    listed = await async_client.get("/api/v1/workflows/triggers", headers=h)
    assert any(t["event_type"] == "invoice.detected" for t in listed.json()["triggers"])


# ---------------------------------------------------------------------------
# Schedules v2
# ---------------------------------------------------------------------------
def test_next_trigger_daily_weekly_cron() -> None:
    from datetime import datetime, timedelta, timezone

    from src.platform.workflows.engine import next_trigger_at

    utc = timezone.utc
    now = datetime(2026, 9, 9, 21, 30, tzinfo=utc)  # miércoles 21:30

    daily = next_trigger_at({"daily": {"time": "18:00", "timezone": "UTC"}}, now)
    assert daily == datetime(2026, 9, 10, 18, 0, tzinfo=utc)
    morning = next_trigger_at({"daily": {"time": "09:00"}}, datetime(2026, 9, 9, 8, 0, tzinfo=utc))
    assert morning == datetime(2026, 9, 9, 9, 0, tzinfo=utc)

    weekly = next_trigger_at({"weekly": {"days": [0], "time": "09:00"}}, now)  # lunes
    assert weekly.weekday() == 0
    assert weekly.hour == 9

    cron = next_trigger_at({"cron": {"expr": "0 6 * * 1"}}, now)  # lunes 06:00
    assert cron.weekday() == 0 and cron.hour == 6

    every = next_trigger_at({"every_minutes": 90}, now)
    assert every == now + timedelta(minutes=90)


@pytest.mark.asyncio
async def test_scheduler_daily_due(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "WF Daily Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])

    created = await async_client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"dl-c-{uuid4().hex}"},
        json={
            "name": "Diario",
            "trigger_type": "schedule",
            "trigger_config": {"daily": {"time": "00:00", "timezone": "UTC"}},
            "steps": [
                {"type": "notify", "config": {"channel": "in_app", "title": "tick", "message": "d"}}
            ],
        },
    )
    wid = created.json()["workflow_id"]
    await async_client.post(f"/api/v1/workflows/{wid}/activate", headers={**_headers(org)})

    from datetime import datetime, timezone

    from src.platform.workflows.engine import run_due_scheduled_workflows

    # Último run a las 23:00 de ayer → la próxima ocurrencia (00:00 hoy) venció.
    session = await _get_session()
    try:
        from sqlalchemy import text

        await session.execute(
            text("UPDATE workflows SET last_run_at = :ts WHERE id = :wid"),
            {"ts": datetime(2026, 9, 8, 23, 0, tzinfo=timezone.utc), "wid": UUID(wid)},
        )
        await session.commit()
    finally:
        await session.close()

    n = await run_due_scheduled_workflows(
        organization_id=UUID(org["organization_id"]),
        now=datetime(2026, 9, 9, 6, 0, tzinfo=timezone.utc),
    )
    assert n >= 1


# ---------------------------------------------------------------------------
# RBAC workflows:*
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_rbac_viewer_cannot_create_workflow(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "WF Rbac Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])

    # Usuario con rol viewer (INSERT directo: create_default_user reutiliza
    # external_id 'default-admin' y pisaría el rol del owner).
    import hashlib as _hl

    from sqlalchemy import text as _txt

    from src.infrastructure.postgres.relational_db import PostgresMembershipRepository, PostgresUserRepository
    from src.infrastructure.postgres.session import get_async_session
    from src.platform.auth.passwords import hash_password

    viewer_email = f"viewer-{uuid4().hex[:8]}@example.com"
    viewer_id = uuid4()
    session = await get_async_session()
    try:
        await session.execute(
            _txt(
                "INSERT INTO users (id, organization_id, external_id, email_hash, "
                "role, email, password_hash) "
                "VALUES (:id, :oid, :ext, :eh, 'member', :email, :ph)"
            ),
            {
                "id": viewer_id,
                "oid": UUID(org["organization_id"]),
                "ext": f"viewer-{uuid4().hex[:12]}",
                "eh": _hl.sha256(viewer_email.encode()).hexdigest(),
                "email": viewer_email,
                "ph": hash_password("secret-123"),
            },
        )
        await session.commit()
    finally:
        await session.close()
    user = await PostgresUserRepository().get_by_email(viewer_email)
    assert user is not None
    await PostgresMembershipRepository().assign_role(
        UUID(org["organization_id"]), user.id, "viewer"
    )

    from src.platform.auth.session import encrypt_session

    view_headers = {
        "Authorization": f"Bearer {encrypt_session(user.id, UUID(org['organization_id']))}",
        "X-Organization-Id": org["organization_id"],
        "Idempotency-Key": f"rb-v-{uuid4().hex}",
    }
    denied = await async_client.post(
        "/api/v1/workflows",
        headers=view_headers,
        json={"name": "Nope", "steps": []},
    )
    assert denied.status_code == 403

    ok = await async_client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"rb-o-{uuid4().hex}"},
        json={"name": "Owner ok", "steps": []},
    )
    assert ok.status_code == 200


# ---------------------------------------------------------------------------
# Resultado estructurado / run inspector
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_run_inspector_fields(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "WF Insp Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    created = await async_client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"in-c-{uuid4().hex}"},
        json={
            "name": "Insp",
            "steps": [
                {"type": "llm", "config": {"prompt": "hola"}},
                {"type": "notify", "config": {"channel": "in_app", "title": "N", "message": "m"}},
            ],
        },
    )
    wid = created.json()["workflow_id"]
    run = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers={**_headers(org), "Idempotency-Key": f"in-r-{uuid4().hex}"},
        json={"payload": {}},
    )
    body = run.json()
    assert body["status"] == "succeeded"
    assert body["correlation_id"].startswith("wf:")
    assert body["result"]["notifications"]  # notify ejecutado
    det = await async_client.get(f"/api/v1/workflows/runs/{body['run_id']}", headers=h)
    step = det.json()["steps"][0]
    assert step["node_type"] == "llm"
    assert step["idempotency_key"].endswith(":n0:0")
