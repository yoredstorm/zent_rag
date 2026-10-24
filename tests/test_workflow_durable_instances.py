# =============================================================================
# Workflows durables — WorkflowInstance, WAIT como primitiva, signals durables,
# Conversation Router, business state, timeouts, cancelación y portabilidad.
#
# Criterio: un proceso de negocio puede durar días y sobrevivir reinicios sin
# perder contexto; cero procesos esperando en memoria.
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


async def _workflow(client: AsyncClient, org: dict, name: str, graph: dict) -> str:
    created = await client.post(
        "/api/v1/workflows",
        headers=_headers(org),
        json={"name": name, "trigger_type": "webhook", "graph": graph, "workflow_version": 2},
    )
    assert created.status_code == 200, created.text
    return created.json()["workflow_id"]


async def _certify(client: AsyncClient, org: dict, workflow_id: str) -> None:
    response = await client.post(
        f"/api/v1/workflows/{workflow_id}/certifications",
        headers={**_headers(org), "Idempotency-Key": f"cert-{uuid4().hex}"},
        json={"level": "design"},
    )
    assert response.status_code == 200, response.text


def _wait_node(nid: str, config: dict | None = None, **extra) -> dict:
    node = _node(nid, "wait_event", config or {"preset": "message"}, **extra)
    node["output_ports"] = [
        {"name": "out", "type": "json"},
        {"name": "timeout", "type": "json"},
    ]
    return node


def _durable_graph(preset: str = "message", timeout_seconds: int | None = None, on_timeout: str | None = None) -> dict:
    wait_cfg: dict = {"preset": preset}
    if timeout_seconds is not None:
        wait_cfg["timeout_seconds"] = timeout_seconds
    if on_timeout:
        wait_cfg["on_timeout"] = on_timeout
    return _graph(
        nodes=[
            _node("t", "trigger_webhook"),
            _node("n1", "set_variable", {"name": "greeting", "value": "amigo"}),
            _node("n2", "state_append", {"path": "cart.items", "value": {"sku": "ARZ-1"}}),
            _wait_node("w1", wait_cfg),
            _node("n3", "state_set", {"path": "echo", "value": "{{nodes.n1.output.value}}"}),
            _node("end", "end"),
        ],
        edges=[
            _edge("e1", "t", "n1"),
            _edge("e2", "n1", "n2"),
            _edge("e3", "n2", "w1"),
            _edge("e4", "w1", "n3"),
            _edge("e5", "n3", "end"),
        ],
        entrypoints=["t"],
    )


async def _start_instance(
    client: AsyncClient,
    org: dict,
    workflow_id: str,
    *,
    payload: dict | None = None,
    conversation_id: str | None = None,
    business_key: str | None = None,
    expires_in_hours: int | None = None,
) -> dict:
    body: dict = {"payload": payload or {}}
    if conversation_id:
        body["conversation_id"] = conversation_id
    if business_key:
        body["business_key"] = business_key
    if expires_in_hours:
        body["expires_in_hours"] = expires_in_hours
    resp = await client.post(
        f"/api/v1/workflows/{workflow_id}/instances",
        headers={**_headers(org), "Idempotency-Key": f"inst-{uuid4().hex}"},
        json=body,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _instance(client: AsyncClient, org: dict, instance_id: str) -> dict:
    resp = await client.get(
        f"/api/v1/workflows/instances/{instance_id}", headers=_headers(org)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _timeline(client: AsyncClient, org: dict, instance_id: str) -> dict:
    resp = await client.get(
        f"/api/v1/workflows/instances/{instance_id}/timeline", headers=_headers(org)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _signal(
    client: AsyncClient,
    org: dict,
    instance_id: str,
    *,
    event_type: str = "signal.manual",
    correlation: dict | None = None,
    payload: dict | None = None,
    idempotency_key: str | None = None,
) -> dict:
    resp = await client.post(
        f"/api/v1/workflows/instances/{instance_id}/signal",
        headers={**_headers(org), "Idempotency-Key": f"sig-{uuid4().hex}"},
        json={
            "event_type": event_type,
            "correlation": correlation or {},
            "payload": payload or {},
            "idempotency_key": idempotency_key,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# WAIT libera el worker + resume por segmento
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_wait_suspends_and_first_segment_ends(async_client: AsyncClient) -> None:
    org = await _org(async_client, "Durable Wait")
    workflow_id = await _workflow(async_client, org, "Pedido", _durable_graph())

    started = await _start_instance(async_client, org, workflow_id)
    assert started["status"] == "running"
    inst = started["instance"]
    assert inst["status"] == "WAITING"
    assert inst["current_node_id"] == "w1"
    assert inst["waiting_event_type"] == "conversation.message"
    # Estado de negocio ya durable ANTES del wait.
    assert inst["state"]["cart"]["items"] == [{"sku": "ARZ-1"}]
    # El segmento 1 terminó: el run quedó en "waiting" (worker liberado).
    assert started["run"]["status"] == "waiting"


@pytest.mark.asyncio
async def test_resume_after_restart_continues_same_instance(async_client: AsyncClient) -> None:
    """Reinicio lógico: la instancia vive en DB; otra sesión HTTP la reanuda."""
    org = await _org(async_client, "Durable Resume")
    workflow_id = await _workflow(async_client, org, "Pedido", _durable_graph())
    conversation_id = str(uuid4())
    started = await _start_instance(async_client, org, workflow_id, conversation_id=conversation_id)
    instance_id = started["instance_id"]

    # "Reinicio": sesión nueva, cero estado en memoria del proceso anterior.
    org2_session = await _owner_session(async_client, org["organization_id"])
    org["session"] = org2_session
    signal = await _signal(
        async_client,
        org,
        instance_id,
        event_type="conversation.message",
        correlation={"conversation_id": conversation_id},
        payload={"text": "listo"},
    )
    assert signal["status"] == "resumed"
    inst = await _instance(async_client, org, instance_id)
    assert inst["status"] == "COMPLETED"
    # Contexto restaurado: el output del segmento 1 está disponible en el 2.
    assert inst["state"]["echo"] == "amigo"
    # Sin doble efecto: el append sólo ocurrió una vez.
    assert inst["state"]["cart"]["items"] == [{"sku": "ARZ-1"}]
    timeline = await _timeline(async_client, org, instance_id)
    assert len(timeline["runs"]) == 2
    assert timeline["runs"][1]["trigger"] == "signal"
    kinds = [e["kind"] for e in timeline["events"]]
    assert "wait_entered" in kinds and "instance_completed" in kinds
    assert any(s["event_type"] == "conversation.message" for s in timeline["signals"])


@pytest.mark.asyncio
async def test_duplicate_signal_does_not_run_twice(async_client: AsyncClient) -> None:
    org = await _org(async_client, "Durable Dup")
    workflow_id = await _workflow(async_client, org, "Pedido", _durable_graph())
    started = await _start_instance(async_client, org, workflow_id)
    instance_id = started["instance_id"]

    first = await _signal(
        async_client,
        org,
        instance_id,
        event_type="conversation.message",
        idempotency_key="msg-1",
    )
    assert first["status"] == "resumed"
    second = await _signal(
        async_client,
        org,
        instance_id,
        event_type="conversation.message",
        idempotency_key="msg-1",
    )
    assert second["status"] == "duplicate"
    timeline = await _timeline(async_client, org, instance_id)
    assert len(timeline["runs"]) == 2  # sin tercer segmento


@pytest.mark.asyncio
async def test_webhook_before_wait_is_consumed_when_wait_starts(async_client: AsyncClient) -> None:
    """Carrera clásica: la señal llega ANTES de que exista el wait → inbox."""
    from src.platform.workflows.instances import signal_workflow_instance

    org = await _org(async_client, "Durable Race")
    workflow_id = await _workflow(
        async_client,
        org,
        "Pago",
        _graph(
            nodes=[
                _node("t", "trigger_webhook"),
                _wait_node("w1", {"preset": "payment", "correlation": {"payment_reference": "PAY-9"}}),
                _node("end", "end"),
            ],
            edges=[_edge("e1", "t", "w1"), _edge("e2", "w1", "end")],
            entrypoints=["t"],
        ),
    )
    # El signal llega antes de que la instancia llegue al wait.
    queued = await signal_workflow_instance(
        organization_id=UUID(org["organization_id"]),
        event_type="payment.succeeded",
        correlation={"payment_reference": "PAY-9"},
        payload={"amount": 100},
        external_event_id="evt-1",
    )
    assert queued["status"] == "queued"

    started = await _start_instance(async_client, org, workflow_id)
    instance_id = started["instance_id"]
    # El wait consume el signal pendiente al entrar: el proceso ya avanzó.
    inst = await _instance(async_client, org, instance_id)
    assert inst["status"] == "COMPLETED"
    timeline = await _timeline(async_client, org, instance_id)
    assert timeline["signals"][0]["external_event_id"] == "evt-1"
    assert len(timeline["runs"]) == 2


@pytest.mark.asyncio
async def test_repeated_payment_success_is_ignored(async_client: AsyncClient) -> None:
    from src.platform.workflows.instances import signal_workflow_instance

    org = await _org(async_client, "Durable Pay")
    workflow_id = await _workflow(async_client, org, "Pago", _durable_graph(preset="payment"))
    started = await _start_instance(async_client, org, workflow_id)
    instance_id = started["instance_id"]
    inst = await _instance(async_client, org, instance_id)
    assert inst["status"] == "WAITING"

    org_id = UUID(org["organization_id"])
    first = await signal_workflow_instance(
        organization_id=org_id,
        event_type="payment.succeeded",
        correlation={},
        payload={"amount": 10},
        external_event_id="stripe-evt-7",
    )
    assert first["status"] == "resumed"
    second = await signal_workflow_instance(
        organization_id=org_id,
        event_type="payment.succeeded",
        correlation={},
        payload={"amount": 10},
        external_event_id="stripe-evt-7",
    )
    assert second["status"] == "duplicate"
    timeline = await _timeline(async_client, org, instance_id)
    assert len(timeline["runs"]) == 2


@pytest.mark.asyncio
async def test_concurrent_signals_exactly_one_winner(async_client: AsyncClient) -> None:
    from src.platform.workflows.instances import signal_workflow_instance

    org = await _org(async_client, "Durable Race2")
    workflow_id = await _workflow(async_client, org, "Pedido", _durable_graph())
    started = await _start_instance(async_client, org, workflow_id)
    instance_id = started["instance_id"]
    org_id = UUID(org["organization_id"])

    results = await asyncio.gather(
        signal_workflow_instance(
            organization_id=org_id,
            event_type="conversation.message",
            correlation={},
            payload={"text": "a"},
        ),
        signal_workflow_instance(
            organization_id=org_id,
            event_type="conversation.message",
            correlation={},
            payload={"text": "b"},
        ),
    )
    claimed = [r for r in results if r.get("resumed")]
    assert len(claimed) == 1  # exactly one winner
    inst = await _instance(async_client, org, instance_id)
    assert inst["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_cross_tenant_signal_does_not_resume(async_client: AsyncClient) -> None:
    from src.platform.workflows.instances import signal_workflow_instance

    org_a = await _org(async_client, "Durable A")
    org_b = await _org(async_client, "Durable B")
    workflow_id = await _workflow(async_client, org_a, "Pedido", _durable_graph())
    started = await _start_instance(async_client, org_a, workflow_id)

    out = await signal_workflow_instance(
        organization_id=UUID(org_b["organization_id"]),
        event_type="conversation.message",
        correlation={"conversation_id": str(uuid4())},
        payload={"text": "intruso"},
    )
    assert out["status"] == "queued"
    inst = await _instance(async_client, org_a, started["instance_id"])
    assert inst["status"] == "WAITING"  # intacta


@pytest.mark.asyncio
async def test_wrong_conversation_does_not_resume(async_client: AsyncClient) -> None:
    org = await _org(async_client, "Durable WrongConv")
    workflow_id = await _workflow(async_client, org, "Pedido", _durable_graph())
    started = await _start_instance(
        async_client, org, workflow_id, conversation_id=str(uuid4())
    )
    signal = await _signal(
        async_client,
        org,
        started["instance_id"],
        event_type="conversation.message",
        correlation={"conversation_id": str(uuid4())},
        payload={"text": "otra conversación"},
    )
    assert signal["status"] in ("queued", "correlation_mismatch")
    inst = await _instance(async_client, org, started["instance_id"])
    assert inst["status"] == "WAITING"


# ---------------------------------------------------------------------------
# Timeout, expiración, cancelación, suspensión
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_wait_timeout_expires_instance(async_client: AsyncClient) -> None:
    from src.platform.workflows.instances import sweep_waiting_instances

    org = await _org(async_client, "Durable Timeout")
    workflow_id = await _workflow(
        async_client, org, "Pedido", _durable_graph(timeout_seconds=1, on_timeout="expire")
    )
    started = await _start_instance(async_client, org, workflow_id)
    await asyncio.sleep(1.2)
    await sweep_waiting_instances()
    inst = await _instance(async_client, org, started["instance_id"])
    assert inst["status"] == "EXPIRED"
    assert inst["status_reason"] == "wait_timeout"


@pytest.mark.asyncio
async def test_wait_timeout_branch_resumes_timeout_port(async_client: AsyncClient) -> None:
    from src.platform.workflows.instances import sweep_waiting_instances

    org = await _org(async_client, "Durable TimeoutBranch")
    graph = _graph(
        nodes=[
            _node("t", "trigger_webhook"),
            _wait_node("w1", {"preset": "payment", "timeout_seconds": 1}),
            _node("ok", "state_set", {"path": "outcome", "value": "pagado"}),
            _node("late", "state_set", {"path": "outcome", "value": "sin_pago"}),
            _node("end", "end"),
        ],
        edges=[
            _edge("e1", "t", "w1"),
            _edge("e2", "w1", "ok"),
            _edge("e3", "w1", "late", from_port="timeout"),
            _edge("e4", "ok", "end"),
            _edge("e5", "late", "end"),
        ],
        entrypoints=["t"],
    )
    workflow_id = await _workflow(async_client, org, "Pago con timeout", graph)
    started = await _start_instance(async_client, org, workflow_id)
    await asyncio.sleep(1.2)
    await sweep_waiting_instances()
    inst = await _instance(async_client, org, started["instance_id"])
    assert inst["status"] == "COMPLETED"
    assert inst["state"]["outcome"] == "sin_pago"  # rama timeout, no la rama normal


@pytest.mark.asyncio
async def test_instance_expires_at_deadline(async_client: AsyncClient) -> None:
    from src.platform.workflows.instances import sweep_waiting_instances

    org = await _org(async_client, "Durable Expires")
    workflow_id = await _workflow(async_client, org, "Pedido", _durable_graph())
    started = await _start_instance(async_client, org, workflow_id, expires_in_hours=1)
    # Forzar vencimiento para no esperar una hora.
    from sqlalchemy import text as _text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(
            _text(
                "UPDATE workflow_instances SET expires_at = NOW() - INTERVAL '1 minute' "
                "WHERE id = :iid"
            ),
            {"iid": started["instance_id"]},
        )
        await session.commit()
    finally:
        await session.close()
    await sweep_waiting_instances()
    inst = await _instance(async_client, org, started["instance_id"])
    assert inst["status"] == "EXPIRED"
    assert inst["status_reason"] == "expires_at"


@pytest.mark.asyncio
async def test_cancel_waiting_instance(async_client: AsyncClient) -> None:
    org = await _org(async_client, "Durable Cancel")
    workflow_id = await _workflow(async_client, org, "Pedido", _durable_graph())
    started = await _start_instance(async_client, org, workflow_id)
    resp = await async_client.post(
        f"/api/v1/workflows/instances/{started['instance_id']}/cancel",
        headers={**_headers(org), "Idempotency-Key": f"c-{uuid4().hex}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "CANCELLED"
    inst = await _instance(async_client, org, started["instance_id"])
    assert inst["status"] == "CANCELLED"
    # Un signal posterior ya no la despierta.
    signal = await _signal(async_client, org, started["instance_id"])
    assert signal.get("resumed") in (False, None)


@pytest.mark.asyncio
async def test_suspend_and_resume_instance(async_client: AsyncClient) -> None:
    org = await _org(async_client, "Durable Suspend")
    workflow_id = await _workflow(async_client, org, "Pedido", _durable_graph())
    started = await _start_instance(async_client, org, workflow_id)
    iid = started["instance_id"]
    suspended = await async_client.post(
        f"/api/v1/workflows/instances/{iid}/suspend",
        headers={**_headers(org), "Idempotency-Key": f"s-{uuid4().hex}"},
    )
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["status"] == "SUSPENDED"
    resumed = await async_client.post(
        f"/api/v1/workflows/instances/{iid}/resume",
        headers={**_headers(org), "Idempotency-Key": f"r-{uuid4().hex}"},
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "WAITING"


# ---------------------------------------------------------------------------
# Conversation Router
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_conversation_router_resumes_multi_turn(async_client: AsyncClient) -> None:
    from src.platform.workflows.conversation_router import resume_conversation_message

    org = await _org(async_client, "Durable Router")
    workflow_id = await _workflow(async_client, org, "Venta", _durable_graph())
    conversation_id = uuid4()
    started = await _start_instance(
        async_client, org, workflow_id, conversation_id=str(conversation_id)
    )

    routed = await resume_conversation_message(
        organization_id=UUID(org["organization_id"]),
        conversation_id=conversation_id,
        message="prefiero integral",
        user_id=None,
    )
    assert routed is not None
    assert routed["instance_id"] == started["instance_id"]
    assert routed["instance_status"] == "COMPLETED"
    # Segunda pasada: ya no hay proceso vivo en esa conversación.
    again = await resume_conversation_message(
        organization_id=UUID(org["organization_id"]),
        conversation_id=conversation_id,
        message="nada más",
    )
    assert again is None


# ---------------------------------------------------------------------------
# Business state + versionado
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_state_operations_are_durable_and_deterministic(async_client: AsyncClient) -> None:
    org = await _org(async_client, "Durable State")
    graph = _graph(
        nodes=[
            _node("t", "trigger_webhook"),
            _node("s1", "state_set", {"path": "customer", "value": {"name": "Ana"}}),
            _node("s2", "state_merge", {"path": "customer", "value": {"tier": "gold"}}),
            _node("s3", "state_append", {"path": "cart.items", "value": {"sku": "A"}}),
            _node("s4", "state_append", {"path": "cart.items", "value": {"sku": "B"}}),
            _node("s5", "state_remove", {"path": "cart.items", "value": {"sku": "A"}}),
            _wait_node("w1", {"preset": "message"}),
            _node("s6", "state_set", {"path": "order.confirmed", "value": True}),
            _node("end", "end"),
        ],
        edges=[
            _edge("e1", "t", "s1"),
            _edge("e2", "s1", "s2"),
            _edge("e3", "s2", "s3"),
            _edge("e4", "s3", "s4"),
            _edge("e5", "s4", "s5"),
            _edge("e6", "s5", "w1"),
            _edge("e7", "w1", "s6"),
            _edge("e8", "s6", "end"),
        ],
        entrypoints=["t"],
    )
    workflow_id = await _workflow(async_client, org, "Estado", graph)
    started = await _start_instance(async_client, org, workflow_id)
    inst = await _instance(async_client, org, started["instance_id"])
    assert inst["state"]["customer"] == {"name": "Ana", "tier": "gold"}
    assert inst["state"]["cart"]["items"] == [{"sku": "B"}]
    assert inst["status"] == "WAITING"

    await _signal(async_client, org, started["instance_id"], event_type="conversation.message", correlation={})
    # correlación del wait: sin conversation_id declarado el ck es "" → el
    # signal directo sin correlación lo despierta.

    inst = await _instance(async_client, org, started["instance_id"])
    assert inst["status"] == "COMPLETED"
    assert inst["state"]["order"]["confirmed"] is True


@pytest.mark.asyncio
async def test_instance_freezes_workflow_version(async_client: AsyncClient) -> None:
    org = await _org(async_client, "Durable Version")
    workflow_id = await _workflow(async_client, org, "Pedido", _durable_graph())
    started = await _start_instance(async_client, org, workflow_id)
    inst = await _instance(async_client, org, started["instance_id"])
    frozen = inst["definition_snapshot"]["workflow_version"]

    # El workflow cambia (nueva versión publicada) mientras la instancia vive.
    updated = await async_client.patch(
        f"/api/v1/workflows/{workflow_id}",
        headers={**_headers(org), "Idempotency-Key": f"u-{uuid4().hex}"},
        json={
            "graph": _durable_graph(preset="signal"),
            "workflow_version": frozen + 1,
        },
    )
    assert updated.status_code == 200, updated.text

    # La instancia conserva su definición: sigue esperando el mismo evento.
    inst = await _instance(async_client, org, started["instance_id"])
    assert inst["definition_snapshot"]["workflow_version"] == frozen
    assert inst["waiting_event_type"] == "conversation.message"


@pytest.mark.asyncio
async def test_business_key_is_idempotent(async_client: AsyncClient) -> None:
    org = await _org(async_client, "Durable Key")
    workflow_id = await _workflow(async_client, org, "Pedido", _durable_graph())
    first = await _start_instance(async_client, org, workflow_id, business_key="conv-42")
    second = await _start_instance(async_client, org, workflow_id, business_key="conv-42")
    assert second.get("reused") is True
    assert second["instance_id"] == first["instance_id"]


# ---------------------------------------------------------------------------
# Portabilidad (export → inspect → import → bindings → publicar → ejecutar)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_portable_package_export_inspect_import(async_client: AsyncClient) -> None:
    org_a = await _org(async_client, "Portable A")
    org_b = await _org(async_client, "Portable B")
    graph = _graph(
        nodes=[
            _node("t", "trigger_webhook"),
            _node("c1", "capability_call", {"capability": "catalog.products.search", "inputs": {"query": "arroz"}}),
            _wait_node("w1", {"preset": "message"}),
            _node("end", "end"),
        ],
        edges=[_edge("e1", "t", "c1"), _edge("e2", "c1", "w1"), _edge("e3", "w1", "end")],
        entrypoints=["t"],
    )
    workflow_id = await _workflow(async_client, org_a, "Catálogo", graph)

    # Tenant A exporta.
    export = await async_client.get(
        f"/api/v1/workflows/{workflow_id}/export", headers=_headers(org_a)
    )
    assert export.status_code == 200, export.text
    package = export.json()
    assert package["schema"] == "zent.workflow.package/v1"
    assert package["checksum"]
    assert not package["security"]["contains_secrets"]
    assert any(c["ref"] == "catalog.products.search" for c in package["capabilities"])

    # Tenant B inspecciona: la capacidad no está resuelta.
    inspect = await async_client.post(
        "/api/v1/workflows/import/inspect",
        headers={**_headers(org_b), "Idempotency-Key": f"i-{uuid4().hex}"},
        json={"package": package},
    )
    assert inspect.status_code == 200, inspect.text
    report = inspect.json()
    assert report["ready"] is False
    cap_items = [i for i in report["items"] if i["ref"] == "catalog.products.search"]
    assert cap_items and cap_items[0]["status"] in ("MISSING", "NEEDS_CREDENTIALS", "NEEDS_CONFIGURATION")

    # Import bloqueado mientras el requisito siga pendiente.
    blocked = await async_client.post(
        "/api/v1/workflows/import",
        headers={**_headers(org_b), "Idempotency-Key": f"i-{uuid4().hex}"},
        json={"package": package},
    )
    assert blocked.status_code == 409

    # Tenant B resuelve el binding y reintenta.
    binding = await async_client.put(
        "/api/v1/workflows/capability-bindings/catalog.products.search",
        headers={**_headers(org_b), "Idempotency-Key": f"b-{uuid4().hex}"},
        json={
            "provider_kind": "managed_db",
            "config": {"table": "zent_products", "columns": ["sku", "name"], "limit": 5},
        },
    )
    assert binding.status_code == 200, binding.text

    imported = await async_client.post(
        "/api/v1/workflows/import",
        headers={**_headers(org_b), "Idempotency-Key": f"i-{uuid4().hex}"},
        json={"package": package},
    )
    assert imported.status_code == 200, imported.text
    imported_workflow = imported.json()["workflow_id"]
    assert imported.json()["status"] == "draft"

    # Publicar: sin bloqueos tras resolver el binding.
    await _certify(async_client, org_b, imported_workflow)
    published = await async_client.post(
        f"/api/v1/workflows/{imported_workflow}/publish",
        headers={**_headers(org_b), "Idempotency-Key": f"p-{uuid4().hex}"},
        json={},
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "active"


@pytest.mark.asyncio
async def test_import_rejects_package_with_secrets(async_client: AsyncClient) -> None:
    org = await _org(async_client, "Portable Unsafe")
    graph = _durable_graph()
    # Inyectar una credencial prohibida dentro del grafo.
    graph["nodes"][1]["config"]["api_key"] = "sk-live-123"
    package = {
        "schema": "zent.workflow.package/v1",
        "schema_version": 1,
        "package_version": "1.0.0",
        "metadata": {"name": "Sucio"},
        "workflow": {"graph": graph, "trigger_type": "webhook", "trigger_config": {}},
        "dependencies": [],
        "capabilities": [],
        "events": [],
        "parameters": {},
        "permissions": [],
        "tests": [],
    }
    inspect = await async_client.post(
        "/api/v1/workflows/import/inspect",
        headers={**_headers(org), "Idempotency-Key": f"i-{uuid4().hex}"},
        json={"package": package},
    )
    assert inspect.status_code == 200, inspect.text
    report = inspect.json()
    assert report["ready"] is False
    assert any(i["status"] == "UNSAFE" for i in report["items"])


@pytest.mark.asyncio
async def test_durable_run_from_scheduler_sweep_is_idempotent(async_client: AsyncClient) -> None:
    """Doble sweep no dispara dos veces el mismo timeout (wait_seq dedupe)."""
    from src.platform.workflows.instances import sweep_waiting_instances

    org = await _org(async_client, "Durable Sweep")
    workflow_id = await _workflow(
        async_client, org, "Pedido", _durable_graph(timeout_seconds=1, on_timeout="expire")
    )
    started = await _start_instance(async_client, org, workflow_id)
    await asyncio.sleep(1.2)
    first = await sweep_waiting_instances()
    second = await sweep_waiting_instances()
    assert first["waits_timed_out"] >= 1
    assert second["waits_timed_out"] == 0
    inst = await _instance(async_client, org, started["instance_id"])
    assert inst["status"] == "EXPIRED"


@pytest.mark.asyncio
async def test_standing_run_contract_unchanged_without_instance(async_client: AsyncClient) -> None:
    """Un grafo sin WAIT conserva el contrato efímero de siempre."""
    org = await _org(async_client, "Durable Compat")
    graph = _graph(
        nodes=[
            _node("t", "trigger_webhook"),
            _node("n", "notify", {"channel": "in_app", "title": "ok", "message": "ok"}),
            _node("end", "end"),
        ],
        edges=[_edge("e1", "t", "n"), _edge("e2", "n", "end")],
        entrypoints=["t"],
    )
    workflow_id = await _workflow(async_client, org, "Compat", graph)
    resp = await async_client.post(
        f"/api/v1/workflows/{workflow_id}/run",
        headers={**_headers(org), "Idempotency-Key": f"r-{uuid4().hex}"},
        json={"payload": {}, "simulate": False},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "instance_id" not in body
    assert "result" in body and "status" in body


# ---------------------------------------------------------------------------
# Ingress público de señales (webhook) + aprobación durable + retry + reaper
# ---------------------------------------------------------------------------
async def _rotated_secret(async_client: AsyncClient, org: dict, workflow_id: str) -> str:
    resp = await async_client.post(
        f"/api/v1/workflows/{workflow_id}/hook-secret/rotate",
        headers={**_headers(org), "Idempotency-Key": f"sec-{uuid4().hex}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["hook_secret"]


async def _publish(async_client: AsyncClient, org: dict, workflow_id: str) -> None:
    await _certify(async_client, org, workflow_id)
    resp = await async_client.post(
        f"/api/v1/workflows/{workflow_id}/publish",
        headers={**_headers(org), "Idempotency-Key": f"pub-{uuid4().hex}"},
        json={},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_public_signal_hook_authenticates_and_resumes(async_client: AsyncClient) -> None:
    """Proveedores externos empujan señales sin sesión: secret del workflow."""
    org = await _org(async_client, "Durable Webhook")
    workflow_id = await _workflow(async_client, org, "Pedido", _durable_graph())
    secret = await _rotated_secret(async_client, org, workflow_id)
    await _publish(async_client, org, workflow_id)
    started = await _start_instance(async_client, org, workflow_id)

    # Secret inválido → 401 y la instancia intacta.
    bad = await async_client.post(
        f"/api/v1/public/workflows/{workflow_id}/instances/signal",
        headers={"X-Zent-Workflow-Secret": "nope"},
        json={"event_type": "conversation.message", "correlation": {}},
    )
    assert bad.status_code == 401
    inst = await _instance(async_client, org, started["instance_id"])
    assert inst["status"] == "WAITING"

    # Secret válido, sin instance_id: matchea por workflow+evento.
    ok = await async_client.post(
        f"/api/v1/public/workflows/{workflow_id}/instances/signal",
        headers={"X-Zent-Workflow-Secret": secret},
        json={
            "event_type": "conversation.message",
            "correlation": {},
            "payload": {"text": "ya listo"},
            "external_event_id": "wa-msg-1",
        },
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "resumed"
    inst = await _instance(async_client, org, started["instance_id"])
    assert inst["status"] == "COMPLETED"

    # Duplicado del mismo external_event_id → dedupe real.
    dup = await async_client.post(
        f"/api/v1/public/workflows/{workflow_id}/instances/signal",
        headers={"X-Zent-Workflow-Secret": secret},
        json={
            "event_type": "conversation.message",
            "correlation": {},
            "payload": {"text": "ya listo"},
            "external_event_id": "wa-msg-1",
        },
    )
    assert dup.json()["status"] == "duplicate"


@pytest.mark.asyncio
async def test_human_approval_inside_instance_resumes_by_signal(async_client: AsyncClient) -> None:
    org = await _org(async_client, "Durable Approval")
    graph = _graph(
        nodes=[
            _node("t", "trigger_webhook"),
            _node("h1", "human_approval", {"action": "Aprobar pedido", "summary": "Pago verificado"}),
            _node("s1", "state_set", {"path": "order.approved", "value": True}),
            _node("end", "end"),
        ],
        edges=[_edge("e1", "t", "h1"), _edge("e2", "h1", "s1"), _edge("e3", "s1", "end")],
        entrypoints=["t"],
    )
    workflow_id = await _workflow(async_client, org, "Aprobación", graph)
    started = await _start_instance(async_client, org, workflow_id)
    assert started["run"]["status"] == "pending_approval"
    inst = await _instance(async_client, org, started["instance_id"])
    assert inst["status"] == "WAITING"
    assert inst["waiting_event_type"] == "approval.decided"

    run_id = started["run"]["run_id"]
    approvals = await async_client.get(
        f"/api/v1/workflows/runs/{run_id}/approvals", headers=_headers(org)
    )
    assert approvals.status_code == 200, approvals.text
    approval_id = approvals.json()["approvals"][0]["id"]

    decided = await async_client.post(
        f"/api/v1/workflows/runs/{run_id}/approvals/{approval_id}/decide",
        headers={**_headers(org), "Idempotency-Key": f"d-{uuid4().hex}"},
        json={"decision": "approved"},
    )
    assert decided.status_code == 200, decided.text
    body = decided.json()
    assert body["instance_id"] == started["instance_id"]
    inst = await _instance(async_client, org, started["instance_id"])
    assert inst["status"] == "COMPLETED"
    assert inst["state"]["order"]["approved"] is True


@pytest.mark.asyncio
async def test_instance_segment_retries_within_run(async_client: AsyncClient) -> None:
    """Retries por nodo siguen funcionando dentro de un segmento durable."""
    org = await _org(async_client, "Durable Retry")
    graph = _graph(
        nodes=[
            _node("t", "trigger_webhook"),
            _node(
                "n1",
                "llm",
                {"prompt": "x", "fail_once": True},
                retry_policy={"max_attempts": 2},
            ),
            _wait_node("w1", {"preset": "message"}),
            _node("end", "end"),
        ],
        edges=[_edge("e1", "t", "n1"), _edge("e2", "n1", "w1"), _edge("e3", "w1", "end")],
        entrypoints=["t"],
    )
    workflow_id = await _workflow(async_client, org, "Retry", graph)
    started = await _start_instance(async_client, org, workflow_id)
    assert started["status"] == "running"
    run_id = started["run"]["run_id"]
    detail = await async_client.get(
        f"/api/v1/workflows/runs/{run_id}", headers=_headers(org)
    )
    step = next(s for s in detail.json()["steps"] if s["node_id"] == "n1")
    assert step["status"] == "succeeded"
    assert int(step["retries"]) >= 1
    inst = await _instance(async_client, org, started["instance_id"])
    assert inst["status"] == "WAITING"


@pytest.mark.asyncio
async def test_reaper_fails_stale_running_instance(async_client: AsyncClient) -> None:
    from sqlalchemy import text as _text

    from src.infrastructure.postgres.session import get_async_session
    from src.platform.workflows.instances import sweep_waiting_instances

    org = await _org(async_client, "Durable Reaper")
    workflow_id = await _workflow(async_client, org, "Pedido", _durable_graph())
    started = await _start_instance(async_client, org, workflow_id)
    session = await get_async_session()
    try:
        await session.execute(
            _text(
                "UPDATE workflow_instances SET status = 'RUNNING', "
                "updated_at = NOW() - INTERVAL '7 hours' WHERE id = :iid"
            ),
            {"iid": started["instance_id"]},
        )
        await session.commit()
    finally:
        await session.close()
    stats = await sweep_waiting_instances()
    assert stats["instances_reaped"] >= 1
    inst = await _instance(async_client, org, started["instance_id"])
    assert inst["status"] == "FAILED"
    assert inst["status_reason"] == "stale_segment"


# ---------------------------------------------------------------------------
# Generador (plan compiler): wait/state compilan a nodos durables
# ---------------------------------------------------------------------------
def test_plan_compiler_supports_wait_and_state_actions() -> None:
    from src.platform.workflows.intent import PlanAction, PlanTrigger, TriggerKind, WorkflowPlan
    from src.platform.workflows.ir import validate_graph
    from src.platform.workflows.plan_compiler import compile_plan

    plan = WorkflowPlan(
        name="Pedido conversacional",
        description="Toma el pedido por chat, guarda el carrito y espera el pago.",
        trigger=PlanTrigger(kind=TriggerKind.manual),
        actions=[
            PlanAction(kind="state", params={"op": "set", "path": "cart", "value": {"items": []}}),
            PlanAction(
                kind="wait",
                params={"preset": "payment", "timeout_seconds": 3600, "on_timeout": "expire"},
            ),
        ],
        confidence=0.8,
    )
    compiled = compile_plan(plan)
    assert compiled.valid, [i.message for i in compiled.errors]
    types = {n.type for n in compiled.graph.nodes}
    assert "state_set" in types
    assert "wait_event" in types
    validate_graph(compiled.graph)


@pytest.mark.asyncio
async def test_durable_template_installs_and_waits(async_client: AsyncClient) -> None:
    """El template durable de ejemplo corre como proceso vivo end-to-end."""
    org = await _org(async_client, "Durable Template")
    installed = await async_client.post(
        "/api/v1/workflows/templates/pedido_conversacional/install",
        headers={**_headers(org), "Idempotency-Key": f"t-{uuid4().hex}"},
        json={},
    )
    assert installed.status_code == 200, installed.text
    workflow_id = installed.json()["workflow_id"]

    detail = await async_client.get(
        f"/api/v1/workflows/{workflow_id}", headers=_headers(org)
    )
    graph_types = {n.get("type") for n in (detail.json().get("graph") or {}).get("nodes") or []}
    assert "wait_event" in graph_types
    assert "state_append" in graph_types

    conversation_id = str(uuid4())
    started = await _start_instance(
        async_client,
        org,
        workflow_id,
        payload={"text": "quiero un kilo de arroz"},
        conversation_id=conversation_id,
    )
    inst = await _instance(async_client, org, started["instance_id"])
    assert inst["status"] == "WAITING"
    assert inst["waiting_event_type"] == "conversation.message"

    signal = await _signal(
        async_client,
        org,
        started["instance_id"],
        event_type="conversation.message",
        correlation={"conversation_id": conversation_id},
        payload={"text": "nada más"},
    )
    assert signal["status"] == "resumed"
    inst = await _instance(async_client, org, started["instance_id"])
    assert inst["status"] == "COMPLETED"
    assert inst["state"]["order"]["confirmed"] is True
